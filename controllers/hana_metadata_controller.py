from flask import request, jsonify
from database.hana_metadata_service import discover_hana_metadata, get_stored_hana_metadata

def discover_hana_metadata_controller():
    """
    POST /hana/discover-metadata
    Body:
    {
        "user_id": 6,
        "connection_id": 123,
        "session_id": "xyz" (optional)
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        user_id = data.get("user_id")
        connection_id = data.get("connection_id")
        session_id = data.get("session_id")

        if not connection_id:
            return jsonify({
                "status": "error",
                "message": "connection_id is required"
            }), 400

        user_id = int(user_id) if user_id else 0
        connection_id = int(connection_id)

        result = discover_hana_metadata(user_id=user_id, connection_id=connection_id, session_id=session_id)
        return jsonify({
            "status": "success",
            "message": f"Successfully discovered {result.get('total_views', 0)} views and metadata from SAP HANA",
            "data": result
        }), 200

    except Exception as e:
        print(f"[HANA-METADATA-ERROR] {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


def get_hana_metadata_controller():
    """
    GET /hana/metadata?connection_id=123&session_id=xyz&user_id=6
    """
    try:
        connection_id = request.args.get("connection_id")
        session_id = request.args.get("session_id")
        user_id = request.args.get("user_id")

        if not connection_id and not session_id:
            return jsonify({
                "status": "error",
                "message": "Either connection_id or session_id is required"
            }), 400

        cid = int(connection_id) if connection_id else None
        uid = int(user_id) if user_id else None

        metadata = get_stored_hana_metadata(connection_id=cid, session_id=session_id, user_id=uid)
        return jsonify({
            "status": "success",
            "count": len(metadata),
            "data": metadata
        }), 200

    except Exception as e:
        print(f"[HANA-METADATA-GET-ERROR] {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
