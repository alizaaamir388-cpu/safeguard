from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from groq import Groq

app = FastAPI(title="SafeGuard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Safe Groq init
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

client = None
if GROQ_API_KEY:
    client = Groq(api_key=GROQ_API_KEY)

# In-memory storage
parents_db = {}
children_db = {}
activity_db = {}
sessions_db = {}

# Models
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

# Root route (important for 502 fix)
@app.get("/")
def home():
    return {"status": "API running"}

# Health check
@app.get("/health")
def health():
    return {"status": "ok"}

# Register parent
@app.post("/parent/register")
def register_parent(data: ParentRegister):
    parent_id = str(len(parents_db) + 1)

    parents_db[parent_id] = {
        "name": data.name,
        "email": data.email,
        "password": data.password,
        "children": []
    }

    return {"message": "registered", "parent_id": parent_id}


# ✅ IMPORTANT FIX ADDED HERE
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)