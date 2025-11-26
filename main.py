import uvicorn
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from jose import JWTError, jwt
from datetime import datetime, timedelta, timezone
import pytz
import re

import dream_image
import db_utils

# --- Security and App Setup ---
SECRET_KEY = "a_very_secret_key_for_jwt"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- AI Agent Initialization ---
@app.on_event("startup")
def startup_event():
    google_api_key, _ = dream_image.get_api_keys()
    dream_image.llm = dream_image.setup_llm(google_api_key)
    kb_retriever = dream_image.load_or_create_knowledge_base(
        file_path="DreamDictionary.txt",
        index_path="dream_dictionary_index.faiss",
        api_key=google_api_key
    )
    dream_image.interpretation_chain, dream_image.therapy_chain, dream_image.visual_prompt_chain = dream_image.create_chains(dream_image.llm, kb_retriever)
    db_utils.create_tables()
    print("AI Agent and Database initialized.")

# --- Pydantic Models for API ---
class DreamInput(BaseModel):
    dream_text: str

class TherapyInput(BaseModel):
    question: str
    history: str
    session_id: int

class TherapyStartInput(BaseModel):
    session_id: int

# --- Helper Functions ---
def parse_datetime(date_string):
    if isinstance(date_string, str):
        return datetime.fromisoformat(date_string)
    return date_string

def markdown_to_html(text):
    if not text: return ""
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'^\* (.*)', r'<li>\1</li>', text, flags=re.MULTILINE)
    text = re.sub(r'((\r\n|\n)?<li>.*</li>)+', r'<ul>\g<0></ul>', text, flags=re.DOTALL)
    return text.replace('\n', '<br>')

def process_messages_for_template(messages):
    processed = []
    for msg in messages:
        msg_dict = dict(msg)
        msg_dict['text'] = markdown_to_html(msg_dict.get('text'))
        processed.append(msg_dict)
    return processed

def _get_enriched_sessions(user_id: int):
    """Fetches and processes all chat sessions for a user."""
    chat_sessions = db_utils.get_user_chat_sessions(user_id)
    enriched_sessions = []
    ist_timezone = pytz.timezone("Asia/Kolkata")
    
    for session in chat_sessions:
        parsed_date_utc = parse_datetime(session['created_at'])
        if parsed_date_utc.tzinfo is None:
            parsed_date_utc = pytz.utc.localize(parsed_date_utc)
        
        parsed_date_ist = parsed_date_utc.astimezone(ist_timezone)
        
        enriched_sessions.append({
            "id": session['id'], 
            "created_at": parsed_date_ist
        })
    return enriched_sessions

# --- JWT Token and User Authentication ---
def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token: return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        user_id: int = payload.get("id")
        if email is None or user_id is None: return None
        return {"email": email, "id": user_id}
    except JWTError:
        return None

# --- Web Page Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, current_user: dict = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    user_id = current_user["id"]
    enriched_sessions = _get_enriched_sessions(user_id)

    return templates.TemplateResponse("home.html", {
        "request": request, 
        "chat_sessions": enriched_sessions, 
        "selected_session": None, 
        "selected_session_messages": None, 
        "session_state": "initial_dream"
    })

@app.get("/chat/{session_id}", response_class=HTMLResponse)
async def read_chat_session(request: Request, session_id: int, current_user: dict = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        
    user_id = current_user["id"]
    if not db_utils.is_user_session(user_id, session_id):
        raise HTTPException(status_code=403, detail="Forbidden: You do not have access to this chat session.")

    enriched_sessions = _get_enriched_sessions(user_id)
    selected_session_messages = db_utils.get_messages_for_session(session_id)
    
    session_state = "session_ended" # Default to a safe state
    if selected_session_messages:
        last_bot_message = next((msg for msg in reversed(selected_session_messages) if msg['sender'] == 'bot' and msg['text']), None)
        if last_bot_message:
            last_message_text = last_bot_message['text']
            if "Would you like to ask some follow-up questions" in last_message_text:
                session_state = "awaiting_therapy_start"
            elif "Great. What is your first question?" in last_message_text or "Sorry, an error occurred" not in last_message_text:
                 session_state = "in_therapy_session"
    
    selected_session = next((s for s in enriched_sessions if s['id'] == session_id), None)
    processed_selected_messages = process_messages_for_template(selected_session_messages)

    return templates.TemplateResponse("home.html", {
        "request": request, 
        "chat_sessions": enriched_sessions, 
        "selected_session": selected_session, 
        "selected_session_messages": processed_selected_messages,
        "session_state": session_state
    })

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, message: str = None):
    return templates.TemplateResponse("login.html", {"request": request, "message": message})

@app.post("/login")
async def login_user(request: Request, email: str = Form(...), password: str = Form(...)):
    user = db_utils.check_user(email, password)
    if user:
        access_token = create_access_token(data={"sub": user["email"], "id": user["id"]})
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(key="access_token", value=access_token, httponly=True)
        return response
    else:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid email or password."})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register")
async def register_user(request: Request, email: str = Form(...), password: str = Form(...)):
    new_user_id = db_utils.add_user(email, password)
    if new_user_id:
        return RedirectResponse(url=f"/demographics?user_id={new_user_id}", status_code=status.HTTP_303_SEE_OTHER)
    else:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Email already exists."})

@app.get("/demographics", response_class=HTMLResponse)
async def demographics_page(request: Request, user_id: int):
    return templates.TemplateResponse("demographics.html", {"request": request, "user_id": user_id})

@app.post("/submit_demographics")
async def submit_demographics(
    request: Request, 
    user_id: int = Form(...),
    age_range: str = Form(...),
    gender: str = Form(...),
    country: str = Form(...),
    life_stage: str = Form(...)
):
    db_utils.add_demographics(user_id, age_range, gender, country, life_stage)
    return RedirectResponse(url="/login?message=Registration+complete.+Please+log+in.", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
async def logout_user(request: Request):
    response = templates.TemplateResponse("logout.html", {"request": request})
    response.delete_cookie(key="access_token")
    return response

@app.post("/delete_chat/{session_id}")
async def delete_chat(session_id: int, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    user_id = current_user["id"]
    if not db_utils.is_user_session(user_id, session_id):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    db_utils.delete_chat_session(session_id)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

# --- API Routes for Chat Logic ---
@app.post("/submit_message")
async def submit_message(dream_input: DreamInput, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_id = current_user["id"]
    session_id = db_utils.create_chat_session(user_id)
    db_utils.add_message_to_session(session_id, 'user', text=dream_input.dream_text)
    
    try:
        demographics_dict = db_utils.get_user_demographics(user_id)
        if demographics_dict:
            demographics_str = (
                f"Age Range: {demographics_dict.get('age_range', 'N/A')}, "
                f"Gender: {demographics_dict.get('gender', 'N/A')}, "
                f"Country/Cultural Background: {demographics_dict.get('country', 'N/A')}, "
                f"Life Stage: {demographics_dict.get('life_stage', 'N/A')}"
            )
        else:
            demographics_str = "No demographic information provided."

        interpretation = dream_image.interpretation_chain.invoke({
            "dream_text": dream_input.dream_text,
            "demographics": demographics_str
        })
        
        visual_prompt = dream_image.visual_prompt_chain.invoke({"interpretation": interpretation})
        image_url = dream_image.generate_dream_image_data(visual_prompt)
        
        if not image_url:
            image_url = f"https://placehold.co/512x512/000000/bbff00?text=Image+Gen+Failed"

        db_utils.add_message_to_session(session_id, 'bot', image_data=image_url)
        db_utils.add_message_to_session(session_id, 'bot', text=interpretation)
        follow_up_prompt = "Would you like to ask some follow-up questions about this interpretation?"
        db_utils.add_message_to_session(session_id, 'bot', text=follow_up_prompt)
        
        return {"session_id": session_id}
    except Exception as e:
        error_message = f"Sorry, an error occurred during AI processing: {e}"
        db_utils.add_message_to_session(session_id, 'bot', text=error_message)
        return JSONResponse(status_code=500, content={"error": error_message, "session_id": session_id})

@app.post("/start_therapy")
async def start_therapy(therapy_start_input: TherapyStartInput, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session_id = therapy_start_input.session_id
    user_id = current_user["id"]
    if not db_utils.is_user_session(user_id, session_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    db_utils.add_message_to_session(session_id, 'user', text="Yes")
    
    bot_response_text = "Great. What is your first question?"
    bot_message = db_utils.add_message_to_session(session_id, 'bot', text=bot_response_text)
    return {"bot_message": {"text": markdown_to_html(bot_message['text']), "sender": "bot"}}

@app.post("/therapy")
async def therapy_follow_up(therapy_input: TherapyInput, current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    session_id = therapy_input.session_id
    user_id = current_user["id"]
    if not db_utils.is_user_session(user_id, session_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    db_utils.add_message_to_session(session_id, 'user', text=therapy_input.question)

    try:
        messages = db_utils.get_messages_for_session(session_id)
        history = "\n".join([f"{'User' if msg['sender'] == 'user' else 'AI'}: {msg['text']}" for msg in messages if msg.get('text')])

        answer = dream_image.therapy_chain.invoke({"question": therapy_input.question, "history": history})
        formatted_answer = markdown_to_html(answer)
        db_utils.add_message_to_session(session_id, 'bot', text=answer)
        return {"answer": formatted_answer}
    except Exception as e:
        error_message = f"Sorry, an error occurred during the therapy session: {e}"
        db_utils.add_message_to_session(session_id, 'bot', text=error_message)
        return JSONResponse(status_code=500, content={"error": error_message})

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)