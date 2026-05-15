from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import json, re
from datetime import datetime
import uuid

app = FastAPI(title="SafeGuard - AI Parental Control System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Replace with your Groq API Key ──
import os
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
client = Groq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────
# In-Memory Database
# ─────────────────────────────────────────
parents_db = {}   # { parent_id: { name, email, password, children: [...] } }
children_db = {}  # { child_id: { name, age, parent_id } }
activity_db = {}  # { child_id: [ {video, result, timestamp} ] }
sessions_db = {}  # { token: { user_id, role } }

# ─────────────────────────────────────────
# Models
# ─────────────────────────────────────────

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

class ChildLogin(BaseModel):
    child_id: str
    parent_email: str

class CheckContent(BaseModel):
    child_token: str
    video_title: str
    video_description: str = ""

# ─────────────────────────────────────────
# AI Agent
# ─────────────────────────────────────────

def ai_check_content(video_title: str, video_description: str, child_age: int) -> dict:
    system_prompt = """You are a Child Safety AI Agent. Analyze if a video is safe for a child.
Respond ONLY with valid JSON, no extra text:
{
  "is_safe": true or false,
  "risk_level": "SAFE" or "LOW" or "MEDIUM" or "HIGH",
  "reason": "brief explanation",
  "flagged_keywords": ["word1", "word2"]
}
Rules:
- Under 10: very strict. Block violence, romance, horror, strong language, adult themes.
- 10-13: moderate. Allow mild action, block sexual content, gore, drugs.
- 14-17: lenient. Block only explicit sexual content and extreme gore.
- flagged_keywords: list concerning words (empty list if none)"""

    user_msg = f"""Child age: {child_age}
Video Title: {video_title}
Description: {video_description}
Is this safe? JSON only."""

    resp = client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg}
        ],
        temperature=0.1,
        max_tokens=300
    )
    raw = re.sub(r"```json|```", "", resp.choices[0].message.content.strip()).strip()
    return json.loads(raw)

# ─────────────────────────────────────────
# Parent Routes
# ─────────────────────────────────────────

@app.post("/parent/register")
def parent_register(data: ParentRegister):
    for p in parents_db.values():
        if p["email"] == data.email:
            raise HTTPException(400, "Email already registered.")
    pid = str(uuid.uuid4())
    parents_db[pid] = {
        "id": pid,
        "name": data.name,
        "email": data.email,
        "password": data.password,
        "children": []
    }
    return {"message": "Parent registered successfully!", "parent_id": pid}


@app.post("/parent/login")
def parent_login(data: ParentLogin):
    for pid, p in parents_db.items():
        if p["email"] == data.email and p["password"] == data.password:
            token = str(uuid.uuid4())
            sessions_db[token] = {"user_id": pid, "role": "parent"}
            return {"token": token, "name": p["name"], "parent_id": pid}
    raise HTTPException(401, "Invalid email or password.")


@app.post("/parent/add-child")
def add_child(data: AddChild):
    if data.parent_token not in sessions_db:
        raise HTTPException(401, "Invalid session. Please login again.")
    session = sessions_db[data.parent_token]
    if session["role"] != "parent":
        raise HTTPException(403, "Only parents can add children.")
    if not (1 <= data.child_age <= 17):
        raise HTTPException(400, "Child age must be between 1 and 17.")

    parent_id = session["user_id"]
    child_id = str(uuid.uuid4())[:8]  # short ID for easy child login
    children_db[child_id] = {
        "id": child_id,
        "name": data.child_name,
        "age": data.child_age,
        "parent_id": parent_id
    }
    activity_db[child_id] = []
    parents_db[parent_id]["children"].append(child_id)
    return {"message": f"Child '{data.child_name}' added!", "child_id": child_id}


@app.get("/parent/children/{token}")
def get_children(token: str):
    if token not in sessions_db:
        raise HTTPException(401, "Invalid session.")
    parent_id = sessions_db[token]["user_id"]
    parent = parents_db[parent_id]
    children = []
    for cid in parent["children"]:
        if cid in children_db:
            child = children_db[cid].copy()
            child["activity_count"] = len(activity_db.get(cid, []))
            child["blocked_count"] = len([a for a in activity_db.get(cid, []) if not a["is_safe"]])
            children.append(child)
    return {"children": children, "parent_name": parent["name"]}


@app.get("/parent/activity/{token}/{child_id}")
def get_child_activity(token: str, child_id: str):
    if token not in sessions_db:
        raise HTTPException(401, "Invalid session.")
    return {"activity": list(reversed(activity_db.get(child_id, [])))}

# ─────────────────────────────────────────
# Child Routes
# ─────────────────────────────────────────

@app.post("/child/login")
def child_login(data: ChildLogin):
    if data.child_id not in children_db:
        raise HTTPException(404, "Child profile not found.")
    child = children_db[data.child_id]
    parent = parents_db.get(child["parent_id"])
    if not parent or parent["email"] != data.parent_email:
        raise HTTPException(401, "Wrong parent email.")
    token = str(uuid.uuid4())
    sessions_db[token] = {"user_id": data.child_id, "role": "child"}
    return {"token": token, "name": child["name"], "age": child["age"], "child_id": data.child_id}


@app.post("/child/check-content")
def check_content(data: CheckContent):
    if data.child_token not in sessions_db:
        raise HTTPException(401, "Invalid session.")
    session = sessions_db[data.child_token]
    if session["role"] != "child":
        raise HTTPException(403, "Only children can check content.")

    child_id = session["user_id"]
    child = children_db[child_id]

    try:
        result = ai_check_content(data.video_title, data.video_description, child["age"])
    except Exception as e:
        raise HTTPException(500, f"AI Agent error: {str(e)}")

    record = {
        "video_title": data.video_title,
        "is_safe": result.get("is_safe", False),
        "risk_level": result.get("risk_level", "HIGH"),
        "reason": result.get("reason", ""),
        "flagged_keywords": result.get("flagged_keywords", []),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    activity_db[child_id].append(record)

    return record


@app.get("/")
def root():
    return {"message": "SafeGuard AI Parental Control System is running!"}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))