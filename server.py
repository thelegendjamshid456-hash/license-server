from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import secrets
from datetime import datetime, timedelta
import os
import json
import logging

app = FastAPI()

# Set up detailed logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store keys in memory
keys_db = {}

@app.middleware("http")
async def log_all_requests(request: Request, call_next):
    """Log EVERY single request with full details"""
    body = await request.body()
    logger.info("="*60)
    logger.info(f"🔥 NEW REQUEST DETECTED!")
    logger.info(f"📌 Full URL: {request.url}")
    logger.info(f"📌 Path: {request.url.path}")
    logger.info(f"📌 Method: {request.method}")
    logger.info(f"📌 Headers: {dict(request.headers)}")
    logger.info(f"📌 Query Params: {dict(request.query_params)}")
    logger.info(f"📌 Body: {body.decode('utf-8', errors='ignore')}")
    logger.info("="*60)
    
    response = await call_next(request)
    return response

@app.post("/api/validate")
async def validate_key(request: Request):
    """Log the raw request first"""
    body = await request.body()
    logger.info(f"🔍 VALIDATE ENDPOINT HIT")
    logger.info(f"📦 Raw body: {body.decode('utf-8', errors='ignore')}")
    
    # Try to parse as JSON
    try:
        data = json.loads(body)
        logger.info(f"📦 Parsed JSON: {data}")
        
        license_key = data.get("license_key", "")
        device_id = data.get("device_id", "")
        
        logger.info(f"🔑 License Key: {license_key}")
        logger.info(f"📱 Device ID: {device_id}")
        
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
    except Exception as e:
        logger.error(f"❌ Error parsing request: {e}")
        return {"status": "error", "message": "Invalid request"}

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

@app.post("/api/verify")
async def verify(request: Request):
    """Catch any other verify endpoints"""
    body = await request.body()
    logger.info(f"🔍 VERIFY endpoint hit: {body.decode('utf-8', errors='ignore')}")
    return {"status": "valid"}

@app.post("/api/license")
async def license(request: Request):
    """Catch license endpoints"""
    body = await request.body()
    logger.info(f"🔍 LICENSE endpoint hit: {body.decode('utf-8', errors='ignore')}")
    return {"status": "valid"}

@app.get("/api/config")
async def config():
    logger.info("🔍 CONFIG endpoint hit")
    return {"config": {}}

@app.get("/")
async def root():
    logger.info("🔍 ROOT endpoint hit")
    return {"message": "MVP License Server Running", "status": "ok"}

@app.api_route("/{path_name:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catch_all_paths(path_name: str, request: Request):
    """Catch literally anything else"""
    body = await request.body()
    logger.info(f"🔄 WILDCARD CATCH - Path: {path_name}")
    logger.info(f"📦 Body: {body.decode('utf-8', errors='ignore')}")
    return {"status": "ok", "message": "Caught by wildcard"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)