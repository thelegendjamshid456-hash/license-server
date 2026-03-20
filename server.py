from flask import Flask, request, jsonify
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

# IMPORTANT: This should match your Reseller database structure
# For Render, we need to sync data from your local DB
DB_PATH = '/tmp/glass_license.db'  # Render uses /tmp for writable files

def init_db():
    """Create the same database structure as your Reseller panel"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Licenses table - match your Reseller panel exactly
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT UNIQUE,
                  reseller_id INTEGER,
                  customer_email TEXT,
                  license_type TEXT DEFAULT 'DAY',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  expires_at DATETIME,
                  is_active BOOLEAN DEFAULT 1,
                  device_limit INTEGER DEFAULT 10000)''')
    
    # Devices table - track devices per license
    c.execute('''CREATE TABLE IF NOT EXISTS devices
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT,
                  device_id TEXT,
                  first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                  last_seen DATETIME,
                  FOREIGN KEY (license_key) REFERENCES licenses (license_key))''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized on Render")

# Call this when server starts
init_db()

# ============================================
# API ENDPOINTS FOR GLASS ENGINE APP
# ============================================

@app.route('/verify', methods=['POST'])
def verify_license():
    """Main endpoint that Glass Engine calls to verify licenses"""
    data = request.get_json()
    print(f"📦 Verify request: {data}")
    
    license_key = data.get('license_key') or data.get('key') or data.get('license')
    device_id = data.get('device_id') or data.get('hardware_id') or data.get('device') or 'unknown'
    
    if not license_key:
        return jsonify({"error": "No license key"}), 400
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Check if license exists and is active
    c.execute("SELECT * FROM licenses WHERE license_key = ? AND is_active = 1", (license_key,))
    license = c.fetchone()
    
    if not license:
        conn.close()
        return jsonify({
            "valid": False,
            "error": "Invalid license key"
        }), 403
    
    # Check expiration
    expires_at = datetime.strptime(license['expires_at'], '%Y-%m-%d %H:%M:%S')
    if expires_at < datetime.now():
        conn.close()
        return jsonify({
            "valid": False,
            "error": "License expired"
        }), 403
    
    # Check device limit
    c.execute("SELECT COUNT(*) as count FROM devices WHERE license_key = ?", (license_key,))
    device_count = c.fetchone()['count']
    
    # Check if this device is already registered
    c.execute("SELECT * FROM devices WHERE license_key = ? AND device_id = ?", 
             (license_key, device_id))
    existing_device = c.fetchone()
    
    if not existing_device and device_count >= license['device_limit']:
        conn.close()
        return jsonify({
            "valid": False,
            "error": f"Device limit reached ({license['device_limit']})"
        }), 403
    
    # Register or update device
    if existing_device:
        c.execute("UPDATE devices SET last_seen = datetime('now') WHERE license_key = ? AND device_id = ?",
                 (license_key, device_id))
    else:
        c.execute("INSERT INTO devices (license_key, device_id, first_seen, last_seen) VALUES (?, ?, datetime('now'), datetime('now'))",
                 (license_key, device_id))
    
    conn.commit()
    conn.close()
    
    # Return success in format Glass Engine expects
    return jsonify({
        "success": True,
        "valid": True,
        "status": "active",
        "license_key": license_key,
        "expires": license['expires_at'],
        "device_limit": license['device_limit'],
        "devices_used": device_count + (0 if existing_device else 1),
        "features": ["all", "premium", "pro"]
    })

@app.route('/api/license', methods=['POST'])
def api_license():
    """Alternative endpoint that Glass Engine might use"""
    return verify_license()

@app.route('/validate', methods=['POST'])
def validate():
    """Another common endpoint"""
    return verify_license()

# ============================================
# API ENDPOINTS FOR YOUR RESELLER PANEL
# ============================================

@app.route('/api/sync_license', methods=['POST'])
def sync_license():
    """Called by your Reseller panel when new licenses are generated"""
    data = request.get_json()
    admin_token = data.get('admin_token')
    
    # Simple security - you can change this
    if admin_token != "2b969f6736b5b93e495c6ea65acb9216":
        return jsonify({"error": "Unauthorized"}), 401
    
    license_key = data.get('license_key')
    email = data.get('customer_email')
    license_type = data.get('license_type', 'DAY')
    expires_at = data.get('expires_at')
    device_limit = data.get('device_limit', 10000)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        c.execute("""
            INSERT INTO licenses (license_key, customer_email, license_type, expires_at, device_limit)
            VALUES (?, ?, ?, ?, ?)
        """, (license_key, email, license_type, expires_at, device_limit))
        conn.commit()
        return jsonify({"success": True, "message": "License synced to Render"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@app.route('/')
def home():
    return jsonify({
        "status": "Glass Engine License Server",
        "version": "1.0",
        "endpoints": ["/verify", "/api/license", "/validate", "/api/sync_license"]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)