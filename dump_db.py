import sys
sys.path.append(r'e:\D-API-UI\api')
from app import get_db_connection

conn = get_db_connection()
if conn:
    cursor = conn.cursor(dictionary=True)
    cursor.execute('SELECT custom_prompt FROM workspace_prompts WHERE prompt_type = \'session_analysis_controller_code\' LIMIT 1')
    row = cursor.fetchone()
    if row:
        with open('dynamic_controller.py', 'w', encoding='utf-8') as f:
            f.write(row['custom_prompt'])
    conn.close()
