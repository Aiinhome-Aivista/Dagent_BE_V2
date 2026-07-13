import pymysql
from database.db_connection import get_db_connection

def get_prompt(workspace_id, prompt_type):
    """
    Centralized prompt loader.
    Fetches the custom prompt for a given workspace_id and prompt_type.
    Falls back to workspace_id = 0 if not found.
    Returns None if nothing is found.
    """
    prompt = None
    conn = None
    try:
        conn = get_db_connection()
        # db_connection returns dictionary cursor by default
        cur = conn.cursor()
        
        # 1. Search for specific workspace prompt
        if workspace_id is not None:
            cur.execute(
                "SELECT custom_prompt FROM workspace_prompts WHERE workspace_id = %s AND prompt_type = %s",
                (workspace_id, prompt_type)
            )
            row = cur.fetchone()
            if row and row.get("custom_prompt") and str(row["custom_prompt"]).strip():
                prompt = str(row["custom_prompt"])
                print(f"[Prompt Loader] Fetched workspace-specific prompt '{prompt_type}' for workspace {workspace_id}")

        # 2. Fallback to global prompt if no valid prompt found
        if not prompt or not prompt.strip():
            cur.execute(
                "SELECT custom_prompt FROM workspace_prompts WHERE workspace_id = 0 AND prompt_type = %s",
                (prompt_type,)
            )
            row = cur.fetchone()
            if row and row.get("custom_prompt") and str(row["custom_prompt"]).strip():
                prompt = str(row["custom_prompt"])
                print(f"[Prompt Loader] Fetched global fallback prompt '{prompt_type}' (workspace 0)")
            else:
                print(f"[Prompt Loader] WARNING: No prompt found for '{prompt_type}' (workspace {workspace_id} or global)")

    except Exception as e:
        print(f"[Prompt Loader] Error fetching prompt for {prompt_type} (workspace {workspace_id}): {e}")
    finally:
        if conn:
            conn.close()
            
    if prompt and prompt.strip():
        # Fix legacy f-string double braces that might have been copied to the DB
        prompt = prompt.replace("{{", "{").replace("}}", "}")
        return prompt
    
    return None
