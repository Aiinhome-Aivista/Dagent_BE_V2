from flask import request, jsonify
from database.external_sync_service import apply_external_sync as apply_external_sync_service, sync_external_database , apply_bulk_external_sync


def _rebuild_kgraph_for_session(session_id, trigger_source):
    """
    Fires the same update-in-place Knowledge Graph build used by the CSV/SQL
    upload pipelines, for sources that write directly to the workspace DB
    (Tally, generic external DB connectors, per-table / bulk re-sync).
    Every one of these is "some other source" landing in the SAME workspace
    DB, so the graph must be UPDATED (with a kgraph_backups snapshot taken
    first), never silently skipped or rebuilt from scratch.
    """
    try:
        import pymysql
        from database.config import MYSQL_CONFIG
        from database.kgraph_builder import build_kgraph

        conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"],
                                password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
                row = cur.fetchone()
        finally:
            conn.close()

        workspace_db = row[0] if row else None
        if not workspace_db:
            return

        build_kgraph(
            workspace_db, MYSQL_CONFIG["host"], MYSQL_CONFIG["user"],
            MYSQL_CONFIG["password"], MYSQL_CONFIG.get("port", 3306),
            trigger_source=trigger_source
        )
    except Exception as kg_err:
        # Never let a kgraph rebuild failure break the sync response itself.
        print(f"[KGRAPH] post-sync build skipped ({trigger_source}): {kg_err}")


def connect_external_db():

    data = request.json

    user_id = int(data.get("user_id")) if data.get("user_id") else None
    
    connection_ids = data.get("connection_ids", [])
    if not connection_ids and data.get("connection_id"):
        connection_ids = [int(data.get("connection_id"))]
        
    session_id = data.get("session_id")         

    print("INPUT →", user_id, connection_ids, session_id)

    if not user_id or not connection_ids or not session_id:
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Missing data"
        }), 400

    tally_sync_result = None
    result = {"situations": [], "new_tables": [], "summary": {"data_size_mb": 0.0, "total_rows": 0, "total_columns": 0}, "tables": []}
    
    session_connections = []
    if connection_ids:
        try:
            import pymysql
            from database.config import MYSQL_CONFIG
            conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
            with conn.cursor() as cur:
                format_strings = ','.join(['%s'] * len(connection_ids))
                cur.execute(f"SELECT id, db_type FROM connection_history WHERE id IN ({format_strings})", tuple(connection_ids))
                session_connections = list(cur.fetchall())
            conn.close()
        except Exception as e:
            session_connections = [(cid, 'unknown') for cid in connection_ids]

    found_cids = [c[0] for c in session_connections]
    for cid in connection_ids:
        if cid not in found_cids:
            session_connections.append((cid, 'unknown'))

    for cid, ctype in session_connections:
        is_tally = False
        if ctype and ctype.strip().lower() == 'tally':
            is_tally = True
        else:
            try:
                import pymysql
                from database.config import MYSQL_CONFIG
                conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
                with conn.cursor() as cur:
                    cur.execute("SELECT db_type FROM database_credential WHERE connection_id=%s AND user_id=%s", (cid, user_id))
                    cred_row = cur.fetchone()
                    if cred_row and cred_row[0].strip().lower() == 'tally':
                        is_tally = True
                conn.close()
            except Exception:
                pass
        
        sync_res = {}
        if is_tally:
            try:
                import pymysql, json
                from database.config import MYSQL_CONFIG
                conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
                with conn.cursor() as cur:
                    cur.execute("SELECT credential FROM database_credential WHERE connection_id=%s AND user_id=%s", (cid, user_id))
                    clean_cred_data = json.loads(cur.fetchone()[0])
                    cur.execute("SELECT workspace_db FROM workspaces WHERE session_id=%s", (session_id,))
                    ws_row = cur.fetchone()
                    user_db_name = ws_row[0] if ws_row else ""
                    cur.execute("SELECT email FROM users WHERE id=%s", (user_id,))
                    user_row = cur.fetchone()
                    username_for_sync = user_row[0].split("@")[0] if user_row else "unknown"
                conn.close()

                from database.tally_connector import sync_tally_database
                print(f"[*] Triggering Auto-Sync for Tally (connection {cid})...")
                sync_res = sync_tally_database(user_id, cid, session_id, clean_cred_data, user_db_name, username_for_sync)
                tally_sync_result = sync_res
            except Exception as sync_e:
                print(f"[!] Auto-Sync failed for Tally ({cid}): {sync_e}")
                return jsonify({"status": False, "statuscode": 500, "message": str(sync_e), "error": str(sync_e)}), 500
        elif ctype not in ('doc_upload', 'doc_chunk_upload', 'csv_upload', 'csv_chunk_upload', 'saved_web_result', 'web_search'):
            try:
                sync_res = sync_external_database(user_id, cid, session_id)
            except Exception as sync_e:
                print(f"[!] Auto-Sync failed for External DB ({cid}): {sync_e}")
                return jsonify({"status": False, "statuscode": 500, "message": str(sync_e), "error": str(sync_e)}), 500

        if isinstance(sync_res, dict):
            if "situations" in sync_res: result["situations"].extend(sync_res["situations"])
            if "new_tables" in sync_res: result["new_tables"].extend(sync_res["new_tables"])
            if "tables" in sync_res: result["tables"].extend(sync_res["tables"])
            if "summary" in sync_res:
                s = sync_res["summary"]
                result["summary"]["total_rows"] = result["summary"].get("total_rows", 0) + s.get("total_rows", 0)
                result["summary"]["total_columns"] = result["summary"].get("total_columns", 0) + s.get("total_columns", 0)
                try:
                    cur_size = float(result["summary"].get("data_size_mb", 0))
                    new_size = float(s.get("data_size_mb", 0))
                    result["summary"]["data_size_mb"] = str(round(cur_size + new_size, 2))
                except (ValueError, TypeError):
                    pass
                result["summary"]["last_sync"] = s.get("last_sync", "Just now")

        # For doc_upload, the frontend never calls apply_bulk_sync, and apply_bulk_sync skips it anyway.
        # We must insert it into external_db_sync_log here so it appears in /session-sources.
        if ctype in ['doc_upload', 'doc_chunk_upload']:
            try:
                import pymysql
                from database.config import MYSQL_CONFIG
                conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
                with conn.cursor() as cur:
                    cur.execute("SELECT db_type, credential FROM database_credential WHERE connection_id=%s AND user_id=%s", (cid, user_id))
                    cred_row = cur.fetchone()
                    if cred_row:
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
                print(f"Error auto-syncing doc_upload ({cid}): {e}")

    # Ensure CSVs and previously synced tables for this session are included in the final summary response
    try:
        import pymysql
        from database.config import MYSQL_CONFIG
        conn = pymysql.connect(host=MYSQL_CONFIG["host"], user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"], database=MYSQL_CONFIG["database"])
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""
                SELECT *
                FROM external_db_sync_log
                WHERE session_id=%s
                  AND external_database IS NOT NULL
                  AND external_database != ''
            """, (session_id,))
            logs = cur.fetchall()
            
            # Identify which external databases are already covered by result['tables']
            # Build a flat set of table names already in live result for quick lookup
            result_table_names = set()
            for t in result.get('tables', []):
                tbl = t['table']
                result_table_names.add(tbl)
                # also add just the part after the last dot (bare table name)
                if '.' in tbl:
                    result_table_names.add(tbl.rsplit('.', 1)[-1])

            synced_ext_dbs = set()
            for log in logs:
                ext_db = log.get('external_database')
                t_name = log.get('table_name', '')
                if ext_db:
                    # Match if live result already has Poc.Products OR just products
                    already_covered = any(
                        t['table'].startswith(f"{ext_db}.") or t['table'] == f"{ext_db}"
                        for t in result.get('tables', [])
                    )
                    if already_covered:
                        synced_ext_dbs.add(ext_db)
                        continue
                    # Also skip if this individual table is already in the live result
                    if t_name and (f"{ext_db}.{t_name}" in result_table_names or t_name in result_table_names):
                        synced_ext_dbs.add(ext_db)
            
            # Group logs by table to keep only the latest entry
            latest_logs = {}
            for log in logs:
                ext_db = log.get('external_database')
                if ext_db and ext_db in synced_ext_dbs:
                    continue
                
                t_name = log['table_name']
                if ext_db:
                    if ext_db.lower().endswith('.csv'):
                        t_full_name = ext_db
                    elif ext_db.lower().endswith(('.xlsx', '.xls')):
                        t_full_name = f"{ext_db} ({t_name})"
                    else:
                        t_full_name = f"{ext_db}.{t_name}"
                else:
                    t_full_name = t_name
                latest_logs[t_full_name] = log

            latest_sync_time = None
            
            for t_full_name, log in latest_logs.items():
                t_name = log['table_name']
                
                # If there's a total_rows field, prefer it over rows_affected for accurate count
                rows = int(log.get('total_rows') or log.get('rows_affected') or 0)
                size = log.get('data_size_mb') or 0.0
                
                # Fetch exact column count from information_schema
                cols = 0
                if log.get('new_user_db') and t_name:
                    try:
                        cur.execute("SELECT COUNT(*) as col_count FROM information_schema.columns WHERE table_schema=%s AND table_name=%s", (log['new_user_db'], t_name))
                        col_row = cur.fetchone()
                        if col_row:
                            cols = col_row['col_count']
                    except Exception:
                        pass
                
                result['tables'].append({
                    "table": t_full_name,
                    "rows": rows,
                    "columns": cols
                })
                result['summary']['total_rows'] = result['summary'].get('total_rows', 0) + rows
                result['summary']['total_columns'] = result['summary'].get('total_columns', 0) + cols
                try:
                    cur_size = float(result["summary"].get("data_size_mb", 0))
                    result["summary"]["data_size_mb"] = str(round(cur_size + float(size), 2))
                except (ValueError, TypeError):
                    pass
                
                # Track latest sync time
                log_time = log.get('sync_time') or log.get('created_at') or log.get('timestamp')
                if log_time:
                    try:
                        import datetime
                        if isinstance(log_time, str):
                            try:
                                # Attempt to parse common string formats
                                if len(log_time) > 19:
                                    log_time = log_time[:19] # Trim milliseconds if present
                                parsed_time = datetime.datetime.strptime(log_time, "%Y-%m-%d %H:%M:%S")
                                latest_sync_time = parsed_time if not latest_sync_time else max(latest_sync_time, parsed_time)
                            except Exception:
                                pass
                        elif isinstance(log_time, datetime.datetime):
                            latest_sync_time = log_time if not latest_sync_time else max(latest_sync_time, log_time)
                    except Exception:
                        pass

            if latest_sync_time:
                try:
                    import datetime
                    now = datetime.datetime.now()
                    diff = now - latest_sync_time
                    if diff.total_seconds() < 60:
                        result['summary']['last_sync'] = "Just now"
                    else:
                        result['summary']['last_sync'] = latest_sync_time.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    pass

            if 'last_sync' not in result['summary']:
                result['summary']['last_sync'] = 'Just now'

        conn.close()
    except Exception as e:
        print("Error fetching CSV logs for summary:", e)


    # Deduplicate tables to prevent double counting if multiple connectors point to the same DB or if frontend sends duplicate requests
    unique_tables = {}
    for t in result.get("tables", []):
        unique_tables[t["table"]] = t
    
    deduped_tables = list(unique_tables.values())
    result["tables"] = deduped_tables
    
    # Recalculate summary totals accurately
    result["summary"]["total_rows"] = sum(int(t.get("rows", 0)) for t in deduped_tables)
    result["summary"]["total_columns"] = sum(int(t.get("columns", 0)) for t in deduped_tables)

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

    # Update (never recreate) the workspace's Knowledge Graph now that this
    # source has written into it — a kgraph_backups snapshot of the graph as
    # it stood before this sync is taken automatically inside build_kgraph().
    _rebuild_kgraph_for_session(
        session_id, trigger_source="tally_sync" if is_tally else "external_db_sync"
    )

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

    _rebuild_kgraph_for_session(session_id, trigger_source="external_db_apply_sync")

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

        _rebuild_kgraph_for_session(session_id, trigger_source=f"external_db_bulk_sync:{action}")

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
