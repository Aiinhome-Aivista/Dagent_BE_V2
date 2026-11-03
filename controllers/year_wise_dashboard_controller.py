"""
Controller and service for Dynamic Dependent Filters and Year-wise Sales Comparison Dashboard.
STRICTLY NO HARDCODING in API or UI.
All data is fetched directly from SAP HANA (or synced MySQL workspace) via parameterized SQL queries.

Master & Source Views:
  - Zone:          SAP_S4.ZIVF_ZoneMaster_01_TR
  - Region:        SAP_S4.ZIVF_RegionMaster_MD_01
  - Customer Type: SAP_S4.ZIVF_CustomerMaster_01_MD
  - Month:         SAP_S4.ZITR_DayAttribute_01_TR
  - Year:          SAP_S4.ZPVF_SD_SalesHistory_01_TR & ZPVF_SD_CurrentSales_01_TR
  - Cancelled:     SAP_S4.ZPVF_SD_CancelledSalesInvoice_01_TR

Business Rules:
  1. distribution_channel = '10'
  2. KLABC <> 'X'
  3. Cancelled Invoice check:
       (invoice_number, plant, FKART) not in CancelledSalesInvoice
       indicator_cancel NOT IN ('X', 'Y', '1')
"""

import time
from flask import request, jsonify

# In-memory backend cache for master filter queries to prevent repeated DB hits (TTL: 10 minutes)
_FILTER_CACHE = {}
_CACHE_TTL_SECS = 600

def _get_cache(key):
    entry = _FILTER_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL_SECS:
        return entry["data"]
    return None

def _set_cache(key, data):
    _FILTER_CACHE[key] = {
        "ts": time.time(),
        "data": data
    }


def _resolve_session(conn, session_id):
    if session_id and session_id != "null" and session_id != "undefined":
        return session_id.strip()
    try:
        cur = conn.cursor(dictionary=True) if hasattr(conn, "cursor") else conn.cursor()
        cur.execute("SELECT session_id FROM workspaces WHERE session_id IS NOT NULL AND session_id != '' ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        cur.close()
        if row and row.get("session_id"):
            return row["session_id"]
    except Exception:
        pass
    return session_id or ""


def _get_connection_context(get_db_connection, session_id_arg=None, user_id_arg=None):
    mysql_conn = get_db_connection()
    if not mysql_conn:
        raise Exception("Failed to connect to MySQL application database")

    session_id = _resolve_session(mysql_conn, session_id_arg)
    user_id = user_id_arg

    from helper.sap_analytics_service import get_sap_connection_for_session
    hana_conn = None
    tunnel = None
    sap_schema = "SAP_S4"
    is_hana = False

    try:
        hana_conn, tunnel, schema = get_sap_connection_for_session(mysql_conn, session_id, user_id=user_id)
        if hana_conn:
            is_hana = True
            sap_schema = schema or "SAP_S4"
    except Exception:
        is_hana = False

    user_db = None
    if not is_hana:
        try:
            cur = mysql_conn.cursor(dictionary=True) if hasattr(mysql_conn, "cursor") else mysql_conn.cursor()
            cur.execute("""
                SELECT new_user_db 
                FROM external_db_sync_log 
                WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            s_row = cur.fetchone()
            if not s_row:
                cur.execute("""
                    SELECT workspace_db FROM workspaces 
                    WHERE session_id=%s AND workspace_db IS NOT NULL AND workspace_db != ''
                    LIMIT 1
                """, (session_id,))
                s_row = cur.fetchone()
            if s_row:
                user_db = s_row.get("new_user_db") or s_row.get("workspace_db")
            if not user_db:
                user_db = "jk_sales_workspace_db"
            cur.close()
        except Exception:
            user_db = "jk_sales_workspace_db"

    return mysql_conn, hana_conn, tunnel, is_hana, sap_schema, user_db, session_id


def _close_connections(mysql_conn, hana_conn, tunnel, cursor=None):
    if cursor:
        try: cursor.close()
        except Exception: pass
    if hana_conn:
        try: hana_conn.close()
        except Exception: pass
    if tunnel:
        try: tunnel.stop()
        except Exception: pass
    if mysql_conn and hasattr(mysql_conn, "is_connected") and mysql_conn.is_connected():
        try: mysql_conn.close()
        except Exception: pass
    elif mysql_conn:
        try: mysql_conn.close()
        except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# 1. Fetch Zones directly from ZIVF_ZoneMaster_01_TR
# ─────────────────────────────────────────────────────────────────────────────
def fetch_zones(cursor, is_hana, schema, user_db):
    zones = []
    if is_hana:
        sql = f"""
            SELECT DISTINCT
                "P_ZONE" AS ZONE_CODE,
                "NAME" AS ZONE_NAME
            FROM "{schema}"."ZIVF_ZoneMaster_01_TR"
            WHERE "P_ZONE" IS NOT NULL AND TRIM("P_ZONE") <> ''
            ORDER BY "P_ZONE" ASC
        """
        cursor.execute(sql)
        for r in cursor.fetchall():
            zc = r[0] if isinstance(r, (list, tuple)) else r.get("ZONE_CODE")
            zn = r[1] if isinstance(r, (list, tuple)) else r.get("ZONE_NAME")
            if zc:
                zones.append({"label": str(zn or zc).strip(), "value": str(zc).strip()})
    else:
        sql = f"""
            SELECT DISTINCT zone_code AS ZONE_CODE, zone_name AS ZONE_NAME 
            FROM `{user_db}`.`zone_master`
            WHERE zone_code IS NOT NULL AND TRIM(zone_code) <> ''
            ORDER BY zone_code ASC
        """
        cursor.execute(sql)
        for r in cursor.fetchall():
            zc = r.get("ZONE_CODE") if isinstance(r, dict) else r[0]
            zn = r.get("ZONE_NAME") if isinstance(r, dict) else r[1]
            if zc:
                zones.append({"label": str(zn or zc).strip(), "value": str(zc).strip()})

    return [{"label": "ALL", "value": "ALL"}] + zones


# ─────────────────────────────────────────────────────────────────────────────
# 2. Fetch Regions directly from ZIVF_RegionMaster_MD_01
# ─────────────────────────────────────────────────────────────────────────────
def fetch_regions(cursor, is_hana, schema, user_db, zone=None):
    regions = []
    zone_filter = str(zone).strip().upper() if zone and str(zone).strip().lower() != "all" else None

    if is_hana:
        params = []
        where_cls = 'WHERE "region_code" IS NOT NULL AND TRIM("region_code") <> \'\''
        if zone_filter:
            where_cls += ' AND UPPER(TRIM("zone_code")) = ?'
            params.append(zone_filter)

        sql = f"""
            SELECT DISTINCT
                "region_code" AS REGION_CODE,
                "region_name" AS REGION_NAME,
                "zone_code" AS ZONE_CODE
            FROM "{schema}"."ZIVF_RegionMaster_MD_01"
            {where_cls}
            ORDER BY "zone_code", "region_code"
        """
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        for r in cursor.fetchall():
            rc = r[0] if isinstance(r, (list, tuple)) else r.get("REGION_CODE")
            rn = r[1] if isinstance(r, (list, tuple)) else r.get("REGION_NAME")
            zc = r[2] if isinstance(r, (list, tuple)) else r.get("ZONE_CODE")
            if rc:
                regions.append({
                    "label": str(rn or rc).strip(),
                    "value": str(rc).strip(),
                    "zone_code": str(zc or "").strip()
                })
    else:
        params = []
        where_cls = "WHERE region IS NOT NULL AND TRIM(region) <> ''"
        if zone_filter:
            where_cls += " AND UPPER(TRIM(zone)) = %s"
            params.append(zone_filter)

        sql = f"""
            SELECT DISTINCT region AS REGION_CODE, region_name AS REGION_NAME, zone AS ZONE_CODE
            FROM `{user_db}`.`region_master`
            {where_cls}
            ORDER BY zone, region
        """
        if params:
            cursor.execute(sql, tuple(params))
        else:
            cursor.execute(sql)

        for r in cursor.fetchall():
            rc = r.get("REGION_CODE") if isinstance(r, dict) else r[0]
            rn = r.get("REGION_NAME") if isinstance(r, dict) else r[1]
            zc = r.get("ZONE_CODE") if isinstance(r, dict) else r[2]
            if rc:
                regions.append({
                    "label": str(rn or rc).strip(),
                    "value": str(rc).strip(),
                    "zone_code": str(zc or "").strip()
                })

    return [{"label": "ALL", "value": "ALL", "zone_code": "ALL"}] + regions


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fetch Customer Types directly from ZIVF_CustomerMaster_01_MD
# ─────────────────────────────────────────────────────────────────────────────
def fetch_customer_types(cursor, is_hana, schema, user_db, zone=None, region=None):
    customer_types = []
    zone_val = str(zone).strip().upper() if zone and str(zone).strip().lower() != "all" else None
    region_val = str(region).strip() if region and str(region).strip().lower() != "all" else None

    if is_hana:
        params = []
        where_conds = [
            'cm."CH_TYPE" IS NOT NULL',
            'TRIM(cm."CH_TYPE") <> \'\'',
            'IFNULL(cm."KLABC", \'\') <> \'X\''
        ]
        from_part = f'"{schema}"."ZIVF_CustomerMaster_01_MD" cm'

        if region_val or zone_val:
            from_part += f' LEFT JOIN "{schema}"."ZIVF_RegionMaster_MD_01" rm ON (TRIM(rm."region_code") = COALESCE(NULLIF(TRIM(TO_VARCHAR(cm."REGIO")), \'\'), NULLIF(TRIM(cm."BZIRK"), \'\')))'
            if region_val:
                where_conds.append('(rm."region_code" = ? OR cm."REGIO" = ? OR cm."BZIRK" = ?)')
                params.extend([region_val, region_val, region_val])
            if zone_val:
                where_conds.append('(UPPER(TRIM(rm."zone_code")) = ?)')
                params.append(zone_val)

        where_sql = "WHERE " + " AND ".join(where_conds)
        sql = f"""
            SELECT DISTINCT cm."CH_TYPE" AS CUSTOMER_TYPE
            FROM {from_part}
            {where_sql}
            ORDER BY CUSTOMER_TYPE ASC
        """
        if params:
            cursor.execute(sql, params)
        else:
            cursor.execute(sql)

        for r in cursor.fetchall():
            ct = r[0] if isinstance(r, (list, tuple)) else r.get("CUSTOMER_TYPE")
            if ct:
                customer_types.append({"label": str(ct).strip(), "value": str(ct).strip()})
    else:
        params = []
        where_conds = [
            "cm.ch_type IS NOT NULL",
            "TRIM(cm.ch_type) <> ''",
            "IFNULL(cm.klabc, '') <> 'X'"
        ]
        from_part = f"`{user_db}`.`customer_master` cm"

        if region_val or zone_val:
            from_part += f" LEFT JOIN `{user_db}`.`region_master` rm ON (rm.region = cm.sales_office OR rm.region = cm.dlr_catg OR rm.region = cm.segment)"
            if region_val:
                where_conds.append("(rm.region = %s OR cm.sales_office = %s OR cm.dlr_catg = %s)")
                params.extend([region_val, region_val, region_val])
            if zone_val:
                where_conds.append("UPPER(TRIM(rm.zone)) = %s")
                params.append(zone_val)

        where_sql = "WHERE " + " AND ".join(where_conds)
        sql = f"""
            SELECT DISTINCT cm.ch_type AS CUSTOMER_TYPE
            FROM {from_part}
            {where_sql}
            ORDER BY CUSTOMER_TYPE ASC
        """
        if params:
            cursor.execute(sql, tuple(params))
        else:
            cursor.execute(sql)

        for r in cursor.fetchall():
            ct = r.get("CUSTOMER_TYPE") if isinstance(r, dict) else r[0]
            if ct:
                customer_types.append({"label": str(ct).strip(), "value": str(ct).strip()})

    return [{"label": "ALL", "value": "ALL"}] + customer_types


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fetch Master Months directly from ZITR_DayAttribute_01_TR
# ─────────────────────────────────────────────────────────────────────────────
def fetch_master_months(cursor, is_hana, schema, user_db):
    months = []
    if is_hana:
        sql = f"""
            SELECT DISTINCT
                MONTH("Date_") AS MONTH_NO,
                CASE MONTH("Date_")
                    WHEN 1  THEN 'JAN'
                    WHEN 2  THEN 'FEB'
                    WHEN 3  THEN 'MAR'
                    WHEN 4  THEN 'APR'
                    WHEN 5  THEN 'MAY'
                    WHEN 6  THEN 'JUN'
                    WHEN 7  THEN 'JUL'
                    WHEN 8  THEN 'AUG'
                    WHEN 9  THEN 'SEP'
                    WHEN 10 THEN 'OCT'
                    WHEN 11 THEN 'NOV'
                    WHEN 12 THEN 'DEC'
                END AS MONTH_NAME
            FROM "{schema}"."ZITR_DayAttribute_01_TR"
            WHERE "Date_" IS NOT NULL
            ORDER BY MONTH_NO ASC
        """
        cursor.execute(sql)
        for r in cursor.fetchall():
            m_no = r[0] if isinstance(r, (list, tuple)) else r.get("MONTH_NO")
            m_name = r[1] if isinstance(r, (list, tuple)) else r.get("MONTH_NAME")
            if m_no:
                months.append({"label": str(m_name).strip(), "value": int(m_no)})
    else:
        sql = f"""
            SELECT DISTINCT
                MONTH(billing__doc_date) AS MONTH_NO,
                CASE MONTH(billing__doc_date)
                    WHEN 1  THEN 'JAN'
                    WHEN 2  THEN 'FEB'
                    WHEN 3  THEN 'MAR'
                    WHEN 4  THEN 'APR'
                    WHEN 5  THEN 'MAY'
                    WHEN 6  THEN 'JUN'
                    WHEN 7  THEN 'JUL'
                    WHEN 8  THEN 'AUG'
                    WHEN 9  THEN 'SEP'
                    WHEN 10 THEN 'OCT'
                    WHEN 11 THEN 'NOV'
                    WHEN 12 THEN 'DEC'
                END AS MONTH_NAME
            FROM `{user_db}`.`sales_data`
            WHERE billing__doc_date IS NOT NULL
            ORDER BY MONTH_NO ASC
        """
        cursor.execute(sql)
        for r in cursor.fetchall():
            m_no = r.get("MONTH_NO") if isinstance(r, dict) else r[0]
            m_name = r.get("MONTH_NAME") if isinstance(r, dict) else r[1]
            if m_no:
                months.append({"label": str(m_name).upper().strip(), "value": int(m_no)})

    return [{"label": "ALL", "value": "ALL"}] + months


# ─────────────────────────────────────────────────────────────────────────────
# 5. Fetch Master Years directly from Sales History & Current Sales
# ─────────────────────────────────────────────────────────────────────────────
def fetch_master_years(cursor, is_hana, schema, user_db):
    years = []
    if is_hana:
        sql = f"""
            SELECT DISTINCT
                YEAR("invoice_date") AS SALES_YEAR
            FROM (
                SELECT "invoice_date"
                FROM "{schema}"."ZPVF_SD_SalesHistory_01_TR"

                UNION ALL

                SELECT "invoice_date"
                FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR"
            ) S
            WHERE "invoice_date" >= ADD_YEARS(CURRENT_DATE, -2)
              AND "invoice_date" <= CURRENT_DATE
            ORDER BY SALES_YEAR DESC
        """
        cursor.execute(sql)
        for r in cursor.fetchall():
            y = r[0] if isinstance(r, (list, tuple)) else r.get("SALES_YEAR")
            if y:
                years.append({"label": str(y).strip(), "value": int(y)})
    else:
        sql = f"""
            SELECT DISTINCT YEAR(billing__doc_date) AS SALES_YEAR
            FROM `{user_db}`.`sales_data`
            WHERE billing__doc_date IS NOT NULL
            ORDER BY SALES_YEAR DESC
            LIMIT 3
        """
        cursor.execute(sql)
        for r in cursor.fetchall():
            y = r.get("SALES_YEAR") if isinstance(r, dict) else r[0]
            if y:
                years.append({"label": str(y).strip(), "value": int(y)})

    return [{"label": "ALL", "value": "ALL"}] + years


# ─────────────────────────────────────────────────────────────────────────────
# 6. Build Parameterized Sales Query with Business Rules & Faceted Filtering
# ─────────────────────────────────────────────────────────────────────────────
def _build_sales_filter_query(cursor, is_hana, schema, user_db, zone=None, region=None, customer_type=None, month=None, years=None, exclude_dim=None):
    valid_years = []
    if exclude_dim != "year" and years:
        raw_years = years if isinstance(years, list) else [y.strip() for y in str(years).split(",") if y.strip()]
        for y in raw_years:
            if str(y).strip().lower() == "all": continue
            try: valid_years.append(int(y))
            except ValueError: pass

    valid_months = []
    if exclude_dim != "month" and month:
        raw_months = month if isinstance(month, list) else [m.strip() for m in str(month).split(",") if m.strip()]
        for m in raw_months:
            if not m or str(m).strip().lower() == "all": continue
            sm = str(m).strip()
            if sm.isdigit():
                valid_months.append(int(sm))
            else:
                m_lookup = {
                    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
                }
                if sm.upper() in m_lookup:
                    valid_months.append(m_lookup[sm.upper()])

    zone_val = str(zone).strip().upper() if zone and str(zone).strip().lower() != "all" else None
    region_val = str(region).strip() if region and str(region).strip().lower() != "all" else None
    cust_val = str(customer_type).strip().upper() if customer_type and str(customer_type).strip().lower() != "all" else None

    if is_hana:
        where_clauses = [
            "(s.\"distribution_channel\" = '10' OR s.\"distribution_channel\" = 10)",
            "(s.\"indicator_cancel\" IS NULL OR s.\"indicator_cancel\" NOT IN ('X', 'Y', '1'))",
            "s.\"invoice_date\" IS NOT NULL",
            'IFNULL(cm."KLABC", \'\') <> \'X\''
        ]
        params = []

        # Cancelled invoice exclusion against ZPVF_SD_CancelledSalesInvoice_01_TR
        where_clauses.append(f"""NOT EXISTS (
            SELECT 1 FROM "{schema}"."ZPVF_SD_CancelledSalesInvoice_01_TR" can
            WHERE (can."distribution_channel" = '10' OR can."distribution_channel" = 10)
              AND can."invoice_number" = s."invoice_number"
              AND can."plant" = s."plant"
              AND can."FKART" = s."FKART"
        )""")

        if valid_years:
            ph = ", ".join(["?"] * len(valid_years))
            where_clauses.append(f'YEAR(s."invoice_date") IN ({ph})')
            params.extend(valid_years)
        else:
            where_clauses.append('s."invoice_date" >= ADD_YEARS(CURRENT_DATE, -2) AND s."invoice_date" <= CURRENT_DATE')

        if valid_months:
            ph = ", ".join(["?"] * len(valid_months))
            where_clauses.append(f'MONTH(s."invoice_date") IN ({ph})')
            params.extend(valid_months)

        if cust_val:
            where_clauses.append('UPPER(TRIM(cm."CH_TYPE")) = ?')
            params.append(cust_val)

        if region_val:
            where_clauses.append('(rm."region_code" = ? OR cm."REGIO" = ? OR cm."BZIRK" = ?)')
            params.extend([region_val, region_val, region_val])

        if zone_val:
            where_clauses.append('UPPER(TRIM(rm."zone_code")) = ?')
            params.append(zone_val)

        if valid_years and all(y <= 2025 for y in valid_years):
            sales_source = f"""
                SELECT "invoice_number", "plant", "FKART", "dealer_code", "invoice_date",
                       "distribution_channel", "indicator_cancel", "invoice_value", "ndp_value", "taxable_value"
                FROM "{schema}"."ZPVF_SD_SalesHistory_01_TR"
            """
        else:
            sales_source = f"""
                SELECT "invoice_number", "plant", "FKART", "dealer_code", "invoice_date",
                       "distribution_channel", "indicator_cancel", "invoice_value", "ndp_value", "taxable_value"
                FROM "{schema}"."ZPVF_SD_SalesHistory_01_TR"
                UNION ALL
                SELECT "invoice_number", "plant", "FKART", "dealer_code", "invoice_date",
                       "distribution_channel", "indicator_cancel", "invoice_value", "ndp_value", "taxable_value"
                FROM "{schema}"."ZPVF_SD_CurrentSales_01_TR"
            """

        joins = f"""
            FROM ({sales_source}) s
            JOIN "{schema}"."ZIVF_CustomerMaster_01_MD" cm
                ON (LPAD(TRIM(s."dealer_code"), 10, '0') = cm."KUNNR" OR LTRIM(s."dealer_code", '0') = LTRIM(cm."KUNNR", '0'))
            LEFT JOIN "{schema}"."ZIVF_RegionMaster_MD_01" rm
                ON (TRIM(rm."region_code") = COALESCE(NULLIF(TRIM(TO_VARCHAR(cm."REGIO")), ''), NULLIF(TRIM(cm."BZIRK"), '')))
        """

        where_sql = "WHERE " + " AND ".join(where_clauses)
        rev_expr = 'COALESCE(s."ndp_value", s."taxable_value", s."invoice_value", 0)'
        date_expr = 's."invoice_date"'

        return joins, where_sql, params, date_expr, rev_expr

    else:
        where_clauses = [
            "(s.distribution__channel = '10' OR s.distribution__channel = 10)",
            "s.billing__doc_date IS NOT NULL",
            "IFNULL(cm.klabc, '') <> 'X'"
        ]
        params = []

        if valid_years:
            ph = ", ".join(["%s"] * len(valid_years))
            where_clauses.append(f"YEAR(s.billing__doc_date) IN ({ph})")
            params.extend(valid_years)

        if valid_months:
            ph = ", ".join(["%s"] * len(valid_months))
            where_clauses.append(f"MONTH(s.billing__doc_date) IN ({ph})")
            params.extend(valid_months)

        if cust_val:
            where_clauses.append("UPPER(TRIM(cm.ch_type)) = %s")
            params.append(cust_val)

        if region_val:
            where_clauses.append("(rm.region = %s OR cm.sales_office = %s OR cm.dlr_catg = %s)")
            params.extend([region_val, region_val, region_val])

        if zone_val:
            where_clauses.append("UPPER(TRIM(rm.zone)) = %s")
            params.append(zone_val)

        joins = f"""
            FROM `{user_db}`.`sales_data` s
            JOIN `{user_db}`.`customer_master` cm ON (s.customer = cm.kunnr)
            LEFT JOIN `{user_db}`.`region_master` rm ON (rm.region = cm.sales_office OR rm.region = cm.dlr_catg OR rm.region = cm.segment)
        """

        where_sql = "WHERE " + " AND ".join(where_clauses)
        rev_expr = "COALESCE(s.invoice_value_inr, s.taxable_value_inr, s.ndp_inr, 0)"
        date_expr = "s.billing__doc_date"

        return joins, where_sql, params, date_expr, rev_expr


# ─────────────────────────────────────────────────────────────────────────────
# 7. Faceted Available Periods (Months & Years)
# ─────────────────────────────────────────────────────────────────────────────
def fetch_available_periods(cursor, is_hana, schema, user_db, zone=None, region=None, customer_type=None, month=None, years=None):
    # 1. Available Months (excludes month filter)
    joins_m, where_m, params_m, date_col_m, _ = _build_sales_filter_query(
        cursor, is_hana, schema, user_db, zone=zone, region=region, customer_type=customer_type,
        month=month, years=years, exclude_dim="month"
    )

    case_month_expr = f"""
        CASE MONTH({date_col_m})
            WHEN 1  THEN 'JAN'
            WHEN 2  THEN 'FEB'
            WHEN 3  THEN 'MAR'
            WHEN 4  THEN 'APR'
            WHEN 5  THEN 'MAY'
            WHEN 6  THEN 'JUN'
            WHEN 7  THEN 'JUL'
            WHEN 8  THEN 'AUG'
            WHEN 9  THEN 'SEP'
            WHEN 10 THEN 'OCT'
            WHEN 11 THEN 'NOV'
            WHEN 12 THEN 'DEC'
        END
    """

    sql_months = f"""
        SELECT DISTINCT
            MONTH({date_col_m}) AS MONTH_NO,
            {case_month_expr} AS MONTH_NAME
        {joins_m}
        {where_m}
        ORDER BY MONTH_NO ASC
    """

    avail_months = []
    if params_m:
        cursor.execute(sql_months, params_m if is_hana else tuple(params_m))
    else:
        cursor.execute(sql_months)

    for r in cursor.fetchall():
        m_no = r[0] if isinstance(r, (list, tuple)) else (r.get("MONTH_NO") if isinstance(r, dict) else None)
        m_name = r[1] if isinstance(r, (list, tuple)) else (r.get("MONTH_NAME") if isinstance(r, dict) else None)
        if m_no:
            avail_months.append({"label": str(m_name).upper().strip(), "value": int(m_no)})

    if not avail_months:
        avail_months = fetch_master_months(cursor, is_hana, schema, user_db)[1:]

    months_result = [{"label": "ALL", "value": "ALL"}] + avail_months

    # 2. Available Years (excludes year filter)
    joins_y, where_y, params_y, date_col_y, _ = _build_sales_filter_query(
        cursor, is_hana, schema, user_db, zone=zone, region=region, customer_type=customer_type,
        month=month, years=years, exclude_dim="year"
    )

    sql_years = f"""
        SELECT DISTINCT YEAR({date_col_y}) AS SALES_YEAR
        {joins_y}
        {where_y}
        ORDER BY SALES_YEAR DESC
    """

    avail_years = []
    if params_y:
        cursor.execute(sql_years, params_y if is_hana else tuple(params_y))
    else:
        cursor.execute(sql_years)

    for r in cursor.fetchall():
        y_val = r[0] if isinstance(r, (list, tuple)) else (r.get("SALES_YEAR") if isinstance(r, dict) else None)
        if y_val:
            avail_years.append(int(y_val))

    if not avail_years:
        master_y = fetch_master_years(cursor, is_hana, schema, user_db)[1:]
        years_result = [{"label": "ALL", "value": "ALL"}] + master_y
    else:
        top_years = sorted(list(set(avail_years)), reverse=True)[:3]
        years_result = [{"label": "ALL", "value": "ALL"}] + [{"label": str(y), "value": y} for y in top_years]

    return months_result, years_result


# ─────────────────────────────────────────────────────────────────────────────
# API 1: Initial Filter Data
# GET /api/dashboard/filters
# ─────────────────────────────────────────────────────────────────────────────
def get_dashboard_filters_controller(get_db_connection):
    mysql_conn = None
    hana_conn = None
    tunnel = None
    cursor = None

    try:
        session_id = request.args.get("session_id")
        user_id = request.args.get("user_id")

        mysql_conn, hana_conn, tunnel, is_hana, schema, user_db, effective_session = _get_connection_context(
            get_db_connection, session_id, user_id
        )
        cursor = hana_conn.cursor() if is_hana else mysql_conn.cursor()

        cache_key = f"filters_init_{effective_session}_{is_hana}"
        cached = _get_cache(cache_key)
        if cached:
            return jsonify(cached), 200

        zones = fetch_zones(cursor, is_hana, schema, user_db)
        regions = fetch_regions(cursor, is_hana, schema, user_db)
        customer_types = fetch_customer_types(cursor, is_hana, schema, user_db)
        months = fetch_master_months(cursor, is_hana, schema, user_db)
        years = fetch_master_years(cursor, is_hana, schema, user_db)

        response_data = {
            "status": "success",
            "zones": zones,
            "regions": regions,
            "customer_types": customer_types,
            "months": months,
            "years": years
        }

        _set_cache(cache_key, response_data)
        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        _close_connections(mysql_conn, hana_conn, tunnel, cursor)


# ─────────────────────────────────────────────────────────────────────────────
# API 2: Dependent Regions
# GET /api/dashboard/filters/regions?zone=CZ
# ─────────────────────────────────────────────────────────────────────────────
def get_dependent_regions_controller(get_db_connection):
    mysql_conn = None
    hana_conn = None
    tunnel = None
    cursor = None

    try:
        session_id = request.args.get("session_id")
        user_id = request.args.get("user_id")
        zone = request.args.get("zone", "ALL")

        cache_key = f"regions_{session_id}_{zone}"
        cached = _get_cache(cache_key)
        if cached:
            return jsonify(cached), 200

        mysql_conn, hana_conn, tunnel, is_hana, schema, user_db, _ = _get_connection_context(
            get_db_connection, session_id, user_id
        )
        cursor = hana_conn.cursor() if is_hana else mysql_conn.cursor()

        regions = fetch_regions(cursor, is_hana, schema, user_db, zone=zone)
        resp = {"status": "success", "regions": regions}
        _set_cache(cache_key, resp)
        return jsonify(resp), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        _close_connections(mysql_conn, hana_conn, tunnel, cursor)


# ─────────────────────────────────────────────────────────────────────────────
# API 3: Dependent Customer Types
# GET /api/dashboard/filters/customer-types?zone=CZ&region=3681
# ─────────────────────────────────────────────────────────────────────────────
def get_dependent_customer_types_controller(get_db_connection):
    mysql_conn = None
    hana_conn = None
    tunnel = None
    cursor = None

    try:
        session_id = request.args.get("session_id")
        user_id = request.args.get("user_id")
        zone = request.args.get("zone", "ALL")
        region = request.args.get("region", "ALL")

        cache_key = f"cust_types_{session_id}_{zone}_{region}"
        cached = _get_cache(cache_key)
        if cached:
            return jsonify(cached), 200

        mysql_conn, hana_conn, tunnel, is_hana, schema, user_db, _ = _get_connection_context(
            get_db_connection, session_id, user_id
        )
        cursor = hana_conn.cursor() if is_hana else mysql_conn.cursor()

        customer_types = fetch_customer_types(cursor, is_hana, schema, user_db, zone=zone, region=region)
        resp = {"status": "success", "customer_types": customer_types}
        _set_cache(cache_key, resp)
        return jsonify(resp), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        _close_connections(mysql_conn, hana_conn, tunnel, cursor)


# ─────────────────────────────────────────────────────────────────────────────
# API 4: Available Months and Years (Faceted Filtering)
# GET /api/dashboard/filters/available-periods
# ─────────────────────────────────────────────────────────────────────────────
def get_available_periods_controller(get_db_connection):
    mysql_conn = None
    hana_conn = None
    tunnel = None
    cursor = None

    try:
        args = request.args if request.method == "GET" else (request.get_json(silent=True) or {})
        session_id = args.get("session_id")
        user_id = args.get("user_id")
        zone = args.get("zone", "ALL")
        region = args.get("region", "ALL")
        customer_type = args.get("customer_type", "ALL")
        month = args.get("month", "ALL")
        years = args.get("years", "ALL")

        cache_key = f"periods_{session_id}_{zone}_{region}_{customer_type}_{month}_{years}"
        cached = _get_cache(cache_key)
        if cached:
            return jsonify(cached), 200

        mysql_conn, hana_conn, tunnel, is_hana, schema, user_db, _ = _get_connection_context(
            get_db_connection, session_id, user_id
        )
        cursor = hana_conn.cursor() if is_hana else mysql_conn.cursor()

        months, years_list = fetch_available_periods(
            cursor, is_hana, schema, user_db,
            zone=zone, region=region, customer_type=customer_type,
            month=month, years=years
        )

        resp = {
            "status": "success",
            "months": months,
            "years": years_list
        }
        _set_cache(cache_key, resp)
        return jsonify(resp), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        _close_connections(mysql_conn, hana_conn, tunnel, cursor)


# ─────────────────────────────────────────────────────────────────────────────
# API 5: Year-wise Sales Aggregated Data
# GET/POST /api/dashboard/year-wise-sales
# ─────────────────────────────────────────────────────────────────────────────
def get_year_wise_sales_controller(get_db_connection):
    mysql_conn = None
    hana_conn = None
    tunnel = None
    cursor = None

    try:
        data = request.get_json(force=True, silent=True) or {}
        if not data and request.args:
            data = request.args.to_dict(flat=False)
            for k, v in list(data.items()):
                if isinstance(v, list) and len(v) == 1:
                    data[k] = v[0]

        session_id = data.get("session_id")
        user_id = data.get("user_id")

        def make_list(val):
            if val is None: return []
            if isinstance(val, list): return [v for v in val if v]
            return [v.strip() for v in str(val).split(",") if v.strip()]

        selected_years = make_list(data.get("selected_years") or data.get("years") or data.get("year"))
        selected_zones = make_list(data.get("selected_zones") or data.get("zones") or data.get("zone") or data.get("Zone"))
        selected_regions = make_list(data.get("selected_regions") or data.get("regions") or data.get("region") or data.get("Region"))
        selected_months = make_list(data.get("selected_months") or data.get("months") or data.get("month") or data.get("Month"))
        selected_customer_types = make_list(data.get("selected_customer_types") or data.get("customer_types") or data.get("customer_type"))

        zone_param = selected_zones[0] if selected_zones else "ALL"
        region_param = selected_regions[0] if selected_regions else "ALL"
        cust_param = selected_customer_types[0] if selected_customer_types else "ALL"
        month_param = selected_months if selected_months else "ALL"
        year_param = selected_years if selected_years else "ALL"

        mysql_conn, hana_conn, tunnel, is_hana, schema, user_db, effective_session = _get_connection_context(
            get_db_connection, session_id, user_id
        )
        cursor = hana_conn.cursor() if is_hana else mysql_conn.cursor()

        joins, where_sql, params, date_col, rev_expr = _build_sales_filter_query(
            cursor, is_hana, schema, user_db,
            zone=zone_param, region=region_param, customer_type=cust_param,
            month=month_param, years=year_param
        )

        month_expr = f"MONTH({date_col})"
        year_expr = f"YEAR({date_col})"

        case_month_expr = f"""
            CASE {month_expr}
                WHEN 1  THEN 'JAN'
                WHEN 2  THEN 'FEB'
                WHEN 3  THEN 'MAR'
                WHEN 4  THEN 'APR'
                WHEN 5  THEN 'MAY'
                WHEN 6  THEN 'JUN'
                WHEN 7  THEN 'JUL'
                WHEN 8  THEN 'AUG'
                WHEN 9  THEN 'SEP'
                WHEN 10 THEN 'OCT'
                WHEN 11 THEN 'NOV'
                WHEN 12 THEN 'DEC'
            END
        """

        query = f"""
            SELECT 
                {month_expr} AS MONTH_NO,
                {case_month_expr} AS MONTH_NAME,
                {year_expr} AS SALES_YEAR,
                ROUND(SUM({rev_expr}), 2) AS TOTAL_SALES
            {joins}
            {where_sql}
            GROUP BY {year_expr}, {month_expr}
            ORDER BY SALES_YEAR ASC, MONTH_NO ASC
        """

        if params:
            cursor.execute(query, params if is_hana else tuple(params))
        else:
            cursor.execute(query)

        results = cursor.fetchall()
        visualization_data = []

        for row in results:
            if isinstance(row, (list, tuple)):
                m_no = int(row[0] or 1)
                m_name = str(row[1]).upper().strip()
                yr_val = str(row[2])
                sales_val = float(row[3] or 0.0)
            elif isinstance(row, dict):
                m_no = int(row.get("MONTH_NO") or row.get("month_num") or 1)
                m_name = str(row.get("MONTH_NAME") or row.get("month") or "").upper().strip()
                yr_val = str(row.get("SALES_YEAR") or row.get("year"))
                sales_val = float(row.get("TOTAL_SALES") or row.get("total_sales") or 0.0)
            else:
                continue

            visualization_data.append({
                "month": m_name,
                "sales_value": sales_val,
                "year": yr_val
            })

        return jsonify({
            "status": "success",
            "seriesKey": "year",
            "title": "Year-wise Sales Comparison",
            "type": "bar_chart",
            "xKey": "month",
            "yKey": "sales_value",
            "visualization": visualization_data
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "Database query failed.",
            "details": str(e),
            "seriesKey": "year",
            "title": "Year-wise Sales Comparison",
            "type": "bar_chart",
            "xKey": "month",
            "yKey": "sales_value",
            "visualization": []
        }), 500
    finally:
        _close_connections(mysql_conn, hana_conn, tunnel, cursor)
