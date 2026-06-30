from controllers.dashboard_visuals import available_years_controller
from controllers.dashboard_visuals import year_wise_sales_comparison_controller
from controllers.dashboard_visuals import sales_by_zone_data_controller
from controllers.dashboard_visuals import tyre_sales_data_controller
from controllers.dashboard_visuals import dashboard_filters_controller
import os
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import logging
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore")

# Suppress noisy logs globally BEFORE importing other libraries
logging.getLogger('werkzeug').setLevel(logging.INFO)
for logger_name in ["httpx", "sentence_transformers", "huggingface_hub", "chromadb", "apscheduler", "transformers"]:
    logging.getLogger(logger_name).setLevel(logging.ERROR)

import os
import mysql.connector 
from flask import Flask, request
from flask_cors import CORS
from dotenv import load_dotenv
from urllib.parse import quote_plus
from sqlalchemy import create_engine
from controllers.auth_controller import login , register_user_controller
from controllers.external_db import connect_external_db, apply_external_sync, apply_bulk_sync
from controllers.external_sync_controller import sync_external_csv
from controllers.tracker import get_tracker_data
from concurrent.futures import ThreadPoolExecutor
from controllers.insights import insights_controller
from controllers.analyze_files import analyze_controller
from controllers.view_info import view_analyze_controller
from controllers.login_controller import login_controller
from controllers.visualization import send_from_directory
from controllers.delete_history import delete_session_controller
from controllers.session_controller import fetch_successful_sessions
from controllers.chat import upload_files_controller , rag_chat_controller
from controllers.get_analyze_summary import get_analyze_summary_controller
from controllers.uload_file_count_tablename import upload_files_count_controller
from controllers.active_session_controller import update_active_sessions_controller
from database.config import BASE_URL, MYSQL_CONFIG, MAX_SAMPLE_VALUES, GRAPH_FOLDER, UPLOAD_FOLDER, TEMP_UPLOAD_FOLDER
# --- Database & LLM Services ---
# pyrefly: ignore [missing-import]
from pyvis.network import Network
from database.llm_service import LLMService
from database.database_service import DatabaseService
from controllers.orchestrator_controller import process_books
from controllers.admin_login import staff_login_controller, create_staff_account_controller,get_all_staff_controller
load_dotenv()
from controllers.captcha_controller import generate_captcha_controller
from flask import send_from_directory
from controllers.connector_controller import create_connector_controller, agent_query_controller
from controllers.web_search_controller import web_search_controller
from controllers.save_result_controller import (
    save_result_controller,
    get_saved_results_controller,
    delete_saved_result_controller
)
from controllers.saved_content_analysis_controller import (
    saved_content_describe_controller,
    saved_content_chat_controller
)
from controllers.sheet_scan_controller import sheet_scan_controller
from controllers.sheet_content_controller import sheet_describe_controller, sheet_chat_controller
from controllers.connector_controllers import (create_connector_controllers,
                                               agent_query_controllers, create_user_controller, delete_workspace_controller,
                                               get_connection_history_controller,
                                               get_saved_credentials_controller, get_user_workspaces_simple,
                                               get_workspace_history_controller,
                                               create_workspace_controller,
                                                get_user_workspaces_controller, set_active_workspace,
                                                get_all_users_controller,
                                                assign_workspace_users_controller,
                                                get_workspace_users_controller,
                                                remove_workspace_user_controller,
                                                delete_connection_history_controller,
                                                delete_workspace_controller)
from controllers.session_rag_chat_controller import session_rag_chat_controller
from controllers.session_sources_controller import session_sources_controller
from controllers.session_analysis_controller import session_analysis_controller
from controllers.uploads_controller import upload_chunk_controller, upload_universal_dump_controller , upload_csv_controller
from controllers.session_chat_history_controller import session_chat_history_controller
from controllers.admin_knowledge_controller import admin_get_chats_controller, admin_push_knowledge_controller, admin_get_staged_knowledge_controller, admin_trigger_indexing_controller, admin_set_schedule_controller, admin_get_schedule_controller


from controllers.ftp_connector_controller import (
    ftp_connect_controller,
    ftp_fetch_controller,
    ftp_progress_controller,
    ftp_schedule_controller,
    ftp_delete_schedule_controller,
    ftp_get_schedule_controller,
    ftp_fetch_log_controller,
)
from controllers.dashboard_visuals import graph_metrics_controller,extract_graph_data_controller, default_dashboard_metrics_controller


from flask_socketio import SocketIO
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
CORS(app)

# Create necessary folders if not exist
for folder in [GRAPH_FOLDER, UPLOAD_FOLDER, TEMP_UPLOAD_FOLDER]:
    os.makedirs(folder, exist_ok=True)


MYSQL_URI = (
    f"mysql+pymysql://{MYSQL_CONFIG['user']}:{quote_plus(MYSQL_CONFIG['password'])}"
    f"@{MYSQL_CONFIG['host']}:{MYSQL_CONFIG['port']}/{MYSQL_CONFIG['database']}"
)

engine = create_engine(MYSQL_URI, pool_recycle=3600, pool_pre_ping=True)

# Helper function to create a new mysql.connector connection for the controllers
def get_db_connection():
    """Establishes and returns a raw mysql.connector connection."""
    try:
        conn = mysql.connector.connect(
            host=MYSQL_CONFIG['host'],
            port=MYSQL_CONFIG['port'],
            user=MYSQL_CONFIG['user'],
            password=MYSQL_CONFIG['password'],
            database=MYSQL_CONFIG['database']
        )
        return conn
    except mysql.connector.Error as err:
        print(f"Error connecting to MySQL DB: {err}")
        return None
# ------------------- Flask App -------------------
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024 * 1024


UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")  
os.makedirs(UPLOAD_FOLDER, exist_ok=True) 

  
# Global thread pool
executor = ThreadPoolExecutor(max_workers=8) 


# ---------------------------------- API Endpoints ---------------------------------

# Insight
@app.route("/insight", methods=["POST"])
def insights():
    return insights_controller()

# tracker
@app.route('/tracker', methods=['GET'])
def get_tracker_data_():
    return get_tracker_data()

# Analyze Files
@app.route("/analyze_files", methods=["POST"])
def analyze():
    return analyze_controller()



@app.route('/upload', methods=['POST'])
def process_books_route():
    return process_books()


# RAG Chat (vector database)
@app.route("/rag_chat", methods=["POST"])
def rag_chat_route():
    return rag_chat_controller()

# View Info
@app.route("/view_info", methods=["GET"])
def view_analyze():
    return view_analyze_controller() 


@app.route("/graphs/<filename>")
def send_graph(filename):
    return send_from_directory(GRAPH_FOLDER, filename)

 

@app.route("/upload_files", methods=["POST"])
def upload_files():
    return upload_files_controller()


@app.route("/uploadfile_details", methods=["POST"])
def get_analyze_summary_():
    return get_analyze_summary_controller()

@app.route("/upload_files_count", methods=["POST"])
def upload_files_count():
    return upload_files_count_controller()

@app.route("/delete_session/<string:session_name>", methods=["DELETE"])
def delete_session(session_name):
    return delete_session_controller(session_name)


# --- NEW ROUTE: LOGIN ---

@app.route("/register", methods=["POST"])
def register():
    return register_user_controller(get_db_connection)

@app.route('/login', methods=['POST'])
def login_route():
    # Pass the original pymysql connection function (get_connection) to the controller
    return login_controller(get_db_connection)


# 🆕 NEW ROUTE HERE
@app.route('/successful_sessions', methods=['GET'])
def get_successful_sessions_route():
    return fetch_successful_sessions()


@app.route('/update_active_sessions', methods=['POST'])
def update_active_sessions_route():
    return update_active_sessions_controller()


# =======================
# EXPERT / ADMIN ROUTES
# =======================

#admin, expert, superadmin login  
@app.route("/admin_expert_login", methods=["POST"])
def staff_login():
    """Route for Super Admin, Admin, and Expert Login"""
    return staff_login_controller()

#superadmin can ceate multiple admin and expert 
@app.route('/admin_expert_registration', methods=['POST'])
def create_staff():
    return create_staff_account_controller()

# NEW: Route to get list of admins/experts
@app.route("/admin_expert_list", methods=["GET"])
def get_staff_list():
    return get_all_staff_controller()


@app.route("/generate_captcha", methods=["GET"])
def generate_captcha():
    return generate_captcha_controller(get_db_connection)



# ==========================
#      SEO API ROUTES
# ==========================


@app.route("/invoices/<filename>")
def serve_invoice(filename):
    return send_from_directory("invoices", filename)

@app.route("/logo")
def logo():
    return send_from_directory("logo", "newlogo.png")
# --- Database Connector Routes ---

@app.route("/create_connector", methods=["POST"])
def create_db_connector():
    """Saves connection details from the UI you shared"""
    return create_connector_controller()

@app.route("/agent/query_db", methods=["POST"])
def agent_query_db():
    """The endpoint your Agent will call to 'process the db directly'"""
    return agent_query_controller()


@app.route("/login", methods=["POST"])
def login_controller(data):
    return login()

@app.route("/connect-external-db", methods=["POST"])
def connect_external_db_controller():
    return connect_external_db()

@app.route("/apply", methods=["POST"])
def apply_external_sync_controller():
    return apply_external_sync()    

# ─────────────────────────────────────────────
# WEB SEARCH
# ─────────────────────────────────────────────

@app.route("/search", methods=["POST"])
def search():
    return web_search_controller(get_db_connection)

@app.route("/save-result", methods=["POST"])
def save_result():
    return save_result_controller(get_db_connection)

@app.route("/saved-results", methods=["GET"])
def get_saved_results():
    return get_saved_results_controller(get_db_connection)

@app.route("/saved-results/<string:saved_id>", methods=["DELETE"])
def delete_saved_result(saved_id):
    return delete_saved_result_controller(get_db_connection, saved_id)

@app.route("/saved-content/describe", methods=["POST"])
def saved_content_describe():
    return saved_content_describe_controller(get_db_connection)

@app.route("/saved-content/chat", methods=["POST"])
def saved_content_chat():
    return saved_content_chat_controller(get_db_connection)

@app.route("/sheet/scan", methods=["POST"])
def sheet_scan():
    return sheet_scan_controller(get_db_connection)

@app.route("/sheet/describe", methods=["POST"])
def sheet_describe():
    return sheet_describe_controller(get_db_connection)

@app.route("/sheet/chat", methods=["POST"])
def sheet_chat():
    return sheet_chat_controller(get_db_connection)

# --- Database Connector Routes ---
@app.route('/create_workspace', methods=['POST'])
def create_workspace_route():
    return create_workspace_controller(get_db_connection)


# 1. Update your existing POST route to pass the get_db_connection helper
@app.route("/create_connectors", methods=["POST"])
def create_db_connectors():
    """Saves connection details from the UI you shared"""
    return create_connector_controllers(get_db_connection)


# 2. Add the NEW GET route to fetch the history
@app.route('/connection_history', methods=['GET', 'DELETE'])
def connection_history():
    if request.method == 'DELETE':
        return delete_connection_history_controller(get_db_connection)
    return get_connection_history_controller(get_db_connection)

@app.route("/workspace_history", methods=["GET"])
def workspace_history():
    """Returns connection history for a specific workspace/session"""
    return get_workspace_history_controller(get_db_connection)

@app.route('/workspaces', methods=['GET'])
def get_user_workspaces_route():
    """Returns a list of all workspaces for a specific user"""
    return get_user_workspaces_controller(get_db_connection)


# 3. Your agent query route stays exactly the same
@app.route("/agent/query_dbs", methods=["POST"])
def agent_query_dbs():
    """The endpoint your Agent will call to 'process the db directly'"""
    return agent_query_controllers()

@app.route("/saved_credentials", methods=["GET"])
def get_saved_credentials():
    """Fetches a user's saved database credentials"""
    return get_saved_credentials_controller(get_db_connection)

@app.route("/session-chat", methods=["POST"])
def session_chat():
    return session_rag_chat_controller(get_db_connection)

@app.route('/api/apply_bulk_sync', methods=['POST']) 
def apply_bulk_sync_route():
    return apply_bulk_sync()

@app.route("/session-sources", methods=["GET"])
def session_sources():
    return session_sources_controller(get_db_connection)

from controllers.session_analysis_controller import session_analysis_controller
from controllers.session_history_controller import get_session_analysis_history

@app.route("/session-analysis", methods=["POST"])
def session_analysis():
    return session_analysis_controller(get_db_connection)

@app.route("/session-analysis-history", methods=["GET"])
def session_analysis_history():
    return get_session_analysis_history(get_db_connection)

@app.route("/set-active-workspace", methods=["POST"])
def set_active_workspace_controller():
    return set_active_workspace(get_db_connection)

@app.route("/upload_universal_dump", methods=["POST"])
def upload_universal_dump_route():
    return upload_universal_dump_controller(get_db_connection)

@app.route("/upload_csv", methods=["POST"])
def upload_csv_route():
    return upload_csv_controller(get_db_connection)


@app.route('/api/admin/chats', methods=['GET'])
def admin_chats():
    return admin_get_chats_controller(get_db_connection)

@app.route('/api/admin/push_to_kg', methods=['POST'])
def admin_push_kg():
    return admin_push_knowledge_controller(get_db_connection)


@app.route('/api/admin/staged_knowledge', methods=['GET'])
def admin_staged_knowledge():
    return admin_get_staged_knowledge_controller(get_db_connection)

@app.route('/api/admin/trigger_indexing', methods=['POST'])
def admin_trigger_indexing():
    return admin_trigger_indexing_controller(get_db_connection)


@app.route('/api/admin/kg_schedule', methods=['POST'])
def admin_set_kg_schedule():
    return admin_set_schedule_controller(get_db_connection)

@app.route('/api/admin/kg_schedule', methods=['GET'])
def admin_get_kg_schedule():
    return admin_get_schedule_controller(get_db_connection)

@app.route('/users', methods=['GET'])
def get_all_users():
    return get_all_users_controller(get_db_connection)

@app.route('/assign_workspace_users', methods=['POST'])
def assign_workspace_users():
    return assign_workspace_users_controller(get_db_connection)

@app.route('/workspace_users', methods=['POST'])
def get_workspace_users():
    return get_workspace_users_controller(get_db_connection)

@app.route('/remove_workspace_user', methods=['DELETE'])
def remove_workspace_user():
    return remove_workspace_user_controller(get_db_connection)

@app.route("/get-workspace", methods=["GET"])
def get_user_workspaces_simple_controller():
    return get_user_workspaces_simple(get_db_connection)


@app.route("/create_user", methods=["POST"])
def create_user():
    return create_user_controller(get_db_connection)



@app.route("/session-chat-history", methods=["GET", "POST", "DELETE"])
def session_chat_history():
    return session_chat_history_controller(get_db_connection)

@app.route("/upload_chunk", methods=["POST"])
def upload_chunk_controller_route():
    return upload_chunk_controller(get_db_connection)
       


from controllers.import_csv_controller import import_csv_data
from controllers.import_sql_controller import import_sql_data

@app.route("/import-csv-data", methods=["POST"])
def import_csv_data_controller():
    return import_csv_data(get_db_connection)

@app.route("/import-sql-data", methods=["POST"])
def import_sql_data_controller():
    return import_sql_data(get_db_connection)


# FTP Connector — test & save credentials
@app.route("/ftp/connect", methods=["POST"])
def ftp_connect():
    return ftp_connect_controller(get_db_connection)

# FTP Connector — trigger an immediate fetch (returns job_id)
@app.route("/ftp/fetch", methods=["POST"])
def ftp_fetch():
    return ftp_fetch_controller(get_db_connection)

# FTP Connector — SSE stream for incremental fetch progress
@app.route("/ftp/progress/<string:job_id>", methods=["GET"])
def ftp_progress(job_id):
    return ftp_progress_controller(job_id)

# FTP Connector — create / update a recurring schedule
@app.route("/ftp/schedule", methods=["POST"])
def ftp_schedule():
    return ftp_schedule_controller(get_db_connection)

# FTP Connector — delete / pause a schedule
@app.route("/ftp/schedule", methods=["DELETE"])
def ftp_delete_schedule():
    return ftp_delete_schedule_controller(get_db_connection)

# FTP Connector — get current schedule info
@app.route("/ftp/schedule", methods=["GET"])
def ftp_get_schedule():
    return ftp_get_schedule_controller(get_db_connection)

# FTP Connector — historical fetch log
@app.route("/ftp/fetch_log", methods=["GET"])
def ftp_fetch_log():
    return ftp_fetch_log_controller(get_db_connection)

# Workspace Delete
@app.route('/delete_workspace', methods=['DELETE'])
def delete_workspace():
    return delete_workspace_controller(get_db_connection)


# Dashboard Visuals 
@app.route("/graph-metrics", methods=["POST"])
def graph_metrics():
    return graph_metrics_controller()

@app.route("/graph-extract-data", methods=["POST"])
def extract_graph_data():
    return extract_graph_data_controller()    

@app.route("/default-dashboard-metrics", methods=["POST"])
def default_dashboard_metrics():
    return default_dashboard_metrics_controller(get_db_connection)

@app.route("/tyre-sales-data", methods=["POST"])
def tyre_sales_data():
    return tyre_sales_data_controller(get_db_connection)

@app.route("/dashboard-filters/", methods=["GET"])
def dashboard_filters():
    return dashboard_filters_controller(get_db_connection)

@app.route("/sales-by-zone", methods=["POST"])
def sales_by_zone():
    return sales_by_zone_data_controller(get_db_connection)    


@app.route("/year-wise-sales-comparison", methods=["POST"])
def year_wise_sales_comparison():
    return year_wise_sales_comparison_controller(get_db_connection)

@app.route("/available-years", methods=["GET"])
def available_years():
    return available_years_controller(get_db_connection)    


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True, use_reloader=False)