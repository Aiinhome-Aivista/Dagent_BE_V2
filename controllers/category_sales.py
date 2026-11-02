import sys
import os
from flask import request, jsonify
from helper.sap_analytics_service import execute_category_sales
from helper.dashboard_cache_service import get_cached_component_data, set_cached_component_data


def get_category_sales_controller(get_db_connection):
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed"}), 500

    try:
        session_id = request.args.get("session_id")
        zone = request.args.get("zone")
        force_refresh = request.args.get("force_refresh", "").lower() in ("true", "1")
        is_default = not zone or str(zone).lower() == "all"

        if is_default and not force_refresh:
            cached = get_cached_component_data(conn, session_id, "category_sales", "all")
            if cached and cached.get("data") is not None:
                return jsonify({
                    "status": "success",
                    "data": cached["data"],
                    "_cached": True,
                    "_last_synced_at": cached.get("_last_synced_at")
                }), 200

        results = execute_category_sales(conn, session_id, zone=zone)
        if is_default and results is not None:
            set_cached_component_data(conn, session_id, "category_sales", results, "all")

        return jsonify({
            "status": "success",
            "data": results
        }), 200
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
    finally:
        if conn and conn.is_connected():
            conn.close()
