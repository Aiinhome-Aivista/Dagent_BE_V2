import os
import json
import pymysql
import re
from flask import request, jsonify
from database.config import MYSQL_CONFIG
from controllers.uploads_controller import detect_sql_dialect, parse_mysql_or_pg, parse_mssql

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "uploads"))

def import_sql_data(get_db_connection):
    data = request.json
    user_id = data.get("user_id")
    connection_id = data.get("connection_id")
    session_id = data.get("session_id")

    if not user_id or not connection_id or not session_id:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        imported_files = []
        affected_tables_info = []
        total_rows = 0

        # fetch credential
        query = """
        SELECT dc.credential
        FROM database_credential dc
        WHERE (dc.connection_id = %s OR dc.connection_id IS NULL)
        AND dc.user_id = %s
        AND dc.session_id = %s
        ORDER BY dc.connection_id DESC
        LIMIT 1
        """
        cursor.execute(query, (connection_id, user_id, session_id))
        result = cursor.fetchone()

        if not result:
            return jsonify({"status": "error", "message": "Credential not found"}), 404

        credential = json.loads(result["credential"])
        files = credential.get("files", [])

        # fetch user db
        cursor.execute("SELECT name,new_user_db FROM users WHERE id=%s", (user_id,))
        user_data = cursor.fetchone()

        username = user_data["name"]
        user_db = user_data["new_user_db"]

        # connect user database
        user_conn = pymysql.connect(
            host=MYSQL_CONFIG["host"],
            user=MYSQL_CONFIG["user"],
            password=MYSQL_CONFIG["password"],
            database=user_db,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        user_cursor = user_conn.cursor()

        files_in_folder = os.listdir(UPLOAD_DIR)

        for file in files:
            if not file.lower().endswith('.sql'):
                continue

            matched_file = next((f for f in files_in_folder if f.lower() == file.lower()), None)
            if not matched_file:
                continue

            file_path = os.path.join(UPLOAD_DIR, matched_file)
            
            with open(file_path, 'r', encoding='utf-8') as f:
                sql_content = f.read()
                
            file_dialect = detect_sql_dialect(sql_content)
            if file_dialect == 'mssql':
                commands = parse_mssql(sql_content)
            else:
                commands = parse_mysql_or_pg(sql_content)
                
            affected_tables = set()
            for cmd in commands:
                if re.search(r'(?i)^\s*(CREATE\s+DATABASE|USE)\s+', cmd):
                    continue
                    
                try:
                    user_cursor.execute(cmd)
                except Exception as e:
                    print(f"Ignoring SQL execution error: {e}")
                    
                m = re.search(r'(?i)(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|INSERT\s+INTO(?:\s+IGNORE)?|UPDATE|TRUNCATE\s+TABLE)\s+`?([a-zA-Z0-9_]+)`?', cmd)
                if m:
                    affected_tables.add(m.group(1))
                    
            user_conn.commit()
            
            if not affected_tables:
                affected_tables.add(file.lower().replace('.sql', ''))
            
            # Fetch metadata for affected tables
            for t_name in affected_tables:
                try:
                    # Get column count
                    user_cursor.execute(f"""
                        SELECT COUNT(*) as col_count 
                        FROM information_schema.columns 
                        WHERE table_schema = '{user_db}' AND table_name = '{t_name}'
                    """)
                    col_count = user_cursor.fetchone()['col_count'] or 0

                    # Get row count
                    user_cursor.execute(f"SELECT COUNT(*) as row_count FROM `{t_name}`")
                    row_count = user_cursor.fetchone()['row_count'] or 0

                    affected_tables_info.append({
                        "table": t_name,
                        "rows": row_count,
                        "columns": col_count
                    })
                    total_rows += row_count
                except Exception as e:
                    print(f"Error fetching metadata for table {t_name}: {e}")
                    affected_tables_info.append({
                        "table": t_name,
                        "rows": 0,
                        "columns": 0
                    })

            rows_affected = len(commands)
            for t_name in affected_tables:
                log_query = """
                INSERT INTO external_db_sync_log
                (user_id,username,external_database,table_name,
                action_type,rows_affected,session_id,new_user_db)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """
                cursor.execute(log_query, (
                    user_id, username, file, t_name,
                    "IMPORT", rows_affected, session_id, user_db
                ))
            conn.commit()

            imported_files.append(file)

        # Calculate approximate data size
        data_size_mb = round((total_rows * 200) / (1024 * 1024), 2)

        return jsonify({
            "message": "Data imported successfully",
            "status": "success",
            "imported_files": imported_files,
            "data": {
                "summary": {
                    "total_rows": total_rows,
                    "total_columns": sum(t["columns"] for t in affected_tables_info),
                    "data_size_mb": max(data_size_mb, 0.01),
                    "last_sync": "Just now"
                },
                "tables": affected_tables_info
            }
        })

    except Exception as e:
        print("ERROR:", str(e))
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
