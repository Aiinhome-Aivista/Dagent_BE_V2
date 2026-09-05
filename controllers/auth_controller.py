from flask import request, jsonify
from database.db_connection import get_db_connection
from database.user_db_service import create_user_database
from utils.crypto_utils import encrypt_password, decrypt_password

def register_user_controller(get_db_connection):
    data = request.json
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    if not name or not email or not password:
        return jsonify({"status": "error", "message": "Name, email, and password are required"}), 400
    try:
        db_conn = get_db_connection()
        if not db_conn:
            return jsonify({"error": "Cannot connect to database"}), 500
        cursor = db_conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        if existing_user:
            cursor.close()
            db_conn.close()
            return jsonify({"status": "error", "message": "A user with this email already exists"}), 409
        hashed_password = encrypt_password(password)
        cursor.execute("INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", (name, email, hashed_password))
        db_conn.commit()
        new_user_id = cursor.lastrowid
        cursor.close()
        db_conn.close()
        return jsonify({
            "status": "success", 
            "message": "User registered successfully",
            "user": {"id": new_user_id, "name": name, "email": email}
        }), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"status": False, "statuscode": 400, "data": None, "msg": "Email and password required"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    SELECT u.id, u.email, u.name, u.password as stored_password, u.role_id, u.new_user_db, r.role_name
    FROM users u
    LEFT JOIN roles r ON u.role_id = r.id
    WHERE u.email=%s
    """
    cursor.execute(query, (email,))
    user = cursor.fetchone()
    
    if not user:
        return jsonify({"status": False, "statuscode": 401, "data": None, "msg": "Invalid credentials"}), 401

    stored_password = user["stored_password"]
    is_valid_password = (decrypt_password(stored_password) == password)
        
    if not is_valid_password:
        return jsonify({"status": False, "statuscode": 401, "data": None, "msg": "Invalid credentials"}), 401
    
    user_id = user["id"]
    email = user["email"]
    user_name = user["name"]
    role_id = user["role_id"]
    role_name = user["role_name"]

    if role_name == 'Admin':
        cursor.close()
        conn.close()
        return jsonify({
            "status": False,
            "statuscode": 403,
            "data": None,
            "msg": "Admins must use the admin login portal"
        }), 403

    check_query = "SELECT new_user_db FROM users WHERE id=%s"
    cursor.execute(check_query, (user_id,))
    existing_db = cursor.fetchone()
    
    if existing_db and existing_db["new_user_db"]:
        cursor.close()
        conn.close()
        return jsonify({
            "status": True,
            "statuscode": 200,
            "data": {
                "user_id": user_id,
                "user_database": existing_db["new_user_db"],
                "role_id": role_id,
                "role_name": role_name,
                "name": user_name
            },
            "msg": "User database already exists"
        }), 200

    user_db = existing_db["new_user_db"] if existing_db else None
    cursor.close()
    conn.close()
    return jsonify({
        "status": True,
        "statuscode": 200,
        "data": {
            "user_id": user_id,
            "name": user_name,
            "role_id": role_id,
            "role_name": role_name,
            "user_database": user_db
        },
        "msg": "Login successful"
    }), 200

def admin_login_auth():
    from flask import request, jsonify
    from database.db_connection import get_db_connection
    data = request.json
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return jsonify({"status": False, "statuscode": 400, "data": None, "msg": "Email and password required"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    SELECT u.id, u.email, u.name, u.password as stored_password, u.role_id, u.new_user_db, r.role_name
    FROM users u
    LEFT JOIN roles r ON u.role_id = r.id
    WHERE u.email=%s
    """
    cursor.execute(query, (email,))
    user = cursor.fetchone()
    if not user:
        return jsonify({"status": False, "statuscode": 401, "data": None, "msg": "Invalid credentials"}), 401
        
    stored_password = user["stored_password"]
    is_valid_password = (decrypt_password(stored_password) == password)
        
    if not is_valid_password:
        return jsonify({"status": False, "statuscode": 401, "data": None, "msg": "Invalid credentials"}), 401
    
    user_id = user["id"]
    email = user["email"]
    user_name = user["name"]
    role_id = user["role_id"]
    role_name = user["role_name"]

    if role_name != 'Admin':
        cursor.close()
        conn.close()
        return jsonify({"status": False, "statuscode": 403, "data": None, "msg": "Access denied. Admin role required."}), 403

    check_query = "SELECT new_user_db FROM users WHERE id=%s"
    cursor.execute(check_query, (user_id,))
    existing_db = cursor.fetchone()
    
    if existing_db and existing_db["new_user_db"]:
        cursor.close()
        conn.close()
        return jsonify({
            "status": True,
            "statuscode": 200,
            "data": {
                "user_id": user_id,
                "user_database": existing_db["new_user_db"],
                "role_id": role_id,
                "role_name": role_name,
                "name": user_name
            },
            "msg": "User database already exists"
        }), 200

    user_db = existing_db["new_user_db"] if existing_db else None
    cursor.close()
    conn.close()
    return jsonify({
        "status": True,
        "statuscode": 200,
        "data": {
            "user_id": user_id,
            "name": user_name,
            "role_id": role_id,
            "role_name": role_name,
            "user_database": user_db
        },
        "msg": "Login successful"
    }), 200
