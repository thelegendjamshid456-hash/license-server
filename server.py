from flask import Flask, request, jsonify
import sqlite3
import logging
import os
from datetime import datetime
import random
import string
from datetime import datetime, timedelta

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'reseller_panel', 'database.db')
# Use /tmp for SQLite on Render
DB_PATH = '/tmp/glass_license.db'

def check_license_with_device(license_key, device_id):
    """Check if license is valid and track devices"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get license info
        cursor.execute("""
            SELECT * FROM licenses 
            WHERE license_key = ? AND is_active = 1
        """, (license_key,))
        
        license_data = cursor.fetchone()
        
        if not license_data:
            conn.close()
            logging.info(f"❌ License not found: {license_key}")
            return False, "License not found"
        
        # Check expiration
        expires_at = datetime.strptime(license_data['expires_at'], '%Y-%m-%d %H:%M:%S')
        if expires_at < datetime.now():
            conn.close()
            logging.info(f"❌ License expired: {license_key}")
            return False, "License expired"
        
        # Get device limit (default 1 if not set)
        device_limit = license_data['device_limit'] if 'device_limit' in license_data.keys() else 1
        
        # Check if this device is already registered
        cursor.execute("""
            SELECT * FROM devices 
            WHERE license_key = ? AND device_id = ?
        """, (license_key, device_id))
        
        existing_device = cursor.fetchone()
        
        if existing_device:
            # Device exists - update last_seen
            cursor.execute("""
                UPDATE devices 
                SET last_seen = datetime('now') 
                WHERE license_key = ? AND device_id = ?
            """, (license_key, device_id))
            conn.commit()
            logging.info(f"✅ Existing device authenticated: {device_id}")
            
        else:
            # New device - count current devices
            cursor.execute("""
                SELECT COUNT(*) as count FROM devices 
                WHERE license_key = ?
            """, (license_key,))
            
            device_count = cursor.fetchone()['count']
            
            if device_count >= device_limit:
                conn.close()
                logging.info(f"❌ Device limit reached for {license_key}: {device_count}/{device_limit}")
                return False, f"Device limit reached ({device_limit} devices max)"
            
            # Register new device
            cursor.execute("""
                INSERT INTO devices (license_key, device_id, first_seen, last_seen)
                VALUES (?, ?, datetime('now'), datetime('now'))
            """, (license_key, device_id))
            conn.commit()
            logging.info(f"✅ New device registered: {device_id} ({device_count+1}/{device_limit})")
        
        # Update last_checked on license
        cursor.execute("""
            UPDATE licenses 
            SET last_checked = datetime('now') 
            WHERE license_key = ?
        """, (license_key,))
        conn.commit()
        
        # Get updated device count
        cursor.execute("SELECT COUNT(*) as count FROM devices WHERE license_key = ?", (license_key,))
        current_count = cursor.fetchone()['count']
        
        conn.close()
        
        return True, {
            "license": dict(license_data),
            "devices_used": current_count,
            "device_limit": device_limit
        }
        
    except Exception as e:
        logging.error(f"Database error: {e}")
        return False, "Server error"
def init_db():
    """Create database for licenses"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Licenses table - matches GLASS-DAY-XXXXXXXX format
    c.execute('''CREATE TABLE IF NOT EXISTS licenses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT UNIQUE,
                  customer_email TEXT,
                  license_type TEXT DEFAULT 'DAY',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  expires_at DATETIME,
                  is_active BOOLEAN DEFAULT 1,
                  device_limit INTEGER DEFAULT 10000)''')
    
    # Devices table
    c.execute('''CREATE TABLE IF NOT EXISTS devices
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  license_key TEXT,
                  device_id TEXT,
                  first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                  last_seen DATETIME,
                  FOREIGN KEY (license_key) REFERENCES licenses (license_key))''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")

init_db()

def generate_glass_license(license_type="DAY"):
    """Generate license in GLASS-TYPE-XXXXXXXX format"""
    # Generate 8 random characters (A-Z, 0-9)
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"GLASS-{license_type}-{random_part}"

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def handle_all(path):
    logging.info("=" * 50)
    logging.info(f"🔥 Endpoint: /{path}")
    logging.info(f"📡 IP: {request.remote_addr}")
    logging.info(f"🔧 Method: {request.method}")
    
    # Extract license key and device ID
    license_key = None
    device_id = None
    
    if request.is_json:
        data = request.get_json()
        license_key = data.get('license_key') or data.get('key') or data.get('license') or data.get('token')
        device_id = data.get('device_id') or data.get('device') or data.get('hardware_id') or data.get('android_id')
        logging.info(f"📦 JSON data: {data}")
@app.route('/verify', methods=['POST'])
def verify_license():
    """Main endpoint for Glass Engine license verification"""
    data = request.get_json()
    print(f"📦 Verify request: {data}")
    
    license_key = data.get('license_key') or data.get('key') or data.get('license')
    device_id = data.get('device_id') or data.get('hardware_id') or data.get('device') or 'unknown'
    
    print(f"🔑 License: {license_key}")
    print(f"📱 Device: {device_id}")

    if not license_key:
        license_key = request.args.get('key') or request.args.get('license') or request.args.get('token')
    
    if not device_id:
        device_id = request.args.get('device_id') or request.args.get('device') or request.headers.get('X-Device-ID')
    
    # Also check headers for common device IDs
    if not device_id:
        device_id = request.headers.get('User-Agent') or request.headers.get('X-Android-ID')
    
    if license_key and device_id:
        logging.info(f"🔑 License: {license_key}, 📱 Device: {device_id}")
        
        valid, info = check_license_with_device(license_key, device_id)
        
        if valid:
            return jsonify({
                "success": True,
                "valid": True,
                "status": "active",
                "license_key": license_key,
                "device_id": device_id,
                "devices_used": info['devices_used'],
                "device_limit": info['device_limit'],
                "expires": info['license']['expires_at'],
                "message": "License valid",
                "features": ["all", "premium", "pro"]
            })
        else:
            return jsonify({
                "success": False,
                "valid": False,
                "error": info,
                "message": "License validation failed"
            }), 403
    
    elif license_key and not device_id:
        logging.info(f"⚠️ License key provided but no device ID: {license_key}")
        return jsonify({"error": "No license key"}), 400
    
    # Validate format (should be GLASS-XXX-XXXXXXXX)
    parts = license_key.split('-')
    if len(parts) != 3 or parts[0] != 'GLASS':
        return jsonify({
            "success": False,
            "valid": False,
            "error": "Device ID required",
            "message": "Please provide device ID"
        }), 400
            "error": "Invalid license format"
        }), 403
    
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

    logging.info("⚠️ No license key in request")
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
    
    # Return success with GLASS format
    return jsonify({
        "status": "ok",
        "message": "Glass Engine License Server",
        "endpoint": f"/{path}"
        "success": True,
        "valid": True,
        "status": "active",
        "license_key": license_key,
        "license_type": parts[1],  # DAY, WEEK, etc.
        "expires": license['expires_at'],
        "device_limit": license['device_limit'],
        "devices_used": device_count + (0 if existing_device else 1),
        "features": ["all", "premium", "pro"]
    })

# Admin endpoint to check devices on a license
@app.route('/admin/devices/<license_key>', methods=['GET'])
def admin_check_devices(license_key):
    """Admin endpoint to see all devices for a license"""
@app.route('/api/add_license', methods=['POST'])
def add_license():
    """Endpoint for your reseller panel to add licenses"""
    data = request.get_json()
    admin_token = data.get('admin_token')
    
    # Security check
    if admin_token != "2b969f6736b5b93e495c6ea65acb9216":
        return jsonify({"error": "Unauthorized"}), 401
    
    license_key = data.get('license_key')
    email = data.get('customer_email')
    license_type = data.get('license_type', 'DAY')
    expires_at = data.get('expires_at')
    device_limit = data.get('device_limit', 10000)
    
    # Validate GLASS format
    parts = license_key.split('-')
    if len(parts) != 3 or parts[0] != 'GLASS':
        return jsonify({"error": "Invalid license format. Use GLASS-TYPE-XXXXXXXX"}), 400
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT device_id, device_name, first_seen, last_seen, is_active 
            FROM devices WHERE license_key = ?
        """, (license_key,))
        
        devices = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT device_limit FROM licenses WHERE license_key = ?", (license_key,))
        limit = cursor.fetchone()
        
        conn.close()
        
        return jsonify({
            "license_key": license_key,
            "device_limit": limit['device_limit'] if limit else 1,
            "devices": devices,
            "total_devices": len(devices)
        })
        c.execute("""
            INSERT INTO licenses (license_key, customer_email, license_type, expires_at, device_limit)
            VALUES (?, ?, ?, ?, ?)
        """, (license_key, email, license_type, expires_at, device_limit))
        conn.commit()
        return jsonify({"success": True, "message": f"License {license_key} added"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/verify', methods=['POST', 'GET'])
def verify():
    return handle_all('verify')
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()

@app.route('/api/license', methods=['POST'])
def api_license():
    return handle_all('api/license')
@app.route('/api/generate_test', methods=['GET'])
def generate_test():
    """Generate a test license (for debugging)"""
    license_key = generate_glass_license("DAY")
    expires = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d %H:%M:%S')
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO licenses (license_key, customer_email, license_type, expires_at, device_limit)
        VALUES (?, ?, ?, ?, ?)
    """, (license_key, "test@example.com", "DAY", expires, 10000))
    conn.commit()
    conn.close()
    
    return jsonify({"license": license_key, "expires": expires})

@app.route('/validate', methods=['POST'])
def validate():
    return handle_all('validate')
@app.route('/')
def home():
    return jsonify({
        "status": "Glass Engine License Server",
        "version": "1.0",
        "format": "GLASS-TYPE-XXXXXXXX",
        "endpoints": ["/verify", "/api/add_license", "/api/generate_test"]
    })

if __name__ == '__main__':
    if os.path.exists(DB_PATH):
        logging.info(f"✅ Database found at: {DB_PATH}")
    else:
        logging.error(f"❌ Database NOT found at: {DB_PATH}")
        logging.info("Please run setup_database.py first")
    
    logging.info("🚀 License server starting with DEVICE TRACKING...")
    logging.info("📝 Logging all requests")
    app.run(host='0.0.0.0', port=5000, debug=True)
    app.run(host='0.0.0.0', port=5000)