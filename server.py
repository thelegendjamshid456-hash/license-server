from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import secrets
from datetime import datetime, timedelta
import os
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store keys in memory
keys_db = {}

@app.post("/api/validate")
async def validate_key(data: dict):
    license_key = data.get("license_key", "")
    device_id = data.get("device_id", "")
    
    print(f"🔍 MVP APK checking: {license_key}")
    
    # Check if key exists (for testing, we'll accept any key)
    # In production, you'd check against your database
    if not license_key:
        return {"status": "error", "message": "No key provided"}
    
    # FOR MVP APK - Return EXACT format they expect
    return {
        "status": "success",
        "data": {
            "auth_token": secrets.token_hex(16),
            "expiry_date": (datetime.now() + timedelta(days=30)).isoformat(),
            "version": "1.0",
            "license_key": license_key,
            "max_devices": 3,
            "active_devices": 1
        }
    }

@app.post("/api/admin/create_key")
async def create_key(data: dict):
    days = data.get("days", 30)
    max_devices = data.get("max_devices", 3)
    
    # Generate key like: A1B2-C3D4-E5F6-G7H8
    key = ''
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    for i in range(16):
        key += chars[secrets.randbelow(len(chars))]
        if (i + 1) % 4 == 0 and i < 15:
            key += '-'
    
    expires = datetime.now() + timedelta(days=days)
    
    keys_db[key] = {
        'expires': expires,
        'max_devices': max_devices,
        'devices': []
    }
    
    # Return in the format your admin panel expects
    return {
        "key": key,
        "expires": expires.isoformat(),
        "max_devices": max_devices
    }

@app.get("/")
async def root():
    return {"message": "MVP License Server Running", "status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)