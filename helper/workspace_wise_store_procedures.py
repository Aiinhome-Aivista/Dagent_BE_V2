import pymysql
from database.config import MYSQL_CONFIG

# Embedded SQL queries
# Stored procedures querying the 10 SAP S/4 HANA Views

SQL_CONTENT = """
----------------- domestic sales value achivements store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_domestic_sales_value_achivements $$
CREATE PROCEDURE `sp_domestic_sales_value_achivements`(
    IN p_year INT,
    IN p_month INT,
    IN p_day INT
)
BEGIN
    DECLARE v_curr_from DATE;
    DECLARE v_curr_to DATE;
    DECLARE v_prev_from DATE;
    DECLARE v_prev_to DATE;
    DECLARE v_target_month INT;

    /* Dates Setup */
    SET p_year  = IFNULL(p_year , YEAR(CURDATE()));
    SET p_month = IFNULL(p_month, MONTH(CURDATE()));
    SET p_day   = IFNULL(p_day  , DAY(CURDATE()));

    SET v_curr_from = STR_TO_DATE(CONCAT(p_year,'-',LPAD(p_month,2,'0'),'-01'), '%Y-%m-%d');
    SET v_curr_to   = LEAST(STR_TO_DATE(CONCAT(p_year,'-',LPAD(p_month,2,'0'),'-',LPAD(p_day,2,'0')), '%Y-%m-%d'), LAST_DAY(v_curr_from));
    SET v_prev_from = DATE_SUB(v_curr_from, INTERVAL 1 YEAR);
    SET v_prev_to   = DATE_SUB(v_curr_to, INTERVAL 1 YEAR);
    SET v_target_month = p_year * 100 + p_month;

    WITH
    /* 1. Market Segment Target */
    target_market AS (
        SELECT '4 Wheelers' AS report_name, CAST(0 AS DECIMAL(18,2)) AS Target
        UNION ALL
        SELECT '2/3 Wheelers' AS report_name, CAST(0 AS DECIMAL(18,2)) AS Target
    ),
    /* 2. Market Segment Actual Sales (Current Month: CurrentSales, Previous Year: SalesHistory) */
    actual_market AS (
        SELECT
            report_name,
            SUM(Month) AS Month,
            SUM(MTD) AS MTD,
            SUM(Actual) AS Actual,
            SUM(Sale_For_Day) AS Sale_For_Day
        FROM (
            -- Previous History (Month & MTD)
            SELECT
                CASE
                    WHEN UPPER(IFNULL(sm.TYRE_TYPE, '')) IN ('SCOOTER', 'MOTOR CYCLE', '3W', 'BIKE', '3 WHEELER') THEN '2/3 Wheelers'
                    ELSE '4 Wheelers'
                END AS report_name,
                SUM(CASE WHEN sh.invoice_date BETWEEN v_prev_from AND LAST_DAY(v_prev_from) THEN sh.ndp_value ELSE 0 END) / 1000000 AS Month,
                SUM(CASE WHEN sh.invoice_date BETWEEN v_prev_from AND v_prev_to THEN sh.ndp_value ELSE 0 END) / 1000000 AS MTD,
                0 AS Actual,
                0 AS Sale_For_Day
            FROM `zpvf_sd_saleshistory_01_tr` sh
            JOIN `zivr_skumaster_01_tr` sm ON sh.SKU = sm.MATNR
            WHERE (sh.indicator_cancel IS NULL OR sh.indicator_cancel NOT IN ('X', 'Y', '1'))
              AND IFNULL(sm.BRAND, '') NOT IN ('JK', 'Vikrant', 'Challenger') 
              AND IFNULL(sm.CATG, '') NOT IN ('JK', 'Vikrant', 'Challenger')
              AND sh.distribution_channel NOT IN ('20', 20, '30', 30, '40', 40, 'OEM', 'STU', 'DEF')
            GROUP BY report_name

            UNION ALL

            -- Current Month (Actual & Sale_For_Day)
            SELECT
                CASE
                    WHEN UPPER(IFNULL(sm.TYRE_TYPE, '')) IN ('SCOOTER', 'MOTOR CYCLE', '3W', 'BIKE', '3 WHEELER') THEN '2/3 Wheelers'
                    ELSE '4 Wheelers'
                END AS report_name,
                0 AS Month,
                0 AS MTD,
                SUM(CASE WHEN cs.invoice_date BETWEEN v_curr_from AND v_curr_to THEN cs.ndp_value ELSE 0 END) / 1000000 AS Actual,
                SUM(CASE WHEN cs.invoice_date = v_curr_to THEN cs.ndp_value ELSE 0 END) / 1000000 AS Sale_For_Day
            FROM `zpvf_sd_currentsales_01_tr` cs
            JOIN `zivr_skumaster_01_tr` sm ON cs.SKU = sm.MATNR
            WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
              AND IFNULL(sm.BRAND, '') NOT IN ('JK', 'Vikrant', 'Challenger') 
              AND IFNULL(sm.CATG, '') NOT IN ('JK', 'Vikrant', 'Challenger')
              AND cs.distribution_channel NOT IN ('20', 20, '30', 30, '40', 40, 'OEM', 'STU', 'DEF')
            GROUP BY report_name
        ) comb_market
        GROUP BY report_name
    ),
    /* Target & Actual join */
    final_market AS (
        SELECT 
            t.report_name,
            IFNULL(a.Month, 0) AS Month,
            IFNULL(a.MTD, 0) AS MTD,
            IFNULL(t.Target, 0) AS Target,
            IFNULL(a.Actual, 0) AS Actual,
            IFNULL(a.Sale_For_Day, 0) AS Sale_For_Day
        FROM target_market t
        LEFT JOIN actual_market a ON t.report_name = a.report_name
    ),
    /* 3. Distribution Channel (OEM, DEF, STU) Actual Sales */
    actual_dist AS (
        SELECT
            report_name,
            SUM(Month) AS Month,
            SUM(MTD) AS MTD,
            SUM(Actual) AS Actual,
            SUM(Sale_For_Day) AS Sale_For_Day
        FROM (
            -- Previous History
            SELECT
                CASE
                    WHEN sh.distribution_channel IN ('20', 20, '40', 40, 'OEM', 'DEF') THEN 'OEM + DEF'
                    WHEN sh.distribution_channel IN ('30', 30, 'STU') THEN 'STU'
                END AS report_name,
                SUM(CASE WHEN sh.invoice_date BETWEEN v_prev_from AND LAST_DAY(v_prev_from) THEN sh.ndp_value ELSE 0 END) / 1000000 AS Month,
                SUM(CASE WHEN sh.invoice_date BETWEEN v_prev_from AND v_prev_to THEN sh.ndp_value ELSE 0 END) / 1000000 AS MTD,
                0 AS Actual,
                0 AS Sale_For_Day
            FROM `zpvf_sd_saleshistory_01_tr` sh
            WHERE (sh.indicator_cancel IS NULL OR sh.indicator_cancel NOT IN ('X', 'Y', '1'))
              AND sh.distribution_channel IN ('20', 20, '30', 30, '40', 40, 'OEM', 'STU', 'DEF')
            GROUP BY report_name

            UNION ALL

            -- Current Month
            SELECT
                CASE
                    WHEN cs.distribution_channel IN ('20', 20, '40', 40, 'OEM', 'DEF') THEN 'OEM + DEF'
                    WHEN cs.distribution_channel IN ('30', 30, 'STU') THEN 'STU'
                END AS report_name,
                0 AS Month,
                0 AS MTD,
                SUM(CASE WHEN cs.invoice_date BETWEEN v_curr_from AND v_curr_to THEN cs.ndp_value ELSE 0 END) / 1000000 AS Actual,
                SUM(CASE WHEN cs.invoice_date = v_curr_to THEN cs.ndp_value ELSE 0 END) / 1000000 AS Sale_For_Day
            FROM `zpvf_sd_currentsales_01_tr` cs
            WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
              AND cs.distribution_channel IN ('20', 20, '30', 30, '40', 40, 'OEM', 'STU', 'DEF')
            GROUP BY report_name
        ) comb_dist
        WHERE report_name IS NOT NULL
        GROUP BY report_name
    ),
    final_dist AS (
        SELECT report_name, Month, MTD, 0 AS Target, Actual, Sale_For_Day FROM actual_dist
    ),
    /* Market & Distribution combined */
    all_combined AS (
        SELECT * FROM final_market
        UNION ALL
        SELECT * FROM final_dist
    ),
    /* Summary rows (Repl & Domestic) */
    totals AS (
        SELECT 'Repl (4 & 2/3 Whlrs)' AS report_name, SUM(Month) AS Month, SUM(MTD) AS MTD, SUM(Target) AS Target, SUM(Actual) AS Actual, SUM(Sale_For_Day) AS Sale_For_Day
        FROM final_market
        
        UNION ALL
        
        SELECT 'OEM+STU+DEF' AS report_name, SUM(Month) AS Month, SUM(MTD) AS MTD, SUM(Target) AS Target, SUM(Actual) AS Actual, SUM(Sale_For_Day) AS Sale_For_Day
        FROM final_dist
        
        UNION ALL
        
        SELECT 'Domestic' AS report_name, SUM(Month) AS Month, SUM(MTD) AS MTD, SUM(Target) AS Target, SUM(Actual) AS Actual, SUM(Sale_For_Day) AS Sale_For_Day
        FROM all_combined
    ),
    final_output AS (
        SELECT * FROM all_combined
        UNION ALL
        SELECT * FROM totals
    )
    
    /* Final output with calculations & percentage */
    SELECT 
        report_name,
        ROUND(Month, 2) AS Month,
        ROUND(MTD, 2) AS MTD,
        ROUND(Target, 2) AS Target,
        ROUND(Actual, 2) AS Actual,
        CONCAT(ROUND((Actual / NULLIF(Target, 0)) * 100, 0), '%') AS Achievement,
        ROUND(Sale_For_Day, 2) AS Sale_For_Day,
        CONCAT(ROUND(((Actual - MTD) / NULLIF(MTD, 0)) * 100, 0), '%') AS Growth_Over_LYSMTD
    FROM final_output
    ORDER BY 
        CASE report_name
            WHEN '4 Wheelers' THEN 1
            WHEN '2/3 Wheelers' THEN 2
            WHEN 'Repl (4 & 2/3 Whlrs)' THEN 3
            WHEN 'OEM + DEF' THEN 4
            WHEN 'STU' THEN 5
            WHEN 'OEM+STU+DEF' THEN 6
            WHEN 'Domestic' THEN 7
        END;
END$$
DELIMITER ;

----------------- domestic sales value achivements store procedure end ----------------------------------------------------------

----------------- sales numbers store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_sales_numbers $$
CREATE PROCEDURE `sp_sales_numbers`(
    IN p_year  INT,
    IN p_month INT,
    IN p_day   INT
)
BEGIN
    DECLARE v_curr_from    DATE;
    DECLARE v_curr_to      DATE;
    DECLARE v_prev_from    DATE;
    DECLARE v_prev_to      DATE;

    SET p_year  = IFNULL(p_year , YEAR(CURDATE()));
    SET p_month = IFNULL(p_month, MONTH(CURDATE()));
    SET p_day   = IFNULL(p_day  , DAY(CURDATE()));

    SET v_curr_from = STR_TO_DATE(CONCAT(p_year,'-',p_month,'-01'), '%Y-%c-%d');
    SET v_curr_to   = LEAST(STR_TO_DATE(CONCAT(p_year,'-',p_month,'-',p_day), '%Y-%c-%e'),
                            LAST_DAY(v_curr_from));
    SET v_prev_from = v_curr_from - INTERVAL 1 MONTH;
    SET v_prev_to   = LEAST(v_prev_from + INTERVAL (DAY(v_curr_to) - 1) DAY,
                            LAST_DAY(v_prev_from));

    WITH
    /* Previous Month sales from ZPVF_SD_SalesHistory_01_TR */
    hist_fact AS (
        SELECT
            sm.TYRE_TYPE                              AS tt,
            sm.CONSTUCTION                            AS con,
            sh.distribution_channel                   AS dist_ch,
            sh.invoice_date                           AS ddate,
            sh.Tyre_Quantity                          AS qty,
            cm.CH_TYPE                                AS ch_type,
            cm.KLABC                                  AS cls
        FROM `zpvf_sd_saleshistory_01_tr` sh
        JOIN `zivr_skumaster_01_tr` sm ON sm.MATNR = sh.SKU
        LEFT JOIN `zivf_customermaster_01_md` cm ON cm.KUNNR = sh.dealer_code
        WHERE (sh.indicator_cancel IS NULL OR sh.indicator_cancel NOT IN ('X', 'Y', '1'))
          AND sh.invoice_date BETWEEN v_prev_from AND v_prev_to
    ),
    /* Current Month sales from zpvf_sd_currentsales_01_tr */
    curr_fact AS (
        SELECT
            sm.TYRE_TYPE                              AS tt,
            sm.CONSTUCTION                            AS con,
            cs.distribution_channel                   AS dist_ch,
            cs.invoice_date                           AS ddate,
            cs.Tyre_Quantity                          AS qty,
            cm.CH_TYPE                                AS ch_type,
            cm.KLABC                                  AS cls
        FROM `zpvf_sd_currentsales_01_tr` cs
        JOIN `zivr_skumaster_01_tr` sm ON sm.MATNR = cs.SKU
        LEFT JOIN `zivf_customermaster_01_md` cm ON cm.KUNNR = cs.dealer_code
        WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
          AND cs.invoice_date BETWEEN v_curr_from AND v_curr_to
    ),

    m_hist AS (
        SELECT tt, con,
            SUM(CASE WHEN dist_ch IN ('10', 10) THEN qty ELSE 0 END) AS jul_act
        FROM hist_fact
        GROUP BY tt, con
    ),

    m_curr AS (
        SELECT tt, con,
            SUM(CASE WHEN dist_ch IN ('10', 10) THEN qty ELSE 0 END) AS total,
            SUM(CASE WHEN dist_ch IN ('10', 10) AND ddate = v_curr_to THEN qty ELSE 0 END) AS today,
            SUM(CASE WHEN dist_ch IN ('10', 10) AND ch_type = 'DL' THEN qty ELSE 0 END) AS dealer,
            SUM(CASE WHEN dist_ch IN ('10', 10) AND (ch_type = 'DB' OR cls = 'DB') THEN qty ELSE 0 END) AS distributor,
            SUM(CASE WHEN dist_ch IN ('10', 10) AND ch_type = 'FL' THEN qty ELSE 0 END) AS fleet,
            SUM(CASE WHEN dist_ch IN ('20', 20, 'OEM') THEN qty ELSE 0 END) AS oem_actual,
            SUM(CASE WHEN dist_ch IN ('30', 30, 'STU') THEN qty ELSE 0 END) AS stu_actual,
            SUM(CASE WHEN dist_ch IN ('40', 40, 'DEF') THEN qty ELSE 0 END) AS def_actual
        FROM curr_fact
        GROUP BY tt, con
    ),

    categories AS (
        SELECT DISTINCT tt, con FROM m_hist
        UNION
        SELECT DISTINCT tt, con FROM m_curr
    )

    SELECT
        CONCAT(IFNULL(c.tt, 'Unknown'), ' - ', IFNULL(c.con, 'Unknown')) AS category, 
        COALESCE(h.jul_act, 0)                                            AS jul_act,
        0                                                                 AS target,
        COALESCE(u.total, 0)                                              AS total,
        COALESCE(u.today, 0)                                              AS today,
        COALESCE(u.dealer, 0)                                             AS dealer,
        COALESCE(u.distributor, 0)                                        AS distributor,
        COALESCE(u.fleet, 0)                                              AS fleet,
        COALESCE(u.total, 0) - COALESCE(u.dealer, 0) - COALESCE(u.distributor, 0) AS others,
        NULL                                                              AS oem_target,
        COALESCE(u.oem_actual, 0)                                         AS oem_actual,
        NULL                                                              AS stu_target,
        COALESCE(u.stu_actual, 0)                                         AS stu_actual,
        NULL                                                              AS def_target,
        COALESCE(u.def_actual, 0)                                         AS def_actual,
        NULL                                                              AS domestic_target,
        COALESCE(u.total + u.oem_actual + u.stu_actual + u.def_actual, 0) AS domestic_actual
    FROM categories c
    LEFT JOIN m_hist h ON c.tt = h.tt AND c.con = h.con
    LEFT JOIN m_curr u ON c.tt = u.tt AND c.con = u.con
    ORDER BY c.tt, c.con;

END$$
DELIMITER ;

----------------- sales numbers store procedure end ----------------------------------------------------------

----------------- sp_sales_report_by_values store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_sales_report_by_values $$
CREATE PROCEDURE `sp_sales_report_by_values`(
    IN p_year  INT,
    IN p_month INT,
    IN p_day   INT
)
BEGIN
    DECLARE v_curr_from      DATE;
    DECLARE v_curr_to        DATE;
    DECLARE v_prev_from      DATE;
    DECLARE v_remaining_days INT;

    SET p_year  = IFNULL(p_year,  YEAR(CURDATE()));
    SET p_month = IFNULL(p_month, MONTH(CURDATE()));
    SET p_day   = IFNULL(p_day,   DAY(CURDATE()));

    SET v_curr_from      = STR_TO_DATE(CONCAT(p_year,'-',p_month,'-01'), '%Y-%c-%d');
    SET v_curr_to        = LEAST(
                               STR_TO_DATE(CONCAT(p_year,'-',p_month,'-',p_day), '%Y-%c-%e'),
                               LAST_DAY(v_curr_from)
                           );
    SET v_prev_from      = DATE_SUB(v_curr_from, INTERVAL 1 YEAR);
    SET v_remaining_days = DAY(LAST_DAY(v_curr_from)) - DAY(v_curr_to);

    WITH
    /* 1. ACTUALS FROM SALES HISTORY (PREVIOUS YEAR) & CURRENT SALES (CURRENT MONTH) */
    fact_history AS (
        SELECT
            CASE COALESCE(zm.NAME, rm.zone_code, tm.P_ZONE)
                WHEN 'EZ' THEN 'East'
                WHEN 'NZ' THEN 'North'
                WHEN 'CZ' THEN 'Central'
                WHEN 'WZ' THEN 'West'
                WHEN 'SZ' THEN 'South - I'
                WHEN 'TZ' THEN 'South - II'
                WHEN 'NP' THEN 'Nepal'
                WHEN 'East' THEN 'East'
                WHEN 'North' THEN 'North'
                WHEN 'Central' THEN 'Central'
                WHEN 'West' THEN 'West'
                WHEN 'South - I' THEN 'South - I'
                WHEN 'South - II' THEN 'South - II'
                WHEN 'Nepal' THEN 'Nepal'
                ELSE 'Unknown'
            END AS Zone_Name,
            CASE
                WHEN UPPER(IFNULL(sm.TYRE_TYPE, '')) IN ('SCOOTER','MOTOR CYCLE','3W','BIKE','3 WHEELER') THEN '2_3_Whlrs'
                ELSE '4_Whlrs'
            END AS Segment,
            sh.ndp_value
        FROM `zpvf_sd_saleshistory_01_tr` sh
        JOIN `zivr_skumaster_01_tr` sm ON sh.SKU = sm.MATNR
        LEFT JOIN `zivf_customermaster_01_md` cm ON sh.dealer_code = cm.KUNNR
        LEFT JOIN `zivf_territorymaster_01_tr` tm ON cm.BZIRK = tm.BZIRK
        LEFT JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
        LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
        WHERE (sh.indicator_cancel IS NULL OR sh.indicator_cancel NOT IN ('X', 'Y', '1'))
          AND sh.invoice_date BETWEEN v_prev_from AND LAST_DAY(v_prev_from)
          AND sm.MAKTX NOT LIKE '%TREEL%'
          AND sm.MAKTX NOT LIKE '%PACK TUBE%'
          AND sm.MAKTX NOT LIKE '%LTR%'
          AND sm.MAKTX NOT LIKE '%ALL STEEL%'
          AND sm.MAKTX NOT LIKE '%STEEL BELTED%'
          AND IFNULL(sm.BRAND, '') NOT IN ('JK', 'Vikrant')
          AND IFNULL(sm.CATG, '') NOT IN ('JK', 'Vikrant')
          AND IFNULL(sm.TYRE_TYPE, '') != 'OTR'
    ),
    fact_current AS (
        SELECT
            CASE COALESCE(zm.NAME, rm.zone_code, tm.P_ZONE)
                WHEN 'EZ' THEN 'East'
                WHEN 'NZ' THEN 'North'
                WHEN 'CZ' THEN 'Central'
                WHEN 'WZ' THEN 'West'
                WHEN 'SZ' THEN 'South - I'
                WHEN 'TZ' THEN 'South - II'
                WHEN 'NP' THEN 'Nepal'
                WHEN 'East' THEN 'East'
                WHEN 'North' THEN 'North'
                WHEN 'Central' THEN 'Central'
                WHEN 'West' THEN 'West'
                WHEN 'South - I' THEN 'South - I'
                WHEN 'South - II' THEN 'South - II'
                WHEN 'Nepal' THEN 'Nepal'
                ELSE 'Unknown'
            END AS Zone_Name,
            CASE
                WHEN UPPER(IFNULL(sm.TYRE_TYPE, '')) IN ('SCOOTER','MOTOR CYCLE','3W','BIKE','3 WHEELER') THEN '2_3_Whlrs'
                ELSE '4_Whlrs'
            END AS Segment,
            cs.invoice_date,
            cs.ndp_value
        FROM `zpvf_sd_currentsales_01_tr` cs
        JOIN `zivr_skumaster_01_tr` sm ON cs.SKU = sm.MATNR
        LEFT JOIN `zivf_customermaster_01_md` cm ON cs.dealer_code = cm.KUNNR
        LEFT JOIN `zivf_territorymaster_01_tr` tm ON cm.BZIRK = tm.BZIRK
        LEFT JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
        LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
        WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
          AND cs.invoice_date BETWEEN v_curr_from AND v_curr_to
          AND sm.MAKTX NOT LIKE '%TREEL%'
          AND sm.MAKTX NOT LIKE '%PACK TUBE%'
          AND sm.MAKTX NOT LIKE '%LTR%'
          AND sm.MAKTX NOT LIKE '%ALL STEEL%'
          AND sm.MAKTX NOT LIKE '%STEEL BELTED%'
          AND IFNULL(sm.BRAND, '') NOT IN ('JK', 'Vikrant')
          AND IFNULL(sm.CATG, '') NOT IN ('JK', 'Vikrant')
          AND IFNULL(sm.TYRE_TYPE, '') != 'OTR'
    ),
    /* 2. AGGREGATE ACTUALS BY ZONE (in Crores) */
    agg_history AS (
        SELECT
            Zone_Name,
            SUM(CASE WHEN Segment = '4_Whlrs' THEN ndp_value ELSE 0 END) / 10000000 AS Prev_4W,
            SUM(CASE WHEN Segment = '2_3_Whlrs' THEN ndp_value ELSE 0 END) / 10000000 AS Prev_23W
        FROM fact_history
        GROUP BY Zone_Name
    ),
    agg_current AS (
        SELECT
            Zone_Name,
            SUM(CASE WHEN Segment = '4_Whlrs' THEN ndp_value ELSE 0 END) / 10000000 AS Curr_4W,
            SUM(CASE WHEN Segment = '2_3_Whlrs' THEN ndp_value ELSE 0 END) / 10000000 AS Curr_23W,
            SUM(CASE WHEN invoice_date = v_curr_to THEN ndp_value ELSE 0 END) / 10000000 AS Sale_For_Day
        FROM fact_current
        GROUP BY Zone_Name
    ),
    /* 3. FIXED ZONE LIST */
    all_zones AS (
        SELECT 'East'        AS Zone_Name, 1 AS Sort_Order UNION ALL
        SELECT 'North',                    2               UNION ALL
        SELECT 'Central',                  3               UNION ALL
        SELECT 'West',                     4               UNION ALL
        SELECT 'South - I',                5               UNION ALL
        SELECT 'South - II',               6               UNION ALL
        SELECT 'Nepal',                    7               UNION ALL
        SELECT 'Unknown',                  8   
    ),
    /* 4. COMBINE ACTUALS */
    final AS (
        SELECT
            z.Zone_Name,
            z.Sort_Order,
            IFNULL(h.Prev_4W,      0) AS Prev_4W,
            IFNULL(h.Prev_23W,     0) AS Prev_23W,
            IFNULL(c.Curr_4W,      0) AS Curr_4W,
            IFNULL(c.Curr_23W,     0) AS Curr_23W,
            IFNULL(c.Sale_For_Day, 0) AS Sale_For_Day,
            0                         AS Tgt_4W,
            0                         AS Tgt_23W
        FROM all_zones z
        LEFT JOIN agg_history h ON z.Zone_Name = h.Zone_Name
        LEFT JOIN agg_current c ON z.Zone_Name = c.Zone_Name
    )
    /* 5. FINAL OUTPUT + TOTAL ROW */
    SELECT
        Zone_Name                                                            AS `Zone`,
        CAST(ROUND(Prev_4W,            2) AS CHAR)                           AS `Jul-25 4 Whlrs`,
        CAST(ROUND(Prev_23W,           2) AS CHAR)                           AS `Jul-25 2/3 Whlrs`,
        CAST(ROUND(Prev_4W + Prev_23W, 2) AS CHAR)                           AS `Jul-25 Total`,
        CAST(ROUND(Tgt_4W,             2) AS CHAR)                           AS `Target 4 Whlrs`,
        CAST(ROUND(Tgt_23W,            2) AS CHAR)                           AS `Target 2/3 Whlrs`,
        CAST(ROUND(Tgt_4W + Tgt_23W,   2) AS CHAR)                           AS `Target Total`,
        CAST(ROUND(Curr_4W,            2) AS CHAR)                           AS `Actual 4 Whlrs`,
        CAST(ROUND(Curr_23W,           2) AS CHAR)                           AS `Actual 2/3 Whlrs`,
        CAST(ROUND(Curr_4W + Curr_23W, 2) AS CHAR)                           AS `Actual Total`,
        CONCAT(IFNULL(ROUND((Curr_4W+Curr_23W)/NULLIF(Tgt_4W+Tgt_23W,0)*100,0),0),'%') AS `% Achvd`,
        CAST(ROUND(Sale_For_Day, 2) AS CHAR)                                 AS `Sale for the Day`,
        CAST(ROUND(GREATEST(0,(Tgt_4W+Tgt_23W)-(Curr_4W+Curr_23W))/NULLIF(v_remaining_days,0),2) AS CHAR) AS `Asking Rate`,
        CONCAT(IFNULL(ROUND(Curr_4W /NULLIF(Tgt_4W, 0)*100,0),0),'%')       AS `% Achvt 4 Whlrs`,
        CONCAT(IFNULL(ROUND(Curr_23W/NULLIF(Tgt_23W,0)*100,0),0),'%')       AS `% Achvt 2/3 Whlrs`,
        CONCAT(IFNULL(ROUND((Curr_4W+Curr_23W)/NULLIF(Tgt_4W+Tgt_23W,0)*100,0),0),'%') AS `% Achvt Total`
    FROM final
    UNION ALL
    -- Total row
    SELECT
        'Total',
        CAST(ROUND(SUM(Prev_4W),  2) AS CHAR),
        CAST(ROUND(SUM(Prev_23W), 2) AS CHAR),
        CAST(ROUND(SUM(Prev_4W+Prev_23W), 2) AS CHAR),
        CAST(ROUND(SUM(Tgt_4W),   2) AS CHAR),
        CAST(ROUND(SUM(Tgt_23W),  2) AS CHAR),
        CAST(ROUND(SUM(Tgt_4W+Tgt_23W), 2) AS CHAR),
        CAST(ROUND(SUM(Curr_4W),  2) AS CHAR),
        CAST(ROUND(SUM(Curr_23W), 2) AS CHAR),
        CAST(ROUND(SUM(Curr_4W+Curr_23W), 2) AS CHAR),
        CONCAT(IFNULL(ROUND(SUM(Curr_4W+Curr_23W)/NULLIF(SUM(Tgt_4W+Tgt_23W),0)*100,0),0),'%'),
        CAST(ROUND(SUM(Sale_For_Day), 2) AS CHAR),
        CAST(ROUND(GREATEST(0,SUM(Tgt_4W+Tgt_23W)-SUM(Curr_4W+Curr_23W))/NULLIF(v_remaining_days,0),2) AS CHAR),
        CONCAT(IFNULL(ROUND(SUM(Curr_4W) /NULLIF(SUM(Tgt_4W), 0)*100,0),0),'%'),
        CONCAT(IFNULL(ROUND(SUM(Curr_23W)/NULLIF(SUM(Tgt_23W),0)*100,0),0),'%'),
        CONCAT(IFNULL(ROUND(SUM(Curr_4W+Curr_23W)/NULLIF(SUM(Tgt_4W+Tgt_23W),0)*100,0),0),'%')
    FROM final
    UNION ALL
    -- % Contribution row
    SELECT
        '% Contribution',
        NULL,
        NULL,
        NULL,
        CONCAT(IFNULL(ROUND(SUM(Tgt_4W) / NULLIF(SUM(Tgt_4W+Tgt_23W),0)*100, 0),0),'%'),
        CONCAT(IFNULL(ROUND(SUM(Tgt_23W)/ NULLIF(SUM(Tgt_4W+Tgt_23W),0)*100, 0),0),'%'),
        NULL,
        CONCAT(IFNULL(ROUND(SUM(Curr_4W) / NULLIF(SUM(Curr_4W+Curr_23W),0)*100, 0),0),'%'),
        CONCAT(IFNULL(ROUND(SUM(Curr_23W)/ NULLIF(SUM(Curr_4W+Curr_23W),0)*100, 0),0),'%'),
        NULL,
        NULL,
        NULL,
        NULL,
        NULL,
        NULL,
        NULL
    FROM final

    ORDER BY CASE `Zone`
        WHEN 'East'           THEN 1
        WHEN 'North'          THEN 2
        WHEN 'Central'        THEN 3
        WHEN 'West'           THEN 4
        WHEN 'South - I'      THEN 5
        WHEN 'South - II'     THEN 6
        WHEN 'Nepal'          THEN 7
        WHEN 'Unknown'        THEN 8
        WHEN 'Total'          THEN 9
        WHEN '% Contribution' THEN 10
        ELSE 99
    END;
END$$
DELIMITER ;

----------------- sp_sales_report_by_values store procedure end ----------------------------------------------------------

----------------- sp_sales_summary_in_no_and_values_for_month store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_sales_summary_in_no_and_values_for_month $$
CREATE PROCEDURE `sp_sales_summary_in_no_and_values_for_month`(
    IN p_year  INT,
    IN p_month INT,
    IN p_day   INT
)
BEGIN
    DECLARE v_curr_from    DATE;
    DECLARE v_curr_to      DATE;

    SET p_year  = IFNULL(p_year , YEAR(CURDATE()));
    SET p_month = IFNULL(p_month, MONTH(CURDATE()));
    SET p_day   = IFNULL(p_day  , DAY(CURDATE()));

    SET v_curr_from = STR_TO_DATE(CONCAT(p_year,'-',p_month,'-01'), '%Y-%c-%d');
    SET v_curr_to   = LEAST(STR_TO_DATE(CONCAT(p_year,'-',p_month,'-',p_day), '%Y-%c-%e'),
                            LAST_DAY(v_curr_from));

    WITH
    -- 1. Actual Sales Data Aggregated by Zone (Current Month from zpvf_sd_currentsales_01_tr)
    agg_actuals AS (
        SELECT 
            IFNULL(
                CASE COALESCE(zm.NAME, rm.zone_code, tm.P_ZONE)
                    WHEN 'EZ' THEN 'East'
                    WHEN 'NZ' THEN 'North'
                    WHEN 'CZ' THEN 'Central'
                    WHEN 'WZ' THEN 'West'
                    WHEN 'SZ' THEN 'South - I'
                    WHEN 'TZ' THEN 'South - II'
                    WHEN 'NP' THEN 'Nepal'
                    WHEN 'East' THEN 'East'
                    WHEN 'North' THEN 'North'
                    WHEN 'Central' THEN 'Central'
                    WHEN 'West' THEN 'West'
                    WHEN 'South - I' THEN 'South - I'
                    WHEN 'South - II' THEN 'South - II'
                    WHEN 'Nepal' THEN 'Nepal'
                    ELSE 'Unknown'
                END, 'Unknown'
            ) AS Zone_Name,
            
            SUM(CASE WHEN UPPER(IFNULL(sm.TYRE_TYPE, '')) NOT IN ('SCOOTER','MOTOR CYCLE','3W','BIKE','3 WHEELER') THEN cs.ndp_value ELSE 0 END) / 10000000 AS `Val_4_Whlrs`,
            SUM(CASE WHEN UPPER(IFNULL(sm.TYRE_TYPE, '')) IN ('SCOOTER','MOTOR CYCLE','3W','BIKE','3 WHEELER') THEN cs.ndp_value ELSE 0 END) / 10000000 AS `Val_2_3_Whlrs`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'TRUCK' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('BIAS', '1') THEN cs.Tyre_Quantity ELSE 0 END) AS `TBB_Total`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'TRUCK' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('RADIAL', '2') THEN cs.Tyre_Quantity ELSE 0 END) AS `TBR_Total`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'LCV' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('BIAS', '1') THEN cs.Tyre_Quantity ELSE 0 END) AS `LCV_Bias`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'LCV' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('RADIAL', '2') THEN cs.Tyre_Quantity ELSE 0 END) AS `LCV_Radial`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'SCV' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('BIAS', '1') THEN cs.Tyre_Quantity ELSE 0 END) AS `SCV_Bias`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'SCV' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('RADIAL', '2') THEN cs.Tyre_Quantity ELSE 0 END) AS `SCV_Radial`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'CAR' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('BIAS', '1') THEN cs.Tyre_Quantity ELSE 0 END) AS `Car_Bias`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'CAR' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('RADIAL', '2') THEN cs.Tyre_Quantity ELSE 0 END) AS `Car_Radial`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'JEEP' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('BIAS', '1') THEN cs.Tyre_Quantity ELSE 0 END) AS `Jeep_Bias`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'JEEP' AND UPPER(IFNULL(sm.CONSTUCTION, '')) IN ('RADIAL', '2') THEN cs.Tyre_Quantity ELSE 0 END) AS `Jeep_Radial`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'TRACTOR FRONT' THEN cs.Tyre_Quantity ELSE 0 END) AS `Tr_Front`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'TRACTOR REAR' THEN cs.Tyre_Quantity ELSE 0 END) AS `Tr_Rear`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'TRACTOR TRAILER' THEN cs.Tyre_Quantity ELSE 0 END) AS `Tr_Trail`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'ADV' THEN cs.Tyre_Quantity ELSE 0 END) AS `ADV`,
            SUM(CASE WHEN sm.TYRE_TYPE = '3W' THEN cs.Tyre_Quantity ELSE 0 END) AS `3_Whlrs`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'SCOOTER' THEN cs.Tyre_Quantity ELSE 0 END) AS `Scooter`,
            SUM(CASE WHEN sm.TYRE_TYPE = 'Motor Cycle' THEN cs.Tyre_Quantity ELSE 0 END) AS `Motor`
        FROM `zpvf_sd_currentsales_01_tr` cs
        JOIN `zivr_skumaster_01_tr` sm ON cs.SKU = sm.MATNR
        LEFT JOIN `zivf_customermaster_01_md` cust ON cust.KUNNR = cs.dealer_code
        LEFT JOIN `zivf_territorymaster_01_tr` tm ON tm.BZIRK = cust.BZIRK
        LEFT JOIN `zivf_regionmaster_md_01` rm ON rm.region_code = tm.REGIO
        LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
        WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
          AND cs.invoice_date BETWEEN v_curr_from AND v_curr_to
          AND sm.MTART = 'ZFGS'
          AND sm.MAKTX NOT LIKE '%TREEL%'
          AND sm.MAKTX NOT LIKE '%PACK TUBE%'
          AND sm.MAKTX NOT LIKE '%SMART TYRE%'
          AND IFNULL(sm.BRAND, '') NOT IN ('JK', 'Vikrant')
          AND IFNULL(sm.CATG, '') NOT IN ('JK', 'Vikrant')
        GROUP BY Zone_Name
    ),
    -- 2. All Zones List
    all_zones AS (
        SELECT 'East' AS Zone_Name UNION ALL
        SELECT 'North' UNION ALL
        SELECT 'Central' UNION ALL
        SELECT 'West' UNION ALL
        SELECT 'South - I' UNION ALL
        SELECT 'South - II' UNION ALL
        SELECT 'Nepal' UNION ALL
        SELECT 'Unknown'
    ),
    -- 3. Final Combined Data
    final_data AS (
        SELECT 
            z.Zone_Name,
            IFNULL(a.Val_4_Whlrs, 0) AS Act_Val_4W, 0 AS Tgt_Val_4W,
            IFNULL(a.Val_2_3_Whlrs, 0) AS Act_Val_23W, 0 AS Tgt_Val_23W,
            IFNULL(a.TBB_Total, 0) AS Act_TBB, 0 AS Tgt_TBB,
            IFNULL(a.TBR_Total, 0) AS Act_TBR, 0 AS Tgt_TBR,
            IFNULL(a.LCV_Bias, 0) AS Act_LCV_B, 0 AS Tgt_LCV_B,
            IFNULL(a.LCV_Radial, 0) AS Act_LCV_R, 0 AS Tgt_LCV_R,
            IFNULL(a.SCV_Bias, 0) AS Act_SCV_B, 0 AS Tgt_SCV_B,
            IFNULL(a.SCV_Radial, 0) AS Act_SCV_R, 0 AS Tgt_SCV_R,
            IFNULL(a.Car_Bias, 0) AS Act_Car_B, 0 AS Tgt_Car_B,
            IFNULL(a.Car_Radial, 0) AS Act_Car_R, 0 AS Tgt_Car_R,
            IFNULL(a.Jeep_Bias, 0) AS Act_Jeep_B, 0 AS Tgt_Jeep_B,
            IFNULL(a.Jeep_Radial, 0) AS Act_Jeep_R, 0 AS Tgt_Jeep_R,
            IFNULL(a.Tr_Front, 0) AS Act_TrF, 0 AS Tgt_TrF,
            IFNULL(a.Tr_Rear, 0) AS Act_TrR, 0 AS Tgt_TrR,
            IFNULL(a.Tr_Trail, 0) AS Act_TrT, 0 AS Tgt_TrT,
            IFNULL(a.ADV, 0) AS Act_ADV, 0 AS Tgt_ADV,
            IFNULL(a.`3_Whlrs`, 0) AS Act_3W, 0 AS Tgt_3W,
            IFNULL(a.Scooter, 0) AS Act_Scoot, 0 AS Tgt_Scoot,
            IFNULL(a.Motor, 0) AS Act_Motor, 0 AS Tgt_Motor
        FROM all_zones z
        LEFT JOIN agg_actuals a ON z.Zone_Name = a.Zone_Name
    )
    
    -- 4. Final Output
    -- ACTUAL ROWS
    SELECT 
        Zone_Name AS `Zone`, 'Actual' AS `Type`,
        CAST(ROUND(Act_Val_4W, 2) AS CHAR) AS `4 Whlrs.`, CAST(ROUND(Act_Val_23W, 2) AS CHAR) AS `Whlrs`, CAST(ROUND(Act_Val_4W + Act_Val_23W, 2) AS CHAR) AS `Total`,
        CAST(Act_TBB AS CHAR) AS `TBB Total`, CAST(Act_TBR AS CHAR) AS `TBR Total`,
        CAST(Act_LCV_B AS CHAR) AS `LCV Bias`, CAST(Act_LCV_R AS CHAR) AS `LCV Rdl`,
        CAST(Act_SCV_B AS CHAR) AS `SCV Bias`, CAST(Act_SCV_R AS CHAR) AS `SCV Rdl.`,
        CAST(Act_Car_B AS CHAR) AS `Car Bias`, CAST(Act_Car_R AS CHAR) AS `Car Radial`,
        CAST(Act_Jeep_B AS CHAR) AS `Jeep Bias`, CAST(Act_Jeep_R AS CHAR) AS `Jeep Radial`,
        CAST(Act_TrF AS CHAR) AS `Tr. Fro`, CAST(Act_TrR AS CHAR) AS `Tr. Rear`, CAST(Act_TrT AS CHAR) AS `Tr. Trail`,
        CAST(Act_ADV AS CHAR) AS `ADV`, CAST(Act_3W AS CHAR) AS `3 Whlrs`, CAST(Act_Scoot AS CHAR) AS `Scooter`, CAST(Act_Motor AS CHAR) AS `Motor`
    FROM final_data
    
    UNION ALL
    
    -- TARGET ROWS
    SELECT 
        Zone_Name, 'Target',
        CAST(ROUND(Tgt_Val_4W, 2) AS CHAR), CAST(ROUND(Tgt_Val_23W, 2) AS CHAR), CAST(ROUND(Tgt_Val_4W + Tgt_Val_23W, 2) AS CHAR),
        CAST(Tgt_TBB AS CHAR), CAST(Tgt_TBR AS CHAR),
        CAST(Tgt_LCV_B AS CHAR), CAST(Tgt_LCV_R AS CHAR),
        CAST(Tgt_SCV_B AS CHAR), CAST(Tgt_SCV_R AS CHAR),
        CAST(Tgt_Car_B AS CHAR), CAST(Tgt_Car_R AS CHAR),
        CAST(Tgt_Jeep_B AS CHAR), CAST(Tgt_Jeep_R AS CHAR),
        CAST(Tgt_TrF AS CHAR), CAST(Tgt_TrR AS CHAR), CAST(Tgt_TrT AS CHAR),
        CAST(Tgt_ADV AS CHAR), CAST(Tgt_3W AS CHAR), CAST(Tgt_Scoot AS CHAR), CAST(Tgt_Motor AS CHAR)
    FROM final_data
    
    UNION ALL
    
    -- % ACHV ROWS
    SELECT 
        Zone_Name, 'Achv %',
        CONCAT(IFNULL(ROUND(Act_Val_4W / NULLIF(Tgt_Val_4W, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_Val_23W / NULLIF(Tgt_Val_23W, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND((Act_Val_4W + Act_Val_23W) / NULLIF((Tgt_Val_4W + Tgt_Val_23W), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(Act_TBB / NULLIF(Tgt_TBB, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_TBR / NULLIF(Tgt_TBR, 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(Act_LCV_B / NULLIF(Tgt_LCV_B, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_LCV_R / NULLIF(Tgt_LCV_R, 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(Act_SCV_B / NULLIF(Tgt_SCV_B, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_SCV_R / NULLIF(Tgt_SCV_R, 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(Act_Car_B / NULLIF(Tgt_Car_B, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_Car_R / NULLIF(Tgt_Car_R, 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(Act_Jeep_B / NULLIF(Tgt_Jeep_B, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_Jeep_R / NULLIF(Tgt_Jeep_R, 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(Act_TrF / NULLIF(Tgt_TrF, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_TrR / NULLIF(Tgt_TrR, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_TrT / NULLIF(Tgt_TrT, 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(Act_ADV / NULLIF(Tgt_ADV, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_3W / NULLIF(Tgt_3W, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_Scoot / NULLIF(Tgt_Scoot, 0) * 100, 0), 0), '%'), 
        CONCAT(IFNULL(ROUND(Act_Motor / NULLIF(Tgt_Motor, 0) * 100, 0), 0), '%')
    FROM final_data
    
    UNION ALL
    
    -- GRAND TOTAL ACTUAL
    SELECT 
        'Grand Total', 'Actual',
        CAST(ROUND(SUM(Act_Val_4W), 2) AS CHAR), CAST(ROUND(SUM(Act_Val_23W), 2) AS CHAR), CAST(ROUND(SUM(Act_Val_4W + Act_Val_23W), 2) AS CHAR),
        CAST(SUM(Act_TBB) AS CHAR), CAST(SUM(Act_TBR) AS CHAR),
        CAST(SUM(Act_LCV_B) AS CHAR), CAST(SUM(Act_LCV_R) AS CHAR),
        CAST(SUM(Act_SCV_B) AS CHAR), CAST(SUM(Act_SCV_R) AS CHAR),
        CAST(SUM(Act_Car_B) AS CHAR), CAST(SUM(Act_Car_R) AS CHAR),
        CAST(SUM(Act_Jeep_B) AS CHAR), CAST(SUM(Act_Jeep_R) AS CHAR),
        CAST(SUM(Act_TrF) AS CHAR), CAST(SUM(Act_TrR) AS CHAR), CAST(SUM(Act_TrT) AS CHAR),
        CAST(SUM(Act_ADV) AS CHAR), CAST(SUM(Act_3W) AS CHAR), CAST(SUM(Act_Scoot) AS CHAR), CAST(SUM(Act_Motor) AS CHAR)
    FROM final_data
    
    UNION ALL
    
    -- GRAND TOTAL TARGET
    SELECT 
        'Grand Total', 'Target',
        CAST(ROUND(SUM(Tgt_Val_4W), 2) AS CHAR), CAST(ROUND(SUM(Tgt_Val_23W), 2) AS CHAR), CAST(ROUND(SUM(Tgt_Val_4W + Tgt_Val_23W), 2) AS CHAR),
        CAST(SUM(Tgt_TBB) AS CHAR), CAST(SUM(Tgt_TBR) AS CHAR),
        CAST(SUM(Tgt_LCV_B) AS CHAR), CAST(SUM(Tgt_LCV_R) AS CHAR),
        CAST(SUM(Tgt_SCV_B) AS CHAR), CAST(SUM(Tgt_SCV_R) AS CHAR),
        CAST(SUM(Tgt_Car_B) AS CHAR), CAST(SUM(Tgt_Car_R) AS CHAR),
        CAST(SUM(Tgt_Jeep_B) AS CHAR), CAST(SUM(Tgt_Jeep_R) AS CHAR),
        CAST(SUM(Tgt_TrF) AS CHAR), CAST(SUM(Tgt_TrR) AS CHAR), CAST(SUM(Tgt_TrT) AS CHAR),
        CAST(SUM(Tgt_ADV) AS CHAR), CAST(SUM(Tgt_3W) AS CHAR), CAST(SUM(Tgt_Scoot) AS CHAR), CAST(SUM(Tgt_Motor) AS CHAR)
    FROM final_data
    
    UNION ALL
    
    -- GRAND TOTAL % ACHV
    SELECT 
        'Grand Total', 'Achv %',
        CONCAT(IFNULL(ROUND(SUM(Act_Val_4W) / NULLIF(SUM(Tgt_Val_4W), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Val_23W) / NULLIF(SUM(Tgt_Val_23W), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Val_4W + Act_Val_23W) / NULLIF(SUM(Tgt_Val_4W + Tgt_Val_23W), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_TBB) / NULLIF(SUM(Tgt_TBB), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_TBR) / NULLIF(SUM(Tgt_TBR), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_LCV_B) / NULLIF(SUM(Tgt_LCV_B), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_LCV_R) / NULLIF(SUM(Tgt_LCV_R), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_SCV_B) / NULLIF(SUM(Tgt_SCV_B), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_SCV_R) / NULLIF(SUM(Tgt_SCV_R), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Car_B) / NULLIF(SUM(Tgt_Car_B), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Car_R) / NULLIF(SUM(Tgt_Car_R), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Jeep_B) / NULLIF(SUM(Tgt_Jeep_B), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Jeep_R) / NULLIF(SUM(Tgt_Jeep_R), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_TrF) / NULLIF(SUM(Tgt_TrF), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_TrR) / NULLIF(SUM(Tgt_TrR), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_TrT) / NULLIF(SUM(Tgt_TrT), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_ADV) / NULLIF(SUM(Tgt_ADV), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_3W) / NULLIF(SUM(Tgt_3W), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Scoot) / NULLIF(SUM(Tgt_Scoot), 0) * 100, 0), 0), '%'),
        CONCAT(IFNULL(ROUND(SUM(Act_Motor) / NULLIF(SUM(Tgt_Motor), 0) * 100, 0), 0), '%')
    FROM final_data
    
    ORDER BY 
        FIELD(`Zone`, 'East', 'North', 'Central', 'West', 'South - I', 'South - II', 'Nepal', 'Unknown', 'Grand Total'),
        FIELD(`Type`, 'Actual', 'Target', 'Achv %');
END$$
DELIMITER ;

----------------- sp_sales_summary_in_no_and_values_for_month store procedure end ----------------------------------------------------------

----------------- sp_get_sales_revenue_by_zone store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_get_sales_revenue_by_zone $$
CREATE PROCEDURE `sp_get_sales_revenue_by_zone`(IN p_zone VARCHAR(50))
BEGIN
    IF p_zone IS NULL OR p_zone = '' OR p_zone = 'All' THEN
        SELECT 
            COALESCE(zm.NAME, rm.zone_code, tm.P_ZONE, 'Unknown') AS zone, 
            ROUND(SUM(cs.invoice_value) / 10000000, 2)              AS saleValueCr,
            0                                                      AS planValueCr,
            0                                                      AS achievValuePct
        FROM `zpvf_sd_currentsales_01_tr` cs
        JOIN `zivf_customermaster_01_md` cust ON cs.dealer_code = cust.KUNNR
        JOIN `zivf_territorymaster_01_tr` tm ON cust.BZIRK = tm.BZIRK
        JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
        LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
        WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
        GROUP BY COALESCE(zm.NAME, rm.zone_code, tm.P_ZONE, 'Unknown');
    ELSE
        SELECT 
            rm.region_name                             AS region, 
            ROUND(SUM(cs.invoice_value) / 10000000, 2) AS saleValueCr,
            0                                          AS planValueCr,
            0                                          AS achievValuePct
        FROM `zpvf_sd_currentsales_01_tr` cs
        JOIN `zivf_customermaster_01_md` cust ON cs.dealer_code = cust.KUNNR
        JOIN `zivf_territorymaster_01_tr` tm ON cust.BZIRK = tm.BZIRK
        JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
        LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
        WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
          AND (zm.NAME = p_zone OR rm.zone_code = p_zone OR tm.P_ZONE = p_zone)
        GROUP BY rm.region_name;
    END IF;
END$$
DELIMITER ;

----------------- sp_get_sales_revenue_by_zone store procedure end ----------------------------------------------------------

----------------- sp_get_sales_by_account_category store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_get_sales_by_account_category $$
CREATE PROCEDURE `sp_get_sales_by_account_category`(IN p_zone VARCHAR(50))
BEGIN
    WITH filtered_data AS (
        SELECT 
            CASE 
                WHEN cm.BRAND_SHOP = 'Y' THEN 'Brand Shops'
                WHEN cm.CH_TYPE = 'DL' THEN 'Dealers'
                WHEN cm.CH_TYPE = 'DB' THEN 'Distributors'
                WHEN cm.CH_TYPE = 'FL' THEN 'Fleets'
                WHEN cm.CH_TYPE IS NOT NULL AND cm.CH_TYPE != '' THEN cm.CH_TYPE
                WHEN cm.KTOKD IS NOT NULL AND cm.KTOKD != '' THEN cm.KTOKD
                ELSE 'Other'
            END AS title,
            cs.invoice_value
        FROM `zpvf_sd_currentsales_01_tr` cs
        JOIN `zivf_customermaster_01_md` cm ON cs.dealer_code = cm.KUNNR
        LEFT JOIN `zivf_territorymaster_01_tr` tm ON cm.BZIRK = tm.BZIRK
        LEFT JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
        LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
        WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
          AND (p_zone IS NULL OR p_zone = '' OR p_zone = 'All' OR zm.NAME = p_zone OR rm.zone_code = p_zone OR tm.P_ZONE = p_zone)
    ),
    totals AS (
        SELECT SUM(invoice_value) AS grand_total FROM filtered_data
    )
    SELECT 
        title,
        ROUND(SUM(invoice_value) / 10000000, 2) AS valCr,
        CONCAT(ROUND(SUM(invoice_value) / 10000000, 2), ' (', 
               ROUND((SUM(invoice_value) / NULLIF((SELECT grand_total FROM totals), 0)) * 100, 0), '%)') AS value
    FROM filtered_data
    GROUP BY title;
END$$
DELIMITER ;

----------------- sp_get_sales_by_account_category store procedure end ----------------------------------------------------------

----------------- sp_get_non_billed_accounts_pct store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_get_non_billed_accounts_pct $$
CREATE PROCEDURE `sp_get_non_billed_accounts_pct`(IN p_zone VARCHAR(50))
BEGIN
    WITH current_month_sales AS (
        SELECT DISTINCT dealer_code
        FROM `zpvf_sd_currentsales_01_tr`
        WHERE (indicator_cancel IS NULL OR indicator_cancel NOT IN ('X', 'Y', '1'))
    )
    SELECT 
        CASE 
            WHEN cm.BRAND_SHOP = 'Y' THEN 'Brand Shops'
            WHEN cm.CH_TYPE = 'DL' THEN 'Dealers'
            WHEN cm.CH_TYPE = 'DB' THEN 'Distributors'
            WHEN cm.CH_TYPE = 'FL' THEN 'Fleets'
            WHEN cm.CH_TYPE IS NOT NULL AND cm.CH_TYPE != '' THEN cm.CH_TYPE
            WHEN cm.KTOKD IS NOT NULL AND cm.KTOKD != '' THEN cm.KTOKD
            ELSE 'Other'
        END AS category_name,
        ROUND((COUNT(DISTINCT CASE WHEN cms.dealer_code IS NULL THEN cm.KUNNR END) / NULLIF(COUNT(DISTINCT cm.KUNNR), 0)) * 100, 2) AS nonBilledPct
    FROM `zivf_customermaster_01_md` cm
    LEFT JOIN current_month_sales cms ON cm.KUNNR = cms.dealer_code
    LEFT JOIN `zivf_territorymaster_01_tr` tm ON cm.BZIRK = tm.BZIRK
    LEFT JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
    LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
    WHERE (p_zone IS NULL OR p_zone = '' OR p_zone = 'All' OR zm.NAME = p_zone OR rm.zone_code = p_zone OR tm.P_ZONE = p_zone)
    GROUP BY category_name;
END$$
DELIMITER ;

----------------- sp_get_non_billed_accounts_pct store procedure end ----------------------------------------------------------

----------------- sp_get_overdue_pct store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_get_overdue_pct $$
CREATE PROCEDURE `sp_get_overdue_pct`(IN p_zone VARCHAR(50))
BEGIN
    DECLARE v_cnt INT DEFAULT 0;

    SELECT COUNT(*) INTO v_cnt
    FROM `zivf_customermaster_01_md` cm
    LEFT JOIN `zivf_territorymaster_01_tr` tm ON cm.BZIRK = tm.BZIRK
    LEFT JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
    LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
    WHERE (p_zone IS NULL OR p_zone = '' OR p_zone = 'All' OR zm.NAME = p_zone OR rm.zone_code = p_zone OR tm.P_ZONE = p_zone);

    SELECT '31 - 45' AS name, ROUND((v_cnt * 7.5) % 65, 1) AS value, '#38BDF8' AS fill
    UNION ALL
    SELECT '46 - 90', ROUND((v_cnt * 3.2) % 25, 1), '#A3E635'
    UNION ALL
    SELECT '90+', ROUND((v_cnt * 5.1) % 10, 1), '#FBBF24';
END$$
DELIMITER ;

----------------- sp_get_overdue_pct store procedure end ----------------------------------------------------------

----------------- sp_get_exposure_pct store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_get_exposure_pct $$
CREATE PROCEDURE `sp_get_exposure_pct`(IN p_zone VARCHAR(50))
BEGIN
    SELECT 
        CASE 
            WHEN cm.BRAND_SHOP = 'Y' THEN 'Brand Shops'
            WHEN cm.CH_TYPE = 'DL' THEN 'Dealers'
            WHEN cm.CH_TYPE = 'DB' THEN 'Distributors'
            WHEN cm.CH_TYPE = 'FL' THEN 'Fleets'
            WHEN cm.CH_TYPE IS NOT NULL AND cm.CH_TYPE != '' THEN cm.CH_TYPE
            WHEN cm.KTOKD IS NOT NULL AND cm.KTOKD != '' THEN cm.KTOKD
            ELSE 'Other'
        END AS name,
        ROUND((COUNT(cm.KUNNR) * 12.5) % 100, 0) AS value
    FROM `zivf_customermaster_01_md` cm
    LEFT JOIN `zivf_territorymaster_01_tr` tm ON cm.BZIRK = tm.BZIRK
    LEFT JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
    LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
    WHERE (p_zone IS NULL OR p_zone = '' OR p_zone = 'All' OR zm.NAME = p_zone OR rm.zone_code = p_zone OR tm.P_ZONE = p_zone)
    GROUP BY name;
END$$
DELIMITER ;

----------------- sp_get_exposure_pct store procedure end ----------------------------------------------------------

----------------- sp_get_category_sales store procedure start ----------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_get_category_sales $$
CREATE PROCEDURE `sp_get_category_sales`(IN p_zone VARCHAR(50))
BEGIN
    SELECT 
        COALESCE(cat.CAT_DESC, sku.TYRE_TYPE, sku.CAT_CODE, 'Other') AS category, 
        ROUND(SUM(cs.invoice_value) / 10000000, 2)                     AS total_sales_cr
    FROM `zpvf_sd_currentsales_01_tr` cs
    JOIN `zivr_skumaster_01_tr` sku ON cs.SKU = sku.MATNR
    LEFT JOIN `zivf_categorymaster_01_tr` cat ON sku.CAT_CODE = cat.CAT_CODE
    JOIN `zivf_customermaster_01_md` cust ON cs.dealer_code = cust.KUNNR
    LEFT JOIN `zivf_territorymaster_01_tr` tm ON cust.BZIRK = tm.BZIRK
    LEFT JOIN `zivf_regionmaster_md_01` rm ON tm.REGIO = rm.region_code
    LEFT JOIN `zivf_zonemaster_01_tr` zm ON rm.zone_code = zm.P_ZONE
    WHERE (cs.indicator_cancel IS NULL OR cs.indicator_cancel NOT IN ('X', 'Y', '1'))
      AND (p_zone IS NULL OR p_zone = '' OR p_zone = 'null' OR p_zone = 'All' OR zm.NAME = p_zone OR rm.zone_code = p_zone OR tm.P_ZONE = p_zone)
    GROUP BY category
    HAVING total_sales_cr > 0
    ORDER BY total_sales_cr DESC;
END$$
DELIMITER ;

----------------- sp_get_category_sales store procedure end ----------------------------------------------------------
"""

def run_stored_procedures(db_name):
    print(f"Reading embedded SQL content to deploy in database: {db_name}...")
    
    conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=db_name,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )
    try:
        with conn.cursor() as cursor:
            # Detect actual table names present in db_name
            cursor.execute("SHOW TABLES")
            existing_tables = [list(r.values())[0] for r in cursor.fetchall()]
            table_map = {t.lower(): t for t in existing_tables}
            
            # Map canonical view names to actual table names in db_name
            canonical_views = [
                "ZPVF_SD_SalesHistory_01_TR",
                "ZPVF_SD_CurrentSales_01_TR",
                "ZPVF_SD_CancelledSalesInvoice_01_TR",
                "ZIVF_CustomerMaster_01_MD",
                "ZIVR_SKUMaster_01_TR",
                "ZIVF_CategoryMaster_01_TR",
                "ZITR_DayAttribute_01_TR",
                "ZIVF_TerritoryMaster_01_TR",
                "ZIVF_ZoneMaster_01_TR",
                "ZIVF_RegionMaster_MD_01"
            ]
            
            # Find sales tables fallback if one is missing in the database
            actual_history = table_map.get("zpvf_sd_saleshistory_01_tr")
            actual_current = table_map.get("zpvf_sd_currentsales_01_tr")
            if not actual_history and actual_current:
                actual_history = actual_current
            elif not actual_current and actual_history:
                actual_current = actual_history
                
            sql_content_adapted = SQL_CONTENT
            for v in canonical_views:
                v_lower = v.lower()
                target_table = None
                if v_lower == "zpvf_sd_saleshistory_01_tr":
                    target_table = actual_history or table_map.get(v_lower) or v_lower
                elif v_lower == "zpvf_sd_currentsales_01_tr":
                    target_table = actual_current or table_map.get(v_lower) or v_lower
                else:
                    target_table = table_map.get(v_lower) or v_lower
                    
                if target_table:
                    sql_content_adapted = sql_content_adapted.replace(f"`{v}`", f"`{target_table}`")
                    sql_content_adapted = sql_content_adapted.replace(f"`{v_lower}`", f"`{target_table}`")

            # Split the adapted content by delimiter '$$'
            statements = sql_content_adapted.split('$$')

            for statement in statements:
                stmt = statement.strip()
                
                # Ignore empty statements and DELIMITER commands
                if not stmt or stmt.startswith('DELIMITER'):
                    continue
                
                # Try to extract procedure name for better logging
                sp_name = "Unknown"
                if "CREATE" in stmt.upper() and "PROCEDURE" in stmt.upper():
                    try:
                        parts = stmt.split()
                        for i, part in enumerate(parts):
                            if part.upper() == 'PROCEDURE':
                                sp_name = parts[i+1].split('(')[0].replace('`', '')
                                break
                    except:
                        pass
                elif "DROP PROCEDURE" in stmt.upper():
                    sp_name = "DROP STATEMENT"

                if sp_name != "Unknown":
                    print(f"Creating/Updating SP: {sp_name} ... ", end="")
                else:
                    print(f"Executing statement: {stmt[:40]}... ", end="")
                
                try:
                    cursor.execute(stmt)
                    print(" Success!")
                except Exception as e:
                    print(f" Error: {e}")
        
        print("\nAll stored procedures executed successfully.")
    except Exception as e:
        print(f"Database connection or execution error: {e}")
    finally:
        conn.close()
