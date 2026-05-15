from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from groq import Groq
import psycopg2
from psycopg2.extras import RealDictCursor
import hashlib
import uuid

app = FastAPI(title="SafeGuard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = "postgresql://postgres:CjgXWwGRWOTzPBrQZpjwfxEKSaXEUUrU@yamanote.proxy.rlwy.net:56044/railway"

def get_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require', cursor_factory=RealDictCursor)
    return conn

def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS parents (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100),
                email VARCHAR(100) UNIQUE,
                password VARCHAR(200),
                token VARCHAR(200)
            );
            CREATE TABLE IF NOT EXISTS children (
                id SERIAL PRIMARY KEY,
                parent_id INTEGER REFERENCES parents(id),
                name VARCHAR(100),
                age INTEGER
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB init error: {e}")

init_db()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
client = None
if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)

class ParentRegister(BaseModel):
    name: str
    email: str
    password: str

class ParentLogin(BaseModel):
    email: str
    password: str

class AddChild(BaseModel):
    parent_token: str
    child_name: str
    child_age: int

class VideoCheck(BaseModel):
    video_title: str
    video_description: str
    child_age: int

@app.get("/")
def home():
    return {"status": "API running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/parent/register")
def register_parent(data: ParentRegister):
    conn = get_db()
    cur = conn.cursor()
    hashed = hashlib.sha256(data.password.encode()).hexdigest()
    token = str(uuid.uuid4())
    try:
        cur.execute(
            "INSERT INTO parents (name, email, password, token) VALUES (%s, %s, %s, %s) RETURNING id",
            (data.name, data.email, hashed, token)
        )
        parent_id = cur.fetchone()["id"]
        conn.commit()
        return {"message": "registered", "parent_id": parent_id, "token": token}
    except Exception:
        raise HTTPException(status_code=400, detail="Email already exists")
    finally:
        cur.close()
        conn.close()

@app.post("/parent/login")
def login_parent(data: ParentLogin):
    conn = get_db()
    cur = conn.cursor()
    hashed = hashlib.sha256(data.password.encode()).hexdigest()
    cur.execute("SELECT * FROM parents WHERE email=%s AND password=%s", (data.email, hashed))
    parent = cur.fetchone()
    cur.close()
    conn.close()
    if not parent:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return {"message": "login successful", "token": parent["token"], "name": parent["name"]}

@app.post("/parent/add-child")
def add_child(data: AddChild):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM parents WHERE token=%s", (data.parent_token,))
    parent = cur.fetchone()
    if not parent:
        raise HTTPException(status_code=401, detail="Invalid token")
    cur.execute(
        "INSERT INTO children (parent_id, name, age) VALUES (%s, %s, %s) RETURNING id",
        (parent["id"], data.child_name, data.child_age)
    )
    child_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "child added", "child_id": child_id}

@app.get("/parent/children/{token}")
def get_children(token: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM parents WHERE token=%s", (token,))
    parent = cur.fetchone()
    if not parent:
        raise HTTPException(status_code=401, detail="Invalid token")
    cur.execute("SELECT * FROM children WHERE parent_id=%s", (parent["id"],))
    children = cur.fetchall()
    cur.close()
    conn.close()
    return {"children": children}

@app.post("/video/check")
def check_video(data: VideoCheck):
    if not client:
        raise HTTPException(status_code=500, detail="AI not configured")
    
    prompt = f"""You are a parental control AI. 
A child aged {data.child_age} wants to watch:
Title: {data.video_title}
Description: {data.video_description}

Is this video safe for this age? Reply in this exact format:
SAFE: yes or no
REASON: one sentence explanation
WARNING: any specific concerns or 'none'"""

    response = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200
    )
    
    result = response.choices[0].message.content
    is_safe = "SAFE: yes" in result.lower()
    
    return {
        "is_safe": is_safe,
        "age": data.child_age,
        "video_title": data.video_title,
        "ai_response": result
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)