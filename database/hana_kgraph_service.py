"""
hana_kgraph_service.py — Builds a Knowledge Graph for SAP HANA connections
strictly from the already-extracted metadata stored in `sap_hana_view_metadata`.

NO raw data rows are ever read or copied.  The graph is built using only:
  - View / Table names
  - Column names & data types
  - Primary keys
  - Foreign-key / referential relationships
  - Row counts (count metadata, not actual rows)

The resulting graph is stored in ArangoDB (same pipeline as kgraph_builder.py).
"""

import json
import pymysql
from database.config import MYSQL_CONFIG


# ─────────────────────────────────────────────────────────────────────────────
# 1. Load stored metadata from MySQL
# ─────────────────────────────────────────────────────────────────────────────

def _load_hana_metadata(connection_id: int, session_id: str = None, user_id: int = None) -> list:
    """
    Fetch all rows from sap_hana_view_metadata for the given connection.
    Returns a list of dicts with keys:
      view_name, schema_name, view_type, row_count, column_count,
      columns_detail, primary_keys, foreign_keys, relationships
    """
    conn = pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG.get("port", 3306),
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"],
        cursorclass=pymysql.cursors.DictCursor
    )
    try:
        with conn.cursor() as cur:
            query = "SELECT * FROM sap_hana_view_metadata WHERE connection_id = %s"
            params = [connection_id]
            if session_id:
                query += " AND session_id = %s"
                params.append(session_id)
            if user_id:
                query += " AND user_id = %s"
                params.append(user_id)
            query += " ORDER BY schema_name, view_name"
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

        # Parse JSON columns
        for r in rows:
            for col in ["columns_detail", "primary_keys", "foreign_keys", "relationships"]:
                if r.get(col) and isinstance(r[col], str):
                    try:
                        r[col] = json.loads(r[col])
                    except Exception:
                        r[col] = []
                elif not r.get(col):
                    r[col] = []
        return rows
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Convert metadata rows → schema dict (same format kgraph_builder uses)
# ─────────────────────────────────────────────────────────────────────────────

def _metadata_to_schema(metadata_rows: list) -> dict:
    """
    Convert sap_hana_view_metadata rows into the schema dict expected by the
    LLM prompt and the graph builder.

    Output format (mirrors _extract_schema in kgraph_builder.py):
      {
        "VIEW_NAME": {
          "row_count": int,
          "columns": [
            {"name": str, "type": str, "cardinality": None, "values": None,
             "is_primary_key": bool}
          ],
          "primary_keys": [str],
          "foreign_keys": [...],
          "relationships": [...]
        },
        ...
      }
    """
    schema = {}
    for row in metadata_rows:
        view_name = row.get("view_name", "")
        if not view_name:
            continue

        cols_detail = row.get("columns_detail") or []
        primary_keys = row.get("primary_keys") or []
        pk_set = {pk.upper() for pk in primary_keys}

        columns = []
        for c in cols_detail:
            col_name = c.get("name") or c.get("COLUMN_NAME") or ""
            col_type = c.get("data_type") or c.get("DATA_TYPE_NAME") or "NVARCHAR"
            columns.append({
                "name": col_name,
                "type": col_type,
                "cardinality": None,          # metadata only — no actual query
                "values": None,               # no raw data
                "is_primary_key": col_name.upper() in pk_set
            })

        schema[view_name] = {
            "row_count": row.get("row_count", 0),
            "columns": columns,
            "primary_keys": primary_keys,
            "foreign_keys": row.get("foreign_keys") or [],
            "relationships": row.get("relationships") or [],
            "schema_name": row.get("schema_name", ""),
            "view_type": row.get("view_type", "VIEW"),
        }
    return schema


def _schema_for_prompt(schema: dict) -> dict:
    """Compact version of schema for the LLM prompt."""
    out = {}
    for t, meta in schema.items():
        out[t] = {
            "schema": meta.get("schema_name", ""),
            "type": meta.get("view_type", "VIEW"),
            "row_count": meta.get("row_count", 0),
            "primary_keys": meta.get("primary_keys", []),
            "foreign_keys": meta.get("foreign_keys", []),
            "relationships": meta.get("relationships", []),
            "columns": [
                {
                    "name": c["name"],
                    "type": c["type"],
                    "is_primary_key": c.get("is_primary_key", False)
                }
                for c in meta["columns"]
            ],
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 3. Build & store the KGraph in ArangoDB
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(text: str):
    """Parse LLM JSON response, stripping markdown fences."""
    import re
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*", "", s).strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    try:
        return json.loads(s)
    except Exception:
        try:
            from json_repair import repair_json  # type: ignore
            return json.loads(repair_json(s))
        except Exception:
            return None


def _sync_hana_kgraph_to_arango(session_id: str, verified_graph: dict):
    """Push the HANA KGraph into ArangoDB (same collections as kgraph_builder)."""
    from arango import ArangoClient  # type: ignore
    from database.config import ARANGO_HOST, ARANGO_USER, ARANGO_PASS, ARANGO_DB
    import re

    def _safe_key(val: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_:.@()-]", "_", str(val))

    # Resolve target ArangoDB DB for this session
    from database.db_connection import get_db_connection
    conn = get_db_connection()
    target_arango_db = ARANGO_DB
    try:
        with conn.cursor(dictionary=True) as cur:
            cur.execute(
                "SELECT workspace_arango_db FROM workspaces WHERE session_id = %s",
                (session_id,)
            )
            row = cur.fetchone()
            if row and row.get("workspace_arango_db"):
                target_arango_db = row["workspace_arango_db"]
    except Exception as e:
        print(f"[HANA-KGRAPH] Could not resolve arango db for session {session_id}: {e}")
    finally:
        if conn:
            conn.close()

    client = ArangoClient(hosts=ARANGO_HOST)
    sys_db = client.db("_system", username=ARANGO_USER, password=ARANGO_PASS)
    if not sys_db.has_database(target_arango_db):
        sys_db.create_database(target_arango_db)
    db = client.db(target_arango_db, username=ARANGO_USER, password=ARANGO_PASS)

    nodes_col_name = "session_nodes"
    edges_col_name = "session_edges"
    if not db.has_collection(nodes_col_name):
        db.create_collection(nodes_col_name)
    if not db.has_collection(edges_col_name):
        db.create_collection(edges_col_name, edge=True)

    # Backup first
    try:
        from database.kgraph_backup_service import backup_kgraph_collections  # type: ignore
        backup_kgraph_collections(db, nodes_col_name, edges_col_name)
    except Exception as e:
        print(f"[HANA-KGRAPH] Backup step skipped: {e}")

    nodes_col = db.collection(nodes_col_name)
    edges_col = db.collection(edges_col_name)

    # Upsert nodes
    for n in verified_graph.get("nodes", []):
        node_id = str(n.get("id") or n.get("table_name") or n.get("name") or "unknown")
        if node_id == "unknown":
            continue
        key = _safe_key(node_id)
        doc = {
            "_key": key,
            "session_id": session_id,
            "label": n.get("label", node_id),
            "original_id": node_id,
            "type": n.get("type", "SAPHanaView")
        }
        try:
            if nodes_col.has(key):
                nodes_col.update(doc)
            else:
                nodes_col.insert(doc)
        except Exception:
            pass

    # Upsert edges (from FK relationships in metadata)
    for e in verified_graph.get("edges", []):
        from_node = e.get("from_table") or e.get("from")
        to_node = e.get("to_table") or e.get("to")
        if not from_node or not to_node:
            continue
        from_key = _safe_key(from_node)
        to_key = _safe_key(to_node)
        edge_key = _safe_key(f"{from_key}_to_{to_key}")
        doc = {
            "_key": edge_key,
            "_from": f"{nodes_col_name}/{from_key}",
            "_to": f"{nodes_col_name}/{to_key}",
            "session_id": session_id,
            "label": e.get("relationship", e.get("label", "RELATES_TO")),
            "title": f"Join {e.get('from_column', '')} → {e.get('to_column', '')}"
        }
        try:
            if edges_col.has(edge_key):
                edges_col.update(doc)
            else:
                edges_col.insert(doc)
        except Exception:
            pass

    print(f"[HANA-KGRAPH] ArangoDB sync completed for session {session_id}.")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def build_hana_kgraph_from_metadata(
    connection_id: int,
    session_id: str,
    user_id: int = None
) -> dict:
    """
    Main entry point.  Call this AFTER discover_hana_metadata() has stored the
    metadata in sap_hana_view_metadata.

    Steps:
      1. Load metadata from MySQL (no HANA connection needed).
      2. Format as schema JSON.
      3. Ask LLM to propose KGraph (nodes, edges, hierarchies, synonyms, metrics).
      4. Build edges from FK relationships stored in metadata.
      5. Sync verified graph to ArangoDB.

    Returns a summary dict.
    """
    import time
    t0 = time.time()

    # ── Step 1: load metadata ──────────────────────────────────────────────
    metadata_rows = _load_hana_metadata(connection_id, session_id, user_id)
    if not metadata_rows:
        print(f"[HANA-KGRAPH] No metadata found for connection_id={connection_id}. "
              "Run discover_hana_metadata first.")
        return {"status": "empty", "tables": 0}

    schema = _metadata_to_schema(metadata_rows)
    print(f"[HANA-KGRAPH] Loaded metadata for {len(schema)} views/tables.")

    # ── Step 2: call LLM ──────────────────────────────────────────────────
    from database.prompt_loader import get_prompt  # type: ignore
    from model.llm_client import call_llm_chat  # type: ignore

    prompt_template = get_prompt(0, "knowledge_graph")
    if not prompt_template or not prompt_template.strip():
        prompt_template = (
            "You are a data architect. Return a STRICT JSON knowledge graph with keys "
            "fact_tables, nodes, edges, hierarchies, synonyms, metrics.\n"
            "Use ONLY the SAP HANA view metadata below (no raw data rows are available).\n"
            "Build edges using the foreign_keys and relationships provided.\n"
            "Schema:\n{SCHEMA_JSON}"
        )

    prompt = prompt_template.replace(
        "{SCHEMA_JSON}",
        json.dumps(_schema_for_prompt(schema), indent=2, default=str)
    )

    raw = call_llm_chat(
        [{"role": "user", "content": prompt}],
        json_mode=True,
        temperature=0.0
    )
    graph = _parse_json(raw) or {}
    print(
        f"[HANA-KGRAPH] LLM proposed: "
        f"{len(graph.get('nodes', []))} nodes, "
        f"{len(graph.get('edges', []))} edges, "
        f"{len(graph.get('hierarchies', []))} hierarchies"
    )

    # ── Step 3: enrich edges from FK relationships in stored metadata ──────
    # Add edges from the FK relationships that were already discovered
    existing_edge_keys = set()
    for e in graph.get("edges", []):
        ft = e.get("from_table", "")
        tt = e.get("to_table", "")
        if ft and tt:
            existing_edge_keys.add(f"{ft}→{tt}")

    for view_name, meta in schema.items():
        for rel in meta.get("relationships", []):
            ft = rel.get("from_table", view_name)
            tt = rel.get("to_table", "")
            if not tt:
                continue
            key = f"{ft}→{tt}"
            if key not in existing_edge_keys:
                graph.setdefault("edges", []).append({
                    "from_table": ft,
                    "from_column": rel.get("from_column", ""),
                    "to_table": tt,
                    "to_column": rel.get("to_column", ""),
                    "relationship": "FK",
                    "note": "derived from SAP HANA referential constraint"
                })
                existing_edge_keys.add(key)

    verified_graph = {
        "fact_tables": graph.get("fact_tables", []),
        "nodes":       graph.get("nodes", []),
        "edges":       graph.get("edges", []),
        "hierarchies": graph.get("hierarchies", []),
        "synonyms":    graph.get("synonyms", []),
        "metrics":     graph.get("metrics", []),
    }

    # ── Step 4: sync to ArangoDB ──────────────────────────────────────────
    try:
        _sync_hana_kgraph_to_arango(session_id, verified_graph)
    except Exception as e:
        print(f"[HANA-KGRAPH] ArangoDB sync failed: {e}")

    elapsed = round(time.time() - t0, 1)
    print(
        f"[HANA-KGRAPH] Built in {elapsed}s — "
        f"{len(schema)} views, {len(verified_graph['edges'])} edges"
    )

    return {
        "status": "ok",
        "tables": len(schema),
        "edges": len(verified_graph["edges"]),
        "hierarchies": len(verified_graph["hierarchies"]),
        "synonyms": len(verified_graph["synonyms"]),
        "metrics": len(verified_graph["metrics"]),
        "elapsed_s": elapsed,
        "graph": verified_graph
    }
