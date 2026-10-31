import time
import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = None
_app_instance = None
_get_db_conn_func = None
JOB_ID = "sync_dashboard_metrics_job"


def _execute_sync_task():
    """Background task that calculates and caches metrics for all active workspaces."""
    global _app_instance, _get_db_conn_func
    if not _app_instance or not _get_db_conn_func:
        print("[Scheduler] App or DB connection not ready, skipping sync.", flush=True)
        return

    from helper.dashboard_cache_service import record_scheduler_run
    conn = _get_db_conn_func()
    if not conn:
        print("[Scheduler] Failed to connect to DB for sync job.", flush=True)
        return

    start_t = time.time()
    try:
        cur = conn.cursor(dictionary=True) if hasattr(conn, "cursor") else conn.cursor()
        cur.execute("""
            SELECT session_id, MAX(user_id) AS user_id, MAX(name) AS name 
            FROM workspaces 
            WHERE session_id IS NOT NULL AND session_id != ''
            GROUP BY session_id
        """)
        workspaces = cur.fetchall()
        cur.close()

        print(f"[Scheduler] Starting sync for {len(workspaces)} workspaces...", flush=True)

        from controllers.dashboard_visuals import default_dashboard_metrics_controller

        for ws in workspaces:
            s_id = ws.get("session_id")
            u_id = ws.get("user_id")
            ws_name = ws.get("name")
            try:
                with _app_instance.test_request_context(json={"session_id": s_id, "user_id": u_id, "force_refresh": True}):
                    default_dashboard_metrics_controller(_get_db_conn_func)
                print(f"[Scheduler] Synced metrics for workspace '{ws_name}' ({s_id[:8]}...)", flush=True)
            except Exception as ws_err:
                print(f"[Scheduler] Error syncing workspace '{ws_name}': {ws_err}", flush=True)

        duration = round(time.time() - start_t, 2)
        next_run = None
        if _scheduler:
            job = _scheduler.get_job(JOB_ID)
            if job and job.next_run_time:
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")

        record_scheduler_run(conn, "sync_dashboard_metrics", "success", duration, next_run)
        print(f"[Scheduler] Sync completed successfully in {duration}s.", flush=True)

    except Exception as e:
        duration = round(time.time() - start_t, 2)
        print(f"[Scheduler] Sync job failed: {e}", flush=True)
        record_scheduler_run(conn, "sync_dashboard_metrics", "failed", duration)
    finally:
        if conn and hasattr(conn, "is_connected") and conn.is_connected():
            try: conn.close()
            except Exception: pass


def parse_schedule_trigger(schedule_time: str, frequency: str = "daily"):
    """
    Parses schedule_time (e.g. '19:00') and frequency into an APScheduler CronTrigger.
    Default time is 19:00 (7:00 PM evening).
    """
    time_str = (schedule_time or "19:00").strip()
    try:
        parts = time_str.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except Exception:
        hour, minute = 19, 0

    freq = (frequency or "daily").lower().strip()
    if freq in ("twice_daily", "2_times_daily"):
        hour_str = f"{hour},{(hour + 12) % 24}"
        return CronTrigger(hour=hour_str, minute=minute)
    elif freq in ("thrice_daily", "3_times_daily"):
        hour_str = f"{hour},{(hour + 8) % 24},{(hour + 16) % 24}"
        return CronTrigger(hour=hour_str, minute=minute)
    elif freq == "hourly":
        return CronTrigger(minute=minute)
    else:
        return CronTrigger(hour=hour, minute=minute)


def init_scheduler(app, get_db_connection):
    """Initializes and starts the in-app BackgroundScheduler."""
    global _scheduler, _app_instance, _get_db_conn_func
    _app_instance = app
    _get_db_conn_func = get_db_connection

    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True)

    conn = get_db_connection()
    if conn:
        try:
            from helper.dashboard_cache_service import get_scheduler_config
            cfg = get_scheduler_config(conn, "sync_dashboard_metrics")
            if cfg and cfg.get("is_active"):
                trigger = parse_schedule_trigger(cfg.get("schedule_time", "19:00"), cfg.get("frequency", "daily"))
                _scheduler.add_job(
                    _execute_sync_task,
                    trigger=trigger,
                    id=JOB_ID,
                    name="Sync Dashboard Key Metrics",
                    replace_existing=True
                )
                print(f"[Scheduler] Initialized job '{JOB_ID}' at {cfg.get('schedule_time')} ({cfg.get('frequency')})", flush=True)
            else:
                print("[Scheduler] Job is inactive or not yet configured from UI.", flush=True)
        except Exception as e:
            print(f"[Scheduler] Config load note: {e}", flush=True)
        finally:
            if conn and hasattr(conn, "is_connected") and conn.is_connected():
                try: conn.close()
                except Exception: pass

    _scheduler.start()
    return _scheduler


def reschedule_job(schedule_time: str, frequency: str = "daily", is_active: bool = True):
    """Dynamically reschedules the sync job when updated from UI without server restart."""
    global _scheduler
    if not _scheduler:
        return False

    if not is_active:
        if _scheduler.get_job(JOB_ID):
            _scheduler.remove_job(JOB_ID)
            print(f"[Scheduler] Job '{JOB_ID}' paused by user from UI.", flush=True)
        return True

    trigger = parse_schedule_trigger(schedule_time, frequency)
    _scheduler.add_job(
        _execute_sync_task,
        trigger=trigger,
        id=JOB_ID,
        name="Sync Dashboard Key Metrics",
        replace_existing=True
    )
    next_run = _scheduler.get_job(JOB_ID).next_run_time
    print(f"[Scheduler] Rescheduled job '{JOB_ID}' to {schedule_time} ({frequency}). Next run: {next_run}", flush=True)
    return str(next_run) if next_run else None


def trigger_now_in_background():
    """Triggers the sync task immediately in a separate background thread."""
    t = threading.Thread(target=_execute_sync_task, daemon=True)
    t.start()
    return True
