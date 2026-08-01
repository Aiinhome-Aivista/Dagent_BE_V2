# controllers/session_sources_controller.py
#
# GET /session-sources?session_id=xxx
#
# Returns unique topics from saved_web_results
# and unique external_database names from external_db_sync_log
# for a given session_id — as structured JSON

import re
from flask import request, jsonify


def session_sources_controller(get_connection_func):
    session_id = (request.args.get("session_id") or "").strip()
    if not session_id:
        return jsonify({
            "status": "failed", "statusCode": 400,
            "message": "Query param 'session_id' is required."
        }), 400

    conn = cursor = None
    try:
        conn   = get_connection_func()
        cursor = conn.cursor(dictionary=True)

        # ── Web topics ──────────────────────────────────────────
        cursor.execute("""
            SELECT
                topic,
                COUNT(*)        AS result_count,
                MIN(saved_at)   AS first_saved,
                MAX(saved_at)   AS last_saved
            FROM saved_web_results
            WHERE session_id = %s
              AND topic IS NOT NULL
              AND topic != ''
            GROUP BY topic
            ORDER BY result_count DESC
        """, (session_id,))
        topic_rows = cursor.fetchall()

        web_topics = [
            {
                "topic":        r["topic"],
                "result_count": r["result_count"],
                "first_saved":  str(r["first_saved"]) if r["first_saved"] else None,
                "last_saved":   str(r["last_saved"])  if r["last_saved"]  else None,
            }
            for r in topic_rows
        ]

        # ── External databases ───────────────────────────────────
        cursor.execute("""
            SELECT
                external_database,
                new_user_db,
                COUNT(DISTINCT table_name) AS table_count,
                GROUP_CONCAT(DISTINCT table_name ORDER BY table_name SEPARATOR ', ')
                                           AS tables,
                MAX(sync_time)             AS last_sync,
                SUM(total_rows)            AS total_rows,
                SUM(total_columns)         AS total_columns,
                SUM(data_size_mb)          AS data_size_mb
            FROM external_db_sync_log
            WHERE session_id = %s
              AND external_database IS NOT NULL
              AND external_database != ''
            GROUP BY external_database, new_user_db
            ORDER BY external_database
        """, (session_id,))
        db_rows = cursor.fetchall()

        # Deduplicate by tables so multiple files writing to the same table only show the latest
        unique_dbs = {}
        for r in db_rows:
            t_key = r["tables"]
            # Keep the latest sync
            if t_key not in unique_dbs or r["last_sync"] > unique_dbs[t_key]["last_sync"]:
                unique_dbs[t_key] = r
                
        db_rows_deduped = list(unique_dbs.values())

        external_dbs = [
            {
                "external_database": r["external_database"],
                "new_user_db":       r["new_user_db"],
                "table_count":       r["table_count"],
                "tables":            r["tables"].split(", ") if r["tables"] else [],
                "last_sync":         str(r["last_sync"]) if r["last_sync"] else None,
                "summary": {
                    "total_rows": int(r["total_rows"] or 0),
                    "total_columns": int(r["total_columns"] or 0),
                    "data_size_mb": float(r["data_size_mb"] or 0.0)
                }
            }
            for r in db_rows_deduped
        ]
        simple_topics = [r["topic"] for r in topic_rows]
        simple_databases = [r["external_database"] for r in db_rows_deduped]

        return jsonify({
            "status":       "success",
            "statusCode":   200,
            "session_id":   session_id,
                # new simple format
            "topics": simple_topics,
            "databases": simple_databases,
            "web_topics": {
                "total_unique_topics": len(web_topics),
                "topics": web_topics
            },
            "external_databases": {
                "total_unique_databases": len(external_dbs),
                "databases": external_dbs
            }
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error", "statusCode": 500,
            "message": str(e)
        }), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()