# controllers/session_analysis_controller.py
#
# POST /session-analysis
#
# Body:
# {
#   "session_id": "xxx",
#   "topics":     ["AI", "Python"],          // optional — from saved_web_results
#   "databaseses":  ["recipe", "code_complacity"]  // optional — from external_db_sync_log
# }
#
# At least one of topics / databaseses must be provided.
#
# Returns: structured multi-section analysis report as JSON

import re
import json
import requests
import mysql.connector
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("[Analysis] psycopg2 not installed — PostgreSQL support disabled")
# pyrefly: ignore [missing-import]
from flask import request, jsonify
from database.config import MISTRAL_API_KEY, MISTRAL_MODEL, MYSQL_CONFIG
from model.llm_client import call_llm_chat
from database.prompt_loader import get_prompt
from helper.dynamic_profiler import get_table_aggregates
from flask import request, jsonify
from database.config import MISTRAL_API_KEY, MISTRAL_MODEL, MYSQL_CONFIG

from pyvis.network import Network
import os
import uuid
from database.config import GRAPH_FOLDER, BASE_URL

MISTRAL_URL    = "https://api.mistral.ai/v1/chat/completions"
MAX_ROWS       = 100
MAX_CTX_CHARS  = 80000




# def generate_session_graph(session_id, web_data, db_data):

#     net = Network(
#         height="850px",
#         width="100%",
#         bgcolor="#222222",
#         font_color="white",
#         directed=False
#     )

#     SESSION_STYLE = {
#         "color": "#00bfa5",
#         "size": 35
#     }

#     TOPIC_STYLE = {
#         "color": "#ff4081",
#         "size": 20
#     }

#     DB_STYLE = {
#         "color": "#2979ff",
#         "size": 25
#     }

#     TABLE_STYLE = {
#         "color": "#ffc107",
#         "size": 15
#     }

#     session_node = f"session_{session_id}"

#     net.add_node(session_node, label=f"Session {session_id}", **SESSION_STYLE)

#     # Web Topics
#     for w in web_data:

#         topic = w["topic"]

#         net.add_node(topic, label=topic, **TOPIC_STYLE)
#         net.add_edge(session_node, topic)

#         for item in w["items"]:
#             title = item["title"][:40]

#             net.add_node(title, label=title)
#             net.add_edge(topic, title)

#     # databaseses
#     for db in db_data:

#         db_name = db["external_database"]

#         net.add_node(db_name, label=db_name, **DB_STYLE)
#         net.add_edge(session_node, db_name)

#         for table in db["tables"]:

#             tname = table["table_name"]

#             net.add_node(tname, label=tname, **TABLE_STYLE)
#             net.add_edge(db_name, tname)

#     html_filename = f"graph_{uuid.uuid4().hex[:8]}.html"

#     html_path = os.path.join(GRAPH_FOLDER, html_filename)

#     net.save_graph(html_path)

#     graph_url = f"{BASE_URL}/graphs/{html_filename}"

#     return graph_url




# ══════════════════════════════════════════════════════
# CROSS-SOURCE RELATIONSHIP DETECTION
# ══════════════════════════════════════════════════════

def detect_cross_source_relationships(table_columns: dict, web_data: list, db_data: list, workspace_id=None) -> dict:
    """
    Ask Mistral to dynamically generate a business-focused Knowledge Graph.
    """
    from database.prompt_loader import get_prompt
    
    db_summary = {}
    for db in db_data:
        for tbl in db["tables"]:
            # tables never carry "column_stats" — real per-column sample/frequency
            # data lives in "business_aggregates" (populated by get_table_aggregates).
            # Feed that in instead, so the LLM has actual values to work from
            # rather than inventing SKU/customer codes.
            db_summary[tbl["table_name"]] = {
                "columns": tbl.get("columns", []),
                "business_aggregates": tbl.get("business_aggregates", [])
            }

    web_summary = []
    for w in web_data:
        for item in w["items"]:
            web_summary.append({
                "topic": w["topic"],
                "title": item["title"],
                "brief": (item.get("brief") or "")[:200]
            })

    system_prompt = ""
    if workspace_id:
        system_prompt = get_prompt(workspace_id, 'dashboard_insights')
    if not system_prompt:
        system_prompt = get_prompt('0', 'dashboard_insights') or "Generate a business-focused Knowledge Graph from this data. Return exactly JSON with nodes and edges."

    prompt = f"""
{system_prompt}

DATA CONTEXT:
Database Summary: {json.dumps(db_summary)}
Web Summary: {json.dumps(web_summary)}
Analyze the uploaded sales dataset and generate a RICH, HIERARCHICAL, business-focused Knowledge Graph.
The graph MUST reflect the full product taxonomy AND all business relationships visible in the data from the 9 Master tables and 3 Fact tables.
def detect_table_relationships(table_columns):

    prompt = f"""
You are a database expert.

Find relationships between tables using column names.

Return ONLY JSON like:
[
  {{"table1":"table_name","column1":"column","table2":"table_name","column2":"column"}}
]

Tables and columns:
{json.dumps(table_columns, indent=2)}
"""

    try:
        resp = requests.post(
            MISTRAL_URL,
            headers={
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MISTRAL_MODEL,
                "messages":[{"role":"user","content":prompt}],
                "temperature":0,
                "response_format": {"type": "json_object"}
            },
            timeout=60
        )

        text = resp.json()["choices"][0]["message"]["content"]

        return json.loads(text)

    except Exception as e:
        print("Relationship detection error:", e)
        return []


# ══════════════════════════════════════════════════════
# GRAPH GENERATOR
# ══════════════════════════════════════════════════════

def generate_session_graph(session_id, web_data, db_data, target_arango_db=None, workspace_id=None):
def generate_session_graph(session_id, web_data, db_data):

    net = Network(
        height="850px",
        width="100%",
        bgcolor="#222222",
        font_color="white",
        directed=False
    )

    type_colors = {
    "ProductCategory": "#ff4081",   # pink — top-level product
    "Construction":    "#e040fb",   # purple — construction subtype
    "TyreType":        "#2979ff",   # blue — end-use vehicle
    "SKU":             "#9ccc65",   # green — SKU/product code
    "Customer":        "#ffc107",   # amber — customer/dealer
    "CustomerClass":   "#ff9800",   # orange — customer class
    "AccountGroup":    "#ff5722",   # deep orange — account group
    "Zone":            "#ff6d00",   # deep orange — geography parent
    "Region":          "#fb8c00",   # orange — geography
    "Territory":       "#f57c00",   # orange — geography child
    "BillingChannel":  "#00bfa5",   # teal — sales channel
    "Date":            "#00bcd4",
    "Month":           "#18ffff",
    }
    
    if workspace_id:
        import json
        from database.prompt_loader import get_prompt
        config_json = get_prompt(workspace_id, 'workspace_config')
        if config_json and config_json.strip():
            try:
                cfg = json.loads(config_json)
                if "type_colors" in cfg:
                    type_colors = cfg["type_colors"]
            except Exception as e:
                print(f"[Graph] Error parsing workspace_config JSON for type_colors: {e}")

    SESSION_STYLE = {"color": "#00bfa5", "size": 35}
    TOPIC_STYLE   = {"color": "#ff4081", "size": 20}
    DB_STYLE      = {"color": "#2979ff", "size": 25}
    TABLE_STYLE   = {"color": "#ffc107", "size": 15}

    session_node = f"session_{session_id}"
    net.add_node(session_node, label=f"Session {session_id}", **SESSION_STYLE)

    # -------------------------
    # Web Topics
    # -------------------------
    for w in web_data:

        topic = w["topic"]
        net.add_node(topic, label=topic, **TOPIC_STYLE)
        net.add_edge(session_node, topic)

        for item in w["items"]:
            title = item["title"][:40]
            net.add_node(title, label=title)
            net.add_edge(topic, title)


    # -------------------------
    # DB SECTION
    # -------------------------
    table_columns = {} 
    for db in db_data:

        db_name = db["external_database"]
        display_name = db.get("display_name", db_name)

        net.add_node(db_name, label=display_name, **DB_STYLE)
        net.add_edge(session_node, db_name)

        for table in db["tables"]:

    graph_data = detect_cross_source_relationships(table_columns, web_data, db_data, workspace_id)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
            tname = table["table_name"]
            columns = table.get("columns", [])
            table_columns[tname] = columns
            # Table node
            net.add_node(
                tname,
                label=tname,
                shape="box",
                **TABLE_STYLE
            )

            net.add_edge(db_name, tname)

            # Column nodes
            sample_rows = table.get("sample_rows", [])
            for col in columns:
                col_node = f"{tname}.{col}"

                net.add_node(
                    col_node,
                    label=col,
                    color="#9ccc65",
                    size=10
                )

                net.add_edge(tname, col_node)
                
                # Add values as leaf nodes to make the graph rich!
                added_vals = set()
                for row in sample_rows:
                    val = row.get(col)
                    if val is not None and str(val).strip():
                        val_str = str(val).strip()
                        # Shorten if too long
                        if len(val_str) > 25:
                            val_str = val_str[:22] + "..."
                            
                        if val_str not in added_vals:
                            added_vals.add(val_str)
                            val_node = f"{col_node}_{val_str}"
                            net.add_node(val_node, label=val_str, color="#bcaaa4", size=5, shape="text")
                            net.add_edge(col_node, val_node)


    # -------------------------
    # Detect Table Relationships using LLM
    # -------------------------

    relationships = detect_table_relationships(table_columns)

    for r in relationships:

        try:

            col1 = f"{r['table1']}.{r['column1']}"
            col2 = f"{r['table2']}.{r['column2']}"

            net.add_edge(
                col1,
                col2,
                color="#ff5252",
                width=4,
                label="relation"
            )

        except Exception as e:
            print("Relationship edge error:", e)

    # -------------------------
    # Save Graph
    # -------------------------
    html_filename = f"graph_{uuid.uuid4().hex[:8]}.html"
    html_path = os.path.join(GRAPH_FOLDER, html_filename)

    net.save_graph(html_path)

    graph_url = f"{BASE_URL}/graphs/{html_filename}"

    return graph_url
# ══════════════════════════════════════════════════════
# DATA FETCHERS
# ══════════════════════════════════════════════════════

def _fetch_web_data(session_id: str, topics: list, conn) -> list:
    """Fetch saved_web_results filtered by session_id + topic list."""
    if not topics:
        return []
    cursor = None
    results = []
    try:
        cursor = conn.cursor(dictionary=True)
        placeholders = ",".join(["%s"] * len(topics))
        cursor.execute(f"""
            SELECT topic, title, url, brief, saved_at
            FROM saved_web_results
            WHERE session_id = %s
              AND topic IN ({placeholders})
            ORDER BY topic, saved_at DESC
        """, [session_id] + topics)
        rows = cursor.fetchall()

        # Group by topic
        grouped = {}
        for r in rows:
            t = r["topic"]
            if t not in grouped:
                grouped[t] = []
            grouped[t].append({
                "title":    r["title"],
                "url":      r["url"],
                "brief":    r.get("brief", ""),
                "saved_at": str(r["saved_at"]) if r["saved_at"] else None
            })

        for topic, items in grouped.items():
            results.append({
                "source_type":  "web",
                "topic":        topic,
                "result_count": len(items),
                "items":        items
            })
    except Exception as e:
        print(f"[Analysis] web fetch error: {e}")
    finally:
        if cursor: cursor.close()
    return results

def _fetch_db_data(session_id: str, databaseses: list, conn) -> list:
    """
    For each requested database:
      1. Get new_user_db from external_db_sync_log
      2. Connect to new_user_db and read all tables (up to MAX_ROWS each)
    """

    if not databaseses:
        return []

    cursor = None
    results = []

    try:
        cursor = conn.cursor(dictionary=True)

        placeholders = ",".join(["%s"] * len(databaseses))

        cursor.execute(f"""
            SELECT DISTINCT external_database, new_user_db
            FROM external_db_sync_log
            WHERE session_id = %s
              AND external_database IN ({placeholders})
              AND new_user_db IS NOT NULL
              AND new_user_db != ''
        """, [session_id] + databaseses)

        rows = cursor.fetchall()

        db_map = {r["external_database"]: r["new_user_db"] for r in rows}

        print(f"[Analysis] DB MAP -> {db_map}")

    except Exception as e:
        print(f"[Analysis] db_map error: {e}")
        return []

    finally:
        if cursor:
            cursor.close()

    # We need to query each unique new_user_db only once, otherwise if multiple files map to the same workspace database (e.g. document uploads), we'll duplicate the data.
    unique_new_dbs = list(set(db_map.values()))

    for new_db in unique_new_dbs:
        # Find which external_databases map to this new_db to list as the source
        mapped_ext_dbs = [ext for ext, ndb in db_map.items() if ndb == new_db]
        display_name_str = ", ".join(mapped_ext_dbs)

        db_result = {
            "source_type": "database",
            "external_database": display_name_str,
            "new_user_db": new_db,
            "tables": []
        }

        ext_conn = None
        ext_cur = None

        try:

            print(f"[Analysis] Connecting DB -> {new_db}")

            ext_conn = mysql.connector.connect(
                host=MYSQL_CONFIG["host"],
                port=MYSQL_CONFIG["port"],
                user=MYSQL_CONFIG["user"],
                password=MYSQL_CONFIG["password"],
                database=new_db,
                connection_timeout=10
            )

            ext_cur = ext_conn.cursor(dictionary=True)

            # Fetch tables
            ext_cur.execute("SHOW TABLES")
            tables_raw = ext_cur.fetchall()

            tables = [list(r.values())[0] for r in tables_raw]

            print(f"[Analysis] Tables in {new_db} -> {tables}")

            for t in tables:

                print(f"[Analysis] Reading table -> {t}")

                try:

                    if t == 'workspace_files':
                        ext_cur.execute(f"SELECT * FROM `{t}` ORDER BY id DESC LIMIT %s", (MAX_ROWS,))
                    else:
                        ext_cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
                    rows = ext_cur.fetchall()

                    row_count = len(rows)

                    if row_count > 0:
                        cols = list(rows[0].keys())
                    else:
                        cols = []

                    # Column statistics
                    col_stats = {}

                    if row_count > 0:

                        for col in cols:

                            vals = []

                            for r in rows:
                                val = r.get(col)

                                if val is None:
                                    continue

                                val_str = str(val).strip()

                                if val_str:
                                    vals.append(val_str)

                            distinct_vals = list(dict.fromkeys(vals))

                            col_stats[col] = {
                                "total_values": len(vals),
                                "distinct_values": len(distinct_vals),
                                "sample": distinct_vals[:10]
                            }

                    if t == 'workspace_files':
                        for r in rows:
                            try:
                                import json
                                if isinstance(r.get('file_data'), str):
                                    file_data = json.loads(r['file_data'])
                                else:
                                    file_data = r.get('file_data') or {}
                                    
                                # Grab the file name to use as the display name for the db node
                                file_name = r.get('file_name', 'Document')
                                db_result["display_name"] = file_name
                                    
                                structured = file_data.get('structured_content')
                                if structured:
                                    # Add Paragraphs as a virtual table
                                    paragraphs = structured.get('paragraphs', [])
                                    if paragraphs:
                                        db_result["tables"].append({
                                            "table_name": "Document_Paragraphs",
                                            "row_count": len(paragraphs),
                                            "columns": ["title", "text"],
                                            "column_stats": {},
                                            "sample_rows": paragraphs[:5]
                                        })
                                    # Add each PDF table as a virtual table
                                    for idx, vtable in enumerate(structured.get('tables', [])):
                                        vname = vtable.get('table_name', f"PDF_Table_{idx+1}")
                                        vcols = vtable.get('headers', [])
                                        
                                        seen_cols = {}
                                        dedup_cols = []
                                        for c in vcols:
                                            base = str(c).strip() if c else "Column"
                                            if base in seen_cols:
                                                seen_cols[base] += 1
                                                dedup_cols.append(f"{base} ({seen_cols[base]})")
                                            else:
                                                seen_cols[base] = 1
                                                dedup_cols.append(base)

                                        sample_vrows = []
                                        for vrow in vtable.get('rows', [])[:5]:
                                            row_dict = {}
                                            for i, col in enumerate(dedup_cols):
                                                row_dict[col] = vrow[i] if i < len(vrow) else ""
                                            sample_vrows.append(row_dict)
                                            
                                        db_result["tables"].append({
                                            "table_name": vname,
                                            "row_count": len(vtable.get('rows', [])),
                                            "columns": dedup_cols,
                                            "column_stats": {},
                                            "sample_rows": sample_vrows
                                        })
                            except Exception as e:
                                print(f"Error parsing workspace_files json: {e}")
                    else:
                        db_result["tables"].append({
                            "table_name": t,
                            "row_count": row_count,
                            "columns": cols,
                            "column_stats": col_stats,
                            "sample_rows": rows[:5] if rows else []
                        })

                except Exception as table_error:
                    print(f"[Analysis] table {t} error -> {table_error}")

        except Exception as db_error:
            print(f"[Analysis] connect {new_db} error -> {db_error}")

        finally:

            if ext_cur:
                try:
                    ext_cur.close()
                except:
                    pass

            if ext_conn:
                try:
                    ext_conn.close()
                except:
                    pass

        results.append(db_result)

    return results


# def _fetch_db_data(session_id: str, databaseses: list, conn) -> list:
#     """
#     For each requested database:
#       1. Get new_user_db from external_db_sync_log
#       2. Connect to new_user_db and read all tables (up to MAX_ROWS each)
#     """
#     if not databaseses:
#         return []
#     cursor = None
#     results = []
#     try:
#         cursor = conn.cursor(dictionary=True)
#         placeholders = ",".join(["%s"] * len(databaseses))
#         cursor.execute(f"""
#             SELECT DISTINCT external_database, new_user_db
#             FROM external_db_sync_log
#             WHERE session_id = %s
#               AND external_database IN ({placeholders})
#               AND new_user_db IS NOT NULL AND new_user_db != ''
#         """, [session_id] + databaseses)
#         db_map = {r["external_database"]: r["new_user_db"] for r in cursor.fetchall()}
#     except Exception as e:
#         print(f"[Analysis] db_map error: {e}")
#         return []
#     finally:
#         if cursor: cursor.close()

#     for ext_db in databaseses:
#         new_db = db_map.get(ext_db)
#         if not new_db or not re.match(r'^\w+$', new_db):
#             continue

#         db_result = {
#             "source_type":       "database",
#             "external_database": ext_db,
#             "new_user_db":       new_db,
#             "tables":            []
#         }

#         ext_conn = ext_cur = None
#         try:
#             ext_conn = mysql.connector.connect(
#                 host=MYSQL_CONFIG["host"], port=MYSQL_CONFIG["port"],
#                 user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"],
#                 database=new_db, connection_timeout=10
#             )
#             ext_cur = ext_conn.cursor(dictionary=True)
#             ext_cur.execute("SHOW TABLES")
#             tables = [list(r.values())[0] for r in ext_cur.fetchall()]

#             for t in tables:
#                 if not re.match(r'^\w+$', t):
#                     continue
#                 try:
#                     ext_cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
#                     rows = ext_cur.fetchall()
#                     if not rows:
#                         continue
#                     cols = list(rows[0].keys())

#                     # Compute column stats
#                     col_stats = {}
#                     for col in cols:
#                         vals = [str(r[col]) for r in rows
#                                 if r[col] is not None and str(r[col]).strip()]
#                         distinct = list(dict.fromkeys(vals))
#                         col_stats[col] = {
#                             "total_values":    len(vals),
#                             "distinct_values": len(distinct),
#                             "sample":          distinct[:10]
#                         }

#                     db_result["tables"].append({
#                         "table_name":  t,
#                         "row_count":   len(rows),
#                         "columns":     cols,
#                         "column_stats": col_stats,
#                         "sample_rows": [
#                             {k: v for k, v in r.items()}
#                             for r in rows[:5]
#                         ]
#                     })
#                 except Exception as e:
#                     print(f"[Analysis] table {t}: {e}")

#         except Exception as e:
#             print(f"[Analysis] connect {new_db}: {e}")
#         finally:
#             if ext_cur:  ext_cur.close()
#             if ext_conn: ext_conn.close()

#         results.append(db_result)

#     return results


# ══════════════════════════════════════════════════════
# CONTEXT BUILDER
# ══════════════════════════════════════════════════════

def _build_context(web_data: list, db_data: list) -> str:
    parts = []

    for w in web_data:
        lines = [f"=== WEB TOPIC: {w['topic']} ({w['result_count']} results) ==="]
        for item in w["items"]:
            lines.append(f"  Title : {item['title']}")
            lines.append(f"  URL   : {item['url']}")
            if item.get("brief"):
                lines.append(f"  Brief : {item['brief'][:300]}")
        parts.append("\n".join(lines))

    for d in db_data:
        lines = [f"=== DATABASE: {d['external_database']} (stored as: {d['new_user_db']}) ==="]
        for tbl in d["tables"]:
            lines.append(f"\n  Table: {tbl['table_name']} ({tbl['row_count']} rows)")
            lines.append(f"  Columns: {', '.join(tbl['columns'])}")
            # Column stats
            for col, stats in tbl["column_stats"].items():
                lines.append(
                    f"    {col}: {stats['distinct_values']} distinct values — "
                    f"sample: {', '.join(str(v) for v in stats['sample'][:8])}"
                )
            # Sample rows
            lines.append(f"  Sample rows (up to 5):")
            for i, row in enumerate(tbl["sample_rows"], 1):
                r_str = " | ".join(f"{k}:{v}" for k,v in row.items()
                                   if v is not None and str(v).strip())
                lines.append(f"    Row{i}: {r_str}")
        parts.append("\n".join(lines))

    ctx = "\n\n".join(parts)
    if len(ctx) > MAX_CTX_CHARS:
        ctx = ctx[:MAX_CTX_CHARS] + "\n\n[... truncated ...]"
    return ctx


# ══════════════════════════════════════════════════════
# MISTRAL
# ══════════════════════════════════════════════════════

def _call_mistral(context: str, topics: list, databases: list, system_prompt: str) -> dict:
    if "JSON" not in system_prompt.upper():
        system_prompt += "\n\nCRITICAL: Respond ONLY in valid JSON with a single key: \"report\"."
        
def _call_mistral(context: str, topics: list, databaseses: list) -> dict:
    source_desc = []
    if topics:    source_desc.append(f"web topics: {', '.join(topics)}")
    if databaseses: source_desc.append(f"databaseses: {', '.join(databaseses)}")

    system = """You are a Generic Data Analysis and Visualization Engine.

Analyze the provided dataset dynamically. Do not assume any fixed domain, column names, business logic, or visualization type.

STEP 1 — PROFILE THE DATA
First identify:
- Column names and data types
- Numeric, categorical, date/time, identifier, text, percentage and currency fields
- Missing values and duplicate records
- Possible dimensions and measures
- Time granularity if date/time fields exist
- Relationships between columns
- Whether columns represent Budget, Actual, Target, Forecast, Cost, Revenue, Quantity, etc.

Do not infer a business meaning unless it is reasonably supported by the column name and data.

STEP 2 — DETECT DATA PATTERNS & FINANCIAL REPORTS
Before generating any visualization, determine which patterns are actually present.
For annual financial reports, first detect available financial dimensions and measures.

Rules:
1. Budget + Actual → grouped bar + variance KPI.
2. Category + amount → ranked bar.
3. Income components → pie/donut when few categories.
4. Multiple financial years → trend chart (Line/Bar).
5. Positive/negative variance → diverging bar chart.
6. Top/Bottom values (e.g., Top 5 Expense Items, Top 5 Over/Under Budget) → horizontal bar.
7. Two meaningful numeric measures → Correlation/scatter.

STEP 3 — GENERATE KPIs DYNAMICALLY
Generate only KPIs supported by the dataset.
IMPORTANT: Generate AT LEAST 6 to 8 highly relevant KPIs if the data supports it! Do not limit yourself to just 2 or 3.
For financial reports, by default, generate only data-supported KPIs such as:
Total Income, Total Expenditure, Budget vs Actual, Variance %, Total CAM / CAM Rate, Electricity Cost, Savings / Surplus (if data exists), Highest Expense Category, Highest Variance Category.
Never assume a KPI exists unless the required fields are present.

STEP 4 — SELECT VISUALIZATIONS
Do NOT automatically create every possible chart.
IMPORTANT: Generate AT LEAST 4 to 6 meaningful charts if the data supports it! Create multiple charts to provide a comprehensive analysis.
For financial reports, use Default Charts / Graphs if data is available:
- Budget vs Actual → Grouped Bar
- Income vs Expenditure → Bar
- Expense Category Breakdown → Bar
- Variance % by Category → Diverging Bar
- Income Source Contribution → Donut/Pie (if few categories)
- Year-wise Trend → Line/Bar (if multiple FY available)
- Top 5 Expense Items / Top 5 Over/Under Budget Items → Horizontal Bar
Never generate a chart unless required fields are present. Avoid duplicate or redundant charts.

STEP 5 — DATA ACCURACY & MATH LOGIC
- Use only values present in the dataset. Do not invent, estimate, or fabricate missing values.
- NEVER hallucinate mathematical comparisons or trends.
- Double-check calculations (percentages, multiples). For example, a jump from 7.3M to 8.5M is a ~16.4% increase, NOT an 11x increase.
- Ensure trend descriptions strictly match the actual values (e.g., if costs go from 7.8M to 6.6M to 6.3M, describe it as a "steady decline", NOT "significant increase followed by sharp decline").
- Identify the lowest/highest values accurately (e.g., if 2025-26 is 63.35 lakh and 2022-23 is 78.76 lakh, 2025-26 is the lowest).

STEP 6 — INSIGHTS
Provide concise insights based strictly on the available data.
Insights may include: Highest/lowest values, Increasing/decreasing trends, Significant variance, Top/bottom categories, Period-over-period changes, Target achievement, Major contributors.

STEP 7 — OUTPUT
Respond ONLY in valid JSON containing three keys: "report", "kpis", and "charts".
Your report text must be written as ONE continuous plain text — like a textbook chapter. Mix paragraphs and bullet points naturally. Minimum 15-20 lines of content. Use actual values, names, and numbers from the data. Never be vague or generic."""

    user = f"""
Analyze the following data ({'; '.join(source_desc)}):

{context}

Generate a detailed, purely business-focused summary highlighting key insights. Return ONLY this JSON:
Based on the data, return ONLY this JSON structure:
{{
  "report": "TITLE: <descriptive title here>\\n\\n<Opening paragraph — 3 to 4 sentences introducing what data was analyzed, how many sources, key highlights.>\\n\\n<Second paragraph — describe the main data sources, table names, row counts, column names found.>\\n\\n• <Bullet: specific fact with actual value from data>\\n• <Bullet: another specific metric or count>\\n• <Bullet: notable user/record/entry found>\\n• <Bullet: pattern or trend observed>\\n• <Bullet: another important data point>\\n\\n<Third paragraph — deeper analysis: relationships between tables, user activity, data patterns.>\\n\\n• <Bullet: cross-table insight>\\n• <Bullet: most active user or top record>\\n• <Bullet: date range or time pattern>\\n• <Bullet: data distribution observation>\\n• <Bullet: anomaly or interesting finding>\\n\\n<Fourth paragraph — data quality and completeness observations.>\\n\\n• <Bullet: data quality note>\\n• <Bullet: missing or null value observation>\\n\\n<Fifth paragraph — recommendations and conclusions based on the data.>\\n\\n• <Bullet: actionable recommendation>\\n• <Bullet: another recommendation>\\n• <Bullet: conclusion>",
  
  "kpis": [
    {{
      "title": "<Name of the Metric (e.g., Total Users, Average Price)>",
      "value": "<Actual numeric value extracted from data>",
      "description": "<Short explanation of this KPI>",
      "trend": "up"
    }}
  ],
  
  "charts": [
    {{
      "chart_type": "<bar or pie or line>",
      "title": "<Descriptive title for the chart>",
      "description": "<What this chart represents>",
      "labels": ["<Category 1>", "<Category 2>", "<Category 3>"],
      "datasets": [
        {{
          "label": "<Metric Name (e.g., Count, Total Amount)>",
          "data": [1, 2, 3]
        }}
      ]
    }}
  ]
}}
"""

    # system prompt passed from controller now
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user}
    ]
    try:
        content_str = call_llm_chat(messages, json_mode=True, temperature=0.2)
        
        # Clean potential markdown JSON block formatting from LLM output
        clean_str = content_str.strip()
        if clean_str.startswith("```json"):
            clean_str = clean_str[7:]
        elif clean_str.startswith("```"):
            clean_str = clean_str[3:]
            
        if clean_str.endswith("```"):
            clean_str = clean_str[:-3]
            
        clean_str = clean_str.strip()
        
        try:
            return json.loads(clean_str)
        except json.JSONDecodeError as je:
            print(f"[LLM] JSON parse error: {je}. Raw output was:\n{content_str}")
            return None
            
    headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}",
               "Content-Type": "application/json", "Accept": "application/json"}
    payload = {
        "model": MISTRAL_MODEL,
        "messages": [{"role":"system","content":system},
                     {"role":"user","content":user}],
        "response_format": {"type":"json_object"},
        "temperature": 0.2
    }
    try:
        resp = requests.post(MISTRAL_URL, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"[Mistral] {e}")
        return None


# ══════════════════════════════════════════════════════
# MAIN CONTROLLER  —  POST /session-analysis
# ══════════════════════════════════════════════════════

def session_analysis_controller(get_connection_func):
    data       = request.json or {}
    print(f"DEBUG /session-analysis RAW JSON: {data}")
    session_id = (data.get("session_id") or "").strip()
    topics     = [t.strip() for t in (data.get("topics")    or []) if str(t).strip()]
    raw_databases = data.get("databases") or data.get("databaseses") or []
    databaseses  = [d.strip() for d in raw_databases if str(d).strip()]
    print(f"DEBUG parsed topics: {topics}, parsed databases: {databaseses}")

    if not session_id:
        return jsonify({
            "status":"failed","statusCode":400,
            "message":"Field 'session_id' is required."
        }), 400

    if not topics and not databaseses:
        return jsonify({
            "status":"failed","statusCode":400,
            "message":"At least one of 'topics' or 'databaseses' must be provided."
        }), 400

    conn = None
    try:
        conn = get_connection_func()
        
        # Check if files are still processing for this workspace
        from controllers.uploads_controller import is_workspace_processing
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT workspace_db FROM workspaces WHERE session_id = %s", (session_id,))
        ws = cur.fetchone()
        cur.close()
        
        if ws and ws.get("workspace_db"):
            if is_workspace_processing(ws["workspace_db"]):
                return jsonify({
                    "status": "error",
                    "statusCode": 400,
                    "message": "Documents are still being processed in the background. Please wait a few minutes before running the analysis."
                }), 400

        web_data = _fetch_web_data(session_id, topics, conn)
        db_data  = _fetch_db_data(session_id, databaseses, conn)

        if not web_data and not db_data:
            return jsonify({
                "status":"no_data","statusCode":200,
                "session_id":session_id,
                "message":"No matching data found for the provided topics/databaseses."
            }), 200

        # Build raw data summary (always returned)
        raw_summary = {
            "web_sources":      web_data,
            "database_sources": [
                {
                    "external_database": d["external_database"],
                    "new_user_db":       d["new_user_db"],
                    "tables": [
                        {
                            "table_name":  t["table_name"],
                            "row_count":   t["row_count"],
                            "columns":     t["columns"],
                            "sample_rows": t["sample_rows"]
                        }
                        for t in d["tables"]
                    ]
                }
                for d in db_data
            ]
        }

        # Build LLM context
        context = _build_context(web_data, db_data)

        if cached:
            # Cache HIT — return immediately, no LLM call
            return jsonify({
                "status":     "success",
                "statusCode": 200,
                "report":     cached["report"],
                "graph_url":  cached["graph_url"],
            }), 200

        # 5. Cache MISS or STALE — generate fresh
        # Fetch workspace_id for this session to get the custom prompt
        workspace_id = None
        system_prompt = ""
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT id AS workspace_id FROM workspaces WHERE session_id = %s", (session_id,))
            s_row = cur.fetchone()
            if s_row and s_row.get("workspace_id"):
                workspace_id = s_row["workspace_id"]
            cur.close()
        except Exception as e:
            print(f"[Analysis] Session workspace_id fetch error: {e}")

        system_prompt = get_prompt(workspace_id, 'analysis') or ""

        # Fallback to default if no custom prompt
        if not system_prompt.strip():
            return jsonify({
                "status": "error", 
                "statusCode": 500,
                "message": "Analysis prompt not configured in database. Please set a global or workspace-specific prompt."
            }), 500

        analysis  = _call_mistral(context, topics, databases, system_prompt)
        graph_url = generate_session_graph(session_id, web_data, db_data, target_arango_db, workspace_id)
        # Call Mistral for analysis
        analysis = _call_mistral(context, topics, databaseses)
        # Generate Graph
        graph_url = generate_session_graph(session_id, web_data, db_data)

        if not analysis:
            return jsonify({
                "status":"partial","statusCode":200,
                "session_id":session_id,
                "message":"LLM analysis failed, returning raw data only.",
                "raw_data": raw_summary
            }), 200

        return jsonify({
            "status":     "success",
            "statusCode": 200,
            "session_id": session_id,
            "requested": {
                "topics":    topics,
                "databaseses": databaseses
            },
            "report": analysis.get("report", ""),
            "report_content": analysis,
            "graph_url": graph_url,
            "raw_data":  raw_summary
        }), 200

    except Exception as e:
        return jsonify({
            "status":"error","statusCode":500,
            "message":str(e)
        }), 500
    finally:
        if conn: conn.close()









##------------------ BKP ----------------------------

# import hashlib
# import re
# import json
# import requests
# # pyrefly: ignore [missing-import]
# import mysql.connector
# try:
#     import psycopg2
#     import psycopg2.extras
#     PSYCOPG2_AVAILABLE = True
# except ImportError:
#     PSYCOPG2_AVAILABLE = False
#     print("[Analysis] psycopg2 not installed — PostgreSQL support disabled")
# from flask import request, jsonify
# from database.config import MISTRAL_API_KEY, MISTRAL_MODEL, MYSQL_CONFIG
# from model.llm_client import call_llm_chat

# # pyrefly: ignore [missing-import]
# from pyvis.network import Network
# import os
# import uuid
# import re
# # pyrefly: ignore [missing-import]
# from arango import ArangoClient
# from database.config import (
#     GRAPH_FOLDER, BASE_URL,
#     ARANGO_HOST, ARANGO_USER, ARANGO_PASS, ARANGO_DB
# )

# MISTRAL_URL   = "https://api.mistral.ai/v1/chat/completions"
# MAX_ROWS      = 100
# MAX_CTX_CHARS = 24000


# # ══════════════════════════════════════════════════════
# # CACHE HELPERS
# # ══════════════════════════════════════════════════════

# def _hash_context(context: str) -> str:
#     """Return SHA-256 hex digest of the raw context string."""
#     return hashlib.sha256(context.encode("utf-8")).hexdigest()


# def _load_cache(session_id: str, data_hash: str, conn) -> dict | None:
#     """
#     Return cached {report, graph_url} if session_id exists AND hash matches.
#     Returns None otherwise (miss or stale).
#     """
#     cursor = None
#     try:
#         cursor = conn.cursor(dictionary=True)
#         cursor.execute("""
#             SELECT `report`, `graph_url`, `data_hash`
#             FROM `session_analysis_cache`
#             WHERE `session_id` = %s
#             LIMIT 1
#         """, (session_id,))
#         row = cursor.fetchone()
#         if row and row["data_hash"] == data_hash:
#             print(f"[Cache] HIT   session={session_id}")
#             return {"report": row["report"], "graph_url": row["graph_url"]}
#         if row:
#             print(f"[Cache] STALE session={session_id} — data changed, regenerating")
#         else:
#             print(f"[Cache] MISS  session={session_id} — first time")
#         return None
#     except Exception as e:
#         print(f"[Cache] load error: {e}")
#         return None
#     finally:
#         if cursor:
#             cursor.close()


# def _save_cache(session_id: str, data_hash: str,
#                 report: str, graph_url: str,
#                 topics: list, databases: list, conn) -> None:
#     """Upsert cache row for this session."""
#     cursor = None
#     try:
#         cursor = conn.cursor()
#         cursor.execute("""
#             INSERT INTO `session_analysis_cache`
#                 (`session_id`, `data_hash`, `report`, `graph_url`, `topics`, `databases`)
#             VALUES (%s, %s, %s, %s, %s, %s)
#             ON DUPLICATE KEY UPDATE
#                 `data_hash`  = VALUES(`data_hash`),
#                 `report`     = VALUES(`report`),
#                 `graph_url`  = VALUES(`graph_url`),
#                 `topics`     = VALUES(`topics`),
#                 `databases`  = VALUES(`databases`),
#                 `updated_at` = CURRENT_TIMESTAMP
#         """, (
#             session_id,
#             data_hash,
#             report,
#             graph_url,
#             json.dumps(topics),
#             json.dumps(databases)
#         ))
#         conn.commit()
#         print(f"[Cache] SAVED session={session_id}  topics={topics}  databases={databases}")
#     except Exception as e:
#         print(f"[Cache] save error: {e}")
#         raise   # re-raise so the caller knows save failed
#     finally:
#         if cursor:
#             cursor.close()


# # ══════════════════════════════════════════════════════
# # CROSS-SOURCE RELATIONSHIP DETECTION
# # ══════════════════════════════════════════════════════

# def detect_cross_source_relationships(table_columns: dict, web_data: list, db_data: list) -> dict:
#     """
#     Ask Mistral to dynamically generate a business-focused Knowledge Graph.
#     """
#     db_summary = {}
#     for db in db_data:
#         for tbl in db["tables"]:
#             entry = {}
#             for col, stats in tbl.get("column_stats", {}).items():
#                 entry[col] = stats.get("sample", [])[:10]
#             db_summary[tbl["table_name"]] = entry

#     web_summary = []
#     for w in web_data:
#         for item in w["items"]:
#             web_summary.append({
#                 "topic": w["topic"],
#                 "title": item["title"],
#                 "brief": (item.get("brief") or "")[:200]
#             })

#     prompt = f"""
# You are an expert Knowledge Graph Builder specializing in tyre and automotive parts distribution data.

# Analyze the uploaded sales dataset and generate a RICH, HIERARCHICAL, business-focused Knowledge Graph.
# The graph MUST reflect the full product taxonomy AND all business relationships visible in the data.

# ## DB Tables and Sample Data:
# {json.dumps(db_summary, indent=2)}

# ## Web Data:
# {json.dumps(web_summary, indent=2)}

# ---

# ## MANDATORY GRAPH STRUCTURE

# ### LEVEL 1 — Product Category Nodes (CATEGORY column)
# Create one node per unique product category found in the data.
# Known categories in this dataset: Tyre, Tube, Flap, Ret read Belt, Vul. Solution
# Node type: "ProductCategory"

# ### LEVEL 2 — Construction Type Nodes (CONSTRUCTION column)
# Create one node per unique construction type found in the data.
# Known construction types: BIAS, RADIAL, BIAS DOT
# Node type: "Construction"

# MANDATORY EDGES — for every (Category, Construction) combination that exists in the data:
#   (ProductCategory) --[HAS_CONSTRUCTION]--> (Construction)

# Example: Tyre → BIAS, Tyre → RADIAL, Tube → BIAS, Tube → RADIAL, Flap → BIAS, Flap → RADIAL

# ### LEVEL 3 — Tyre/Vehicle Type Nodes (TYRE TYPE column)
# Create one node per unique vehicle/application type found in the data.
# Known types: TRUCK, LCV, CAR, SCV, Motor Cycle, SCOOTER, 3W, JEEP, TRACTOR FRONT, TRACTOR REAR, TRACTOR TRAILER, OTR, INDUSTRIAL
# Node type: "VehicleSegment"

# MANDATORY EDGES — for every (Construction, TyreType) combination that actually exists in the data:
#   (Construction) --[FITS_VEHICLE]--> (VehicleSegment)

# IMPORTANT: Only create edges that actually exist in the data. For example:
# - RADIAL construction connects to: TRUCK, LCV, CAR, SCV (but NOT Motor Cycle, Scooter, 3W — those only appear under BIAS)
# - BIAS construction connects to: TRUCK, LCV, SCV, Motor Cycle, SCOOTER, 3W, JEEP, TRACTOR FRONT, TRACTOR REAR, OTR, INDUSTRIAL

# ### LEVEL 4 — Billing/Channel Type Nodes (Billing type column)
# Create nodes for each billing channel found in the data.
# Node type: "BillingChannel"
# Known billing types and their business meanings:
#   - ZOR = Standard dealer order
#   - ZBCL = Scheme/claim billing
#   - ZFCL = Free of charge (FOC/sample) billing
#   - ZBFO = Bill & forward billing
#   - ZRDR = Return/debit note
#   - ZCCR = Credit note
#   - ZCC = Cash/counter sale

# MANDATORY EDGES:
#   (ProductCategory) --[SOLD_VIA]--> (BillingChannel)
# Only create these edges for combinations that actually appear in the sample data.

# ### LEVEL 5 — Region and Zone Nodes
# Create Region and Zone nodes from the data.
# Node type: "Region" for region values (e.g., JAIPUR)
# Node type: "Zone" for zone values (e.g., Central)

# MANDATORY EDGES:
#   (Zone) --[CONTAINS]--> (Region)
#   (Region) --[TOP_CATEGORY_IN_REGION]--> (ProductCategory)  [for the highest volume category]

# ### LEVEL 6 — Top Material (SKU) Nodes
# From the Material column, identify the TOP 8 most frequently appearing SKUs in the sample data.
# Node type: "Material"

# MANDATORY EDGES:
#   (Material) --[BELONGS_TO]--> (ProductCategory)  [based on the category column for that material]
#   (Material) --[HAS_CONSTRUCTION_TYPE]--> (Construction)
#   (Material) --[USED_IN]--> (VehicleSegment)

# ### LEVEL 7 — Top Customer/Dealer Nodes
# From the Customer column, identify the TOP 5 most frequently appearing customers in the sample data.
# Node type: "Dealer"

# MANDATORY EDGES:
#   (Dealer) --[LOCATED_IN]--> (Region)
#   (Dealer) --[PRIMARILY_BUYS]--> (ProductCategory)  [the category with most transactions for this dealer]

# ---

# ## NUMERICAL PROPERTIES (store as node/edge properties, NEVER as separate nodes)
# - On ProductCategory nodes: total_quantity, total_invoice_value, transaction_count
# - On VehicleSegment nodes: dominant_category (most common product category for this segment)
# - On FITS_VEHICLE edges: transaction_count, avg_invoice_value
# - On SOLD_VIA edges: transaction_count
# - On PRIMARILY_BUYS edges: transaction_count, total_value

# ---

# ## OUTPUT FORMAT
# Return EXACTLY this JSON (no markdown, no extra text):
# {{
#   "nodes": [
#     {{"id": "cat_tyre", "label": "Tyre", "type": "ProductCategory", "properties": {{"transaction_count": 0}}}},
#     {{"id": "cat_tube", "label": "Tube", "type": "ProductCategory", "properties": {{}}}},
#     {{"id": "cat_flap", "label": "Flap", "type": "ProductCategory", "properties": {{}}}},
#     {{"id": "const_bias", "label": "BIAS", "type": "Construction", "properties": {{}}}},
#     {{"id": "const_radial", "label": "RADIAL", "type": "Construction", "properties": {{}}}},
#     {{"id": "seg_truck", "label": "TRUCK", "type": "VehicleSegment", "properties": {{"dominant_category": "Tyre"}}}},
#     {{"id": "seg_car", "label": "CAR", "type": "VehicleSegment", "properties": {{}}}},
#     {{"id": "ch_zor", "label": "ZOR (Standard Order)", "type": "BillingChannel", "properties": {{}}}},
#     {{"id": "reg_jaipur", "label": "JAIPUR", "type": "Region", "properties": {{}}}},
#     {{"id": "zone_central", "label": "Central", "type": "Zone", "properties": {{}}}}
#   ],
#   "edges": [
#     {{"from": "cat_tyre", "to": "const_bias", "label": "HAS_CONSTRUCTION", "properties": {{}}}},
#     {{"from": "cat_tyre", "to": "const_radial", "label": "HAS_CONSTRUCTION", "properties": {{}}}},
#     {{"from": "const_bias", "to": "seg_truck", "label": "FITS_VEHICLE", "properties": {{}}}},
#     {{"from": "const_radial", "to": "seg_car", "label": "FITS_VEHICLE", "properties": {{}}}},
#     {{"from": "cat_tyre", "to": "ch_zor", "label": "SOLD_VIA", "properties": {{}}}},
#     {{"from": "zone_central", "to": "reg_jaipur", "label": "CONTAINS", "properties": {{}}}},
#     {{"from": "reg_jaipur", "to": "cat_tyre", "label": "TOP_CATEGORY_IN_REGION", "properties": {{}}}}
#   ],
#   "identified_node_types": ["ProductCategory", "Construction", "VehicleSegment", "BillingChannel", "Region", "Zone", "Material", "Dealer"],
#   "identified_relationship_types": ["HAS_CONSTRUCTION", "FITS_VEHICLE", "SOLD_VIA", "CONTAINS", "TOP_CATEGORY_IN_REGION", "BELONGS_TO", "HAS_CONSTRUCTION_TYPE", "USED_IN", "LOCATED_IN", "PRIMARILY_BUYS"],
#   "graph_schema": [
#     "(ProductCategory)-[:HAS_CONSTRUCTION]->(Construction)",
#     "(Construction)-[:FITS_VEHICLE]->(VehicleSegment)",
#     "(ProductCategory)-[:SOLD_VIA]->(BillingChannel)",
#     "(Zone)-[:CONTAINS]->(Region)",
#     "(Material)-[:BELONGS_TO]->(ProductCategory)",
#     "(Dealer)-[:PRIMARILY_BUYS]->(ProductCategory)"
#   ],
#   "sample_cypher_queries": [
#     "MATCH (c:ProductCategory)-[:HAS_CONSTRUCTION]->(cn:Construction)-[:FITS_VEHICLE]->(v:VehicleSegment) RETURN c.label, cn.label, v.label",
#     "MATCH (d:Dealer)-[:PRIMARILY_BUYS]->(c:ProductCategory) RETURN d.label, c.label ORDER BY d.transaction_count DESC LIMIT 10",
#     "MATCH (m:Material)-[:USED_IN]->(v:VehicleSegment) WHERE v.label='TRUCK' RETURN m.label"
#   ],
#   "business_insights": [
#     "RADIAL construction dominates CAR and LCV segments while BIAS covers two-wheeler, SCV and tractor segments",
#     "Tyre is the highest-volume ProductCategory, followed by Tube and Flap",
#     "ZOR (standard order) is the primary billing channel, with ZBCL (scheme billing) significant for Tyre category",
#     "TRUCK segment consumes both Tyre, Tube and Flap — all three product categories — making it the most cross-category vehicle type"
#   ],
#   "suggested_graphrag_paths": [
#     "Start from ProductCategory → HAS_CONSTRUCTION → Construction → FITS_VEHICLE → VehicleSegment (full product-to-market path)",
#     "Start from Dealer → PRIMARILY_BUYS → ProductCategory → HAS_CONSTRUCTION → Construction (dealer preference path)",
#     "Start from Zone → CONTAINS → Region → TOP_CATEGORY_IN_REGION → ProductCategory (geographic demand path)"
#   ]
# }}

# ## RULES
# 1. Use ONLY node IDs you defined in the "nodes" array for "from"/"to" in edges.
# 2. Extract actual values from the sample data — do NOT invent SKU codes or customer IDs.
# 3. Every ProductCategory node MUST have at least one HAS_CONSTRUCTION edge.
# 4. Every Construction node MUST have at least one FITS_VEHICLE edge.
# 5. BIAS and RADIAL are different construction types for the SAME categories (Tyre, Tube, Flap) — they are siblings under each category, not children of each other.
# 6. Do NOT create a node for every single Material or Customer — only the top 5-8 most frequent ones from the sample.
# 7. Node IDs must be unique strings with no spaces (use underscores).
# """

#     messages = [{"role": "user", "content": prompt}]
#     try:
#         raw = call_llm_chat(messages, json_mode=True, temperature=0.1)
#         result = json.loads(raw)
#         result.setdefault("nodes", [])
#         result.setdefault("edges", [])
#         return result

#     except Exception as e:
#         print("Business Knowledge Graph detection error:", e)
#         return {"nodes": [], "edges": []}


# # ══════════════════════════════════════════════════════
# # GRAPH GENERATOR
# # ══════════════════════════════════════════════════════

# def generate_session_graph(session_id, web_data, db_data, target_arango_db=None):

#     net = Network(
#         height="850px",
#         width="100%",
#         bgcolor="#222222",
#         font_color="white",
#         directed=True
#     )

#     type_colors = {
#     "ProductCategory": "#ff4081",   # pink — top-level product
#     "Construction":    "#e040fb",   # purple — construction subtype
#     "VehicleSegment":  "#2979ff",   # blue — end-use vehicle
#     "BillingChannel":  "#00bfa5",   # teal — sales channel
#     "Dealer":          "#ffc107",   # amber — customer/dealer
#     "Region":          "#ff9800",   # orange — geography
#     "Zone":            "#ff6d00",   # deep orange — geography parent
#     "Material":        "#9ccc65",   # green — SKU/product code
#     "Customer":        "#ffc107",   # fallback
#     "Category":        "#ff4081",   # fallback
#     "Date":            "#00bcd4",
#     "Month":           "#18ffff",
#     }

#     table_columns = {}
#     for db in db_data:
#         for table in db["tables"]:
#             table_columns[table["table_name"]] = table.get("columns", [])

#     graph_data = detect_cross_source_relationships(table_columns, web_data, db_data)
#     nodes = graph_data.get("nodes", [])
#     edges = graph_data.get("edges", [])

#     existing_ids = set()

#     for n in nodes:
#         node_id = str(n.get("id"))
#         if not node_id: continue
#         label = str(n.get("label", node_id))
#         ntype = str(n.get("type", "Entity"))
        
#         props = n.get("properties", {})
#         title_lines = [f"{k}: {v}" for k, v in props.items()]
#         title = "\n".join(title_lines) if title_lines else ntype

#         color = type_colors.get(ntype, "#b0bec5")
        
#         net.add_node(node_id, label=label, title=title, color=color, size=25, type=ntype)
#         existing_ids.add(node_id)

#     for e in edges:
#         from_node = str(e.get("from"))
#         to_node = str(e.get("to"))
#         label = str(e.get("label", ""))

#         if from_node in existing_ids and to_node in existing_ids:
#             props = e.get("properties", {})
#             title_lines = [f"{k}: {v}" for k, v in props.items()]
#             title = "\n".join(title_lines) if title_lines else label
            
#             net.add_edge(from_node, to_node, label=label, title=title, color="#ff5252", width=2)
#         else:
#             print(f"[Graph] Skipped edge due to missing nodes: {from_node} -> {to_node}")

#     html_filename = f"graph_{uuid.uuid4().hex[:8]}.html"
#     html_path     = os.path.join(GRAPH_FOLDER, html_filename)
#     net.save_graph(html_path)

#     # --- Sync to ArangoDB ---
#     try:
#         _sync_to_arango(session_id, net.nodes, net.edges, target_arango_db)
#     except Exception as e:
#         print(f"[ArangoDB] Sync failed: {e}")

#     return f"{BASE_URL}/graphs/{html_filename}"

# # ══════════════════════════════════════════════════════
# # ARANGODB SYNC
# # ══════════════════════════════════════════════════════

# def _safe_key(val: str) -> str:
#     """ArangoDB _key allows only [a-zA-Z0-9_:.@()-]+"""
#     return re.sub(r'[^a-zA-Z0-9_:.@()-]', '_', str(val))

# def _sync_to_arango(session_id: str, nodes: list, edges: list, target_arango_db: str = None):
#     print(f"[ArangoDB] Connecting to {ARANGO_HOST} ...")
#     client = ArangoClient(hosts=ARANGO_HOST)
#     sys_db = client.db('_system', username=ARANGO_USER, password=ARANGO_PASS)

#     db_to_use = target_arango_db if target_arango_db else ARANGO_DB

#     # Ensure database exists
#     if not sys_db.has_database(db_to_use):
#         sys_db.create_database(db_to_use)
    
#     db = client.db(db_to_use, username=ARANGO_USER, password=ARANGO_PASS)

#     # Ensure collections exist
#     nodes_col_name = "session_nodes"
#     edges_col_name = "session_edges"

#     if not db.has_collection(nodes_col_name):
#         db.create_collection(nodes_col_name)
#     if not db.has_collection(edges_col_name):
#         db.create_collection(edges_col_name, edge=True)

#     nodes_col = db.collection(nodes_col_name)
#     edges_col = db.collection(edges_col_name)

#     # Sync Nodes
#     print(f"[ArangoDB] Syncing {len(nodes)} nodes...")
#     for n in nodes:
#         key = _safe_key(n["id"])
#         doc = {
#             "_key": key,
#             "session_id": session_id,
#             "label": n.get("label", ""),
#             "original_id": n["id"],
#             "type": n.get("type") or (n["id"].split('_')[0] if '_' in n["id"] else "unknown")
#         }
#         try:
#             if nodes_col.has(key):
#                 nodes_col.update(doc)
#             else:
#                 nodes_col.insert(doc)
#         except Exception as e:
#             print(f"[ArangoDB] skip node {key}: {e}")

#     # Sync Edges
#     print(f"[ArangoDB] Syncing {len(edges)} edges...")
#     for e in edges:
#         from_key = _safe_key(e["from"])
#         to_key   = _safe_key(e["to"])
#         edge_key = _safe_key(f"{from_key}_to_{to_key}")
        
#         doc = {
#             "_key": edge_key,
#             "_from": f"{nodes_col_name}/{from_key}",
#             "_to": f"{nodes_col_name}/{to_key}",
#             "session_id": session_id,
#             "label": e.get("label", ""),
#             "title": e.get("title", "")
#         }
#         try:
#             if edges_col.has(edge_key):
#                 edges_col.update(doc)
#             else:
#                 edges_col.insert(doc)
#         except Exception as ex:
#             print(f"[ArangoDB] skip edge {edge_key}: {ex}")

#     print("[ArangoDB] Sync Complete!")


# # ══════════════════════════════════════════════════════
# # DATA FETCHERS
# # ══════════════════════════════════════════════════════

# def _fetch_web_data(session_id: str, topics: list, conn) -> list:
#     if not topics:
#         return []
#     cursor = None
#     results = []
#     try:
#         cursor = conn.cursor(dictionary=True)
#         placeholders = ",".join(["%s"] * len(topics))
#         cursor.execute(f"""
#             SELECT topic, title, url, brief, saved_at
#             FROM saved_web_results
#             WHERE `session_id` = %s
#               AND topic IN ({placeholders})
#             ORDER BY topic, saved_at DESC
#         """, [session_id] + topics)
#         rows = cursor.fetchall()

#         grouped = {}
#         for r in rows:
#             t = r["topic"]
#             grouped.setdefault(t, []).append({
#                 "title":    r["title"],
#                 "url":      r["url"],
#                 "brief":    r.get("brief", ""),
#                 "saved_at": str(r["saved_at"]) if r["saved_at"] else None
#             })

#         for topic, items in grouped.items():
#             results.append({
#                 "source_type":  "web",
#                 "topic":        topic,
#                 "result_count": len(items),
#                 "items":        items
#             })
#     except Exception as e:
#         print(f"[Analysis] web fetch error: {e}")
#     finally:
#         if cursor: cursor.close()
#     return results


# def _fetch_db_data(session_id: str, databases: list, conn) -> list:
#     """
#     Fetch DB data for analysis — supports MySQL and PostgreSQL.
#     For PostgreSQL:
#       - schema provided → only that schema's tables
#       - no schema → all non-system schemas (public + custom)
#     """
#     results = []

#     # ── 1. MySQL / MSSQL (sync log approach) ──
#     cursor = None
#     db_map = {}
#     try:
#         cursor = conn.cursor(dictionary=True)
#         if databases:
#             placeholders = ",".join(["%s"] * len(databases))
#             cursor.execute(f"""
#                 SELECT DISTINCT external_database, new_user_db, table_name
#                 FROM external_db_sync_log
#                 WHERE `session_id` = %s
#                   AND external_database IN ({placeholders})
#                   AND new_user_db IS NOT NULL
#                   AND new_user_db != ''
#             """, [session_id] + databases)
#             rows = cursor.fetchall()
#             for r in rows:
#                 ext_db = r["external_database"]
#                 if ext_db not in db_map:
#                     db_map[ext_db] = {"new_user_db": r["new_user_db"], "tables": []}
#                 if r.get("table_name"):
#                     db_map[ext_db]["tables"].append(r["table_name"])
#             print(f"[Analysis] MySQL DB MAP -> {db_map}")
#     except Exception as e:
#         print(f"[Analysis] db_map error: {e}")
#     finally:
#         if cursor: cursor.close()

#     for ext_db in databases:
#         db_info = db_map.get(ext_db)
#         if not db_info:
#             continue

#         new_db = db_info["new_user_db"]
#         allowed_tables = db_info["tables"]

#         db_result = {
#             "source_type":       "database",
#             "external_database": ext_db,
#             "new_user_db":       new_db,
#             "tables":            []
#         }

#         ext_conn = ext_cur = None
#         try:
#             print(f"[Analysis] Connecting MySQL -> {new_db}")
#             ext_conn = mysql.connector.connect(
#                 host=MYSQL_CONFIG["host"],
#                 port=MYSQL_CONFIG["port"],
#                 user=MYSQL_CONFIG["user"],
#                 password=MYSQL_CONFIG["password"],
#                 database=new_db,
#                 connection_timeout=10
#             )
#             ext_cur = ext_conn.cursor(dictionary=True)
            
#             # Filter tables: only use those explicitly synced for this database
#             if allowed_tables:
#                 tables = allowed_tables
#             else:
#                 ext_cur.execute("SHOW TABLES")
#                 tables = [list(r.values())[0] for r in ext_cur.fetchall()]
                
#             print(f"[Analysis] Tables in {new_db} for {ext_db} -> {tables}")

#             for t in tables:
#                 try:
#                     ext_cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
#                     rows      = ext_cur.fetchall()
#                     row_count = len(rows)
#                     cols      = list(rows[0].keys()) if row_count > 0 else []
#                     col_stats = {}
#                     if row_count > 0:
#                         for col in cols:
#                             vals = [
#                                 str(r[col]).strip()
#                                 for r in rows
#                                 if r.get(col) is not None and str(r[col]).strip()
#                             ]
#                             distinct_vals = list(dict.fromkeys(vals))
#                             col_stats[col] = {
#                                 "total_values":    len(vals),
#                                 "distinct_values": len(distinct_vals),
#                                 "sample":          distinct_vals[:10]
#                             }
#                     db_result["tables"].append({
#                         "table_name":   t,
#                         "row_count":    row_count,
#                         "columns":      cols,
#                         "column_stats": col_stats,
#                         "sample_rows":  rows[:5] if rows else []
#                     })
#                 except Exception as table_error:
#                     print(f"[Analysis] MySQL table {t} error -> {table_error}")

#         except Exception as db_error:
#             print(f"[Analysis] MySQL connect {new_db} error -> {db_error}")
#         finally:
#             if ext_cur:
#                 try: ext_cur.close()
#                 except: pass
#             if ext_conn:
#                 try: ext_conn.close()
#                 except: pass

#         results.append(db_result)

#     # ── 2. PostgreSQL (from database_credential table) ──
#     if not PSYCOPG2_AVAILABLE:
#         return results

#     pg_cursor = None
#     pg_cred_rows = []
#     try:
#         pg_cursor = conn.cursor(dictionary=True)
#         pg_cursor.execute("""
#             SELECT credential, db_type
#             FROM database_credential
#             WHERE session_id = %s AND db_type IN ('postgresql', 'postgres')
#             ORDER BY connection_id DESC
#         """, (session_id,))
#         pg_cred_rows = pg_cursor.fetchall()
#     except Exception as e:
#         print(f"[Analysis] PG credential fetch error: {e}")
#     finally:
#         if pg_cursor: pg_cursor.close()

#     seen_pg = set()
#     for cred_row in pg_cred_rows:
#         try:
#             cred = cred_row["credential"]
#             if isinstance(cred, str):
#                 cred = json.loads(cred)

#             pg_host     = cred.get("host", "localhost")
#             pg_port     = int(cred.get("port", 5432))
#             pg_user     = cred.get("username", "")
#             pg_password = cred.get("password", "")
#             pg_database = cred.get("database", "")
#             pg_schema   = cred.get("schema")  # None/empty → all schemas

#             dedup_key = f"{pg_host}:{pg_port}/{pg_database}/{pg_schema or '__all__'}"
#             if dedup_key in seen_pg:
#                 continue
#             seen_pg.add(dedup_key)

#             # Filter: only process if this DB was requested (or no filter given)
#             if databases and pg_database not in databases:
#                 print(f"[Analysis] PG {pg_database} not in requested list — skipping")
#                 continue

#             print(f"[Analysis] Connecting PostgreSQL: {pg_host}:{pg_port}/{pg_database} schema={pg_schema or 'ALL'}")

#             pg_conn = psycopg2.connect(
#                 host=pg_host, port=pg_port,
#                 user=pg_user, password=pg_password,
#                 dbname=pg_database,
#                 connect_timeout=10
#             )
#             pg_cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

#             db_result = {
#                 "source_type":       "database",
#                 "external_database": pg_database,
#                 "new_user_db":       pg_database,
#                 "tables":            []
#             }

#             # Determine schemas
#             if pg_schema and pg_schema.strip():
#                 schemas_to_fetch = [pg_schema.strip()]
#             else:
#                 pg_cur.execute("""
#                     SELECT schema_name
#                     FROM information_schema.schemata
#                     WHERE schema_name NOT IN ('pg_catalog', 'information_schema',
#                                               'pg_toast', 'pg_temp_1', 'pg_toast_temp_1')
#                       AND schema_name NOT LIKE 'pg_temp_%'
#                       AND schema_name NOT LIKE 'pg_toast_temp_%'
#                     ORDER BY schema_name
#                 """)
#                 schemas_to_fetch = [r["schema_name"] for r in pg_cur.fetchall()]
#                 print(f"[Analysis] PG schemas: {schemas_to_fetch}")

#             for schema in schemas_to_fetch:
#                 pg_cur.execute("""
#                     SELECT table_name
#                     FROM information_schema.tables
#                     WHERE table_schema = %s AND table_type = 'BASE TABLE'
#                     ORDER BY table_name
#                 """, (schema,))
#                 tables = [r["table_name"] for r in pg_cur.fetchall()]
#                 print(f"[Analysis] PG schema '{schema}' tables: {tables}")

#                 for t in tables:
#                     qualified = f"{schema}.{t}"
#                     try:
#                         pg_cur.execute(
#                             f'SELECT * FROM "{schema}"."{t}" LIMIT %s',
#                             (MAX_ROWS,)
#                         )
#                         rows = [dict(r) for r in pg_cur.fetchall()]
#                         row_count = len(rows)
#                         if row_count == 0:
#                             continue

#                         # Serialise non-JSON types
#                         for row in rows:
#                             for k, v in row.items():
#                                 if v is not None and not isinstance(v, (str, int, float, bool)):
#                                     row[k] = str(v)

#                         cols = list(rows[0].keys())
#                         col_stats = {}
#                         for col in cols:
#                             vals = [
#                                 str(r[col]).strip()
#                                 for r in rows
#                                 if r.get(col) is not None and str(r[col]).strip()
#                             ]
#                             distinct_vals = list(dict.fromkeys(vals))
#                             col_stats[col] = {
#                                 "total_values":    len(vals),
#                                 "distinct_values": len(distinct_vals),
#                                 "sample":          distinct_vals[:10]
#                             }

#                         db_result["tables"].append({
#                             "table_name":   qualified,
#                             "row_count":    row_count,
#                             "columns":      cols,
#                             "column_stats": col_stats,
#                             "sample_rows":  rows[:5]
#                         })
#                         print(f"[Analysis] PG {pg_database}.{qualified}: {row_count} rows")

#                     except Exception as te:
#                         print(f"[Analysis] PG skip {qualified}: {te}")
#                         pg_conn.rollback()

#             pg_cur.close()
#             pg_conn.close()
#             results.append(db_result)

#         except Exception as e:
#             print(f"[Analysis] PostgreSQL connect error: {e}")

#     return results


# # ══════════════════════════════════════════════════════
# # CONTEXT BUILDER
# # ══════════════════════════════════════════════════════

# def _build_context(web_data: list, db_data: list) -> str:
#     parts = []

#     for w in web_data:
#         lines = [f"=== WEB TOPIC: {w['topic']} ({w['result_count']} results) ==="]
#         for item in w["items"]:
#             lines.append(f"  Title : {item['title']}")
#             lines.append(f"  URL   : {item['url']}")
#             if item.get("brief"):
#                 lines.append(f"  Brief : {item['brief'][:300]}")
#         parts.append("\n".join(lines))

#     for d in db_data:
#         lines = [f"=== DATABASE: {d['external_database']} (stored as: {d['new_user_db']}) ==="]
#         for tbl in d["tables"]:
#             lines.append(f"\n  Table: {tbl['table_name']} ({tbl['row_count']} rows)")
#             lines.append(f"  Columns: {', '.join(tbl['columns'])}")
#             for col, stats in tbl["column_stats"].items():
#                 lines.append(
#                     f"    {col}: {stats['distinct_values']} distinct -- "
#                     f"sample: {', '.join(str(v) for v in stats['sample'][:8])}"
#                 )
#             lines.append("  Sample rows (up to 5):")
#             for i, row in enumerate(tbl["sample_rows"], 1):
#                 r_str = " | ".join(
#                     f"{k}:{v}" for k, v in row.items()
#                     if v is not None and str(v).strip()
#                 )
#                 lines.append(f"    Row{i}: {r_str}")
#         parts.append("\n".join(lines))

#     ctx = "\n\n".join(parts)
#     if len(ctx) > MAX_CTX_CHARS:
#         ctx = ctx[:MAX_CTX_CHARS] + "\n\n[... truncated ...]"
#     return ctx


# # ══════════════════════════════════════════════════════
# # MISTRAL — REPORT GENERATION
# # ══════════════════════════════════════════════════════

# def _call_mistral(context: str, topics: list, databases: list) -> dict:
#     source_desc = []
#     if topics:    source_desc.append(f"web topics: {', '.join(topics)}")
#     if databases: source_desc.append(f"databases: {', '.join(databases)}")

#     system = """ IQ200 You are an expert business analyst and strategist.
# Your task is to analyze the provided sales data of different types of tyres, tubes, Ret read Belt, Vul Solutions, flap  and extract purely business-focused insights and context.
# CRITICAL INSTRUCTIONS:
# 1. Do NOT include ANY technical details (e.g., table names, column names, row counts, distinct values, data types, schema info, missing values, database structure).
# 2. Use ONLY actual values, numbers, and facts from the data provided. DO NOT invent or assume any data.
# 3. The column "Customer" means the unique customer, buyer, performer who are categorised or grouped under "Group". The column "Region" means the area or the city where the customer is located. The product type or material type is based on the columns "CATEGORY", "CONSTRUCTION",TYRE TYPE". Total sales, invoice value, revenue, performance should be calculated on the column "Invoice value"
# 4. Identify the key columns in the data such as region, account group, product category, construction, tyre type and summarise the    taxable value, claims, quantity, tatal gst and invoice value.
# 5. The report must dynamically adapt to the dataset and focus purely on actionable business insights, performance, and trends.
# 6. Respond ONLY in valid JSON with a single key: "report".
# """

#     user = f"""
# Analyze the strictly provided business data ({'; '.join(source_desc)}):

# {context}

# Generate a detailed, purely business-focused summary highlighting key insights. 
# ALSO, generate exactly 5 "What" critical questions about the data.
# ALSO, generate a category-wise trend report as a "line_chart" visualization extracting numeric/categorical trend values.

# Return ONLY this JSON:
# {{
#   "report": "TITLE: <Create a descriptive business-focused title based on the data>\\n\\n<Executive Summary: 3-4 sentences summarizing overall business performance, key trends, and the main takeaway. Do not mention data tables or row counts.>\\n\\n### Key Business Insights\\n\\n- **Overall Performance & Trends**: <Highlight overall metric performance, growth/decline patterns over time, and significant variations>\\n- **Volume Analysis**: <Analyze volume such as high/low periods, increasing/decreasing momentum>\\n- **Time-Based Movements**: <Detail week-wise, month-wise, or date-wise upward/downward movements, peak periods, and lowest periods>\\n- **Anomalies & Spikes**: <Identify sudden spikes, sudden drops, or outlier behavior with corresponding dates or periods>\\n- **Segment Performance**: <Highlight product, category, region, customer, or channel performance based on available data>\\n- **Key Drivers**: <Identify key business drivers and observations derived from the data>\\n\\n### Actionable Recommendations\\n\\n- <Actionable recommendation 1 based on the data>\\n- <Actionable recommendation 2 based on the data>\\n- <Strategic conclusion>",
#   "follow_up_questions": ["What ...?", "What ...?", "What ...?", "What ...?", "What ...?"],
#   "visualizations": [
#     {{
#       "type": "line_chart",
#       "title": "Category-wise Trend Report",
#       "xKey": "category",
#       "yKey": "value",
#       "data": [
#         {{"category": "A", "value": 100}},
#         {{"category": "B", "value": 200}}
#       ]
#     }}
#   ]
# }}

# RULES:
# - Replace all <...> with REAL business insights and metrics from the actual data provided.
# - DO NOT mention tables, rows, columns, data types, nulls, or database schema. Keep it 100% business-focused.
# - If specific segments (e.g., categories, regions) or time periods are missing in the data, omit that specific bullet or adapt it to what IS available.
# - Minimum 15-20 lines inside the report string.
# - Use \\n for newlines inside the JSON string.
# - Every point must reference a specific value, name, or number from the actual data.
# - Do NOT use generic filler sentences.
# """
#     messages = [
#         {"role": "system", "content": system},
#         {"role": "user",   "content": user}
#     ]
#     try:
#         content_str = call_llm_chat(messages, json_mode=True, temperature=0.2)
#         return json.loads(content_str)
#     except Exception as e:
#         print(f"[LLM] session analysis error: {e}")
#         return None


# # ══════════════════════════════════════════════════════
# # MAIN CONTROLLER  —  POST /session-analysis
# # ══════════════════════════════════════════════════════

# def session_analysis_controller(get_connection_func):
#     data       = request.json or {}
#     session_id = (data.get("session_id") or "").strip()
#     topics     = [t.strip() for t in (data.get("topics")    or []) if str(t).strip()]
#     databases  = [d.strip() for d in (data.get("databases") or []) if str(d).strip()]

#     if not session_id:
#         return jsonify({
#             "status": "failed", "statusCode": 400,
#             "message": "Field 'session_id' is required."
#         }), 400

#     if not topics and not databases:
#         return jsonify({
#             "status": "failed", "statusCode": 400,
#             "message": "At least one of 'topics' or 'databases' must be provided."
#         }), 400

#     conn = None
#     try:
#         conn = get_connection_func()
        
#         target_arango_db = None
#         try:
#             cursor = conn.cursor(dictionary=True)
#             cursor.execute("SELECT workspace_arango_db FROM workspaces WHERE session_id = %s", (session_id,))
#             row = cursor.fetchone()
#             if row and row.get("workspace_arango_db"):
#                 target_arango_db = row["workspace_arango_db"]
#             cursor.close()
#         except Exception as e:
#             print(f"[Analysis] DB fetch target_arango_db error: {e}")

#         # 1. Fetch raw data
#         web_data = _fetch_web_data(session_id, topics, conn)
#         db_data  = _fetch_db_data(session_id, databases, conn)

#         has_web = bool(web_data)
#         has_db = any(len(d.get("tables", [])) > 0 for d in db_data)

#         if not has_web and not has_db:
#             return jsonify({
#                 "status":     "no_data",
#                 "statusCode": 200,
#                 "message":    "আপনার ডাটাবেসে কোনো টেবিল বা ডেটা নেই, দয়া করে আগে ডেটা আপলোড করুন।"
#             }), 200


#         # 2. Build context + hash
#         context   = _build_context(web_data, db_data)
#         data_hash = _hash_context(context)

#         # 3. Raw summary (always returned in response)
#         raw_summary = {
#             "web_sources": web_data,
#             "database_sources": [
#                 {
#                     "external_database": d["external_database"],
#                     "new_user_db":       d["new_user_db"],
#                     "tables": [
#                         {
#                             "table_name":  t["table_name"],
#                             "row_count":   t["row_count"],
#                             "columns":     t["columns"],
#                             "sample_rows": t["sample_rows"]
#                         }
#                         for t in d["tables"]
#                     ]
#                 }
#                 for d in db_data
#             ]
#         }

#         # 4. Check cache
#         cached = _load_cache(session_id, data_hash, conn)

#         if cached:
#             # Cache HIT — return immediately, no LLM call
#             return jsonify({
#                 "status":     "success",
#                 "statusCode": 200,
#                 "report":     cached["report"],
#                 "graph_url":  cached["graph_url"],
#             }), 200

#         # 5. Cache MISS or STALE — generate fresh
#         analysis  = _call_mistral(context, topics, databases)
#         graph_url = generate_session_graph(session_id, web_data, db_data, target_arango_db)

#         if not analysis:
#             return jsonify({
#                 "status":     "partial",
#                 "statusCode": 200,
#                 "message":    "LLM analysis failed.",
#             }), 200

#         report = analysis.get("report", "")
#         follow_up_questions = analysis.get("follow_up_questions", [])
#         visualizations = analysis.get("visualizations", [])

#         # 6. Save to cache
#         _save_cache(session_id, data_hash, report, graph_url, topics, databases, conn)

#         return jsonify({
#             "status":     "success",
#             "statusCode": 200,
#             "report":     report,
#             "graph_url":  graph_url,
#             "follow_up_questions": follow_up_questions,
#             "visualizations": visualizations
#         }), 200

#     except Exception as e:
#         return jsonify({
#             "status": "error", "statusCode": 500,
#             "message": str(e)
#         }), 500
#     finally:
#         if conn: conn.close()
           