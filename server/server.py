from flask import Flask, request, jsonify
import sqlite3
import logging
import os
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'reseller_panel', 'database.db')

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
        return jsonify({
            "success": False,
            "valid": False,
            "error": "Device ID required",
            "message": "Please provide device ID"
        }), 400
    
    logging.info("⚠️ No license key in request")
    return jsonify({
        "status": "ok",
        "message": "Glass Engine License Server",
        "endpoint": f"/{path}"
    })

# Admin endpoint to check devices on a license
@app.route('/admin/devices/<license_key>', methods=['GET'])
def admin_check_devices(license_key):
    """Admin endpoint to see all devices for a license"""
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
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/verify', methods=['POST', 'GET'])
def verify():
    return handle_all('verify')

@app.route('/api/license', methods=['POST'])
def api_license():
    return handle_all('api/license')

@app.route('/validate', methods=['POST'])
def validate():
    return handle_all('validate')

if __name__ == '__main__':
    if os.path.exists(DB_PATH):
        logging.info(f"✅ Database found at: {DB_PATH}")
    else:
        logging.error(f"❌ Database NOT found at: {DB_PATH}")
        logging.info("Please run setup_database.py first")
    
    logging.info("🚀 License server starting with DEVICE TRACKING...")
    logging.info("📝 Logging all requests")
    app.run(host='0.0.0.0', port=5000, debug=True)