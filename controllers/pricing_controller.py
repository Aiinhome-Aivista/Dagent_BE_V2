from flask import jsonify, request
# pyrefly: ignore [missing-import]
import mysql.connector
from database.config import MYSQL_CONFIG

def get_db_connection():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except mysql.connector.Error as err:
        print(f"Error connecting to MySQL DB: {err}")
        return None

def get_all_pricing_plans():
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    query = "SELECT * FROM pricing_plans ORDER BY id ASC"
    try:
        cursor.execute(query)
        return cursor.fetchall()
    except Exception as e:
        print(f"Error fetching pricing plans: {e}")
        return []
    finally:
        cursor.close()
        conn.close()

def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

def create_pricing_plan(data):
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    query = """
    INSERT INTO pricing_plans 
    (plan_name, data_storage, uploads, insights_queries, basic_features, download_allowed, number_of_users, custom_kpi, scheduled_email)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        data.get("plan_name", ""),
        safe_int(data.get("data_storage", 0)),
        safe_int(data.get("uploads", 0)),
        safe_int(data.get("insights_queries", 0)),
        data.get("basic_features", ""),
        data.get("download_allowed", ""),
        safe_int(data.get("number_of_users", 0)),
        data.get("custom_kpi", ""),
        data.get("scheduled_email", "")
    )
    try:
        cursor.execute(query, values)
        conn.commit()
        return True
    except Exception as e:
        print(f"Error creating pricing plan: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def update_pricing_plan(plan_id, data):
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    query = """
    UPDATE pricing_plans 
    SET plan_name = %s, data_storage = %s, uploads = %s, insights_queries = %s, 
        basic_features = %s, download_allowed = %s, number_of_users = %s, 
        custom_kpi = %s, scheduled_email = %s
    WHERE id = %s
    """
    values = (
        data.get("plan_name", ""),
        safe_int(data.get("data_storage", 0)),
        safe_int(data.get("uploads", 0)),
        safe_int(data.get("insights_queries", 0)),
        data.get("basic_features", ""),
        data.get("download_allowed", ""),
        safe_int(data.get("number_of_users", 0)),
        data.get("custom_kpi", ""),
        data.get("scheduled_email", ""),
        plan_id
    )
    try:
        cursor.execute(query, values)
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating pricing plan: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def delete_pricing_plan(plan_id):
    conn = get_db_connection()
    if not conn:
        return False
    cursor = conn.cursor()
    query = "DELETE FROM pricing_plans WHERE id = %s"
    try:
        cursor.execute(query, (plan_id,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error deleting pricing plan: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def get_pricing_controller():
    try:
        plans = get_all_pricing_plans()
        return jsonify({"status": "success", "pricing": plans}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def create_pricing_controller():
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400
    
    success = create_pricing_plan(data)
    if success:
        return jsonify({"status": "success", "message": "Pricing plan created successfully"}), 201
    else:
        return jsonify({"status": "error", "message": "Failed to create pricing plan"}), 500

def update_pricing_controller(plan_id):
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400
        
    success = update_pricing_plan(plan_id, data)
    if success:
        return jsonify({"status": "success", "message": "Pricing plan updated successfully"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to update pricing plan"}), 500

def delete_pricing_controller(plan_id):
    success = delete_pricing_plan(plan_id)
    if success:
        return jsonify({"status": "success", "message": "Pricing plan deleted successfully"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to delete pricing plan"}), 500
