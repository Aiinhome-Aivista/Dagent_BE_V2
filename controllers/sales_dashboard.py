from flask import jsonify, request

def get_sales_revenue_data_controller(get_db_connection):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        session_id = request.args.get("session_id")
        cursor = conn.cursor(dictionary=True)
        
        if session_id:
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE session_id=%s 
                  AND new_user_db IS NOT NULL 
                  AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            sync_row = cursor.fetchone()
            if sync_row:
                user_db = sync_row["new_user_db"]
                cursor.execute(f"USE `{user_db}`")
        
        zone = request.args.get("zone")
        
        # Calling the Stored Procedure
        args = (zone,) if zone else (None,)
        cursor.callproc('sp_get_sales_revenue_by_zone', args)
        
        chart_data = []
        # Fetching the result set from the stored procedure
        for result in cursor.stored_results():
            chart_data = result.fetchall()
            break  # We only need the first result set

        return jsonify({
            "status": "success",
            "data": chart_data
        }), 200

    except Exception as e:
        print(f"Error fetching sales revenue data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_sales_by_account_category_controller(get_db_connection):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        session_id = request.args.get("session_id")
        cursor = conn.cursor(dictionary=True)
        
        if session_id:
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            sync_row = cursor.fetchone()
            if sync_row:
                cursor.execute(f"USE `{sync_row['new_user_db']}`")
        
        zone = request.args.get("zone")
        args = (zone,) if zone else (None,)
        cursor.callproc('sp_get_sales_by_account_category', args)
        
        chart_data = []
        for result in cursor.stored_results():
            chart_data = result.fetchall()
            break 
            
        return jsonify({"status": "success", "data": chart_data}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_non_billed_accounts_controller(get_db_connection):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        session_id = request.args.get("session_id")
        cursor = conn.cursor(dictionary=True)
        
        if session_id:
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            sync_row = cursor.fetchone()
            if sync_row:
                cursor.execute(f"USE `{sync_row['new_user_db']}`")
        
        zone = request.args.get("zone")
        args = (zone,) if zone else (None,)
        cursor.callproc('sp_get_non_billed_accounts_pct', args)
        
        chart_data = []
        for result in cursor.stored_results():
            chart_data = result.fetchall()
            break 
            
        return jsonify({"status": "success", "data": chart_data}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_overdue_pct_controller(get_db_connection):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        session_id = request.args.get("session_id")
        cursor = conn.cursor(dictionary=True)
        
        if session_id:
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            sync_row = cursor.fetchone()
            if sync_row:
                cursor.execute(f"USE `{sync_row['new_user_db']}`")
        
        zone = request.args.get("zone")
        args = (zone,) if zone else (None,)
        cursor.callproc('sp_get_overdue_pct', args)
        
        chart_data = []
        for result in cursor.stored_results():
            chart_data = result.fetchall()
            break 
            
        return jsonify({"status": "success", "data": chart_data}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()

def get_exposure_pct_controller(get_db_connection):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        session_id = request.args.get("session_id")
        cursor = conn.cursor(dictionary=True)
        
        if session_id:
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            sync_row = cursor.fetchone()
            if sync_row:
                cursor.execute(f"USE `{sync_row['new_user_db']}`")
        
        zone = request.args.get("zone")
        args = (zone,) if zone else (None,)
        cursor.callproc('sp_get_exposure_pct', args)
        
        chart_data = []
        for result in cursor.stored_results():
            chart_data = result.fetchall()
            break 
            
        return jsonify({"status": "success", "data": chart_data}), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()
