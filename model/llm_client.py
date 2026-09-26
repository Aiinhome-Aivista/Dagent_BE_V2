import requests
import json 
import time
from flask import request, has_request_context
# pyrefly: ignore [missing-import]
import google.generativeai as genai
from database.config import engine, ACTIVE_LLM, GEMINI_API_KEY, MODEL_NAME, MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_LOCAL_URL, MISTRAL_LOCAL_MODEL

# Global HTTP Session for connection pooling
http_session = requests.Session()

# Simple in-memory cache for LLM configs
_config_cache = {}
CACHE_TTL = 300  # 5 minutes


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
    except Exception:
        pass
    return "rag_chat"


def get_assigned_llm_config(scenario):
    """Fetch the LLM configuration for the given scenario from the DB."""
    now = time.time()
    if scenario in _config_cache:
        cached = _config_cache[scenario]
        if now - cached["timestamp"] < CACHE_TTL:
            return cached["data"]
            
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            query = text("""
                SELECT p.provider_type, p.api_key, p.model_name, p.base_url, a.temperature, a.max_tokens
                FROM llm_scenario_assignments a
                JOIN llm_providers p ON a.provider_id = p.id
                WHERE a.scenario = :scenario AND p.is_active = TRUE
            """)
            result = conn.execute(query, {"scenario": scenario})
            row = result.mappings().fetchone()
            
        config_data = dict(row) if row else None
        _config_cache[scenario] = {"data": config_data, "timestamp": now}
        return config_data
    except Exception as e:
        print(f"[LLM Client] DB fetch error for scenario '{scenario}': {e}")
        if scenario in _config_cache:
            return _config_cache[scenario]["data"]
        return None


def _call_gemini(messages, json_mode, temperature, api_key, model_name, timeout=90):
    genai.configure(api_key=api_key or GEMINI_API_KEY)
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
        model_name=model_name or MODEL_NAME,
        system_instruction=system_instruction,
        generation_config=generation_config
    )
    return model.generate_content(contents).text.strip()


def _call_mistral_cloud(messages, json_mode, temperature, api_key, model_name, timeout=90):
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key or MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name or MISTRAL_MODEL,
        "messages": messages,
        "temperature": temperature
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    res = http_session.post(url, json=payload, headers=headers, timeout=timeout)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()


def _call_mistral_local(messages, json_mode, temperature, model_name, base_url, timeout=600):
    start_time = time.time()
    payload = {
        "model": model_name or MISTRAL_LOCAL_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature}
    }
    if json_mode:
        payload["format"] = "json"
    
    raw_base = (base_url or MISTRAL_LOCAL_URL or "").strip().rstrip('/')
    if raw_base.endswith('/api/chat'):
        target_url = raw_base
    else:
        target_url = f"{raw_base}/api/chat"

    res = http_session.post(target_url, json=payload, timeout=timeout)
    res.raise_for_status()
    print(f"[LLM Client] Local Mistral responded in {time.time() - start_time:.2f} seconds")
    return res.json()["message"]["content"].strip()


def _call_openai(messages, json_mode, temperature, api_key, model_name, base_url, timeout=90):
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
    
    if base_url and base_url.strip():
        raw_base = base_url.strip().rstrip('/')
        if raw_base.endswith('/chat/completions'):
            target_url = raw_base
        else:
            target_url = f"{raw_base}/chat/completions"
    else:
        target_url = "https://api.openai.com/v1/chat/completions"

    res = http_session.post(target_url, json=payload, headers=headers, timeout=timeout)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()


def call_llm_chat(messages: list, json_mode: bool = False, temperature: float = 0.3, scenario: str = None) -> str:
    system_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
    if system_msg:
        print(f"\n{'='*60}\n[LLM CLIENT] SYSTEM PROMPT BEING SENT:\n{'-'*60}\n{system_msg[:500]}\n{'='*60}\n")

    if scenario is None:
        scenario = get_current_scenario()
    config = get_assigned_llm_config(scenario)

    # 1. Start with baseline .env defaults
    provider = ACTIVE_LLM 
    api_key = None
    model_name = None
    base_url = None

    # 2. If DB has an active assignment for this scenario, override the .env defaults
    if config:
        provider = config['provider_type']
        api_key = config['api_key']
        model_name = config['model_name']
        base_url = config['base_url']
        if config['temperature'] is not None:
            temperature = config['temperature']
        print(f"[LLM Client] DB Routing Active -> Scenario: {scenario} | Provider: {provider} | Model: {model_name}")
    else:
        print(f"[LLM Client] No DB config for scenario '{scenario}' -> Falling back to .env ACTIVE_LLM: {ACTIVE_LLM}")

    try:
        max_retries = 2
        last_err = None
        
        for attempt in range(max_retries + 1):
            try:
                if provider == "gemini":
                    return _call_gemini(messages, json_mode, temperature, api_key, model_name)
                elif provider == "mistral_cloud":
                    return _call_mistral_cloud(messages, json_mode, temperature, api_key, model_name)
                elif provider == "mistral_local":
                    return _call_mistral_local(messages, json_mode, temperature, model_name, base_url)
                elif provider == "openai":
                    return _call_openai(messages, json_mode, temperature, api_key, model_name, base_url)
                else:
                    print(f"[LLM Client] Unknown provider '{provider}', falling back to .env config")
                    return json.dumps({"error": "Invalid config"}) if json_mode else "[LLM Error] Invalid config"
            except Exception as loop_e:
                last_err = loop_e
                if provider == "mistral_local" or attempt == max_retries:
                    raise last_err
                print(f"[LLM Client] Attempt {attempt + 1} failed for {provider}: {loop_e}. Retrying...")
                time.sleep(1)

    except Exception as e:
        print(f"[LLM Error] Primary provider '{provider}' failed after retries: {e}. Attempting local mistral fallback...")
        try:
            return _call_mistral_local(messages, json_mode, temperature, None, None)
        except Exception as fallback_err:
            print(f"[LLM Error] Both primary and local fallback failed. Error: {fallback_err}")
            if json_mode:
                return json.dumps({"error": "LLM failed completely", "details": str(fallback_err)})
            return f"[LLM Error] Both primary and local fallback failed. Error: {str(fallback_err)}"


def call_llm(prompt: str, scenario: str = None) -> str:
    return call_llm_chat([{"role": "user", "content": prompt}], json_mode=False, scenario=scenario)
