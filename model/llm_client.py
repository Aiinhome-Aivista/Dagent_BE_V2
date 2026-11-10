import requests
import json 
import time
from flask import request, has_request_context
# pyrefly: ignore [missing-import]
import google.generativeai as genai
from database.config import engine

# Global HTTP Session for connection pooling
http_session = requests.Session()

# Simple in-memory cache for LLM configs
_config_cache = {}
CACHE_TTL = 300  # 5 minutes

def clear_llm_cache():
    """Clear the in-memory LLM configuration cache."""
    _config_cache.clear()
    print("[LLM Client] Configuration cache cleared.")


def get_current_scenario():
    """Automatically determine the scenario based on the active API endpoint."""
    if not has_request_context():
        return "rag_chat"
    try:
        route = request.path
        if "rag_chat" in route or "session-chat" in route or "chat" in route: return "rag_chat"
        elif "analysis" in route or "analyze" in route: return "analysis"
        elif "view_info" in route: return "visualization"
        elif "insight" in route: return "insights"
        elif "search" in route: return "web_search"
        elif "agent" in route or "query" in route: return "agent_planner"
        elif "knowledge" in route: return "knowledge"
        elif "sheet" in route: return "sheet_processing"
    except:
        pass
    return "rag_chat"


def detect_current_company_id():
    """Dynamically detect company_id from request context, payload, session, or user."""
    if not has_request_context():
        return None
    try:
        # 1. Direct header or URL param
        hdr_cid = request.headers.get("X-Company-Id")
        if hdr_cid and str(hdr_cid).isdigit():
            return int(hdr_cid)
        arg_cid = request.args.get("company_id")
        if arg_cid and str(arg_cid).isdigit():
            return int(arg_cid)

        # 2. JSON body check
        data = request.get_json(silent=True) or {}
        if data.get("company_id") and str(data.get("company_id")).isdigit():
            return int(data["company_id"])

        # 3. Derive from user_id
        user_id = data.get("user_id") or request.args.get("user_id")
        if user_id and str(user_id).isdigit():
            from sqlalchemy import text
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT company_id FROM users WHERE id = :uid"),
                    {"uid": int(user_id)}
                ).fetchone()
                if row and row[0]:
                    return int(row[0])

        # 4. Derive from session_id or workspace_id
        session_id = data.get("session_id") or request.args.get("session_id")
        workspace_id = data.get("workspace_id") or request.args.get("workspace_id")
        if session_id or workspace_id:
            sid_str = str(session_id or "")
            wid_int = int(workspace_id) if workspace_id and str(workspace_id).isdigit() else 0
            from sqlalchemy import text
            with engine.connect() as conn:
                # 4a. Check workspace_users table for assigned user with non-null company_id
                q_wu = text("""
                    SELECT u.company_id 
                    FROM workspace_users wu 
                    JOIN users u ON wu.user_id = u.id 
                    WHERE (wu.session_id = :sid OR wu.workspace_id = :wid)
                      AND u.company_id IS NOT NULL 
                    LIMIT 1
                """)
                row = conn.execute(q_wu, {"sid": sid_str, "wid": wid_int}).fetchone()
                if row and row[0]:
                    return int(row[0])

                # 4b. Match workspace_name to companies.company_name
                q_name = text("""
                    SELECT c.id 
                    FROM workspaces w 
                    JOIN companies c ON LOWER(REPLACE(REPLACE(w.workspace_name, '_', ''), ' ', '')) = LOWER(REPLACE(REPLACE(c.company_name, '_', ''), ' ', ''))
                    WHERE w.session_id = :sid OR w.id = :wid
                    LIMIT 1
                """)
                row = conn.execute(q_name, {"sid": sid_str, "wid": wid_int}).fetchone()
                if row and row[0]:
                    return int(row[0])

                # 4c. Creator user company_id fallback
                q_creator = text("""
                    SELECT u.company_id 
                    FROM workspaces w 
                    JOIN users u ON w.user_id = u.id 
                    WHERE (w.session_id = :sid OR w.id = :wid)
                      AND u.company_id IS NOT NULL 
                    LIMIT 1
                """)
                row = conn.execute(q_creator, {"sid": sid_str, "wid": wid_int}).fetchone()
                if row and row[0]:
                    return int(row[0])
    except Exception as e:
        print(f"[LLM Client] detect_current_company_id warning: {e}")
    return None


def get_assigned_llm_config(scenario, company_id=None):
    """Fetch the LLM configuration for scenario: Company-specific first, fallback to Global."""
    now = time.time()
    cache_key = f"{scenario}::{company_id if company_id else 'global'}"
    if cache_key in _config_cache:
        cached = _config_cache[cache_key]
        if now - cached["timestamp"] < CACHE_TTL:
            return cached["data"]
            
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            config_data = None
            
            # Step 1: Check for company-specific assignment
            if company_id:
                query_company = text("""
                    SELECT p.provider_type, p.api_key, p.model_name, p.base_url, a.temperature, a.max_tokens, a.timeout
                    FROM llm_scenario_assignments a
                    JOIN llm_providers p ON a.provider_id = p.id
                    WHERE a.scenario = :scenario AND a.company_id = :company_id AND p.is_active = TRUE
                    LIMIT 1
                """)
                result = conn.execute(query_company, {"scenario": scenario, "company_id": company_id})
                row = result.mappings().fetchone()
                if row:
                    config_data = dict(row)
                    config_data["_scope"] = f"Company: {company_id}"

            # Step 2: Fallback to global default (company_id IS NULL)
            if not config_data:
                query_global = text("""
                    SELECT p.provider_type, p.api_key, p.model_name, p.base_url, a.temperature, a.max_tokens, a.timeout
                    FROM llm_scenario_assignments a
                    JOIN llm_providers p ON a.provider_id = p.id
                    WHERE a.scenario = :scenario AND a.company_id IS NULL AND p.is_active = TRUE
                    LIMIT 1
                """)
                result = conn.execute(query_global, {"scenario": scenario})
                row = result.mappings().fetchone()
                if row:
                    config_data = dict(row)
                    if company_id:
                        config_data["_scope"] = f"Company: {company_id} (Fallback to Global Default)"
                    else:
                        config_data["_scope"] = "Global Default"
            
        _config_cache[cache_key] = {"data": config_data, "timestamp": now}
        return config_data
    except Exception as e:
        print(f"[LLM Client] DB fetch error for scenario '{scenario}' (Company: {company_id}): {e}")
        if cache_key in _config_cache:
            return _config_cache[cache_key]["data"]
        return None


def _get_fallback_mistral_local_config():
    """Fetch the active local provider from the DB for fallback purposes."""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            query = text("""
                SELECT api_key, model_name, base_url
                FROM llm_providers
                WHERE provider_type IN ('local', 'mistral_local') AND is_active = TRUE
                LIMIT 1
            """)
            result = conn.execute(query)
            row = result.mappings().fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"[LLM Fallback] DB fetch error for mistral_local fallback: {e}")
        return None


def _call_gemini(messages, json_mode, temperature, api_key, model_name, base_url=None, timeout=90):
    if not api_key or not model_name:
        raise ValueError("api_key and model_name are required for gemini")
        
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["client_options"] = {"api_endpoint": base_url}
    genai.configure(**kwargs)
    
    system_instruction = None
    contents = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        if role == "system":
            system_instruction = content
        elif role == "user":
            contents.append({"role": "user", "parts": [content]})
        elif role in ("assistant", "model"):
            contents.append({"role": "model", "parts": [content]})
    generation_config = {}
    if json_mode:
        generation_config["response_mime_type"] = "application/json"
    if temperature is not None:
        generation_config["temperature"] = temperature
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_instruction,
        generation_config=generation_config
    )
    # Gemini client uses its own internal timeout logic, but we can pass it if supported (not natively in simple generate_content)
    return model.generate_content(contents).text.strip()


def _call_mistral_cloud(messages, json_mode, temperature, api_key, model_name, base_url=None, timeout=90):
    if not api_key or not model_name or not base_url:
        raise ValueError("api_key, model_name, and base_url are required for mistral_cloud")
        
    url = base_url if base_url.endswith("/chat/completions") else f"{base_url.rstrip('/')}/chat/completions"
        
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    res = http_session.post(url, json=payload, headers=headers, timeout=timeout)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()


def _call_local(messages, json_mode, temperature, api_key, model_name, base_url, timeout=600):
    if not model_name or not base_url:
        raise ValueError("model_name and base_url are required for mistral_local")
        
    start_time = time.time()
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature}
    }
    if json_mode:
        payload["format"] = "json"
    target_url = f"{base_url.rstrip('/')}/api/chat"
    res = http_session.post(target_url, json=payload, timeout=timeout)
    res.raise_for_status()
    print(f"[LLM Client] Local Mistral responded in {time.time() - start_time:.2f} seconds")
    return res.json()["message"]["content"].strip()


def _call_openai(messages, json_mode, temperature, api_key, model_name, base_url, timeout=90):
    if not api_key or not model_name or not base_url:
        raise ValueError("api_key, model_name, and base_url are required for openai/openrouter")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://traverseai.com",  # Optional, required by some providers like OpenRouter
        "X-Title": "D-Agent"
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        
    target_url = base_url if base_url.endswith("/chat/completions") else f"{base_url.rstrip('/')}/chat/completions"
        
    res = http_session.post(target_url, json=payload, headers=headers, timeout=timeout)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()


PROVIDER_HANDLERS = {
    "gemini": _call_gemini,
    "mistral_cloud": _call_mistral_cloud,
    "local": _call_local,
    "openai": _call_openai,
    "openrouter": _call_openai,
}


def call_llm_chat(messages: list, json_mode: bool = False, temperature: float = 0.3, scenario: str = None, company_id: int = None) -> str:
    # --- DEBUG LOG FOR ALL LLM CALLS ---
    system_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
    if system_msg:
        print(f"\n{'='*60}\n[LLM CLIENT] SYSTEM PROMPT BEING SENT:\n{'-'*60}\n{system_msg}\n{'='*60}\n")
    # -----------------------------------

    if scenario is None:
        scenario = get_current_scenario()
    if company_id is None:
        company_id = detect_current_company_id()

    config = get_assigned_llm_config(scenario, company_id=company_id)
    comp_label = (config.get("_scope") if config else None) or (f"Company: {company_id}" if company_id else "Global Default")

    if not config:
        print(f"[LLM Error] No DB config found for scenario '{scenario}' ({comp_label}). Attempting local fallback.")
        fallback_config = _get_fallback_mistral_local_config()
        if not fallback_config:
            err_msg = f"No DB config found for scenario '{scenario}' and no active local provider available in DB."
            return json.dumps({"error": err_msg}) if json_mode else f"[LLM Error] {err_msg}"
        
        provider = "local"
        api_key = fallback_config.get("api_key")
        model_name = fallback_config.get("model_name")
        base_url = fallback_config.get("base_url")
        timeout_val = 600
        print(f"[LLM Client] DB Routing Active -> Scenario: {scenario} | Scope: {comp_label} | Provider: {provider} | Model: {model_name} (FALLBACK)")
    else:
        provider = config['provider_type']
        api_key = config['api_key']
        model_name = config['model_name']
        base_url = config['base_url']
        if config['temperature'] is not None:
            temperature = config['temperature']
        timeout_val = config.get('timeout')
        if timeout_val is None:
            timeout_val = 600 if provider == "local" else 90
        print(f"[LLM Client] DB Routing Active -> Scenario: {scenario} | Scope: {comp_label} | Provider: {provider} | Model: {model_name}")

    try:
        # 3. Execute with whichever provider was selected, with retry logic
        max_retries = 2
        last_err = None
        
        for attempt in range(max_retries + 1):
            try:
                handler = PROVIDER_HANDLERS.get(provider.strip().lower())
                if handler:
                    return handler(messages, json_mode, temperature, api_key, model_name, base_url, timeout=timeout_val)
                else:
                    print(f"[LLM Client] Unknown provider '{provider}'")
                    return json.dumps({"error": "Invalid config"}) if json_mode else "[LLM Error] Invalid config"
            except Exception as loop_e:
                last_err = loop_e
                if provider == "local" or attempt == max_retries:
                    raise last_err
                print(f"[LLM Client] Attempt {attempt + 1} failed for {provider}: {loop_e}. Retrying...")
                time.sleep(1)

    except Exception as e:
        print(f"[LLM Error] Provider '{provider}' failed after retries: {e}")
        if provider != "mistral_local" and provider != "local":
            print("[LLM Error] Attempting ultimate fallback to local provider from DB...")
            try:
                fallback_config = _get_fallback_mistral_local_config()
                if fallback_config:
                    return _call_local(messages, json_mode, temperature, fallback_config.get("api_key"), fallback_config.get("model_name"), fallback_config.get("base_url"))
                else:
                    raise ValueError("No active local provider found in DB")
            except Exception as fallback_err:
                print(f"[LLM Error] Both primary and local fallback failed. Error: {fallback_err}")
                if json_mode:
                    return json.dumps({"error": "LLM failed completely", "details": str(fallback_err)})
                return f"[LLM Error] Both primary and local fallback failed. Error: {str(fallback_err)}"
        
        if json_mode:
            return json.dumps({"error": "LLM failed completely", "details": str(e)})
        return f"[LLM Error] LLM failed completely. Error: {str(e)}"


def call_llm(prompt: str, scenario: str = None, company_id: int = None) -> str:
    return call_llm_chat([{"role": "user", "content": prompt}], json_mode=False, scenario=scenario, company_id=company_id)

