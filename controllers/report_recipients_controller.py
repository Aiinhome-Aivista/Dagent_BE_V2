from flask import request, jsonify
from database.db_connection import get_db_connection

def add_recipient_controller():
    data = request.json
    name = data.get('name')
    email = data.get('email')

    if not name or not email:
        return jsonify({"status": "error", "message": "Name and email are required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if email exists
        cursor.execute("SELECT id FROM report_recipients WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({"status": "error", "message": "Email already exists"}), 409

        cursor.execute("INSERT INTO report_recipients (name, email) VALUES (%s, %s)", (name, email))
        conn.commit()
        new_id = cursor.lastrowid
        
        return jsonify({"status": "success", "message": "Recipient added", "data": {"id": new_id, "name": name, "email": email}}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

def get_recipients_controller():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email FROM report_recipients ORDER BY id DESC")
        recipients = cursor.fetchall()
        return jsonify({"status": "success", "data": recipients}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

def update_recipient_controller(recipient_id):
    data = request.json
    name = data.get('name')
    email = data.get('email')
    
    if not name or not email:
        return jsonify({"status": "error", "message": "Name and email are required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if email exists for another recipient
        cursor.execute("SELECT id FROM report_recipients WHERE email = %s AND id != %s", (email, recipient_id))
        if cursor.fetchone():
            return jsonify({"status": "error", "message": "Email already used by another recipient"}), 409

        cursor.execute("UPDATE report_recipients SET name = %s, email = %s WHERE id = %s", (name, email, recipient_id))
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Recipient not found"}), 404
            
        return jsonify({"status": "success", "message": "Recipient updated"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()

def delete_recipient_controller(recipient_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM report_recipients WHERE id = %s", (recipient_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            return jsonify({"status": "error", "message": "Recipient not found"}), 404
            
        return jsonify({"status": "success", "message": "Recipient deleted"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals(): conn.close()
