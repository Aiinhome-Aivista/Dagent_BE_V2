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


def generate_session_graph(session_id, web_data, db_data):

    net = Network(
        height="850px",
        width="100%",
        bgcolor="#222222",
        font_color="white",
        directed=False
    )

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