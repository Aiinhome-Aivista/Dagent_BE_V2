from flask import request, jsonify
import traceback
import re
from datetime import datetime
from arango import ArangoClient
from database.config import ARANGO_HOST, ARANGO_USER, ARANGO_PASS, ARANGO_DB

METADATA_COLLECTION = "kgraph_backups_metadata"


def _resolve_workspace_arango_db(get_db_connection, session_id=None, workspace_id=None, explicit_arango_db=None):
    """
    Resolves the workspace ArangoDB name from explicit param, session_id, workspace_id,
    or falls back to the latest active workspace / default ARANGO_DB.
    """
    if explicit_arango_db and explicit_arango_db.strip():
        return explicit_arango_db.strip()

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(dictionary=True) as cur:
            if session_id:
                cur.execute("SELECT workspace_arango_db FROM workspaces WHERE session_id = %s", (session_id,))
                row = cur.fetchone()
                if row and row.get("workspace_arango_db"):
                    return row["workspace_arango_db"]

            if workspace_id:
                cur.execute("SELECT workspace_arango_db FROM workspaces WHERE id = %s", (workspace_id,))
                row = cur.fetchone()
                if row and row.get("workspace_arango_db"):
                    return row["workspace_arango_db"]

            # Fallback to the most recently created workspace
            cur.execute("SELECT workspace_arango_db FROM workspaces WHERE workspace_arango_db IS NOT NULL ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if row and row.get("workspace_arango_db"):
                return row["workspace_arango_db"]
    except Exception as e:
        print(f"[KGraph] Warning resolving workspace_arango_db: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return ARANGO_DB


def _get_arango_db_handle(db_name: str):
    """
    Returns an ArangoDB database handle and an error message (if any).
    """
    try:
        client = ArangoClient(hosts=ARANGO_HOST)
        sys_db = client.db('_system', username=ARANGO_USER, password=ARANGO_PASS)
        target_db = db_name if db_name else ARANGO_DB

        if not sys_db.has_database(target_db):
            return None, f"ArangoDB database '{target_db}' does not exist."

        db = client.db(target_db, username=ARANGO_USER, password=ARANGO_PASS)
        return db, None
    except Exception as e:
        return None, f"Failed connecting to ArangoDB: {str(e)}"


def _ensure_metadata_collection(db):
    """Ensures that the kgraph_backups_metadata collection exists."""
    if not db.has_collection(METADATA_COLLECTION):
        try:
            db.create_collection(METADATA_COLLECTION, edge=False)
        except Exception:
            pass


def _backup_name_exists(db, name: str) -> bool:
    """Checks whether a backup name already exists in metadata or as a collection."""
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    node_col = f"session_nodes_backup_{safe_name}"
    if db.has_collection(node_col):
        return True

    if db.has_collection(METADATA_COLLECTION):
        try:
            query = f"FOR doc IN `{METADATA_COLLECTION}` FILTER doc.backup_name == @bname RETURN 1"
            res = list(db.aql.execute(query, bind_vars={"bname": name}))
            if res:
                return True
        except Exception:
            pass

    return False


def _generate_unique_backup_name(db, custom_name: str = None) -> str:
    """
    Generates a unique backup name following user requirement:
    Format: 'kg-{ddmmyy}-OK', or 'kg-{ddmmyy}-OK-1', etc.
    """
    if custom_name and custom_name.strip():
        base = custom_name.strip()
    else:
        today_code = datetime.now().strftime("%d%m%y")
        base = f"kg-{today_code}-OK"

    candidate = base
    counter = 1
    while _backup_name_exists(db, candidate):
        candidate = f"{base}-{counter}"
        counter += 1

    return candidate


def create_kgraph_backup_controller(get_db_connection):
    """
    Creates an explicit snapshot backup of the live knowledge graph (nodes + edges).
    Naming convention: 'kg-DDMMYY-OK' (e.g. kg-301026-OK).
    """
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id") or request.args.get("session_id")
        workspace_id = data.get("workspace_id") or request.args.get("workspace_id")
        explicit_arango_db = data.get("workspace_arango_db") or request.args.get("workspace_arango_db")
        custom_name = data.get("backup_name")
        description = data.get("description", "")

        db_name = _resolve_workspace_arango_db(get_db_connection, session_id, workspace_id, explicit_arango_db)
        db, err = _get_arango_db_handle(db_name)
        if err:
            return jsonify({"status": "error", "message": err}), 404

        _ensure_metadata_collection(db)

        nodes_col_name = "session_nodes"
        edges_col_name = "session_edges"

        if not db.has_collection(nodes_col_name):
            db.create_collection(nodes_col_name, edge=False)
        if not db.has_collection(edges_col_name):
            db.create_collection(edges_col_name, edge=True)

        cur_nodes = next(db.aql.execute(f"RETURN LENGTH(`{nodes_col_name}`)"), 0) or 0
        cur_edges = next(db.aql.execute(f"RETURN LENGTH(`{edges_col_name}`)"), 0) or 0

        # Generate unique backup name like kg-301026-OK
        backup_name = _generate_unique_backup_name(db, custom_name)
        safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', backup_name)

        nodes_backup_col = f"session_nodes_backup_{safe_name}"
        edges_backup_col = f"session_edges_backup_{safe_name}"

        # Clean any preexisting collection with this exact name
        if db.has_collection(nodes_backup_col):
            db.delete_collection(nodes_backup_col)
        if db.has_collection(edges_backup_col):
            db.delete_collection(edges_backup_col)

        db.create_collection(nodes_backup_col, edge=False)
        db.create_collection(edges_backup_col, edge=True)

        # Atomic copy via AQL using backticks
        if cur_nodes > 0:
            db.aql.execute(f"FOR doc IN `{nodes_col_name}` INSERT doc INTO `{nodes_backup_col}`")
        if cur_edges > 0:
            db.aql.execute(f"FOR doc IN `{edges_col_name}` INSERT doc INTO `{edges_backup_col}`")

        # Record metadata
        created_at_iso = datetime.now().isoformat()
        created_date_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")

        backup_meta = {
            "_key": safe_name,
            "backup_name": backup_name,
            "nodes_collection": nodes_backup_col,
            "edges_collection": edges_backup_col,
            "nodes_count": cur_nodes,
            "edges_count": cur_edges,
            "created_at": created_at_iso,
            "created_date": created_date_str,
            "workspace_arango_db": db_name,
            "session_id": session_id or "",
            "workspace_id": workspace_id or "",
            "description": description or f"K-Graph backup created on {created_date_str}"
        }

        meta_col = db.collection(METADATA_COLLECTION)
        meta_col.insert(backup_meta, overwrite=True)

        return jsonify({
            "status": "success",
            "message": f"K-Graph backup '{backup_name}' created successfully.",
            "backup": backup_meta
        }), 201

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def list_kgraph_backups_controller(get_db_connection):
    """
    Lists all available K-Graph backups for the target workspace ArangoDB.
    Combines records from kgraph_backups_metadata and scans for legacy backup collections.
    """
    try:
        session_id = request.args.get("session_id")
        workspace_id = request.args.get("workspace_id")
        explicit_arango_db = request.args.get("workspace_arango_db")

        if not session_id and not workspace_id and not explicit_arango_db:
            body = request.get_json(silent=True) or {}
            session_id = body.get("session_id")
            workspace_id = body.get("workspace_id")
            explicit_arango_db = body.get("workspace_arango_db")

        db_name = _resolve_workspace_arango_db(get_db_connection, session_id, workspace_id, explicit_arango_db)
        db, err = _get_arango_db_handle(db_name)
        if err:
            return jsonify({"status": "error", "message": err}), 404

        _ensure_metadata_collection(db)

        backups = []
        recorded_node_cols = set()

        # 1. Fetch from metadata collection
        if db.has_collection(METADATA_COLLECTION):
            cursor = db.aql.execute(f"FOR doc IN `{METADATA_COLLECTION}` SORT doc.created_at DESC RETURN doc")
            for doc in cursor:
                # Verify that backing collections still exist
                if db.has_collection(doc.get("nodes_collection", "")):
                    backups.append(doc)
                    recorded_node_cols.add(doc.get("nodes_collection"))

        # 2. Also discover any legacy backup collections not recorded in metadata
        all_colls = db.collections()
        for c in all_colls:
            cname = c["name"]
            if "_backup_" in cname and cname.startswith("session_nodes") and cname not in recorded_node_cols and not cname.startswith("_"):
                edge_col_candidate = cname.replace("session_nodes_", "session_edges_")
                try:
                    n_count = next(db.aql.execute(f"RETURN LENGTH(`{cname}`)"), 0) or 0
                except Exception:
                    n_count = 0
                try:
                    e_count = next(db.aql.execute(f"RETURN LENGTH(`{edge_col_candidate}`)"), 0) or 0 if db.has_collection(edge_col_candidate) else 0
                except Exception:
                    e_count = 0

                display_name = cname.replace("session_nodes_backup_", "kg-")
                backups.append({
                    "_key": cname,
                    "backup_name": display_name,
                    "nodes_collection": cname,
                    "edges_collection": edge_col_candidate if db.has_collection(edge_col_candidate) else "",
                    "nodes_count": n_count,
                    "edges_count": e_count,
                    "created_at": "",
                    "created_date": "Legacy Backup",
                    "workspace_arango_db": db_name,
                    "description": "Historical backup collection"
                })

        return jsonify({
            "status": "success",
            "count": len(backups),
            "workspace_arango_db": db_name,
            "backups": backups
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def restore_kgraph_backup_controller(get_db_connection):
    """
    Restores live session_nodes and session_edges from a designated backup snapshot.
    """
    try:
        data = request.get_json(silent=True) or {}
        backup_name = data.get("backup_name")
        backup_key = data.get("_key") or data.get("key")
        nodes_collection = data.get("nodes_collection")
        session_id = data.get("session_id") or request.args.get("session_id")
        workspace_id = data.get("workspace_id") or request.args.get("workspace_id")
        explicit_arango_db = data.get("workspace_arango_db") or request.args.get("workspace_arango_db")

        if not backup_name and not backup_key and not nodes_collection:
            return jsonify({"status": "error", "message": "backup_name or nodes_collection is required"}), 400

        db_name = _resolve_workspace_arango_db(get_db_connection, session_id, workspace_id, explicit_arango_db)
        db, err = _get_arango_db_handle(db_name)
        if err:
            return jsonify({"status": "error", "message": err}), 404

        _ensure_metadata_collection(db)

        # Resolve backup collections
        nodes_backup_col = None
        edges_backup_col = None
        actual_backup_name = backup_name or backup_key

        # 1. Search in metadata collection
        if db.has_collection(METADATA_COLLECTION):
            query = f"""
            FOR doc IN `{METADATA_COLLECTION}`
            FILTER doc.backup_name == @target OR doc._key == @target OR doc.nodes_collection == @target
            LIMIT 1
            RETURN doc
            """
            search_val = backup_name or backup_key or nodes_collection
            results = list(db.aql.execute(query, bind_vars={"target": search_val}))
            if results:
                meta = results[0]
                nodes_backup_col = meta.get("nodes_collection")
                edges_backup_col = meta.get("edges_collection")
                actual_backup_name = meta.get("backup_name", actual_backup_name)

        # 2. If not found in metadata, derive collection names directly
        if not nodes_backup_col:
            if nodes_collection and db.has_collection(nodes_collection):
                nodes_backup_col = nodes_collection
                edges_backup_col = nodes_collection.replace("session_nodes_", "session_edges_")
            elif backup_name:
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', backup_name)
                cand_node = f"session_nodes_backup_{safe_name}"
                cand_edge = f"session_edges_backup_{safe_name}"
                if db.has_collection(cand_node):
                    nodes_backup_col = cand_node
                    edges_backup_col = cand_edge

        if not nodes_backup_col or not db.has_collection(nodes_backup_col):
            return jsonify({
                "status": "error",
                "message": f"Backup collection '{nodes_backup_col or backup_name}' not found in database '{db_name}'."
            }), 404

        # Ensure active collections exist
        nodes_col_name = "session_nodes"
        edges_col_name = "session_edges"

        if not db.has_collection(nodes_col_name):
            db.create_collection(nodes_col_name, edge=False)
        if not db.has_collection(edges_col_name):
            db.create_collection(edges_col_name, edge=True)

        nodes_col = db.collection(nodes_col_name)
        edges_col = db.collection(edges_col_name)

        # Truncate active collections before restoration
        nodes_col.truncate()
        edges_col.truncate()

        # Atomic copy from backup into active collections via AQL
        db.aql.execute(f"FOR doc IN `{nodes_backup_col}` INSERT UNSET(doc, '_id', '_rev') INTO `{nodes_col_name}`")
        if edges_backup_col and db.has_collection(edges_backup_col):
            db.aql.execute(f"FOR doc IN `{edges_backup_col}` INSERT UNSET(doc, '_id', '_rev') INTO `{edges_col_name}`")

        restored_nodes = next(db.aql.execute(f"RETURN LENGTH(`{nodes_col_name}`)"), 0) or 0
        restored_edges = next(db.aql.execute(f"RETURN LENGTH(`{edges_col_name}`)"), 0) or 0

        return jsonify({
            "status": "success",
            "message": f"Successfully restored K-Graph from backup '{actual_backup_name}'.",
            "backup_name": actual_backup_name,
            "workspace_arango_db": db_name,
            "restored_nodes": restored_nodes,
            "restored_edges": restored_edges
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def delete_kgraph_backup_controller(get_db_connection):
    """
    Deletes a K-Graph backup and its corresponding collections in ArangoDB.
    """
    try:
        data = request.get_json(silent=True) or {}
        backup_name = data.get("backup_name") or request.args.get("backup_name")
        backup_key = data.get("_key") or request.args.get("_key")
        nodes_collection = data.get("nodes_collection") or request.args.get("nodes_collection")
        session_id = data.get("session_id") or request.args.get("session_id")
        workspace_id = data.get("workspace_id") or request.args.get("workspace_id")
        explicit_arango_db = data.get("workspace_arango_db") or request.args.get("workspace_arango_db")

        if not backup_name and not backup_key and not nodes_collection:
            return jsonify({"status": "error", "message": "backup_name, _key, or nodes_collection is required"}), 400

        db_name = _resolve_workspace_arango_db(get_db_connection, session_id, workspace_id, explicit_arango_db)
        db, err = _get_arango_db_handle(db_name)
        if err:
            return jsonify({"status": "error", "message": err}), 404

        _ensure_metadata_collection(db)

        # Resolve collection names
        nodes_col = None
        edges_col = None
        doc_key = None

        if db.has_collection(METADATA_COLLECTION):
            search_val = backup_name or backup_key or nodes_collection
            query = f"""
            FOR doc IN `{METADATA_COLLECTION}`
            FILTER doc.backup_name == @target OR doc._key == @target OR doc.nodes_collection == @target
            LIMIT 1
            RETURN doc
            """
            results = list(db.aql.execute(query, bind_vars={"target": search_val}))
            if results:
                meta = results[0]
                nodes_col = meta.get("nodes_collection")
                edges_col = meta.get("edges_collection")
                doc_key = meta.get("_key")

        if not nodes_col:
            if nodes_collection:
                nodes_col = nodes_collection
                edges_col = nodes_collection.replace("session_nodes_", "session_edges_")
            elif backup_name:
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', backup_name)
                nodes_col = f"session_nodes_backup_{safe_name}"
                edges_col = f"session_edges_backup_{safe_name}"

        # Drop the collections
        deleted_cols = []
        if nodes_col and db.has_collection(nodes_col):
            db.delete_collection(nodes_col)
            deleted_cols.append(nodes_col)
        if edges_col and db.has_collection(edges_col):
            db.delete_collection(edges_col)
            deleted_cols.append(edges_col)

        # Remove from metadata collection
        if doc_key and db.has_collection(METADATA_COLLECTION):
            try:
                db.collection(METADATA_COLLECTION).delete(doc_key)
            except Exception:
                pass

        return jsonify({
            "status": "success",
            "message": f"Backup '{backup_name or nodes_col}' deleted successfully.",
            "deleted_collections": deleted_cols
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def _list_backup_timestamps(db, nodes_col_name: str = "session_nodes", edges_col_name: str = "session_edges") -> list:
    """Returns a sorted list of timestamps (descending) of available backups."""
    known_prefixes = (nodes_col_name, edges_col_name)
    all_colls = db.collections()
    old_backups = [
        c["name"] for c in all_colls
        if "_backup_" in c["name"]
        and not c["name"].startswith("_")
        and any(c["name"].startswith(p) for p in known_prefixes)
    ]
    timestamps = set()
    for coll in old_backups:
        parts = coll.split("_backup_")
        if len(parts) > 1:
            ts_part = parts[1].split("_nodes_")[0]
            timestamps.add(ts_part)
    return sorted(list(timestamps), reverse=True)


def _get_backup_collection_names(db, target_timestamp: str, nodes_col_name: str = "session_nodes", edges_col_name: str = "session_edges"):
    """Returns the exact node and edge backup collection names for a given timestamp."""
    all_colls = db.collections()
    node_bkp = None
    edge_bkp = None
    for c in all_colls:
        name = c["name"]
        if "_backup_" in name and target_timestamp in name:
            if name.startswith(nodes_col_name):
                node_bkp = name
            elif name.startswith(edges_col_name):
                edge_bkp = name
    return node_bkp, edge_bkp


def rollback_kgraph_controller(get_db_connection):
    """
    Backwards-compatible rollback controller supporting timestamp and backup_name.
    """
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")
        workspace_id = data.get("workspace_id")
        target_timestamp = data.get("backup_timestamp") or data.get("backup_name")

        db_name = _resolve_workspace_arango_db(get_db_connection, session_id, workspace_id)
        db, err = _get_arango_db_handle(db_name)
        if err:
            return jsonify({"status": "error", "message": err}), 404

        nodes_col_name = "session_nodes"
        edges_col_name = "session_edges"

        if not target_timestamp:
            timestamps = _list_backup_timestamps(db)
            if not timestamps:
                return jsonify({"status": "error", "message": "No backups found to roll back to."}), 404
            target_timestamp = timestamps[0]

        nodes_backup, edges_backup = _get_backup_collection_names(db, target_timestamp)

        # Fallback to search in metadata or direct safe name
        if not nodes_backup or not db.has_collection(nodes_backup):
            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', target_timestamp)
            cand_node = f"session_nodes_backup_{safe_name}"
            cand_edge = f"session_edges_backup_{safe_name}"
            if db.has_collection(cand_node):
                nodes_backup = cand_node
                edges_backup = cand_edge

        if not nodes_backup or not db.has_collection(nodes_backup):
            return jsonify({"status": "error", "message": f"Backup collections for '{target_timestamp}' do not exist."}), 404

        if not db.has_collection(nodes_col_name):
            db.create_collection(nodes_col_name)
        if not db.has_collection(edges_col_name):
            db.create_collection(edges_col_name, edge=True)

        nodes_col = db.collection(nodes_col_name)
        edges_col = db.collection(edges_col_name)

        # Truncate active collections
        nodes_col.truncate()
        edges_col.truncate()

        # Atomic AQL copy using backticks
        db.aql.execute(f"FOR doc IN `{nodes_backup}` INSERT UNSET(doc, '_id', '_rev') INTO `{nodes_col_name}`")
        if edges_backup and db.has_collection(edges_backup):
            db.aql.execute(f"FOR doc IN `{edges_backup}` INSERT UNSET(doc, '_id', '_rev') INTO `{edges_col_name}`")

        return jsonify({
            "status": "success", 
            "message": f"Successfully rolled back to K-Graph backup '{target_timestamp}'",
            "timestamp": target_timestamp
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def get_all_kgraphs_controller(get_db_connection):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute("SELECT id, session_name, graph_url FROM graph ORDER BY id DESC")
            graphs = cursor.fetchall()
            return jsonify({"status": "success", "graphs": graphs}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


def get_kgraph_ontology_analysis_controller(get_db_connection):
    """
    Returns the Golden Sales Ontology comparison and AI missing node analysis
    for the given session/workspace.
    """
    try:
        body = request.get_json(silent=True) or {}
        session_id = request.args.get("session_id") or body.get("session_id")
        if not session_id:
            return jsonify({"status": "error", "message": "session_id is required"}), 400

        conn = get_db_connection()
        workspace_arango_db = None
        workspace_db = None
        try:
            with conn.cursor(dictionary=True) as cur:
                cur.execute("SELECT workspace_db, workspace_arango_db FROM workspaces WHERE session_id = %s", (session_id,))
                row = cur.fetchone()
                if row:
                    workspace_db = row["workspace_db"]
                    workspace_arango_db = row["workspace_arango_db"]
        finally:
            if conn:
                conn.close()

        # 1. Retrieve persisted analysis from ArangoDB session_metadata
        if workspace_arango_db:
            try:
                from arango import ArangoClient
                from database.config import ARANGO_HOST, ARANGO_USER, ARANGO_PASS
                client = ArangoClient(hosts=ARANGO_HOST)
                db = client.db(workspace_arango_db, username=ARANGO_USER, password=ARANGO_PASS)
                if db.has_collection("session_metadata"):
                    meta_col = db.collection("session_metadata")
                    if meta_col.has("ontology_analysis"):
                        doc = meta_col.get("ontology_analysis")
                        return jsonify({"status": "success", "data": doc.get("data")}), 200
            except Exception as arango_err:
                print(f"[KGRAPH] Could not fetch cached ontology analysis from Arango: {arango_err}")

        # 2. If not ready/cached yet, return a pending status instead of generating a false 0% report
        return jsonify({
            "status": "pending",
            "message": "Ontology analysis is pending or data has not been synced yet for this workspace."
        }), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500
