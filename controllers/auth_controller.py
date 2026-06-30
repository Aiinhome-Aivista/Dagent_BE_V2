from flask import request, jsonify
from database.db_connection import get_db_connection
from database.user_db_service import create_user_database


def register_user_controller(get_db_connection):
    data = request.json
    
    # Extract user details from the request
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    
    # Basic validation
    if not name or not email or not password:
        return jsonify({"status": "error", "message": "Name, email, and password are required"}), 400

    try:
        db_conn = get_db_connection()
        if not db_conn:
            return jsonify({"error": "Cannot connect to database"}), 500
            
        cursor = db_conn.cursor(dictionary=True)
        
        # 1. Check if the user already exists in the database
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            cursor.close()
            db_conn.close()
            return jsonify({"status": "error", "message": "A user with this email already exists"}), 409
            
        # 2. Insert the new user with the PLAIN TEXT password
        cursor.execute(
            "INSERT INTO users (name, email, password) VALUES (%s, %s, %s)", 
            (name, email, password)
        )
        db_conn.commit()
        
        # Grab the newly created user's ID
        new_user_id = cursor.lastrowid
        
        cursor.close()
        db_conn.close()
        
        return jsonify({
            "status": "success", 
            "message": "User registered successfully",
            "user": {
                "id": new_user_id,
                "name": name,
                "email": email
            }
        }), 201
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def login():

    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Email and password required"
        }), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
    SELECT u.id, u.email, u.name, u.role_id, u.new_user_db, r.role_name
    FROM users u
    LEFT JOIN roles r ON u.role_id = r.id
    WHERE u.email=%s AND u.password=%s
    """
    cursor.execute(query, (email, password))
    user = cursor.fetchone()

    if not user:
        return jsonify({
            "status": False,
            "statuscode": 401,
            "data": None,
            "msg": "Invalid credentials"
        }), 401

    user_id = user["id"]
    email = user["email"]
    user_name = user["name"]
    role_id = user["role_id"]
    role_name = user["role_name"]
    # check existing db
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


    # --- BYPASSED USER DB CREATION ---
    # The database context is now workspace-centric (workspaces.workspace_db)
    # db_result = create_user_database(email)
    # user_db = db_result["db_name"]
    # update_query = "UPDATE users SET new_user_db=%s WHERE id=%s"
    # cursor.execute(update_query, (user_db, user_id))
    # conn.commit()
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

