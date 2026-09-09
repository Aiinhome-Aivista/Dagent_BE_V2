import os
import sys
sys.path.append(r'e:\D-API-UI\api')
from app import get_db_connection

conn = get_db_connection()
if conn:
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, custom_prompt FROM workspace_prompts WHERE prompt_type = 'session_analysis_controller_code'")
    rows = cursor.fetchall()
    count = 0
    for row in rows:
        code = row['custom_prompt']
        if "r['table1']" in code or 'r["table1"]' in code:
            # Safely replace dictionary lookups for string values
            new_code = code.replace(
                "col1 = f\"{r['table1']}.{r['column1']}\"",
                "if not isinstance(r, dict): continue\n            col1 = f\"{r.get('table1', '')}.{r.get('column1', '')}\""
            )
            new_code = new_code.replace(
                "col2 = f\"{r['table2']}.{r['column2']}\"",
                "col2 = f\"{r.get('table2', '')}.{r.get('column2', '')}\""
            )
            cursor.execute('UPDATE workspace_prompts SET custom_prompt = %s WHERE id = %s', (new_code, row['id']))
            count += 1
    conn.commit()
    print(f'Fixed {count} dynamic controllers in DB.')
    conn.close()
else:
    print('Failed to connect to DB')
