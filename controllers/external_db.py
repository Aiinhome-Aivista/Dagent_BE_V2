from flask import request, jsonify
from database.external_sync_service import apply_external_sync as apply_external_sync_service, sync_external_database , apply_bulk_external_sync


def connect_external_db():

    data = request.json

    user_id = int(data.get("user_id"))          
    connection_id = int(data.get("connection_id"))
    session_id = data.get("session_id")         

    print("INPUT →", user_id, connection_id, session_id)

    if not user_id or not connection_id or not session_id:
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Missing data"
        }), 400

    is_tally = False
    try:
        import pymysql
        from database.config import MYSQL_CONFIG
        conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
        with conn.cursor() as cur:
            cur.execute("SELECT db_type FROM database_credential WHERE connection_id=%s AND user_id=%s", (connection_id, user_id))
            cred_row = cur.fetchone()
            if cred_row and cred_row[0].strip().lower() == 'tally':
                is_tally = True
        conn.close()
    except Exception:
        pass

    tally_sync_result = None
    if is_tally:
        try:
            import pymysql, json
            from database.config import MYSQL_CONFIG
            conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
            with conn.cursor() as cur:
                cur.execute("SELECT credential FROM database_credential WHERE connection_id=%s AND user_id=%s", (connection_id, user_id))
                clean_cred_data = json.loads(cur.fetchone()[0])
                cur.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
                user_db_name = cur.fetchone()[0]
                cur.execute("SELECT email FROM users WHERE id=%s", (user_id,))
                user_email = cur.fetchone()[0]
                username_for_sync = user_email.split("@")[0] if user_email else "unknown"
            conn.close()

            from database.tally_connector import sync_tally_database
            print("[*] Triggering Auto-Sync for Tally after connection creation...")
            tally_sync_result = sync_tally_database(user_id, connection_id, session_id, clean_cred_data, user_db_name, username_for_sync)
            result = tally_sync_result
        except Exception as sync_e:
            print(f"[!] Auto-Sync failed for Tally: {sync_e}")
            tally_sync_result = {"error": str(sync_e)}
            result = {"situations": [], "new_tables": [], "summary": {}, "tables": []}
    else:
        result = sync_external_database(user_id, connection_id, session_id)

    # For doc_upload, the frontend never calls apply_bulk_sync, and apply_bulk_sync skips it anyway.
    # We must insert it into external_db_sync_log here so it appears in /session-sources.
    try:
        import pymysql
        from database.config import MYSQL_CONFIG
        conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
        with conn.cursor() as cur:
            cur.execute("SELECT db_type, credential FROM database_credential WHERE connection_id=%s AND user_id=%s", (connection_id, user_id))
            cred_row = cur.fetchone()
            if cred_row and cred_row[0] in ['doc_upload', 'doc_chunk_upload']:
                db_type = cred_row[0]
                import json
                cred_data = json.loads(cred_row[1])
                filename = cred_data.get("files", [""])[0] if cred_data.get("files") else "document"
                
                cur.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
                ws_row = cur.fetchone()
                user_db = ws_row[0] if ws_row else ""
                
                cur.execute("SELECT email FROM users WHERE id=%s", (user_id,))
                user_row = cur.fetchone()
                username = user_row[0].split("@")[0] if user_row else "unknown"
                
                import os
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                file_path = os.path.join(base_dir, "uploads", filename)
                try:
                    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
                except Exception:
                    file_size_mb = 0.0

                new_tables = result.get("new_tables", [])
                size_per_table = file_size_mb / max(1, len(new_tables))
                
                for t in new_tables:
                    # check if already exists
                    cur.execute("SELECT id FROM external_db_sync_log WHERE session_id=%s AND table_name=%s", (session_id, t))
                    if not cur.fetchone():
                        cur.execute("""
                            INSERT INTO external_db_sync_log 
                            (user_id, session_id, username, external_database, new_user_db, table_name, action_type, rows_affected, data_size_mb)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (user_id, session_id, username, filename, user_db, t, "NEW_TABLE", 0, size_per_table))
                conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error auto-syncing doc_upload: {e}")

    if not result.get("situations") and not result.get("new_tables"):
        response_data = {
            "status": True,
            "statuscode": 200,
            "data": {
                "summary": result.get("summary", {}),
                "tables": result.get("tables", [])
            },
            "msg": "Database already up to date. No changes detected."
        }
    else:
        response_data = {
            "status": True,
            "statuscode": 200,
            "data": {
                "situations": result.get("situations", []),
                "tables": result.get("tables", []),
                "summary": result.get("summary", {})
            },
            "msg": "External database analyzed successfully"
        }

    if 'tally_sync_result' in locals() and tally_sync_result:
        response_data["tally_sync_result"] = tally_sync_result
        response_data["msg"] += " (Data fetched and saved successfully!)"

    return jsonify(response_data)

def apply_external_sync():

    data = request.json

    user_id = data.get("user_id")
    connection_id = data.get("connection_id")
    session_id = data.get("session_id")
    table = data.get("table")

    if not user_id or not connection_id or not session_id or not table:
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Missing required fields"
        }), 400

    apply_external_sync_service(user_id, connection_id, session_id, table)

    return jsonify({
        "status": True,
        "statuscode": 200,
        "data": None,
        "msg": "External sync applied successfully"
    })

def apply_bulk_sync():
    """
    API endpoint to handle bulk synchronization of multiple tables.
    Supports 'update' (append new rows/add new tables) and 'replace' (drop and recreate).
    """
    data = request.json

    user_id = data.get("user_id")
    connection_id = data.get("connection_id")
    session_id = data.get("session_id")
    tables = data.get("tables") # Now expects a list of table names
    action = data.get("action", "update") # "update" (Update Existing) or "replace" (Replace All)

    if not user_id or not connection_id or not tables or not isinstance(tables, list):
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Missing required fields or 'tables' is not a list"
        }), 400

    try:
        apply_bulk_external_sync(user_id, connection_id, session_id, tables, action)
        
        return jsonify({
            "status": True,
            "statuscode": 200,
            "data": None,
            "msg": f"Successfully applied '{action}' sync for {len(tables)} tables."
        })
    except Exception as e:
        return jsonify({
            "status": False,
            "statuscode": 500,
            "data": None,
            "msg": str(e)
        }), 500
