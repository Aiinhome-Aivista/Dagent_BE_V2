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
        
        target = expected_name.lower().replace('_', '').replace(' ', '')
        
        # 1. Exact match
        for col in columns:
            if col == expected_name: return f"`{col}`"
                
        # 2. Case insensitive match
        for col in columns:
            if col.lower() == expected_name.lower(): return f"`{col}`"
                
        # 3. Fuzzy match
        for col in columns:
            if col.lower().replace('_', '').replace(' ', '') == target: return f"`{col}`"
                
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
    # required_metrics and optional_dims are now dictionaries: { "key_name": ["opt1", "opt2", ...] }
    cursor.execute("""
        SELECT DISTINCT new_user_db, table_name 
        FROM external_db_sync_log 
        WHERE session_id=%s 
          AND new_user_db IS NOT NULL 
          AND table_name IS NOT NULL
    """, (session_id,))
    rows = cursor.fetchall()
    if not rows:
        return None, None, {}

    user_db = rows[0]["new_user_db"]
    synced_tables = [r["table_name"] for r in rows]
    
    table_columns = {}
    for tbl in synced_tables:
        try:
            cursor.execute(f"DESCRIBE `{user_db}`.`{tbl}`")
            cols = cursor.fetchall()
            table_columns[tbl] = {c["Field"].lower().replace(' ', '').replace('_', ''): c["Field"] for c in cols}
        except Exception:
            pass

    def check_match(cols_dict, opts_list):
        for opt in opts_list:
            clean_opt = opt.lower().replace(' ', '').replace('_', '')
            if clean_opt in cols_dict:
                return cols_dict[clean_opt]
        return None

    # Find the fact table
    fact_table = None
    
    # ALWAYS prioritize sales_data if it exists
    for tbl in table_columns.keys():
        if "sales_data" in tbl.lower():
            fact_table = tbl
            break
            
    # Fallback to original logic if sales_data is not found
    if not fact_table:
        for tbl, cols in table_columns.items():
            req_keys = list(required_metrics.keys())
            # Check if first required metric is in this table
            if req_keys and check_match(cols, required_metrics[req_keys[0]]):
                fact_table = tbl
                if any("invoice" in k for k in cols.keys()):
                    break
    
    if not fact_table:
        fact_table = synced_tables[0] if synced_tables else None
        
    if not fact_table:
        return None, None, {}

    resolved_cols = {}
    
    all_metrics = {**required_metrics, **optional_dims}
    
    # --- MULTI-HOP LOGIC FOR SALES_DATA ---
    # Since zone is in region_master, it requires a 3-hop join from sales_data.
    # We must handle this explicitly because the generic logic below only does single-hop.
    fact_table_actual = None
    for tbl in table_columns.keys():
        if "sales_data" in tbl.lower():
            fact_table_actual = tbl
            break

    if fact_table_actual and "sales_data" in fact_table.lower():
        synced_lower = {t.lower(): t for t in synced_tables}
        from_clause = f"`{user_db}`.`{fact_table_actual}` s"
        joins = []
        
        def add_join(table_key, alias, on_clause):
            if table_key in synced_lower:
                actual_tbl = synced_lower[table_key]
                joins.append(f"LEFT JOIN `{user_db}`.`{actual_tbl}` {alias} ON {on_clause}")
                return True
            return False

        add_join("customer_master", "cm", "s.`customer` = cm.`KUNNR`")
        add_join("territory_master", "tm", "cm.`territory` = tm.`territory_code`")
        add_join("region_master", "rm", "tm.`region_code` = rm.`region`")
        add_join("sku_master", "sm", "s.`material` = sm.`MATNR`")
        add_join("tyre_type_master", "ttm", "sm.`tyre_type` = ttm.`tyre_type_code`")
        add_join("category_master", "catm", "sm.`category` = catm.`category_code`")
        add_join("construction_master", "consm", "sm.`construction` = consm.`construction_code`")
            
        from_clause += " " + " ".join(joins)

        resolved_cols = {}
        alias_map = {
            "customer_master": "cm",
            "territory_master": "tm",
            "region_master": "rm",
            "tyre_type_master": "ttm",
            "category_master": "catm",
            "construction_master": "consm",
            "sku_master": "sm"
        }
        
        for req_key, opts in all_metrics.items():
            found = check_match(table_columns[fact_table_actual], opts)
            if found:
                resolved_cols[req_key] = f"s.`{found}`"
                continue
            resolved = False
            for tbl_key, alias in alias_map.items():
                if tbl_key in synced_lower:
                    actual_tbl = synced_lower[tbl_key]
                    found = check_match(table_columns[actual_tbl], opts)
                    if found:
                        resolved_cols[req_key] = f"{alias}.`{found}`"
                        resolved = True
                        break
            if not resolved:
                resolved_cols[req_key] = None
                
        # If required metrics are met, return immediately
        missing_required = False
        for req_key in required_metrics.keys():
            if not resolved_cols.get(req_key):
                missing_required = True
                
        if not missing_required:
            return from_clause, user_db, resolved_cols

    # --- GENERIC SINGLE-HOP LOGIC FALLBACK ---
    resolved_cols = {}
    
    # Try to find all columns in fact_table first
    for req_key, opts in all_metrics.items():
        found = check_match(table_columns[fact_table], opts)
        if found:
            resolved_cols[req_key] = f"s.`{found}`"
        else:
            resolved_cols[req_key] = None

    joins = []
    dim_count = 1
    
    for req_key, opts in all_metrics.items():
        if resolved_cols.get(req_key) is not None:
            continue
            
        for tbl in synced_tables:
            if tbl == fact_table: continue
            
            found_col = check_match(table_columns[tbl], opts)
            if found_col:
                alias = f"t{dim_count}"
                # Join key
                # Compare original keys but ignoring spaces and underscores
                common_cols = set(table_columns[fact_table].keys()) & set(table_columns[tbl].keys())
                join_key = None
                # Check for special mappings first (like material -> MATNR, customer -> KUNNR)
                fact_keys = table_columns[fact_table].keys()
                dim_keys = table_columns[tbl].keys()
                
                join_col_fact = None
                join_col_dim = None
                
                if "material" in fact_keys and "matnr" in dim_keys:
                    join_col_fact = table_columns[fact_table]["material"]
                    join_col_dim = table_columns[tbl]["matnr"]
                    join_key = "special_mapping"
                elif "customer" in fact_keys and "kunnr" in dim_keys:
                    join_col_fact = table_columns[fact_table]["customer"]
                    join_col_dim = table_columns[tbl]["kunnr"]
                    join_key = "special_mapping"
                elif "territory" in fact_keys and "territorycode" in dim_keys:
                    join_col_fact = table_columns[fact_table]["territory"]
                    join_col_dim = table_columns[tbl]["territorycode"]
                    join_key = "special_mapping"
                elif "regioncode" in fact_keys and "region" in dim_keys:
                    join_col_fact = table_columns[fact_table]["regioncode"]
                    join_col_dim = table_columns[tbl]["region"]
                    join_key = "special_mapping"
                else:
                    for pref in ["material", "customer", "plant", "id", "oldcode"]:
                        if pref in common_cols:
                            join_key = pref
                            break
                    if not join_key and common_cols:
                        join_key = list(common_cols)[0]
                        
                    if join_key:
                        join_col_fact = table_columns[fact_table][join_key]
                        join_col_dim = table_columns[tbl][join_key]
                        
                if join_key:
                    joins.append(f"LEFT JOIN `{user_db}`.`{tbl}` {alias} ON s.`{join_col_fact}` = {alias}.`{join_col_dim}`")
                    resolved_cols[req_key] = f"{alias}.`{found_col}`"
                    dim_count += 1
                    break
                    
    for req_key in required_metrics.keys():
        if not resolved_cols.get(req_key):
            return None, None, {}
            
    from_clause = f"`{user_db}`.`{fact_table}` s"
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
            "vehicle_type": ["tyre_type_name", "tyre_type_description", "tyre_type_desc", "vehicle_type", "tyre_type", "category_name", "category"],
            "invoice_value": ["invoice_value", "taxable_value", "revenue", "Invoice_Value_INR"]
        }
        optional_dims = {}
        if has_valid_filters(selected_years):
            optional_dims["invoice_date"] = ["invoice_date", "date", "billing__doc_date"]
        if has_valid_filters(selected_customer_categories):
            optional_dims["customer_category"] = ["customer_type", "customer_category", "cust_type", "type"]
        if has_valid_filters(selected_zones):
            optional_dims["zone"] = ["Zone", "zone"]
        if has_valid_filters(selected_regions):
            optional_dims["region"] = ["Region", "region"]
        if has_valid_filters(selected_constructions):
            optional_dims["construction_type"] = ["construction_type", "construction"]
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
            
        cursor = conn.cursor(dictionary=True)
        
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
        
        table_name = None
        actual_cat = None
        actual_const = None
        actual_tyre = None
        actual_date = None

        if row:
            user_db = row["new_user_db"]
            cursor.execute(f"USE `{user_db}`")
            cursor.execute("SHOW TABLES")
            tables = [list(r.values())[0] for r in cursor.fetchall()]
            
            # Find categories across all tables
            for tbl in tables:
                t_name = f"`{user_db}`.`{tbl}`"
                cat = get_actual_column_name(cursor, t_name, "product_category") or \
                      get_actual_column_name(cursor, t_name, "category") or \
                      get_actual_column_name(cursor, t_name, "product_type")
                if cat:
                    try:
                        cursor.execute(f"SELECT DISTINCT {cat} as val FROM {t_name} WHERE {cat} IS NOT NULL AND {cat} != ''")
                        res = [r["val"] for r in cursor.fetchall() if r["val"]]
                        if res:
                            filters_data["categories"] = res
                            break
                    except Exception as e:
                        print(f"Error fetching categories from {t_name}: {e}")

            # Find constructions across all tables
            for tbl in tables:
                t_name = f"`{user_db}`.`{tbl}`"
                const = get_actual_column_name(cursor, t_name, "construction_type") or \
                        get_actual_column_name(cursor, t_name, "construction")
                if const:
                    try:
                        cursor.execute(f"SELECT DISTINCT {const} as val FROM {t_name} WHERE {const} IS NOT NULL AND {const} != ''")
                        res = [r["val"] for r in cursor.fetchall() if r["val"]]
                        if res:
                            filters_data["constructions"] = res
                            break
                    except Exception as e:
                        print(f"Error fetching constructions from {t_name}: {e}")

            # Find tyreTypes across all tables
            for tbl in tables:
                t_name = f"`{user_db}`.`{tbl}`"
                tyre = get_actual_column_name(cursor, t_name, "vehicle_type")
                if tyre:
                    try:
                        cursor.execute(f"SELECT DISTINCT {tyre} as val FROM {t_name} WHERE {tyre} IS NOT NULL AND {tyre} != ''")
                        res = [r["val"] for r in cursor.fetchall() if r["val"]]
                        if res:
                            filters_data["tyreTypes"] = res
                            break
                    except Exception as e:
                        print(f"Error fetching tyreTypes from {t_name}: {e}")

            # Find years and months across all tables
            for tbl in tables:
                t_name = f"`{user_db}`.`{tbl}`"
                date_col = get_actual_column_name(cursor, t_name, "invoice_date") or \
                           get_actual_column_name(cursor, t_name, "date")
                if date_col:
                    try:
                        cursor.execute(f"SELECT DISTINCT YEAR({date_col}) as yr FROM {t_name} WHERE {date_col} IS NOT NULL ORDER BY yr ASC")
                        res_yrs = [int(r["yr"]) for r in cursor.fetchall() if r["yr"]]
                        
                        cursor.execute(f"SELECT DISTINCT MONTHNAME({date_col}) as m_name, MONTH({date_col}) as m_num FROM {t_name} WHERE {date_col} IS NOT NULL ORDER BY m_num ASC")
                        res_mths = [r["m_name"] for r in cursor.fetchall() if r["m_name"]]
                        
                        if res_yrs or res_mths:
                            filters_data["years"] = res_yrs
                            filters_data["months"] = res_mths
                            break
                    except Exception as e:
                        print(f"Error fetching dates from {t_name}: {e}")
                
        # Debug info
        debug_info = {
            "tables_scanned": len(tables) if row else 0,
        }

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
        if conn and conn.is_connected():
            conn.close()



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
            "zone": ["Zone", "zone"],
            "invoice_value": ["Invoice_Value", "invoice_value", "Taxable_Value", "taxable_value", "Invoice_Value_INR"]
        }
        optional_dims = {}
        if has_valid_filters(selected_years) or has_valid_filters(selected_months):
            optional_dims["invoice_date"] = ["invoice_date", "date", "billing__doc_date"]
        if product_type and product_type.lower() != 'all':
            optional_dims["customer_category"] = ["CATEGORY", "product_category", "category"]
        if vehicle_type and vehicle_type.lower() != 'all':
            optional_dims["vehicle_type"] = ["vehicle_type"]
        if construction_type and construction_type.lower() != 'all':
            optional_dims["construction_type"] = ["CONSTRUCTION", "construction_type", "construction"]
        from_clause, user_db, cols = get_query_context_for_session(cursor, session_id, required_metrics, optional_dims)

        if not from_clause:
            return jsonify({"status": "success", "data": chart_data, "message": "Required metrics (zone, invoice_value) not found in any table."}), 200

        cursor.execute(f"USE `{user_db}`")
        
        actual_zone = cols["zone"]
        actual_invoice_value = cols["invoice_value"]

        actual_invoice_date = cols.get("invoice_date")
        actual_cat = cols.get("customer_category")
        actual_const = cols.get("construction_type")
        actual_tyre = cols.get("vehicle_type")

        where_clauses = [f"{actual_zone} IS NOT NULL", f"{actual_zone} <> ''"]
        params = []

        if product_type and product_type.lower() != 'all' and actual_cat:
            where_clauses.append(f"{actual_cat} = %s")
            params.append(product_type)
                
        if construction_type and construction_type.lower() != 'all' and actual_const:
            where_clauses.append(f"{actual_const} = %s")
            params.append(construction_type)

        if vehicle_type and vehicle_type.lower() != 'all' and actual_tyre:
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
                    ROUND(SUM({actual_invoice_value}), 2) AS sales_value
                FROM {from_clause}
                WHERE {where_sql}
                GROUP BY {actual_zone}
                ORDER BY sales_value DESC
            """
            cursor.execute(query, tuple(params))
            results = cursor.fetchall()
            
            total_sales = sum(float(r['sales_value']) for r in results if r['sales_value'])
            
            for r in results:
                r['name'] = r['zone']
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
            "invoice_value": ["Invoice_Value", "invoice_value", "Taxable_Value", "taxable_value", "Invoice_Value_INR"],
            "invoice_date": ["invoice_date", "date", "billing__doc_date"]
        }
        optional_dims = {}
        if has_valid_filters(selected_zones):
            optional_dims["zone"] = ["Zone", "zone"]
        if has_valid_filters(selected_regions):
            optional_dims["region"] = ["Region", "region"]
        if has_valid_filters(selected_customer_types):
            optional_dims["customer_type"] = ["customer_type", "customer_category", "cust_type", "type"]

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
            
        cursor = conn.cursor(dictionary=True)

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

        # 1. Fetch Years and Months
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_invoice_date = (get_actual_column_name(cursor, t_name, "invoice_date") or 
                                   get_actual_column_name(cursor, t_name, "date") or
                                   get_actual_column_name(cursor, t_name, "billing__doc_date"))
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
                        years = [int(r["yr"]) for r in cursor.fetchall() if r["yr"]]

                        cursor.execute(f"""
                            SELECT DISTINCT MONTHNAME({actual_invoice_date}) as m_name, MONTH({actual_invoice_date}) as m_num
                            FROM {t_name}
                            WHERE {actual_invoice_date} IS NOT NULL
                            ORDER BY m_num ASC
                        """)
                        months = [r["m_name"] for r in cursor.fetchall() if r["m_name"]]
                        if years or months:
                            break
                except Exception as e:
                    print(f"Error fetching dates from {t_name}: {e}")

        # 2. Fetch Zones
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_zone = get_actual_column_name(cursor, t_name, "zone")
            if actual_zone:
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

        # 3. Fetch Regions
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_region = get_actual_column_name(cursor, t_name, "region")
            if actual_region:
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

        # 4. Fetch Customer Types
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_customer_type = (get_actual_column_name(cursor, t_name, "customer_type") or 
                                    get_actual_column_name(cursor, t_name, "customer_category") or 
                                    get_actual_column_name(cursor, t_name, "cust_type") or 
                                    get_actual_column_name(cursor, t_name, "type"))
            if actual_customer_type:
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

        # 5. Fetch Construction Types
        for tbl in tables:
            t_name = f"`{user_db}`.`{tbl}`"
            actual_construction_type = (get_actual_column_name(cursor, t_name, "construction_type") or 
                                        get_actual_column_name(cursor, t_name, "construction"))
            if actual_construction_type:
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
        if conn and conn.is_connected():
            conn.close()

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
        "metric_5": {"label": "Achievement", "value": "42%", "subtext": "Current achievement"},
        "metric_6": {"label": "Sales Target", "value": "800 Cr", "subtext": "Target sales"},
        "metric_7": {"label": "Sales Actual", "value": "334 Cr", "subtext": "Actual sales"},
        "metric_8": {"label": "SAS IN", "value": "951.45 Cr", "subtext": "SAS IN value"},
        "metric_9": {"label": "SAS Variance", "value": "9.44 Cr", "subtext": "Variance"},
        "metric_10": {"label": "Billing Scope", "value": "0 Cr", "subtext": "Billing scope"},
        "metric_11": {"label": "Dealer Spread", "value": "76%", "subtext": "Dealer spread"},
        "metric_12": {"label": "Overdue", "value": "32%", "subtext": "Overdue percentage"},
        "metric_13": {"label": "Exposure", "value": "37%", "subtext": "Exposure percentage"},
        "metric_14": {"label": "Rotation", "value": "0.53", "subtext": "Rotation metric"},
        "metric_15": {"label": "New Dealer", "value": "37", "subtext": "New dealers"},
        "metric_16": {"label": "Attrition", "value": "795", "subtext": "Attrition count"}
    }

    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "Failed to connect to database."}), 500
            
        cursor = conn.cursor(dictionary=True)

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

        table_columns = {}
        for tbl in session_tables:
            try:
                cursor.execute(f"DESCRIBE `{tbl}`")
                cols = cursor.fetchall()
                table_columns[tbl] = {col["Field"].lower(): col["Field"] for col in cols}
            except Exception as e:
                print(f"[Default Metrics] Describe table {tbl} failed: {e}")

        # Find the table that contains invoice_value
        sales_table = None
        for tbl, cols in table_columns.items():
            if (
                "invoice_value" in cols
                or "invoice_value_inr" in cols
                or "taxable_value" in cols
                or "taxable_value_inr" in cols
            ):
                sales_table = tbl
                break

        # Fallback to tbl_name if no table with invoice_value is found
        if not sales_table:
            sales_table = tbl_name

        sales_cols = table_columns.get(sales_table, {})

        if "invoice_value" in sales_cols:
            real_revenue_col = sales_cols["invoice_value"]
            has_revenue = True
        elif "invoice_value_inr" in sales_cols:
            real_revenue_col = sales_cols["invoice_value_inr"]
            has_revenue = True
        elif "taxable_value" in sales_cols:
            real_revenue_col = sales_cols["taxable_value"]
            has_revenue = True
        elif "taxable_value_inr" in sales_cols:
            real_revenue_col = sales_cols["taxable_value_inr"]
            has_revenue = True
        else:
            has_revenue = False

        if has_revenue:
            revenue_expr = f"CAST(REPLACE(TRIM(`{real_revenue_col}`), ',', '') AS DECIMAL(18,2))"
            # For JOIN queries where the sales table has alias 's'
            join_revenue_expr = f"CAST(REPLACE(TRIM(s.`{real_revenue_col}`), ',', '') AS DECIMAL(18,2))"
        else:
            revenue_expr = "0.0"
            join_revenue_expr = "0.0"

        # 1. Total Sales Revenue
        total_revenue = 0.0
        if has_revenue:
            try:
                cursor.execute(f"SELECT SUM({revenue_expr}) AS total_sales_revenue FROM `{sales_table}`")
                total_revenue = cursor.fetchone()["total_sales_revenue"] or 0
            except Exception as rev_err:
                print(f"[Default Metrics] Total revenue query failed: {rev_err}")

        # 2. Top Performing Tyre
        top_tyre = "N/A"
        if has_revenue:
            if "vehicle_type" in sales_cols:
                real_tyre_col = sales_cols["vehicle_type"]
                try:
                    cursor.execute(f"""
                        SELECT
                            `{real_tyre_col}` AS vehicle_type,
                            ROUND(SUM({revenue_expr}), 2) AS revenue
                        FROM `{sales_table}`
                        WHERE `{real_tyre_col}` IS NOT NULL
                          AND `{real_tyre_col}` <> ''
                        GROUP BY `{real_tyre_col}`
                        ORDER BY revenue DESC
                        LIMIT 1
                    """)
                    row = cursor.fetchone()
                    if row:
                        top_tyre = row["vehicle_type"]
                except Exception as tyre_err:
                    print(f"[Default Metrics] Top tyre query failed: {tyre_err}")
            else:
                sku_table = None
                tyre_table = None
                for tbl, cols in table_columns.items():
                    if "matnr" in cols and "tyre_type" in cols:
                        sku_table = tbl
                    if "tyre_type_code" in cols and "tyre_type_name" in cols:
                        tyre_table = tbl

                if sku_table and tyre_table:
                    sales_material = sales_cols["material"]
                    sku_material = table_columns[sku_table]["matnr"]
                    sku_tyre = table_columns[sku_table]["tyre_type"]
                    tyre_code = table_columns[tyre_table]["tyre_type_code"]
                    tyre_name = table_columns[tyre_table]["tyre_type_name"]
                    try:
                        cursor.execute(f"""
                        SELECT
                            t.`{tyre_name}` AS vehicle_type,
                            ROUND(SUM({join_revenue_expr}),2) revenue
                        FROM `{sales_table}` s
                        JOIN `{sku_table}` k
                            ON s.`{sales_material}` = k.`{sku_material}`
                        JOIN `{tyre_table}` t
                            ON k.`{sku_tyre}` = t.`{tyre_code}`
                        GROUP BY t.`{tyre_name}`
                        ORDER BY revenue DESC
                        LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row:
                            top_tyre = row["vehicle_type"]
                    except Exception as tyre_err:
                        print(f"[Default Metrics] Joined top tyre query failed: {tyre_err}")

        # 3. Leading Region
        leading_region = "N/A"
        if has_revenue:
            if "region" in sales_cols:
                real_region_col = sales_cols["region"]
                try:
                    cursor.execute(f"""
                        SELECT
                            `{real_region_col}` AS region,
                            ROUND(SUM({revenue_expr}), 2) AS revenue
                        FROM `{sales_table}`
                        WHERE `{real_region_col}` IS NOT NULL
                          AND `{real_region_col}` <> ''
                        GROUP BY `{real_region_col}`
                        ORDER BY revenue DESC
                        LIMIT 1
                    """)
                    row = cursor.fetchone()
                    if row:
                        leading_region = row["region"]
                except Exception as reg_err:
                    print(f"[Default Metrics] Leading region query failed: {reg_err}")
            else:
                customer_table = None
                territory_table = None
                region_table = None
                for tbl, cols in table_columns.items():
                    if "kunnr" in cols and "territory" in cols:
                        customer_table = tbl
                    elif "territory_code" in cols and "region_code" in cols:
                        territory_table = tbl
                    elif "region" in cols and "region_name" in cols:
                        region_table = tbl

                if customer_table and territory_table and region_table:
                    sales_customer = sales_cols["customer"]
                    cust_id = table_columns[customer_table]["kunnr"]
                    cust_territory = table_columns[customer_table]["territory"]
                    terr_code = table_columns[territory_table]["territory_code"]
                    terr_region = table_columns[territory_table]["region_code"]
                    region_code = table_columns[region_table]["region"]
                    region_name = table_columns[region_table]["region_name"]
                    try:
                        cursor.execute(f"""
                        SELECT
                            r.`{region_name}` AS region_name,
                            ROUND(SUM({join_revenue_expr}),2) revenue
                        FROM `{sales_table}` s
                        JOIN `{customer_table}` c
                            ON s.`{sales_customer}` = c.`{cust_id}`
                        JOIN `{territory_table}` t
                            ON c.`{cust_territory}` = t.`{terr_code}`
                        JOIN `{region_table}` r
                            ON t.`{terr_region}` = r.`{region_code}`
                        GROUP BY r.`{region_name}`
                        ORDER BY revenue DESC
                        LIMIT 1
                        """)
                        row = cursor.fetchone()
                        if row:
                            leading_region = row["region_name"]
                    except Exception as reg_err:
                        print(f"[Default Metrics] Joined region query failed: {reg_err}")

        # 4. YoY Growth
        current_year = 0.0
        previous_year = 0.0
        yoy = 0.0
        real_date_col = None

        if "invoice_date" in sales_cols:
            real_date_col = sales_cols["invoice_date"]
        elif "billing__doc_date" in sales_cols:
            real_date_col = sales_cols["billing__doc_date"]
        elif "date" in sales_cols:
            real_date_col = sales_cols["date"]

        if has_revenue and real_date_col:
            try:
                # Detect column type to decide date parsing strategy
                cursor.execute(f"SHOW COLUMNS FROM `{sales_table}` LIKE %s", (real_date_col,))
                col_info = cursor.fetchone()
                col_type = col_info["Type"].lower() if col_info else "text"

                if "date" in col_type or "timestamp" in col_type:
                    year_expr = f"YEAR(`{real_date_col}`)"
                    date_filter = f"`{real_date_col}` IS NOT NULL"
                else:
                    year_expr = f"YEAR(STR_TO_DATE(`{real_date_col}`, '%d-%m-%Y'))"
                    date_filter = f"`{real_date_col}` IS NOT NULL AND `{real_date_col}` != ''"

                # Current Year Revenue
                cursor.execute(f"""
                    SELECT ROUND(SUM({revenue_expr}), 2) AS revenue
                    FROM `{sales_table}`
                    WHERE {date_filter}
                      AND {year_expr} = YEAR(CURDATE())
                """)
                curr_row = cursor.fetchone()
                current_year = float(curr_row["revenue"] or 0) if curr_row else 0.0

                # Previous Year Revenue
                cursor.execute(f"""
                    SELECT ROUND(SUM({revenue_expr}), 2) AS revenue
                    FROM `{sales_table}`
                    WHERE {date_filter}
                      AND {year_expr} = YEAR(CURDATE()) - 1
                """)
                prev_row = cursor.fetchone()
                previous_year = float(prev_row["revenue"] or 0) if prev_row else 0.0

                if previous_year > 0:
                    yoy = round(((current_year - previous_year) / previous_year) * 100, 2)
            except Exception as yoy_err:
                print(f"[Default Metrics] YoY query failed: {yoy_err}")

        # 5. Billing Scope
        billing_scope = "N/A"
        real_cust_col_sales = None
        if "customer" in sales_cols:
            real_cust_col_sales = sales_cols["customer"]
        elif "kunnr" in sales_cols:
            real_cust_col_sales = sales_cols["kunnr"]
        
        if real_cust_col_sales:
            try:
                cursor.execute(f"SELECT COUNT(DISTINCT `{real_cust_col_sales}`) AS count FROM `{sales_table}`")
                row = cursor.fetchone()
                if row and row["count"] is not None:
                    billing_scope = str(row["count"])
            except Exception as e:
                print(f"[Default Metrics] Billing scope query failed: {e}")

        # 6. Dealer Spread
        dealer_spread = "N/A"
        customer_table = None
        for tbl, cols in table_columns.items():
            if "kunnr" in cols and "acc_grp" in cols:
                customer_table = tbl
                break
        
        if real_cust_col_sales and customer_table:
            cust_id_col = table_columns[customer_table]["kunnr"]
            acc_grp_col = table_columns[customer_table]["acc_grp"]
            try:
                cursor.execute(f"""
                    SELECT COUNT(DISTINCT s.`{real_cust_col_sales}`) AS count
                    FROM `{sales_table}` s
                    JOIN `{customer_table}` c ON s.`{real_cust_col_sales}` = c.`{cust_id_col}`
                    WHERE c.`{acc_grp_col}` = 'Z001'
                """)
                row = cursor.fetchone()
                if row and row["count"] is not None:
                    dealer_spread = str(row["count"])
            except Exception as e:
                print(f"[Default Metrics] Dealer spread query failed: {e}")

        # 7. Attrition
        attrition = "N/A"
        if real_cust_col_sales and real_date_col:
            try:
                if "date" in col_type or "timestamp" in col_type:
                    date_expr = f"`{real_date_col}`"
                else:
                    date_expr = f"STR_TO_DATE(`{real_date_col}`, '%d-%m-%Y')"
                    
                cursor.execute(f"""
                    SELECT COUNT(DISTINCT prev_month_cust) AS attrition_count
                    FROM (
                        SELECT DISTINCT `{real_cust_col_sales}` AS prev_month_cust
                        FROM `{sales_table}`
                        WHERE {date_expr} >= DATE_FORMAT(CURRENT_DATE - INTERVAL 1 MONTH, '%Y-%m-01')
                          AND {date_expr} < DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
                    ) AS prev
                    WHERE prev_month_cust NOT IN (
                        SELECT DISTINCT `{real_cust_col_sales}`
                        FROM `{sales_table}`
                        WHERE {date_expr} >= DATE_FORMAT(CURRENT_DATE, '%Y-%m-01')
                    )
                """)
                row = cursor.fetchone()
                if row and row["attrition_count"] is not None:
                    attrition = str(row["attrition_count"])
            except Exception as e:
                print(f"[Default Metrics] Attrition query failed: {e}")

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
                "value": f"{yoy}%" if (current_year > 0 or previous_year > 0) else "N/A", 
                "subtext": "Compared to last year" if (current_year > 0 or previous_year > 0) else "No data available"
            },
            "metric_5": {"label": "Achievement", "value": "N/A", "subtext": "Current achievement"},
            "metric_6": {"label": "Sales Target", "value": "N/A", "subtext": "Target sales"},
            "metric_7": {"label": "Sales Actual", "value": formatted_revenue, "subtext": "Actual sales"},
            "metric_8": {"label": "SAS IN", "value": "N/A", "subtext": "SAS IN value"},
            "metric_9": {"label": "SAS Variance", "value": "N/A", "subtext": "Variance"},
            "metric_10": {"label": "Billing Scope", "value": billing_scope, "subtext": "Customers billed"},
            "metric_11": {"label": "Dealer Spread", "value": dealer_spread, "subtext": "Active dealers"},
            "metric_12": {"label": "Overdue", "value": "N/A", "subtext": "Overdue percentage"},
            "metric_13": {"label": "Exposure", "value": "N/A", "subtext": "Exposure percentage"},
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
            cursor.close()
        if conn and conn.is_connected():
            conn.close()