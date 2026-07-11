from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, HTTPException
import os
import json
import random
from dotenv import load_dotenv
from supabase import create_client
from google import genai
from pydantic import BaseModel
from typing import List
import random
import string

def generate_join_code():
    # Generates a 6-character alphanumeric code (e.g., "X7K9M2")
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# 1. Load Environment Variables
load_dotenv()

# 2. Start the Server
app = FastAPI(title="Edu-Insight AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Connect Supabase
supabase_url = "https://pyxweopjmuhodbgfecvy.supabase.co"
supabase_key = "sb_publishable_rKElQBQyLCnjkoQtlqhTPg_7Nr-vQ-7"
supabase = create_client(supabase_url, supabase_key)

# 4. Connect Gemini (FIXED: Using the new SDK syntax and securely grabbing the key)
# DO NOT PASTE YOUR REAL KEY HERE! Your system/Render will provide it.
api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

# 5. Define Models
class TestRequest(BaseModel):
    subject: str
    grade: str
    topic: str
    num_questions: int = 10
    difficulty: str = "Medium"
    start_time: str
    end_time: str

class Question(BaseModel):
    question: str
    options: List[str]
    answer: str
    explanation: str

class QuizResponse(BaseModel):
    questions: List[Question]
    quiz_id: str 

class QuizSubmission(BaseModel):
    quiz_id: str  # <-- Change this from int to str
    student_name: str
    score: int
    total_questions: int
    student_answers: dict

class TeacherQuery(BaseModel):
    quiz_id: int
    question: str

# 6. Basic Routes
@app.get("/")
def home():
    return {"message": "Edu-Insight AI Server is Running! 🚀"}

# 7. Core Quiz Generator Route
@app.post("/generate-quiz", response_model=QuizResponse)
def generate_quiz(request: TestRequest):
    prompt = f"""
    Create a {request.num_questions}-question multiple choice quiz for CBSE Grade {request.grade} {request.subject} on the topic: {request.topic}. 
    The difficulty level MUST be: {request.difficulty}.

    STRICT RULES:
    1. SHUFFLE the options! Do NOT always put the correct answer as the first option.
    2. The 'answer' field MUST exactly match one of the strings in the 'options' list.
    3. Respond STRICTLY in this exact JSON format:
    {{
        "questions": [
            {{
                "question": "Question text?",
                "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
                "answer": "Correct Option String",
                "explanation": "Why it is correct"
            }}
        ]
    }}
    """
    
    try:
        # 1. Ask Gemini for the Quiz
        response = client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=prompt
        )
        
        # 2. Clean and Parse the JSON
        clean_text = response.text.strip().replace("```json", "").replace("```", "")
        structured_data = json.loads(clean_text)

        # 3. Shuffle Options Manually (Extra Safety)
        for q in structured_data["questions"]:
            ans_text = q["answer"]
            random.shuffle(q["options"])
            q["answer"] = ans_text
                
        # 4. Generate the new 6-Character Join Code
        quiz_id = generate_join_code()
        
        # 5. Prepare Database Payload with the String ID
        db_data = {
            "id": quiz_id,
            "subject": request.subject,
            "grade": request.grade,
            "topic": request.topic,
            "difficulty": request.difficulty,
            "start_time": request.start_time, 
            "end_time": request.end_time,
            "quiz_data": structured_data
        }
        
        # 6. Insert into Supabase
        supabase.table("quizzes").insert(db_data).execute()
                
        # 7. Return the expected payload to the Frontend
        return {
            "quiz_id": quiz_id,
            "questions": structured_data["questions"]
        }

    except Exception as e:
        print(f"Server Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
# 8. Fetch Saved Quizzes List
@app.get("/quizzes")
def get_quizzes():
    response = supabase.table("quizzes").select("id, subject, grade, topic, difficulty").execute()
    return {"history": response.data}

# 9. Student Submission
@app.post("/submit-quiz")
def submit_quiz(submission: QuizSubmission):
    try:
        data = {
            "quiz_id": submission.quiz_id,
            "student_name": submission.student_name,
            "score": submission.score,
            "total_questions": submission.total_questions,
            "student_answers": submission.student_answers
        }
        supabase.table("quiz_results").insert(data).execute()
        return {"message": "Results saved!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# 10. Fetch Single Quiz for Student
@app.get("/quiz/{quiz_id}")
def get_single_quiz(quiz_id: str):
    response = supabase.table("quizzes").select("*").eq("id", quiz_id).execute()
    if response.data:
        return response.data[0]
    raise HTTPException(status_code=404, detail="Quiz not found")

# 11. AI Analytics for Teacher Dashboard
@app.post("/analyze-results")
def analyze_results(query: TeacherQuery):
    quiz = supabase.table("quizzes").select("*").eq("id", query.quiz_id).execute()
    results = supabase.table("quiz_results").select("*").eq("quiz_id", query.quiz_id).execute()
    
    data_context = f"Quiz: {quiz.data} | Results: {results.data}"
    
    ai_prompt = f"""
    Analyze this educational data: {data_context}
    Question: {query.question}
    Rules: Be short (1-3 sentences), mention student names and scores, and identify specific topics to reteach.
    """
    
    response = client.models.generate_content(model='gemini-2.5-flash', contents=ai_prompt)
    return {"ai_analysis": response.text}

# 12. Fetch Raw Data for Dashboard Charts
@app.get("/quiz-results/{quiz_id}")
def get_quiz_results(quiz_id: str):
    quiz = supabase.table("quizzes").select("*").eq("id", quiz_id).execute()
    results = supabase.table("quiz_results").select("*").eq("quiz_id", quiz_id).execute()
    return {
        "quiz": quiz.data[0] if quiz.data else None, 
        "results": results.data
    }

# 13. Delete Quiz Route
@app.delete("/delete-quiz/{quiz_id}")
def delete_quiz(quiz_id: str):
    try:
        supabase.table("quiz_results").delete().eq("quiz_id", quiz_id).execute()
        supabase.table("quizzes").delete().eq("id", quiz_id).execute()
        return {"message": "Deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 14. Update Quiz Content (For Teacher Edits)
@app.put("/update-quiz/{quiz_id}")
def update_quiz(quiz_id: int, payload: dict):
    try:
        response = supabase.table("quizzes").update({"quiz_data": payload}).eq("id", quiz_id).execute()
        if not response.data:
            return {"error": "Quiz not found in database"}
        return {"message": "Saved to Cloud! ✅"}
    except Exception as e:
        print(f"Error updating: {e}")
        raise HTTPException(status_code=500, detail=str(e))
