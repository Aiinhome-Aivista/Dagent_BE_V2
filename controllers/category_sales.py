import sys
import os
sys.path.append(os.path.abspath('e:\\D-API-UI\\api'))
from flask import request, jsonify

def get_category_sales_controller(get_db_connection):
    try:
        session_id = request.args.get("session_id")
        conn = get_db_connection()
        if not conn:
            return jsonify({"status": "error", "message": "Database connection failed"}), 500
            
        cursor = conn.cursor(dictionary=True)
        
        # Determine database to use
        db_name = None
        if session_id:
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE session_id=%s 
                  AND new_user_db IS NOT NULL 
                  AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            row = cursor.fetchone()
            if row:
                db_name = row["new_user_db"]
                
        if db_name:
            cursor.execute(f"USE `{db_name}`;")
            
        cursor.execute("CALL sp_get_category_sales()")
        results = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "status": "success",
            "data": results
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
