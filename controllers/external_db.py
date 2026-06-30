from flask import request, jsonify
from database.external_sync_service import apply_external_sync as apply_external_sync_service, sync_external_database , apply_bulk_external_sync


def connect_external_db():

    data = request.json

    user_id = int(data.get("user_id"))          
    connection_id = int(data.get("connection_id"))
    session_id = data.get("session_id")         

    print("INPUT →", user_id, connection_id, session_id)

    if not user_id or not connection_id or not session_id:
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Missing data"
        }), 400

    result = sync_external_database(user_id, connection_id, session_id)

    if not result["situations"] and not result["new_tables"]:
        return jsonify({
            "status": True,
            "statuscode": 200,
            "data": {
                "summary": result["summary"],
                "tables": result["tables"]
            },
            "msg": "Database already up to date. No changes detected."
        })

    return jsonify({
        "status": True,
        "statuscode": 200,
        "data": {
            "situations": result["situations"],
            "tables": result["tables"],
            "summary": result["summary"]
        },
        "msg": "External database analyzed successfully"
    })

def apply_external_sync():

    data = request.json

    user_id = data.get("user_id")
    connection_id = data.get("connection_id")
    session_id = data.get("session_id")
    table = data.get("table")

    if not user_id or not connection_id or not session_id or not table:
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Missing required fields"
        }), 400

    apply_external_sync_service(user_id, connection_id, session_id, table)

    return jsonify({
        "status": True,
        "statuscode": 200,
        "data": None,
        "msg": "External sync applied successfully"
    })

def apply_bulk_sync():
    """
    API endpoint to handle bulk synchronization of multiple tables.
    Supports 'update' (append new rows/add new tables) and 'replace' (drop and recreate).
    """
    data = request.json

    user_id = data.get("user_id")
    connection_id = data.get("connection_id")
    session_id = data.get("session_id")
    tables = data.get("tables") # Now expects a list of table names
    action = data.get("action", "update") # "update" (Update Existing) or "replace" (Replace All)

    if not user_id or not connection_id or not tables or not isinstance(tables, list):
        return jsonify({
            "status": False,
            "statuscode": 400,
            "data": None,
            "msg": "Missing required fields or 'tables' is not a list"
        }), 400

    try:
        apply_bulk_external_sync(user_id, connection_id, session_id, tables, action)
        
        return jsonify({
            "status": True,
            "statuscode": 200,
            "data": None,
            "msg": f"Successfully applied '{action}' sync for {len(tables)} tables."
        })
    except Exception as e:
        return jsonify({
            "status": False,
            "statuscode": 500,
            "data": None,
            "msg": str(e)
        }), 500
