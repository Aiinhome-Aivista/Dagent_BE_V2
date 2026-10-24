import json
import pymysql
import pandas as pd
from database.config import MYSQL_CONFIG

# ── Whitelisted SAP HANA views (SAP_S4 schema) — Metadata extraction only ──
SAP_ALLOWED_DATASPEC_OBJECTS = [
    "ZIVF_CustomerMaster_01_MD",
    "ZIVR_SKUMaster_01_TR",
    "ZIVF_CategoryMaster_01_TR",
    "ZITR_DayAttribute_01_TR",
    "ZIVF_TerritoryMaster_01_TR",
    "ZPVF_SD_SalesHistory_01_TR",
    "ZPVF_SD_CurrentSales_01_TR",
    "ZIVF_ZoneMaster_01_TR",
    "ZIVF_RegionMaster_MD_01",
    "ZPVF_SD_CancelledSalesInvoice_01_TR"
]
SAP_ALLOWED_OBJECTS_SET = {name.upper() for name in SAP_ALLOWED_DATASPEC_OBJECTS}
TARGET_SCHEMA = "SAP_S4"

def get_hana_connection_from_credential(external_db):
    """
    Creates an hdbcli dbapi connection using the existing connection parameters pattern.
    Supports SSH tunnel, HANA Cloud (port 443 / SSL), and tenant databases.
    """
    from hdbcli import dbapi

    tunnel = None
    db_host = external_db["host"]
    db_port = int(external_db.get("port", 30015))

    if external_db.get("ssh_host"):
        # pyrefly: ignore[missing-import]
        from sshtunnel import SSHTunnelForwarder
        tunnel = SSHTunnelForwarder(
            (external_db["ssh_host"], int(external_db.get("ssh_port", 22))),
            ssh_username=external_db.get("ssh_username"),
            ssh_password=external_db.get("ssh_password"),
            ssh_pkey=external_db.get("ssh_key_file"),
            remote_bind_address=(external_db.get("remote_mysql_host", external_db["host"]), int(external_db.get("remote_mysql_port", db_port)))
        )
        tunnel.start()
        db_host = "127.0.0.1"
        db_port = tunnel.local_bind_port

    is_hana_cloud = ("hanacloud.ondemand.com" in str(db_host).lower()) or (db_port == 443)
    connect_kwargs = {
        "address": db_host,
        "port": db_port,
        "user": external_db["username"],
        "password": external_db["password"],
        "autocommit": True
    }
    if external_db.get("database") and not is_hana_cloud:
        connect_kwargs["databaseName"] = external_db["database"]

    effective_schema = external_db.get("schema") or (external_db.get("database") if is_hana_cloud else None)
    if effective_schema:
        connect_kwargs["currentSchema"] = effective_schema

    if external_db.get("encrypt") or is_hana_cloud:
        connect_kwargs["encrypt"] = True
        connect_kwargs["sslValidateCertificate"] = False

    try:
        source_conn = dbapi.connect(**connect_kwargs)
    except Exception as e:
        if "not connected" in str(e).lower() and "databaseName" in connect_kwargs:
            fallback_db = connect_kwargs.pop("databaseName", None)
            if not connect_kwargs.get("currentSchema") and fallback_db:
                connect_kwargs["currentSchema"] = fallback_db
            source_conn = dbapi.connect(**connect_kwargs)
        else:
            if tunnel:
                try: tunnel.stop()
                except Exception: pass
            raise e

    return source_conn, tunnel, effective_schema


def discover_hana_metadata(user_id, connection_id, session_id=None):
    """
    Connects to SAP HANA, discovers views and their metadata:
    - View Name
    - Schema Name
    - Row Count
    - Column Count
    - Columns Detail (name, data_type, is_nullable, length, scale)
    - Primary Keys
    - Foreign Keys
    - Relationships
    Saves and persists all discovered metadata into central MySQL `sap_hana_view_metadata` table.
    STRICTLY metadata only: No business data is copied or migrated.
    """
    # 1. Fetch credentials from database_credential
    cred_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG.get("port", 3306),
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    try:
        with cred_conn.cursor() as cursor:
            if session_id:
                cursor.execute("""
                    SELECT credential, db_type, session_id
                    FROM database_credential
                    WHERE user_id=%s AND connection_id=%s AND session_id=%s
                    ORDER BY id DESC LIMIT 1
                """, (user_id, connection_id, session_id))
            else:
                cursor.execute("""
                    SELECT credential, db_type, session_id
                    FROM database_credential
                    WHERE user_id=%s AND connection_id=%s
                    ORDER BY id DESC LIMIT 1
                """, (user_id, connection_id))

            row = cursor.fetchone()
            if not row:
                # Fallback to connection_id only if user_id was stored differently
                cursor.execute("""
                    SELECT credential, db_type, session_id
                    FROM database_credential
                    WHERE connection_id=%s
                    ORDER BY id DESC LIMIT 1
                """, (connection_id,))
                row = cursor.fetchone()

            if not row:
                raise Exception(f"Connection credential not found for connection_id: {connection_id}")

            external_db = json.loads(row[0])
            db_type = (row[1] or "").strip().lower()
            if not session_id and row[2]:
                session_id = row[2]
    finally:
        cred_conn.close()

    if db_type not in ["hana", "sap_hana", "saphana", "sap"]:
        raise Exception(f"Connection type '{db_type}' is not SAP HANA.")

    source_conn, tunnel, effective_schema = get_hana_connection_from_credential(external_db)

    discovered_views = []
    try:
        source_cursor = source_conn.cursor()

        # Build candidate schemas
        cand_schemas = []
        if effective_schema:
            cand_schemas.append(effective_schema)
            if "#" in effective_schema:
                cand_schemas.append(effective_schema.split("#")[0])
        if external_db.get("username") and "#" in external_db.get("username"):
            cand_schemas.append(external_db["username"].split("#")[0])
        cand_schemas.append("SAP_S4")

        unique_cand_schemas = []
        for s in cand_schemas:
            if s and s.upper() not in [u.upper() for u in unique_cand_schemas]:
                unique_cand_schemas.append(s)

        # 2. Discover ONLY whitelisted views from SAP_S4 schema
        # Build placeholders for allowed object names
        allowed_names = list(SAP_ALLOWED_DATASPEC_OBJECTS)
        allowed_placeholders = ", ".join(["?"] * len(allowed_names))
        # Also add upper-cased variants
        allowed_args = allowed_names + [n.upper() for n in allowed_names]
        double_placeholders = ", ".join(["?"] * len(allowed_names))

        views_found = []
        try:
            source_cursor.execute(f"""
                SELECT VIEW_NAME, SCHEMA_NAME, 'VIEW' AS OBJ_TYPE
                FROM SYS.VIEWS
                WHERE UPPER(SCHEMA_NAME) = '{TARGET_SCHEMA.upper()}'
                  AND (VIEW_NAME IN ({allowed_placeholders})
                       OR UPPER(VIEW_NAME) IN ({double_placeholders}))
                ORDER BY VIEW_NAME
            """, allowed_args)
            views_found = source_cursor.fetchall()
            print(f"[HANA-METADATA] Found {len(views_found)} whitelisted views in {TARGET_SCHEMA} schema.")
        except Exception as e:
            print(f"[HANA-METADATA] Error querying whitelisted views: {e}")

        # Fallback: if SYS.VIEWS is inaccessible, try SYS.TABLES with same whitelist
        if not views_found:
            try:
                source_cursor.execute(f"""
                    SELECT TABLE_NAME, SCHEMA_NAME, 'TABLE' AS OBJ_TYPE
                    FROM SYS.TABLES
                    WHERE UPPER(SCHEMA_NAME) = '{TARGET_SCHEMA.upper()}'
                      AND IS_TEMPORARY = 'FALSE'
                      AND (TABLE_NAME IN ({allowed_placeholders})
                           OR UPPER(TABLE_NAME) IN ({double_placeholders}))
                    ORDER BY TABLE_NAME
                """, allowed_args)
                views_found = source_cursor.fetchall()
                print(f"[HANA-METADATA] Fallback: found {len(views_found)} whitelisted tables in {TARGET_SCHEMA} schema.")
            except Exception as e:
                print(f"[HANA-METADATA] Error querying SYS.TABLES fallback: {e}")

        # Convert discovered objects to pandas DataFrame
        views_df = pd.DataFrame(views_found, columns=["OBJ_NAME", "SCHEMA_NAME", "OBJ_TYPE"]) if views_found else pd.DataFrame(columns=["OBJ_NAME", "SCHEMA_NAME", "OBJ_TYPE"])

        # 3. For each view/table, retrieve column metadata, counts, primary keys & relationships using pandas
        for _, row in views_df.iterrows():
            v_name = str(row["OBJ_NAME"])
            v_schema = str(row["SCHEMA_NAME"])
            v_type = str(row["OBJ_TYPE"])

            # Column Metadata using pandas
            cols_info = []
            try:
                source_cursor.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE_NAME, LENGTH, SCALE, POSITION
                    FROM SYS.VIEW_COLUMNS
                    WHERE (VIEW_NAME = ? OR UPPER(VIEW_NAME) = UPPER(?))
                      AND (SCHEMA_NAME = ? OR UPPER(SCHEMA_NAME) = UPPER(?))
                    ORDER BY POSITION
                """, (v_name, v_name, v_schema, v_schema))
                c_rows = source_cursor.fetchall()
                if c_rows:
                    cols_df = pd.DataFrame(c_rows, columns=["name", "data_type", "length", "scale", "position"])
                    cols_df["is_nullable"] = True
                    # Fill any NA values cleanly
                    cols_df = cols_df.fillna({"length": 0, "scale": 0})
                    cols_info = cols_df.to_dict(orient="records")
            except Exception as col_err:
                print(f"[HANA-METADATA] SYS.VIEW_COLUMNS error for {v_name}: {col_err}")

            if not cols_info:
                # Try SYS.TABLE_COLUMNS with pandas
                try:
                    source_cursor.execute("""
                        SELECT COLUMN_NAME, DATA_TYPE_NAME, IS_NULLABLE, LENGTH, SCALE, POSITION
                        FROM SYS.TABLE_COLUMNS
                        WHERE (TABLE_NAME = ? OR UPPER(TABLE_NAME) = UPPER(?))
                          AND (SCHEMA_NAME = ? OR UPPER(SCHEMA_NAME) = UPPER(?))
                        ORDER BY POSITION
                    """, (v_name, v_name, v_schema, v_schema))
                    c_rows = source_cursor.fetchall()
                    if c_rows:
                        cols_df = pd.DataFrame(c_rows, columns=["name", "data_type", "is_nullable", "length", "scale", "position"])
                        cols_df["is_nullable"] = cols_df["is_nullable"].apply(lambda x: str(x).upper() == "TRUE")
                        cols_df = cols_df.fillna({"length": 0, "scale": 0})
                        cols_info = cols_df.to_dict(orient="records")
                except Exception as tbl_col_err:
                    print(f"[HANA-METADATA] SYS.TABLE_COLUMNS error for {v_name}: {tbl_col_err}")

            # Primary Keys using pandas → SYS.CONSTRAINTS
            primary_keys = []
            pk_detected_from_sys = False
            try:
                source_cursor.execute("""
                    SELECT COLUMN_NAME
                    FROM SYS.CONSTRAINTS
                    WHERE (TABLE_NAME = ? OR UPPER(TABLE_NAME) = UPPER(?))
                      AND (SCHEMA_NAME = ? OR UPPER(SCHEMA_NAME) = UPPER(?))
                      AND IS_PRIMARY_KEY = 'TRUE'
                    ORDER BY POSITION
                """, (v_name, v_name, v_schema, v_schema))
                pk_rows = source_cursor.fetchall()
                if pk_rows:
                    pk_df = pd.DataFrame(pk_rows, columns=["COLUMN_NAME"])
                    primary_keys = pk_df["COLUMN_NAME"].tolist()
                    pk_detected_from_sys = True
                    print(f"[HANA-METADATA] SYS.CONSTRAINTS: {len(primary_keys)} PKs for {v_name}")
            except Exception as pk_err:
                print(f"[HANA-METADATA] SYS.CONSTRAINTS error for {v_name}: {pk_err}")

            # Foreign Keys & Relationships → SYS.REFERENTIAL_CONSTRAINTS
            foreign_keys = []
            relationships = []
            fk_detected_from_sys = False
            try:
                source_cursor.execute("""
                    SELECT CONSTRAINT_NAME, COLUMN_NAME, REFERENCED_SCHEMA_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
                    FROM SYS.REFERENTIAL_CONSTRAINTS
                    WHERE (SCHEMA_NAME = ? OR UPPER(SCHEMA_NAME) = UPPER(?))
                      AND (TABLE_NAME = ? OR UPPER(TABLE_NAME) = UPPER(?))
                """, (v_schema, v_schema, v_name, v_name))
                fk_rows = source_cursor.fetchall()
                if fk_rows:
                    fk_df = pd.DataFrame(fk_rows, columns=[
                        "constraint_name", "column_name", "referenced_schema", "referenced_table", "referenced_column"
                    ])
                    foreign_keys = fk_df.to_dict(orient="records")
                    rel_df = pd.DataFrame({
                        "from_table": v_name,
                        "from_column": fk_df["column_name"],
                        "to_table": fk_df["referenced_table"],
                        "to_column": fk_df["referenced_column"]
                    })
                    relationships = rel_df.to_dict(orient="records")
                    fk_detected_from_sys = True
                    print(f"[HANA-METADATA] SYS.REFERENTIAL_CONSTRAINTS: {len(foreign_keys)} FKs for {v_name}")
            except Exception as fk_err:
                print(f"[HANA-METADATA] SYS.REFERENTIAL_CONSTRAINTS error for {v_name}: {fk_err}")

            # ── Fallback: LLM inference from 100 sample rows ───────────────────
            # If both PK and FK are empty, read up to 100 rows and let the LLM
            # infer primary keys, candidate FKs and relationships from column
            # names + value patterns.  NO data is stored — only the inferred
            # structural metadata (key names / relationships) is kept.
            if (not pk_detected_from_sys or not fk_detected_from_sys) and cols_info:
                try:
                    print(f"[HANA-METADATA] SYS tables returned no PK/FK for {v_name}. "
                          "Reading 100 sample rows for LLM inference...")

                    target_obj = f'"{v_schema}"."{v_name}"' if v_schema else f'"{v_name}"'
                    col_names = [c["name"] for c in cols_info]
                    col_select = ", ".join(f'"{c}"' for c in col_names[:40])  # cap at 40 cols

                    sample_rows_data = []
                    try:
                        source_cursor.execute(
                            f'SELECT TOP 100 {col_select} FROM {target_obj}'
                        )
                        raw_rows = source_cursor.fetchall()
                        if raw_rows:
                            sample_df = pd.DataFrame(raw_rows, columns=col_names[:40])
                            # Sanitise: drop all-null cols, convert to str
                            sample_df = sample_df.dropna(axis=1, how='all')
                            sample_df = sample_df.fillna("")
                            sample_rows_data = sample_df.head(100).to_dict(orient="records")
                    except Exception as sample_err:
                        print(f"[HANA-METADATA] Sample read error for {v_name}: {sample_err}")

                    if sample_rows_data:
                        from model.llm_client import call_llm_chat  # type: ignore
                        import json as _json

                        all_view_names = [r.get("view_name", "") or r.get("OBJ_NAME", "")
                                          for r in discovered_views]

                        llm_prompt = f"""You are a database analyst.
Below are up to 100 sample rows (NO actual business data should be stored — these rows are used ONLY to infer schema structure) from the SAP HANA view "{v_schema}"."{v_name}".

Column definitions:
{_json.dumps([{"name": c["name"], "type": c.get("data_type","?")} for c in cols_info[:40]], indent=2)}

Sample rows (first 100):
{_json.dumps(sample_rows_data[:100], indent=2, default=str)}

Other known views in the same schema: {', '.join(all_view_names) or 'unknown'}

Task: Based ONLY on column names, data types, and value patterns:
1. Identify which column(s) are likely PRIMARY KEY(s) — look for ID columns, uniqueness, non-null integer/string patterns.
2. Identify any FOREIGN KEY relationships to other views/tables in the schema — look for columns ending in _ID, _CODE, _KEY that reference another view.
3. Do NOT include any actual data values in your response.

Return STRICT JSON with this exact structure:
{{
  "primary_keys": ["col1", "col2"],
  "foreign_keys": [
    {{"column_name": "col", "referenced_table": "OTHER_VIEW", "referenced_column": "ID"}}
  ],
  "relationships": [
    {{"from_table": "{v_name}", "from_column": "col", "to_table": "OTHER_VIEW", "to_column": "ID"}}
  ],
  "confidence": "high|medium|low",
  "reasoning": "brief explanation"
}}"""

                        raw_llm = call_llm_chat(
                            [{"role": "user", "content": llm_prompt}],
                            json_mode=True,
                            temperature=0.0
                        )

                        # Parse LLM response
                        llm_inferred = None
                        try:
                            import re as _re
                            s = raw_llm.strip()
                            if s.startswith("```"):
                                s = _re.sub(r"^```[a-zA-Z]*", "", s).strip()
                                if s.endswith("```"):
                                    s = s[:-3].strip()
                            llm_inferred = _json.loads(s)
                        except Exception:
                            try:
                                from json_repair import repair_json  # type: ignore
                                llm_inferred = _json.loads(repair_json(raw_llm))
                            except Exception:
                                llm_inferred = None

                        if llm_inferred:
                            confidence = llm_inferred.get("confidence", "low")
                            print(f"[HANA-METADATA] LLM inferred PKs/FKs for {v_name} "
                                  f"(confidence={confidence}): "
                                  f"PKs={llm_inferred.get('primary_keys', [])}, "
                                  f"FKs={len(llm_inferred.get('foreign_keys', []))}")

                            # Only fill in what SYS tables missed
                            if not pk_detected_from_sys:
                                primary_keys = llm_inferred.get("primary_keys", primary_keys)

                            if not fk_detected_from_sys:
                                foreign_keys = llm_inferred.get("foreign_keys", foreign_keys)
                                relationships = llm_inferred.get("relationships", relationships)

                            # Tag inferred entries so caller can distinguish
                            for fk in foreign_keys:
                                if isinstance(fk, dict) and "source" not in fk:
                                    fk["source"] = "llm_inferred"
                            for rel in relationships:
                                if isinstance(rel, dict) and "source" not in rel:
                                    rel["source"] = "llm_inferred"
                        else:
                            print(f"[HANA-METADATA] LLM returned unparseable response for {v_name}.")

                except Exception as llm_err:
                    print(f"[HANA-METADATA] LLM inference failed for {v_name}: {llm_err}")

            # Row Count (strictly metadata counting, no rows retrieved)
            row_count = 0
            try:
                target_obj = f'"{v_schema}"."{v_name}"' if v_schema else f'"{v_name}"'
                source_cursor.execute(f"SELECT COUNT(*) FROM {target_obj}")
                count_res = source_cursor.fetchone()
                if count_res:
                    row_count = int(count_res[0])
            except Exception as cnt_err:
                print(f"[HANA-METADATA] Count error for {v_name}: {cnt_err}")
                row_count = 0


            discovered_views.append({
                "schema_name": v_schema or "",
                "view_name": v_name,
                "view_type": v_type,
                "row_count": row_count,
                "column_count": len(cols_info),
                "columns_detail": cols_info,
                "primary_keys": primary_keys,
                "foreign_keys": foreign_keys,
                "relationships": relationships
            })

    finally:
        try: source_conn.close()
        except Exception: pass
        if tunnel:
            try: tunnel.stop()
            except Exception: pass

    # 4. Save/Update discovered metadata in central MySQL
    save_conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG.get("port", 3306),
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"],
        autocommit=True
    )

    try:
        with save_conn.cursor() as cur:
            # Ensure table exists
            cur.execute("""
            CREATE TABLE IF NOT EXISTS sap_hana_view_metadata (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT NOT NULL,
                connection_id INT NOT NULL,
                session_id VARCHAR(100) NULL,
                schema_name VARCHAR(100) NOT NULL,
                view_name VARCHAR(200) NOT NULL,
                view_type VARCHAR(50) DEFAULT 'VIEW',
                row_count BIGINT DEFAULT 0,
                column_count INT DEFAULT 0,
                columns_detail JSON NULL,
                primary_keys JSON NULL,
                foreign_keys JSON NULL,
                relationships JSON NULL,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_conn_schema_view (connection_id, schema_name, view_name),
                INDEX idx_user_conn (user_id, connection_id),
                INDEX idx_session (session_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)

            upsert_query = """
            INSERT INTO sap_hana_view_metadata
            (user_id, connection_id, session_id, schema_name, view_name, view_type, row_count, column_count, columns_detail, primary_keys, foreign_keys, relationships, discovered_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                session_id = VALUES(session_id),
                view_type = VALUES(view_type),
                row_count = VALUES(row_count),
                column_count = VALUES(column_count),
                columns_detail = VALUES(columns_detail),
                primary_keys = VALUES(primary_keys),
                foreign_keys = VALUES(foreign_keys),
                relationships = VALUES(relationships),
                discovered_at = CURRENT_TIMESTAMP
            """

            for view in discovered_views:
                cur.execute(upsert_query, (
                    user_id,
                    connection_id,
                    session_id,
                    view["schema_name"],
                    view["view_name"],
                    view["view_type"],
                    view["row_count"],
                    view["column_count"],
                    json.dumps(view["columns_detail"]),
                    json.dumps(view["primary_keys"]),
                    json.dumps(view["foreign_keys"]),
                    json.dumps(view["relationships"])
                ))
    finally:
        save_conn.close()

    return {
        "status": "success",
        "connection_id": connection_id,
        "total_views": len(discovered_views),
        "views": discovered_views
    }


def get_stored_hana_metadata(connection_id=None, session_id=None, user_id=None):
    """
    Fetches the stored SAP HANA metadata from central MySQL for a given connection or session.
    """
    conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG.get("port", 3306),
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"]
    )

    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            query = "SELECT * FROM sap_hana_view_metadata WHERE 1=1"
            params = []
            if connection_id:
                query += " AND connection_id = %s"
                params.append(connection_id)
            if session_id:
                query += " AND session_id = %s"
                params.append(session_id)
            if user_id:
                query += " AND user_id = %s"
                params.append(user_id)

            query += " ORDER BY schema_name, view_name ASC"
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            for r in rows:
                for json_col in ["columns_detail", "primary_keys", "foreign_keys", "relationships"]:
                    if r.get(json_col) and isinstance(r[json_col], str):
                        try:
                            r[json_col] = json.loads(r[json_col])
                        except Exception:
                            pass
                if r.get("discovered_at"):
                    r["discovered_at"] = r["discovered_at"].strftime("%Y-%m-%d %H:%M:%S")

            return rows
    finally:
        conn.close()
