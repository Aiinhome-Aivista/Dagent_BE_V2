import json
import time
from datetime import datetime

CACHE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `dashboard_cached_metrics` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(100) NOT NULL COMMENT 'Workspace or Session ID',
    `component_key` VARCHAR(100) NOT NULL COMMENT 'e.g. key_metrics, sales_revenue, sales_by_zone',
    `filter_context` VARCHAR(255) DEFAULT 'all' COMMENT 'Filter details e.g. all or zone=NZ',
    `payload` LONGTEXT NOT NULL COMMENT 'Complete JSON payload rendered directly by UI',
    `row_count` INT DEFAULT 0 COMMENT 'Number of records represented',
    `last_synced_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `sync_status` ENUM('success', 'failed', 'running') DEFAULT 'success',
    `execution_duration_sec` DECIMAL(8, 2) DEFAULT 0.00,
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_session_component_filter` (`session_id`, `component_key`, `filter_context`),
    INDEX `idx_session_component` (`session_id`, `component_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SCHEDULER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `scheduler_configurations` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `job_name` VARCHAR(100) UNIQUE NOT NULL,
    `title` VARCHAR(255) DEFAULT 'Dashboard Key Metrics & Analytics Sync',
    `schedule_time` VARCHAR(10) DEFAULT '19:00' COMMENT 'Daily time in 24hr HH:MM format',
    `frequency` VARCHAR(50) DEFAULT 'daily' COMMENT 'daily, twice_daily, thrice_daily',
    `is_active` BOOLEAN DEFAULT TRUE,
    `last_run_at` DATETIME DEFAULT NULL,
    `last_run_status` VARCHAR(50) DEFAULT 'idle',
    `last_run_duration_sec` DECIMAL(8, 2) DEFAULT 0.00,
    `next_run_at` DATETIME DEFAULT NULL,
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

_tables_initialized = False

def ensure_cache_tables(conn):
    """Ensures caching and scheduler tables exist in MySQL database (no hardcoded rows inserted)."""
    global _tables_initialized
    if _tables_initialized or not conn:
        return
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(CACHE_TABLE_SQL)
        cur.execute(SCHEDULER_TABLE_SQL)
        conn.commit()
        _tables_initialized = True
    except Exception as e:
        print(f"[Dashboard Cache] Table init note: {e}", flush=True)
    finally:
        if cur:
            try: cur.close()
            except Exception: pass


def get_cached_component_data(conn, session_id: str, component_key: str, filter_context: str = "all"):
    """
    Retrieves pre-calculated component data from MySQL cache table.
    Returns python dict with data or None.
    """
    if not conn or not component_key:
        return None

    cur = None
    try:
        ensure_cache_tables(conn)
        cur = conn.cursor(dictionary=True) if hasattr(conn, "cursor") else conn.cursor()
        row = None
        if session_id:
            cur.execute("""
                SELECT payload, last_synced_at, sync_status
                FROM dashboard_cached_metrics
                WHERE session_id = %s AND component_key = %s AND filter_context = %s
                LIMIT 1
            """, (str(session_id), str(component_key), str(filter_context)))
            row = cur.fetchone()

        if not row:
            # Fallback: check most recent cached record for this component across sessions
            cur.execute("""
                SELECT payload, last_synced_at, sync_status
                FROM dashboard_cached_metrics
                WHERE component_key = %s AND filter_context = %s
                ORDER BY last_synced_at DESC
                LIMIT 1
            """, (str(component_key), str(filter_context)))
            row = cur.fetchone()

        if row and row.get("payload"):
            payload = json.loads(row["payload"])
            return {
                "data": payload,
                "_cached": True,
                "_last_synced_at": str(row.get("last_synced_at")),
                "_sync_status": row.get("sync_status")
            }
        return None
    except Exception as e:
        print(f"[Dashboard Cache] Error reading cache for {component_key}: {e}", flush=True)
        return None
    finally:
        if cur:
            try: cur.close()
            except Exception: pass


def set_cached_component_data(conn, session_id: str, component_key: str, payload: dict, filter_context: str = "all", duration_sec: float = 0.0):
    """
    Upserts calculated component data into MySQL cache table.
    """
    if not conn or not session_id or not component_key or payload is None:
        return False

    cur = None
    try:
        ensure_cache_tables(conn)
        cur = conn.cursor()
        json_str = json.dumps(payload, ensure_ascii=False)
        cur.execute("""
            INSERT INTO dashboard_cached_metrics
                (session_id, component_key, filter_context, payload, sync_status, execution_duration_sec, last_synced_at)
            VALUES (%s, %s, %s, %s, 'success', %s, NOW())
            ON DUPLICATE KEY UPDATE
                payload = VALUES(payload),
                sync_status = 'success',
                execution_duration_sec = VALUES(execution_duration_sec),
                last_synced_at = NOW();
        """, (str(session_id), str(component_key), str(filter_context), json_str, duration_sec))
        conn.commit()
        return True
    except Exception as e:
        print(f"[Dashboard Cache] Error saving cache for {component_key}: {e}", flush=True)
        return False
    finally:
        if cur:
            try: cur.close()
            except Exception: pass


def get_scheduler_config(conn, job_name: str = "sync_dashboard_metrics"):
    """Fetches configuration for a scheduler job (from DB, configured via UI)."""
    if not conn:
        return None
    cur = None
    try:
        ensure_cache_tables(conn)
        cur = conn.cursor(dictionary=True) if hasattr(conn, "cursor") else conn.cursor()
        cur.execute("SELECT * FROM scheduler_configurations WHERE job_name = %s LIMIT 1", (job_name,))
        row = cur.fetchone()
        return row
    except Exception as e:
        print(f"[Scheduler Service] Error reading config: {e}", flush=True)
        return None
    finally:
        if cur:
            try: cur.close()
            except Exception: pass


def save_or_update_scheduler_config(conn, job_name: str, schedule_time: str, frequency: str = "daily", is_active: bool = True, title: str = None):
    """Saves or updates scheduler configuration directly from UI form."""
    if not conn or not job_name or not schedule_time:
        return False
    cur = None
    try:
        ensure_cache_tables(conn)
        cur = conn.cursor()
        title_val = title or "Dashboard Key Metrics & Analytics Sync"
        cur.execute("""
            INSERT INTO scheduler_configurations
                (job_name, title, schedule_time, frequency, is_active, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                schedule_time = VALUES(schedule_time),
                frequency = VALUES(frequency),
                is_active = VALUES(is_active),
                updated_at = NOW();
        """, (str(job_name).strip(), title_val, str(schedule_time).strip(), str(frequency).strip(), bool(is_active)))
        conn.commit()
        return True
    except Exception as e:
        print(f"[Scheduler Service] Error saving config from UI: {e}", flush=True)
        return False
    finally:
        if cur:
            try: cur.close()
            except Exception: pass


def record_scheduler_run(conn, job_name: str, status: str, duration_sec: float = 0.0, next_run_at=None):
    """Records the execution status and duration of a scheduler job."""
    if not conn:
        return False
    cur = None
    try:
        ensure_cache_tables(conn)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scheduler_configurations
                (job_name, title, schedule_time, frequency, is_active, last_run_at, last_run_status, last_run_duration_sec, next_run_at, updated_at)
            VALUES (%s, 'Dashboard Key Metrics & Analytics Sync', '19:00', 'daily', TRUE, NOW(), %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                last_run_at = NOW(),
                last_run_status = VALUES(last_run_status),
                last_run_duration_sec = VALUES(last_run_duration_sec),
                next_run_at = VALUES(next_run_at),
                updated_at = NOW();
        """, (str(job_name).strip(), str(status), float(duration_sec), next_run_at))
        conn.commit()
        return True
    except Exception as e:
        print(f"[Scheduler Service] Error recording run: {e}", flush=True)
        return False
    finally:
        if cur:
            try: cur.close()
            except Exception: pass
