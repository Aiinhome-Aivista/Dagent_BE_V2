import requests
import json 
# pyrefly: ignore [missing-import]
import google.generativeai as genai
from database.config import ACTIVE_LLM, GEMINI_API_KEY, MODEL_NAME, MISTRAL_API_KEY, MISTRAL_MODEL, MISTRAL_LOCAL_URL, MISTRAL_LOCAL_MODEL


def call_llm_chat(messages: list, json_mode: bool = False, temperature: float = 0.3) -> str:
    print(f"[LLM Client] Using ACTIVE_LLM: {ACTIVE_LLM}")
    try:
        # 1. Gemini Cloud
        if ACTIVE_LLM == "gemini":
            genai.configure(api_key=GEMINI_API_KEY)
            
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
                model_name=MODEL_NAME,
                system_instruction=system_instruction,
                generation_config=generation_config
            )
            response = model.generate_content(contents)
            return response.text.strip()

        # 2. Mistral Cloud API
        elif ACTIVE_LLM == "mistral_cloud":
            url = "https://api.mistral.ai/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": MISTRAL_MODEL,
                "messages": messages,
                "temperature": temperature
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
                
            res = requests.post(url, json=payload, headers=headers, timeout=90)
            res.raise_for_status()
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()

        # 3. 🧠 Local Ollama (with local fallback if public IP times out)
        elif ACTIVE_LLM == "mistral_local":
            import time
            start_time = time.time()
            payload = {
                "model": MISTRAL_LOCAL_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature}
            }
            if json_mode:
                payload["format"] = "json"

            # Try configured remote IP first
            url = f"{MISTRAL_LOCAL_URL}/api/chat"
            try:
                res = requests.post(url, json=payload, timeout=300)
                res.raise_for_status()
                data = res.json()
                print(f"[LLM Client] Local Mistral responded in {time.time() - start_time:.2f} seconds (Remote IP)")
                return data["message"]["content"].strip()
            except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
                print(f"[LLM Client] Remote IP failed ({e}), trying localhost fallback...")
                # Fallback to localhost if remote IP connection fails/times out
                fallback_url = "http://localhost:11434/api/chat"
                res = requests.post(fallback_url, json=payload, timeout=300)
                res.raise_for_status()
                data = res.json()
                print(f"[LLM Client] Local Mistral responded in {time.time() - start_time:.2f} seconds (Fallback Localhost)")
                return data["message"]["content"].strip()

        # Invalid LLM setting
        else:
            return "[LLM Error] Invalid ACTIVE_LLM configuration."

    except Exception as e:
        return f"[LLM Error] {str(e)}"


def call_llm(prompt: str) -> str:
    return call_llm_chat([{"role": "user", "content": prompt}], json_mode=False)

