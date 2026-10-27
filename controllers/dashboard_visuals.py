from sqlalchemy.engine import cursor
import json
from flask import request, jsonify
from model.llm_client import call_llm_chat
from database import config

def graph_metrics_controller():
    """
    Extracts the 4 dashboard metrics dynamically from the chat context.
    Expects JSON: { "question": "...", "answer": "..." }
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    question = data.get("question", "")
    answer = data.get("answer", "")
    
    defaults = {
        "metric_1": {"label": "Metric 1", "value": "N/A", "subtext": "No data available"},
        "metric_2": {"label": "Metric 2", "value": "N/A", "subtext": "No data available"},
        "metric_3": {"label": "Metric 3", "value": "N/A", "subtext": "No data available"},
        "metric_4": {"label": "Metric 4", "value": "N/A", "subtext": "No data available"}
    }

    if not answer.strip():
        return jsonify({"status": "success", "data": defaults}), 200
    
    prompt = f"""
You are a data extraction assistant for a sales dashboard. 
Based on the user's question and the system's answer below, extract up to 4 key numerical highlights or metrics dynamically.

Instead of hardcoding specific metrics, find ANY 4 meaningful metrics from the text (e.g., "Average Bulk Invoice Value", "Average Retail Invoice Value", "Volume Discount", etc.).

Question: "{question}"
Answer: "{answer}"

Return EXACTLY a valid JSON object in this format, using dynamic labels for whatever metrics you find:
{{
  "metric_1": {{"label": "Name of Metric 1", "value": "...", "subtext": "..."}},
  "metric_2": {{"label": "Name of Metric 2", "value": "...", "subtext": "..."}},
  "metric_3": {{"label": "Name of Metric 3", "value": "...", "subtext": "..."}},
  "metric_4": {{"label": "Name of Metric 4", "value": "...", "subtext": "..."}}
}}

If you cannot find 4 metrics, return null for the remaining metric fields (e.g., "metric_3": null).
"""
    messages = [{"role": "user", "content": prompt}]
    
    try:
        response = call_llm_chat(messages, temperature=0.0)
        # Clean json if it contains markdown formatting
        if response.startswith("```json"):
            response = response.replace("```json", "").replace("```", "").strip()
        elif response.startswith("```"):
            response = response.replace("```", "").strip()
            
        metrics = json.loads(response)
        
        # Provide default fallback values if any metric is null or missing
        defaults = {
            "metric_1": {"label": "Metric 1", "value": "N/A", "subtext": "No data available"},
            "metric_2": {"label": "Metric 2", "value": "N/A", "subtext": "No data available"},
            "metric_3": {"label": "Metric 3", "value": "N/A", "subtext": "No data available"},
            "metric_4": {"label": "Metric 4", "value": "N/A", "subtext": "No data available"}
        }
        
        for key in defaults:
            if key not in metrics or not metrics[key] or metrics[key].get("value") is None:
                metrics[key] = defaults[key]
            else:
                # Ensure all required fields exist
                if not metrics[key].get("label"): metrics[key]["label"] = defaults[key]["label"]
                if not metrics[key].get("subtext"): metrics[key]["subtext"] = ""
                
        return jsonify({"status": "success", "data": metrics}), 200
    except Exception as e:
        print(f"[Graph] Error extracting metrics: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def extract_graph_data_controller():
    """
    Extracts numerical data points from the chat context (question + answer)
    and formats them as structured chart data for frontend visualization.
    Expects JSON: { "question": "...", "answer": "..." }
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    question = data.get("question", "")
    answer = data.get("answer", "")
    
    prompt = f"""
You are a data visualization assistant.
Based on the user's question and the system's answer below, extract any numerical or sales data mentioned and format it as structured JSON.
You must categorize the extracted data into one of the following chart data formats based on what is being compared in the text:

1. "dummyYoYData": Use this if the data compares Year-over-Year sales (specifically 2025 vs 2026) for different regions or cities.
   Format of each item: {{ "name": "REGION_NAME", "y2026": float, "y2025": float }}
   
2. "dummyYearComparisonData": Use this if the data compares monthly sales across multiple years (2022 to 2026).
   Format of each item: {{ "month": "MONTH_NAME", "y2022": float, "y2023": float, "y2024": float, "y2025": float, "y2026": float }}
   
3. "dummyZoneData": Use this if the data shows sales across different geographic zones (e.g., Central, North, East, South, West).
   Format of each item: {{ "name": "ZONE_NAME", "value": float }}
   
4. "dummyTyreData": Use this if the data shows sales for different tyre categories (e.g., TRUCK, CAR, LCV, SCV, etc.).
   Format of each item: {{ "name": "VEHICLE _TYPE", "value": float }}

Important Instructions:
- Only populate the array that matches the data category discussed in the Q&A context. 
- For any of the 4 arrays that are NOT applicable or do not have any data mentioned in the text, return them as empty lists `[]`.
- Include the "COLORS" key exactly as shown below.
- Parse all numeric values as clean floats/integers.

Question: "{question}"
Answer: "{answer}"

Return EXACTLY a valid JSON object in this format, with no markdown formatting or extra text:
{{
  "dummyYoYData": [ ... ],
  "dummyYearComparisonData": [ ... ],
  "dummyZoneData": [ ... ],
  "COLORS": ["#0088FE", "#00C49F", "#FFBB28", "#FF8042", "#8884D8", "#E06666", "#93C47D"],
  "dummyTyreData": [ ... ]
}}
"""
    messages = [{"role": "user", "content": prompt}]
    
    try:
        response = call_llm_chat(messages, temperature=0.0)
        # Clean json if it contains markdown formatting
        if response.startswith("```json"):
            response = response.replace("```json", "").replace("```", "").strip()
        elif response.startswith("```"):
            response = response.replace("```", "").strip()
            
        chart_data = json.loads(response)
        return jsonify({"status": "success", "data": chart_data}), 200
    except Exception as e:
        print(f"[Graph] Error extracting chart data: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500




# default_dashboard_metrics_controller

# def default_dashboard_metrics_controller(get_db_connection):
#     """
#     Fetches default summary metrics (total sales, top tyre, leading region, YoY growth)
#     to populate the dashboard right-side panels when the page initially loads.
#     Uses dynamic table mapping based on session_id from external_db_sync_log.
#     """
#     data = request.json
#     if not data:
#         return jsonify({"error": "No data provided"}), 400
#         
#     session_id = data.get("session_id", "")
#     if not session_id:
#         return jsonify({"error": "Missing session_id"}), 400
# 
#     conn = None
#     cursor = None
#     
#     # Fallback default values
#     metrics_data = {
#         "metric_1": {"label": "Total Sales Revenue", "value": "N/A", "subtext": "No data available"},
#         "metric_2": {"label": "Top Performing Tyre", "value": "N/A", "subtext": "No data available"},
#         "metric_3": {"label": "Leading Region", "value": "N/A", "subtext": "No data available"},
#         "metric_4": {"label": "Year-over-Year Growth", "value": "N/A", "subtext": "No data available"}
#     }
# 
#     try:
#         conn = get_db_connection()
#         if not conn:
#             return jsonify({"error": "Failed to connect to database."}), 500
#             
#         cursor = conn.cursor(dictionary=True)
# 
#         # 1. Look up the dynamic table name and database from external_db_sync_log
#         cursor.execute("""
#             SELECT new_user_db, table_name 
#             FROM external_db_sync_log 
#             WHERE session_id=%s 
#               AND new_user_db IS NOT NULL 
#               AND new_user_db != ''
#               AND table_name IS NOT NULL
#             ORDER BY id DESC LIMIT 1
#         """, (session_id,))
#         sync_row = cursor.fetchone()
# 
#         if not sync_row:
#             print(f"[Default Metrics] No dynamic table found for session {session_id}")
#             return jsonify({"status": "success", "data": metrics_data}), 200
# 
#         user_db = sync_row["new_user_db"]
#         tbl_name = sync_row["table_name"]
#         
#         # Build the dynamic fully qualified table name `db`.`table`
#         table_name = f"`{user_db}`.`{tbl_name}`"
#         
#         # Fetch all synced tables for this session to dynamically inspect schemas
#         # We query the main database (config.MYSQL_CONFIG['database']) before switching to user_db
#         cursor.execute(f"""
#             SELECT DISTINCT table_name 
#             FROM `{config.MYSQL_CONFIG['database']}`.`external_db_sync_log` 
#             WHERE session_id = %s 
#               AND new_user_db = %s
#               AND table_name IS NOT NULL
#         """, (session_id, user_db))
#         session_tables = [r["table_name"] for r in cursor.fetchall()]
# 
#         # Switch to the user's database just to be safe, though fully qualified name works
#         cursor.execute(f"USE `{user_db}`")
# 
#         table_columns = {}
#         for tbl in session_tables:
#             try:
#                 cursor.execute(f"DESCRIBE `{tbl}`")
#                 cols = cursor.fetchall()
#                 table_columns[tbl] = {col["Field"].lower(): col["Field"] for col in cols}
#             except Exception as e:
#                 print(f"[Default Metrics] Describe table {tbl} failed: {e}")
# 
#         # Find the table that contains invoice_value
#         sales_table = None
#         for tbl, cols in table_columns.items():
#             if (
#                 "invoice_value" in cols
#                 or "invoice_value_inr" in cols
#                 or "taxable_value" in cols
#                 or "taxable_value_inr" in cols
#             ):
#                 sales_table = tbl
#                 break
# 
#         # Fallback to tbl_name if no table with invoice_value is found
#         if not sales_table:
#             sales_table = tbl_name
# 
#         sales_cols = table_columns.get(sales_table, {})
# 
#         if "invoice_value" in sales_cols:
#             real_revenue_col = sales_cols["invoice_value"]
#             has_revenue = True
#         elif "invoice_value_inr" in sales_cols:
#             real_revenue_col = sales_cols["invoice_value_inr"]
#             has_revenue = True
#         elif "taxable_value" in sales_cols:
#             real_revenue_col = sales_cols["taxable_value"]
#             has_revenue = True
#         elif "taxable_value_inr" in sales_cols:
#             real_revenue_col = sales_cols["taxable_value_inr"]
#             has_revenue = True
#         else:
#             has_revenue = False
# 
#         if has_revenue:
#             revenue_expr = f"CAST(REPLACE(TRIM(`{real_revenue_col}`), ',', '') AS DECIMAL(18,2))"
#             # For JOIN queries where the sales table has alias 's'
#             join_revenue_expr = f"CAST(REPLACE(TRIM(s.`{real_revenue_col}`), ',', '') AS DECIMAL(18,2))"
#         else:
#             revenue_expr = "0.0"
#             join_revenue_expr = "0.0"
# 
#         # 1. Total Sales Revenue
#         total_revenue = 0.0
#         if has_revenue:
#             try:
#                 cursor.execute(f"SELECT SUM({revenue_expr}) AS total_sales_revenue FROM `{sales_table}`")
#                 total_revenue = cursor.fetchone()["total_sales_revenue"] or 0
#             except Exception as rev_err:
#                 print(f"[Default Metrics] Total revenue query failed: {rev_err}")
# 
#         # 2. Top Performing Tyre
#         top_tyre = "N/A"
#         if has_revenue:
#             if "vehicle_type" in sales_cols:
#                 real_tyre_col = sales_cols["vehicle_type"]
#                 try:
#                     cursor.execute(f"""
#                         SELECT
#                             `{real_tyre_col}` AS vehicle_type,
#                             ROUND(SUM({revenue_expr}), 2) AS revenue
#                         FROM `{sales_table}`
#                         WHERE `{real_tyre_col}` IS NOT NULL
#                           AND `{real_tyre_col}` <> ''
#                         GROUP BY `{real_tyre_col}`
#                         ORDER BY revenue DESC
#                         LIMIT 1
#                     """)
#                     row = cursor.fetchone()
#                     if row:
#                         top_tyre = row["vehicle_type"]
#                 except Exception as tyre_err:
#                     print(f"[Default Metrics] Top tyre query failed: {tyre_err}")
#             else:
#                 sku_table = None
#                 tyre_table = None
#                 for tbl, cols in table_columns.items():
#                     if "matnr" in cols and "tyre_type" in cols:
#                         sku_table = tbl
#                     if "tyre_type_code" in cols and "tyre_type_name" in cols:
#                         tyre_table = tbl
# 
#                 if sku_table and tyre_table:
#                     sales_material = sales_cols["material"]
#                     sku_material = table_columns[sku_table]["matnr"]
#                     sku_tyre = table_columns[sku_table]["tyre_type"]
#                     tyre_code = table_columns[tyre_table]["tyre_type_code"]
#                     tyre_name = table_columns[tyre_table]["tyre_type_name"]
#                     try:
#                         cursor.execute(f"""
#                         SELECT
#                             t.`{tyre_name}` AS vehicle_type,
#                             ROUND(SUM({join_revenue_expr}),2) revenue
#                         FROM `{sales_table}` s
#                         JOIN `{sku_table}` k
#                             ON s.`{sales_material}` = k.`{sku_material}`
#                         JOIN `{tyre_table}` t
#                             ON k.`{sku_tyre}` = t.`{tyre_code}`
#                         GROUP BY t.`{tyre_name}`
#                         ORDER BY revenue DESC
#                         LIMIT 1
#                         """)
#                         row = cursor.fetchone()
#                         if row:
#                             top_tyre = row["vehicle_type"]
#                     except Exception as tyre_err:
#                         print(f"[Default Metrics] Joined top tyre query failed: {tyre_err}")
# 
#         # 3. Leading Region
#         leading_region = "N/A"
#         if has_revenue:
#             if "region" in sales_cols:
#                 real_region_col = sales_cols["region"]
#                 try:
#                     cursor.execute(f"""
#                         SELECT
#                             `{real_region_col}` AS region,
#                             ROUND(SUM({revenue_expr}), 2) AS revenue
#                         FROM `{sales_table}`
#                         WHERE `{real_region_col}` IS NOT NULL
#                           AND `{real_region_col}` <> ''
#                         GROUP BY `{real_region_col}`
#                         ORDER BY revenue DESC
#                         LIMIT 1
#                     """)
#                     row = cursor.fetchone()
#                     if row:
#                         leading_region = row["region"]
#                 except Exception as reg_err:
#                     print(f"[Default Metrics] Leading region query failed: {reg_err}")
#             else:
#                 customer_table = None
#                 territory_table = None
#                 region_table = None
#                 for tbl, cols in table_columns.items():
#                     if "kunnr" in cols and "territory" in cols:
#                         customer_table = tbl
#                     elif "territory_code" in cols and "region_code" in cols:
#                         territory_table = tbl
#                     elif "region" in cols and "region_name" in cols:
#                         region_table = tbl
# 
#                 if customer_table and territory_table and region_table:
#                     sales_customer = sales_cols["customer"]
#                     cust_id = table_columns[customer_table]["kunnr"]
#                     cust_territory = table_columns[customer_table]["territory"]
#                     terr_code = table_columns[territory_table]["territory_code"]
#                     terr_region = table_columns[territory_table]["region_code"]
#                     region_code = table_columns[region_table]["region"]
#                     region_name = table_columns[region_table]["region_name"]
#                     try:
#                         cursor.execute(f"""
#                         SELECT
#                             r.`{region_name}` AS region_name,
#                             ROUND(SUM({join_revenue_expr}),2) revenue
#                         FROM `{sales_table}` s
#                         JOIN `{customer_table}` c
#                             ON s.`{sales_customer}` = c.`{cust_id}`
#                         JOIN `{territory_table}` t
#                             ON c.`{cust_territory}` = t.`{terr_code}`
#                         JOIN `{region_table}` r
#                             ON t.`{terr_region}` = r.`{region_code}`
#                         GROUP BY r.`{region_name}`
#                         ORDER BY revenue DESC
#                         LIMIT 1
#                         """)
#                         row = cursor.fetchone()
#                         if row:
#                             leading_region = row["region_name"]
#                     except Exception as reg_err:
#                         print(f"[Default Metrics] Joined region query failed: {reg_err}")
# 
#         # 4. YoY Growth
#         current_year = 0.0
#         previous_year = 0.0
#         yoy = 0.0
#         real_date_col = None
# 
#         if "invoice_date" in sales_cols:
#             real_date_col = sales_cols["invoice_date"]
#         elif "billing__doc_date" in sales_cols:
#             real_date_col = sales_cols["billing__doc_date"]
# 
#         if has_revenue and real_date_col:
#             try:
#                 # Detect column type to decide date parsing strategy
#                 cursor.execute(f"SHOW COLUMNS FROM `{sales_table}` LIKE %s", (real_date_col,))
#                 col_info = cursor.fetchone()
#                 col_type = col_info["Type"].lower() if col_info else "text"
# 
#                 # If column is already date/datetime, use YEAR() directly
#                 # If it's text/varchar, parse with STR_TO_DATE
#                 if "date" in col_type or "timestamp" in col_type:
#                     year_expr = f"YEAR(`{real_date_col}`)"
#                     date_filter = f"`{real_date_col}` IS NOT NULL"
#                 else:
#                     year_expr = f"YEAR(STR_TO_DATE(`{real_date_col}`, '%d-%m-%Y'))"
#                     date_filter = f"`{real_date_col}` IS NOT NULL AND `{real_date_col}` != ''"
# 
#                 # Current Year Revenue
#                 cursor.execute(f"""
#                     SELECT ROUND(SUM({revenue_expr}), 2) AS revenue
#                     FROM `{sales_table}`
#                     WHERE {date_filter}
#                       AND {year_expr} = YEAR(CURDATE())
#                 """)
#                 curr_row = cursor.fetchone()
#                 current_year = float(curr_row["revenue"] or 0) if curr_row else 0.0
# 
#                 # Previous Year Revenue
#                 cursor.execute(f"""
#                     SELECT ROUND(SUM({revenue_expr}), 2) AS revenue
#                     FROM `{sales_table}`
#                     WHERE {date_filter}
#                       AND {year_expr} = YEAR(CURDATE()) - 1
#                 """)
#                 prev_row = cursor.fetchone()
#                 previous_year = float(prev_row["revenue"] or 0) if prev_row else 0.0
# 
#                 if previous_year > 0:
#                     yoy = round(((current_year - previous_year) / previous_year) * 100, 2)
#             except Exception as yoy_err:
#                 print(f"[Default Metrics] YoY query failed: {yoy_err}")
# 
#         # Format total revenue smartly (Cr or Lacs)
#         formatted_revenue = f"₹{float(total_revenue):,.2f}"
#         if total_revenue >= 10000000:
#             formatted_revenue = f"₹{(total_revenue / 10000000):.2f} Cr"
#         elif total_revenue >= 100000:
#             formatted_revenue = f"₹{(total_revenue / 100000):.2f} Lac"
# 
#         # Format output as dynamic metrics for frontend
#         metrics_data = {
#             "metric_1": {
#                 "label": "Total Sales Revenue", 
#                 "value": formatted_revenue, 
#                 "subtext": "Lifetime revenue"
#             },
#             "metric_2": {
#                 "label": "Top Performing Tyre", 
#                 "value": str(top_tyre), 
#                 "subtext": "Highest revenue generator"
#             },
#             "metric_3": {
#                 "label": "Leading Region", 
#                 "value": str(leading_region), 
#                 "subtext": "Most profitable territory"
#             },
#             "metric_4": {
#                 "label": "Year-over-Year Growth", 
#                 "value": f"{yoy}%", 
#                 "subtext": "Compared to last year"
#             }
#         }
# 
#         return jsonify({"status": "success", "data": metrics_data}), 200
# 
#     except Exception as exc:
#         print(f"[Default Metrics] Database query failed: {exc}")
#         return jsonify({
#             "status": "error",
#             "message": "Database query failed.",
#             "details": str(exc)
#         }), 500
# 
#     finally:
#         if cursor:
#             cursor.close()
#         if conn and conn.is_connected():
#             conn.close()


import json
from flask import request, jsonify

def get_actual_column_name(cursor, table_name, expected_name):
    try:
        cursor.execute(f"SHOW COLUMNS FROM {table_name}")
        columns = [row['Field'] for row in cursor.fetchall()]
        
        candidates = expected_name if isinstance(expected_name, (list, tuple)) else [expected_name]
        
        for cand in candidates:
            # 1. Exact match
            for col in columns:
                if col == cand:
                    return f"`{col}`"
                    
            # 2. Case insensitive match
            for col in columns:
                if col.lower() == cand.lower():
                    return f"`{col}`"
                    
            # 3. Fuzzy match
            target = cand.lower().replace('_', '').replace(' ', '')
            for col in columns:
                if col.lower().replace('_', '').replace(' ', '') == target:
                    return f"`{col}`"
                
    except Exception as e:
        print(f"Error fetching columns for {table_name}: {e}")
        
    return None

def check_table_columns(cursor, table_name, required_columns):
    found_cols = {}
    for col in required_columns:
        actual_col = get_actual_column_name(cursor, table_name, col)
        if not actual_col:
            return None
        found_cols[col] = actual_col
    return found_cols

def get_best_table_for_session(cursor, session_id, required_columns):
    """Finds a table that contains ALL required columns. 
       First checks tables synced in this session, then falls back to any table in the user's database."""
    
    # Get the user_db for this session
    cursor.execute("""
        SELECT new_user_db 
        FROM external_db_sync_log 
        WHERE session_id=%s 
          AND new_user_db IS NOT NULL 
          AND new_user_db != ''
        ORDER BY id DESC LIMIT 1
    """, (session_id,))
    row = cursor.fetchone()
    if not row:
        return None, None, {}
        
    user_db = row["new_user_db"]
    
    # 1. Check tables synced in this session
    cursor.execute("""
        SELECT table_name 
        FROM external_db_sync_log 
        WHERE session_id=%s AND new_user_db=%s AND table_name IS NOT NULL
        ORDER BY id DESC
    """, (session_id, user_db))
    
    synced_tables = [r["table_name"] for r in cursor.fetchall()]
    
    for tbl_name in synced_tables:
        table_name = f"`{user_db}`.`{tbl_name}`"
        found_cols = check_table_columns(cursor, table_name, required_columns)
        if found_cols:
            return table_name, user_db, found_cols
            
    # 2. Fallback: Check ALL tables in the user_db
    try:
        cursor.execute(f"SHOW TABLES FROM `{user_db}`")
        all_tables = [list(r.values())[0] for r in cursor.fetchall()]
        
        for tbl_name in all_tables:
            if tbl_name in synced_tables:
                continue # already checked
            table_name = f"`{user_db}`.`{tbl_name}`"
            found_cols = check_table_columns(cursor, table_name, required_columns)
            if found_cols:
                return table_name, user_db, found_cols
    except Exception as e:
        print(f"Error scanning all tables in {user_db}: {e}")
            
    return None, None, {}

# tyre_sales_data_controller

def get_query_context_for_session(cursor, session_id, required_metrics, optional_dims):
    # required_metrics and optional_dims are dictionaries: { "key_name": ["opt1", "opt2", ...] }
    cursor.execute("""
        SELECT DISTINCT new_user_db, table_name 
        FROM external_db_sync_log 
        WHERE session_id=%s 
          AND new_user_db IS NOT NULL 
          AND table_name IS NOT NULL
    """, (session_id,))
    rows = cursor.fetchall()
    
    # Fallback to most recent synced db if session not found
    if not rows:
        cursor.execute("""
            SELECT DISTINCT new_user_db, table_name 
            FROM external_db_sync_log 
            WHERE new_user_db IS NOT NULL AND new_user_db != '' AND table_name IS NOT NULL
            ORDER BY id DESC LIMIT 10
        """)
        rows = cursor.fetchall()

    if not rows:
        return None, None, {}

    user_db = rows[0]["new_user_db"]
    synced_tables = [r["table_name"] for r in rows]
    
    # Also fetch all tables in user_db so we don't miss any synced SAP views/tables
    try:
        cursor.execute(f"SHOW TABLES FROM `{user_db}`")
        db_tables = [list(r.values())[0] for r in cursor.fetchall()]
        all_tables = list(dict.fromkeys(synced_tables + db_tables))
    except Exception:
        all_tables = synced_tables

    table_columns = {}
    for tbl in all_tables:
        try:
            cursor.execute(f"DESCRIBE `{user_db}`.`{tbl}`")
            cols = cursor.fetchall()
            table_columns[tbl] = {c["Field"].lower().replace(' ', '').replace('_', ''): c["Field"] for c in cols}
        except Exception:
            pass

    def check_match(cols_dict, opts_list):
        if not cols_dict:
            return None
        for opt in opts_list:
            clean_opt = opt.lower().replace(' ', '').replace('_', '')
            if clean_opt in cols_dict:
                return cols_dict[clean_opt]
        return None

    def find_tbl(candidates):
        for cand in candidates:
            clean_cand = cand.lower().replace('_', '').replace('-', '')
            for tbl in table_columns.keys():
                clean_tbl = tbl.lower().replace('_', '').replace('-', '')
                if clean_cand in clean_tbl:
                    return tbl
        return None

    # Identify tables (SAP Views & Legacy Tables)
    curr_sales_tbl = find_tbl(["zpvfsdcurrentsales", "currentsales", "current_sales"])
    hist_sales_tbl = find_tbl(["zpvfsdsaleshistory", "saleshistory", "sales_history"])
    sales_data_tbl = find_tbl(["salesdata", "sales_data"])
    cust_tbl = find_tbl(["zivfcustomermaster", "customermaster", "customer"])
    terr_tbl = find_tbl(["zivfterritorymaster", "territorymaster", "territory"])
    reg_tbl = find_tbl(["zivfregionmaster", "regionmaster", "region"])
    zone_tbl = find_tbl(["zivfzonemaster", "zonemaster", "zone"])
    sku_tbl = find_tbl(["zivrskumaster", "skumaster", "materialmaster", "material", "sku"])
    cat_tbl = find_tbl(["zivfcategorymaster", "categorymaster", "category"])
    tyre_tbl = find_tbl(["tyretypemaster", "tyretype"])

    # Determine fact table / subquery
    fact_from = None
    fact_cols = {}

    canc_tbl = find_tbl(["zpvfsdcancelledsalesinvoice", "cancelledsalesinvoice", "cancelled_sales_invoice", "cancelled"])
    can_filter = f"LEFT JOIN `{user_db}`.`{canc_tbl}` can ON s.invoice_number = can.invoice_number AND s.plant = can.plant AND s.fkart = can.fkart AND (can.distribution_channel = 10 OR can.distribution_channel = '10')" if canc_tbl else ""
    can_null = "AND can.invoice_number IS NULL" if canc_tbl else ""

    if curr_sales_tbl and hist_sales_tbl:
        fact_from = f"(SELECT s.* FROM (SELECT * FROM `{user_db}`.`{curr_sales_tbl}` WHERE (indicator_cancel IS NULL OR indicator_cancel NOT IN ('X', 'Y', '1')) AND (distribution_channel = 10 OR distribution_channel = '10') UNION ALL SELECT * FROM `{user_db}`.`{hist_sales_tbl}` WHERE (indicator_cancel IS NULL OR indicator_cancel NOT IN ('X', 'Y', '1')) AND (distribution_channel = 10 OR distribution_channel = '10')) s {can_filter} WHERE 1=1 {can_null}) s"
        fact_cols = table_columns.get(curr_sales_tbl) or table_columns.get(hist_sales_tbl) or {}
    elif curr_sales_tbl:
        fact_from = f"(SELECT s.* FROM `{user_db}`.`{curr_sales_tbl}` s {can_filter} WHERE (s.indicator_cancel IS NULL OR s.indicator_cancel NOT IN ('X', 'Y', '1')) AND (s.distribution_channel = 10 OR s.distribution_channel = '10') {can_null}) s"
        fact_cols = table_columns.get(curr_sales_tbl, {})
    elif hist_sales_tbl:
        fact_from = f"(SELECT s.* FROM `{user_db}`.`{hist_sales_tbl}` s {can_filter} WHERE (s.indicator_cancel IS NULL OR s.indicator_cancel NOT IN ('X', 'Y', '1')) AND (s.distribution_channel = 10 OR s.distribution_channel = '10') {can_null}) s"
        fact_cols = table_columns.get(hist_sales_tbl, {})
    elif sales_data_tbl:
        fact_from = f"`{user_db}`.`{sales_data_tbl}` s"
        fact_cols = table_columns.get(sales_data_tbl, {})
    else:
        # Fallback to any table matching first required metric
        req_keys = list(required_metrics.keys())
        first_req = req_keys[0] if req_keys else None
        found_fact = None
        if first_req:
            for tbl, cols in table_columns.items():
                if check_match(cols, required_metrics[first_req]):
                    found_fact = tbl
                    if any("invoice" in k for k in cols.keys()):
                        break
        if not found_fact and all_tables:
            found_fact = all_tables[0]
        if found_fact:
            fact_from = f"`{user_db}`.`{found_fact}` s"
            fact_cols = table_columns.get(found_fact, {})

    if not fact_from or not fact_cols:
        return None, None, {}

    # Build Joins
    joins = []

    # 1. Customer Master `cm`
    if cust_tbl:
        s_cust = check_match(fact_cols, ["dealercode", "dealer_code", "customer", "kunnr"])
        c_cust = check_match(table_columns[cust_tbl], ["kunnr", "dealercode", "customer"])
        if s_cust and c_cust:
            joins.append(f"LEFT JOIN `{user_db}`.`{cust_tbl}` cm ON s.`{s_cust}` = cm.`{c_cust}`")

    # 2. Territory Master `tm`
    if terr_tbl:
        s_plant = check_match(fact_cols, ["plant", "werks", "vwerk"])
        t_plant = check_match(table_columns[terr_tbl], ["werks", "plant"])
        if s_plant and t_plant:
            joins.append(f"LEFT JOIN `{user_db}`.`{terr_tbl}` tm ON s.`{s_plant}` = tm.`{t_plant}`")
        elif cust_tbl:
            c_terr = check_match(table_columns[cust_tbl], ["bzirk", "territory", "territory_code"])
            t_terr = check_match(table_columns[terr_tbl], ["bzirk", "territory_code", "territory"])
            if c_terr and t_terr:
                joins.append(f"LEFT JOIN `{user_db}`.`{terr_tbl}` tm ON cm.`{c_terr}` = tm.`{t_terr}`")

    # 3. Region Master `rm`
    if reg_tbl:
        if terr_tbl and any("tm" in j for j in joins):
            t_reg = check_match(table_columns[terr_tbl], ["regio", "region_code", "region"])
            r_reg = check_match(table_columns[reg_tbl], ["region_code", "region", "regio"])
            if t_reg and r_reg:
                joins.append(f"LEFT JOIN `{user_db}`.`{reg_tbl}` rm ON tm.`{t_reg}` = rm.`{r_reg}`")
        elif cust_tbl and any("cm" in j for j in joins):
            c_reg = check_match(table_columns[cust_tbl], ["regio", "region_code", "region"])
            r_reg = check_match(table_columns[reg_tbl], ["region_code", "region", "regio"])
            if c_reg and r_reg:
                joins.append(f"LEFT JOIN `{user_db}`.`{reg_tbl}` rm ON cm.`{c_reg}` = rm.`{r_reg}`")

    # 4. Zone Master `zm`
    if zone_tbl:
        if terr_tbl and any("tm" in j for j in joins):
            t_zone = check_match(table_columns[terr_tbl], ["p_zone", "zone_code", "zone"])
            z_zone = check_match(table_columns[zone_tbl], ["p_zone", "zone_code", "zone"])
            if t_zone and z_zone:
                joins.append(f"LEFT JOIN `{user_db}`.`{zone_tbl}` zm ON tm.`{t_zone}` = zm.`{z_zone}`")
        elif reg_tbl and any("rm" in j for j in joins):
            r_zone = check_match(table_columns[reg_tbl], ["zone_code", "zone", "p_zone"])
            z_zone = check_match(table_columns[zone_tbl], ["p_zone", "zone_code", "zone"])
            if r_zone and z_zone:
                joins.append(f"LEFT JOIN `{user_db}`.`{zone_tbl}` zm ON rm.`{r_zone}` = zm.`{z_zone}`")
        elif cust_tbl and any("cm" in j for j in joins):
            c_zone = check_match(table_columns[cust_tbl], ["p_zone", "zone_code", "zone"])
            z_zone = check_match(table_columns[zone_tbl], ["p_zone", "zone_code", "zone"])
            if c_zone and z_zone:
                joins.append(f"LEFT JOIN `{user_db}`.`{zone_tbl}` zm ON cm.`{c_zone}` = zm.`{z_zone}`")

    # 5. SKU Master `sm`
    if sku_tbl:
        s_mat = check_match(fact_cols, ["sku", "material", "matnr"])
        sm_mat = check_match(table_columns[sku_tbl], ["matnr", "sku", "material"])
        if s_mat and sm_mat:
            joins.append(f"LEFT JOIN `{user_db}`.`{sku_tbl}` sm ON s.`{s_mat}` = sm.`{sm_mat}`")

    # 6. Category Master `catm`
    if cat_tbl and sku_tbl and any("sm" in j for j in joins):
        sm_cat = check_match(table_columns[sku_tbl], ["cat_code", "category", "catg", "prd_cat"])
        catm_cat = check_match(table_columns[cat_tbl], ["cat_code", "category_code", "category"])
        if sm_cat and catm_cat:
            joins.append(f"LEFT JOIN `{user_db}`.`{cat_tbl}` catm ON sm.`{sm_cat}` = catm.`{catm_cat}`")

    # 7. Tyre Type Master `ttm` (if legacy tyre_type_master exists)
    if tyre_tbl and sku_tbl and any("sm" in j for j in joins):
        sm_tyre = check_match(table_columns[sku_tbl], ["tyre_type", "tyretype"])
        ttm_tyre = check_match(table_columns[tyre_tbl], ["tyre_type_code", "tyre_type"])
        if sm_tyre and ttm_tyre:
            joins.append(f"LEFT JOIN `{user_db}`.`{tyre_tbl}` ttm ON sm.`{sm_tyre}` = ttm.`{ttm_tyre}`")

    # Column resolution order:
    alias_map = [
        ("s", fact_cols),
        ("ttm", table_columns.get(tyre_tbl, {}) if tyre_tbl and any("ttm" in j for j in joins) else {}),
        ("catm", table_columns.get(cat_tbl, {}) if cat_tbl and any("catm" in j for j in joins) else {}),
        ("zm", table_columns.get(zone_tbl, {}) if zone_tbl and any("zm" in j for j in joins) else {}),
        ("rm", table_columns.get(reg_tbl, {}) if reg_tbl and any("rm" in j for j in joins) else {}),
        ("tm", table_columns.get(terr_tbl, {}) if terr_tbl and any("tm" in j for j in joins) else {}),
        ("sm", table_columns.get(sku_tbl, {}) if sku_tbl and any("sm" in j for j in joins) else {}),
        ("cm", table_columns.get(cust_tbl, {}) if cust_tbl and any("cm" in j for j in joins) else {}),
    ]

    resolved_cols = {}
    all_metrics = {**required_metrics, **optional_dims}

    for req_key, opts in all_metrics.items():
        found_expr = None
        for alias, cols in alias_map:
            if not cols:
                continue
            matched = check_match(cols, opts)
            if matched:
                found_expr = f"{alias}.`{matched}`"
                break
        resolved_cols[req_key] = found_expr

    # If any required metric is missing, return None
    for req_key in required_metrics.keys():
        if not resolved_cols.get(req_key):
            return None, None, {}

    from_clause = fact_from
    if joins:
        unique_joins = list(dict.fromkeys(joins))
        from_clause += " " + " ".join(unique_joins)

    return from_clause, user_db, resolved_cols

def tyre_sales_data_controller(get_db_connection):
    data = request.json or {}
    session_id = data.get("session_id")
    user_id = data.get("user_id")
    question = data.get("question") # currently not used for SQL but required in payload

    def make_list(val):
        if val is None:
            return []
        if isinstance(val, list):
            return [v for v in val if v]
        return [val] if val else []

    selected_years = make_list(data.get("selected_years") or data.get("years") or data.get("year"))
    selected_customer_categories = make_list(data.get("selected_customer_categories") or data.get("customer_categories") or data.get("customer_category") or data.get("selected_customer_types") or data.get("customer_types") or data.get("customer_type"))
    selected_zones = make_list(data.get("selected_zones") or data.get("zones") or data.get("Zone") or data.get("zone"))
    selected_regions = make_list(data.get("selected_regions") or data.get("regions") or data.get("Region") or data.get("region"))
    selected_constructions = make_list(data.get("selected_constructions") or data.get("construction_types") or data.get("construction_type") or data.get("constructions") or data.get("construction"))

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = None
    cursor = None
    chart_data = []

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Failed to connect to database."}), 500
            
        cursor = conn.cursor(dictionary=True)

        def has_valid_filters(filters):
            return any(f and str(f).strip().lower() != "all" for f in filters)

        required_metrics = {
            "vehicle_type": ["cat_desc", "category_name", "category", "tyre_type_description", "tyre_type_desc", "tyre_type_name", "vehicle_type", "tyre_type", "maktx"],
            "invoice_value": ["invoice_value", "ndp_value", "taxable_value", "revenue", "Invoice_Value_INR"]
        }
        optional_dims = {}
        if has_valid_filters(selected_years):
            optional_dims["invoice_date"] = ["invoice_date", "date", "billing__doc_date"]
        if has_valid_filters(selected_customer_categories):
            optional_dims["customer_category"] = ["ch_type", "ktokd", "customer_type", "customer_category", "cust_type", "type"]
        if has_valid_filters(selected_zones):
            optional_dims["zone"] = ["name", "p_zone", "Zone", "zone"]
        if has_valid_filters(selected_regions):
            optional_dims["region"] = ["region_name", "region_code", "Region", "region", "regio"]
        if has_valid_filters(selected_constructions):
            optional_dims["construction_type"] = ["constuction", "construction_type", "construction"]
        from_clause, user_db, cols = get_query_context_for_session(cursor, session_id, required_metrics, optional_dims)

        if not from_clause:
            return jsonify({"status": "success", "data": chart_data, "message": "Required metrics (vehicle_type, invoice_value) not found."}), 200

        cursor.execute(f"USE `{user_db}`")
        
        actual_vehicle_type = cols["vehicle_type"]
        actual_invoice_value = cols["invoice_value"]

        actual_invoice_date = cols.get("invoice_date")
        actual_customer_category = cols.get("customer_category")
        actual_zone = cols.get("zone")
        actual_region = cols.get("region")
        actual_construction = cols.get("construction_type")

        revenue_expr = f"""
            CAST(
                REPLACE(TRIM({actual_invoice_value}), ',', '')
                AS DECIMAL(18,2)
            )
        """

        where_clauses = [f"{actual_vehicle_type} IS NOT NULL", f"{actual_vehicle_type} <> ''"]
        params = []

        # Years filter
        if actual_invoice_date and selected_years:
            valid_years = []
            for y in selected_years:
                if str(y).strip().lower() == "all":
                    continue
                try:
                    valid_years.append(int(y))
                except ValueError:
                    pass
            if valid_years:
                placeholders = ",".join(["%s"] * len(valid_years))
                where_clauses.append(f"YEAR({actual_invoice_date}) IN ({placeholders})")
                params.extend(valid_years)

        # Customer Category Filter
        if actual_customer_category and selected_customer_categories:
            valid_categories = [str(c).strip() for c in selected_customer_categories if c and str(c).strip().lower() != "all"]
            if valid_categories:
                placeholders = ",".join(["%s"] * len(valid_categories))
                where_clauses.append(f"{actual_customer_category} IN ({placeholders})")
                params.extend(valid_categories)

        # Zone Filter
        if actual_zone and selected_zones:
            valid_zones = [str(z).strip() for z in selected_zones if z and str(z).strip().lower() != "all"]
            if valid_zones:
                placeholders = ",".join(["%s"] * len(valid_zones))
                where_clauses.append(f"{actual_zone} IN ({placeholders})")
                params.extend(valid_zones)

        # Region Filter
        if actual_region and selected_regions:
            valid_regions = [str(r).strip() for r in selected_regions if r and str(r).strip().lower() != "all"]
            if valid_regions:
                placeholders = ",".join(["%s"] * len(valid_regions))
                where_clauses.append(f"{actual_region} IN ({placeholders})")
                params.extend(valid_regions)

        # Construction Filter
        if actual_construction and selected_constructions:
            valid_constructions = [str(c).strip() for c in selected_constructions if c and str(c).strip().lower() != "all"]
            if valid_constructions:
                placeholders = ",".join(["%s"] * len(valid_constructions))
                where_clauses.append(f"{actual_construction} IN ({placeholders})")
                params.extend(valid_constructions)

        where_sql = " AND ".join(where_clauses)

        # dummyTyreData
        try:
            query = f"""
                SELECT
                    {actual_vehicle_type} as category,
                    ROUND(SUM({revenue_expr}), 2) AS sales_value
                FROM {from_clause}
                WHERE {where_sql}
                GROUP BY {actual_vehicle_type}
                ORDER BY sales_value DESC
                LIMIT 10
            """
            cursor.execute(query, tuple(params))
            chart_data = cursor.fetchall()
            error_msg = ""
        except Exception as e:
            print(f"Skipping tyre_sales_data due to error: {e}")
            error_msg = str(e)
            
        visualizations = []
        if chart_data:
            visualizations.append({
                "data": chart_data,
                "seriesKey": "",
                "title": "Top 10 Tyre Types by Sales",
                "type": "horizontal_bar_chart",
                "xKey": "sales_value",
                "yKey": "vehicle_type"
            })
            
        return jsonify({
            "status": "success" if not error_msg else "error", 
            "visualizations": visualizations,
            "message": "Data retrieved successfully. Missing metrics means the column doesn't exist in the current table." if not chart_data and not error_msg else "",
            "sql_error": error_msg
        }), 200 if not error_msg else 400

    except Exception as exc:
        print(f"[Tyre Sales Data] Database query failed: {exc}")
        return jsonify({
            "status": "error",
            "message": "Database query failed.",
            "details": str(exc)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


#filter for sales by zone chart

# def dashboard_filters_controller(get_db_connection):
#     session_id = request.args.get("session_id")
#     if not session_id:
#         return jsonify({"error": "Missing session_id"}), 400

#     conn = None
#     cursor = None
    
#     # Initialize empty dynamic filters
#     filters_data = {
#         "categories": [],
#         "constructions": [],
#         "tyreTypes": []
#     }

#     try:
#         conn = get_db_connection()
#         if not conn:
#             return jsonify({"status": "success", **filters_data}), 200
            
#         cursor = conn.cursor(dictionary=True)
        
#         # Find user_db for session
#         cursor.execute("""
#             SELECT new_user_db 
#             FROM external_db_sync_log 
#             WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
#             ORDER BY id DESC LIMIT 1
#         """, (session_id,))
#         row = cursor.fetchone()
        
#         # Fallback: if session not found, use most recent synced db
#         if not row:
#             cursor.execute("""
#                 SELECT new_user_db 
#                 FROM external_db_sync_log 
#                 WHERE new_user_db IS NOT NULL AND new_user_db != ''
#                 ORDER BY id DESC LIMIT 1
#             """)
#             row = cursor.fetchone()
        
#         table_name = None
#         actual_cat = None
#         actual_const = None
#         actual_tyre = None

#         if row:
#             user_db = row["new_user_db"]
#             cursor.execute(f"USE `{user_db}`")
#             cursor.execute("SHOW TABLES")
#             tables = [list(r.values())[0] for r in cursor.fetchall()]
            
#             # Find the first existing table that has at least one relevant column
#             for tbl in tables:
#                 t_name = f"`{user_db}`.`{tbl}`"
#                 cat = get_actual_column_name(cursor, t_name, "product_category") or \
#                       get_actual_column_name(cursor, t_name, "category") or \
#                       get_actual_column_name(cursor, t_name, "product_type")
                      
#                 const = get_actual_column_name(cursor, t_name, "construction_type") or \
#                         get_actual_column_name(cursor, t_name, "construction")
                        
#                 tyre = get_actual_column_name(cursor, t_name, "vehicle_type")
                
#                 if cat or const or tyre:
#                     # Check if table has data
#                     cursor.execute(f"SELECT 1 FROM {t_name} LIMIT 1")
#                     if cursor.fetchone():
#                         table_name = t_name
#                         actual_cat = cat
#                         actual_const = const
#                         actual_tyre = tyre
#                         break

#             if actual_cat:
#                 cursor.execute(f"SELECT DISTINCT {actual_cat} as val FROM {table_name} WHERE {actual_cat} IS NOT NULL AND {actual_cat} != ''")
#                 res = [r["val"] for r in cursor.fetchall() if r["val"]]
#                 if res: filters_data["categories"] = res
                
#             if actual_const:
#                 cursor.execute(f"SELECT DISTINCT {actual_const} as val FROM {table_name} WHERE {actual_const} IS NOT NULL AND {actual_const} != ''")
#                 res = [r["val"] for r in cursor.fetchall() if r["val"]]
#                 if res: filters_data["constructions"] = res
                
#             if actual_tyre:
#                 cursor.execute(f"SELECT DISTINCT {actual_tyre} as val FROM {table_name} WHERE {actual_tyre} IS NOT NULL AND {actual_tyre} != ''")
#                 res = [r["val"] for r in cursor.fetchall() if r["val"]]
#                 if res: filters_data["tyreTypes"] = res
                
#         # Debug info
#         debug_info = {
#             "table_found": table_name,
#             "actual_cat": actual_cat if table_name else None,
#             "actual_const": actual_const if table_name else None,
#             "actual_tyre": actual_tyre if table_name else None,
#         }
#         if table_name:
#             cursor.execute(f"SHOW COLUMNS FROM {table_name}")
#             debug_info["all_columns"] = [r['Field'] for r in cursor.fetchall()]

#         return jsonify({
#             "status": "success",
#             **filters_data
#         }), 200

#     except Exception as exc:
#         print(f"[Dashboard Filters] query failed: {exc}")
#         return jsonify({
#             "status": "success",
#             **filters_data
#         }), 200
#     finally:
#         if cursor:
#             cursor.close()
#         if conn and conn.is_connected():
#             conn.close()

#filter for sales by zone chart
def dashboard_filters_controller(get_db_connection):
    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = None
    cursor = None
    
    # Initialize empty dynamic filters
    filters_data = {
        "categories": [],
        "constructions": [],
        "tyreTypes": [],
        "years": [],
        "months": []
    }

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"status": "success", **filters_data}), 200
            
        try:
            cursor = conn.cursor(dictionary=True)
        except TypeError:
            cursor = conn.cursor()
        
        # Find user_db for session
        cursor.execute("""
            SELECT new_user_db 
            FROM external_db_sync_log 
            WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
            ORDER BY id DESC LIMIT 1
        """, (session_id,))
        row = cursor.fetchone()
        
        # Fallback: if session not found, use most recent synced db
        if not row:
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()

        if row:
            user_db = row["new_user_db"]
            cursor.execute(f"USE `{user_db}`")
            cursor.execute("SHOW TABLES")
            tables = [list(r.values())[0] for r in cursor.fetchall()]
            
            # 1. Find categories across all tables with { value: code, label: desc }
            for tbl in tables:
                tbl_low = tbl.lower()
                if "category" in tbl_low:
                    t_name = f"`{user_db}`.`{tbl}`"
                    code_col = get_actual_column_name(cursor, t_name, ["cat_code", "category_code", "code"])
                    desc_col = get_actual_column_name(cursor, t_name, ["cat_desc", "category_name", "category"])
                    if code_col and desc_col:
                        try:
                            cursor.execute(f"SELECT DISTINCT {code_col} as val_code, {desc_col} as val_label FROM {t_name} WHERE {desc_col} IS NOT NULL AND {desc_col} != '' ORDER BY val_label ASC")
                            res = [{"value": r["val_code"], "label": r["val_label"]} for r in cursor.fetchall() if r.get("val_label")]
                            if res:
                                filters_data["categories"] = res
                                break
                        except Exception as e:
                            print(f"Error fetching categories from {t_name}: {e}")

            if not filters_data["categories"]:
                for tbl in tables:
                    t_name = f"`{user_db}`.`{tbl}`"
                    cat = get_actual_column_name(cursor, t_name, ["cat_desc", "catg", "prd_cat", "product_category", "category", "product_type"])
                    if cat:
                        try:
                            cursor.execute(f"SELECT DISTINCT {cat} as val FROM {t_name} WHERE {cat} IS NOT NULL AND {cat} != '' ORDER BY val ASC")
                            res = [{"value": r["val"], "label": r["val"]} for r in cursor.fetchall() if r["val"]]
                            if res:
                                filters_data["categories"] = res
                                break
                        except Exception as e:
                            print(f"Error fetching categories from {t_name}: {e}")

            # 2. Find constructions across all tables with { value: code, label: desc }
            construction_labels = {
                1: "Bias",
                2: "Radial",
                3: "Tubeless Bias",
                4: "Tubeless Radial",
                5: "Radial (Tube Type)",
                6: "Radial (Tubeless)",
                7: "Solid / OTR"
            }
            for tbl in tables:
                t_name = f"`{user_db}`.`{tbl}`"
                const = get_actual_column_name(cursor, t_name, ["constuction", "construction_type", "construction"])
                if const:
                    try:
                        cursor.execute(f"SELECT DISTINCT {const} as val FROM {t_name} WHERE {const} IS NOT NULL AND {const} != '' ORDER BY val ASC")
                        res = []
                        for r in cursor.fetchall():
                            raw_val = r["val"]
                            try:
                                val_int = int(raw_val)
                                lbl = construction_labels.get(val_int, f"Type {raw_val}")
                            except (ValueError, TypeError):
                                lbl = str(raw_val)
                            res.append({"value": raw_val, "label": lbl})
                        if res:
                            filters_data["constructions"] = res
                            break
                    except Exception as e:
                        print(f"Error fetching constructions from {t_name}: {e}")

            # 3. Find tyreTypes across all tables with { value: code, label: desc }
            for tbl in tables:
                tbl_low = tbl.lower()
                if "category" in tbl_low:
                    t_name = f"`{user_db}`.`{tbl}`"
                    code_col = get_actual_column_name(cursor, t_name, ["cat_code", "category_code", "code"])
                    desc_col = get_actual_column_name(cursor, t_name, ["cat_desc", "category_name", "category"])
                    if desc_col:
                        try:
                            cursor.execute(f"SELECT DISTINCT {code_col or desc_col} as val_code, {desc_col} as val_label FROM {t_name} WHERE {desc_col} IS NOT NULL AND {desc_col} != '' ORDER BY val_label ASC")
                            res = [{"value": r["val_code"], "label": r["val_label"]} for r in cursor.fetchall() if r.get("val_label")]
                            if res:
                                filters_data["tyreTypes"] = res
                                break
                        except Exception as e:
                            print(f"Error fetching tyreTypes from categorymaster: {e}")

            if not filters_data["tyreTypes"]:
                for tbl in tables:
                    t_name = f"`{user_db}`.`{tbl}`"
                    tyre = get_actual_column_name(cursor, t_name, ["tyre_type", "vehicle_type", "tyre_type_name"])
                    if tyre:
                        try:
                            cursor.execute(f"SELECT DISTINCT {tyre} as val FROM {t_name} WHERE {tyre} IS NOT NULL AND {tyre} != '' ORDER BY val ASC")
                            res = [{"value": r["val"], "label": r["val"]} for r in cursor.fetchall() if r["val"]]
                            if res:
                                filters_data["tyreTypes"] = res
                                break
                        except Exception as e:
                            print(f"Error fetching tyreTypes from {t_name}: {e}")

            # Find years and months across actual sales tables (both CurrentSales and SalesHistory)
            all_years = set()
            month_map = {}
            for tbl in tables:
                tbl_lower = tbl.lower()
                # Exclude calendar/master/attribute/cancelled/target tables
                if any(k in tbl_lower for k in ["dayattribute", "master", "calendar", "attribute", "cancelled", "target", "budget"]):
                    continue
                if not any(k in tbl_lower for k in ["sales", "invoice"]):
                    continue

                t_name = f"`{user_db}`.`{tbl}`"
                date_col = get_actual_column_name(cursor, t_name, ["invoice_date", "date", "billing__doc_date"])
                if date_col:
                    try:
                        cursor.execute(f"SELECT DISTINCT YEAR({date_col}) as yr FROM {t_name} WHERE {date_col} IS NOT NULL ORDER BY yr ASC")
                        for r in cursor.fetchall():
                            if r["yr"] and 2000 <= int(r["yr"]) <= 2100:
                                all_years.add(int(r["yr"]))
                        
                        cursor.execute(f"SELECT DISTINCT MONTHNAME({date_col}) as m_name, MONTH({date_col}) as m_num FROM {t_name} WHERE {date_col} IS NOT NULL ORDER BY m_num ASC")
                        for r in cursor.fetchall():
                            if r["m_name"] and r["m_name"] not in month_map:
                                month_map[r["m_name"]] = r["m_num"]
                    except Exception as e:
                        print(f"Error fetching dates from {t_name}: {e}")
            
            if all_years:
                filters_data["years"] = sorted(list(all_years))
            if month_map:
                filters_data["months"] = [m[0] for m in sorted(month_map.items(), key=lambda x: x[1])]

        return jsonify({
            "status": "success",
            **filters_data
        }), 200

    except Exception as exc:
        print(f"[Dashboard Filters] query failed: {exc}")
        return jsonify({
            "status": "success",
            **filters_data
        }), 200
    finally:
        if cursor:
            cursor.close()
        if conn:
            try:
                if hasattr(conn, "is_connected"):
                    if conn.is_connected():
                        conn.close()
                else:
                    conn.close()
            except Exception:
                pass



def sales_by_zone_data_controller(get_db_connection):
    data = request.json or {}
    session_id = data.get("session_id")
    
    # Try different possible keys for product category just in case
    product_type = data.get("product_type") or data.get("category") or data.get("product_category")
    construction_type = data.get("construction_type") or data.get("construction")
    vehicle_type = data.get("vehicle_type") or data.get("tyre_type") or data.get("tyreType") or data.get("tyre_types")

    def make_list(val):
        if val is None:
            return []
        if isinstance(val, list):
            return [v for v in val if v]
        return [val] if val else []

    selected_years = make_list(data.get("selected_years") or data.get("years") or data.get("year"))
    selected_months = make_list(data.get("selected_months") or data.get("months") or data.get("month"))
    selected_zones = make_list(data.get("selected_zones") or data.get("zones") or data.get("zone") or data.get("Zone"))

    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = None
    cursor = None
    chart_data = []

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Failed to connect to database."}), 500
            
        cursor = conn.cursor(dictionary=True)

        def has_valid_filters(filters):
            return any(f and str(f).strip().lower() != "all" for f in filters)

        required_metrics = {
            "zone": ["name", "p_zone", "Zone", "zone"],
            "invoice_value": ["invoice_value", "ndp_value", "Invoice_Value", "taxable_value", "Invoice_Value_INR"]
        }
        optional_dims = {}
        if has_valid_filters(selected_years) or has_valid_filters(selected_months):
            optional_dims["invoice_date"] = ["invoice_date", "date", "billing__doc_date"]
        if product_type and str(product_type).lower() != 'all':
            optional_dims["customer_category"] = ["cat_code", "cat_desc", "category", "product_category", "catg", "prd_cat"]
        if vehicle_type and str(vehicle_type).lower() != 'all':
            optional_dims["vehicle_type"] = ["cat_code", "cat_desc", "tyre_type", "vehicle_type", "tyre_type_name", "maktx"]
        if construction_type and str(construction_type).lower() != 'all':
            optional_dims["construction_type"] = ["constuction", "CONSTRUCTION", "construction_type", "construction"]
        from_clause, user_db, cols = get_query_context_for_session(cursor, session_id, required_metrics, optional_dims)

        if not from_clause:
            return jsonify({"status": "success", "data": chart_data, "message": "Required metrics (zone, invoice_value) not found in any table."}), 200

        cursor.execute(f"USE `{user_db}`")
        
        actual_zone = cols["zone"]
        actual_invoice_value = cols["invoice_value"]

        revenue_expr = f"""
            CAST(
                REPLACE(TRIM({actual_invoice_value}), ',', '')
                AS DECIMAL(18,2)
            )
        """

        actual_invoice_date = cols.get("invoice_date")
        actual_cat = cols.get("customer_category")
        actual_const = cols.get("construction_type")
        actual_tyre = cols.get("vehicle_type")

        where_clauses = [f"{actual_zone} IS NOT NULL", f"{actual_zone} <> ''"]
        if "cm" in from_clause:
            where_clauses.append("(cm.`klabc` IS NULL OR UPPER(TRIM(cm.`klabc`)) <> 'X')")
        params = []

        if product_type and str(product_type).lower() != 'all' and actual_cat:
            if "catm" in from_clause:
                where_clauses.append(f"({actual_cat} = %s OR catm.`cat_desc` = %s OR catm.`cat_code` = %s)")
                params.extend([product_type, product_type, product_type])
            else:
                where_clauses.append(f"{actual_cat} = %s")
                params.append(product_type)
                
        if construction_type and str(construction_type).lower() != 'all' and actual_const:
            where_clauses.append(f"{actual_const} = %s")
            params.append(construction_type)

        if vehicle_type and str(vehicle_type).lower() != 'all' and actual_tyre:
            if "catm" in from_clause:
                where_clauses.append(f"({actual_tyre} = %s OR catm.`cat_desc` = %s OR catm.`cat_code` = %s)")
                params.extend([vehicle_type, vehicle_type, vehicle_type])
            else:
                where_clauses.append(f"{actual_tyre} = %s")
                params.append(vehicle_type)

        # Years filter
        if actual_invoice_date and selected_years:
            valid_years = []
            for y in selected_years:
                if str(y).strip().lower() == "all":
                    continue
                try:
                    valid_years.append(int(y))
                except ValueError:
                    pass
            if valid_years:
                placeholders = ",".join(["%s"] * len(valid_years))
                where_clauses.append(f"YEAR({actual_invoice_date}) IN ({placeholders})")
                params.extend(valid_years)

        # Months filter
        if actual_invoice_date and selected_months:
            valid_months = [str(m).strip() for m in selected_months if m and str(m).strip().lower() != "all"]
            if valid_months:
                placeholders = ",".join(["%s"] * len(valid_months))
                where_clauses.append(f"MONTHNAME({actual_invoice_date}) IN ({placeholders})")
                params.extend(valid_months)
                
        # Zones filter
        if actual_zone and selected_zones:
            valid_zones = [str(z).strip() for z in selected_zones if z and str(z).strip().lower() != "all"]
            if valid_zones:
                placeholders = ",".join(["%s"] * len(valid_zones))
                where_clauses.append(f"{actual_zone} IN ({placeholders})")
                params.extend(valid_zones)

        where_sql = " AND ".join(where_clauses)

        try:
            query = f"""
                SELECT
                    {actual_zone} as zone,
                    ROUND(SUM({revenue_expr}), 2) AS sales_value
                FROM {from_clause}
                WHERE {where_sql}
                GROUP BY {actual_zone}
                ORDER BY sales_value DESC
            """
            cursor.execute(query, tuple(params))
            results = cursor.fetchall()
            
            total_sales = sum(float(r['sales_value']) for r in results if r['sales_value'])
            
            zone_map = {
                'WZ': 'West Zone',
                'EZ': 'East Zone',
                'NZ': 'North Zone',
                'SZ': 'South Zone I',
                'TZ': 'South Zone II',
                'CZ': 'Central Zone',
                'NP': 'Nepal'
            }
            
            for r in results:
                raw_zone = r['zone'] or ''
                r['name'] = zone_map.get(raw_zone.upper(), raw_zone)
                r['value'] = float(r['sales_value']) if r['sales_value'] else 0.0
                if total_sales > 0:
                    r['percentage'] = round((r['value'] / total_sales) * 100, 1)
                else:
                    r['percentage'] = 0.0
                    
            chart_data = results
            error_msg = ""
        except Exception as e:
            print(f"Skipping sales_by_zone due to error: {e}")
            error_msg = str(e)
            
        visualizations = []
        if chart_data:
            visualizations.append({
                "data": chart_data,
                "seriesKey": "",
                "title": "Sales by Zone",
                "type": "pie_chart", 
                "xKey": "name",
                "yKey": "value"
            })
            
        return jsonify({
            "status": "success" if not error_msg else "error", 
            "visualizations": visualizations,
            "data": chart_data,
            "message": "Data retrieved successfully." if not error_msg else "",
            "sql_error": error_msg
        }), 200 if not error_msg else 400

    except Exception as exc:
        print(f"[Sales by Zone] Database query failed: {exc}")
        return jsonify({
            "status": "error",
            "message": "Database query failed.",
            "details": str(exc)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# year_wise_sales_comparison_controller



def year_wise_sales_comparison_controller(get_db_connection):
    """
    Fetches Year-wise Sales Comparison data grouped by month and year.
    Returns data in the format requested by the user:
    {
      "seriesKey": "year",
      "title": "Year-wise Sales Comparison",
      "type": "bar_chart",
      "xKey": "month",
      "yKey": "sales_value",
      "visualization": [
        { "month": "January",  "sales_value": 232010756.39, "year": "2026" }, ...
      ]
    }
    """
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    session_id = data.get("session_id", "")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    def make_list(val):
        if val is None:
            return []
        if isinstance(val, list):
            return [v for v in val if v]
        return [val] if val else []

    selected_years = make_list(data.get("selected_years") or data.get("years") or data.get("year"))
    selected_zones = make_list(data.get("selected_zones") or data.get("zones") or data.get("Zone") or data.get("zone"))
    selected_regions = make_list(data.get("selected_regions") or data.get("regions") or data.get("Region") or data.get("region"))
    selected_months = make_list(data.get("selected_months") or data.get("months") or data.get("Month") or data.get("month"))
    selected_customer_types = make_list(data.get("selected_customer_types") or data.get("customer_types") or data.get("customer_type"))

    conn = None
    cursor = None
    visualization_data = []

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Failed to connect to database."}), 500
            
        cursor = conn.cursor(dictionary=True)

        def has_valid_filters(filters):
            return any(f and str(f).strip().lower() != "all" for f in filters)

        required_metrics = {
            "invoice_value": ["invoice_value", "ndp_value", "Invoice_Value", "taxable_value", "Invoice_Value_INR"],
            "invoice_date": ["invoice_date", "date", "billing__doc_date"]
        }
        optional_dims = {}
        if has_valid_filters(selected_zones):
            optional_dims["zone"] = ["name", "p_zone", "Zone", "zone"]
        if has_valid_filters(selected_regions):
            optional_dims["region"] = ["region_name", "region_code", "Region", "region", "regio"]
        if has_valid_filters(selected_customer_types):
            optional_dims["customer_type"] = ["ch_type", "ktokd", "customer_type", "customer_category", "cust_type", "type"]

        from_clause, user_db, cols = get_query_context_for_session(cursor, session_id, required_metrics, optional_dims)

        if not from_clause:
            return jsonify({
                "seriesKey": "year",
                "title": "Year-wise Sales Comparison",
                "type": "bar_chart",
                "xKey": "month",
                "yKey": "sales_value",
                "visualization": []
            }), 200

        cursor.execute(f"USE `{user_db}`")

        actual_invoice_date_expr = cols["invoice_date"]
        actual_invoice_value_expr = cols["invoice_value"]
        actual_zone = cols.get("zone")
        actual_region = cols.get("region")
        actual_customer_type_expr = cols.get("customer_type")

        revenue_expr = f"""
            CAST(
                REPLACE(TRIM({actual_invoice_value_expr}), ',', '')
                AS DECIMAL(18,2)
            )
        """

        where_clauses = [f"{actual_invoice_date_expr} IS NOT NULL"]
        params = []

        # Years filter
        if selected_years:
            valid_years = []
            for y in selected_years:
                if str(y).strip().lower() == "all":
                    continue
                try:
                    valid_years.append(int(y))
                except ValueError:
                    pass
            if valid_years:
                placeholders = ",".join(["%s"] * len(valid_years))
                where_clauses.append(f"YEAR({actual_invoice_date_expr}) IN ({placeholders})")
                params.extend(valid_years)

        # Months filter
        if selected_months:
            valid_months = [str(m).strip() for m in selected_months if m and str(m).strip().lower() != "all"]
            if valid_months:
                placeholders = ",".join(["%s"] * len(valid_months))
                where_clauses.append(f"MONTHNAME({actual_invoice_date_expr}) IN ({placeholders})")
                params.extend(valid_months)

        # Zone Filter
        if actual_zone and selected_zones:
            valid_zones = [str(z).strip() for z in selected_zones if z and str(z).strip().lower() != "all"]
            if valid_zones:
                placeholders = ",".join(["%s"] * len(valid_zones))
                where_clauses.append(f"{actual_zone} IN ({placeholders})")
                params.extend(valid_zones)

        # Region Filter
        if actual_region and selected_regions:
            valid_regions = [str(r).strip() for r in selected_regions if r and str(r).strip().lower() != "all"]
            if valid_regions:
                placeholders = ",".join(["%s"] * len(valid_regions))
                where_clauses.append(f"{actual_region} IN ({placeholders})")
                params.extend(valid_regions)

        # Customer Type Filter
        # if actual_customer_type_expr and selected_customer_types:
        #     valid_types = [str(c).strip() for c in selected_customer_types if c and str(c).strip().lower() != "all"]
        #     if valid_types:
        #         placeholders = ",".join(["%s"] * len(valid_types))
        #         where_clauses.append(f"{actual_customer_type_expr} IN ({placeholders})")
        #         params.extend(valid_types)
        if actual_customer_type_expr and selected_customer_types:
            valid_types = [
                str(c).strip().upper()
                for c in selected_customer_types
                if c and str(c).strip().lower() != "all"
            ]

            if valid_types:
                placeholders = ",".join(["%s"] * len(valid_types))

                where_clauses.append(
                    f"UPPER({actual_customer_type_expr}) IN ({placeholders})"
                )
                params.extend(valid_types)

        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql

        query = f"""
            SELECT 
                MONTHNAME({actual_invoice_date_expr}) AS month_name,
                MONTH({actual_invoice_date_expr}) AS month_num,
                YEAR({actual_invoice_date_expr}) AS year,
                ROUND(SUM({revenue_expr}), 2) AS total_sales
            FROM {from_clause}
            {where_sql}
            GROUP BY YEAR({actual_invoice_date_expr}), MONTH({actual_invoice_date_expr}), MONTHNAME({actual_invoice_date_expr})
            ORDER BY year ASC, month_num ASC
        """
        
        # print("\n========== FINAL QUERY ==========")
        # print(query)

        # print("\n========== PARAMS ==========")
        # print(params)

        # print("\n========== FACT TABLE ==========")
        # print(table_name)

        # print("\n========== CUSTOMER TABLE ==========")
        # print(customer_tbl_name)

        # print("\n========== CUSTOMER TYPE ==========")
        # print(actual_customer_type_expr)

        cursor.execute(query, tuple(params))
        results = cursor.fetchall()

        for row in results:
            visualization_data.append({
                "month": row["month_name"],
                "sales_value": float(row["total_sales"] or 0),
                "year": str(row["year"])
            })

        return jsonify({
            "seriesKey": "year",
            "title": "Year-wise Sales Comparison",
            "type": "bar_chart",
            "xKey": "month",
            "yKey": "sales_value",
            "visualization": visualization_data
        }), 200

    except Exception as exc:
        print(f"[Year-wise Sales Comparison] Database query failed: {exc}")
        return jsonify({
            "status": "error",
            "message": "Database query failed.",
            "details": str(exc)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()



# available_years_controller



def available_years_controller(get_db_connection):
    """
    Fetches the distinct years, zones, regions, months, construction types, and customer types available in the database for the active session.
    Expects session_id as a GET query parameter.
    """
    session_id = request.args.get("session_id", "")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = None
    cursor = None
    years = []
    zones = []
    regions = []
    months = []
    customer_types = []
    construction_types = []

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Failed to connect to database."}), 500
            
        try:
            cursor = conn.cursor(dictionary=True)
        except TypeError:
            cursor = conn.cursor()

        # Look up the dynamic table name and database from external_db_sync_log
        cursor.execute("""
            SELECT new_user_db 
            FROM external_db_sync_log 
            WHERE session_id=%s 
              AND new_user_db IS NOT NULL 
              AND new_user_db != ''
            ORDER BY id DESC LIMIT 1
        """, (session_id,))
        sync_row = cursor.fetchone()

        if not sync_row:
            # Fallback: if session not found, use most recent synced db
            cursor.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """)
            sync_row = cursor.fetchone()

        if not sync_row:
            return jsonify({
                "status": "success",
                "years": [],
                "zones": [],
                "regions": [],
                "months": [],
                "customer_types": [],
                "construction_types": []
            }), 200

        user_db = sync_row["new_user_db"]
        
        cursor.execute(f"USE `{user_db}`")
        cursor.execute("SHOW TABLES")
        tables = [list(r.values())[0] for r in cursor.fetchall()]

        # 1. Fetch Years and Months across actual sales tables (CurrentSales & SalesHistory)
        all_years = set()
        month_map = {}
        for tbl in tables:
            tbl_lower = tbl.lower()
            # Exclude non-sales tables like dayattribute, calendar, master, attribute, cancelled, target
            if any(k in tbl_lower for k in ["dayattribute", "master", "calendar", "attribute", "cancelled", "target", "budget"]):
                continue
            if not any(k in tbl_lower for k in ["sales", "invoice"]):
                continue

            t_name = f"`{user_db}`.`{tbl}`"
            actual_invoice_date = get_actual_column_name(cursor, t_name, ["invoice_date", "date", "billing__doc_date"])
            if actual_invoice_date:
                try:
                    cursor.execute(f"SELECT 1 FROM {t_name} LIMIT 1")
                    if cursor.fetchone():
                        cursor.execute(f"""
                            SELECT DISTINCT YEAR({actual_invoice_date}) as yr 
                            FROM {t_name} 
                            WHERE {actual_invoice_date} IS NOT NULL 
                            ORDER BY yr ASC
                        """)
                        for r in cursor.fetchall():
                            if r["yr"] and 2000 <= int(r["yr"]) <= 2100:
                                all_years.add(int(r["yr"]))

                        cursor.execute(f"""
                            SELECT DISTINCT MONTHNAME({actual_invoice_date}) as m_name, MONTH({actual_invoice_date}) as m_num
                            FROM {t_name}
                            WHERE {actual_invoice_date} IS NOT NULL
                            ORDER BY m_num ASC
                        """)
                        for r in cursor.fetchall():
                            if r["m_name"] and r["m_name"] not in month_map:
                                month_map[r["m_name"]] = r["m_num"]
                except Exception as e:
                    print(f"Error fetching dates from {t_name}: {e}")
        if all_years:
            years = sorted(list(all_years))
        if month_map:
            months = [m[0] for m in sorted(month_map.items(), key=lambda x: x[1])]

        # 2. Fetch Zones (SAP ZoneMaster has NAME and P_ZONE, CustomerMaster has P_ZONE)
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_zone = get_actual_column_name(cursor, t_name, ["name", "p_zone", "zone"])
            if actual_zone and any(z in tbl.lower() for z in ["zone", "customer"]):
                try:
                    cursor.execute(f"SELECT 1 FROM {t_name} LIMIT 1")
                    if cursor.fetchone():
                        cursor.execute(f"""
                            SELECT DISTINCT {actual_zone} as val
                            FROM {t_name}
                            WHERE {actual_zone} IS NOT NULL AND {actual_zone} <> ''
                            ORDER BY val ASC
                        """)
                        zones = [r["val"] for r in cursor.fetchall() if r["val"]]
                        if zones:
                            break
                except Exception as e:
                    print(f"Error fetching zones from {t_name}: {e}")

        # 3. Fetch Regions (SAP RegionMaster has region_name, TerritoryMaster has NAME/REGIO)
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_region = get_actual_column_name(cursor, t_name, ["region_name", "region_code", "region", "regio"])
            if actual_region and any(r in tbl.lower() for r in ["region", "territory"]):
                try:
                    cursor.execute(f"SELECT 1 FROM {t_name} LIMIT 1")
                    if cursor.fetchone():
                        cursor.execute(f"""
                            SELECT DISTINCT {actual_region} as val
                            FROM {t_name}
                            WHERE {actual_region} IS NOT NULL AND {actual_region} <> ''
                            ORDER BY val ASC
                        """)
                        regions = [r["val"] for r in cursor.fetchall() if r["val"]]
                        if regions:
                            break
                except Exception as e:
                    print(f"Error fetching regions from {t_name}: {e}")

        # 4. Fetch Customer Types (SAP CustomerMaster has CH_TYPE e.g. DL, and KTOKD e.g. Z001)
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_customer_type = get_actual_column_name(cursor, t_name, ["ch_type", "ktokd", "customer_type", "customer_category", "cust_type", "type"])
            if actual_customer_type and "customer" in tbl.lower():
                try:
                    cursor.execute(f"SELECT 1 FROM {t_name} LIMIT 1")
                    if cursor.fetchone():
                        cursor.execute(f"""
                            SELECT DISTINCT {actual_customer_type} as val
                            FROM {t_name}
                            WHERE {actual_customer_type} IS NOT NULL AND {actual_customer_type} <> ''
                            ORDER BY val ASC
                        """)
                        customer_types = [r["val"] for r in cursor.fetchall() if r["val"]]
                        if customer_types:
                            break
                except Exception as e:
                    print(f"Error fetching customer types from {t_name}: {e}")

        # 5. Fetch Construction Types (SAP SKUMaster has CONSTUCTION)
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_construction_type = get_actual_column_name(cursor, t_name, ["constuction", "construction_type", "construction"])
            if actual_construction_type and any(s in tbl.lower() for s in ["sku", "material", "construction"]):
                try:
                    cursor.execute(f"SELECT 1 FROM {t_name} LIMIT 1")
                    if cursor.fetchone():
                        cursor.execute(f"""
                            SELECT DISTINCT {actual_construction_type} as val
                            FROM {t_name}
                            WHERE {actual_construction_type} IS NOT NULL AND {actual_construction_type} <> ''
                            ORDER BY val ASC
                        """)
                        construction_types = [r["val"] for r in cursor.fetchall() if r["val"]]
                        if construction_types:
                            break
                except Exception as e:
                    print(f"Error fetching construction types from {t_name}: {e}")

        return jsonify({
            "status": "success",
            "years": years,
            "zones": zones,
            "regions": regions,
            "months": months,
            "customer_types": customer_types,
            "construction_types": construction_types
        }), 200

    except Exception as exc:
        print(f"[Available Years] Database query failed: {exc}")
        return jsonify({
            "status": "error",
            "message": "Database query failed.",
            "details": str(exc)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            try:
                if hasattr(conn, "is_connected"):
                    if conn.is_connected():
                        conn.close()
                else:
                    conn.close()
            except Exception:
                pass

def default_dashboard_metrics_controller(get_db_connection):
    """
    Fetches default summary metrics (total sales, top tyre, leading region, YoY growth)
    to populate the dashboard right-side panels when the page initially loads.
    Uses dynamic table mapping based on session_id from external_db_sync_log.
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
        
    session_id = data.get("session_id", "")
    if not session_id:
        return jsonify({"error": "Missing session_id"}), 400

    conn = None
    cursor = None
    
    # Fallback default values
    metrics_data = {
        "metric_1": {"label": "Total Sales Revenue", "value": "N/A", "subtext": "No data available"},
        "metric_2": {"label": "Top Performing Tyre", "value": "N/A", "subtext": "No data available"},
        "metric_3": {"label": "Leading Region", "value": "N/A", "subtext": "No data available"},
        "metric_4": {"label": "Year-over-Year Growth", "value": "N/A", "subtext": "No data available"},
        "metric_5": {"label": "Achievement", "value": "N/A", "subtext": "Current achievement"},
        "metric_6": {"label": "Sales Target", "value": "N/A", "subtext": "Target sales"},
        "metric_7": {"label": "Sales Actual", "value": "N/A", "subtext": "Actual sales"},
        "metric_8": {"label": "SAS IN", "value": "N/A", "subtext": "SAS IN value"},
        "metric_9": {"label": "SAS Variance", "value": "N/A", "subtext": "Variance"},
        "metric_10": {"label": "Billing Scope", "value": "N/A", "subtext": "Billing scope"},
        "metric_11": {"label": "Dealer Spread", "value": "N/A", "subtext": "Dealer spread"},
        "metric_12": {"label": "Overdue", "value": "N/A", "subtext": "Overdue percentage"},
        "metric_13": {"label": "Exposure", "value": "N/A", "subtext": "Exposure percentage"},
        "metric_14": {"label": "Rotation", "value": "N/A", "subtext": "Rotation metric"},
        "metric_15": {"label": "New Dealer", "value": "N/A", "subtext": "New dealers"},
        "metric_16": {"label": "Attrition", "value": "N/A", "subtext": "Attrition count"}
    }

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Failed to connect to database."}), 500
            
        try:
            cursor = conn.cursor(dictionary=True)
        except TypeError:
            cursor = conn.cursor()

        # 1. Look up the dynamic table name and database from external_db_sync_log
        cursor.execute("""
            SELECT new_user_db, table_name 
            FROM external_db_sync_log 
            WHERE session_id=%s 
              AND new_user_db IS NOT NULL 
              AND new_user_db != ''
              AND table_name IS NOT NULL
            ORDER BY id DESC LIMIT 1
        """, (session_id,))
        sync_row = cursor.fetchone()

        if not sync_row:
            print(f"[Default Metrics] No dynamic table found for session {session_id}")
            return jsonify({"status": "success", "data": metrics_data}), 200

        user_db = sync_row["new_user_db"]
        tbl_name = sync_row["table_name"]
        
        # Build the dynamic fully qualified table name `db`.`table`
        table_name = f"`{user_db}`.`{tbl_name}`"
        
        # Fetch all synced tables for this session to dynamically inspect schemas
        # We query the main database (config.MYSQL_CONFIG['database']) before switching to user_db
        cursor.execute(f"""
            SELECT DISTINCT table_name 
            FROM `{config.MYSQL_CONFIG['database']}`.`external_db_sync_log` 
            WHERE session_id = %s 
              AND new_user_db = %s
              AND table_name IS NOT NULL
        """, (session_id, user_db))
        session_tables = [r["table_name"] for r in cursor.fetchall()]

        # Switch to the user's database just to be safe, though fully qualified name works
        cursor.execute(f"USE `{user_db}`")

        # Fetch all tables in user_db so we never miss any synced SAP views or tables
        cursor.execute("SHOW TABLES")
        db_tables = [list(r.values())[0] for r in cursor.fetchall()]
        all_tables = list(dict.fromkeys(session_tables + db_tables))

        table_columns = {}
        for tbl in all_tables:
            try:
                cursor.execute(f"DESCRIBE `{tbl}`")
                cols = cursor.fetchall()
                table_columns[tbl] = {col["Field"].lower().replace(' ', '').replace('_', ''): col["Field"] for col in cols}
            except Exception as e:
                print(f"[Default Metrics] Describe table {tbl} failed: {e}")

        def check_col(cols_dict, opts_list):
            if not cols_dict:
                return None
            for opt in opts_list:
                clean_opt = opt.lower().replace(' ', '').replace('_', '')
                if clean_opt in cols_dict:
                    return cols_dict[clean_opt]
            return None

        def find_table(candidates):
            for cand in candidates:
                clean_cand = cand.lower().replace('_', '').replace('-', '')
                for tbl in table_columns.keys():
                    clean_tbl = tbl.lower().replace('_', '').replace('-', '')
                    if clean_cand in clean_tbl:
                        return tbl
            return None

        # Identify SAP & Legacy Tables
        curr_sales_tbl = find_table(["zpvfsdcurrentsales", "currentsales", "current_sales"])
        hist_sales_tbl = find_table(["zpvfsdsaleshistory", "saleshistory", "sales_history"])
        sales_data_tbl = find_table(["salesdata", "sales_data"])
        cust_tbl = find_table(["zivfcustomermaster", "customermaster", "customer"])
        terr_tbl = find_table(["zivfterritorymaster", "territorymaster", "territory"])
        reg_tbl = find_table(["zivfregionmaster", "regionmaster", "region"])
        zone_tbl = find_table(["zivfzonemaster", "zonemaster", "zone"])
        sku_tbl = find_table(["zivrskumaster", "skumaster", "materialmaster", "material", "sku"])
        cat_tbl = find_table(["zivfcategorymaster", "categorymaster", "category"])
        tyre_tbl = find_table(["tyretypemaster", "tyretype"])
        day_attr_tbl = find_table(["zitrdayattribute", "dayattribute", "day_attribute"])
        target_tbl = find_table(["salestarget", "sales_target", "target", "budget"])

        # Determine sales fact expression and columns (union of CurrentSales and SalesHistory if both exist)
        if curr_sales_tbl and hist_sales_tbl:
            sales_from = f"(SELECT * FROM `{curr_sales_tbl}` UNION ALL SELECT * FROM `{hist_sales_tbl}`) s"
            sales_cols = table_columns.get(curr_sales_tbl) or table_columns.get(hist_sales_tbl) or {}
            primary_sales_tbl = curr_sales_tbl
        elif curr_sales_tbl:
            sales_from = f"`{curr_sales_tbl}` s"
            sales_cols = table_columns.get(curr_sales_tbl, {})
            primary_sales_tbl = curr_sales_tbl
        elif hist_sales_tbl:
            sales_from = f"`{hist_sales_tbl}` s"
            sales_cols = table_columns.get(hist_sales_tbl, {})
            primary_sales_tbl = hist_sales_tbl
        elif sales_data_tbl:
            sales_from = f"`{sales_data_tbl}` s"
            sales_cols = table_columns.get(sales_data_tbl, {})
            primary_sales_tbl = sales_data_tbl
        else:
            # Fallback to tbl_name or table with revenue column
            found_tbl = tbl_name
            for tbl, cols in table_columns.items():
                if check_col(cols, ["invoice_value", "ndp_value", "invoice_value_inr", "taxable_value"]):
                    found_tbl = tbl
                    break
            sales_from = f"`{found_tbl}` s"
            sales_cols = table_columns.get(found_tbl, {})
            primary_sales_tbl = found_tbl

        real_revenue_col = check_col(sales_cols, ["invoice_value", "ndp_value", "invoice_value_inr", "taxable_value", "taxable_value_inr", "ndp_inr"])
        has_revenue = bool(real_revenue_col)

        if has_revenue:
            join_revenue_expr = f"CAST(REPLACE(TRIM(s.`{real_revenue_col}`), ',', '') AS DECIMAL(18,2))"
        else:
            join_revenue_expr = "0.0"

        # 1. Total Sales Revenue
        total_revenue = 0.0
        if has_revenue:
            try:
                cursor.execute(f"SELECT SUM({join_revenue_expr}) AS total_sales_revenue FROM {sales_from}")
                row = cursor.fetchone()
                total_revenue = float(row["total_sales_revenue"] or 0) if row else 0.0
            except Exception as rev_err:
                print(f"[Default Metrics] Total revenue query failed: {rev_err}")

        # 2. Top Performing Tyre
        top_tyre = "N/A"
        if has_revenue:
            # Priority 1: Join SKU Master with Category Master (SAP Standard: sku -> matnr -> cat_code -> cat_desc)
            if sku_tbl and cat_tbl:
                sales_mat = check_col(sales_cols, ["sku", "material", "matnr"])
                sku_mat = check_col(table_columns[sku_tbl], ["matnr", "sku", "material"])
                sku_cat = check_col(table_columns[sku_tbl], ["cat_code", "catcode", "category_code", "category"])
                cat_code = check_col(table_columns[cat_tbl], ["cat_code", "catcode", "category_code"])
                cat_desc = check_col(table_columns[cat_tbl], ["cat_desc", "catdesc", "category_desc", "category_name", "cat_name"])
                
                if sales_mat and sku_mat and sku_cat and cat_code and cat_desc:
                    try:
                        cursor.execute(f"""
                            SELECT
                                cat.`{cat_desc}` AS vehicle_type,
                                ROUND(SUM({join_revenue_expr}), 2) AS revenue
                            FROM {sales_from}
                            JOIN `{sku_tbl}` sm ON s.`{sales_mat}` = sm.`{sku_mat}`
                            JOIN `{cat_tbl}` cat ON sm.`{sku_cat}` = cat.`{cat_code}`
                            WHERE cat.`{cat_desc}` IS NOT NULL AND cat.`{cat_desc}` <> ''
                            GROUP BY cat.`{cat_desc}`
                            ORDER BY revenue DESC
                            LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row and row.get("vehicle_type"):
                            top_tyre = row["vehicle_type"]
                    except Exception as tyre_err:
                        print(f"[Default Metrics] Category master join query failed: {tyre_err}")

            # Priority 2: Direct join Sales SKU with Category Master (cat.matnr)
            if top_tyre == "N/A" and cat_tbl:
                sales_mat = check_col(sales_cols, ["sku", "material", "matnr"])
                cat_mat = check_col(table_columns[cat_tbl], ["matnr", "sku", "material"])
                cat_desc = check_col(table_columns[cat_tbl], ["cat_desc", "catdesc", "category_desc", "category_name"])
                if sales_mat and cat_mat and cat_desc:
                    try:
                        cursor.execute(f"""
                            SELECT
                                cat.`{cat_desc}` AS vehicle_type,
                                ROUND(SUM({join_revenue_expr}), 2) AS revenue
                            FROM {sales_from}
                            JOIN `{cat_tbl}` cat ON s.`{sales_mat}` = cat.`{cat_mat}`
                            WHERE cat.`{cat_desc}` IS NOT NULL AND cat.`{cat_desc}` <> ''
                            GROUP BY cat.`{cat_desc}`
                            ORDER BY revenue DESC
                            LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row and row.get("vehicle_type"):
                            top_tyre = row["vehicle_type"]
                    except Exception as tyre_err:
                        print(f"[Default Metrics] Direct category master query failed: {tyre_err}")

            # Priority 3: Tyre Type from tyre_tbl (legacy)
            if top_tyre == "N/A" and tyre_tbl and sku_tbl:
                sales_mat = check_col(sales_cols, ["sku", "material", "matnr"])
                sku_mat = check_col(table_columns[sku_tbl], ["matnr", "sku", "material"])
                sku_tyre = check_col(table_columns[sku_tbl], ["tyre_type", "tyretype", "vehicle_type"])
                tyre_code = check_col(table_columns[tyre_tbl], ["tyre_type_code", "tyre_type"])
                tyre_name = check_col(table_columns[tyre_tbl], ["tyre_type_name", "tyre_name"])
                if sales_mat and sku_mat and sku_tyre and tyre_code and tyre_name:
                    try:
                        cursor.execute(f"""
                            SELECT
                                t.`{tyre_name}` AS vehicle_type,
                                ROUND(SUM({join_revenue_expr}), 2) AS revenue
                            FROM {sales_from}
                            JOIN `{sku_tbl}` k ON s.`{sales_mat}` = k.`{sku_mat}`
                            JOIN `{tyre_tbl}` t ON k.`{sku_tyre}` = t.`{tyre_code}`
                            WHERE t.`{tyre_name}` IS NOT NULL AND t.`{tyre_name}` NOT IN ('', '0', '-')
                            GROUP BY t.`{tyre_name}`
                            ORDER BY revenue DESC
                            LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row and row.get("vehicle_type"):
                            top_tyre = row["vehicle_type"]
                    except Exception as tyre_err:
                        print(f"[Default Metrics] Joined tyre_tbl query failed: {tyre_err}")

            # Priority 4: vehicle_type directly in sales table
            if top_tyre == "N/A":
                sales_tyre = check_col(sales_cols, ["vehicle_type", "tyre_type"])
                if sales_tyre:
                    try:
                        cursor.execute(f"""
                            SELECT
                                s.`{sales_tyre}` AS vehicle_type,
                                ROUND(SUM({join_revenue_expr}), 2) AS revenue
                            FROM {sales_from}
                            WHERE s.`{sales_tyre}` IS NOT NULL AND s.`{sales_tyre}` NOT IN ('', '0', '-')
                            GROUP BY s.`{sales_tyre}`
                            ORDER BY revenue DESC
                            LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row and row.get("vehicle_type"):
                            top_tyre = row["vehicle_type"]
                    except Exception as tyre_err:
                        print(f"[Default Metrics] Top tyre direct query failed: {tyre_err}")

            # Priority 5: From SKU Master (excluding '0', '', '-')
            if top_tyre == "N/A" and sku_tbl:
                sales_mat = check_col(sales_cols, ["sku", "material", "matnr"])
                sku_mat = check_col(table_columns[sku_tbl], ["matnr", "sku", "material"])
                sku_tyre = check_col(table_columns[sku_tbl], ["tyre_type", "tyretype", "vehicle_type", "maktx"])
                if sales_mat and sku_mat and sku_tyre:
                    try:
                        cursor.execute(f"""
                            SELECT
                                k.`{sku_tyre}` AS vehicle_type,
                                ROUND(SUM({join_revenue_expr}), 2) AS revenue
                            FROM {sales_from}
                            JOIN `{sku_tbl}` k ON s.`{sales_mat}` = k.`{sku_mat}`
                            WHERE k.`{sku_tyre}` IS NOT NULL AND k.`{sku_tyre}` NOT IN ('', '0', '-')
                            GROUP BY k.`{sku_tyre}`
                            ORDER BY revenue DESC
                            LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row and row.get("vehicle_type"):
                            top_tyre = row["vehicle_type"]
                    except Exception as tyre_err:
                        print(f"[Default Metrics] SKU tyre query failed: {tyre_err}")

        # 3. Leading Region
        leading_region = "N/A"
        if has_revenue:
            # Priority 1: Direct region column in sales table
            sales_reg = check_col(sales_cols, ["region", "region_name"])
            if sales_reg:
                try:
                    cursor.execute(f"""
                        SELECT
                            s.`{sales_reg}` AS region,
                            ROUND(SUM({join_revenue_expr}), 2) AS revenue
                        FROM {sales_from}
                        WHERE s.`{sales_reg}` IS NOT NULL AND s.`{sales_reg}` <> ''
                        GROUP BY s.`{sales_reg}`
                        ORDER BY revenue DESC
                        LIMIT 1
                    """)
                    row = cursor.fetchone()
                    if row and row.get("region"):
                        leading_region = row["region"]
                except Exception as reg_err:
                    print(f"[Default Metrics] Leading region direct query failed: {reg_err}")

            # Priority 2: SAP Plant mapping (sales.plant -> territorymaster.werks -> territorymaster.area -> regionmaster.region_code)
            if leading_region == "N/A" and terr_tbl and reg_tbl:
                sales_plant = check_col(sales_cols, ["plant", "werks"])
                terr_werks = check_col(table_columns[terr_tbl], ["werks", "plant"])
                terr_area = check_col(table_columns[terr_tbl], ["area", "region_code", "region", "regio"])
                r_code = check_col(table_columns[reg_tbl], ["region_code", "region", "regio"])
                r_name = check_col(table_columns[reg_tbl], ["region_name", "region", "name"])

                if sales_plant and terr_werks and terr_area and r_code and r_name:
                    try:
                        cursor.execute(f"""
                            SELECT
                                r.`{r_name}` AS region_name,
                                ROUND(SUM({join_revenue_expr}), 2) AS revenue
                            FROM {sales_from}
                            JOIN `{terr_tbl}` t ON s.`{sales_plant}` = t.`{terr_werks}`
                            JOIN `{reg_tbl}` r ON (t.`{terr_area}` = r.`{r_code}`)
                            WHERE r.`{r_name}` IS NOT NULL AND r.`{r_name}` <> ''
                            GROUP BY r.`{r_name}`
                            ORDER BY revenue DESC
                            LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row and row.get("region_name"):
                            leading_region = row["region_name"]
                    except Exception as reg_err:
                        print(f"[Default Metrics] Plant territory region query failed: {reg_err}")

            # Priority 3: Customer -> Territory -> Region join
            if leading_region == "N/A" and cust_tbl and reg_tbl:
                sales_cust = check_col(sales_cols, ["dealercode", "dealer_code", "customer", "kunnr"])
                cust_id = check_col(table_columns[cust_tbl], ["kunnr", "dealercode", "customer"])
                r_name = check_col(table_columns[reg_tbl], ["region_name", "region", "name"])

                if terr_tbl:
                    cust_terr = check_col(table_columns[cust_tbl], ["bzirk", "territory", "territory_code"])
                    terr_code = check_col(table_columns[terr_tbl], ["bzirk", "territory_code", "territory"])
                    terr_reg = check_col(table_columns[terr_tbl], ["regio", "region_code", "region", "area"])
                    r_code = check_col(table_columns[reg_tbl], ["region_code", "region", "regio"])

                    if sales_cust and cust_id and cust_terr and terr_code and terr_reg and r_code and r_name:
                        try:
                            cursor.execute(f"""
                                SELECT
                                    r.`{r_name}` AS region_name,
                                    ROUND(SUM({join_revenue_expr}), 2) AS revenue
                                FROM {sales_from}
                                JOIN `{cust_tbl}` c ON s.`{sales_cust}` = c.`{cust_id}`
                                JOIN `{terr_tbl}` t ON c.`{cust_terr}` = t.`{terr_code}`
                                JOIN `{reg_tbl}` r ON (t.`{terr_reg}` = r.`{r_code}`)
                                WHERE r.`{r_name}` IS NOT NULL AND r.`{r_name}` <> ''
                                GROUP BY r.`{r_name}`
                                ORDER BY revenue DESC
                                LIMIT 1
                            """)
                            row = cursor.fetchone()
                            if row and row.get("region_name"):
                                leading_region = row["region_name"]
                        except Exception as reg_err:
                            print(f"[Default Metrics] Joined territory region query failed: {reg_err}")

                if leading_region == "N/A" and sales_cust and cust_id and r_name:
                    # Direct join Customer -> Region if Customer has REGIO
                    cust_reg = check_col(table_columns[cust_tbl], ["regio", "region_code", "region"])
                    r_code = check_col(table_columns[reg_tbl], ["region_code", "region", "regio"])
                    if cust_reg and r_code:
                        try:
                            cursor.execute(f"""
                                SELECT
                                    r.`{r_name}` AS region_name,
                                    ROUND(SUM({join_revenue_expr}), 2) AS revenue
                                FROM {sales_from}
                                JOIN `{cust_tbl}` c ON s.`{sales_cust}` = c.`{cust_id}`
                                JOIN `{reg_tbl}` r ON c.`{cust_reg}` = r.`{r_code}`
                                WHERE r.`{r_name}` IS NOT NULL AND r.`{r_name}` <> ''
                                GROUP BY r.`{r_name}`
                                ORDER BY revenue DESC
                                LIMIT 1
                            """)
                            row = cursor.fetchone()
                            if row and row.get("region_name"):
                                leading_region = row["region_name"]
                        except Exception as reg_err:
                            print(f"[Default Metrics] Direct customer region query failed: {reg_err}")

        # 4. YoY Growth
        current_year = 0.0
        previous_year = 0.0
        current_year_num = None
        prev_year_num = None
        yoy = 0.0
        yoy_subtext = "No data available"
        real_date_col = check_col(sales_cols, ["invoice_date", "date", "billing__doc_date", "billing_doc_date"])

        if has_revenue and real_date_col:
            try:
                # Detect column type
                cursor.execute(f"SHOW COLUMNS FROM `{primary_sales_tbl}` LIKE %s", (real_date_col,))
                col_info = cursor.fetchone()
                col_type = col_info["Type"].lower() if col_info else "text"

                if "date" in col_type or "timestamp" in col_type:
                    year_expr = f"YEAR(s.`{real_date_col}`)"
                    date_filter = f"s.`{real_date_col}` IS NOT NULL"
                else:
                    year_expr = f"YEAR(COALESCE(STR_TO_DATE(s.`{real_date_col}`, '%Y-%m-%d'), STR_TO_DATE(s.`{real_date_col}`, '%d-%m-%Y'), STR_TO_DATE(s.`{real_date_col}`, '%d/%m/%Y')))"
                    date_filter = f"s.`{real_date_col}` IS NOT NULL AND s.`{real_date_col}` != ''"

                # Fetch available revenue by year dynamically (descending order)
                cursor.execute(f"""
                    SELECT {year_expr} AS yr, ROUND(SUM({join_revenue_expr}), 2) AS revenue
                    FROM {sales_from}
                    WHERE {date_filter} AND {year_expr} IS NOT NULL AND {year_expr} > 2000
                    GROUP BY {year_expr}
                    ORDER BY yr DESC
                """)
                year_rows = cursor.fetchall()
                if year_rows and len(year_rows) > 0:
                    current_year_row = year_rows[0]
                    current_year = float(current_year_row["revenue"] or 0)
                    current_year_num = current_year_row["yr"]

                    if len(year_rows) > 1:
                        prev_year_row = year_rows[1]
                        previous_year = float(prev_year_row["revenue"] or 0)
                        prev_year_num = prev_year_row["yr"]

                        if previous_year > 0:
                            yoy = round(((current_year - previous_year) / previous_year) * 100, 2)
                            if current_year_num - prev_year_num == 1:
                                yoy_subtext = "Compared to last year"
                            else:
                                yoy_subtext = f"Compared to {prev_year_num}"
                        else:
                            yoy_subtext = f"{current_year_num} sales only"
                    else:
                        yoy_subtext = f"{current_year_num} sales only"
            except Exception as yoy_err:
                print(f"[Default Metrics] YoY query failed: {yoy_err}")

        # 5. Billing Scope (Distinct active customers billed)
        billing_scope = "N/A"
        real_cust_col_sales = check_col(sales_cols, ["dealercode", "dealer_code", "customer", "kunnr"])
        
        if real_cust_col_sales:
            try:
                cursor.execute(f"SELECT COUNT(DISTINCT s.`{real_cust_col_sales}`) AS count FROM {sales_from}")
                row = cursor.fetchone()
                if row and row["count"] is not None:
                    billing_scope = str(row["count"])
            except Exception as e:
                print(f"[Default Metrics] Billing scope query failed: {e}")

        # 6. Dealer Spread (Active dealers with CH_TYPE='DL' or KTOKD='Z001')
        dealer_spread = "N/A"
        if real_cust_col_sales and cust_tbl:
            cust_id_col = check_col(table_columns[cust_tbl], ["kunnr", "dealercode", "customer"])
            dealer_type_col = check_col(table_columns[cust_tbl], ["ch_type", "ktokd", "acc_grp", "customer_type"])
            if cust_id_col and dealer_type_col:
                try:
                    cursor.execute(f"""
                        SELECT COUNT(DISTINCT s.`{real_cust_col_sales}`) AS count
                        FROM {sales_from}
                        JOIN `{cust_tbl}` c ON s.`{real_cust_col_sales}` = c.`{cust_id_col}`
                        WHERE c.`{dealer_type_col}` = 'DL' OR c.`{dealer_type_col}` = 'Z001'
                    """)
                    row = cursor.fetchone()
                    if row and row["count"] is not None:
                        dealer_spread = str(row["count"])
                except Exception as e:
                    print(f"[Default Metrics] Dealer spread query failed: {e}")

        # 7. Credit Exposure and Outstanding (from SAP Customer Master ZIVF_CustomerMaster_01_MD)
        exposure_val = "N/A"
        overdue_val = "N/A"
        if cust_tbl:
            exp_col = check_col(table_columns[cust_tbl], ["exposure"])
            out_col = check_col(table_columns[cust_tbl], ["outstand", "outstanding"])
            if exp_col:
                try:
                    cursor.execute(f"SELECT SUM(CAST(REPLACE(TRIM(`{exp_col}`), ',', '') AS DECIMAL(18,2))) AS val FROM `{cust_tbl}` WHERE `{exp_col}` IS NOT NULL AND `{exp_col}` != ''")
                    row = cursor.fetchone()
                    if row and row["val"] is not None:
                        v = float(row["val"])
                        if v >= 10000000:
                            exposure_val = f"₹{(v / 10000000):.2f} Cr"
                        elif v >= 100000:
                            exposure_val = f"₹{(v / 100000):.2f} Lac"
                        else:
                            exposure_val = f"₹{v:,.2f}"
                except Exception as e:
                    print(f"[Default Metrics] Exposure query failed: {e}")
            if out_col:
                try:
                    cursor.execute(f"SELECT SUM(CAST(REPLACE(TRIM(`{out_col}`), ',', '') AS DECIMAL(18,2))) AS val FROM `{cust_tbl}` WHERE `{out_col}` IS NOT NULL AND `{out_col}` != ''")
                    row = cursor.fetchone()
                    if row and row["val"] is not None:
                        v = float(row["val"])
                        if v >= 10000000:
                            overdue_val = f"₹{(v / 10000000):.2f} Cr"
                        elif v >= 100000:
                            overdue_val = f"₹{(v / 100000):.2f} Lac"
                        else:
                            overdue_val = f"₹{v:,.2f}"
                except Exception as e:
                    print(f"[Default Metrics] Outstanding query failed: {e}")

        # 8. Attrition
        attrition = "N/A"
        if real_cust_col_sales and real_date_col:
            try:
                if "date" in col_type or "timestamp" in col_type:
                    date_expr = f"s.`{real_date_col}`"
                else:
                    date_expr = f"STR_TO_DATE(s.`{real_date_col}`, '%d-%m-%Y')"
                    
                cursor.execute(f"""
                    SELECT COUNT(DISTINCT prev_month_cust) AS attrition_count
                    FROM (
                        SELECT DISTINCT s.`{real_cust_col_sales}` AS prev_month_cust
                        FROM {sales_from}
                        WHERE {date_expr} >= DATE_FORMAT(CURRENT_DATE - INTERVAL 1 MONTH, '%Y-%m-01')
                          AND {date_expr} < DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
                    ) AS prev
                    WHERE prev_month_cust NOT IN (
                        SELECT DISTINCT s.`{real_cust_col_sales}`
                        FROM {sales_from}
                        WHERE {date_expr} >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
                    )
                """)
                row = cursor.fetchone()
                if row and row["attrition_count"] is not None:
                    attrition = str(row["attrition_count"])
            except Exception as e:
                print(f"[Default Metrics] Attrition query failed: {e}")

        # 9. Sales Target and Achievement
        sales_target_val = "N/A"
        achievement_val = "N/A"
        
        if target_tbl:
            try:
                target_col = check_col(table_columns[target_tbl], ["value", "target", "target_value"]) or "Value"
                cursor.execute(f"SELECT SUM(`{target_col}`) AS total_target FROM `{target_tbl}`")
                t_row = cursor.fetchone()
                if t_row and t_row["total_target"] is not None:
                    t_val = float(t_row["total_target"])
                    if t_val > 0:
                        formatted_target = f"₹{t_val:,.2f}"
                        if t_val >= 10000000:
                            formatted_target = f"₹{(t_val / 10000000):.2f} Cr"
                        elif t_val >= 100000:
                            formatted_target = f"₹{(t_val / 100000):.2f} Lac"
                        sales_target_val = formatted_target
                        
                        if float(total_revenue) > 0:
                            ach = (float(total_revenue) / t_val) * 100
                            achievement_val = f"{ach:.2f}%"
            except Exception as e:
                print(f"[Default Metrics] Sales target query failed: {e}")

        # Format total revenue smartly (Cr or Lacs)
        formatted_revenue = f"₹{float(total_revenue):,.2f}"
        if total_revenue >= 10000000:
            formatted_revenue = f"₹{(total_revenue / 10000000):.2f} Cr"
        elif total_revenue >= 100000:
            formatted_revenue = f"₹{(total_revenue / 100000):.2f} Lac"

        total_revenue = float(total_revenue)
        # Format output as dynamic metrics for frontend
        metrics_data = {
            "metric_1": {
                "label": "Total Sales Revenue", 
                "value": formatted_revenue, 
                "subtext": "Lifetime revenue"
            },
            "metric_2": {
                "label": "Top Performing Tyre", 
                "value": str(top_tyre), 
                "subtext": "Highest revenue generator"
            },
            "metric_3": {
                "label": "Leading Region", 
                "value": str(leading_region), 
                "subtext": "Most profitable territory"
            },
            "metric_4": {
                "label": "Year-over-Year Growth", 
                "value": f"{yoy:+0.1f}%" if previous_year > 0 else ("0.0%" if current_year > 0 else "N/A"), 
                "subtext": yoy_subtext
            },
            "metric_5": {"label": "Achievement", "value": achievement_val, "subtext": "Current achievement"},
            "metric_6": {"label": "Sales Target", "value": sales_target_val, "subtext": "Target sales"},
            "metric_7": {"label": "Sales Actual", "value": formatted_revenue, "subtext": "Actual sales"},
            "metric_8": {"label": "SAS IN", "value": "N/A", "subtext": "SAS IN value"},
            "metric_9": {"label": "SAS Variance", "value": "N/A", "subtext": "Variance"},
            "metric_10": {"label": "Billing Scope", "value": billing_scope, "subtext": "Customers billed"},
            "metric_11": {"label": "Dealer Spread", "value": dealer_spread, "subtext": "Active dealers"},
            "metric_12": {"label": "Overdue", "value": overdue_val, "subtext": "Outstanding balance"},
            "metric_13": {"label": "Exposure", "value": exposure_val, "subtext": "Credit exposure"},
            "metric_14": {"label": "Rotation", "value": "N/A", "subtext": "Rotation metric"},
            "metric_15": {"label": "New Dealer", "value": "N/A", "subtext": "New dealers"},
            "metric_16": {"label": "Attrition", "value": attrition, "subtext": "Inactive from last month"}
        }

        return jsonify({"status": "success", "data": metrics_data}), 200

    except Exception as exc:
        print(f"[Default Metrics] Database query failed: {exc}")
        return jsonify({
            "status": "error",
            "message": "Database query failed.",
            "details": str(exc)
        }), 500

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                if hasattr(conn, "is_connected"):
                    if conn.is_connected():
                        conn.close()
                else:
                    conn.close()
            except Exception:
                pass