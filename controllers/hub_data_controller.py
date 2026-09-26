import json
import requests
from flask import request, jsonify

def store_hub_data_controller(get_db_connection):
    data = request.json or {}
    
    session_id = data.get("session_id")
    name = data.get("name")
    email = data.get("email")
    age = data.get("age")
    gender = data.get("gender")
    # UI হয়তো 'query' পাঠাচ্ছে, কিন্তু মেইন চ্যাট API 'question' খোঁজে, তাই দুটোর সাপোর্ট রাখলাম
    query_text = data.get("question") or data.get("query") 

    if not session_id:
        return jsonify({"status": "error", "message": "session_id is required"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        cursor = conn.cursor()
        
        # ১. ইউজারের লিড ডাটা সেভ করা হচ্ছে
        if name or email or age or gender:
            lead_query = """
                INSERT INTO user_chat_leads (session_id, name, email, age, gender, chat_data)
                VALUES (%s, %s, %s, %s, %s, JSON_ARRAY())
                ON DUPLICATE KEY UPDATE 
                    name = COALESCE(VALUES(name), name), 
                    email = COALESCE(VALUES(email), email), 
                    age = COALESCE(VALUES(age), age), 
                    gender = COALESCE(VALUES(gender), gender);
            """
            cursor.execute(lead_query, (session_id, name, email, age, gender))
            conn.commit()
            
        # ২. প্রক্সি: যদি প্রশ্ন (query) থাকে, তবে মেইন চ্যাট API-কে ইন্টারনালি কল করবে
        if query_text:
            # অরিজিনাল হেডারগুলো কপি করা হচ্ছে (host/content-length বাদে)
            headers = {k: v for k, v in request.headers if k.lower() not in ['host', 'content-length']}
            
            # মেইন চ্যাট API-এর URL ডাইনামিক্যালি তৈরি হচ্ছে
            chat_url = request.host_url.rstrip('/') + "/session-chat"
            
            # মেইন API-তে ডাটা ফরোয়ার্ড করা হচ্ছে
            forward_data = data.copy()
            if "question" not in forward_data and query_text:
                forward_data["question"] = query_text
                
            try:
                # মেইন চ্যাট API (LLM) কল হচ্ছে
                chat_resp = requests.post(chat_url, json=forward_data, headers=headers, timeout=120)
                chat_result = chat_resp.json()
                
                # LLM থেকে আসা উত্তরটি বের করে আনা হচ্ছে
                response_text = chat_result.get("answer", "")
                
                if response_text:
                    # ৩. প্রশ্ন এবং উত্তরটি ডাটাবেসের JSON-এ সেভ করা হচ্ছে
                    new_chat_entry = json.dumps({"query": query_text, "response": response_text})
                    chat_query = """
                        INSERT INTO user_chat_leads (session_id, chat_data) 
                        VALUES (%s, JSON_ARRAY(CAST(%s AS JSON)))
                        ON DUPLICATE KEY UPDATE 
                            chat_data = JSON_ARRAY_APPEND(COALESCE(chat_data, JSON_ARRAY()), '$', CAST(%s AS JSON));
                    """
                    cursor.execute(chat_query, (session_id, new_chat_entry, new_chat_entry))
                    conn.commit()
                
                # ৪. মেইন চ্যাট API থেকে পাওয়া রেসপন্সটাই হুবহু UI-কে ফেরত দেওয়া হচ্ছে!
                return jsonify(chat_result), chat_resp.status_code
                
            except requests.exceptions.RequestException as e:
                return jsonify({"status": "error", "message": f"Error calling main chat API: {str(e)}"}), 500

        # যদি কোনো প্রশ্ন না থাকে, শুধু লিড সেভের সাকসেস মেসেজ দেবে
        return jsonify({"status": "success", "message": "Lead data stored successfully"}), 200
        
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
