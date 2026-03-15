from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import secrets
from datetime import datetime, timedelta
import os
import json
from typing import Optional
import hashlib
import uuid

app = FastAPI()

# Allow all origins (important for panels)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== DATABASE SETUP ==========
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def load_db(db_name):
    db_path = os.path.join(DATA_DIR, f"{db_name}.json")
    if os.path.exists(db_path):
        with open(db_path, 'r') as f:
            return json.load(f)
    return {}

def save_db(db_name, data):
    db_path = os.path.join(DATA_DIR, f"{db_name}.json")
    with open(db_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

# ========== MASTER SETTINGS ==========
# CHANGE THIS TO YOUR SECRET MASTER KEY!
MASTER_KEY = "YOUR_SUPER_SECRET_MASTER_KEY_2026_CHANGE_THIS"

# ========== RESELLER MANAGEMENT ==========

@app.post("/api/master/create_reseller")
async def create_reseller(data: dict):
    """MASTER ONLY: Create a new reseller (YOU use this)"""
    master_key = data.get("master_key", "")
    
    if master_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid master key")
    
    username = data.get("username")
    days_valid = data.get("days_valid", 365)  # 1 year default
    max_keys = data.get("max_keys", 1000)  # How many keys they can create
    
    # Generate unique token for reseller
    reseller_token = secrets.token_hex(16)
    panel_id = str(uuid.uuid4())
    
    resellers = load_db("resellers")
    
    # Check if username exists
    if username in resellers:
        raise HTTPException(status_code=400, detail="Username already exists")
    
    expires = datetime.now() + timedelta(days=days_valid)
    
    resellers[username] = {
        "panel_id": panel_id,
        "token": reseller_token,
        "created": datetime.now().isoformat(),
        "expires": expires.isoformat(),
        "active": True,
        "max_keys": max_keys,
        "keys_created": 0,
        "total_revenue": 0
    }
    save_db("resellers", resellers)
    
    # Create empty keys file for this reseller
    reseller_keys = load_db(f"keys_{panel_id}")
    save_db(f"keys_{panel_id}", {})
    
    return {
        "success": True,
        "username": username,
        "token": reseller_token,
        "panel_id": panel_id,
        "expires": expires.isoformat(),
        "panel_login_url": f"https://YOUR_PANEL_DOMAIN.com/login?token={reseller_token}",
        "api_endpoint": "https://license-server-jmsn.onrender.com/api/reseller"
    }

@app.post("/api/master/list_resellers")
async def list_resellers(data: dict):
    """MASTER ONLY: List all resellers"""
    master_key = data.get("master_key", "")
    
    if master_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid master key")
    
    resellers = load_db("resellers")
    return {"resellers": resellers}

@app.post("/api/master/deactivate_reseller")
async def deactivate_reseller(data: dict):
    """MASTER ONLY: Deactivate a reseller"""
    master_key = data.get("master_key", "")
    
    if master_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid master key")
    
    username = data.get("username")
    resellers = load_db("resellers")
    
    if username in resellers:
        resellers[username]["active"] = False
        save_db("resellers", resellers)
        return {"success": True}
    
    raise HTTPException(status_code=404, detail="Reseller not found")

# ========== RESELLER AUTH ==========

def verify_reseller_token(token: str):
    """Verify reseller token and return reseller info"""
    resellers = load_db("resellers")
    for username, data in resellers.items():
        if data.get("token") == token and data.get("active", False):
            # Check expiry
            expires = datetime.fromisoformat(data["expires"])
            if datetime.now() > expires:
                return None, "Panel expired"
            return username, data
    return None, "Invalid token"

# ========== RESELLER API (What the panel uses) ==========

@app.post("/api/reseller/login")
async def reseller_login(data: dict):
    """Reseller logs in with their token"""
    token = data.get("token", "")
    
    username, reseller_data = verify_reseller_token(token)
    if not username:
        return {"success": False, "error": "Invalid or expired token"}
    
    return {
        "success": True,
        "username": username,
        "expires": reseller_data["expires"],
        "keys_created": reseller_data["keys_created"],
        "max_keys": reseller_data["max_keys"]
    }

@app.post("/api/reseller/create_key")
async def reseller_create_key(data: dict):
    """Reseller creates a new license key"""
    token = data.get("token", "")
    days = data.get("days", 30)
    max_devices = data.get("max_devices", 3)
    
    # Verify reseller
    username, reseller_data = verify_reseller_token(token)
    if not username:
        return {"success": False, "error": "Invalid token"}
    
    # Check key limit
    if reseller_data["keys_created"] >= reseller_data["max_keys"]:
        return {"success": False, "error": "Key limit reached"}
    
    # Generate key
    key = ''
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    for i in range(16):
        key += chars[secrets.randbelow(len(chars))]
        if (i + 1) % 4 == 0 and i < 15:
            key += '-'
    
    expires = datetime.now() + timedelta(days=days)
    
    # Load reseller's keys
    panel_id = reseller_data["panel_id"]
    reseller_keys = load_db(f"keys_{panel_id}")
    
    # Save key
    reseller_keys[key] = {
        "created": datetime.now().isoformat(),
        "expires": expires.isoformat(),
        "max_devices": max_devices,
        "devices": [],
        "created_by": username
    }
    save_db(f"keys_{panel_id}", reseller_keys)
    
    # Update reseller key count
    resellers = load_db("resellers")
    resellers[username]["keys_created"] += 1
    save_db("resellers", resellers)
    
    return {
        "success": True,
        "key": key,
        "expires": expires.isoformat(),
        "max_devices": max_devices
    }

@app.post("/api/reseller/list_keys")
async def reseller_list_keys(data: dict):
    """Reseller lists all their keys"""
    token = data.get("token", "")
    
    username, reseller_data = verify_reseller_token(token)
    if not username:
        return {"success": False, "error": "Invalid token"}
    
    panel_id = reseller_data["panel_id"]
    reseller_keys = load_db(f"keys_{panel_id}")
    
    keys_list = []
    for key, key_data in reseller_keys.items():
        keys_list.append({
            "key": key,
            "expires": key_data["expires"],
            "max_devices": key_data["max_devices"],
            "devices_used": len(key_data["devices"])
        })
    
    return {"success": True, "keys": keys_list}

# ========== PUBLIC API (For AIMX app) ==========

@app.get("/")
async def root():
    return {
        "message": "License Server is running!",
        "version": "2.0 with Reseller Support",
        "docs": "/docs"
    }

@app.post("/api/validate")
async def validate_key(data: dict):
    """Public endpoint for AIMX app to validate keys"""
    license_key = data.get("license_key", "")
    device_id = data.get("device_id", "")
    
    # Search through all resellers' keys
    resellers = load_db("resellers")
    
    for username, reseller_data in resellers.items():
        if not reseller_data.get("active"):
            continue
            
        panel_id = reseller_data["panel_id"]
        reseller_keys = load_db(f"keys_{panel_id}")
        
        if license_key in reseller_keys:
            key_data = reseller_keys[license_key]
            
            # Check expiry
            expires = datetime.fromisoformat(key_data["expires"])
            if datetime.now() > expires:
                return {"status": "expired"}
            
            # Check device limit
            if device_id not in key_data["devices"]:
                if len(key_data["devices"]) >= key_data["max_devices"]:
                    return {"status": "device_limit"}
                key_data["devices"].append(device_id)
                save_db(f"keys_{panel_id}", reseller_keys)
            
            return {"status": "valid", "expires": key_data["expires"]}
    
    return {"status": "invalid"}

# ========== FOR TESTING ==========
@app.post("/api/test/create_test_reseller")
async def create_test_reseller():
    """Create a test reseller (for development only)"""
    test_token = secrets.token_hex(16)
    panel_id = str(uuid.uuid4())
    
    resellers = load_db("resellers")
    resellers["test_reseller"] = {
        "panel_id": panel_id,
        "token": test_token,
        "created": datetime.now().isoformat(),
        "expires": (datetime.now() + timedelta(days=365)).isoformat(),
        "active": True,
        "max_keys": 100,
        "keys_created": 0
    }
    save_db("resellers", resellers)
    
    save_db(f"keys_{panel_id}", {})
    
    return {
        "token": test_token,
        "panel_id": panel_id
    }

# ========== RUN ==========
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)