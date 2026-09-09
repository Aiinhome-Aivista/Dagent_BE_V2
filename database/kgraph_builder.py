"""
kgraph_builder.py — builds and persists the schema Knowledge Graph for a database.

Runs ONCE at data-sync time (right after csv_processor.process_csv_job /
sql_processor.process_sql_job finish). It:

  1. Extracts the real schema from the user's allocated MySQL DB
     (SHOW TABLES, DESCRIBE, row counts, per-column distinct counts, and sample
     distinct values for low-cardinality columns).
  2. Asks the LLM (kgraph_build_prompt.txt) to PROPOSE a knowledge graph:
     fact/dimension nodes, join edges, hierarchies, synonyms, metric formulas.
  3. VERIFIES every proposed edge and hierarchy with cheap SQL — this turns LLM
     guesses into facts and is what prevents fan-out joins (e.g. joining a product
     attribute on the customer key) and false hierarchies.
  4. Stores the result in kgraph_* tables INSIDE the same allocated DB, with a
     schema_hash so it is rebuilt only when the schema changes.

Wire-in (database/external_sync_service.py, right after the sync job succeeds):

    from database.kgraph_builder import build_kgraph
    build_kgraph(allocated_db_name=new_user_db,
                 db_host=db_host, db_user=db_user,
                 db_pass=db_pass, db_port=db_port)

Idempotent and safe to call repeatedly; if the schema hash is unchanged it returns
early without calling the LLM.
"""

import os
import re
import json
import time
import hashlib

import pymysql

try:
    # pyrefly: ignore [missing-import]
    from json_repair import repair_json
except Exception:                       # pragma: no cover
    repair_json = None

from model.llm_client import call_llm_chat

# ─────────────────────────────────────────────────────────────────────────────
# Tunables
# ─────────────────────────────────────────────────────────────────────────────
LOW_CARD_MAX      = 60        # columns with <= this many distinct values are "dimensional"
SAMPLE_VALUES_MAX = 50        # distinct values stored per low-cardinality column
VERIFY_ROW_CAP    = 500_000   # skip COUNT(DISTINCT) verification above this many rows

from database.db_connection import get_db_connection


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _bt(name: str) -> str:
    """Backtick-quote an identifier safely."""
    return "`" + str(name).replace("`", "``") + "`"


def _connect(db, host, user, pwd, port):
    return pymysql.connect(host=host, port=int(port), user=user, password=pwd,
                           database=db, cursorclass=pymysql.cursors.DictCursor,
                           connect_timeout=15)





def _parse_json(text):
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
        if repair_json:
            try:
                return json.loads(repair_json(s))
            except Exception:
                return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema extraction
# ─────────────────────────────────────────────────────────────────────────────
def _extract_schema(cur):
    """Return {table: {row_count, columns:[{name,type,cardinality,values?}]}}."""
    cur.execute("SHOW TABLES")
    rows = cur.fetchall()
    tables = [list(r.values())[0] for r in rows]
    # Never describe our own metadata tables.
    tables = [t for t in tables if not str(t).lower().startswith("kgraph_")]

    schema = {}
    for t in tables:
        if not re.match(r"^[\w]+$", t):
            continue
        try:
            cur.execute(f"DESCRIBE {_bt(t)}")
            desc = cur.fetchall()
            cur.execute(f"SELECT COUNT(*) AS n FROM {_bt(t)}")
            row_count = int(cur.fetchone()["n"])

            cols = []
            for d in desc:
                col = d.get("Field")
                dtype = d.get("Type")
                card = None
                values = None
                if row_count <= VERIFY_ROW_CAP:
                    try:
                        cur.execute(
                            f"SELECT COUNT(DISTINCT {_bt(col)}) AS c FROM {_bt(t)}")
                        card = int(cur.fetchone()["c"])
                    except Exception:
                        card = None
                # Sample distinct values for low-cardinality non-numeric columns.
                is_text = bool(re.search(r"char|text|enum|set", str(dtype), re.I))
                if is_text and card is not None and 0 < card <= LOW_CARD_MAX:
                    try:
                        cur.execute(
                            f"SELECT DISTINCT {_bt(col)} AS v FROM {_bt(t)} "
                            f"WHERE {_bt(col)} IS NOT NULL LIMIT {SAMPLE_VALUES_MAX}")
                        values = [str(r["v"]) for r in cur.fetchall()
                                  if r["v"] is not None and str(r["v"]).strip()]
                    except Exception:
                        values = None
                cols.append({"name": col, "type": str(dtype),
                             "cardinality": card, "values": values})
            schema[t] = {"row_count": row_count, "columns": cols}
        except Exception as e:
            print(f"[KGRAPH] describe {t} failed: {e}")
    return schema


def _schema_hash(schema):
    sig = []
    for t in sorted(schema):
        cols = ",".join(f"{c['name']}:{c['type']}" for c in schema[t]["columns"])
        sig.append(f"{t}|{cols}")
    return hashlib.md5("\n".join(sig).encode()).hexdigest()


def _schema_for_prompt(schema):
    """Compact schema the LLM can reason over (drops big value lists)."""
    out = {}
    for t, meta in schema.items():
        out[t] = {
            "row_count": meta["row_count"],
            "columns": [
                {"name": c["name"], "type": c["type"], "distinct": c["cardinality"],
                 **({"sample_values": c["values"][:15]} if c["values"] else {})}
                for c in meta["columns"]
            ],
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 2. Verification (SQL-confirm the LLM's proposals)
# ─────────────────────────────────────────────────────────────────────────────
def _verify_edge(cur, schema, e):
    """Classify an edge as 1:1 / N:1 / 1:N / N:N and compute a referential match
    ratio. A safe dimension join is N:1 (dimension key unique). Returns a dict or
    None if the columns don't exist."""
    ft, fc = e.get("from_table"), e.get("from_column")
    tt, tc = e.get("to_table"), e.get("to_column")
    if not all([ft, fc, tt, tc]):
        return None
    if ft not in schema or tt not in schema:
        return None
    fcols = {c["name"] for c in schema[ft]["columns"]}
    tcols = {c["name"] for c in schema[tt]["columns"]}
    if fc not in fcols or tc not in tcols:
        return None
    rel, match, verified = "unknown", None, 0
    try:
        cur.execute(f"SELECT COUNT(*) total, COUNT(DISTINCT {_bt(tc)}) dis "
                    f"FROM {_bt(tt)}")
        r = cur.fetchone()
        to_unique = r["total"] == r["dis"] and r["total"] > 0

        cur.execute(f"SELECT COUNT(*) total, COUNT(DISTINCT {_bt(fc)}) dis "
                    f"FROM {_bt(ft)}")
        r2 = cur.fetchone()
        from_unique = r2["total"] == r2["dis"] and r2["total"] > 0

        if to_unique and from_unique:
            rel = "1:1"
        elif to_unique:
            rel = "N:1"          # many fact rows -> one dim row  (SAFE for SUM)
        elif from_unique:
            rel = "1:N"
        else:
            rel = "N:N"          # fan-out risk

        # Referential match: fraction of fact keys present in the dimension.
        cur.execute(
            f"SELECT COUNT(*) miss FROM "
            f"(SELECT DISTINCT {_bt(fc)} v FROM {_bt(ft)} "
            f" WHERE {_bt(fc)} IS NOT NULL) f "
            f"LEFT JOIN {_bt(tt)} d ON f.v = d.{_bt(tc)} "
            f"WHERE d.{_bt(tc)} IS NULL")
        miss = cur.fetchone()["miss"]
        cur.execute(f"SELECT COUNT(DISTINCT {_bt(fc)}) c FROM {_bt(ft)} "
                    f"WHERE {_bt(fc)} IS NOT NULL")
        distinct_keys = cur.fetchone()["c"] or 1
        match = round(1.0 - (miss / distinct_keys), 4)
        verified = 1 if rel in ("N:1", "1:1") and match >= 0.5 else 0
    except Exception as ex:
        print(f"[KGRAPH] edge verify failed {ft}.{fc}->{tt}.{tc}: {ex}")
    return {"from_table": ft, "from_column": fc, "to_table": tt, "to_column": tc,
            "relationship": rel, "match_ratio": match, "verified": verified,
            "note": e.get("note", "")}


def _verify_hierarchy_level(cur, table, parent, child):
    """True if each child value maps to exactly one parent value (real nesting)."""
    try:
        cur.execute(
            f"SELECT COUNT(*) bad FROM ("
            f"  SELECT {_bt(child)} c FROM {_bt(table)} "
            f"  WHERE {_bt(child)} IS NOT NULL AND {_bt(parent)} IS NOT NULL "
            f"  GROUP BY {_bt(child)} HAVING COUNT(DISTINCT {_bt(parent)}) > 1"
            f") x")
        return cur.fetchone()["bad"] == 0
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. Storage
# ─────────────────────────────────────────────────────────────────────────────
_DDL = {
    "kgraph_meta": """
        CREATE TABLE IF NOT EXISTS kgraph_meta(
            id INT AUTO_INCREMENT PRIMARY KEY,
            schema_hash VARCHAR(40), status VARCHAR(20),
            table_count INT, built_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            note TEXT)""",
    "kgraph_nodes": """
        CREATE TABLE IF NOT EXISTS kgraph_nodes(
            id INT AUTO_INCREMENT PRIMARY KEY,
            table_name VARCHAR(128), node_type VARCHAR(20),
            primary_key VARCHAR(128), row_count BIGINT, note TEXT,
            INDEX(table_name))""",
    "kgraph_edges": """
        CREATE TABLE IF NOT EXISTS kgraph_edges(
            id INT AUTO_INCREMENT PRIMARY KEY,
            from_table VARCHAR(128), from_column VARCHAR(128),
            to_table VARCHAR(128), to_column VARCHAR(128),
            relationship VARCHAR(8), match_ratio FLOAT, verified TINYINT,
            note TEXT, INDEX(from_table), INDEX(to_table))""",
    "kgraph_hierarchy": """
        CREATE TABLE IF NOT EXISTS kgraph_hierarchy(
            id INT AUTO_INCREMENT PRIMARY KEY,
            hierarchy_name VARCHAR(128), dimension_table VARCHAR(128),
            level_index INT, column_name VARCHAR(128),
            cardinality INT, verified TINYINT,
            INDEX(hierarchy_name))""",
    "kgraph_synonyms": """
        CREATE TABLE IF NOT EXISTS kgraph_synonyms(
            id INT AUTO_INCREMENT PRIMARY KEY,
            business_term VARCHAR(160), target_table VARCHAR(128),
            target_column VARCHAR(128), phrase_len INT, priority INT,
            INDEX(business_term))""",
    "kgraph_metrics": """
        CREATE TABLE IF NOT EXISTS kgraph_metrics(
            id INT AUTO_INCREMENT PRIMARY KEY,
            term VARCHAR(160), expression TEXT, fact_table VARCHAR(128), note TEXT)""",
    "kgraph_dim_values": """
        CREATE TABLE IF NOT EXISTS kgraph_dim_values(
            id INT AUTO_INCREMENT PRIMARY KEY,
            table_name VARCHAR(128), column_name VARCHAR(128), value VARCHAR(255),
            INDEX(table_name), INDEX(column_name))""",
    "kgraph_backup": """
        CREATE TABLE IF NOT EXISTS kgraph_backup(
            id INT AUTO_INCREMENT PRIMARY KEY,
            version_number INT,
            schema_hash VARCHAR(40),
            trigger_source VARCHAR(64),
            snapshot_data LONGTEXT,
            node_count INT DEFAULT 0,
            edge_count INT DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX(version_number))""",
}



def _diff_schemas(schema, kgraph_nodes):
    existing_tables = {n["table_name"] for n in kgraph_nodes}
    physical_tables = set(schema.keys())
    added = physical_tables - existing_tables
    unchanged = existing_tables & physical_tables
    return {"added": list(added), "unchanged": list(unchanged)}

def _create_backup_snapshot(cur, conn, allocated_db_name, version_number, schema_hash, trigger_source):
    try:
        from controllers.kgraph_service import load_kgraph
        current_graph = load_kgraph(allocated_db_name)
        if not current_graph: return False
        import json
        snapshot_json = json.dumps(current_graph)
        node_count = len(current_graph.get("nodes", []))
        edge_count = len(current_graph.get("edges", []))
        cur.execute(
            "INSERT INTO kgraph_backup (version_number, schema_hash, trigger_source, snapshot_data, node_count, edge_count) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (version_number, schema_hash, trigger_source, snapshot_json, node_count, edge_count)
        )
        conn.commit()
        return True
    except Exception as e:
        print("[KGRAPH] Backup snapshot failed:", e)
        return False

def restore_kgraph_backup(allocated_db_name, db_host, db_user, db_pass, db_port, version_number=None):
    from database.db_connection import get_db_connection
    conn = None
    try:
        conn = pymysql.connect(host=db_host, port=int(db_port), user=db_user, password=db_pass,
                               database=allocated_db_name, cursorclass=pymysql.cursors.DictCursor)
        cur = conn.cursor()
        
        # 1. Fetch snapshot
        if version_number:
            cur.execute("SELECT snapshot_data FROM kgraph_backup WHERE version_number=%s LIMIT 1", (version_number,))
        else:
            cur.execute("SELECT snapshot_data FROM kgraph_backup ORDER BY id DESC LIMIT 1")
            
        row = cur.fetchone()
        if not row:
            print("[KGRAPH] No backup found to restore.")
            return False
            
        import json
        snapshot = json.loads(row["snapshot_data"])
        
        # 2. Wipe current
        _wipe(cur)
        
        # 3. Re-populate
        for n in snapshot.get("nodes", []):
            cur.execute("INSERT INTO kgraph_nodes(table_name,node_type,primary_key,row_count,note) VALUES(%s,%s,%s,%s,%s)",
                (n.get("table_name"), n.get("node_type"), n.get("primary_key"), n.get("row_count"), n.get("note")))
                
        for e in snapshot.get("edges", []):
            cur.execute("INSERT INTO kgraph_edges(from_table,from_column,to_table,to_column,relationship,match_ratio,verified,note) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (e.get("from_table"), e.get("from_column"), e.get("to_table"), e.get("to_column"), e.get("relationship"), e.get("match_ratio"), e.get("verified"), e.get("note")))
                
        for h in snapshot.get("hierarchies", []):
            cur.execute("INSERT INTO kgraph_hierarchy(hierarchy_name,dimension_table,level_index,column_name,cardinality,verified) VALUES(%s,%s,%s,%s,%s,%s)",
                (h.get("hierarchy_name"), h.get("dimension_table"), h.get("level_index"), h.get("column_name"), h.get("cardinality"), h.get("verified")))
                
        for s in snapshot.get("synonyms", []):
            cur.execute("INSERT INTO kgraph_synonyms(business_term,target_table,target_column,phrase_len,priority) VALUES(%s,%s,%s,%s,%s)",
                (s.get("business_term"), s.get("target_table"), s.get("target_column"), s.get("phrase_len"), s.get("priority")))
                
        for m in snapshot.get("metrics", []):
            cur.execute("INSERT INTO kgraph_metrics(term,expression,fact_table,note) VALUES(%s,%s,%s,%s)",
                (m.get("term"), m.get("expression"), m.get("fact_table"), m.get("note")))
                
        cur.execute("INSERT INTO kgraph_meta(schema_hash,status,table_count,note) VALUES(%s,%s,%s,%s)",
            (snapshot.get("schema_hash", "restored"), "ok", len(snapshot.get("nodes", [])), "Restored from backup"))
            
        conn.commit()
        return True
    except Exception as e:
        if conn: conn.rollback()
        print(f"[KGRAPH] Restore failed: {e}")
        return False


def _ensure_tables(cur):
    for ddl in _DDL.values():
        cur.execute(ddl)


def _wipe(cur):
    for t in ("kgraph_nodes", "kgraph_edges", "kgraph_hierarchy",
              "kgraph_synonyms", "kgraph_metrics", "kgraph_dim_values", "kgraph_meta"):
        try:
            cur.execute(f"DELETE FROM {t}")
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────
def build_kgraph(allocated_db_name, db_host, db_user, db_pass, db_port, force=False, trigger_source="unknown"):
    t0 = time.time()
    conn = None
    try:
        conn = _connect(allocated_db_name, db_host, db_user, db_pass, db_port)
        cur = conn.cursor()
        _ensure_tables(cur)
        conn.commit()

        schema = _extract_schema(cur)
        if not schema:
            print("[KGRAPH] no tables found — nothing to build")
            return {"status": "empty"}

        shash = _schema_hash(schema)
        try:
            cur.execute("SELECT schema_hash, status, id FROM kgraph_meta ORDER BY id DESC LIMIT 1")
            prev = cur.fetchone()
        except Exception:
            prev = None

        graph_exists = bool(prev and prev["status"] == "ok")
        version_number = (prev["id"] + 1) if prev else 1

        if not force and graph_exists and prev["schema_hash"] == shash:
            print("[KGRAPH] schema unchanged — keeping existing graph")
            return {"status": "unchanged"}

        incremental_mode = False
        diff = {"added": [], "unchanged": []}
        
        if graph_exists:
            cur.execute("SELECT table_name FROM kgraph_nodes")
            kg_nodes = cur.fetchall()
            diff = _diff_schemas(schema, kg_nodes)
            
            # Always use incremental mode when an existing verified graph is present.
            # This prevents the full graph from being wiped on schema changes.
            incremental_mode = True

            if diff["added"]:
                print(f"[KGRAPH] Incremental update: new tables detected = {diff['added']}")
            else:
                print("[KGRAPH] Incremental update: re-evaluating existing tables without wipe.")

            # Save a backup snapshot of the current graph BEFORE any modification.
            backed_up = _create_backup_snapshot(cur, conn, allocated_db_name, version_number, prev["schema_hash"], trigger_source)
            if backed_up:
                print(f"[KGRAPH] Backup snapshot v{version_number} saved successfully.")
            else:
                print("[KGRAPH] WARNING: Backup snapshot could not be saved.")

        # ── LLM proposes the graph ──────────────────────────────────────────
        from database.prompt_loader import get_prompt
        
        if incremental_mode:
            prompt_template = (
                "You are an expert Data Architect. An existing Knowledge Graph exists, but NEW tables have been added.\n"
                "Here are the existing unchanged tables:\n{UNCHANGED_JSON}\n\n"
                "Here are the NEWly added tables:\n{ADDED_JSON}\n\n"
                "Return a STRICT JSON knowledge graph with keys nodes, edges, hierarchies, synonyms, metrics.\n"
                "ONLY return details for the NEW tables and how they relate (edges) to the existing tables.\n"
                "Do NOT redefine the existing tables."
            )
            unchanged_schema = {k: v for k, v in _schema_for_prompt(schema).items() if k in diff["unchanged"]}
            added_schema = {k: v for k, v in _schema_for_prompt(schema).items() if k in diff["added"]}
            
            prompt = prompt_template.replace("{UNCHANGED_JSON}", json.dumps(unchanged_schema, indent=2))
            prompt = prompt.replace("{ADDED_JSON}", json.dumps(added_schema, indent=2))
        else:
            prompt_template = get_prompt(0, 'knowledge_graph')
            if not prompt_template or not prompt_template.strip():
                prompt_template = ("Return a STRICT JSON knowledge graph with keys fact_tables, nodes, "
                                   "edges, hierarchies, synonyms, metrics, using ONLY the columns in:\n"
                                   "{SCHEMA_JSON}")
            prompt = prompt_template.replace(
                "{SCHEMA_JSON}", json.dumps(_schema_for_prompt(schema), indent=2))
        raw = call_llm_chat([{"role": "user", "content": prompt}],
                            json_mode=True, temperature=0.0)
        graph = _parse_json(raw) or {}
        print(f"[KGRAPH] LLM proposed: "
              f"{len(graph.get('nodes', []))} nodes, "
              f"{len(graph.get('edges', []))} edges, "
              f"{len(graph.get('hierarchies', []))} hierarchies, "
              f"{len(graph.get('synonyms', []))} synonyms, "
              f"{len(graph.get('metrics', []))} metrics")

        # ── Verify edges ────────────────────────────────────────────────────
        edges = []
        for e in graph.get("edges", []):
            v = _verify_edge(cur, schema, e)
            if v:
                edges.append(v)

        # ── Verify hierarchies (and order by cardinality) ───────────────────
        hierarchies = []
        for h in graph.get("hierarchies", []):
            tbl = h.get("dimension_table")
            levels = [c for c in (h.get("levels") or []) if tbl in schema and
                      c in {col["name"] for col in schema[tbl]["columns"]}]
            if tbl not in schema or len(levels) < 2:
                continue
            card = {col["name"]: (col["cardinality"] or 0)
                    for col in schema[tbl]["columns"]}
            levels = sorted(dict.fromkeys(levels), key=lambda c: card.get(c, 0))
            verified_flags = []
            for i in range(len(levels) - 1):
                verified_flags.append(
                    _verify_hierarchy_level(cur, tbl, levels[i], levels[i + 1]))
            hierarchies.append({"name": h.get("name") or f"{tbl}_hierarchy",
                                "dimension_table": tbl, "levels": levels,
                                "cardinality": card,
                                "verified": verified_flags})

        # ── Persist ─────────────────────────────────────────────────────────
        
        try:
            # We enforce transaction
            conn.begin()
            
            if not incremental_mode:
                _wipe(cur)
            
            for n in graph.get("nodes", []):
                tbl = n.get("table")
                if tbl not in schema:
                    continue
                # Instead of simple insert, check if it exists so we don't duplicate on forced non-incremental run
                cur.execute("SELECT id FROM kgraph_nodes WHERE table_name=%s", (tbl,))
                if cur.fetchone():
                    cur.execute("UPDATE kgraph_nodes SET row_count=%s WHERE table_name=%s", (schema[tbl]["row_count"], tbl))
                else:
                    cur.execute(
                        "INSERT INTO kgraph_nodes(table_name,node_type,primary_key,row_count,note) "
                        "VALUES(%s,%s,%s,%s,%s)",
                        (tbl, (n.get("type") or "dimension")[:20], n.get("primary_key"),
                         schema[tbl]["row_count"], (n.get("note") or "")[:255]))

            for e in edges:
                # Basic dedup by checking from_table + from_column -> to_table + to_column
                cur.execute("SELECT id FROM kgraph_edges WHERE from_table=%s AND from_column=%s AND to_table=%s AND to_column=%s",
                            (e["from_table"], e["from_column"], e["to_table"], e["to_column"]))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO kgraph_edges(from_table,from_column,to_table,to_column,"
                        "relationship,match_ratio,verified,note) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                        (e["from_table"], e["from_column"], e["to_table"], e["to_column"],
                         e["relationship"], e["match_ratio"], e["verified"], (e["note"] or "")[:255]))

            for h in hierarchies:
                for i, col in enumerate(h["levels"]):
                    ver = 1 if (i == 0 or (i - 1) < len(h["verified"]) and h["verified"][i - 1]) else 0
                    # Check if exists
                    cur.execute("SELECT id FROM kgraph_hierarchy WHERE hierarchy_name=%s AND dimension_table=%s AND level_index=%s AND column_name=%s",
                                (h["name"][:128], h["dimension_table"], i, col))
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO kgraph_hierarchy(hierarchy_name,dimension_table,"
                            "level_index,column_name,cardinality,verified) VALUES(%s,%s,%s,%s,%s,%s)",
                            (h["name"][:128], h["dimension_table"], i, col,
                             int(h["cardinality"].get(col, 0)), ver))

            for s in graph.get("synonyms", []):
                term = (s.get("term") or "").strip()
                tbl, col = s.get("table"), s.get("column")
                if not term or tbl not in schema:
                    continue
                if col not in {c["name"] for c in schema[tbl]["columns"]}:
                    continue
                cur.execute("SELECT id FROM kgraph_synonyms WHERE business_term=%s AND target_table=%s AND target_column=%s",
                            (term.lower()[:160], tbl, col))
                if not cur.fetchone():
                    cur.execute(
                        "INSERT INTO kgraph_synonyms(business_term,target_table,target_column,"
                        "phrase_len,priority) VALUES(%s,%s,%s,%s,%s)",
                        (term.lower()[:160], tbl, col, len(term), len(term.split())))

            for m in graph.get("metrics", []):
                term = (m.get("term") or "").strip()
                expr = (m.get("expression") or "").strip()
                if term and expr:
                    cur.execute("SELECT id FROM kgraph_metrics WHERE term=%s", (term.lower()[:160],))
                    if not cur.fetchone():
                        cur.execute(
                            "INSERT INTO kgraph_metrics(term,expression,fact_table,note) "
                            "VALUES(%s,%s,%s,%s)",
                            (term.lower()[:160], expr, m.get("fact_table"), (m.get("note") or "")[:255]))

            # Authoritative dimension values (from DB, not the LLM) for drill-down.
            # Only do this for added tables if incremental, or all if wipe
            tables_to_sync_dims = diff["added"] if incremental_mode else list(schema.keys())
            for t in tables_to_sync_dims:
                meta = schema[t]
                for c in meta["columns"]:
                    if c["values"]:
                        for v in c["values"][:SAMPLE_VALUES_MAX]:
                            cur.execute("SELECT id FROM kgraph_dim_values WHERE table_name=%s AND column_name=%s AND value=%s", (t, c["name"], str(v)[:255]))
                            if not cur.fetchone():
                                cur.execute(
                                    "INSERT INTO kgraph_dim_values(table_name,column_name,value) "
                                    "VALUES(%s,%s,%s)", (t, c["name"], str(v)[:255]))
            
            conn.commit()
            
        except Exception as persist_error:
            conn.rollback()
            raise persist_error

        cur.execute("INSERT INTO kgraph_meta(schema_hash,status,table_count,note) "
                    "VALUES(%s,%s,%s,%s)",
                    (shash, "ok", len(schema),
                     f"edges_verified={sum(e['verified'] for e in edges)}/{len(edges)}"))
        conn.commit()
        print(f"[KGRAPH] built for {allocated_db_name}: "
              f"{len(schema)} tables, {len(edges)} edges "
              f"({sum(e['verified'] for e in edges)} verified), "
              f"{len(hierarchies)} hierarchies in {time.time()-t0:.1f}s")
        return {"status": "ok", "tables": len(schema), "edges": len(edges)}

    except Exception as e:
        print(f"[KGRAPH] build failed: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
