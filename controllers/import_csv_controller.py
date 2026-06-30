# import os
# import json
# import pandas as pd
# import pymysql
# from flask import request, jsonify
# from database.config import MYSQL_CONFIG
# from database.csv_processor import _infer_schema, _apply_schema, MONEY_PRECISION, MONEY_SCALE

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# UPLOAD_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "uploads"))

# def import_csv_data(get_db_connection):
#     data = request.json
#     user_id = data.get("user_id")
#     connection_id = data.get("connection_id")
#     session_id = data.get("session_id")

#     if not user_id or not connection_id or not session_id:
#         return jsonify({"error": "Missing parameters"}), 400

#     try:
#         conn = get_db_connection()
#         cursor = conn.cursor(dictionary=True)

#         imported_files = []
#         affected_tables_info = []
#         total_rows = 0

#         # fetch credential
#         query = """
#         SELECT dc.credential
#         FROM database_credential dc
#         WHERE (dc.connection_id = %s OR dc.connection_id IS NULL)
#         AND dc.user_id = %s
#         AND dc.session_id = %s
#         ORDER BY dc.connection_id DESC
#         LIMIT 1
#         """
#         cursor.execute(query, (connection_id, user_id, session_id))
#         result = cursor.fetchone()

#         if not result:
#             return jsonify({"status": "error", "message": "Credential not found"}), 404

#         credential = json.loads(result["credential"])
#         files = credential.get("files", [])

#         # fetch user db
#         cursor.execute("SELECT name,new_user_db FROM users WHERE id=%s", (user_id,))
#         user_data = cursor.fetchone()

#         username = user_data["name"]
#         user_db = user_data["new_user_db"]

#         # connect user database
#         user_conn = pymysql.connect(
#             host=MYSQL_CONFIG["host"],
#             user=MYSQL_CONFIG["user"],
#             password=MYSQL_CONFIG["password"],
#             database=user_db,
#             cursorclass=pymysql.cursors.DictCursor,
#             autocommit=True
#         )
#         user_cursor = user_conn.cursor()

#         files_in_folder = os.listdir(UPLOAD_DIR)

#         # Pre-fetch existing tables and their schemas to enable smart merging
#         user_cursor.execute("SHOW TABLES")
#         existing_tables = [list(row.values())[0] for row in user_cursor.fetchall()]
        
#         schema_map = {}
#         for t in existing_tables:
#             user_cursor.execute(f"SHOW COLUMNS FROM `{t}`")
#             t_cols = [r['Field'] for r in user_cursor.fetchall()]
#             schema_map[t] = set(t_cols)

#         for file in files:
#             if not file.lower().endswith('.csv'):
#                 continue

#             matched_file = next((f for f in files_in_folder if f.lower() == file.lower()), None)
#             if not matched_file:
#                 continue

#             file_path = os.path.join(UPLOAD_DIR, matched_file)
#             df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str)

#             if df.empty:
#                 continue

#             # Standardize column names: strip whitespace, replace spaces and dots with underscores
#             df.columns = df.columns.str.strip().str.replace(" ", "_").str.replace(".", "_", regex=False)
            
#             # Infer schema and apply data types using csv_processor
#             schema = _infer_schema(df.head(50000))
#             df = _apply_schema(df, schema)
            
#             df = df.where(pd.notnull(df), None)
#             df_cols_set = set(df.columns)
#             num_columns = len(df.columns)

#             # Check if columns match any existing table (Smart Schema Detection)
#             matched_table = None
#             for t_name, t_cols_set in schema_map.items():
#                 if df_cols_set == t_cols_set:
#                     matched_table = t_name
#                     break

#             # If match found, use that table. Else, create new table named after file.
#             table_name = matched_table if matched_table else file.replace(".csv", "").lower()

#             if not matched_table:
#                 # Create the new table
#                 col_defs = []
#                 for c in df.columns:
#                     kind = schema.get(c, {}).get('kind', 'text')
#                     if kind == 'numeric':
#                         col_defs.append(f"`{c}` DECIMAL({MONEY_PRECISION}, {MONEY_SCALE})")
#                     elif kind == 'int':
#                         col_defs.append(f"`{c}` BIGINT")
#                     elif kind == 'date':
#                         col_defs.append(f"`{c}` DATE")
#                     else:
#                         col_defs.append(f"`{c}` TEXT")
                
#                 cols = ", ".join(col_defs)
#                 create_query = f"CREATE TABLE IF NOT EXISTS `{table_name}` ({cols})"
#                 user_cursor.execute(create_query)
#                 # Register in schema_map so subsequent files in this batch can match it
#                 schema_map[table_name] = df_cols_set

#             # 1. Deduplicate within the dataframe itself
#             df = df.drop_duplicates()
            
#             # Prepare data values
#             data_values = [tuple(None if pd.isna(x) else x for x in row) for row in df.values]
            
#             # 2. Setup Temporary Table
#             temp_table_name = "temp_csv_import_table"
#             user_cursor.execute(f"DROP TEMPORARY TABLE IF EXISTS `{temp_table_name}`")
#             user_cursor.execute(f"CREATE TEMPORARY TABLE `{temp_table_name}` LIKE `{table_name}`")

#             # 3. Bulk Insert into Temporary Table
#             columns = ", ".join([f"`{c}`" for c in df.columns])
#             placeholders = ", ".join(["%s"] * len(df.columns))
#             insert_temp_query = f"INSERT INTO `{temp_table_name}` ({columns}) VALUES ({placeholders})"
#             user_cursor.executemany(insert_temp_query, data_values)

#             # 4. Insert into Main Table avoiding duplicates
#             # Build the ON conditions for all columns using NULL-safe equal (<=>)
#             join_conditions = " AND ".join([f"`{table_name}`.`{c}` <=> `{temp_table_name}`.`{c}`" for c in df.columns])

#             insert_main_query = f"""
#             INSERT INTO `{table_name}` ({columns})
#             SELECT {columns} FROM `{temp_table_name}`
#             WHERE NOT EXISTS (
#                 SELECT 1 FROM `{table_name}`
#                 WHERE {join_conditions}
#             )
#             """
#             user_cursor.execute(insert_main_query)
#             rows_inserted = user_cursor.rowcount

#             # 5. Drop Temporary Table
#             user_cursor.execute(f"DROP TEMPORARY TABLE `{temp_table_name}`")

#             total_rows += rows_inserted
#             imported_files.append(file)
#             affected_tables_info.append({
#                 "table": table_name,
#                 "rows": rows_inserted,
#                 "columns": num_columns
#             })

#             log_query = """
#             INSERT INTO external_db_sync_log
#             (user_id,username,external_database,table_name,
#             action_type,rows_affected,session_id,new_user_db)
#             VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
#             """
#             cursor.execute(log_query, (
#                 user_id, username, file, table_name,
#                 "IMPORT", rows_inserted, session_id, user_db
#             ))
#             conn.commit()

#         # Calculate approximate data size
#         data_size_mb = round((total_rows * 200) / (1024 * 1024), 2)  # Rough estimate

#         return jsonify({
#             "message": "Data imported successfully",
#             "status": "success",
#             "imported_files": imported_files,
#             "data": {
#                 "summary": {
#                     "total_rows": total_rows,
#                     "total_columns": sum(t["columns"] for t in affected_tables_info),
#                     "data_size_mb": max(data_size_mb, 0.01),
#                     "last_sync": "Just now"
#                 },
#                 "tables": affected_tables_info
#             }
#         })

#     except Exception as e:
#         print("ERROR:", str(e))
#         return jsonify({
#             "status": "error",
#             "message": str(e)
#         }), 500



import os
import json
import pandas as pd
import pymysql
from flask import request, jsonify
from database.config import MYSQL_CONFIG
from database.csv_processor import _infer_schema, _apply_schema, MONEY_PRECISION, MONEY_SCALE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "uploads"))

def import_csv_data(get_db_connection):
    data = request.json
    user_id = data.get("user_id")
    session_id = data.get("session_id")
    
    # Handle both single connection_id and multiple connection_ids
    connection_id_data = data.get("connection_id")
    if isinstance(connection_id_data, list):
        connection_ids = connection_id_data
    elif connection_id_data:
        connection_ids = [connection_id_data]
    else:
        connection_ids = data.get("connection_ids", [])

    if not user_id or not connection_ids or not session_id:
        return jsonify({"error": "Missing parameters"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        imported_files = []
        unique_tables_info = {}

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
        
        all_files = []
        for cid in connection_ids:
            cursor.execute(query, (cid, user_id, session_id))
            result = cursor.fetchone()
            if result:
                credential = json.loads(result["credential"])
                all_files.extend(credential.get("files", []))
                
        # Remove duplicates while preserving order
        files = list(dict.fromkeys(all_files))

        if not files:
            return jsonify({"status": "error", "message": "Credentials not found or no files to import"}), 404

        # fetch workspace db
        cursor.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
        workspace_data = cursor.fetchone()
        
        if not workspace_data or not workspace_data.get("workspace_db"):
            return jsonify({"status": "error", "message": "Workspace database not found"}), 404
            
        user_db = workspace_data["workspace_db"]
        
        # also fetch username for logs
        cursor.execute("SELECT name FROM users WHERE id=%s", (user_id,))
        user_data = cursor.fetchone()
        username = user_data["name"] if user_data else "Unknown"

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

        # Pre-fetch existing tables and their schemas to enable smart merging
        user_cursor.execute("SHOW TABLES")
        existing_tables = [list(row.values())[0] for row in user_cursor.fetchall()]
        
        schema_map = {}
        for t in existing_tables:
            user_cursor.execute(f"SHOW COLUMNS FROM `{t}`")
            t_cols = [r['Field'] for r in user_cursor.fetchall()]
            schema_map[t] = set(t_cols)

        for file in files:
            if not file.lower().endswith('.csv'):
                continue

            matched_file = next((f for f in files_in_folder if f.lower() == file.lower()), None)
            if not matched_file:
                continue

            file_path = os.path.join(UPLOAD_DIR, matched_file)
            df = pd.read_csv(file_path, encoding="utf-8-sig", dtype=str)

            if df.empty:
                continue

            # Standardize column names: strip whitespace, replace spaces and dots with underscores
            df.columns = df.columns.str.strip().str.replace(" ", "_").str.replace(".", "_", regex=False)
            
            # Infer schema and apply data types using csv_processor
            schema = _infer_schema(df.head(50000))
            df = _apply_schema(df, schema)
            
            df = df.where(pd.notnull(df), None)
            df_cols_set = set(df.columns)
            num_columns = len(df.columns)

            # Check if columns match any existing table (Smart Schema Detection)
            matched_table = None
            for t_name, t_cols_set in schema_map.items():
                if df_cols_set == t_cols_set:
                    matched_table = t_name
                    break

            # If match found, use that table. Else, create new table named after file.
            table_name = matched_table if matched_table else file.replace(".csv", "").lower()

            if not matched_table:
                # Create the new table
                col_defs = []
                for c in df.columns:
                    kind = schema.get(c, {}).get('kind', 'text')
                    if kind == 'numeric':
                        col_defs.append(f"`{c}` DECIMAL({MONEY_PRECISION}, {MONEY_SCALE})")
                    elif kind == 'int':
                        col_defs.append(f"`{c}` BIGINT")
                    elif kind == 'date':
                        col_defs.append(f"`{c}` DATE")
                    else:
                        col_defs.append(f"`{c}` TEXT")
                
                cols = ", ".join(col_defs)
                create_query = f"CREATE TABLE IF NOT EXISTS `{table_name}` ({cols})"
                user_cursor.execute(create_query)
                # Register in schema_map so subsequent files in this batch can match it
                schema_map[table_name] = df_cols_set

            # Check if this specific file was already imported in this session
            cursor.execute("SELECT id FROM external_db_sync_log WHERE session_id=%s AND external_database=%s AND action_type='IMPORT'", (session_id, file))
            already_imported = cursor.fetchone() is not None
            
            rows_inserted = 0
            
            if not already_imported:
                # Define keywords to identify transaction tables
                transaction_keywords = ['invoice', 'sale', 'order', 'transaction', 'receipt']
                is_transaction = any(kw in table_name.lower() for kw in transaction_keywords)

                if is_transaction:
                    # 1. Bulk Insert into Main Table directly (Append Only) for Transaction tables
                    data_values = [tuple(None if pd.isna(x) else x for x in row) for row in df.values]
                    columns = ", ".join([f"`{c}`" for c in df.columns])
                    placeholders = ", ".join(["%s"] * len(df.columns))
                    insert_main_query = f"INSERT INTO `{table_name}` ({columns}) VALUES ({placeholders})"
                    
                    user_cursor.executemany(insert_main_query, data_values)
                    rows_inserted = len(data_values)
                else:
                    # 1. Deduplicate within the dataframe itself for Master tables
                    df = df.drop_duplicates()
                    data_values = [tuple(None if pd.isna(x) else x for x in row) for row in df.values]
                    
                    columns = ", ".join([f"`{c}`" for c in df.columns])
                    placeholders = ", ".join(["%s"] * len(df.columns))
                    
                    # 2. Setup Temporary Table
                    temp_table_name = "temp_csv_import_table"
                    user_cursor.execute(f"DROP TEMPORARY TABLE IF EXISTS `{temp_table_name}`")
                    user_cursor.execute(f"CREATE TEMPORARY TABLE `{temp_table_name}` LIKE `{table_name}`")

                    # 3. Bulk Insert into Temporary Table
                    insert_temp_query = f"INSERT INTO `{temp_table_name}` ({columns}) VALUES ({placeholders})"
                    user_cursor.executemany(insert_temp_query, data_values)

                    # 4. Insert into Main Table avoiding duplicates
                    join_conditions = " AND ".join([f"`{table_name}`.`{c}` <=> `{temp_table_name}`.`{c}`" for c in df.columns])

                    insert_main_query = f"""
                    INSERT INTO `{table_name}` ({columns})
                    SELECT {columns} FROM `{temp_table_name}`
                    WHERE NOT EXISTS (
                        SELECT 1 FROM `{table_name}`
                        WHERE {join_conditions}
                    )
                    """
                    user_cursor.execute(insert_main_query)
                    rows_inserted = user_cursor.rowcount

                    # 5. Drop Temporary Table
                    user_cursor.execute(f"DROP TEMPORARY TABLE `{temp_table_name}`")

            # 6. Get actual total rows in the table for reporting
            user_cursor.execute(f"SELECT COUNT(*) as cnt FROM `{table_name}`")
            table_total_rows = user_cursor.fetchone()['cnt']

            imported_files.append(file)
            unique_tables_info[table_name] = {
                "table": table_name,
                "rows": table_total_rows,
                "columns": num_columns
            }

            if not already_imported:
                log_query = """
                INSERT INTO external_db_sync_log
                (user_id,username,external_database,table_name,
                action_type,rows_affected,session_id,new_user_db)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """
                cursor.execute(log_query, (
                    user_id, username, file, table_name,
                    "IMPORT", rows_inserted, session_id, user_db
                ))
                conn.commit()

        affected_tables_info = list(unique_tables_info.values())
        total_rows = sum(t["rows"] for t in affected_tables_info)
        total_columns = sum(t["columns"] for t in affected_tables_info)

        # Calculate approximate data size
        data_size_mb = round((total_rows * 200) / (1024 * 1024), 2)  # Rough estimate

        return jsonify({
            "message": "Data imported successfully",
            "status": "success",
            "imported_files": imported_files,
            "data": {
                "summary": {
                    "total_rows": total_rows,
                    "total_columns": total_columns,
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

