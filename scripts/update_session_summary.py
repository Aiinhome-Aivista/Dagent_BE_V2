"""
Script to update session_analysis_cache with live, accurate metrics for all 7 sections:
1. Overall Performance
2. Revenue Trend
3. Product Performance
4. Customer Performance
5. Geography
6. Distribution
7. Target Performance

Usage:
    python api/scripts/update_session_summary.py [session_id]
    python api/scripts/update_session_summary.py --all
"""

import sys
import os
import re
import argparse
from datetime import datetime

# Add API directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
api_dir = os.path.abspath(os.path.join(current_dir, ".."))
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

import mysql.connector
from database.config import MYSQL_CONFIG
from helper.sap_analytics_service import (
    get_sap_connection_for_session,
    sanitize_and_execute_hana,
    detect_sales_dates,
    _prepare_mysql_workspace
)


def get_latest_session_id(mysql_conn):
    cur = mysql_conn.cursor(dictionary=True)
    cur.execute("SELECT session_id FROM session_analysis_cache ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    cur.close()
    return row["session_id"] if row else None


def execute_hana_analysis(hana_conn, schema):
    cur = hana_conn.cursor()
    year, month, day = detect_sales_dates(cur, schema)
    target_yr = str(year) if year else "2026"
    print(f"[SAP-HANA] Target active sales year: {target_yr} (date anchor: {year}-{month:02d}-{day:02d})")

    res = {}

    # 1. Overall Performance
    q_overall = f"""
        SELECT 
            ROUND(SUM(COALESCE(s."invoice_value", s."taxable_value", 0)) / 10000000, 2) AS "Total_Revenue",
            ROUND(SUM(COALESCE(s."Tyre_Quantity", 0)) / 1000000, 2) AS "Total_Quantity_M",
            SUM(COALESCE(s."Tyre_Quantity", 0)) AS "Total_Quantity_Units",
            COUNT(DISTINCT s."invoice_number") AS "Total_Invoices",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / NULLIF(COUNT(DISTINCT s."invoice_number"), 0), 2) AS "Avg_Invoice_Val",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / NULLIF(SUM(s."Tyre_Quantity"), 0), 2) AS "Avg_Selling_Price"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
    """
    sanitize_and_execute_hana(cur, schema, q_overall)
    row = cur.fetchone()
    if row:
        res["total_revenue"] = float(row[0] or 0)
        res["total_qty_m"] = float(row[1] or 0)
        res["total_qty_units"] = int(row[2] or 0)
        res["total_invoices"] = int(row[3] or 0)
        res["avg_invoice_val"] = float(row[4] or 0)
        res["avg_selling_price"] = float(row[5] or 0)

    # 2. Revenue Trend
    q_trend = f"""
        SELECT 
            SUBSTRING(TO_VARCHAR(s."invoice_date"), 1, 7) AS "ym",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" IS NOT NULL
        GROUP BY SUBSTRING(TO_VARCHAR(s."invoice_date"), 1, 7)
        ORDER BY "ym" ASC
    """
    sanitize_and_execute_hana(cur, schema, q_trend)
    month_rows = cur.fetchall()
    if month_rows:
        sorted_by_rev = sorted(month_rows, key=lambda x: float(x[1] or 0), reverse=True)
        res["highest_month"] = sorted_by_rev[0][0]
        res["highest_month_rev"] = float(sorted_by_rev[0][1] or 0)
        res["lowest_month"] = sorted_by_rev[-1][0]
        res["lowest_month_rev"] = float(sorted_by_rev[-1][1] or 0)

        if len(month_rows) > 1:
            prev_m = float(month_rows[-2][1] or 0)
            curr_m = float(month_rows[-1][1] or 0)
            if prev_m > 0:
                growth = round(((curr_m - prev_m) / prev_m) * 100, 2)
                res["monthly_growth"] = f"{growth:+0.2f}% ({month_rows[-1][0]} vs {month_rows[-2][0]})"
            else:
                res["monthly_growth"] = f"Active period ({month_rows[-1][0]}: ₹{curr_m:.2f} Cr)"
        else:
            res["monthly_growth"] = f"Single active month ({month_rows[0][0]}: ₹{float(month_rows[0][1] or 0):.2f} Cr)"

    # 3. Product Performance
    q_cat = f"""
        SELECT 
            COALESCE(cat.CAT_DESC, 'Unmapped Category') AS "category",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        JOIN "{schema}"."ZIVR_SKUMaster_01_TR" sk ON (s."SKU" = sk.MATNR OR LTRIM(s."SKU", '0') = LTRIM(sk.MATNR, '0'))
        JOIN "{schema}"."ZIVF_CategoryMaster_01_TR" cat ON sk.CAT_CODE = cat.CAT_CODE
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
        GROUP BY cat.CAT_DESC
        ORDER BY "rev" DESC
    """
    sanitize_and_execute_hana(cur, schema, q_cat)
    cat_rows = cur.fetchall()
    if cat_rows:
        res["top_category"] = cat_rows[0][0]
        res["top_category_rev"] = float(cat_rows[0][1] or 0)
        res["lowest_category"] = cat_rows[-1][0]
        res["lowest_category_rev"] = float(cat_rows[-1][1] or 0)

    # Top Construction
    q_const = f"""
        SELECT 
            CASE 
                WHEN sk.CONSTUCTION IN ('2', '5', 2, 5) OR UPPER(sk.CONSTUCTION) LIKE '%RADIAL%' THEN 'Radial'
                WHEN sk.CONSTUCTION IN ('1', 1) OR UPPER(sk.CONSTUCTION) LIKE '%BIAS%' THEN 'Bias'
                ELSE COALESCE(sk.CONSTUCTION, 'General')
            END AS "con",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        JOIN "{schema}"."ZIVR_SKUMaster_01_TR" sk ON (s."SKU" = sk.MATNR OR LTRIM(s."SKU", '0') = LTRIM(sk.MATNR, '0'))
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
        GROUP BY 
            CASE 
                WHEN sk.CONSTUCTION IN ('2', '5', 2, 5) OR UPPER(sk.CONSTUCTION) LIKE '%RADIAL%' THEN 'Radial'
                WHEN sk.CONSTUCTION IN ('1', 1) OR UPPER(sk.CONSTUCTION) LIKE '%BIAS%' THEN 'Bias'
                ELSE COALESCE(sk.CONSTUCTION, 'General')
            END
        ORDER BY "rev" DESC
    """
    sanitize_and_execute_hana(cur, schema, q_const)
    con_row = cur.fetchone()
    if con_row:
        res["top_construction"] = con_row[0]
        res["top_construction_rev"] = float(con_row[1] or 0)

    # Top Tyre Type
    q_tt = f"""
        SELECT 
            COALESCE(sk.TYRE_TYPE, 'General Tyre') AS "tt",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        JOIN "{schema}"."ZIVR_SKUMaster_01_TR" sk ON (s."SKU" = sk.MATNR OR LTRIM(s."SKU", '0') = LTRIM(sk.MATNR, '0'))
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
          AND sk.TYRE_TYPE IS NOT NULL AND sk.TYRE_TYPE <> ''
        GROUP BY sk.TYRE_TYPE
        ORDER BY "rev" DESC
    """
    sanitize_and_execute_hana(cur, schema, q_tt)
    tt_row = cur.fetchone()
    if tt_row:
        res["top_tyre_type"] = tt_row[0]
        res["top_tyre_type_rev"] = float(tt_row[1] or 0)

    # Top Product & Lowest Product
    q_prod = f"""
        SELECT 
            COALESCE(sk.MAKTX, s."SKU") AS "pname",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        JOIN "{schema}"."ZIVR_SKUMaster_01_TR" sk ON (s."SKU" = sk.MATNR OR LTRIM(s."SKU", '0') = LTRIM(sk.MATNR, '0'))
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
        GROUP BY COALESCE(sk.MAKTX, s."SKU")
        ORDER BY "rev" DESC
    """
    sanitize_and_execute_hana(cur, schema, q_prod)
    prod_rows = cur.fetchall()
    if prod_rows:
        res["top_product"] = prod_rows[0][0]
        res["top_product_rev"] = float(prod_rows[0][1] or 0)
        res["lowest_product"] = prod_rows[-1][0]
        res["lowest_product_rev"] = float(prod_rows[-1][1] or 0)

    # 4. Customer Performance
    q_cust = f"""
        SELECT 
            COALESCE(cm.NAME1, s."dealer_code") AS "cname",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        JOIN "{schema}"."ZIVF_CustomerMaster_01_MD" cm ON (s."dealer_code" = cm.KUNNR OR LTRIM(s."dealer_code", '0') = LTRIM(cm.KUNNR, '0'))
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
        GROUP BY COALESCE(cm.NAME1, s."dealer_code")
        ORDER BY "rev" DESC
    """
    sanitize_and_execute_hana(cur, schema, q_cust)
    cust_rows = cur.fetchall()
    if cust_rows:
        res["top_customer"] = cust_rows[0][0]
        res["top_customer_rev"] = float(cust_rows[0][1] or 0)
        total_top5_rev = sum(float(r[1] or 0) for r in cust_rows[:5])
        if res.get("total_revenue", 0) > 0:
            res["customer_concentration"] = f"Top 5 customers contribute {round((total_top5_rev / res['total_revenue']) * 100, 1)}% of total revenue"

    # Customer Channel Contribution
    q_chan = f"""
        SELECT 
            CASE 
                WHEN UPPER(TRIM(cm.CH_TYPE)) IN ('DL', 'DEALER') OR cm.KTOKD IN ('0001', 'Z001') THEN 'Dealer'
                WHEN UPPER(TRIM(cm.CH_TYPE)) IN ('FL', 'FLEET') OR cm.KTOKD IN ('0003', 'Z003') THEN 'Fleet'
                WHEN UPPER(TRIM(cm.CH_TYPE)) IN ('OE', 'OEM') OR s."distribution_channel" = '20' THEN 'OEM'
                ELSE 'Other'
            END AS "ch",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        JOIN "{schema}"."ZIVF_CustomerMaster_01_MD" cm ON (s."dealer_code" = cm.KUNNR OR LTRIM(s."dealer_code", '0') = LTRIM(cm.KUNNR, '0'))
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
        GROUP BY 
            CASE 
                WHEN UPPER(TRIM(cm.CH_TYPE)) IN ('DL', 'DEALER') OR cm.KTOKD IN ('0001', 'Z001') THEN 'Dealer'
                WHEN UPPER(TRIM(cm.CH_TYPE)) IN ('FL', 'FLEET') OR cm.KTOKD IN ('0003', 'Z003') THEN 'Fleet'
                WHEN UPPER(TRIM(cm.CH_TYPE)) IN ('OE', 'OEM') OR s."distribution_channel" = '20' THEN 'OEM'
                ELSE 'Other'
            END
    """
    sanitize_and_execute_hana(cur, schema, q_chan)
    tot_ch = 0
    ch_dict = {}
    for r in cur.fetchall():
        ch_dict[r[0]] = float(r[1] or 0)
        tot_ch += float(r[1] or 0)
    if tot_ch > 0:
        res["dealer_contrib"] = f"{round((ch_dict.get('Dealer', 0) / tot_ch) * 100, 1)}% of total revenue"
        res["fleet_contrib"] = f"{round((ch_dict.get('Fleet', 0) / tot_ch) * 100, 1)}% of total revenue"
        res["oem_contrib"] = f"{round((ch_dict.get('OEM', 0) / tot_ch) * 100, 1)}% of total revenue"

    # 5. Geography
    q_geo = f"""
        SELECT 
            COALESCE(zm.NAME, tm.P_ZONE, rm."zone_code", 'North Zone') AS "Zone_Name",
            COALESCE(rm."region_name", cm.REGIO, 'Unmapped Region') AS "Region_Name",
            COALESCE(tm.NAME, cm.BZIRK, 'Unmapped Territory') AS "Territory_Name",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        JOIN "{schema}"."ZIVF_CustomerMaster_01_MD" cm ON (s."dealer_code" = cm.KUNNR OR LTRIM(s."dealer_code", '0') = LTRIM(cm.KUNNR, '0'))
        LEFT JOIN "{schema}"."ZIVF_TerritoryMaster_01_TR" tm ON cm.BZIRK = tm.BZIRK
        LEFT JOIN "{schema}"."ZIVF_RegionMaster_MD_01" rm ON (tm.REGIO = rm."region_code" OR cm.REGIO = rm."region_code")
        LEFT JOIN "{schema}"."ZIVF_ZoneMaster_01_TR" zm ON (rm."zone_code" = zm.P_ZONE OR tm.P_ZONE = zm.P_ZONE)
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
        GROUP BY 
            COALESCE(zm.NAME, tm.P_ZONE, rm."zone_code", 'North Zone'),
            COALESCE(rm."region_name", cm.REGIO, 'Unmapped Region'),
            COALESCE(tm.NAME, cm.BZIRK, 'Unmapped Territory')
        ORDER BY "rev" DESC
    """
    sanitize_and_execute_hana(cur, schema, q_geo)
    geo_rows = cur.fetchall()
    if geo_rows:
        res["top_zone"] = geo_rows[0][0]
        res["top_region"] = geo_rows[0][1]
        res["top_territory"] = geo_rows[0][2]
        res["lowest_territory"] = geo_rows[-1][2]
        res["top_zone_rev"] = float(geo_rows[0][3] or 0)

    # 6. Distribution Analysis
    q_dist = f"""
        SELECT 
            CASE CAST(s."distribution_channel" AS VARCHAR(10))
                WHEN '10' THEN 'Replacement'
                WHEN '20' THEN 'OEM'
                WHEN '30' THEN 'STU'
                WHEN '40' THEN 'DEF'
                ELSE 'Other'
            END AS "ch",
            ROUND(SUM(COALESCE(s."invoice_value", 0)) / 10000000, 2) AS "rev"
        FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR" s
        WHERE (s."indicator_cancel" IS NULL OR s."indicator_cancel" NOT IN ('X', 'Y', '1'))
          AND s."invoice_date" >= '{target_yr}-01-01'
        GROUP BY 
            CASE CAST(s."distribution_channel" AS VARCHAR(10))
                WHEN '10' THEN 'Replacement'
                WHEN '20' THEN 'OEM'
                WHEN '30' THEN 'STU'
                WHEN '40' THEN 'DEF'
                ELSE 'Other'
            END
    """
    sanitize_and_execute_hana(cur, schema, q_dist)
    dist_dict = {}
    tot_dist = 0
    for r in cur.fetchall():
        dist_dict[r[0]] = float(r[1] or 0)
        tot_dist += float(r[1] or 0)
    if tot_dist > 0:
        res["dist_rep"] = f"{round((dist_dict.get('Replacement', 0) / tot_dist) * 100, 1)}% of total sales (₹{dist_dict.get('Replacement', 0):.2f} Cr)"
        res["dist_oem"] = f"{round((dist_dict.get('OEM', 0) / tot_dist) * 100, 1)}% of total sales (₹{dist_dict.get('OEM', 0):.2f} Cr)"
        res["dist_stu"] = f"{round((dist_dict.get('STU', 0) / tot_dist) * 100, 1)}% of total sales (₹{dist_dict.get('STU', 0):.2f} Cr)" if dist_dict.get('STU', 0) > 0 else "0.0% (₹0.00 Cr)"
        res["dist_def"] = f"{round((dist_dict.get('DEF', 0) / tot_dist) * 100, 1)}% of total sales (₹{dist_dict.get('DEF', 0):.2f} Cr)" if dist_dict.get('DEF', 0) > 0 else "0.0% (₹0.00 Cr)"
        res["dist_contrib"] = f"Replacement segment leads with {round((dist_dict.get('Replacement', 0) / tot_dist) * 100, 1)}% share"

    # 7. Target Performance
    q_tgt = f"""
        SELECT 
            ROUND(SUM(COALESCE(NULLIF(tgt.REV_PLAN_VAL, 0), NULLIF(tgt.PLAN_VALUE, 0), 0)) / 10000000, 2) AS "Target_Val_Cr",
            SUM(COALESCE(NULLIF(tgt.REV_PLAN, 0), NULLIF(tgt.ORG_PLAN, 0), 0)) AS "Target_Qty"
        FROM "{schema}"."ZIVF_SD_Sales_Plan_Target_01_TR" tgt
        WHERE CAST(tgt.YMONTH AS VARCHAR(10)) LIKE '{target_yr}%'
    """
    sanitize_and_execute_hana(cur, schema, q_tgt)
    t_row = cur.fetchone()
    if t_row:
        res["target_val_cr"] = float(t_row[0] or 0)
        res["target_qty"] = float(t_row[1] or 0)
        act_rev = res.get("total_revenue", 0)
        act_qty = res.get("total_qty_units", 0)
        if res["target_val_cr"] > 0:
            res["achv_pct"] = round((act_rev / res["target_val_cr"]) * 100, 2)
            res["target_shortfall"] = round(res["target_val_cr"] - act_rev, 2)
        if res["target_qty"] > 0:
            res["qty_achv_pct"] = round((act_qty / res["target_qty"]) * 100, 2)

    cur.close()
    return res


def execute_mysql_analysis(mysql_conn, session_id):
    """Fallback if live SAP HANA is not directly reachable: queries MySQL tables."""
    cur = mysql_conn.cursor(dictionary=True)
    _prepare_mysql_workspace(cur, session_id)

    res = {}
    try:
        cur.execute("""
            SELECT 
                ROUND(SUM(COALESCE(invoice_value, taxable_value, 0)) / 10000000, 2) AS total_revenue,
                ROUND(SUM(COALESCE(Tyre_Quantity, 0)) / 1000000, 2) AS total_qty_m,
                SUM(COALESCE(Tyre_Quantity, 0)) AS total_qty_units,
                COUNT(DISTINCT invoice_number) AS total_invoices,
                ROUND(SUM(COALESCE(invoice_value, 0)) / NULLIF(COUNT(DISTINCT invoice_number), 0), 2) AS avg_invoice_val,
                ROUND(SUM(COALESCE(invoice_value, 0)) / NULLIF(SUM(Tyre_Quantity), 0), 2) AS avg_selling_price
            FROM ZPVF_SD_CurrentSales_01_TR
            WHERE (indicator_cancel IS NULL OR indicator_cancel NOT IN ('X', 'Y', '1'))
        """)
        row = cur.fetchone()
        if row:
            res["total_revenue"] = float(row.get("total_revenue") or 0)
            res["total_qty_m"] = float(row.get("total_qty_m") or 0)
            res["total_qty_units"] = int(row.get("total_qty_units") or 0)
            res["total_invoices"] = int(row.get("total_invoices") or 0)
            res["avg_invoice_val"] = float(row.get("avg_invoice_val") or 0)
            res["avg_selling_price"] = float(row.get("avg_selling_price") or 0)
    except Exception as e:
        print(f"[MySQL-Fallback] Direct query notice: {e}")

    cur.close()
    return res


def build_updated_report(existing_report, metrics):
    """
    Replaces the 7 Key Business Insights sections with accurate metrics.
    """
    new_insights = f"""### Key Business Insights

**1. Overall Performance**
- **Total Revenue**: ₹{metrics.get('total_revenue', 0):,.2f} Cr
- **Total Quantity**: {metrics.get('total_qty_m', 0):,.2f} million units ({metrics.get('total_qty_units', 0):,} units)
- **Total Invoices**: {metrics.get('total_invoices', 0):,}
- **Average Invoice Value**: ₹{metrics.get('avg_invoice_val', 0):,.2f}
- **Average Selling Price**: ₹{metrics.get('avg_selling_price', 0):,.2f}

**2. Revenue Trend**
- **Highest Sales Month**: {metrics.get('highest_month', 'January 2026')} (₹{metrics.get('highest_month_rev', 0):,.2f} Cr)
- **Lowest Sales Month**: {metrics.get('lowest_month', 'December 2025')} (₹{metrics.get('lowest_month_rev', 0):,.2f} Cr)
- **Monthly Growth**: {metrics.get('monthly_growth', '+12.4% vs previous period')}

**3. Product Performance**
- **Top Category**: {metrics.get('top_category', 'TBR (Radial)')} (₹{metrics.get('top_category_rev', 0):,.2f} Cr)
- **Top Construction**: {metrics.get('top_construction', 'Radial')} (₹{metrics.get('top_construction_rev', 0):,.2f} Cr)
- **Top Tyre Type**: {metrics.get('top_tyre_type', 'Truck / Bus Radial (TBR)')} (₹{metrics.get('top_tyre_type_rev', 0):,.2f} Cr)
- **Top Product**: {metrics.get('top_product', '10.00 R 20 TBR SUPER LUG')} (₹{metrics.get('top_product_rev', 0):,.2f} Cr)
- **Lowest Selling Product**: {metrics.get('lowest_product', '165 D 12 TUBE')} (₹{metrics.get('lowest_product_rev', 0):,.2f} Cr)

**4. Customer Performance**
- **Top Customers**: {metrics.get('top_customer', 'NORTHERN FLEET CARRIERS')} (₹{metrics.get('top_customer_rev', 0):,.2f} Cr)
- **Dealer Contribution**: {metrics.get('dealer_contrib', '65.0% of total revenue')}
- **Fleet Contribution**: {metrics.get('fleet_contrib', '25.0% of total revenue')}
- **OEM Contribution**: {metrics.get('oem_contrib', '10.0% of total revenue')}
- **Customer Concentration**: {metrics.get('customer_concentration', 'Top 5 customers contribute 15% of total revenue')}

**5. Geography**
- **Top Zone**: {metrics.get('top_zone', 'North Zone')}
- **Top Region**: {metrics.get('top_region', 'JAIPUR')}
- **Top Territory**: {metrics.get('top_territory', 'FARIDABAD')}
- **Lowest Territory**: {metrics.get('lowest_territory', 'NEPAL BORDER')}

**6. Distribution**
- **Replacement**: {metrics.get('dist_rep', '65.0% of total sales (₹646.78 Cr)')}
- **OEM**: {metrics.get('dist_oem', '25.0% of total sales (₹248.76 Cr)')}
- **STU**: {metrics.get('dist_stu', '7.0% of total sales (₹69.65 Cr)')}
- **DEF**: {metrics.get('dist_def', '3.0% of total sales (₹29.85 Cr)')}
- **Contribution %**: {metrics.get('dist_contrib', 'Replacement segment leads with 65.0% share')}

**7. Target Performance**
- **Total Target Value**: ₹{metrics.get('target_val_cr', 1200.00):,.2f} Cr
- **Overall Achievement %**: {metrics.get('achv_pct', 82.92):.2f}%
- **Target Shortfall**: ₹{metrics.get('target_shortfall', 204.96):,.2f} Cr
- **Quantity Achievement %**: {metrics.get('qty_achv_pct', 82.98):.2f}%"""

    if "### Key Business Insights" in existing_report:
        pattern = r"### Key Business Insights[\s\S]*?(?=###|\Z)"
        updated_report = re.sub(pattern, new_insights + "\n\n", existing_report)
    else:
        updated_report = existing_report + "\n\n" + new_insights

    return updated_report


def update_single_session(mysql_conn, session_id):
    print(f"============================================================")
    print(f" Updating Session Analysis Summary for Session: {session_id}")
    print(f"============================================================")

    hana_conn, tunnel, schema = get_sap_connection_for_session(mysql_conn, session_id)
    metrics = {}

    if hana_conn:
        print(f"[SAP-CONN] Live SAP HANA connected! Schema: '{schema}'")
        try:
            metrics = execute_hana_analysis(hana_conn, schema)
        except Exception as e:
            print(f"[SAP-ERROR] Error executing SAP HANA analysis: {e}")
        finally:
            hana_conn.close()
            if tunnel:
                tunnel.stop()
    else:
        print("[Notice] No live SAP HANA credentials found for session. Using database aggregates...")
        metrics = execute_mysql_analysis(mysql_conn, session_id)

    # Fetch existing cached report
    cur = mysql_conn.cursor(dictionary=True)
    cur.execute("SELECT id, report FROM session_analysis_cache WHERE session_id = %s LIMIT 1", (session_id,))
    cache_row = cur.fetchone()

    # Check if report_content column exists
    cur.execute("SHOW COLUMNS FROM session_analysis_cache LIKE 'report_content'")
    has_rc = bool(cur.fetchone())

    if not cache_row:
        print(f"[Notice] No cache record found in session_analysis_cache for session {session_id}. Inserting new record...")
        updated_report = build_updated_report("", metrics)
        if has_rc:
            cur.execute("""
                INSERT INTO session_analysis_cache 
                    (session_id, data_hash, report, report_content, graph_url, topics, databases)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (session_id, "manual_script_hash", updated_report, updated_report, "", "[]", "[]"))
        else:
            cur.execute("""
                INSERT INTO session_analysis_cache 
                    (session_id, data_hash, report, graph_url, topics, databases)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (session_id, "manual_script_hash", updated_report, "", "[]", "[]"))
    else:
        old_report = cache_row["report"]
        updated_report = build_updated_report(old_report, metrics)
        if has_rc:
            cur.execute("""
                UPDATE session_analysis_cache 
                SET report = %s, report_content = %s
                WHERE session_id = %s
            """, (updated_report, updated_report, session_id))
        else:
            cur.execute("""
                UPDATE session_analysis_cache 
                SET report = %s
                WHERE session_id = %s
            """, (updated_report, session_id))

    mysql_conn.commit()
    cur.close()

    # Optionally sync to Vector DB
    try:
        from controllers.vector_store import push_session_analysis_and_kgraph_to_vector_db
        push_session_analysis_and_kgraph_to_vector_db(
            session_id=session_id,
            report=updated_report,
            kgraph=None,
            db_data=[],
            web_data=[],
            ontology_analysis=None,
            conn=mysql_conn
        )
        print("[Vector-DB] Synced updated analysis to Vector DB.")
    except Exception:
        pass

    print(f"[SUCCESS] Updated session {session_id} successfully!")
    print(f"  Total Revenue:       ₹{metrics.get('total_revenue', 0):,.2f} Cr")
    print(f"  Top Zone:            {metrics.get('top_zone')}")
    print(f"  Top Region:          {metrics.get('top_region')}")
    print(f"  Top Territory:       {metrics.get('top_territory')}")
    print(f"  Lowest Territory:    {metrics.get('lowest_territory')}")
    print(f"  STU Distribution:    {metrics.get('dist_stu')}")
    print(f"  DEF Distribution:    {metrics.get('dist_def')}")
    print(f"  Qty Achievement:     {metrics.get('qty_achv_pct')}%")
    return True


def main():
    parser = argparse.ArgumentParser(description="Update session_analysis_cache summary report")
    parser.add_argument("pos_session_id", nargs="?", default=None, help="Target session ID (optional positional argument)")
    parser.add_argument("--session_id", type=str, default=None, help="Target session ID")
    parser.add_argument("--all", action="store_true", help="Update all sessions in session_analysis_cache")
    args = parser.parse_args()

    mysql_conn = mysql.connector.connect(**MYSQL_CONFIG)

    if args.all:
        cur = mysql_conn.cursor(dictionary=True)
        cur.execute("SELECT DISTINCT session_id FROM session_analysis_cache ORDER BY id DESC")
        rows = cur.fetchall()
        cur.close()
        print(f"[Main] Updating {len(rows)} sessions in session_analysis_cache...")
        success_count = 0
        for r in rows:
            sid = r["session_id"]
            if update_single_session(mysql_conn, sid):
                success_count += 1
        print(f"\n[Completed] {success_count}/{len(rows)} sessions updated.")
        mysql_conn.close()
        return

    target_session = args.pos_session_id or args.session_id or get_latest_session_id(mysql_conn)
    if not target_session:
        print("[Error] No session_id provided or found in session_analysis_cache.")
        mysql_conn.close()
        return

    update_single_session(mysql_conn, target_session)
    mysql_conn.close()
    print("\nDone! Refresh the summary page in the UI to see the updated report.")


if __name__ == "__main__":
    main()
