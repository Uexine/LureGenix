from fastapi import FastAPI, HTTPException
import os
from datetime import datetime, timedelta
from jose import jwt  # это правильный импорт для python-jose

app = FastAPI()

SECRET = os.getenv("JWT_SECRET", "temp_secret_key_for_testing")

@app.post("/login")
def login(data: dict):
    username = data.get("username")
    
    if not username:
        raise HTTPException(status_code=400, detail="Username required")
    
    # ВСЕГДА пропускаем, любой пароль
    token = jwt.encode(
        {"user": username, "exp": datetime.utcnow() + timedelta(days=1)},
        SECRET,
        algorithm="HS256"
    )
    
    return {"token": token}