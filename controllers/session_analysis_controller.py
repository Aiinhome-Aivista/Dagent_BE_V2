# # controllers/session_analysis_controller.py
# #
# # POST /session-analysis
# #
# # Body:
# # {
# #   "session_id": "xxx",
# #   "topics":     ["AI", "Python"],          // optional — from saved_web_results
# #   "databaseses":  ["recipe", "code_complacity"]  // optional — from external_db_sync_log
# # }
# #
# # At least one of topics / databaseses must be provided.
# #
# # Returns: structured multi-section analysis report as JSON

# import re
# import json
# import requests
# import mysql.connector
# from flask import request, jsonify
# from database.config import MISTRAL_API_KEY, MISTRAL_MODEL, MYSQL_CONFIG

# from pyvis.network import Network
# import os
# import uuid
# from database.config import GRAPH_FOLDER, BASE_URL

# MISTRAL_URL    = "https://api.mistral.ai/v1/chat/completions"
# MAX_ROWS       = 100
# MAX_CTX_CHARS  = 24000




# # def generate_session_graph(session_id, web_data, db_data):

# #     net = Network(
# #         height="850px",
# #         width="100%",
# #         bgcolor="#222222",
# #         font_color="white",
# #         directed=False
# #     )

# #     SESSION_STYLE = {
# #         "color": "#00bfa5",
# #         "size": 35
# #     }

# #     TOPIC_STYLE = {
# #         "color": "#ff4081",
# #         "size": 20
# #     }

# #     DB_STYLE = {
# #         "color": "#2979ff",
# #         "size": 25
# #     }

# #     TABLE_STYLE = {
# #         "color": "#ffc107",
# #         "size": 15
# #     }

# #     session_node = f"session_{session_id}"

# #     net.add_node(session_node, label=f"Session {session_id}", **SESSION_STYLE)

# #     # Web Topics
# #     for w in web_data:

# #         topic = w["topic"]

# #         net.add_node(topic, label=topic, **TOPIC_STYLE)
# #         net.add_edge(session_node, topic)

# #         for item in w["items"]:
# #             title = item["title"][:40]

# #             net.add_node(title, label=title)
# #             net.add_edge(topic, title)

# #     # databaseses
# #     for db in db_data:

# #         db_name = db["external_database"]

# #         net.add_node(db_name, label=db_name, **DB_STYLE)
# #         net.add_edge(session_node, db_name)

# #         for table in db["tables"]:

# #             tname = table["table_name"]

# #             net.add_node(tname, label=tname, **TABLE_STYLE)
# #             net.add_edge(db_name, tname)

# #     html_filename = f"graph_{uuid.uuid4().hex[:8]}.html"

# #     html_path = os.path.join(GRAPH_FOLDER, html_filename)

# #     net.save_graph(html_path)

# #     graph_url = f"{BASE_URL}/graphs/{html_filename}"

# #     return graph_url



# def detect_table_relationships(table_columns):

#     prompt = f"""
# You are a database expert.

# Find relationships between tables using column names.

# Return ONLY JSON like:
# [
#   {{"table1":"table_name","column1":"column","table2":"table_name","column2":"column"}}
# ]

# Tables and columns:
# {json.dumps(table_columns, indent=2)}
# """

#     try:
#         resp = requests.post(
#             MISTRAL_URL,
#             headers={
#                 "Authorization": f"Bearer {MISTRAL_API_KEY}",
#                 "Content-Type": "application/json"
#             },
#             json={
#                 "model": MISTRAL_MODEL,
#                 "messages":[{"role":"user","content":prompt}],
#                 "temperature":0
#             },
#             timeout=60
#         )

#         text = resp.json()["choices"][0]["message"]["content"]

#         return json.loads(text)

#     except Exception as e:
#         print("Relationship detection error:", e)
#         return []


# def generate_session_graph(session_id, web_data, db_data):

#     net = Network(
#         height="850px",
#         width="100%",
#         bgcolor="#222222",
#         font_color="white",
#         directed=False
#     )

#     SESSION_STYLE = {"color": "#00bfa5", "size": 35}
#     TOPIC_STYLE   = {"color": "#ff4081", "size": 20}
#     DB_STYLE      = {"color": "#2979ff", "size": 25}
#     TABLE_STYLE   = {"color": "#ffc107", "size": 15}

#     session_node = f"session_{session_id}"
#     net.add_node(session_node, label=f"Session {session_id}", **SESSION_STYLE)

#     # -------------------------
#     # Web Topics
#     # -------------------------
#     for w in web_data:

#         topic = w["topic"]
#         net.add_node(topic, label=topic, **TOPIC_STYLE)
#         net.add_edge(session_node, topic)

#         for item in w["items"]:
#             title = item["title"][:40]
#             net.add_node(title, label=title)
#             net.add_edge(topic, title)


#     # -------------------------
#     # DB SECTION
#     # -------------------------
#     table_columns = {} 
#     for db in db_data:

#         db_name = db["external_database"]

#         net.add_node(db_name, label=db_name, **DB_STYLE)
#         net.add_edge(session_node, db_name)

#         for table in db["tables"]:

#             tname = table["table_name"]
#             columns = table.get("columns", [])
#             table_columns[tname] = columns
#             # Table node
#             net.add_node(
#                 tname,
#                 label=tname,
#                 shape="box",
#                 **TABLE_STYLE
#             )

#             net.add_edge(db_name, tname)

#             # Column nodes
#             for col in columns:

#                 col_node = f"{tname}.{col}"

#                 net.add_node(
#                     col_node,
#                     label=col,
#                     color="#9ccc65",
#                     size=10
#                 )

#                 net.add_edge(tname, col_node)


#     # -------------------------
#     # Detect Table Relationships using LLM
#     # -------------------------

#     relationships = detect_table_relationships(table_columns)

#     for r in relationships:

#         try:

#             col1 = f"{r['table1']}.{r['column1']}"
#             col2 = f"{r['table2']}.{r['column2']}"

#             net.add_edge(
#                 col1,
#                 col2,
#                 color="#ff5252",
#                 width=4,
#                 label="relation"
#             )

#         except Exception as e:
#             print("Relationship edge error:", e)

#     # -------------------------
#     # Save Graph
#     # -------------------------
#     html_filename = f"graph_{uuid.uuid4().hex[:8]}.html"
#     html_path = os.path.join(GRAPH_FOLDER, html_filename)

#     net.save_graph(html_path)

#     graph_url = f"{BASE_URL}/graphs/{html_filename}"

#     return graph_url
# # ══════════════════════════════════════════════════════
# # DATA FETCHERS
# # ══════════════════════════════════════════════════════

# def _fetch_web_data(session_id: str, topics: list, conn) -> list:
#     """Fetch saved_web_results filtered by session_id + topic list."""
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
#             WHERE session_id = %s
#               AND topic IN ({placeholders})
#             ORDER BY topic, saved_at DESC
#         """, [session_id] + topics)
#         rows = cursor.fetchall()

#         # Group by topic
#         grouped = {}
#         for r in rows:
#             t = r["topic"]
#             if t not in grouped:
#                 grouped[t] = []
#             grouped[t].append({
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
#               AND new_user_db IS NOT NULL
#               AND new_user_db != ''
#         """, [session_id] + databaseses)

#         rows = cursor.fetchall()

#         db_map = {r["external_database"]: r["new_user_db"] for r in rows}

#         print(f"[Analysis] DB MAP -> {db_map}")

#     except Exception as e:
#         print(f"[Analysis] db_map error: {e}")
#         return []

#     finally:
#         if cursor:
#             cursor.close()

#     for ext_db in databaseses:

#         new_db = db_map.get(ext_db)

#         if not new_db:
#             print(f"[Analysis] No mapped DB for {ext_db}")
#             continue

#         db_result = {
#             "source_type": "database",
#             "external_database": ext_db,
#             "new_user_db": new_db,
#             "tables": []
#         }

#         ext_conn = None
#         ext_cur = None

#         try:

#             print(f"[Analysis] Connecting DB -> {new_db}")

#             ext_conn = mysql.connector.connect(
#                 host=MYSQL_CONFIG["host"],
#                 port=MYSQL_CONFIG["port"],
#                 user=MYSQL_CONFIG["user"],
#                 password=MYSQL_CONFIG["password"],
#                 database=new_db,
#                 connection_timeout=10
#             )

#             ext_cur = ext_conn.cursor(dictionary=True)

#             # Fetch tables
#             ext_cur.execute("SHOW TABLES")
#             tables_raw = ext_cur.fetchall()

#             tables = [list(r.values())[0] for r in tables_raw]

#             print(f"[Analysis] Tables in {new_db} -> {tables}")

#             for t in tables:

#                 print(f"[Analysis] Reading table -> {t}")

#                 try:

#                     ext_cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
#                     rows = ext_cur.fetchall()

#                     row_count = len(rows)

#                     if row_count > 0:
#                         cols = list(rows[0].keys())
#                     else:
#                         cols = []

#                     # Column statistics
#                     col_stats = {}

#                     if row_count > 0:

#                         for col in cols:

#                             vals = []

#                             for r in rows:
#                                 val = r.get(col)

#                                 if val is None:
#                                     continue

#                                 val_str = str(val).strip()

#                                 if val_str:
#                                     vals.append(val_str)

#                             distinct_vals = list(dict.fromkeys(vals))

#                             col_stats[col] = {
#                                 "total_values": len(vals),
#                                 "distinct_values": len(distinct_vals),
#                                 "sample": distinct_vals[:10]
#                             }

#                     db_result["tables"].append({
#                         "table_name": t,
#                         "row_count": row_count,
#                         "columns": cols,
#                         "column_stats": col_stats,
#                         "sample_rows": rows[:5] if rows else []
#                     })

#                 except Exception as table_error:
#                     print(f"[Analysis] table {t} error -> {table_error}")

#         except Exception as db_error:
#             print(f"[Analysis] connect {new_db} error -> {db_error}")

#         finally:

#             if ext_cur:
#                 try:
#                     ext_cur.close()
#                 except:
#                     pass

#             if ext_conn:
#                 try:
#                     ext_conn.close()
#                 except:
#                     pass

#         results.append(db_result)

#     return results


# # def _fetch_db_data(session_id: str, databaseses: list, conn) -> list:
# #     """
# #     For each requested database:
# #       1. Get new_user_db from external_db_sync_log
# #       2. Connect to new_user_db and read all tables (up to MAX_ROWS each)
# #     """
# #     if not databaseses:
# #         return []
# #     cursor = None
# #     results = []
# #     try:
# #         cursor = conn.cursor(dictionary=True)
# #         placeholders = ",".join(["%s"] * len(databaseses))
# #         cursor.execute(f"""
# #             SELECT DISTINCT external_database, new_user_db
# #             FROM external_db_sync_log
# #             WHERE session_id = %s
# #               AND external_database IN ({placeholders})
# #               AND new_user_db IS NOT NULL AND new_user_db != ''
# #         """, [session_id] + databaseses)
# #         db_map = {r["external_database"]: r["new_user_db"] for r in cursor.fetchall()}
# #     except Exception as e:
# #         print(f"[Analysis] db_map error: {e}")
# #         return []
# #     finally:
# #         if cursor: cursor.close()

# #     for ext_db in databaseses:
# #         new_db = db_map.get(ext_db)
# #         if not new_db or not re.match(r'^\w+$', new_db):
# #             continue

# #         db_result = {
# #             "source_type":       "database",
# #             "external_database": ext_db,
# #             "new_user_db":       new_db,
# #             "tables":            []
# #         }

# #         ext_conn = ext_cur = None
# #         try:
# #             ext_conn = mysql.connector.connect(
# #                 host=MYSQL_CONFIG["host"], port=MYSQL_CONFIG["port"],
# #                 user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"],
# #                 database=new_db, connection_timeout=10
# #             )
# #             ext_cur = ext_conn.cursor(dictionary=True)
# #             ext_cur.execute("SHOW TABLES")
# #             tables = [list(r.values())[0] for r in ext_cur.fetchall()]

# #             for t in tables:
# #                 if not re.match(r'^\w+$', t):
# #                     continue
# #                 try:
# #                     ext_cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
# #                     rows = ext_cur.fetchall()
# #                     if not rows:
# #                         continue
# #                     cols = list(rows[0].keys())

# #                     # Compute column stats
# #                     col_stats = {}
# #                     for col in cols:
# #                         vals = [str(r[col]) for r in rows
# #                                 if r[col] is not None and str(r[col]).strip()]
# #                         distinct = list(dict.fromkeys(vals))
# #                         col_stats[col] = {
# #                             "total_values":    len(vals),
# #                             "distinct_values": len(distinct),
# #                             "sample":          distinct[:10]
# #                         }

# #                     db_result["tables"].append({
# #                         "table_name":  t,
# #                         "row_count":   len(rows),
# #                         "columns":     cols,
# #                         "column_stats": col_stats,
# #                         "sample_rows": [
# #                             {k: v for k, v in r.items()}
# #                             for r in rows[:5]
# #                         ]
# #                     })
# #                 except Exception as e:
# #                     print(f"[Analysis] table {t}: {e}")

# #         except Exception as e:
# #             print(f"[Analysis] connect {new_db}: {e}")
# #         finally:
# #             if ext_cur:  ext_cur.close()
# #             if ext_conn: ext_conn.close()

# #         results.append(db_result)

# #     return results


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
#             # Column stats
#             for col, stats in tbl["column_stats"].items():
#                 lines.append(
#                     f"    {col}: {stats['distinct_values']} distinct values — "
#                     f"sample: {', '.join(str(v) for v in stats['sample'][:8])}"
#                 )
#             # Sample rows
#             lines.append(f"  Sample rows (up to 5):")
#             for i, row in enumerate(tbl["sample_rows"], 1):
#                 r_str = " | ".join(f"{k}:{v}" for k,v in row.items()
#                                    if v is not None and str(v).strip())
#                 lines.append(f"    Row{i}: {r_str}")
#         parts.append("\n".join(lines))

#     ctx = "\n\n".join(parts)
#     if len(ctx) > MAX_CTX_CHARS:
#         ctx = ctx[:MAX_CTX_CHARS] + "\n\n[... truncated ...]"
#     return ctx


# # ══════════════════════════════════════════════════════
# # MISTRAL
# # ══════════════════════════════════════════════════════

# def _call_mistral(context: str, topics: list, databaseses: list) -> dict:
#     source_desc = []
#     if topics:    source_desc.append(f"web topics: {', '.join(topics)}")
#     if databaseses: source_desc.append(f"databaseses: {', '.join(databaseses)}")

#     system = """You are a senior data analyst who writes detailed textbook-style reports.
# Your report must be written as ONE continuous plain text — like a textbook chapter.
# Mix paragraphs and bullet points naturally. Minimum 15-20 lines of content.
# Use actual values, names, numbers from the data. Never be vague or generic.
# Respond ONLY in valid JSON with a single key: "report"."""

#     user = f"""
# Analyze the following data ({'; '.join(source_desc)}):

# {context}

# Write a comprehensive textbook-style analysis report. Return ONLY this JSON:
# {{
#   "report": "TITLE: <descriptive title here>\n\n<Opening paragraph — 3 to 4 sentences introducing what data was analyzed, how many sources, key highlights.>\n\n<Second paragraph — describe the main data sources, table names, row counts, column names found.>\n\n• <Bullet: specific fact with actual value from data>\n• <Bullet: another specific metric or count>\n• <Bullet: notable user/record/entry found>\n• <Bullet: pattern or trend observed>\n• <Bullet: another important data point>\n\n<Third paragraph — deeper analysis: relationships between tables, user activity, data patterns.>\n\n• <Bullet: cross-table insight>\n• <Bullet: most active user or top record>\n• <Bullet: date range or time pattern>\n• <Bullet: data distribution observation>\n• <Bullet: anomaly or interesting finding>\n\n<Fourth paragraph — data quality and completeness observations.>\n\n• <Bullet: data quality note>\n• <Bullet: missing or null value observation>\n\n<Fifth paragraph — recommendations and conclusions based on the data.>\n\n• <Bullet: actionable recommendation>\n• <Bullet: another recommendation>\n• <Bullet: conclusion>"
# }}

# RULES:
# - Replace all <...> placeholders with REAL content from the data above.
# - Minimum 18 lines inside the report string.
# - Use \n for newlines inside the JSON string.
# - Every bullet point must have a specific value/name/number from the actual data.
# - Do NOT use generic filler — every sentence must reference actual data.
# """
#     headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}",
#                "Content-Type": "application/json", "Accept": "application/json"}
#     payload = {
#         "model": MISTRAL_MODEL,
#         "messages": [{"role":"system","content":system},
#                      {"role":"user","content":user}],
#         "response_format": {"type":"json_object"},
#         "temperature": 0.2
#     }
#     try:
#         resp = requests.post(MISTRAL_URL, headers=headers, json=payload, timeout=120)
#         resp.raise_for_status()
#         return json.loads(resp.json()["choices"][0]["message"]["content"])
#     except Exception as e:
#         print(f"[Mistral] {e}")
#         return None


# # ══════════════════════════════════════════════════════
# # MAIN CONTROLLER  —  POST /session-analysis
# # ══════════════════════════════════════════════════════

# def session_analysis_controller(get_connection_func):
#     data       = request.json or {}
#     session_id = (data.get("session_id") or "").strip()
#     topics     = [t.strip() for t in (data.get("topics")    or []) if str(t).strip()]
#     databaseses  = [d.strip() for d in (data.get("databaseses") or []) if str(d).strip()]

#     if not session_id:
#         return jsonify({
#             "status":"failed","statusCode":400,
#             "message":"Field 'session_id' is required."
#         }), 400

#     if not topics and not databaseses:
#         return jsonify({
#             "status":"failed","statusCode":400,
#             "message":"At least one of 'topics' or 'databaseses' must be provided."
#         }), 400

#     conn = None
#     try:
#         conn = get_connection_func()

#         web_data = _fetch_web_data(session_id, topics, conn)
#         db_data  = _fetch_db_data(session_id, databaseses, conn)

#         if not web_data and not db_data:
#             return jsonify({
#                 "status":"no_data","statusCode":200,
#                 "session_id":session_id,
#                 "message":"No matching data found for the provided topics/databaseses."
#             }), 200

#         # Build raw data summary (always returned)
#         raw_summary = {
#             "web_sources":      web_data,
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

#         # Build LLM context
#         context = _build_context(web_data, db_data)

#         # Call Mistral for analysis
#         analysis = _call_mistral(context, topics, databaseses)
#         # Generate Graph
#         graph_url = generate_session_graph(session_id, web_data, db_data)

#         if not analysis:
#             return jsonify({
#                 "status":"partial","statusCode":200,
#                 "session_id":session_id,
#                 "message":"LLM analysis failed, returning raw data only.",
#                 "raw_data": raw_summary
#             }), 200

#         return jsonify({
#             "status":     "success",
#             "statusCode": 200,
#             "session_id": session_id,
#             "requested": {
#                 "topics":    topics,
#                 "databaseses": databaseses
#             },
#             "report": analysis.get("report", ""),
#             "graph_url": graph_url,
#             "raw_data":  raw_summary
#         }), 200

#     except Exception as e:
#         return jsonify({
#             "status":"error","statusCode":500,
#             "message":str(e)
#         }), 500
#     finally:
#         if conn: conn.close()


# controllers/session_analysis_controller.py
#
# POST /session-analysis
#
# Body:
# {
#   "session_id": "xxx",
#   "topics":     ["AI", "Python"],           // optional
#   "databases":  ["recipe", "O2C"]           // optional
# }
#
# Cache logic:
#   - Builds a SHA-256 hash of the raw context (DB rows + web briefs).
#   - If session_id exists in session_analysis_cache AND hash matches
#     → return saved report + graph_url immediately (no LLM call).
#   - If session_id is new OR hash differs (data changed)
#     → call LLM, generate graph, upsert cache row.

import hashlib
import re
import json
import requests
# pyrefly: ignore [missing-import]
import mysql.connector
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("[Analysis] psycopg2 not installed — PostgreSQL support disabled")
from flask import request, jsonify
from database.config import MISTRAL_API_KEY, MISTRAL_MODEL, MYSQL_CONFIG
from model.llm_client import call_llm_chat

# pyrefly: ignore [missing-import]
from pyvis.network import Network
import os
import uuid
import re
# pyrefly: ignore [missing-import]
from arango import ArangoClient
from database.config import (
    GRAPH_FOLDER, BASE_URL,
    ARANGO_HOST, ARANGO_USER, ARANGO_PASS, ARANGO_DB
)

MISTRAL_URL   = "https://api.mistral.ai/v1/chat/completions"
MAX_ROWS      = 100
MAX_CTX_CHARS = 24000


# ══════════════════════════════════════════════════════
# CACHE HELPERS
# ══════════════════════════════════════════════════════

def _hash_context(context: str) -> str:
    """Return SHA-256 hex digest of the raw context string."""
    return hashlib.sha256(context.encode("utf-8")).hexdigest()


def _load_cache(session_id: str, data_hash: str, conn) -> dict | None:
    """
    Return cached {report, graph_url} if session_id exists AND hash matches.
    Returns None otherwise (miss or stale).
    """
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT `report`, `graph_url`, `data_hash`
            FROM `session_analysis_cache`
            WHERE `session_id` = %s
            LIMIT 1
        """, (session_id,))
        row = cursor.fetchone()
        if row and row["data_hash"] == data_hash:
            print(f"[Cache] HIT   session={session_id}")
            return {"report": row["report"], "graph_url": row["graph_url"]}
        if row:
            print(f"[Cache] STALE session={session_id} — data changed, regenerating")
        else:
            print(f"[Cache] MISS  session={session_id} — first time")
        return None
    except Exception as e:
        print(f"[Cache] load error: {e}")
        return None
    finally:
        if cursor:
            cursor.close()


def _save_cache(session_id: str, data_hash: str,
                report: str, graph_url: str,
                topics: list, databases: list, conn) -> None:
    """Upsert cache row for this session."""
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO `session_analysis_cache`
                (`session_id`, `data_hash`, `report`, `graph_url`, `topics`, `databases`)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                `data_hash`  = VALUES(`data_hash`),
                `report`     = VALUES(`report`),
                `graph_url`  = VALUES(`graph_url`),
                `topics`     = VALUES(`topics`),
                `databases`  = VALUES(`databases`),
                `updated_at` = CURRENT_TIMESTAMP
        """, (
            session_id,
            data_hash,
            report,
            graph_url,
            json.dumps(topics),
            json.dumps(databases)
        ))
        conn.commit()
        print(f"[Cache] SAVED session={session_id}  topics={topics}  databases={databases}")
    except Exception as e:
        print(f"[Cache] save error: {e}")
        raise   # re-raise so the caller knows save failed
    finally:
        if cursor:
            cursor.close()


# ══════════════════════════════════════════════════════
# CROSS-SOURCE RELATIONSHIP DETECTION
# ══════════════════════════════════════════════════════

def detect_cross_source_relationships(table_columns: dict, web_data: list, db_data: list) -> dict:
    """
    Ask Mistral to dynamically generate a business-focused Knowledge Graph.
    """
    db_summary = {}
    for db in db_data:
        for tbl in db["tables"]:
            entry = {}
            for col, stats in tbl.get("column_stats", {}).items():
                entry[col] = stats.get("sample", [])[:10]
            db_summary[tbl["table_name"]] = entry

    web_summary = []
    for w in web_data:
        for item in w["items"]:
            web_summary.append({
                "topic": w["topic"],
                "title": item["title"],
                "brief": (item.get("brief") or "")[:200]
            })

    prompt = f"""
You are an expert Knowledge Graph Builder specializing in tyre and automotive parts distribution data.

Analyze the uploaded sales dataset and generate a RICH, HIERARCHICAL, business-focused Knowledge Graph.
The graph MUST reflect the full product taxonomy AND all business relationships visible in the data.

## DB Tables and Sample Data:
{json.dumps(db_summary, indent=2)}

## Web Data:
{json.dumps(web_summary, indent=2)}

---

## MANDATORY GRAPH STRUCTURE

### LEVEL 1 — Product Category Nodes (CATEGORY column)
Create one node per unique product category found in the data.
Known categories in this dataset: Tyre, Tube, Flap, Ret read Belt, Vul. Solution
Node type: "ProductCategory"

### LEVEL 2 — Construction Type Nodes (CONSTRUCTION column)
Create one node per unique construction type found in the data.
Known construction types: BIAS, RADIAL, BIAS DOT
Node type: "Construction"

MANDATORY EDGES — for every (Category, Construction) combination that exists in the data:
  (ProductCategory) --[HAS_CONSTRUCTION]--> (Construction)

Example: Tyre → BIAS, Tyre → RADIAL, Tube → BIAS, Tube → RADIAL, Flap → BIAS, Flap → RADIAL

### LEVEL 3 — Tyre/Vehicle Type Nodes (TYRE TYPE column)
Create one node per unique vehicle/application type found in the data.
Known types: TRUCK, LCV, CAR, SCV, Motor Cycle, SCOOTER, 3W, JEEP, TRACTOR FRONT, TRACTOR REAR, TRACTOR TRAILER, OTR, INDUSTRIAL
Node type: "VehicleSegment"

MANDATORY EDGES — for every (Construction, TyreType) combination that actually exists in the data:
  (Construction) --[FITS_VEHICLE]--> (VehicleSegment)

IMPORTANT: Only create edges that actually exist in the data. For example:
- RADIAL construction connects to: TRUCK, LCV, CAR, SCV (but NOT Motor Cycle, Scooter, 3W — those only appear under BIAS)
- BIAS construction connects to: TRUCK, LCV, SCV, Motor Cycle, SCOOTER, 3W, JEEP, TRACTOR FRONT, TRACTOR REAR, OTR, INDUSTRIAL

### LEVEL 4 — Billing/Channel Type Nodes (Billing type column)
Create nodes for each billing channel found in the data.
Node type: "BillingChannel"
Known billing types and their business meanings:
  - ZOR = Standard dealer order
  - ZBCL = Scheme/claim billing
  - ZFCL = Free of charge (FOC/sample) billing
  - ZBFO = Bill & forward billing
  - ZRDR = Return/debit note
  - ZCCR = Credit note
  - ZCC = Cash/counter sale

MANDATORY EDGES:
  (ProductCategory) --[SOLD_VIA]--> (BillingChannel)
Only create these edges for combinations that actually appear in the sample data.

### LEVEL 5 — Region and Zone Nodes
Create Region and Zone nodes from the data.
Node type: "Region" for region values (e.g., JAIPUR)
Node type: "Zone" for zone values (e.g., Central)

MANDATORY EDGES:
  (Zone) --[CONTAINS]--> (Region)
  (Region) --[TOP_CATEGORY_IN_REGION]--> (ProductCategory)  [for the highest volume category]

### LEVEL 6 — Top Material (SKU) Nodes
From the Material column, identify the TOP 8 most frequently appearing SKUs in the sample data.
Node type: "Material"

MANDATORY EDGES:
  (Material) --[BELONGS_TO]--> (ProductCategory)  [based on the category column for that material]
  (Material) --[HAS_CONSTRUCTION_TYPE]--> (Construction)
  (Material) --[USED_IN]--> (VehicleSegment)

### LEVEL 7 — Top Customer/Dealer Nodes
From the Customer column, identify the TOP 5 most frequently appearing customers in the sample data.
Node type: "Dealer"

MANDATORY EDGES:
  (Dealer) --[LOCATED_IN]--> (Region)
  (Dealer) --[PRIMARILY_BUYS]--> (ProductCategory)  [the category with most transactions for this dealer]

---

## NUMERICAL PROPERTIES (store as node/edge properties, NEVER as separate nodes)
- On ProductCategory nodes: total_quantity, total_invoice_value, transaction_count
- On VehicleSegment nodes: dominant_category (most common product category for this segment)
- On FITS_VEHICLE edges: transaction_count, avg_invoice_value
- On SOLD_VIA edges: transaction_count
- On PRIMARILY_BUYS edges: transaction_count, total_value

---

## OUTPUT FORMAT
Return EXACTLY this JSON (no markdown, no extra text):
{{
  "nodes": [
    {{"id": "cat_tyre", "label": "Tyre", "type": "ProductCategory", "properties": {{"transaction_count": 0}}}},
    {{"id": "cat_tube", "label": "Tube", "type": "ProductCategory", "properties": {{}}}},
    {{"id": "cat_flap", "label": "Flap", "type": "ProductCategory", "properties": {{}}}},
    {{"id": "const_bias", "label": "BIAS", "type": "Construction", "properties": {{}}}},
    {{"id": "const_radial", "label": "RADIAL", "type": "Construction", "properties": {{}}}},
    {{"id": "seg_truck", "label": "TRUCK", "type": "VehicleSegment", "properties": {{"dominant_category": "Tyre"}}}},
    {{"id": "seg_car", "label": "CAR", "type": "VehicleSegment", "properties": {{}}}},
    {{"id": "ch_zor", "label": "ZOR (Standard Order)", "type": "BillingChannel", "properties": {{}}}},
    {{"id": "reg_jaipur", "label": "JAIPUR", "type": "Region", "properties": {{}}}},
    {{"id": "zone_central", "label": "Central", "type": "Zone", "properties": {{}}}}
  ],
  "edges": [
    {{"from": "cat_tyre", "to": "const_bias", "label": "HAS_CONSTRUCTION", "properties": {{}}}},
    {{"from": "cat_tyre", "to": "const_radial", "label": "HAS_CONSTRUCTION", "properties": {{}}}},
    {{"from": "const_bias", "to": "seg_truck", "label": "FITS_VEHICLE", "properties": {{}}}},
    {{"from": "const_radial", "to": "seg_car", "label": "FITS_VEHICLE", "properties": {{}}}},
    {{"from": "cat_tyre", "to": "ch_zor", "label": "SOLD_VIA", "properties": {{}}}},
    {{"from": "zone_central", "to": "reg_jaipur", "label": "CONTAINS", "properties": {{}}}},
    {{"from": "reg_jaipur", "to": "cat_tyre", "label": "TOP_CATEGORY_IN_REGION", "properties": {{}}}}
  ],
  "identified_node_types": ["ProductCategory", "Construction", "VehicleSegment", "BillingChannel", "Region", "Zone", "Material", "Dealer"],
  "identified_relationship_types": ["HAS_CONSTRUCTION", "FITS_VEHICLE", "SOLD_VIA", "CONTAINS", "TOP_CATEGORY_IN_REGION", "BELONGS_TO", "HAS_CONSTRUCTION_TYPE", "USED_IN", "LOCATED_IN", "PRIMARILY_BUYS"],
  "graph_schema": [
    "(ProductCategory)-[:HAS_CONSTRUCTION]->(Construction)",
    "(Construction)-[:FITS_VEHICLE]->(VehicleSegment)",
    "(ProductCategory)-[:SOLD_VIA]->(BillingChannel)",
    "(Zone)-[:CONTAINS]->(Region)",
    "(Material)-[:BELONGS_TO]->(ProductCategory)",
    "(Dealer)-[:PRIMARILY_BUYS]->(ProductCategory)"
  ],
  "sample_cypher_queries": [
    "MATCH (c:ProductCategory)-[:HAS_CONSTRUCTION]->(cn:Construction)-[:FITS_VEHICLE]->(v:VehicleSegment) RETURN c.label, cn.label, v.label",
    "MATCH (d:Dealer)-[:PRIMARILY_BUYS]->(c:ProductCategory) RETURN d.label, c.label ORDER BY d.transaction_count DESC LIMIT 10",
    "MATCH (m:Material)-[:USED_IN]->(v:VehicleSegment) WHERE v.label='TRUCK' RETURN m.label"
  ],
  "business_insights": [
    "RADIAL construction dominates CAR and LCV segments while BIAS covers two-wheeler, SCV and tractor segments",
    "Tyre is the highest-volume ProductCategory, followed by Tube and Flap",
    "ZOR (standard order) is the primary billing channel, with ZBCL (scheme billing) significant for Tyre category",
    "TRUCK segment consumes both Tyre, Tube and Flap — all three product categories — making it the most cross-category vehicle type"
  ],
  "suggested_graphrag_paths": [
    "Start from ProductCategory → HAS_CONSTRUCTION → Construction → FITS_VEHICLE → VehicleSegment (full product-to-market path)",
    "Start from Dealer → PRIMARILY_BUYS → ProductCategory → HAS_CONSTRUCTION → Construction (dealer preference path)",
    "Start from Zone → CONTAINS → Region → TOP_CATEGORY_IN_REGION → ProductCategory (geographic demand path)"
  ]
}}

## RULES
1. Use ONLY node IDs you defined in the "nodes" array for "from"/"to" in edges.
2. Extract actual values from the sample data — do NOT invent SKU codes or customer IDs.
3. Every ProductCategory node MUST have at least one HAS_CONSTRUCTION edge.
4. Every Construction node MUST have at least one FITS_VEHICLE edge.
5. BIAS and RADIAL are different construction types for the SAME categories (Tyre, Tube, Flap) — they are siblings under each category, not children of each other.
6. Do NOT create a node for every single Material or Customer — only the top 5-8 most frequent ones from the sample.
7. Node IDs must be unique strings with no spaces (use underscores).
"""

    messages = [{"role": "user", "content": prompt}]
    try:
        raw = call_llm_chat(messages, json_mode=True, temperature=0.1)
        result = json.loads(raw)
        result.setdefault("nodes", [])
        result.setdefault("edges", [])
        return result

    except Exception as e:
        print("Business Knowledge Graph detection error:", e)
        return {"nodes": [], "edges": []}


# ══════════════════════════════════════════════════════
# GRAPH GENERATOR
# ══════════════════════════════════════════════════════

def generate_session_graph(session_id, web_data, db_data):

    net = Network(
        height="850px",
        width="100%",
        bgcolor="#222222",
        font_color="white",
        directed=True
    )

    type_colors = {
    "ProductCategory": "#ff4081",   # pink — top-level product
    "Construction":    "#e040fb",   # purple — construction subtype
    "VehicleSegment":  "#2979ff",   # blue — end-use vehicle
    "BillingChannel":  "#00bfa5",   # teal — sales channel
    "Dealer":          "#ffc107",   # amber — customer/dealer
    "Region":          "#ff9800",   # orange — geography
    "Zone":            "#ff6d00",   # deep orange — geography parent
    "Material":        "#9ccc65",   # green — SKU/product code
    "Customer":        "#ffc107",   # fallback
    "Category":        "#ff4081",   # fallback
    "Date":            "#00bcd4",
    "Month":           "#18ffff",
    }

    table_columns = {}
    for db in db_data:
        for table in db["tables"]:
            table_columns[table["table_name"]] = table.get("columns", [])

    graph_data = detect_cross_source_relationships(table_columns, web_data, db_data)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    existing_ids = set()

    for n in nodes:
        node_id = str(n.get("id"))
        if not node_id: continue
        label = str(n.get("label", node_id))
        ntype = str(n.get("type", "Entity"))
        
        props = n.get("properties", {})
        title_lines = [f"{k}: {v}" for k, v in props.items()]
        title = "\n".join(title_lines) if title_lines else ntype

        color = type_colors.get(ntype, "#b0bec5")
        
        net.add_node(node_id, label=label, title=title, color=color, size=25, type=ntype)
        existing_ids.add(node_id)

    for e in edges:
        from_node = str(e.get("from"))
        to_node = str(e.get("to"))
        label = str(e.get("label", ""))

        if from_node in existing_ids and to_node in existing_ids:
            props = e.get("properties", {})
            title_lines = [f"{k}: {v}" for k, v in props.items()]
            title = "\n".join(title_lines) if title_lines else label
            
            net.add_edge(from_node, to_node, label=label, title=title, color="#ff5252", width=2)
        else:
            print(f"[Graph] Skipped edge due to missing nodes: {from_node} -> {to_node}")

    html_filename = f"graph_{uuid.uuid4().hex[:8]}.html"
    html_path     = os.path.join(GRAPH_FOLDER, html_filename)
    net.save_graph(html_path)

    # --- Sync to ArangoDB ---
    try:
        _sync_to_arango(session_id, net.nodes, net.edges)
    except Exception as e:
        print(f"[ArangoDB] Sync failed: {e}")

    return f"{BASE_URL}/graphs/{html_filename}"

# ══════════════════════════════════════════════════════
# ARANGODB SYNC
# ══════════════════════════════════════════════════════

def _safe_key(val: str) -> str:
    """ArangoDB _key allows only [a-zA-Z0-9_:.@()-]+"""
    return re.sub(r'[^a-zA-Z0-9_:.@()-]', '_', str(val))

def _sync_to_arango(session_id: str, nodes: list, edges: list):
    print(f"[ArangoDB] Connecting to {ARANGO_HOST} ...")
    client = ArangoClient(hosts=ARANGO_HOST)
    sys_db = client.db('_system', username=ARANGO_USER, password=ARANGO_PASS)

    # Ensure database exists
    if not sys_db.has_database(ARANGO_DB):
        sys_db.create_database(ARANGO_DB)
    
    db = client.db(ARANGO_DB, username=ARANGO_USER, password=ARANGO_PASS)

    # Ensure collections exist
    nodes_col_name = "session_nodes"
    edges_col_name = "session_edges"

    if not db.has_collection(nodes_col_name):
        db.create_collection(nodes_col_name)
    if not db.has_collection(edges_col_name):
        db.create_collection(edges_col_name, edge=True)

    nodes_col = db.collection(nodes_col_name)
    edges_col = db.collection(edges_col_name)

    # Sync Nodes
    print(f"[ArangoDB] Syncing {len(nodes)} nodes...")
    for n in nodes:
        key = _safe_key(n["id"])
        doc = {
            "_key": key,
            "session_id": session_id,
            "label": n.get("label", ""),
            "original_id": n["id"],
            "type": n.get("type") or (n["id"].split('_')[0] if '_' in n["id"] else "unknown")
        }
        try:
            if nodes_col.has(key):
                nodes_col.update(doc)
            else:
                nodes_col.insert(doc)
        except Exception as e:
            print(f"[ArangoDB] skip node {key}: {e}")

    # Sync Edges
    print(f"[ArangoDB] Syncing {len(edges)} edges...")
    for e in edges:
        from_key = _safe_key(e["from"])
        to_key   = _safe_key(e["to"])
        edge_key = _safe_key(f"{from_key}_to_{to_key}")
        
        doc = {
            "_key": edge_key,
            "_from": f"{nodes_col_name}/{from_key}",
            "_to": f"{nodes_col_name}/{to_key}",
            "session_id": session_id,
            "label": e.get("label", ""),
            "title": e.get("title", "")
        }
        try:
            if edges_col.has(edge_key):
                edges_col.update(doc)
            else:
                edges_col.insert(doc)
        except Exception as ex:
            print(f"[ArangoDB] skip edge {edge_key}: {ex}")

    print("[ArangoDB] Sync Complete!")


# ══════════════════════════════════════════════════════
# DATA FETCHERS
# ══════════════════════════════════════════════════════

def _fetch_web_data(session_id: str, topics: list, conn) -> list:
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
            WHERE `session_id` = %s
              AND topic IN ({placeholders})
            ORDER BY topic, saved_at DESC
        """, [session_id] + topics)
        rows = cursor.fetchall()

        grouped = {}
        for r in rows:
            t = r["topic"]
            grouped.setdefault(t, []).append({
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


def _fetch_db_data(session_id: str, databases: list, conn) -> list:
    """
    Fetch DB data for analysis — supports MySQL and PostgreSQL.
    For PostgreSQL:
      - schema provided → only that schema's tables
      - no schema → all non-system schemas (public + custom)
    """
    results = []

    # ── 1. MySQL / MSSQL (sync log approach) ──
    cursor = None
    db_map = {}
    try:
        cursor = conn.cursor(dictionary=True)
        if databases:
            placeholders = ",".join(["%s"] * len(databases))
            cursor.execute(f"""
                SELECT DISTINCT external_database, new_user_db, table_name
                FROM external_db_sync_log
                WHERE `session_id` = %s
                  AND external_database IN ({placeholders})
                  AND new_user_db IS NOT NULL
                  AND new_user_db != ''
            """, [session_id] + databases)
            rows = cursor.fetchall()
            for r in rows:
                ext_db = r["external_database"]
                if ext_db not in db_map:
                    db_map[ext_db] = {"new_user_db": r["new_user_db"], "tables": []}
                if r.get("table_name"):
                    db_map[ext_db]["tables"].append(r["table_name"])
            print(f"[Analysis] MySQL DB MAP -> {db_map}")
    except Exception as e:
        print(f"[Analysis] db_map error: {e}")
    finally:
        if cursor: cursor.close()

    for ext_db in databases:
        db_info = db_map.get(ext_db)
        if not db_info:
            continue

        new_db = db_info["new_user_db"]
        allowed_tables = db_info["tables"]

        db_result = {
            "source_type":       "database",
            "external_database": ext_db,
            "new_user_db":       new_db,
            "tables":            []
        }

        ext_conn = ext_cur = None
        try:
            print(f"[Analysis] Connecting MySQL -> {new_db}")
            ext_conn = mysql.connector.connect(
                host=MYSQL_CONFIG["host"],
                port=MYSQL_CONFIG["port"],
                user=MYSQL_CONFIG["user"],
                password=MYSQL_CONFIG["password"],
                database=new_db,
                connection_timeout=10
            )
            ext_cur = ext_conn.cursor(dictionary=True)
            
            # Filter tables: only use those explicitly synced for this database
            if allowed_tables:
                tables = allowed_tables
            else:
                ext_cur.execute("SHOW TABLES")
                tables = [list(r.values())[0] for r in ext_cur.fetchall()]
                
            print(f"[Analysis] Tables in {new_db} for {ext_db} -> {tables}")

            for t in tables:
                try:
                    ext_cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
                    rows      = ext_cur.fetchall()
                    row_count = len(rows)
                    cols      = list(rows[0].keys()) if row_count > 0 else []
                    col_stats = {}
                    if row_count > 0:
                        for col in cols:
                            vals = [
                                str(r[col]).strip()
                                for r in rows
                                if r.get(col) is not None and str(r[col]).strip()
                            ]
                            distinct_vals = list(dict.fromkeys(vals))
                            col_stats[col] = {
                                "total_values":    len(vals),
                                "distinct_values": len(distinct_vals),
                                "sample":          distinct_vals[:10]
                            }
                    db_result["tables"].append({
                        "table_name":   t,
                        "row_count":    row_count,
                        "columns":      cols,
                        "column_stats": col_stats,
                        "sample_rows":  rows[:5] if rows else []
                    })
                except Exception as table_error:
                    print(f"[Analysis] MySQL table {t} error -> {table_error}")

        except Exception as db_error:
            print(f"[Analysis] MySQL connect {new_db} error -> {db_error}")
        finally:
            if ext_cur:
                try: ext_cur.close()
                except: pass
            if ext_conn:
                try: ext_conn.close()
                except: pass

        results.append(db_result)

    # ── 2. PostgreSQL (from database_credential table) ──
    if not PSYCOPG2_AVAILABLE:
        return results

    pg_cursor = None
    pg_cred_rows = []
    try:
        pg_cursor = conn.cursor(dictionary=True)
        pg_cursor.execute("""
            SELECT credential, db_type
            FROM database_credential
            WHERE session_id = %s AND db_type IN ('postgresql', 'postgres')
            ORDER BY connection_id DESC
        """, (session_id,))
        pg_cred_rows = pg_cursor.fetchall()
    except Exception as e:
        print(f"[Analysis] PG credential fetch error: {e}")
    finally:
        if pg_cursor: pg_cursor.close()

    seen_pg = set()
    for cred_row in pg_cred_rows:
        try:
            cred = cred_row["credential"]
            if isinstance(cred, str):
                cred = json.loads(cred)

            pg_host     = cred.get("host", "localhost")
            pg_port     = int(cred.get("port", 5432))
            pg_user     = cred.get("username", "")
            pg_password = cred.get("password", "")
            pg_database = cred.get("database", "")
            pg_schema   = cred.get("schema")  # None/empty → all schemas

            dedup_key = f"{pg_host}:{pg_port}/{pg_database}/{pg_schema or '__all__'}"
            if dedup_key in seen_pg:
                continue
            seen_pg.add(dedup_key)

            # Filter: only process if this DB was requested (or no filter given)
            if databases and pg_database not in databases:
                print(f"[Analysis] PG {pg_database} not in requested list — skipping")
                continue

            print(f"[Analysis] Connecting PostgreSQL: {pg_host}:{pg_port}/{pg_database} schema={pg_schema or 'ALL'}")

            pg_conn = psycopg2.connect(
                host=pg_host, port=pg_port,
                user=pg_user, password=pg_password,
                dbname=pg_database,
                connect_timeout=10
            )
            pg_cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            db_result = {
                "source_type":       "database",
                "external_database": pg_database,
                "new_user_db":       pg_database,
                "tables":            []
            }

            # Determine schemas
            if pg_schema and pg_schema.strip():
                schemas_to_fetch = [pg_schema.strip()]
            else:
                pg_cur.execute("""
                    SELECT schema_name
                    FROM information_schema.schemata
                    WHERE schema_name NOT IN ('pg_catalog', 'information_schema',
                                              'pg_toast', 'pg_temp_1', 'pg_toast_temp_1')
                      AND schema_name NOT LIKE 'pg_temp_%'
                      AND schema_name NOT LIKE 'pg_toast_temp_%'
                    ORDER BY schema_name
                """)
                schemas_to_fetch = [r["schema_name"] for r in pg_cur.fetchall()]
                print(f"[Analysis] PG schemas: {schemas_to_fetch}")

            for schema in schemas_to_fetch:
                pg_cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """, (schema,))
                tables = [r["table_name"] for r in pg_cur.fetchall()]
                print(f"[Analysis] PG schema '{schema}' tables: {tables}")

                for t in tables:
                    qualified = f"{schema}.{t}"
                    try:
                        pg_cur.execute(
                            f'SELECT * FROM "{schema}"."{t}" LIMIT %s',
                            (MAX_ROWS,)
                        )
                        rows = [dict(r) for r in pg_cur.fetchall()]
                        row_count = len(rows)
                        if row_count == 0:
                            continue

                        # Serialise non-JSON types
                        for row in rows:
                            for k, v in row.items():
                                if v is not None and not isinstance(v, (str, int, float, bool)):
                                    row[k] = str(v)

                        cols = list(rows[0].keys())
                        col_stats = {}
                        for col in cols:
                            vals = [
                                str(r[col]).strip()
                                for r in rows
                                if r.get(col) is not None and str(r[col]).strip()
                            ]
                            distinct_vals = list(dict.fromkeys(vals))
                            col_stats[col] = {
                                "total_values":    len(vals),
                                "distinct_values": len(distinct_vals),
                                "sample":          distinct_vals[:10]
                            }

                        db_result["tables"].append({
                            "table_name":   qualified,
                            "row_count":    row_count,
                            "columns":      cols,
                            "column_stats": col_stats,
                            "sample_rows":  rows[:5]
                        })
                        print(f"[Analysis] PG {pg_database}.{qualified}: {row_count} rows")

                    except Exception as te:
                        print(f"[Analysis] PG skip {qualified}: {te}")
                        pg_conn.rollback()

            pg_cur.close()
            pg_conn.close()
            results.append(db_result)

        except Exception as e:
            print(f"[Analysis] PostgreSQL connect error: {e}")

    return results


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
            for col, stats in tbl["column_stats"].items():
                lines.append(
                    f"    {col}: {stats['distinct_values']} distinct -- "
                    f"sample: {', '.join(str(v) for v in stats['sample'][:8])}"
                )
            lines.append("  Sample rows (up to 5):")
            for i, row in enumerate(tbl["sample_rows"], 1):
                r_str = " | ".join(
                    f"{k}:{v}" for k, v in row.items()
                    if v is not None and str(v).strip()
                )
                lines.append(f"    Row{i}: {r_str}")
        parts.append("\n".join(lines))

    ctx = "\n\n".join(parts)
    if len(ctx) > MAX_CTX_CHARS:
        ctx = ctx[:MAX_CTX_CHARS] + "\n\n[... truncated ...]"
    return ctx


# ══════════════════════════════════════════════════════
# MISTRAL — REPORT GENERATION
# ══════════════════════════════════════════════════════

def _call_mistral(context: str, topics: list, databases: list) -> dict:
    source_desc = []
    if topics:    source_desc.append(f"web topics: {', '.join(topics)}")
    if databases: source_desc.append(f"databases: {', '.join(databases)}")

    system = """ IQ200 You are an expert business analyst and strategist.
Your task is to analyze the provided sales data of different types of tyres, tubes, Ret read Belt, Vul Solutions, flap  and extract purely business-focused insights and context.
CRITICAL INSTRUCTIONS:
1. Do NOT include ANY technical details (e.g., table names, column names, row counts, distinct values, data types, schema info, missing values, database structure).
2. Use ONLY actual values, numbers, and facts from the data provided. DO NOT invent or assume any data.
3. The column "Customer" means the unique customer, buyer, performer who are categorised or grouped under "Group". The column "Region" means the area or the city where the customer is located. The product type or material type is based on the columns "CATEGORY", "CONSTRUCTION",TYRE TYPE". Total sales, invoice value, revenue, performance should be calculated on the column "Invoice value"
4. Identify the key columns in the data such as region, account group, product category, construction, tyre type and summarise the    taxable value, claims, quantity, tatal gst and invoice value.
5. The report must dynamically adapt to the dataset and focus purely on actionable business insights, performance, and trends.
6. Respond ONLY in valid JSON with a single key: "report".
"""

    user = f"""
Analyze the strictly provided business data ({'; '.join(source_desc)}):

{context}

Generate a detailed, purely business-focused summary highlighting key insights. 
ALSO, generate exactly 5 "What" critical questions about the data.
ALSO, generate a category-wise trend report as a "line_chart" visualization extracting numeric/categorical trend values.

Return ONLY this JSON:
{{
  "report": "TITLE: <Create a descriptive business-focused title based on the data>\\n\\n<Executive Summary: 3-4 sentences summarizing overall business performance, key trends, and the main takeaway. Do not mention data tables or row counts.>\\n\\n### Key Business Insights\\n\\n- **Overall Performance & Trends**: <Highlight overall metric performance, growth/decline patterns over time, and significant variations>\\n- **Volume Analysis**: <Analyze volume such as high/low periods, increasing/decreasing momentum>\\n- **Time-Based Movements**: <Detail week-wise, month-wise, or date-wise upward/downward movements, peak periods, and lowest periods>\\n- **Anomalies & Spikes**: <Identify sudden spikes, sudden drops, or outlier behavior with corresponding dates or periods>\\n- **Segment Performance**: <Highlight product, category, region, customer, or channel performance based on available data>\\n- **Key Drivers**: <Identify key business drivers and observations derived from the data>\\n\\n### Actionable Recommendations\\n\\n- <Actionable recommendation 1 based on the data>\\n- <Actionable recommendation 2 based on the data>\\n- <Strategic conclusion>",
  "follow_up_questions": ["What ...?", "What ...?", "What ...?", "What ...?", "What ...?"],
  "visualizations": [
    {{
      "type": "line_chart",
      "title": "Category-wise Trend Report",
      "xKey": "category",
      "yKey": "value",
      "data": [
        {{"category": "A", "value": 100}},
        {{"category": "B", "value": 200}}
      ]
    }}
  ]
}}

RULES:
- Replace all <...> with REAL business insights and metrics from the actual data provided.
- DO NOT mention tables, rows, columns, data types, nulls, or database schema. Keep it 100% business-focused.
- If specific segments (e.g., categories, regions) or time periods are missing in the data, omit that specific bullet or adapt it to what IS available.
- Minimum 15-20 lines inside the report string.
- Use \\n for newlines inside the JSON string.
- Every point must reference a specific value, name, or number from the actual data.
- Do NOT use generic filler sentences.
"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user}
    ]
    try:
        content_str = call_llm_chat(messages, json_mode=True, temperature=0.2)
        return json.loads(content_str)
    except Exception as e:
        print(f"[LLM] session analysis error: {e}")
        return None


# ══════════════════════════════════════════════════════
# MAIN CONTROLLER  —  POST /session-analysis
# ══════════════════════════════════════════════════════

def session_analysis_controller(get_connection_func):
    data       = request.json or {}
    session_id = (data.get("session_id") or "").strip()
    topics     = [t.strip() for t in (data.get("topics")    or []) if str(t).strip()]
    databases  = [d.strip() for d in (data.get("databases") or []) if str(d).strip()]

    if not session_id:
        return jsonify({
            "status": "failed", "statusCode": 400,
            "message": "Field 'session_id' is required."
        }), 400

    if not topics and not databases:
        return jsonify({
            "status": "failed", "statusCode": 400,
            "message": "At least one of 'topics' or 'databases' must be provided."
        }), 400

    conn = None
    try:
        conn = get_connection_func()

        # 1. Fetch raw data
        web_data = _fetch_web_data(session_id, topics, conn)
        db_data  = _fetch_db_data(session_id, databases, conn)

        has_web = bool(web_data)
        has_db = any(len(d.get("tables", [])) > 0 for d in db_data)

        if not has_web and not has_db:
            return jsonify({
                "status":     "no_data",
                "statusCode": 200,
                "message":    "আপনার ডাটাবেসে কোনো টেবিল বা ডেটা নেই, দয়া করে আগে ডেটা আপলোড করুন।"
            }), 200


        # 2. Build context + hash
        context   = _build_context(web_data, db_data)
        data_hash = _hash_context(context)

        # 3. Raw summary (always returned in response)
        raw_summary = {
            "web_sources": web_data,
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

        # 4. Check cache
        cached = _load_cache(session_id, data_hash, conn)

        if cached:
            # Cache HIT — return immediately, no LLM call
            return jsonify({
                "status":     "success",
                "statusCode": 200,
                "report":     cached["report"],
                "graph_url":  cached["graph_url"],
            }), 200

        # 5. Cache MISS or STALE — generate fresh
        analysis  = _call_mistral(context, topics, databases)
        graph_url = generate_session_graph(session_id, web_data, db_data)

        if not analysis:
            return jsonify({
                "status":     "partial",
                "statusCode": 200,
                "message":    "LLM analysis failed.",
            }), 200

        report = analysis.get("report", "")
        follow_up_questions = analysis.get("follow_up_questions", [])
        visualizations = analysis.get("visualizations", [])

        # 6. Save to cache
        _save_cache(session_id, data_hash, report, graph_url, topics, databases, conn)

        return jsonify({
            "status":     "success",
            "statusCode": 200,
            "report":     report,
            "graph_url":  graph_url,
            "follow_up_questions": follow_up_questions,
            "visualizations": visualizations
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error", "statusCode": 500,
            "message": str(e)
        }), 500
    finally:
        if conn: conn.close()