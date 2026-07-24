from flask import request, send_file, jsonify
import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

def generate_domestic_sales_excel(conn, session_id, year, month, day):
    cursor = None
    try:
        try:
            # For mysql.connector
            cursor = conn.cursor(dictionary=True)
            is_mysql_connector = True
        except TypeError:
            # For pymysql
            import pymysql
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            is_mysql_connector = False
        print(f"[Excel Export] Starting SP calls for {year}-{month}-{day}", flush=True)
        
        sync_row = None
        print(f"[Excel Export] Received session_id: {session_id}, year: {year}, month: {month}, day: {day}", flush=True)
        # Handle dynamic database based on session_id and where SP exists
        if session_id:
            cursor.execute("""
                SELECT new_user_db, external_database
                FROM external_db_sync_log 
                WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db != ''
                ORDER BY id DESC LIMIT 1
            """, (session_id,))
            sync_rows = cursor.fetchall()
            print(f"[Excel Export] DB Sync Log returned {len(sync_rows)} rows for session {session_id}.", flush=True)
            if sync_rows:
                sync_row = sync_rows[0]
                new_user_db = sync_row['new_user_db']
                external_database = sync_row['external_database']
                
                db_to_use = new_user_db
                print(f"[Excel Export] Selected DB: {db_to_use} (Fallback: {external_database})", flush=True)
                
                # Check if SP exists in new_user_db
                cursor.execute("""
                    SELECT ROUTINE_NAME 
                    FROM information_schema.routines 
                    WHERE ROUTINE_TYPE='PROCEDURE' 
                      AND ROUTINE_SCHEMA=%s 
                      AND ROUTINE_NAME='sp_domestic_sales_report'
                """, (new_user_db,))
                
                routine_rows = cursor.fetchall()
                if not routine_rows and external_database:
                    # Fallback to external_database
                    db_to_use = external_database
                    
                # Explicitly call the SP using the correct fully qualified DB name
                print(f"[Excel Export] Executing {db_to_use}.sp_domestic_sales_report...", flush=True)
                cursor.execute(
                    f"CALL `{db_to_use}`.sp_domestic_sales_report(%s, %s, %s)",
                    (year, month, day)
                )
                print(f"[Excel Export] sp_domestic_sales_report finished.", flush=True)
            else:
                # Fallback if no session found (uses default DB)
                cursor.execute("CALL sp_domestic_sales_report(%s, %s, %s)", (year, month, day))
        else:
            # Fallback if no session_id provided
            print(f"[Excel Export] Executing sp_domestic_sales_report (fallback)...", flush=True)
            cursor.execute("CALL sp_domestic_sales_report(%s, %s, %s)", (year, month, day))
            print(f"[Excel Export] sp_domestic_sales_report finished.", flush=True)
        
        print(f"[Excel Export] Fetching results...", flush=True)
        rows = []
        if is_mysql_connector:
            try:
                # Try regular fetchall first
                if cursor.description is not None:
                    rows = cursor.fetchall()
            except Exception: pass
            
            for result in cursor.stored_results():
                fetched = result.fetchall()
                if not rows and fetched:
                    rows = fetched
            
            while True:
                try:
                    if not cursor.nextset(): break
                    if cursor.description is not None: cursor.fetchall()
                except Exception: break
        else:
            if cursor.description is not None:
                rows = cursor.fetchall()
            while True:
                try:
                    if not cursor.nextset(): break
                    if cursor.description is not None: cursor.fetchall()
                except Exception: break
        
        print(f"[Excel Export] sp_domestic_sales_report returned {len(rows)} rows.", flush=True)
        if len(rows) > 0:
            print(f"[Excel Export] First row sample: {rows[0]}", flush=True)
            
        # Generate Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Domestic Sales Value Achv."
        
        import calendar
        month_abbr = calendar.month_abbr[month] if 1 <= month <= 12 else str(month)
        curr_year_str = str(year)[-2:]
        prev_year_str = str(year - 1)[-2:]
        
        # Add the 3 other sheets for the other sections requested by the user
        ws1 = wb.create_sheet("Sales Number's")
        ws1['A1'].value = "Sales Number's"
        ws1['A1'].font = Font(bold=True)
        
        ws2 = wb.create_sheet("Sales Report by Values")
        ws2['A1'].value = "Sales Report by Values"
        ws2['A1'].font = Font(bold=True)
        
        ws3 = wb.create_sheet("Sales Summary in No's & Values")
        ws3['A1'].value = "Sales Summary in No's & Values"
        ws3['A1'].font = Font(bold=True)
        
        # Styles
        bold_font = Font(bold=True)
        center_aligned_text = Alignment(horizontal="center", vertical="center", wrap_text=True)
        
        fill_title = PatternFill(start_color="CCFFFF", end_color="CCFFFF", fill_type="solid")
        fill_header = PatternFill(start_color="CCFFFF", end_color="CCFFFF", fill_type="solid")
        fill_total = PatternFill(start_color="E6E6FA", end_color="E6E6FA", fill_type="solid")
        fill_pink = PatternFill(start_color="E4DFEC", end_color="E4DFEC", fill_type="solid")
        fill_yellow = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
        fill_blue = PatternFill(start_color="CCFFFF", end_color="CCFFFF", fill_type="solid")
        
        thin = Side(border_style="thin", color="000000")
        border = Border(top=thin, left=thin, right=thin, bottom=thin)

        # Title Row (Row 1)
        ws.merge_cells('A1:H1')
        cell = ws['A1']
        cell.value = "Domestic Sales Value Achv."
        cell.font = bold_font
        cell.fill = fill_title
        cell.border = border
        cell.alignment = center_aligned_text
        
        # Headers Group 1 (Row 2)
        ws.merge_cells('A2:A3')
        ws['A2'].value = "Market Segment"
        ws.merge_cells('B2:D2')
        ws['B2'].value = f"{month_abbr}-{prev_year_str} Actual"
        ws.merge_cells('E2:H2')
        ws['E2'].value = f"Actual Sale for {month_abbr}-{curr_year_str}"
        
        for c in range(1, 9):
            ws.cell(row=2, column=c).border = border
            ws.cell(row=2, column=c).font = bold_font
            ws.cell(row=2, column=c).alignment = center_aligned_text
            ws.cell(row=2, column=c).fill = fill_header

        # Headers Group 2 (Row 3)
        h3 = ["Month", "MTD", "Target", "Actual", "% Achvd", f"Sale for\nday {day}", "Grth\nOver\nLYSMT"]
        for i, h in enumerate(h3, start=2):
            cell = ws.cell(row=3, column=i)
            cell.value = h
            cell.font = bold_font
            cell.alignment = center_aligned_text
            cell.fill = fill_header
            cell.border = border
            
        ws.cell(row=3, column=1).border = border
        ws.cell(row=3, column=1).fill = fill_header
        
        row_num = 4
        
        # Calculate totals while avoiding double-counting known DB subtotals
        totals = { "Month": 0, "MTD": 0, "Target": 0, "Actual": 0, "Sale_For_Day": 0 }
        
        repl_totals = { "Month": 0, "MTD": 0, "Target": 0, "Actual": 0, "Sale_For_Day": 0 }
        four_whlr_totals = { "Month": 0, "MTD": 0, "Target": 0, "Actual": 0, "Sale_For_Day": 0 }
        two_three_whlr_totals = { "Month": 0, "MTD": 0, "Target": 0, "Actual": 0, "Sale_For_Day": 0 }
        
        has_4_whlrs_splits = False
        has_23_whlrs_splits = False
        
        # Pre-process rows to insert totals
        processed_rows = []
        insert_repl_idx = -1
        
        for idx, row in enumerate(rows):
            label = row.get('report_name') or row.get('market_segment', 'Unknown')
            processed_rows.append(row)
            
            # Identify components for totals
            if "4 Wheeler" in label or "4 Whlr" in label:
                if label not in ["4 Wheelers", "4 Whlrs Total"]:
                    has_4_whlrs_splits = True
                for key in four_whlr_totals:
                    val = row.get(key)
                    if val is not None:
                        try: four_whlr_totals[key] += float(val)
                        except: pass
                        
            elif "2/3 Wheeler" in label or "2/3 Whlr" in label:
                if label not in ["2/3 Wheelers", "2/3 Whlrs Total"]:
                    has_23_whlrs_splits = True
                for key in two_three_whlr_totals:
                    val = row.get(key)
                    if val is not None:
                        try: two_three_whlr_totals[key] += float(val)
                        except: pass
            
            # Find the best index to insert Repl
            if "2/3 Wheeler" in label or ("2/3 Whlrs" in label and "Total" in label) or ("2/3" in label and not has_23_whlrs_splits):
                insert_repl_idx = len(processed_rows) # insert right after this row
            elif "Treel" in label and insert_repl_idx != -1:
                insert_repl_idx = len(processed_rows) # move insertion after Treel

        # Combine totals for Repl
        for key in repl_totals:
            repl_totals[key] = four_whlr_totals[key] + two_three_whlr_totals[key]

        # Insert 4 Whlrs Total
        if True:
            achv = f"{round((four_whlr_totals['Actual'] / four_whlr_totals['Target'] * 100))}%" if four_whlr_totals['Target'] else "0%"
            grth = f"{round(((four_whlr_totals['Actual'] - four_whlr_totals['MTD']) / four_whlr_totals['MTD']) * 100)}%" if four_whlr_totals['MTD'] else "0%"
            total_4_row = {
                'market_segment': '4 Whlrs Total', 'Month': four_whlr_totals['Month'], 'MTD': four_whlr_totals['MTD'],
                'Target': four_whlr_totals['Target'], 'Actual': four_whlr_totals['Actual'], 'Achievement': achv,
                'Sale_For_Day': four_whlr_totals['Sale_For_Day'], 'Growth_Over_LYSMTD': grth, '_is_purple': True
            }
            # Find where to insert (after the last 4 Whlr row)
            idx_4 = max((i for i, r in enumerate(processed_rows) if "4 Wheeler" in (r.get('report_name') or r.get('market_segment', '')) or "4 Whlr" in (r.get('report_name') or r.get('market_segment', ''))), default=-1)
            if idx_4 != -1:
                processed_rows.insert(idx_4 + 1, total_4_row)
                if insert_repl_idx > idx_4: insert_repl_idx += 1

        # Insert 2/3 Whlrs Total
        if True:
            achv = f"{round((two_three_whlr_totals['Actual'] / two_three_whlr_totals['Target'] * 100))}%" if two_three_whlr_totals['Target'] else "0%"
            grth = f"{round(((two_three_whlr_totals['Actual'] - two_three_whlr_totals['MTD']) / two_three_whlr_totals['MTD']) * 100)}%" if two_three_whlr_totals['MTD'] else "0%"
            total_23_row = {
                'market_segment': '2/3 Whlrs Total', 'Month': two_three_whlr_totals['Month'], 'MTD': two_three_whlr_totals['MTD'],
                'Target': two_three_whlr_totals['Target'], 'Actual': two_three_whlr_totals['Actual'], 'Achievement': achv,
                'Sale_For_Day': two_three_whlr_totals['Sale_For_Day'], 'Growth_Over_LYSMTD': grth, '_is_purple': True
            }
            idx_23 = max((i for i, r in enumerate(processed_rows) if "2/3 Wheeler" in (r.get('report_name') or r.get('market_segment', '')) or "2/3 Whlr" in (r.get('report_name') or r.get('market_segment', ''))), default=-1)
            if idx_23 != -1:
                processed_rows.insert(idx_23 + 1, total_23_row)
                if insert_repl_idx > idx_23: insert_repl_idx += 1

        if insert_repl_idx != -1:
            achv = f"{round((repl_totals['Actual'] / repl_totals['Target'] * 100))}%" if repl_totals['Target'] else "0%"
            grth = f"{round(((repl_totals['Actual'] - repl_totals['MTD']) / repl_totals['MTD']) * 100)}%" if repl_totals['MTD'] else "0%"
            
            repl_row = {
                'market_segment': 'Repl (4 & 2/3 Whlrs)',
                'Month': repl_totals['Month'],
                'MTD': repl_totals['MTD'],
                'Target': repl_totals['Target'],
                'Actual': repl_totals['Actual'],
                'Achievement': achv,
                'Sale_For_Day': repl_totals['Sale_For_Day'],
                'Growth_Over_LYSMTD': grth,
                '_is_yellow': True
            }
            processed_rows.insert(insert_repl_idx, repl_row)
        
        for row in processed_rows:
            label = row.get('report_name') or row.get('market_segment', 'Unknown')
            
            c1 = ws.cell(row=row_num, column=1, value=label)
            c2 = ws.cell(row=row_num, column=2, value=row.get('Month', 0))
            c3 = ws.cell(row=row_num, column=3, value=row.get('MTD', 0))
            c4 = ws.cell(row=row_num, column=4, value=row.get('Target', 0))
            c5 = ws.cell(row=row_num, column=5, value=row.get('Actual', 0))
            c6 = ws.cell(row=row_num, column=6, value=row.get('Achievement', '0%'))
            c7 = ws.cell(row=row_num, column=7, value=row.get('Sale_For_Day', 0) if row.get('Sale_For_Day') is not None else 0)
            c8 = ws.cell(row=row_num, column=8, value=row.get('Growth_Over_LYSMTD', '0%'))
            
            # Apply formatting
            is_subtotal = "OEM+STU+DEF" in label or "Repl" in label or "Total" in label
            
            fill_color = None
            if row.get('_is_purple') or "Total" in label:
                fill_color = fill_pink
            elif row.get('_is_yellow') or is_subtotal:
                fill_color = fill_yellow
            
            for c in [c1, c2, c3, c4, c5, c6, c7, c8]:
                c.border = border
                if is_subtotal or fill_color:
                    c.font = bold_font
                if fill_color:
                    c.fill = fill_color
            
            # Add to totals (Skip adding known subtotals to avoid double counting)
            if not is_subtotal:
                for key in totals:
                    val = row.get(key)
                    if val is not None:
                        try:
                            totals[key] += float(val)
                        except ValueError:
                            pass
            
            row_num += 1

        # Add Grand Total Row (Domestic)
        ws.cell(row=row_num, column=1, value="Domestic").font = bold_font
        ws.cell(row=row_num, column=1).fill = fill_blue
        ws.cell(row=row_num, column=1).border = border
        
        ws.cell(row=row_num, column=2, value=totals["Month"]).font = bold_font
        ws.cell(row=row_num, column=2).fill = fill_blue
        ws.cell(row=row_num, column=2).border = border
        
        ws.cell(row=row_num, column=3, value=totals["MTD"]).font = bold_font
        ws.cell(row=row_num, column=3).fill = fill_blue
        ws.cell(row=row_num, column=3).border = border
        
        ws.cell(row=row_num, column=4, value=totals["Target"]).font = bold_font
        ws.cell(row=row_num, column=4).fill = fill_blue
        ws.cell(row=row_num, column=4).border = border
        
        ws.cell(row=row_num, column=5, value=totals["Actual"]).font = bold_font
        ws.cell(row=row_num, column=5).fill = fill_blue
        ws.cell(row=row_num, column=5).border = border
        
        achv = f"{round((totals['Actual'] / totals['Target'] * 100))}%" if totals['Target'] else "0%"
        ws.cell(row=row_num, column=6, value=achv).font = bold_font
        ws.cell(row=row_num, column=6).fill = fill_blue
        ws.cell(row=row_num, column=6).border = border
        
        ws.cell(row=row_num, column=7, value=totals["Sale_For_Day"]).font = bold_font
        ws.cell(row=row_num, column=7).fill = fill_blue
        ws.cell(row=row_num, column=7).border = border
        
        grth = f"{round(((totals['Actual'] - totals['MTD']) / totals['MTD']) * 100)}%" if totals['MTD'] else "0%"
        ws.cell(row=row_num, column=8, value=grth).font = bold_font
        ws.cell(row=row_num, column=8).fill = fill_blue
        ws.cell(row=row_num, column=8).border = border

        # Adjust column widths for WS
        from openpyxl.utils import get_column_letter
        for idx, col in enumerate(ws.columns, start=1):
            max_length = 0
            column = get_column_letter(idx)
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            ws.column_dimensions[column].width = adjusted_width

        # ==========================================
        # POPULATE WS1 (Sales Summary)
        # ==========================================
        try:
            print(f"[Excel Export] Executing sp_summary_sales_numbers_V2 for WS1...", flush=True)
            if session_id and sync_row:
                cursor.execute(f"CALL `{db_to_use}`.sp_summary_sales_numbers_V2(%s, %s, %s)", (year, month, day))
            else:
                cursor.execute("CALL sp_summary_sales_numbers_V2(%s, %s, %s)", (year, month, day))
            print(f"[Excel Export] sp_summary_sales_numbers_V2 finished.", flush=True)
                
            rows_ws1 = []
            if is_mysql_connector:
                try:
                    if cursor.description is not None:
                        rows_ws1 = cursor.fetchall()
                except Exception: pass
                
                for result in cursor.stored_results():
                    fetched = result.fetchall()
                    if not rows_ws1 and fetched:
                        rows_ws1 = fetched
                        
                while True:
                    try:
                        if not cursor.nextset(): break
                        if cursor.description is not None: cursor.fetchall()
                    except Exception: break
            else:
                if cursor.description is not None:
                    rows_ws1 = cursor.fetchall()
                while True:
                    try:
                        if not cursor.nextset(): break
                        if cursor.description is not None: cursor.fetchall()
                    except Exception: break
                        
            print(f"[Excel Export] sp_summary_sales_numbers returned {len(rows_ws1)} rows.", flush=True)
            if len(rows_ws1) > 0:
                print(f"[Excel Export] First row sample: {rows_ws1[0]}", flush=True)
                
            # Row 1 is intentionally left entirely blank and unstyled

            # Merge cells for title
            ws1.merge_cells('A1:W1')
            ws1['A1'].value = "Sales Number's"
            ws1['A1'].font = bold_font
            ws1['A1'].alignment = center_aligned_text
            ws1['A1'].fill = fill_title
            
            for c in range(2, 24):
                ws1.cell(row=1, column=c).border = border
                ws1.cell(row=1, column=c).fill = fill_title
            
            # Headers Group 1 (Row 2)
            fill_cat = fill_header # Cyan
            fill_rep = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid") # Yellow
            fill_oem = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid") # Pink
            fill_stu = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid") # Light Blue
            fill_def = PatternFill(start_color="FFF0F5", end_color="FFF0F5", fill_type="solid") # Light Purple
            fill_dom = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid") # Grey
            
            ws1.merge_cells('A2:A4')
            ws1['A2'].value = "Category"
            ws1['A2'].fill = fill_cat
            ws1.merge_cells('B2:N2')
            ws1['B2'].value = "Replacement"
            ws1['B2'].fill = fill_rep
            ws1.merge_cells('O2:P2')
            ws1['O2'].value = "OEM"
            ws1['O2'].fill = fill_oem
            ws1.merge_cells('Q2:R2')
            ws1['Q2'].value = "STU"
            ws1['Q2'].fill = fill_stu
            ws1.merge_cells('S2:T2')
            ws1['S2'].value = "DEF"
            ws1['S2'].fill = fill_def
            ws1.merge_cells('U2:W2')
            ws1['U2'].value = "Domestic"
            ws1['U2'].fill = fill_dom
            
            for c in range(1, 24):
                ws1.cell(row=2, column=c).border = border
                ws1.cell(row=2, column=c).font = bold_font
                ws1.cell(row=2, column=c).alignment = center_aligned_text

            # Headers Group 2 (Row 3 and Row 4)
            h3_headers = {
                2: f"{month_abbr}-{prev_year_str} Act", 3: "Target", 4: "Total", 5: "% Achv", 6: "Today", 
                7: "Dealer", 8: "Dist.", 9: "Fleet", 12: "Inst.", 13: "Govt", 14: "Others", 
                15: "Target", 16: "Actual", 17: "Target", 18: "Actual", 19: "Target", 20: "Actual", 
                21: "Target", 22: "Actual", 23: "% Achv."
            }
            
            for col, val in h3_headers.items():
                if col == 9: # Fleet spans 3 columns
                    ws1.merge_cells(start_row=3, start_column=9, end_row=3, end_column=11)
                    ws1.cell(row=3, column=9).value = val
                else: # Others span 2 rows (3 and 4)
                    ws1.merge_cells(start_row=3, start_column=col, end_row=4, end_column=col)
                    ws1.cell(row=3, column=col).value = val

            # Row 4 Subheaders under Fleet
            ws1.cell(row=4, column=9).value = "Mobilty-GR"
            ws1.cell(row=4, column=10).value = "FM-Actual"
            ws1.cell(row=4, column=11).value = "Total"

            # Apply borders and formatting for rows 3 and 4 (No background fill)
            for r in [3, 4]:
                for c in range(2, 24):
                    cell = ws1.cell(row=r, column=c)
                    cell.border = border
                    cell.font = bold_font
                    cell.alignment = center_aligned_text
                    
            ws1.cell(row=3, column=1).border = border
            ws1.cell(row=4, column=1).border = border
                
            # Aggregate duplicates by category
            aggregated = {}
            for r in rows_ws1:
                cat = r.get('category', '')
                if cat not in aggregated:
                    aggregated[cat] = dict(r)
                else:
                    for k in r:
                        if k not in ('row_no', 'category', 'tyre_type_name', 'construction_description', 'achievement', 'domestic_achievement'):
                            val1 = aggregated[cat].get(k) or 0
                            val2 = r.get(k) or 0
                            aggregated[cat][k] = float(val1) + float(val2)
            
            # Recalculate percentages
            for cat, r in aggregated.items():
                target = float(r.get('target') or 0)
                total = float(r.get('total') or 0)
                r['achievement'] = round((total / target * 100), 2) if target > 0 else 0
                
                dom_target = float(r.get('domestic_target') or 0)
                dom_actual = float(r.get('domestic_actual') or 0)
                r['domestic_achievement'] = round((dom_actual / dom_target * 100), 2) if dom_target > 0 else 0
                
            final_rows = sorted(aggregated.values(), key=lambda x: float(x.get('row_no') or 9999))
                
            # Data rows
            r_idx = 5
            
            def sv(val):
                return val if val is not None and str(val).strip() != '' else ""
                
            for r in final_rows:
                cat = r.get('category', '')
                
                achv1 = r.get('achievement')
                achv1_str = f"{achv1}%" if achv1 is not None else "0%"
                if achv1_str == "0%" and not r.get('achievement'):
                    achv1_str = "%" # match image for empty
                achv2 = r.get('domestic_achievement')
                achv2_str = f"{achv2}%" if achv2 is not None else "0%"
                if achv2_str == "0%" and not r.get('domestic_achievement'):
                    achv2_str = "%"
                
                c_cells = [
                    ws1.cell(row=r_idx, column=1, value=cat),
                    ws1.cell(row=r_idx, column=2, value=sv(r.get('jul_act'))),
                    ws1.cell(row=r_idx, column=3, value=sv(r.get('target'))),
                    ws1.cell(row=r_idx, column=4, value=sv(r.get('total'))),
                    ws1.cell(row=r_idx, column=5, value=achv1_str),
                    ws1.cell(row=r_idx, column=6, value=sv(r.get('today'))),
                    ws1.cell(row=r_idx, column=7, value=sv(r.get('dealer'))),
                    ws1.cell(row=r_idx, column=8, value=sv(r.get('distributor'))),
                    ws1.cell(row=r_idx, column=9, value=sv(r.get('mobility_grn'))),
                    ws1.cell(row=r_idx, column=10, value=sv(r.get('fm_actual'))),
                    ws1.cell(row=r_idx, column=11, value=sv(r.get('fleet_total'))),
                    ws1.cell(row=r_idx, column=12, value=sv(r.get('institution'))),
                    ws1.cell(row=r_idx, column=13, value=sv(r.get('government'))),
                    ws1.cell(row=r_idx, column=14, value=sv(r.get('others'))),
                    ws1.cell(row=r_idx, column=15, value=sv(r.get('oem_target'))),
                    ws1.cell(row=r_idx, column=16, value=sv(r.get('oem_actual'))),
                    ws1.cell(row=r_idx, column=17, value=sv(r.get('stu_target'))),
                    ws1.cell(row=r_idx, column=18, value=sv(r.get('stu_actual'))),
                    ws1.cell(row=r_idx, column=19, value=sv(r.get('def_target'))),
                    ws1.cell(row=r_idx, column=20, value=sv(r.get('def_actual'))),
                    ws1.cell(row=r_idx, column=21, value=sv(r.get('domestic_target'))),
                    ws1.cell(row=r_idx, column=22, value=sv(r.get('domestic_actual'))),
                    ws1.cell(row=r_idx, column=23, value=achv2_str),
                ]
                
                is_subtotal = "Total" in cat or "Total" in str(cat)
                
                f_color = None
                if is_subtotal:
                    f_color = fill_yellow
                elif cat in ["Pack Tube", "Treel"]:
                    f_color = fill_pink
                
                for cell in c_cells:
                    cell.border = border
                    cell.font = bold_font # Make ALL values bold
                    if is_subtotal:
                        cell.fill = fill_yellow
                    elif f_color == fill_pink:
                        cell.fill = fill_pink
                    if f_color:
                        cell.fill = f_color
                        
                r_idx += 1
                
            from openpyxl.utils import get_column_letter
            for idx, col in enumerate(ws1.columns, start=1):
                max_length = 0
                column = get_column_letter(idx)
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = (max_length + 2)
                ws1.column_dimensions[column].width = adjusted_width
                
        except Exception as e:
            print(f"Error populating WS1 (Sales Summary): {e}")

        # ==========================================
        # POPULATE WS2 (Sales Report by Values)
        # ==========================================
        try:
            print(f"[Excel Export] Executing sp_zone_sales_report for WS2...", flush=True)
            if session_id and sync_row:
                cursor.execute(f"CALL `{db_to_use}`.sp_zone_sales_report(%s, %s, %s)", (year, month, day))
            else:
                cursor.execute("CALL sp_zone_sales_report(%s, %s, %s)", (year, month, day))
            print(f"[Excel Export] sp_zone_sales_report finished.", flush=True)
                
            rows_ws2 = []
            if is_mysql_connector:
                try:
                    if cursor.description is not None:
                        rows_ws2 = cursor.fetchall()
                except Exception: pass
                
                for result in cursor.stored_results():
                    fetched = result.fetchall()
                    if not rows_ws2 and fetched:
                        rows_ws2 = fetched
                        
                while True:
                    try:
                        if not cursor.nextset(): break
                        if cursor.description is not None: cursor.fetchall()
                    except Exception: break
            else:
                if cursor.description is not None:
                    rows_ws2 = cursor.fetchall()
                while True:
                    try:
                        if not cursor.nextset(): break
                        if cursor.description is not None: cursor.fetchall()
                    except Exception: break
                        
            print(f"[Excel Export] sp_zone_sales_report returned {len(rows_ws2)} rows.", flush=True)

            # Row 1 is intentionally left entirely blank and unstyled

            fill_greyish = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")

            ws2.merge_cells('A1:P1')
            ws2['A1'].value = "Sales Report by Values ( In Crores / Rs. )"
            ws2['A1'].font = bold_font
            ws2['A1'].alignment = center_aligned_text
            ws2['A1'].fill = fill_greyish
            for c in range(1, 17):
                ws2.cell(row=1, column=c).border = border
                ws2.cell(row=1, column=c).fill = fill_greyish
            
            # Row 2
            ws2.merge_cells('A2:A4')
            ws2['A2'].value = "Zone"
            
            ws2.merge_cells('B2:D3')
            ws2['B2'].value = f"{month_abbr}-{prev_year_str} Actual"
            
            ws2.merge_cells('E2:P2')
            ws2['E2'].value = f"Actual Sale for {month_abbr}-{curr_year_str}"
            
            # Row 3
            ws2.merge_cells('E3:G3')
            ws2['E3'].value = "Target"
            ws2.merge_cells('H3:J3')
            ws2['H3'].value = "Actual Sales"
            ws2.merge_cells('K3:K4')
            ws2['K3'].value = "% Achvd"
            ws2.merge_cells('L3:L4')
            ws2['L3'].value = "Sale for\nthe Day"
            ws2.merge_cells('M3:M4')
            ws2['M3'].value = "Asking\nRate"
            ws2.merge_cells('N3:P3')
            ws2['N3'].value = "% Achvt."
            
            fill_orange = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
            
            # Row 4 Subheaders
            sub_h = {
                2: "4 Whlrs.", 3: "2/3 Whlrs", 4: "Total",
                5: "4 Whlrs.", 6: "2/3 Whlrs", 7: "Total",
                8: "4 Whlrs", 9: "2/3 Whlrs", 10: "Total",
                14: "4 Whlrs", 15: "2/3 Whlrs", 16: "Total"
            }
            for col, val in sub_h.items():
                ws2.cell(row=4, column=col, value=val)
                
            # Apply styles for rows 2,3,4
            for r in range(2, 5):
                for c in range(1, 17):
                    cell = ws2.cell(row=r, column=c)
                    cell.border = border
                    cell.font = bold_font
                    cell.alignment = center_aligned_text
                    if c >= 14 and r == 3:
                        cell.fill = fill_orange
                    else:
                        cell.fill = fill_header

            # Data rows
            r_idx = 5
            totals_ws2 = {
                "LY_4W": 0, "LY_23W": 0, "LY_TOTAL": 0,
                "TARGET_4W": 0, "TARGET_23W": 0, "TARGET_TOTAL": 0,
                "ACTUAL_4W": 0, "ACTUAL_23W": 0, "ACTUAL_TOTAL": 0,
                "SALE_FOR_DAY": 0
            }
            
            for r in rows_ws2:
                # Add data
                c1 = ws2.cell(row=r_idx, column=1, value=r.get('Zone', ''))
                c2 = ws2.cell(row=r_idx, column=2, value=r.get('LY_4W', 0))
                c3 = ws2.cell(row=r_idx, column=3, value=r.get('LY_23W', 0))
                c4 = ws2.cell(row=r_idx, column=4, value=r.get('LY_TOTAL', 0))
                c5 = ws2.cell(row=r_idx, column=5, value=r.get('TARGET_4W', 0))
                c6 = ws2.cell(row=r_idx, column=6, value=r.get('TARGET_23W', 0))
                c7 = ws2.cell(row=r_idx, column=7, value=r.get('TARGET_TOTAL', 0))
                c8 = ws2.cell(row=r_idx, column=8, value=r.get('ACTUAL_4W', 0))
                c9 = ws2.cell(row=r_idx, column=9, value=r.get('ACTUAL_23W', 0))
                c10 = ws2.cell(row=r_idx, column=10, value=r.get('ACTUAL_TOTAL', 0))
                
                achv = r.get('ACHIEVEMENT', 0)
                achv_val = achv if achv is not None else 0
                c11 = ws2.cell(row=r_idx, column=11, value=f"{int(round(float(achv_val)))}%" if achv_val else "0%")
                
                c12 = ws2.cell(row=r_idx, column=12, value=r.get('SALE_FOR_DAY', 0))
                c13 = ws2.cell(row=r_idx, column=13, value="") # Asking Rate (Blank)
                
                achv_4w = r.get('ACHV_4W', 0)
                achv_4w_val = achv_4w if achv_4w is not None else 0
                c14 = ws2.cell(row=r_idx, column=14, value=f"{int(round(float(achv_4w_val)))}%" if achv_4w_val else "0%")
                
                achv_23w = r.get('ACHV_23W', 0)
                achv_23w_val = achv_23w if achv_23w is not None else 0
                c15 = ws2.cell(row=r_idx, column=15, value=f"{int(round(float(achv_23w_val)))}%" if achv_23w_val else "0%")
                
                achv_tot = r.get('ACHV_TOTAL', 0)
                achv_tot_val = achv_tot if achv_tot is not None else 0
                c16 = ws2.cell(row=r_idx, column=16, value=f"{int(round(float(achv_tot_val)))}%" if achv_tot_val else "0%")
                
                for c in range(1, 17):
                    ws2.cell(row=r_idx, column=c).border = border
                    ws2.cell(row=r_idx, column=c).font = bold_font
                    
                # Update totals
                for k in totals_ws2:
                    val = r.get(k)
                    if val is not None:
                        try: totals_ws2[k] += float(val)
                        except: pass
                        
                r_idx += 1
                
            # Total row
            ws2.cell(row=r_idx, column=1, value="Total").font = bold_font
            ws2.cell(row=r_idx, column=1).fill = fill_yellow
            ws2.cell(row=r_idx, column=1).border = border
            
            t_ly_4w = round(totals_ws2.get("LY_4W", 0), 2)
            t_ly_23w = round(totals_ws2.get("LY_23W", 0), 2)
            t_ly_tot = round(totals_ws2.get("LY_TOTAL", 0), 2)
            t_tgt_4w = round(totals_ws2.get("TARGET_4W", 0), 2)
            t_tgt_23w = round(totals_ws2.get("TARGET_23W", 0), 2)
            t_tgt_tot = round(totals_ws2.get("TARGET_TOTAL", 0), 2)
            t_act_4w = round(totals_ws2.get("ACTUAL_4W", 0), 2)
            t_act_23w = round(totals_ws2.get("ACTUAL_23W", 0), 2)
            t_act_tot = round(totals_ws2.get("ACTUAL_TOTAL", 0), 2)
            t_sale = round(totals_ws2.get("SALE_FOR_DAY", 0), 2)
            
            t_achv_4w = round((t_act_4w / t_tgt_4w * 100)) if t_tgt_4w else 0
            t_achv_23w = round((t_act_23w / t_tgt_23w * 100)) if t_tgt_23w else 0
            t_achv_tot = round((t_act_tot / t_tgt_tot * 100)) if t_tgt_tot else 0
            
            # Fill the Total row values (columns 2 to 16)
            ws2.cell(row=r_idx, column=2, value=t_ly_4w).fill = fill_yellow
            ws2.cell(row=r_idx, column=3, value=t_ly_23w).fill = fill_yellow
            ws2.cell(row=r_idx, column=4, value=t_ly_tot).fill = fill_yellow
            ws2.cell(row=r_idx, column=5, value=t_tgt_4w).fill = fill_yellow
            ws2.cell(row=r_idx, column=6, value=t_tgt_23w).fill = fill_yellow
            ws2.cell(row=r_idx, column=7, value=t_tgt_tot).fill = fill_yellow
            ws2.cell(row=r_idx, column=8, value=t_act_4w).fill = fill_yellow
            ws2.cell(row=r_idx, column=9, value=t_act_23w).fill = fill_yellow
            ws2.cell(row=r_idx, column=10, value=t_act_tot).fill = fill_yellow
            ws2.cell(row=r_idx, column=11, value=f"{t_achv_tot}%").fill = fill_yellow
            ws2.cell(row=r_idx, column=12, value=t_sale).fill = fill_yellow
            ws2.cell(row=r_idx, column=13, value="").fill = fill_yellow # Asking Rate Blank
            ws2.cell(row=r_idx, column=14, value=f"{t_achv_4w}%").fill = fill_yellow
            ws2.cell(row=r_idx, column=15, value=f"{t_achv_23w}%").fill = fill_yellow
            ws2.cell(row=r_idx, column=16, value=f"{t_achv_tot}%").fill = fill_yellow
            
            for c in range(2, 17):
                ws2.cell(row=r_idx, column=c).border = border
                ws2.cell(row=r_idx, column=c).font = bold_font

            # Percentage Contribution Row
            r_idx += 1
            fill_magenta = PatternFill(start_color="FFCCFF", end_color="FFCCFF", fill_type="solid")
            ws2.cell(row=r_idx, column=1, value="% Contribution").font = bold_font
            ws2.cell(row=r_idx, column=1).fill = fill_magenta
            ws2.cell(row=r_idx, column=1).border = border
            
            # Empty cells up to D with pink fill
            for c in range(2, 5):
                ws2.cell(row=r_idx, column=c).fill = fill_magenta
                ws2.cell(row=r_idx, column=c).border = border

            # Target percentage contribution placeholders
            ws2.cell(row=r_idx, column=5, value="%").fill = fill_magenta
            ws2.cell(row=r_idx, column=5).font = bold_font
            ws2.cell(row=r_idx, column=5).border = border
            
            ws2.cell(row=r_idx, column=6, value="%").fill = fill_magenta
            ws2.cell(row=r_idx, column=6).font = bold_font
            ws2.cell(row=r_idx, column=6).border = border
            
            ws2.cell(row=r_idx, column=7, value="").fill = fill_yellow
            ws2.cell(row=r_idx, column=7).border = border
            
            # Actual sales contribution
            ws2.cell(row=r_idx, column=8, value="100%").fill = PatternFill(start_color="CCFFCC", end_color="CCFFCC", fill_type="solid")
            ws2.cell(row=r_idx, column=8).font = bold_font
            ws2.cell(row=r_idx, column=8).border = border
            
            ws2.cell(row=r_idx, column=9, value="%").fill = fill_magenta
            ws2.cell(row=r_idx, column=9).font = bold_font
            ws2.cell(row=r_idx, column=9).border = border

            # Fill rest with yellow and pink
            for c in range(10, 17):
                if c == 10:
                    ws2.cell(row=r_idx, column=c).fill = fill_magenta
                else:
                    ws2.cell(row=r_idx, column=c).fill = fill_yellow
                ws2.cell(row=r_idx, column=c).border = border
                
            from openpyxl.utils import get_column_letter
            for idx, col in enumerate(ws2.columns, start=1):
                max_length = 0
                column = get_column_letter(idx)
                for cell in col:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                ws2.column_dimensions[column].width = max_length + 2

        except Exception as e:
            print(f"Error populating WS2 (Sales Report by Values): {e}")

        # ==========================================
        # POPULATE WS3 (Sales Numbers)
        # ==========================================
        try:
            print(f"[Excel Export] Executing sp_zone_sales_numbers_values for WS3...", flush=True)
            if session_id and sync_row:
                cursor.execute(f"CALL `{db_to_use}`.sp_zone_sales_numbers_values(%s, %s, %s)", (year, month, day))
            else:
                cursor.execute("CALL sp_zone_sales_numbers_values(%s, %s, %s)", (year, month, day))
            print(f"[Excel Export] sp_zone_sales_numbers_values finished.", flush=True)
                
            rows_ws3 = []
            if is_mysql_connector:
                try:
                    if cursor.description is not None:
                        rows_ws3 = cursor.fetchall()
                except Exception: pass
                
                for result in cursor.stored_results():
                    fetched = result.fetchall()
                    if not rows_ws3 and fetched:
                        rows_ws3 = fetched
                        
                while True:
                    try:
                        if not cursor.nextset(): break
                        if cursor.description is not None: cursor.fetchall()
                    except Exception: break
            else:
                if cursor.description is not None:
                    rows_ws3 = cursor.fetchall()
                while True:
                    try:
                        if not cursor.nextset(): break
                        if cursor.description is not None: cursor.fetchall()
                    except Exception: break

            print(f"[Excel Export] sp_zone_sales_numbers_values returned {len(rows_ws3)} rows.", flush=True)

            # Row 1 is intentionally left entirely blank and unstyled

            ws3.merge_cells('A1:AC1')
            ws3['A1'].value = f"Sales Summary in No's & Values for {month_abbr}-{curr_year_str}"
            ws3['A1'].font = bold_font
            ws3['A1'].alignment = center_aligned_text
            
            for c in range(1, 30):
                ws3.cell(row=1, column=c).border = border

            if rows_ws3:
                fill_ws3_header = PatternFill(start_color="E0FFFF", end_color="E0FFFF", fill_type="solid") # Light Cyan
                
                # Row 2: Grouped Headers
                ws3.merge_cells('A2:A3')
                ws3['A2'].value = "Zone"
                ws3.merge_cells('B2:B3')
                ws3['B2'].value = "Type"
                ws3.merge_cells('C2:E2')
                ws3['C2'].value = "Sales Values in( In Crores )"
                ws3.merge_cells('F2:H2')
                ws3['F2'].value = "TBB"
                ws3.merge_cells('I2:K2')
                ws3['I2'].value = "TBR"
                
                single_headers = {
                    12: "LCV\nBias", 13: "LCV\nRdl", 14: "SCV\nBias", 15: "SCV\nRdl",
                    16: "Car\nBias", 17: "Car\nRadial", 18: "Jeep\nBias", 19: "Jeep\nRadial",
                    20: "Tr. Fro", 21: "Tr. Rear", 22: "Trail", 23: "ADV", 24: "3 Whlrs",
                    25: "Scooter", 26: "Motor", 27: "Pack\nTube", 28: "Treel", 29: "Smart Tyre"
                }
                
                for col, val in single_headers.items():
                    ws3.merge_cells(start_row=2, start_column=col, end_row=3, end_column=col)
                    ws3.cell(row=2, column=col).value = val

                for c in range(1, 30):
                    cell = ws3.cell(row=2, column=c)
                    cell.font = bold_font
                    cell.alignment = center_aligned_text
                    cell.fill = fill_ws3_header
                    cell.border = border

                # Row 3: Sub Headers
                sub_h = {
                    3: "4 Whlrs.", 4: "Whlrs", 5: "Total",
                    6: "JK", 7: "Vikrant", 8: "Total",
                    9: "JK", 10: "Vikrant", 11: "Total"
                }
                for col, val in sub_h.items():
                    cell = ws3.cell(row=3, column=col, value=val)
                    cell.font = bold_font
                    cell.alignment = center_aligned_text
                    cell.fill = fill_ws3_header
                    cell.border = border
                
                # Apply borders to Row 3 merged cells (which are single_headers and Zone, Type)
                for c in [1, 2] + list(single_headers.keys()):
                    ws3.cell(row=3, column=c).border = border
                    ws3.cell(row=3, column=c).fill = fill_ws3_header
                    
                # Data rows start at 4
                r_idx = 4
                headers_ws3 = list(rows_ws3[0].keys())
                
                fill_achv = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid") # Light green
                fill_grand_total = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid") # Light green for Grand Total

                def sv_ws3(val):
                    return val if val is not None and str(val).strip() != '' else ""

                for r in rows_ws3:
                    zone_name = r.get('Zone', '') or r.get('Zone_Name', '') or ''
                    row_type = r.get('Type', '') or r.get('Row_Type', '') or ''
                    
                    is_grand_total = "Grand Total" in str(zone_name)
                    is_achv = "chv" in str(row_type)
                    
                    for c_idx, header in enumerate(headers_ws3, start=1):
                        val = r[header]
                        # Don't apply sv to Zone and Type if they are empty for some reason, though they shouldn't be
                        cell = ws3.cell(row=r_idx, column=c_idx, value=sv_ws3(val) if c_idx > 2 else val)
                        cell.border = border
                        cell.font = bold_font # Make ALL values bold
                        
                        # Apply green background for Achv % rows or Grand Total rows
                        if is_grand_total or is_achv:
                            cell.fill = fill_achv
                            
                    r_idx += 1
                
                # Merge Zone cells vertically (every 3 rows)
                start_r = 4
                while start_r < r_idx:
                    ws3.merge_cells(start_row=start_r, start_column=1, end_row=start_r+2, end_column=1)
                    cell = ws3.cell(row=start_r, column=1)
                    cell.alignment = Alignment(horizontal='center', vertical='center')
                    cell.font = bold_font
                    # The other cells in the merge range already have borders from the loop
                    start_r += 3
                    
                from openpyxl.utils import get_column_letter
                for idx, col in enumerate(ws3.columns, start=1):
                    max_length = 0
                    column = get_column_letter(idx)
                    for cell in col:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    ws3.column_dimensions[column].width = max_length + 2

        except Exception as e:
            print(f"Error populating WS3 (Sales Numbers): {e}")

        import os
        file_name = f"Summary Revised_{year}_{month}_{day}.xlsx"
        output_path = os.path.join(os.getcwd(), file_name)
        wb.save(output_path)
        
        return output_path

    except Exception as e:
        print(f"Error generating excel internally: {e}")
        return None
    finally:
        if cursor:
            cursor.close()

def export_domestic_sales_report_controller(get_db_connection):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        # Check if the request is sending JSON body
        data = request.get_json(silent=True) or {}
        
        from datetime import datetime
        now = datetime.now()
        
        session_id = data.get("session_id") or request.args.get("session_id")
        year = data.get("year") or request.args.get("year", now.year, type=int)
        month = data.get("month") or request.args.get("month", now.month, type=int)
        day = data.get("day") or request.args.get("day", now.day, type=int)

        # Convert to int just in case they were passed as strings in JSON
        if year: year = int(year)
        if month: month = int(month)
        if day: day = int(day)

        output_path = generate_domestic_sales_excel(conn, session_id, year, month, day)
        
        if not output_path:
            return jsonify({"status": "error", "message": "Failed to generate excel file"}), 500
            
        import os
        from flask import send_file
        file_name = os.path.basename(output_path)
        return send_file(output_path, as_attachment=True, download_name=file_name)
        
    except Exception as e:
        print(f"Error in export_domestic_sales_report_controller: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        try:
            if conn and conn.is_connected():
                # Consume any trailing results before closing
                try:
                    conn.commit()
                except Exception:
                    pass
                conn.close()
        except Exception:
            try:
                conn.close()
            except: pass
