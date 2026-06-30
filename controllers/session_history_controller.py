from flask import request, jsonify

def get_session_analysis_history(get_connection_func):
    session_id = request.args.get('session_id')
    
    if not session_id:
        return jsonify({"status": "failed", "statusCode": 400, "message": "session_id is required"}), 400

    conn = cur = None
    try:
        conn = get_connection_func()
        cur = conn.cursor(dictionary=True)
        
        # Check if table exists
        cur.execute("SHOW TABLES LIKE 'analysis_cache'")
        if not cur.fetchone():
            return jsonify({"status": "success", "statusCode": 200, "history": []}), 200

        cur.execute("""
            SELECT id, session_id, report, graph_url, topics, databases, created_at 
            FROM analysis_cache 
            WHERE session_id = %s
            ORDER BY created_at DESC
        """, (session_id,))
        
        rows = cur.fetchall()
        
        history = []
        for r in rows:
            history.append({
                "id": r["id"],
                "session_id": r["session_id"],
                "report": r["report"],
                "graph_url": r["graph_url"],
                "topics": r["topics"],
                "databases": r["databases"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None
            })
            
        return jsonify({
            "status": "success",
            "statusCode": 200,
            "history": history
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "statusCode": 500, "message": str(e)}), 500
    finally:
        if cur: cur.close()
        if conn: conn.close()
