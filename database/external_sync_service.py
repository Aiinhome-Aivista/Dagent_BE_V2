import json
import pymysql
from database.config import MYSQL_CONFIG
from helper.workspace_wise_store_procedures import run_stored_procedures
import math

def clean_row(row, col_types=None):
    cleaned = []
    for i, v in enumerate(row):
        if isinstance(v, float) and math.isnan(v):
            cleaned.append(None)
        elif col_types and i < len(col_types) and col_types[i] in ['json', 'jsonb']:
            if v is None:
                cleaned.append(None)
            else:
                cleaned.append(json.dumps(v))
        elif isinstance(v, (dict, list)):
            cleaned.append(json.dumps(v))
        else:
            cleaned.append(v)
    return tuple(cleaned)

def get_source_column_types(source_cursor, table_name, db_type, schema='public'):
    if db_type in ["postgresql", "postgres"]:
        source_cursor.execute("""
            SELECT data_type 
            FROM information_schema.columns 
            WHERE table_name = %s AND table_schema = %s
            ORDER BY ordinal_position
        """, (table_name, schema))
        return [r[0].lower() for r in source_cursor.fetchall()]
    return None

def resolve_source_table(source_cursor, target_table_name, db_name, db_type, connection_schema=None):
    if db_type in ["postgresql", "postgres"]:
        prefix = f"{db_name}_"
        if target_table_name.startswith(prefix):
            remainder = target_table_name[len(prefix):]
        else:
            remainder = target_table_name

        if connection_schema:
            return remainder, connection_schema

        source_cursor.execute("""
            SELECT table_name, table_schema
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND table_type = 'BASE TABLE'
        """)
        all_tables = source_cursor.fetchall()
        for t_name, t_schema in all_tables:
            if remainder == f"{t_schema}_{t_name}":
                return t_name, t_schema
            if remainder == t_name:
                return t_name, t_schema
        
        return remainder, "public"
    else:
        prefix = f"{db_name}_"
        if target_table_name.startswith(prefix):
            remainder = target_table_name[len(prefix):]
        else:
            remainder = target_table_name
        return remainder, None

def postgres_to_mysql_type(data_type, char_len):
    dt = data_type.lower()
    if dt in ['integer', 'int', 'serial']:
        return 'INT'
    elif dt in ['bigint', 'bigserial']:
        return 'BIGINT'
    elif dt in ['smallint', 'smallserial']:
        return 'SMALLINT'
    elif dt in ['boolean', 'bool']:
        return 'TINYINT(1)'
    elif 'character varying' in dt or 'varchar' in dt:
        length = char_len if char_len else 255
        return f'VARCHAR({length})'
    elif 'character' in dt or 'char' in dt:
        length = char_len if char_len else 1
        return f'CHAR({length})'
    elif dt == 'text':
        return 'TEXT'
    elif 'double precision' in dt or dt == 'float8':
        return 'DOUBLE'
    elif dt in ['real', 'float4', 'float']:
        return 'FLOAT'
    elif dt in ['numeric', 'decimal']:
        return 'DECIMAL(20, 6)'
    elif 'timestamp' in dt:
        return 'DATETIME'
    elif dt == 'date':
        return 'DATE'
    elif 'time' in dt:
        return 'TIME'
    elif dt in ['json', 'jsonb']:
        return 'JSON'
    elif dt == 'bytea':
        return 'LONGBLOB'
    else:
        return 'TEXT'

def get_source_table_select_name(table_name, db_type):
    if db_type in ["postgresql", "postgres"]:
        return f'"{table_name}"'
    return f"`{table_name}`"

def get_source_columns(source_cursor, table_name, db_type, schema='public'):
    if db_type in ["postgresql", "postgres"]:
        source_cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND table_schema = %s
            ORDER BY ordinal_position
        """, (table_name, schema))
        return [r[0] for r in source_cursor.fetchall()]
    else:
        source_cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        return [c[0] for c in source_cursor.fetchall()]

def sync_external_database(user_id, connection_id, session_id):

    # fetch credential from database_credential table
    cred_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    with cred_conn.cursor() as cursor:

        print("INPUT VALUES ->", user_id, connection_id, session_id)

        cursor.execute("SELECT user_id, connection_id, session_id FROM database_credential")
        print("DB ROWS ->", cursor.fetchall())

        cursor.execute("""
        SELECT credential, db_type
        FROM database_credential
        WHERE user_id=%s AND connection_id=%s AND session_id=%s
        """, (user_id, connection_id, session_id))

        result = cursor.fetchone()

        print("QUERY RESULT ->", result)

        if not result:
            raise Exception("Database credential not found")

        external_db = json.loads(result[0])
        db_type = result[1]

    cred_conn.close()

    db_type = db_type.lower() if db_type else "mysql"

    # get username from users table first
    user_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    with user_conn.cursor() as cursor:
        # Fetch username from users table
        cursor.execute("SELECT email FROM users WHERE id=%s", (user_id,))
        user_result = cursor.fetchone()
        if not user_result:
            raise Exception("User not found")
        
        email = user_result[0]
        username = email.split("@")[0]

        # Fetch workspace database from workspaces table
        cursor.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
        workspace_result = cursor.fetchone()
        
        if not workspace_result or not workspace_result[0]:
            raise Exception("Workspace database not found for this session")
            
        new_user_db = workspace_result[0]

    user_conn.close()
    user_db_name = new_user_db

    if db_type in ['csv_upload', 'csv_chunk_upload', 'sql_upload', 'sql_chunk_upload', 'doc_upload', 'doc_chunk_upload']:
        total_rows = 0
        total_columns = 0
        table_summary = []
        
        try:
            target_conn = pymysql.connect(
                host=MYSQL_CONFIG["host"],
                user=MYSQL_CONFIG["user"],
                password=MYSQL_CONFIG["password"],
                database=user_db_name,
                autocommit=True
            )
            
            # For doc upload, wait up to 5 minutes for the background job to create the table
            if db_type in ['doc_upload', 'doc_chunk_upload']:
                import time
                for _ in range(150):
                    with target_conn.cursor() as cursor:
                        cursor.execute("SHOW TABLES")
                        current_tables = [t[0] for t in cursor.fetchall()]
                    if "workspace_files" in current_tables:
                        # Wait an extra few seconds to allow data insertion to complete
                        time.sleep(2)
                        break
                    time.sleep(2)
            
            with target_conn.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                tables = [t[0] for t in cursor.fetchall()]
                for t in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM `{t}`")
                    row_count = cursor.fetchone()[0]
                    cursor.execute(f"SHOW COLUMNS FROM `{t}`")
                    col_count = len(cursor.fetchall())
                    total_rows += row_count
                    total_columns += col_count
                    table_summary.append({"table": t, "rows": row_count, "columns": col_count})
                
                # Accurately calculate data size from information_schema
                cursor.execute("""
                    SELECT SUM(data_length + index_length) 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                """, (user_db_name,))
                size_result = cursor.fetchone()[0]
                total_size_bytes = size_result if size_result else 0
                data_size_mb = round(total_size_bytes / (1024 * 1024), 2)
                
            target_conn.close()
        except Exception as e:
            print("Error fetching tables for file upload:", e)
            data_size_mb = 0.0
            
        return {
            "summary": {
                "total_rows": total_rows,
                "total_columns": total_columns,
                "data_size_mb": data_size_mb,
                "last_sync": "Just now"
            },
            "tables": table_summary,
            "situations": [],
            "new_tables": [t["table"] for t in table_summary]
        }

    if db_type == 'ftp':
        import ftplib
        import os
        import uuid
        import pandas as pd
        from database.config import UPLOAD_FOLDER
        
        host       = external_db.get("host", "")
        port       = int(external_db.get("port", 21))
        username   = external_db.get("username", "")
        password   = external_db.get("password", "")
        remote_dir = external_db.get("remote_dir", "/")
        passive    = external_db.get("passive_mode", True)
        
        ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=30)
        ftp.login(username, password)
        if passive:
            ftp.set_pasv(True)
            
        ftp.cwd(remote_dir)
        file_list = []
        
        def _parse_list(line):
            parts = line.split()
            if len(parts) >= 9:
                name = " ".join(parts[8:])
                size = parts[4] if parts[4].isdigit() else "0"
                is_dir = parts[0].startswith("d")
                file_list.append({"name": name, "size": int(size), "is_dir": is_dir})
        
        ftp.retrlines("LIST", _parse_list)
        files = [f for f in file_list if f.get("name") and not f.get("is_dir")]
        
        csv_files = []
        sql_files = []
        table_summary = []
        total_rows = 0
        total_columns = 0
        total_size_bytes = 0
        
        for file_info in files:
            fname = file_info["name"]
            local_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4()}_{fname}")
            
            with open(local_path, "wb") as f:
                ftp.retrbinary(f"RETR {fname}", f.write)
                
            size_bytes = os.path.getsize(local_path)
            total_size_bytes += size_bytes
            
            rows = 0
            cols = 0
            
            if fname.lower().endswith(".csv"):
                csv_files.append(local_path)
                try:
                    df_chunk = pd.read_csv(local_path, nrows=0, encoding="latin1", on_bad_lines="skip")
                    cols = len(df_chunk.columns)
                    with open(local_path, encoding="latin1") as f_csv:
                        rows = sum(1 for _ in f_csv) - 1
                        if rows < 0: rows = 0
                except:
                    pass
            elif fname.lower().endswith(".sql"):
                sql_files.append(local_path)
            
            total_rows += rows
            total_columns += cols
            
            table_summary.append({
                "table": fname,
                "rows": rows,
                "columns": cols
            })
            
        ftp.quit()

        # Log to external_db_sync_log
        log_conn = pymysql.connect(
            host=MYSQL_CONFIG["host"],
            user=MYSQL_CONFIG["user"],
            password=MYSQL_CONFIG["password"],
            database=MYSQL_CONFIG["database"]
        )
        with log_conn.cursor() as cursor:
            for summary in table_summary:
                cursor.execute(f"""
                    INSERT INTO `{MYSQL_CONFIG["database"]}`.external_db_sync_log
                    (user_id, new_user_db, username, external_database, table_name, action_type, rows_affected, session_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    user_id,
                    user_db_name,
                    username,
                    external_db.get("name", "FTP Connector"),
                    summary["table"],
                    "NEW_TABLE",
                    summary["rows"],
                    session_id
                ))
            log_conn.commit()
        log_conn.close()
        
        # Schedule the background processing
        if user_db_name:
            from controllers.uploads_controller import scheduler as up_scheduler
            from database.csv_processor import process_csv_job
            from database.sql_processor import process_sql_job
            
            db_user = MYSQL_CONFIG.get("user")
            db_pass = MYSQL_CONFIG.get("password")
            db_host = MYSQL_CONFIG.get("host")
            db_port = int(MYSQL_CONFIG.get("port", 3306))

            if csv_files:
                up_scheduler.add_job(
                    func=process_csv_job,
                    args=[csv_files, user_db_name, db_host, db_user, db_pass, db_port],
                    trigger='date',
                    id=str(uuid.uuid4()),
                    replace_existing=True
                )
                
            if sql_files:
                up_scheduler.add_job(
                    func=process_sql_job,
                    args=[sql_files, user_db_name, db_host, db_user, db_pass, db_port],
                    trigger='date',
                    id=str(uuid.uuid4()),
                    replace_existing=True
                )
        
        data_size_mb = round(total_size_bytes / (1024 * 1024), 2)
        
        return {
            "summary": {
                "total_rows": total_rows,
                "total_columns": total_columns,
                "data_size_mb": data_size_mb,
                "last_sync": "Just now"
            },
            "tables": table_summary,
            "situations": [],
            "new_tables": [t["table"] for t in table_summary]
        }

    if "port" not in external_db or not str(external_db.get("port", "")).strip():
        external_db["port"] = "5432" if "postgres" in db_type else "3306"

    required_fields = ["host", "port","username", "password", "database"]
    for field in required_fields:
        if field not in external_db or not external_db[field]:
            raise Exception(f"Missing external DB field: {field}")

    # check if first sync
    log_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    with log_conn.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM external_db_sync_log
            WHERE username=%s AND external_database=%s AND session_id=%s
        """, (username, external_db["database"], session_id))

        sync_count = cursor.fetchone()[0]

    log_conn.close()

    first_sync = sync_count == 0

    if db_type in ["postgresql", "postgres"]:
        import psycopg2
        source_conn = psycopg2.connect(
            host=external_db["host"],
            port=external_db.get("port", 5432),
            user=external_db["username"],
            password=external_db["password"],
            database=external_db["database"]
        )
        source_conn.autocommit = True
    else:
        source_conn = pymysql.connect(
            host=external_db["host"],
            port=external_db.get("port", 3306),
            user=external_db["username"],
            password=external_db["password"],
            database=external_db["database"],
            autocommit=True
        )

    target_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=user_db_name,
        autocommit=True
    )

    new_tables = []
    updated_tables = []
    situations = []
    table_summary = []
    total_rows = 0
    total_columns = 0

    try:
        with source_conn.cursor() as source_cursor, target_conn.cursor() as target_cursor:

            log_query = f"""
            INSERT INTO `{MYSQL_CONFIG["database"]}`.external_db_sync_log
            (user_id, new_user_db ,username, external_database, table_name, action_type, rows_affected, session_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """

            schema_name = external_db.get("schema")
            if db_type in ["postgresql", "postgres"]:
                if schema_name:
                    source_cursor.execute(f"SET search_path TO {schema_name}")
                    source_cursor.execute("""
                        SELECT table_name, %s::varchar as table_schema
                        FROM information_schema.tables 
                        WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    """, (schema_name, schema_name))
                else:
                    source_cursor.execute("""
                        SELECT table_name, table_schema
                        FROM information_schema.tables 
                        WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast') 
                          AND table_type = 'BASE TABLE'
                    """)
                source_tables = [(r[0], r[1]) for r in source_cursor.fetchall()]
            else:
                source_cursor.execute("SHOW TABLES")
                source_tables = [(t[0], None) for t in source_cursor.fetchall()]

            target_cursor.execute("SHOW TABLES")
            target_tables = [t[0] for t in target_cursor.fetchall()]

            # Disable FK
            target_cursor.execute("SET FOREIGN_KEY_CHECKS=0")

            for table_name, schema_name_from_db in source_tables:
                if db_type in ["postgresql", "postgres"] and schema_name_from_db:
                    source_cursor.execute(f"SET search_path TO {schema_name_from_db}")
                
                active_schema = schema_name_from_db if schema_name_from_db else schema_name

                # count rows
                source_cursor.execute(f"SELECT COUNT(*) FROM {get_source_table_select_name(table_name, db_type)}")
                row_count = source_cursor.fetchone()[0]

                # count columns
                columns = get_source_columns(source_cursor, table_name, db_type, active_schema)
                col_count = len(columns)

                total_rows += row_count
                total_columns += col_count

                if db_type in ["postgresql", "postgres"] and not schema_name:
                    table_display_name = f"{external_db['database']}.{active_schema}.{table_name}"
                else:
                    table_display_name = f"{external_db['database']}.{table_name}"

                table_summary.append({
                    "table": table_display_name,
                    "rows": row_count,
                    "columns": col_count
                })

                if db_type in ["postgresql", "postgres"] and not schema_name:
                    new_table_name = f"{external_db['database']}_{active_schema}_{table_name}"
                else:
                    new_table_name = f"{external_db['database']}_{table_name}"

                # ---------- NEW TABLE ----------
                if new_table_name not in target_tables:

                    if first_sync:
                        new_tables.append(new_table_name)

                        if db_type in ["postgresql", "postgres"]:
                            source_cursor.execute("""
                                SELECT column_name, data_type, is_nullable, character_maximum_length
                                FROM information_schema.columns
                                WHERE table_name = %s AND table_schema = %s
                                ORDER BY ordinal_position
                            """, (table_name, active_schema))
                            cols_info = source_cursor.fetchall()
                            col_defs = []
                            for col_name, data_type, is_nullable, char_len in cols_info:
                                mysql_type = postgres_to_mysql_type(data_type, char_len)
                                null_def = "NULL" if is_nullable == "YES" else "NOT NULL"
                                col_defs.append(f"`{col_name}` {mysql_type} {null_def}")
                            create_query = f"CREATE TABLE `{new_table_name}` (\n  " + ",\n  ".join(col_defs) + "\n)"
                        else:
                            source_cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
                            create_query = source_cursor.fetchone()[1]

                            create_query = create_query.replace(
                                f"CREATE TABLE `{table_name}`",
                                f"CREATE TABLE `{new_table_name}`"
                            )

                        target_cursor.execute(create_query)

                        source_cursor.execute(f"SELECT * FROM {get_source_table_select_name(table_name, db_type)}")
                        rows = source_cursor.fetchall()

                        inserted_count = 0

                        if rows:
                            placeholders = ", ".join(["%s"] * len(rows[0]))

                            insert_query = f"""
                            INSERT INTO `{new_table_name}`
                            VALUES ({placeholders})
                            """

                            col_types = get_source_column_types(source_cursor, table_name, db_type, active_schema)
                            cleaned_rows = [clean_row(row, col_types) for row in rows]
                            target_cursor.executemany(insert_query, cleaned_rows)
                            inserted_count = len(rows)

                        #  LOG INSERT
                        target_cursor.execute(
                            log_query,
                            (   user_id,
                                new_user_db,
                                username,
                                external_db["database"],
                                new_table_name,
                                "NEW_TABLE",
                                inserted_count,
                                session_id
                            )
                        )

                    else:
                        situations.append({
                            "type": "NEW_DATASET",
                            "table": new_table_name,
                            "message": f"I see there are new data sources available: {new_table_name}. Do you want to add them?",
                            "buttons": ["Yes", "No"]
                        })

                else:

                    # check new columns
                    source_columns = get_source_columns(source_cursor, table_name, db_type, active_schema)

                    target_cursor.execute(f"SHOW COLUMNS FROM `{new_table_name}`")
                    target_columns = [c[0] for c in target_cursor.fetchall()]

                    new_columns = set(source_columns) - set(target_columns)
                
                    if new_columns and not first_sync:
                        if not any(s["table"] == new_table_name and s["type"]=="SCHEMA_CHANGE" for s in situations):
                            situations.append({
                                "type": "SCHEMA_CHANGE",
                                "table": new_table_name,
                                "message": f"New columns detected in {new_table_name}: {', '.join(new_columns)}",
                                "buttons": ["Yes", "No"]
                            })


                    source_cursor.execute(f"SELECT COUNT(*) FROM {get_source_table_select_name(table_name, db_type)}")
                    source_count = source_cursor.fetchone()[0]

                    target_cursor.execute(f"SELECT COUNT(*) FROM `{new_table_name}`")
                    target_count = target_cursor.fetchone()[0]

                    if source_count > target_count and not first_sync:
                        if not any(s["table"] == new_table_name for s in situations):
                            situations.append({
                                "type": "DATA_DISCREPANCY",
                                "table": new_table_name,
                                "message": f"I found some discrepancy in table {new_table_name}. I'm doing reconciliation.",
                                "buttons": ["Yes", "No"]
                            })

            data_size_mb = round((total_rows * total_columns * 8) / (1024 * 1024), 2)

            # Enable FK
            target_cursor.execute("SET FOREIGN_KEY_CHECKS=1")

            if not situations and not new_tables:

                target_cursor.execute(
                    log_query,
                    (   user_id,
                        new_user_db,
                        username,
                        external_db["database"],
                        "ALL_TABLES",
                        "NO_CHANGE",
                        0,
                        session_id
                    )
                )

    except Exception as e:

        situations.append({
            "type": "FAILED_ATTEMPT",
            "message": "I see that my last attempt failed. I'm trying again.",
            "buttons": ["Retry", "No"]
        })

        raise e

    finally:
        source_conn.close()
        target_conn.close()

    return {
        "summary": {
            "total_rows": total_rows,
            "total_columns": total_columns,
            "data_size_mb": data_size_mb,
            "last_sync": "Just now"
        },
        "tables": table_summary,
        "situations": situations,
        "new_tables": new_tables
    }

 
def apply_external_sync(user_id, connection_id, session_id, table):

    # fetch credential from database_credential table
    cred_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    with cred_conn.cursor() as cursor:
        cursor.execute("""
            SELECT credential, db_type
            FROM database_credential
            WHERE user_id=%s AND connection_id=%s AND session_id=%s
        """, (user_id, connection_id, session_id))

        result = cursor.fetchone()

        if not result:
            raise Exception("Database credential not found")

        external_db = json.loads(result[0])
        db_type = result[1]

    cred_conn.close()

    db_type = db_type.lower() if db_type else "mysql"

    # get username from users table
    user_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    with user_conn.cursor() as cursor:
        # Fetch username from users table
        cursor.execute("SELECT email FROM users WHERE id=%s", (user_id,))
        user_result = cursor.fetchone()
        if not user_result:
            raise Exception("User not found")
        
        email = user_result[0]
        username = email.split("@")[0]

        # Fetch workspace database from workspaces table
        cursor.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
        workspace_result = cursor.fetchone()
        
        if not workspace_result or not workspace_result[0]:
            raise Exception("Workspace database not found for this session")
            
        new_user_db = workspace_result[0]

    user_conn.close()

    user_db_name = new_user_db

    # ensure user database exists
    db_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"]
    )

    with db_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{user_db_name}`")

    # Create stored procedures for this database
    try:
        # run_stored_procedures(user_db_name)
        pass
    except Exception as e:
        print(f"Error creating stored procedures for {user_db_name}: {e}")

    db_conn.close()

    if db_type in ['csv_upload', 'csv_chunk_upload', 'sql_upload', 'sql_chunk_upload', 'doc_upload', 'doc_chunk_upload']:
        return

    if db_type in ["postgresql", "postgres"]:
        import psycopg2
        source_conn = psycopg2.connect(
            host=external_db["host"],
            port=external_db.get("port", 5432),
            user=external_db["username"],
            password=external_db["password"],
            database=external_db["database"]
        )
        source_conn.autocommit = True
    else:
        source_conn = pymysql.connect(
            host=external_db["host"],
            port=external_db.get("port", 3306),
            user=external_db["username"],
            password=external_db["password"],
            database=external_db["database"],
            autocommit=True
        )

    target_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=user_db_name,
        autocommit=True
    )

    try:
        with source_conn.cursor() as source_cursor, target_conn.cursor() as target_cursor:

            connection_schema = external_db.get("schema")
            original_table, schema_name_from_db = resolve_source_table(
                source_cursor, table, external_db["database"], db_type, connection_schema
            )
            
            if db_type in ["postgresql", "postgres"] and schema_name_from_db:
                source_cursor.execute(f"SET search_path TO {schema_name_from_db}")
            
            active_schema = schema_name_from_db if schema_name_from_db else connection_schema

            col_types = get_source_column_types(source_cursor, original_table, db_type, active_schema)

            # check if table exists in target database
            target_cursor.execute("SHOW TABLES LIKE %s", (table,))
            exists = target_cursor.fetchone()

            # if table does not exist → create it
            if not exists:

                if db_type in ["postgresql", "postgres"]:
                    source_cursor.execute("""
                        SELECT column_name, data_type, is_nullable, character_maximum_length
                        FROM information_schema.columns
                        WHERE table_name = %s AND table_schema = %s
                        ORDER BY ordinal_position
                    """, (original_table, active_schema))
                    cols_info = source_cursor.fetchall()
                    col_defs = []
                    for col_name, data_type, is_nullable, char_len in cols_info:
                        mysql_type = postgres_to_mysql_type(data_type, char_len)
                        null_def = "NULL" if is_nullable == "YES" else "NOT NULL"
                        col_defs.append(f"`{col_name}` {mysql_type} {null_def}")
                    create_query = f"CREATE TABLE `{table}` (\n  " + ",\n  ".join(col_defs) + "\n)"
                else:
                    source_cursor.execute(f"SHOW CREATE TABLE `{original_table}`")
                    create_query = source_cursor.fetchone()[1]

                    create_query = create_query.replace(
                        f"CREATE TABLE `{original_table}`",
                        f"CREATE TABLE `{table}`"
                    )

                target_cursor.execute(create_query)

                # copy all rows
                source_cursor.execute(f"SELECT * FROM {get_source_table_select_name(original_table, db_type)}")
                rows = source_cursor.fetchall()

                if rows:
                    placeholders = ", ".join(["%s"] * len(rows[0]))

                    insert_query = f"""
                    INSERT INTO `{table}`
                    VALUES ({placeholders})
                    """

                    cleaned_rows = [clean_row(row, col_types) for row in rows]
                    target_cursor.executemany(insert_query, cleaned_rows)

                return

            source_cursor.execute(f"SELECT COUNT(*) FROM {get_source_table_select_name(original_table, db_type)}")
            source_count = source_cursor.fetchone()[0]

            target_cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            target_count = target_cursor.fetchone()[0]

            if source_count > target_count:

                offset = target_count

                limit_str = f"LIMIT {source_count-offset} OFFSET {offset}"
                source_cursor.execute(
                    f"SELECT * FROM {get_source_table_select_name(original_table, db_type)} {limit_str}"
                )

                rows = source_cursor.fetchall()

                if rows:

                    placeholders = ", ".join(["%s"] * len(rows[0]))

                    insert_query = f"""
                    INSERT INTO `{table}`
                    VALUES ({placeholders})
                    """

                    cleaned_rows = [clean_row(row, col_types) for row in rows]
                    target_cursor.executemany(insert_query, cleaned_rows)

    finally:
        source_conn.close()
        target_conn.close()

def apply_bulk_external_sync(user_id, connection_id, session_id, tables, action):
    """
    Service to handle multiple tables at once and support Replace All vs Update Existing.
    """
    # 1. Fetch credential from database_credential table
    cred_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    with cred_conn.cursor() as cursor:
        cursor.execute("""
            SELECT credential, db_type
            FROM database_credential
            WHERE user_id=%s AND connection_id=%s AND session_id=%s
        """, (user_id, connection_id, session_id))

        result = cursor.fetchone()
        if not result:
            raise Exception("Database credential not found")
        external_db = json.loads(result[0])
        db_type = result[1]
    cred_conn.close()

    db_type = db_type.lower() if db_type else "mysql"

    # 2. Get username from users table to find target database
    user_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    with user_conn.cursor() as cursor:
        # Fetch username from users table
        cursor.execute("SELECT email FROM users WHERE id=%s", (user_id,))
        user_result = cursor.fetchone()
        if not user_result:
            raise Exception("User not found")
        
        email = user_result[0]
        username = email.split("@")[0]

        # Fetch workspace database from workspaces table
        cursor.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
        workspace_result = cursor.fetchone()
        
        if not workspace_result or not workspace_result[0]:
            raise Exception("Workspace database not found for this session")
            
        new_user_db = workspace_result[0]
    user_conn.close()

    user_db_name = new_user_db

    if db_type in ['csv_upload', 'csv_chunk_upload', 'sql_upload', 'sql_chunk_upload', 'doc_upload', 'doc_chunk_upload']:
        return

    # 3. Connect to Source and Target Databases
    if db_type in ["postgresql", "postgres"]:
        import psycopg2
        source_conn = psycopg2.connect(
            host=external_db["host"],
            port=external_db.get("port", 5432),
            user=external_db["username"],
            password=external_db["password"],
            database=external_db["database"]
        )
        source_conn.autocommit = True
    else:
        source_conn = pymysql.connect(
            host=external_db["host"],
            port=external_db.get("port", 3306),
            user=external_db["username"],
            password=external_db["password"],
            database=external_db["database"],
            autocommit=True
        )

    target_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=user_db_name,
        autocommit=True
    )

    try:
        with source_conn.cursor() as source_cursor, target_conn.cursor() as target_cursor:
            
            connection_schema = external_db.get("schema")

            # Loop through all tables sent from the UI
            for table in tables:
                original_table, schema_name_from_db = resolve_source_table(
                    source_cursor, table, external_db["database"], db_type, connection_schema
                )
                
                if db_type in ["postgresql", "postgres"] and schema_name_from_db:
                    source_cursor.execute(f"SET search_path TO {schema_name_from_db}")
                
                active_schema = schema_name_from_db if schema_name_from_db else connection_schema

                col_types = get_source_column_types(source_cursor, original_table, db_type, active_schema)

                # ---------------------------------------------------------
                # LOGIC FOR "Replace All"
                # ---------------------------------------------------------
                if action == "replace":
                    # Drop the table if it exists to start fresh
                    target_cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
                    
                    # Get create schema from source
                    if db_type in ["postgresql", "postgres"]:
                        source_cursor.execute("""
                            SELECT column_name, data_type, is_nullable, character_maximum_length
                            FROM information_schema.columns
                            WHERE table_name = %s AND table_schema = %s
                            ORDER BY ordinal_position
                        """, (original_table, active_schema))
                        cols_info = source_cursor.fetchall()
                        col_defs = []
                        for col_name, data_type, is_nullable, char_len in cols_info:
                            mysql_type = postgres_to_mysql_type(data_type, char_len)
                            null_def = "NULL" if is_nullable == "YES" else "NOT NULL"
                            col_defs.append(f"`{col_name}` {mysql_type} {null_def}")
                        create_query = f"CREATE TABLE `{table}` (\n  " + ",\n  ".join(col_defs) + "\n)"
                    else:
                        source_cursor.execute(f"SHOW CREATE TABLE `{original_table}`")
                        create_query = source_cursor.fetchone()[1]
                        create_query = create_query.replace(
                            f"CREATE TABLE `{original_table}`",
                            f"CREATE TABLE `{table}`"
                        )
                    target_cursor.execute(create_query)

                    # Copy all rows
                    source_cursor.execute(f"SELECT * FROM {get_source_table_select_name(original_table, db_type)}")
                    rows = source_cursor.fetchall()

                    if rows:
                        placeholders = ", ".join(["%s"] * len(rows[0]))
                        insert_query = f"INSERT INTO `{table}` VALUES ({placeholders})"
                        cleaned_rows = [clean_row(row, col_types) for row in rows]
                        target_cursor.executemany(insert_query, cleaned_rows)   

                # ---------------------------------------------------------
                # LOGIC FOR "Update Existing" (Append / Create New)
                # ---------------------------------------------------------
                elif action == "update":
                    # check if table exists in target database
                    target_cursor.execute("SHOW TABLES LIKE %s", (table,))
                    exists = target_cursor.fetchone()

                    if not exists:
                        # Table doesn't exist, create and copy all
                        if db_type in ["postgresql", "postgres"]:
                            source_cursor.execute("""
                                SELECT column_name, data_type, is_nullable, character_maximum_length
                                FROM information_schema.columns
                                WHERE table_name = %s AND table_schema = %s
                                ORDER BY ordinal_position
                            """, (original_table, active_schema))
                            cols_info = source_cursor.fetchall()
                            col_defs = []
                            for col_name, data_type, is_nullable, char_len in cols_info:
                                mysql_type = postgres_to_mysql_type(data_type, char_len)
                                null_def = "NULL" if is_nullable == "YES" else "NOT NULL"
                                col_defs.append(f"`{col_name}` {mysql_type} {null_def}")
                            create_query = f"CREATE TABLE `{table}` (\n  " + ",\n  ".join(col_defs) + "\n)"
                        else:
                            source_cursor.execute(f"SHOW CREATE TABLE `{original_table}`")
                            create_query = source_cursor.fetchone()[1]
                            create_query = create_query.replace(
                                f"CREATE TABLE `{original_table}`",
                                f"CREATE TABLE `{table}`"
                            )
                        target_cursor.execute(create_query)

                        source_cursor.execute(f"SELECT * FROM {get_source_table_select_name(original_table, db_type)}")
                        rows = source_cursor.fetchall()

                        if rows:
                            placeholders = ", ".join(["%s"] * len(rows[0]))
                            insert_query = f"INSERT INTO `{table}` VALUES ({placeholders})"
                            cleaned_rows = [clean_row(row, col_types) for row in rows]
                            target_cursor.executemany(insert_query, cleaned_rows)
                    else:
                        # Table exists, append only new rows
                        source_cursor.execute(f"SELECT COUNT(*) FROM {get_source_table_select_name(original_table, db_type)}")
                        source_count = source_cursor.fetchone()[0]

                        target_cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                        target_count = target_cursor.fetchone()[0]

                        if source_count > target_count:
                            offset = target_count
                            limit_str = f"LIMIT {source_count-offset} OFFSET {offset}"
                            source_cursor.execute(
                                f"SELECT * FROM {get_source_table_select_name(original_table, db_type)} {limit_str}"
                            )
                            rows = source_cursor.fetchall()

                            if rows:
                                placeholders = ", ".join(["%s"] * len(rows[0]))
                                insert_query = f"INSERT INTO `{table}` VALUES ({placeholders})"
                                cleaned_rows = [clean_row(row, col_types) for row in rows]
                                target_cursor.executemany(insert_query, cleaned_rows)
                            

    finally:
        source_conn.close()
        target_conn.close()
