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
        
        # Check workspace type
        is_generic_workspace = False
        ws_type = None

        if workspace_id is not None and str(workspace_id) != '0':
            cur.execute("SELECT workspace_type FROM workspaces WHERE id = %s", (workspace_id,))
            ws_row = cur.fetchone()
            if ws_row and ws_row.get('workspace_type'):
                ws_type = str(ws_row['workspace_type']).strip().lower()
                if ws_type == 'generic':
                    is_generic_workspace = True

        # 1. Search for specific workspace prompt if NOT generic
        if workspace_id is not None and not is_generic_workspace:
            cur.execute(
                "SELECT custom_prompt FROM workspace_prompts WHERE workspace_id = %s AND prompt_type = %s",
                (workspace_id, prompt_type)
            )
            row = cur.fetchone()
            if row and row.get("custom_prompt") and str(row["custom_prompt"]).strip():
                prompt = str(row["custom_prompt"])
                print(f"[Prompt Loader] Fetched workspace-specific prompt '{prompt_type}' for workspace {workspace_id}")

        # 2. Fallback to global prompt
        if not prompt or not prompt.strip():
            if is_generic_workspace:
                # Strictly avoid 'sales' data_category for generic workspaces
                cur.execute(
                    "SELECT custom_prompt FROM workspace_prompts WHERE workspace_id = 0 AND prompt_type = %s AND (data_category = 'global' OR data_category IS NULL OR data_category NOT IN ('sales', 'Sales')) LIMIT 1",
                    (prompt_type,)
                )
                row = cur.fetchone()
            else:
                # Try to match the specific global category
                target_cat = 'sales' if ws_type == 'sales' else 'global'
                cur.execute(
                    "SELECT custom_prompt FROM workspace_prompts WHERE workspace_id = 0 AND prompt_type = %s AND data_category = %s LIMIT 1",
                    (prompt_type, target_cat)
                )
                row = cur.fetchone()
                
                # If specific category not found, fallback to anything
                if not row or not row.get("custom_prompt") or not str(row["custom_prompt"]).strip():
                    cur.execute(
                        "SELECT custom_prompt FROM workspace_prompts WHERE workspace_id = 0 AND prompt_type = %s LIMIT 1",
                        (prompt_type,)
                    )
                    row = cur.fetchone()

            if row and row.get("custom_prompt") and str(row["custom_prompt"]).strip():
                prompt = str(row["custom_prompt"])
                print(f"[Prompt Loader] Fetched global prompt '{prompt_type}' (workspace 0)")
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
