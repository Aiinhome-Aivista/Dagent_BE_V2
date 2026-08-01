import hashlib
import re
import json
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
from helper.dynamic_profiler import get_table_aggregates


# pyrefly: ignore [missing-import]
from pyvis.network import Network
import os
import uuid
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
    # db_summary = {}
    # for db in db_data:
    #     for tbl in db["tables"]:
    #         entry = {}
    #         for col, stats in tbl.get("column_stats", {}).items():
    #             entry[col] = stats.get("sample", [])[:10]
    #         db_summary[tbl["table_name"]] = entry
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

    prompt = f"""
You are an expert Knowledge Graph Builder specializing in tyre and automotive parts distribution data.

Analyze the uploaded sales dataset and generate a RICH, HIERARCHICAL, business-focused Knowledge Graph.
The graph MUST reflect the full product taxonomy AND all business relationships visible in the data from the 9 Master tables and 3 Fact tables.

## DB Tables and Sample Data:
{json.dumps(db_summary, indent=2)}

## Web Data:
{json.dumps(web_summary, indent=2)}

---

## MANDATORY GRAPH STRUCTURE

### LEVEL 1 — Product Category Nodes (from Category Master)
Create one node per unique category found in the data (e.g., Tyre, Tube, Flap).
Node type: "ProductCategory"

### LEVEL 2 — Construction Nodes (from Construction Master)
Create one node per unique construction type (e.g., BIAS, RADIAL).
Node type: "Construction"

### LEVEL 3 — Tyre/Vehicle Type Nodes (from Tyre Type Master)
Create one node per unique vehicle/application type (e.g., TRUCK, LCV, CAR, 3W, SCV).
Node type: "TyreType"

### LEVEL 4 — SKU/Material Nodes (from SKU Master)
Identify the TOP 15 most frequently appearing SKUs/Materials in the sales data.
Node type: "SKU"

### LEVEL 5 — Customer/Dealer Nodes (from Customer Master)
Identify the TOP 15 most frequently appearing customers in the sales data.
Node type: "Customer"

### LEVEL 6 — Customer Class Nodes (from Class Master)
Create one node for each customer class (e.g., A, B, C, D).
Node type: "CustomerClass"

### LEVEL 7 — Account Group Nodes (from Account Group Master)
Create one node for each account group (e.g., ZOR, Z1).
Node type: "AccountGroup"

### LEVEL 8 — Geography Nodes (from Region & Territory Masters)
Create nodes for Zone, Region, and Territory based on the data.
Node types: "Zone", "Region", "Territory"

### LEVEL 9 — Billing/Channel Type Nodes (from Fact Tables)
Create nodes for each billing distribution channel (e.g., ZOR, ZBCL, ZCC).
Node type: "BillingChannel"


## MANDATORY EDGES (Only create if supported by data)

1. PRODUCT HIERARCHY
   - (ProductCategory) --[HAS_CONSTRUCTION]--> (Construction)
   - (Construction) --[FITS_TYRE_TYPE]--> (TyreType)
   - (SKU) --[BELONGS_TO_CATEGORY]--> (ProductCategory)
   - (SKU) --[HAS_CONSTRUCTION_TYPE]--> (Construction)
   - (SKU) --[USED_IN]--> (TyreType)

2. CUSTOMER & GEOGRAPHY HIERARCHY
   - (Zone) --[CONTAINS_REGION]--> (Region)
   - (Region) --[CONTAINS_TERRITORY]--> (Territory)
   - (Territory) --[HAS_CUSTOMER]--> (Customer)
   - (Customer) --[HAS_CLASS]--> (CustomerClass)
   - (Customer) --[BELONGS_TO_ACCOUNT_GROUP]--> (AccountGroup)

3. FACT / TRANSACTION EDGES (Linking Customer to Material via Sales Data)
   - (Customer) --[PURCHASED]--> (SKU)
   - (Customer) --[PRIMARILY_BUYS]--> (ProductCategory)
   - (ProductCategory) --[SOLD_VIA]--> (BillingChannel)

---

## NUMERICAL PROPERTIES (store as node/edge properties, NEVER as separate nodes)
- On ProductCategory / SKU nodes: total_sales_qty, total_invoice_value, total_discount
- On Customer nodes: total_invoice_value, total_claims
- On PURCHASED edges: transaction_count, total_invoice_value, total_qty

---

## OUTPUT FORMAT
Return EXACTLY this JSON (no markdown, no extra text):
{{
  "nodes": [
    {{"id": "cat_tyre", "label": "Tyre", "type": "ProductCategory", "properties": {{"total_invoice_value": 0}}}},
    {{"id": "const_bias", "label": "BIAS", "type": "Construction", "properties": {{}}}},
    {{"id": "tt_truck", "label": "TRUCK", "type": "TyreType", "properties": {{}}}},
    {{"id": "sku_1001", "label": "1001-TYRE", "type": "SKU", "properties": {{}}}},
    {{"id": "cust_99", "label": "CUST 99", "type": "Customer", "properties": {{}}}},
    {{"id": "cls_A", "label": "Class A", "type": "CustomerClass", "properties": {{}}}},
    {{"id": "acc_z1", "label": "Z1 Group", "type": "AccountGroup", "properties": {{}}}},
    {{"id": "zone_central", "label": "Central", "type": "Zone", "properties": {{}}}},
    {{"id": "reg_jaipur", "label": "JAIPUR", "type": "Region", "properties": {{}}}},
    {{"id": "ter_north", "label": "North Terr", "type": "Territory", "properties": {{}}}},
    {{"id": "ch_zor", "label": "ZOR", "type": "BillingChannel", "properties": {{}}}}
  ],
  "edges": [
    {{"from": "cat_tyre", "to": "const_bias", "label": "HAS_CONSTRUCTION", "properties": {{}}}},
    {{"from": "sku_1001", "to": "cat_tyre", "label": "BELONGS_TO_CATEGORY", "properties": {{}}}},
    {{"from": "cust_99", "to": "sku_1001", "label": "PURCHASED", "properties": {{"total_invoice_value": 50000}}}},
    {{"from": "zone_central", "to": "reg_jaipur", "label": "CONTAINS_REGION", "properties": {{}}}},
    {{"from": "reg_jaipur", "to": "ter_north", "label": "CONTAINS_TERRITORY", "properties": {{}}}},
    {{"from": "ter_north", "to": "cust_99", "label": "HAS_CUSTOMER", "properties": {{}}}},
    {{"from": "cust_99", "to": "cls_A", "label": "HAS_CLASS", "properties": {{}}}},
    {{"from": "cust_99", "to": "acc_z1", "label": "BELONGS_TO_ACCOUNT_GROUP", "properties": {{}}}}
  ],
  "identified_node_types": ["ProductCategory", "Construction", "TyreType", "SKU", "Customer", "CustomerClass", "AccountGroup", "Zone", "Region", "Territory", "BillingChannel"],
  "identified_relationship_types": ["HAS_CONSTRUCTION", "FITS_TYRE_TYPE", "BELONGS_TO_CATEGORY", "HAS_CONSTRUCTION_TYPE", "USED_IN", "CONTAINS_REGION", "CONTAINS_TERRITORY", "HAS_CUSTOMER", "HAS_CLASS", "BELONGS_TO_ACCOUNT_GROUP", "PURCHASED", "PRIMARILY_BUYS", "SOLD_VIA"],
  "graph_schema": [
    "(Customer)-[:PURCHASED]->(SKU)",
    "(SKU)-[:BELONGS_TO_CATEGORY]->(ProductCategory)",
    "(Territory)-[:HAS_CUSTOMER]->(Customer)"
  ],
  "sample_cypher_queries": [
    "MATCH (c:Customer)-[p:PURCHASED]->(s:SKU) RETURN c.label, s.label, p.total_invoice_value ORDER BY p.total_invoice_value DESC LIMIT 10",
    "MATCH (t:Territory)-[:HAS_CUSTOMER]->(c:Customer) RETURN t.label, count(c) as customer_count"
  ],
  "business_insights": [
    "Identify any insights based on the relationship between Customer Classes and Top SKUs",
    "Identify top regions based on Customer purchases"
  ],
  "suggested_graphrag_paths": [
    "Start from Customer → PURCHASED → SKU → BELONGS_TO_CATEGORY → ProductCategory",
    "Start from Zone → CONTAINS_REGION → Region → CONTAINS_TERRITORY → Territory → HAS_CUSTOMER → Customer"
  ]
}}

## RULES
1. Use ONLY node IDs you defined in the "nodes" array for "from"/"to" in edges.
2. Extract actual values from the sample data — do NOT invent SKU codes or customer IDs.
3. Node IDs must be unique strings with no spaces (use underscores).
4. For nodes like Customer, SKU, limit to the top 15 most frequent/significant ones from the sample to avoid overwhelming the graph, but capture all master table reference nodes (like Category, Construction, Region, etc.).
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

def generate_session_graph(session_id, web_data, db_data, target_arango_db=None):

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
        _sync_to_arango(session_id, net.nodes, net.edges, target_arango_db)
    except Exception as e:
        print(f"[ArangoDB] Sync failed: {e}")

    return f"{BASE_URL}/graphs/{html_filename}"

# ══════════════════════════════════════════════════════
# ARANGODB SYNC
# ══════════════════════════════════════════════════════

def _safe_key(val: str) -> str:
    """ArangoDB _key allows only [a-zA-Z0-9_:.@()-]+"""
    return re.sub(r'[^a-zA-Z0-9_:.@()-]', '_', str(val))

def _sync_to_arango(session_id: str, nodes: list, edges: list, target_arango_db: str = None):
    print(f"[ArangoDB] Connecting to {ARANGO_HOST} ...")
    client = ArangoClient(hosts=ARANGO_HOST)
    sys_db = client.db('_system', username=ARANGO_USER, password=ARANGO_PASS)

    db_to_use = target_arango_db if target_arango_db else ARANGO_DB

    # Ensure database exists
    if not sys_db.has_database(db_to_use):
        sys_db.create_database(db_to_use)
    
    db = client.db(db_to_use, username=ARANGO_USER, password=ARANGO_PASS)

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


def _fetch_agentic_insights(cursor, tables_info: list, db_type: str) -> list:
    """
    Agentic Workflow:
    1. Sends schema to LLM and asks for 7-10 comprehensive business SQL queries.
    2. Executes the queries.
    3. Returns the successful results as a list of strings.
    """
    if not tables_info:
        return []
        
    schema_desc = []
    for t in tables_info:
        schema_desc.append(f"Table: {t['table_name']}")
        schema_desc.append(f"Columns: {', '.join(t['columns'])}")
    schema_str = "\n".join(schema_desc)
    
#     system_prompt = f"""You are an expert Data Analyst and {db_type.upper()} DBA.
# Your task is to write EXACTLY 8 to 12 advanced SQL queries that will extract the most critical business metrics from the provided schema.

# BUSINESS KPI CALCULATION LOGIC
    system_prompt = f"""You are an expert Data Analyst and {db_type.upper()} DBA.
Your task is to write advanced SQL queries that extract the most critical business metrics from the provided schema.

MANDATORY COVERAGE — write ONE query for EACH of the 8 numbered sections below, in order,
even if you also add supporting queries. Do not skip a section because it seems less
important — a missing query is what causes that section to show "N/A" in the final report.
After the 8 mandatory queries, you may add up to 4 more (e.g. Top-5/Bottom-5 products,
Dealer/Fleet/OEM split) for a total of 8 to 12 queries.

BUSINESS KPI CALCULATION LOGIC

Always use the following joins. Several join keys have MISMATCHED COLUMN TYPES between tables
(one side bigint/int, the other text) — always wrap the text side in CAST(... AS UNSIGNED) or
the numeric side in CAST(... AS CHAR) so the join is explicit and doesn't rely on implicit coercion:

sales_data.customer = customer_master.KUNNR
customer_master.acc_grp = account_group_master.KTOKD
customer_master.class = class_master.class_code
customer_master.territory = CAST(territory_master.territory_code AS UNSIGNED)          -- type mismatch: bigint vs text
CAST(territory_master.region_code AS UNSIGNED) = region_master.region                    -- type mismatch: text vs bigint
region_master.zone                                                                       -- ZONE lives here — always surface it, see RULE below

sales_data.material = sku_master.MATNR
sku_master.category = category_master.category_code
sku_master.construction = CAST(construction_master.construction_code AS UNSIGNED)       -- type mismatch: bigint vs text
sku_master.tyre_type = tyre_type_master.tyre_type_code

sales_data.distribution__Channel = distribution_mapping.distribution_code
sales_target.MATNR = sku_master.MATNR
sales_target.Terr_Code = territory_master.territory_code                                 -- NEW: both text, direct match — wire this up for Target-by-Territory/Region/Zone
DATE_FORMAT(sales_data.billing__doc_date, '%Y%m') = CAST(sales_target.Month AS CHAR)      -- NEW: required to compare Target vs Actual by month; sales_target.Month is bigint in YYYYMM form

Never display IDs or codes. Always return descriptive names from the master tables.

OPTIONAL: `report_business_mapping` (report_row, brand, tyre_type, construction, distribution,
account_group, remarks) is available for canonical report-row/brand rollups. Only join to it
when a query specifically needs a standardized report_row grouping — don't force it into every query.

=====================================================
1. Overall Performance
=====================================================
Total Revenue = SUM(sales_data.Invoice_Value_INR)
Total Quantity = SUM(sales_data.Sales_Qty)
Total Transactions = COUNT(*)
Average Transaction Value = SUM(Invoice_Value_INR) / COUNT(*)

=====================================================
2. Revenue Trend
=====================================================
GROUP BY DATE_FORMAT(billing__doc_date, '%Y-%m')
Highest Sales Month = month with highest SUM(Invoice_Value_INR)
Lowest Sales Month  = month with lowest SUM(Invoice_Value_INR)

=====================================================
3. Product Performance
=====================================================
Join sales_data -> sku_master -> category_master -> construction_master -> tyre_type_master
(remember the construction CAST above)
Top Category = Category having highest SUM(Invoice_Value_INR)
Top Construction = Construction having highest SUM(Invoice_Value_INR)
Top Tyre Type = Tyre Type having highest SUM(Invoice_Value_INR)
Top 5 Products = ORDER BY Revenue DESC LIMIT 5
Bottom 5 Products = ORDER BY Revenue ASC LIMIT 5

=====================================================
4. Customer Performance
=====================================================
Join sales_data -> customer_master -> account_group_master
Top Customers = Customers ranked by SUM(Invoice_Value_INR) LIMIT 5
NOTE: If sales_data.customer has no matching row in customer_master, do NOT silently drop it
via INNER JOIN — use LEFT JOIN and label it "Unmapped Account (<code>)" so concentration
metrics aren't understated by excluding unmapped high-revenue codes.

=====================================================
5. Geography
=====================================================
Join customer_master -> territory_master -> region_master (remember the CASTs above)
Top Zone = Zone (region_master.zone) having highest Revenue        -- ALWAYS include a zone-level query, this was previously missing
Top Region = Region having highest Revenue
Top Territory = Territory having highest Revenue

=====================================================
6. Distribution Analysis
=====================================================
Join distribution_mapping
Group By distribution_name
For each Distribution Channel: Revenue = SUM(Invoice_Value_INR), Quantity = SUM(Sales_Qty)

=====================================================
7. Pricing Analysis
=====================================================
Average Selling Price = SUM(Invoice_Value_INR) / SUM(Sales_Qty)
Claim Quantity = SUM(Claim_Qty)
Claim Amount = SUM(NDP_CLAIM_INR)
Return Quantity = SUM(Return_Qty)

=====================================================
8. Target Performance
=====================================================
Join sales_target -> sku_master (MATNR), sales_target -> territory_master (Terr_Code),
and correlate sales_target.Month against DATE_FORMAT(sales_data.billing__doc_date,'%Y%m')
as shown above.
Target = SUM(sales_target.Value) [and/or SUM(sales_target.Qty) for volume target]
Actual = SUM(sales_data.Invoice_Value_INR) for the matching MATNR + month (+ territory if scoping by geography)
Achievement % = Actual / Target * 100
Gap = Actual - Target
=====================================================
GENERAL RULES
=====================================================
- Always use Invoice_Value_INR for revenue calculations.
- Always use Sales_Qty for quantity calculations.
- Always use billing__doc_date for all date filtering (already a DATE column — no parsing needed).
- Always return names from master tables instead of IDs.
- Use LEFT JOIN (not INNER JOIN) when resolving names, and use COALESCE() to label unmatched
  codes explicitly (e.g. "Unmapped Account") rather than dropping those rows.
- Cast mismatched join key types explicitly (see CASTs above) — do not rely on implicit coercion.
- GROUP BY CORRECTNESS (critical): every non-aggregated column you SELECT (e.g. sku_master.MAKTX,
  customer_master.Cname, region_master.zone) MUST also appear in that query's GROUP BY clause.
  Never SELECT a descriptive name column next to SUM(...)/COUNT(...) without grouping by that
  same column — doing so lets the database pick an arbitrary or NULL value for the name while
  still summing across ALL rows, producing a single fake row like "None: ₹9,677 million" that
  silently absorbs nearly the whole table's revenue instead of a real top product/customer/region.
  Before finalizing each query, check: does every non-aggregate item in SELECT also appear in
  GROUP BY? If not, fix it.
- Generate optimized MySQL 8+ queries.

Respond ONLY with a valid JSON array of strings containing the SQL queries."""

    user_prompt = f"Schema:\n{schema_str}\nGenerate the JSON array of queries."
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    insights = []
    try:
        content_str = call_llm_chat(messages, json_mode=True, temperature=0.1)
        queries = json.loads(content_str)
        if not isinstance(queries, list):
            return insights
            
    #     for i, query in enumerate(queries, 1):
    #         query = query.strip()
    #         if not query.lower().startswith("select"):
    #             continue
    #         try:
    #             cursor.execute(query)
    #             rows = cursor.fetchall()
    #             if rows:
    #                 insights.append(f"--- Insight Query {i} ---")
    #                 insights.append(f"Query: {query}")
    #                 for row in rows:
    #                     row_str = " | ".join(f"{k}: {v}" for k, v in row.items())
    #                     insights.append(f"  {row_str}")
    #         except Exception as e:
    #             print(f"[Agentic Helper] Query failed: {query}. Error: {e}")
                
    # except Exception as e:
    #     print(f"[Agentic Helper] LLM call failed: {e}")
        BLOCKED_KEYWORDS = ("into outfile", "into dumpfile", "load_file", "load data")

        for i, query in enumerate(queries, 1):
            query = query.strip().rstrip(";")
            q_lower = query.lower()

            if not q_lower.startswith("select"):
                continue
            if ";" in query:                          # reject any embedded multi-statement
                print(f"[Agentic Helper] Rejected multi-statement query: {query}")
                continue
            if any(kw in q_lower for kw in BLOCKED_KEYWORDS):
                print(f"[Agentic Helper] Rejected unsafe query: {query}")
                continue

            try:
                cursor.execute(query)
                rows = cursor.fetchall()[:MAX_ROWS]   # cap rows fed into context
                if rows:
                    insights.append(f"--- Insight Query {i} ---")
                    insights.append(f"Query: {query}")
                    for row in rows:
                        row_str = " | ".join(f"{k}: {v}" for k, v in row.items())
                        insights.append(f"  {row_str}")
            except Exception as e:
                print(f"[Agentic Helper] Query failed: {query}. Error: {e}")
                
    except Exception as e:
        print(f"[Agentic Helper] LLM call failed: {e}")
        
    return insights


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
                new_user_db = r["new_user_db"]
                if new_user_db not in db_map:
                    db_map[new_user_db] = {"external_databases": [], "tables": []}
                ext_db = r["external_database"]
                if ext_db not in db_map[new_user_db]["external_databases"]:
                    db_map[new_user_db]["external_databases"].append(ext_db)
                if r.get("table_name"):
                    db_map[new_user_db]["tables"].append(r["table_name"])
            print(f"[Analysis] MySQL DB MAP -> {db_map}")
    except Exception as e:
        print(f"[Analysis] db_map error: {e}")
    finally:
        if cursor: cursor.close()

    for new_db, db_info in db_map.items():
        allowed_tables = db_info["tables"]
        ext_dbs_str = ", ".join(db_info["external_databases"])

        db_result = {
            "source_type":       "database",
            "external_database": ext_dbs_str,
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
                
            print(f"[Analysis] Tables in {new_db} -> {tables}")

            for t in tables:
                try:
                    ext_cur.execute(f"SELECT * FROM `{t}` LIMIT 0")
                    ext_cur.fetchall()
                    cols = [desc[0] for desc in ext_cur.description]
                    
                    db_result["tables"].append({
                        "table_name":   t,
                        "columns":      cols,
                        "business_aggregates": get_table_aggregates(ext_cur, t)
                    })
                except Exception as table_error:
                    print(f"[Analysis] MySQL table {t} error -> {table_error}")
            
            # [NEW] Fetch agentic insights
            db_result["executed_insights"] = _fetch_agentic_insights(ext_cur, db_result["tables"], "mysql")

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

            pg_conn = None
            pg_cur = None
            try:
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
                            pg_cur.execute(f'SELECT * FROM "{schema}"."{t}" LIMIT 0')
                            pg_cur.fetchall()
                            cols = [desc.name for desc in pg_cur.description]

                            db_result["tables"].append({
                                "table_name":   qualified,
                                "columns":      cols,
                                "business_aggregates": get_table_aggregates(pg_cur, qualified)
                            })
                            print(f"[Analysis] PG {pg_database}.{qualified}: schema loaded")

                        except Exception as te:
                            print(f"[Analysis] PG skip {qualified}: {te}")
                            pg_conn.rollback()

                # [NEW] Execute Agentic Workflow
                db_result["executed_insights"] = _fetch_agentic_insights(pg_cur, db_result["tables"], "postgresql")

                results.append(db_result)

            except Exception as e:
                print(f"[Analysis] PostgreSQL connect error: {e}")
            finally:
                if pg_cur:
                    try: pg_cur.close()
                    except: pass
                if pg_conn:
                    try: pg_conn.close()
                    except: pass
        except Exception as outer_e:
            print(f"[Analysis] Outer PostgreSQL block error: {outer_e}")

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
            lines.append(f"\n  Table: {tbl['table_name']}")
            
            if tbl.get("business_aggregates"):
                lines.append("  [CRITICAL ACTUAL BUSINESS TOTALS (ENTIRE TABLE)]:")
                for agg in tbl["business_aggregates"]:
                    lines.append(f"    - {agg}")

            lines.append(f"  Columns: {', '.join(tbl['columns'])}")
                
        if d.get("executed_insights"):
            lines.append("\n=== CRITICAL EXECUTED INSIGHTS ===")
            lines.extend(d["executed_insights"])
            
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

    # system = """ IQ200 You are an expert business analyst and strategist.
    system = """You are an expert business analyst and strategist.
Your task is to analyze the provided sales data of different types of tyres, tubes, Ret read Belt, Vul Solutions, flap  and extract purely business-focused insights and context.
CRITICAL INSTRUCTIONS:
1. Do NOT include ANY technical details (e.g., table names, column names, row counts, distinct values, data types, schema info, missing values, database structure).
2. STRICT ANTI-HALLUCINATION RULE: Use ONLY actual numbers and facts explicitly provided in the context. If you see a specific entity name in the sample rows, DO NOT invent transaction counts or revenue for them unless those specific numbers are explicitly written next to their name in the CRITICAL CROSS-TABLE INSIGHTS or Aggregates. If you don't have the exact number, state the trend generally or omit the number.
3. Pay SPECIAL ATTENTION to the "CRITICAL EXECUTED INSIGHTS" block. This contains the exact mathematical results of dynamic SQL queries executed directly against the database. Use ONLY these results to form the quantitative basis of your summary.
4. Identify the key business trends, top performers, and overall performance metrics explicitly found in the executed insights or table totals.
5. The report must dynamically adapt to the executed queries and focus purely on actionable business insights, performance, and trends.
6. Use Descriptive Names: ALWAYS map and use descriptive names instead of raw IDs or codes (e.g., use category_name instead of category_code, customer Cname instead of KUNNR, region_name instead of region_code). Raw IDs make the report difficult to read for business users.
7. Date Formatting: The 'Month' column or any period formatted as YYYYMM (e.g., 202601, 202512) must be translated into readable month names (e.g., 'January 2026', 'December 2025') in your report.
8. Respond ONLY in valid JSON with a single key: "report".
"""

    user = f"""
Analyze the strictly provided business data ({'; '.join(source_desc)}):

{context}

Generate a detailed, purely business-focused summary highlighting key insights. 
ALSO, generate exactly 5 "What" critical questions about the data.
ALSO, generate a category-wise trend report as a "line_chart" visualization extracting numeric/categorical trend values.

Return ONLY this JSON:
{{
  "report": "TITLE: <Create a descriptive business-focused title based on the data>\\n\\n### Executive Summary\\n<Write exactly 5 to 8 lines summarizing overall business performance, key trends, and main takeaways based purely on the data.>\\n\\n### Key Business Insights\\n\\n**1. Overall Performance**\\n- **Total Revenue**: <Value>\\n- **Total Quantity**: <Value>\\n- **Total Invoices**: <Value>\\n- **Average Invoice Value**: <Value>\\n\\n**2. Revenue Trend**\\n- **Highest Sales Month**: <Value>\\n- **Lowest Sales Month**: <Value>\\n- **Monthly Growth**: <Value>\\n\\n**3. Product Performance**\\n- **Top Category**: <Value>\\n- **Top Construction**: <Value>\\n- **Top Tyre Type**: <Value>\\n- **Top Product**: <Value>\\n- **Lowest Selling Product**: <Value>\\n\\n**4. Customer Performance**\\n- **Top Customers**: <Value>\\n- **Dealer Contribution**: <Value>\\n- **Fleet Contribution**: <Value>\\n- **OEM Contribution**: <Value>\\n- **Customer Concentration**: <Value>\\n\\n**5. Geography**\\n- **Top Zone**: <Value>\\n- **Top Region**: <Value>\\n- **Top Territory**: <Value>\\n- **Lowest Territory**: <Value>\\n\\n**6. Distribution**\\n- **Replacement**: <Value>\\n- **OEM**: <Value>\\n- **STU**: <Value>\\n- **DEF**: <Value>\\n- **Contribution %**: <Value>\\n\\n**7. Pricing**\\n- **Average Selling Price**: <Value>\\n- **Discount %**: <Value>\\n- **Claims**: <Value>\\n- **Returns**: <Value>\\n\\n**8. Target Performance (if available)**\\n- **Target**: <Value>\\n- **Actual**: <Value>\\n- **Achievement %**: <Value>\\n- **Gap**: <Value>\\n- **MTD / YTD / YOY**: <Value>\\n\\n### Business Risks\\n- <Data-driven Risk 1 (e.g. High customer concentration)>\\n- <Data-driven Risk 2 (e.g. High discount dependency)>\\n- <Data-driven Risk 3>\\n\\n### Actionable Recommendations\\n- <Data-driven Recommendation 1 (e.g. Improve sales in low-performing territories)>\\n- <Data-driven Recommendation 2 (e.g. Reduce dependency on top customers)>\\n- <Data-driven Recommendation 3>\\n\\n### Strategic Conclusion\\n<A final strategic conclusion summarizing the path forward for the business.>",
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
- If a specific metric (e.g., Target Performance, OEM Contribution, Highest/Lowest Sales Month, YTD) is not explicitly calculated and available in the provided data, write "N/A based on available data" rather than hallucinating or guessing based on overall date ranges. Keep the bullet structure intact.
- Use \\n for newlines inside the JSON string.
- Every point must reference a specific value, name, or number from the actual data. DO NOT INVENT NUMBERS for entities just to fulfill this rule.
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
        
        target_arango_db = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT workspace_arango_db FROM workspaces WHERE session_id = %s", (session_id,))
            row = cursor.fetchone()
            if row and row.get("workspace_arango_db"):
                target_arango_db = row["workspace_arango_db"]
            cursor.close()
        except Exception as e:
            print(f"[Analysis] DB fetch target_arango_db error: {e}")

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
                            "columns":     t["columns"]
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

        # # 5. Cache MISS or STALE — generate fresh
        # analysis  = _call_mistral(context, topics, databases)
        # graph_url = generate_session_graph(session_id, web_data, db_data, target_arango_db)

        # if not analysis:
        #     return jsonify({
        #         "status":     "partial",
        #         "statusCode": 200,
        #         "message":    "LLM analysis failed.",
        #     }), 200
        # 5. Cache MISS or STALE — generate fresh
        analysis  = _call_mistral(context, topics, databases)
        graph_url = generate_session_graph(session_id, web_data, db_data, target_arango_db)

        if not analysis:
            return jsonify({
                "status":     "partial",
                "statusCode": 200,
                "message":    "LLM analysis failed.",
                "graph_url":  graph_url,
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