import re, json, time, hashlib, math, requests, mysql.connector, threading, os
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    print("[RAG] psycopg2 not installed — PostgreSQL support disabled")
from collections import defaultdict
from flask import request, jsonify
from controllers.intent_router import classify_intent
from controllers.query_branches import execute_hybrid
from database.config import MISTRAL_API_KEY, MISTRAL_MODEL, MYSQL_CONFIG

# ChromaDB persistent storage — vectors survive server restarts
CHROMA_PERSIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chroma_store"
)
os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)

MISTRAL_URL        = "https://api.mistral.ai/v1/chat/completions"
MAX_ROWS           = 200
TOP_K              = 80
CACHE_TTL          = 600
MAX_CTX_CHARS      = 15000

_CACHE   = {}
_CLIENTS = {}
_LOCKS   = {}

_FOLLOWUP_CYCLE = ["What", "Where", "Why"]
_TURN_COUNTER   = {}

def _next_followup_type(session_id):
    turn = _TURN_COUNTER.get(session_id, 0)
    return _FOLLOWUP_CYCLE[turn % 3]

def _advance_turn(session_id):
    _TURN_COUNTER[session_id] = _TURN_COUNTER.get(session_id, 0) + 1

def _followup_instruction(ftype):

    if ftype.lower() == "what":
        count = 5
    elif ftype.lower() == "where":
        count = 3
    elif ftype.lower() == "why":
        count = 3
    else:
        count = 3

    questions = ",\n".join([f'"{ftype} ...?"' for _ in range(count)])

    return f"""
Generate exactly {count} intelligent follow-up questions based on the previous answer.

STRICT RULES:
1. Questions must be high-level BUSINESS INSIGHT questions.
2. Questions must be directly related to the returned data.

Do not assume:
- causes
- risks
- opportunities
- business strategy
- customer behaviour
- operational issues

Only ask questions supported by the data.
3. Questions must encourage deeper analysis, strategic thinking, or early problem detection.
4. DO NOT mention table names, database names, column names, or technical terms.
5. Questions should sound like executive/business analyst questions.
6. Each question must start with "{ftype}".

Return ONLY:

"follow_up_questions":[
{questions}
]
"""

GRAPH_KW  = {"graph","chart","plot","visualize","visualise","bar","pie","line","histogram","scatter"}
REPORT_KW = {"report","summary report","generate report","make a report","create a report","write a report"}
GREET_RE  = re.compile(r'^\s*(hi+|hello+|hey+|howdy|greetings|sup|yo+|hiya|good\s*(morning|afternoon|evening|night)|what\'?s\s*up)\s*[!?.]*\s*$', re.I)


# ══════════════════════════════════════════════════════
# OPTIMIZATION 1: Global models loaded once at startup
# ══════════════════════════════════════════════════════

_EMBED_MODEL   = None
_CROSS_ENCODER = None
_MODEL_LOCK    = threading.Lock()

# OPTIMIZATION 2: Embedding cache
_EMBED_CACHE   = {}


def _get_embed_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        with _MODEL_LOCK:
            if _EMBED_MODEL is None:
                from sentence_transformers import SentenceTransformer
                print("[RAG] Loading SentenceTransformer globally...")
                _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
                print("[RAG] SentenceTransformer ready")
    return _EMBED_MODEL


def _get_cross_encoder():
    global _CROSS_ENCODER
    if _CROSS_ENCODER is None:
        with _MODEL_LOCK:
            if _CROSS_ENCODER is None:
                from sentence_transformers.cross_encoder import CrossEncoder
                print("[RAG] Loading CrossEncoder globally...")
                _CROSS_ENCODER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                print("[RAG] CrossEncoder ready")
    return _CROSS_ENCODER


def _encode_texts(texts):
    """OPTIMIZATION 2+3: Cache-aware batch embedding."""
    model  = _get_embed_model()
    result = [None] * len(texts)
    uncached_idx   = []
    uncached_texts = []

    for i, t in enumerate(texts):
        if t in _EMBED_CACHE:
            result[i] = _EMBED_CACHE[t]
        else:
            uncached_idx.append(i)
            uncached_texts.append(t)

    if uncached_texts:
        new_embeds = model.encode(uncached_texts, batch_size=128, show_progress_bar=False).tolist()
        for idx, emb, txt in zip(uncached_idx, new_embeds, uncached_texts):
            _EMBED_CACHE[txt] = emb
            result[idx] = emb

    return result


# ══════════════════════════════════════════════════════
# BM25
# ══════════════════════════════════════════════════════

class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.N = len(docs)
        self.tokenized = [self._tok(d) for d in docs]
        self.avgdl = sum(len(t) for t in self.tokenized) / max(self.N, 1)
        self.df = defaultdict(int)
        for td in self.tokenized:
            for w in set(td): self.df[w] += 1

    def _tok(self, text):
        return re.findall(r'\b\w+\b', text.lower())

    def score(self, query, top_k):
        q_terms = self._tok(query)
        scores  = []
        for i, td in enumerate(self.tokenized):
            tf_map = defaultdict(int)
            for w in td: tf_map[w] += 1
            s = 0.0
            for term in q_terms:
                if term not in tf_map: continue
                tf  = tf_map[term]
                idf = math.log((self.N - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1)
                den = tf + self.k1 * (1 - self.b + self.b * len(td) / self.avgdl)
                s  += idf * (tf * (self.k1 + 1)) / den
            if s > 0: scores.append((i, s))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]


# ══════════════════════════════════════════════════════
# DATA LOADERS
# ══════════════════════════════════════════════════════

def _local_conn(fn):
    c = fn()
    if not c: raise RuntimeError("Local DB failed")
    return c


def _load_all(session_id, get_fn):
    chunks = []
    chunks += _load_db(session_id, get_fn)
    chunks += _load_sheets(session_id, get_fn)
    chunks += _load_web(session_id, get_fn)
    chunks += _load_analysis_report(session_id, get_fn)
    return chunks


def _load_analysis_report(session_id, get_fn):

    chunks = []
    local = cur = None
    try:
        local = _local_conn(get_fn)
        cur   = local.cursor(dictionary=True)

        # ── 1. saved_web_results: grouped by topic (richer than _load_web) ──
        cur.execute(
            """SELECT topic, title, url, brief FROM saved_web_results
               WHERE session_id=%s ORDER BY topic""",
            (session_id,)
        )
        web_rows = cur.fetchall()
        if web_rows:
            # Group by topic
            from collections import defaultdict as _dd
            by_topic = _dd(list)
            for r in web_rows:
                by_topic[r["topic"]].append(r)
            for topic, items in by_topic.items():
                lines = [f"[ANALYSIS_WEB] Web research topic: {topic} ({len(items)} results)"]
                for item in items:
                    lines.append(f"  Title: {item['title']}")
                    if item.get("brief"):
                        lines.append(f"  Brief: {str(item['brief'])[:400]}")
                chunks.append(_chunk("\n".join(lines), kind="analysis_web", table=topic))
            print(f"[RAG] analysis_web: {len(by_topic)} topics from saved_web_results")

        # ── 2. external_db_sync_log: DB + table metadata summary ──
        cur.execute(
            """SELECT DISTINCT external_database, new_user_db, table_name
               FROM external_db_sync_log
               WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db!=''
               ORDER BY external_database, table_name""",
            (session_id,)
        )
        sync_rows = cur.fetchall()
        if sync_rows:
            from collections import defaultdict as _dd2
            by_db = _dd2(list)
            for r in sync_rows:
                by_db[r["external_database"]].append(r)
            for ext_db, rows in by_db.items():
                new_db  = rows[0]["new_user_db"]
                tables  = [r["table_name"] for r in rows if r["table_name"]]
                text = (
                    f"[ANALYSIS_DB_META] Database analyzed: {ext_db} "
                    f"(stored as: {new_db})\n"
                    f"Tables found: {', '.join(tables)}\n"
                    f"Total tables: {len(tables)}"
                )
                chunks.append(_chunk(text, kind="analysis_db_meta", db=new_db))
            print(f"[RAG] analysis_db_meta: {len(by_db)} databases from sync_log")

    except Exception as e:
        print(f"[RAG] analysis_report load error: {e}")
    finally:
        if cur:   cur.close()
        if local: local.close()

    return chunks


def _load_db(session_id, get_fn):
    """
    Loads DB chunks for RAG — supports both MySQL and PostgreSQL.
    For PostgreSQL:
      - If schema was specified during connection → only that schema's tables
      - If no schema → all non-system schemas (public + any custom ones)
    """
    chunks = []
    local = cur = None

    # ── 1. Fetch all DB credentials for this session ──
    try:
        local = _local_conn(get_fn)
        cur   = local.cursor(dictionary=True)

        # MySQL/MSSQL: get allocated db name from sync log
        cur.execute("""
            SELECT DISTINCT new_user_db
            FROM external_db_sync_log
            WHERE session_id=%s AND new_user_db IS NOT NULL AND new_user_db!=''
        """, (session_id,))
        sync_rows = cur.fetchall()

        # PostgreSQL: credentials stored in database_credential
        cur.execute("""
            SELECT credential, db_type
            FROM database_credential
            WHERE session_id=%s AND db_type IN ('postgresql', 'postgres')
            ORDER BY connection_id DESC
        """, (session_id,))
        pg_cred_rows = cur.fetchall()

    finally:
        if cur:   cur.close()
        if local: local.close()

    # ── 2. MySQL / MSSQL (sync log approach — existing logic) ──
    mysql_dbs = [r["new_user_db"] for r in sync_rows
                 if r.get("db_type", "mysql") not in ("postgresql", "postgres")]

    for db in mysql_dbs:
        if not re.match(r'^\w+$', db): continue
        conn = c2 = None
        try:
            conn = mysql.connector.connect(
                host=MYSQL_CONFIG["host"], port=MYSQL_CONFIG["port"],
                user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"],
                database=db, connection_timeout=10)
            c2 = conn.cursor(dictionary=True)
            c2.execute("SHOW TABLES")
            tables   = [list(r.values())[0] for r in c2.fetchall()]
            all_rows = {}

            for t in tables:
                if not re.match(r'^\w+$', t): continue
                try:
                    c2.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
                    rows = c2.fetchall()
                    if not rows: continue
                    all_rows[t] = rows
                    cols = list(rows[0].keys())
                    chunks.append(_chunk(
                        f"[SCHEMA] db:{db} table:{t} columns:{','.join(cols)} total_rows:{len(rows)}",
                        db=db, table=t, kind="schema"))
                    lines = [
                        f"[COUNT] db:{db} table:{t} has {len(rows)} rows total.",
                        f"Number of {t}: {len(rows)}",
                        f"Total {t} count: {len(rows)}"
                    ]
                    for col in cols[:10]:
                        vals = list(dict.fromkeys(
                            str(r[col]) for r in rows if r[col] is not None and str(r[col]).strip()))
                        if vals:
                            lines.append(f"All values of {col} in {t}: {', '.join(vals[:40])}")
                    chunks.append(_chunk("\n".join(lines), db=db, table=t, kind="count"))
                    for i, row in enumerate(rows, 1):
                        parts = " | ".join(f"{k}:{v}" for k,v in row.items()
                                           if v is not None and str(v).strip())
                        chunks.append(_chunk(f"[ROW] db:{db} table:{t} row{i}: {parts}",
                                             db=db, table=t, kind="row"))
                    print(f"[RAG] {db}.{t}: {len(rows)} rows → {len(rows)+2} chunks")
                except Exception as e:
                    print(f"[RAG] skip {t}: {e}")

            chunks += _build_joins(db, all_rows)
        except Exception as e:
            print(f"[RAG] db connect {db}: {e}")
        finally:
            if c2:   c2.close()
            if conn: conn.close()

    # ── 3. PostgreSQL (direct connection using stored credentials) ──
    if not PSYCOPG2_AVAILABLE:
        if pg_cred_rows:
            print("[RAG] PostgreSQL credentials found but psycopg2 not installed — skipping")
        return chunks

    seen_pg_dbs = set()
    for cred_row in pg_cred_rows:
        try:
            cred = cred_row["credential"]
            if isinstance(cred, str):
                cred = json.loads(cred)

            pg_host     = cred.get("host", "localhost")
            pg_port     = int(cred.get("port", 5432))
            pg_user     = cred.get("username", "")
            pg_password = cred.get("password", "")
            pg_database = cred.get("database", "")
            pg_schema   = cred.get("schema")  # may be None/empty

            # Deduplicate same DB+schema combos
            dedup_key = f"{pg_host}:{pg_port}/{pg_database}/{pg_schema or '__all__'}"
            if dedup_key in seen_pg_dbs:
                continue
            seen_pg_dbs.add(dedup_key)

            print(f"[RAG] Connecting PostgreSQL: {pg_host}:{pg_port}/{pg_database} schema={pg_schema or 'ALL'}")

            pg_conn = psycopg2.connect(
                host=pg_host, port=pg_port,
                user=pg_user, password=pg_password,
                dbname=pg_database,
                connect_timeout=10
            )
            pg_cur = pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            # Determine which schemas to fetch
            if pg_schema and pg_schema.strip():
                # User specified a schema → use only that
                schemas_to_fetch = [pg_schema.strip()]
            else:
                # No schema specified → fetch ALL non-system schemas
                pg_cur.execute("""
                    SELECT schema_name
                    FROM information_schema.schemata
                    WHERE schema_name NOT IN ('pg_catalog', 'information_schema',
                                              'pg_toast', 'pg_temp_1', 'pg_toast_temp_1')
                      AND schema_name NOT LIKE 'pg_temp_%'
                      AND schema_name NOT LIKE 'pg_toast_temp_%'
                    ORDER BY schema_name
                """)
                schemas_to_fetch = [r["schema_name"] for r in pg_cur.fetchall()]
                print(f"[RAG] PostgreSQL schemas found: {schemas_to_fetch}")

            all_rows_pg = {}

            for schema in schemas_to_fetch:
                # Get all tables in this schema
                pg_cur.execute("""
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """, (schema,))
                tables = [r["table_name"] for r in pg_cur.fetchall()]
                print(f"[RAG] PG schema '{schema}' tables: {tables}")

                for t in tables:
                    qualified = f"{schema}.{t}"
                    label     = f"{pg_database}.{qualified}"
                    try:
                        pg_cur.execute(
                            f'SELECT * FROM "{schema}"."{t}" LIMIT %s',
                            (MAX_ROWS,)
                        )
                        rows = [dict(r) for r in pg_cur.fetchall()]
                        if not rows:
                            continue

                        # Convert non-serialisable types (dates, Decimal, etc.)
                        for row in rows:
                            for k, v in row.items():
                                if v is not None and not isinstance(v, (str, int, float, bool)):
                                    row[k] = str(v)

                        all_rows_pg[qualified] = rows
                        cols = list(rows[0].keys())

                        chunks.append(_chunk(
                            f"[SCHEMA] db:{label} table:{qualified} schema:{schema} "
                            f"columns:{','.join(cols)} total_rows:{len(rows)}",
                            db=pg_database, table=qualified, kind="schema"))

                        lines = [
                            f"[COUNT] db:{label} table:{qualified} has {len(rows)} rows total.",
                            f"Number of {t}: {len(rows)}",
                            f"Total {t} count: {len(rows)}"
                        ]
                        for col in cols[:10]:
                            vals = list(dict.fromkeys(
                                str(r[col]) for r in rows
                                if r[col] is not None and str(r[col]).strip()))
                            if vals:
                                lines.append(f"All values of {col} in {t}: {', '.join(vals[:40])}")
                        chunks.append(_chunk("\n".join(lines), db=pg_database, table=qualified, kind="count"))

                        for i, row in enumerate(rows, 1):
                            parts = " | ".join(
                                f"{k}:{v}" for k, v in row.items()
                                if v is not None and str(v).strip()
                            )
                            chunks.append(_chunk(
                                f"[ROW] db:{label} schema:{schema} table:{t} row{i}: {parts}",
                                db=pg_database, table=qualified, kind="row"))

                        print(f"[RAG] PG {label}: {len(rows)} rows → {len(rows)+2} chunks")

                    except Exception as e:
                        print(f"[RAG] PG skip {qualified}: {e}")
                        pg_conn.rollback()

            pg_cur.close()
            pg_conn.close()

        except Exception as e:
            print(f"[RAG] PostgreSQL connect error: {e}")

    return chunks


def _build_joins(db, all_rows):
    chunks = []
    user_tables = [t for t in all_rows if re.search(r'\busers?\b', t, re.I)]
    for ut in user_tables:
        u_rows = all_rows[ut]
        if not u_rows: continue
        ucols  = list(u_rows[0].keys())
        id_col = next((c for c in ucols if c in ('id','user_id','uid')), ucols[0])
        nm_col = next((c for c in ucols if re.search(r'\b(name|username)\b', c, re.I)), None)
        for ur in u_rows:
            uid   = str(ur.get(id_col,"")).strip()
            uname = str(ur.get(nm_col, uid)).strip() if nm_col else uid
            if not uid: continue
            for at, a_rows in all_rows.items():
                if at == ut or not a_rows: continue
                acols   = list(a_rows[0].keys())
                ref_col = next((c for c in acols if re.search(r'\buser_id\b|\buid\b|\bauthor\b', c, re.I)), None)
                if not ref_col: continue
                acts = [r for r in a_rows if str(r.get(ref_col,"")).strip() == uid]
                if not acts: continue
                detail = " || ".join(
                    " | ".join(f"{k}:{v}" for k,v in r.items() if v is not None and str(v).strip())
                    for r in acts[:15])
                chunks.append(_chunk(
                    f"[JOIN] db:{db} user:'{uname}' (id:{uid}) from:{ut} "
                    f"has {len(acts)} record(s) in table:{at}. data: {detail}",
                    db=db, table=f"{ut}+{at}", kind="join"))
    return chunks


def _load_sheets(session_id, get_fn):
    chunks = []
    local = cur = None
    try:
        local = _local_conn(get_fn)
        cur   = local.cursor(dictionary=True)
        cur.execute("SELECT table_name,sheet_url FROM sheet_scans WHERE session_id=%s", (session_id,))
        for sc in cur.fetchall():
            t = sc["table_name"]
            if not re.match(r'^sheet_\w+$', t): continue
            try:
                cur.execute(f"SELECT * FROM `{t}` LIMIT %s", (MAX_ROWS,))
                rows = cur.fetchall()
                if not rows: continue
                cols = [c for c in rows[0].keys() if c != "_row_id"]
                chunks.append(_chunk(f"[SCHEMA] sheet:{t} url:{sc.get('sheet_url','')} columns:{','.join(cols)} rows:{len(rows)}", table=t, kind="schema"))
                lines = [f"[COUNT] sheet:{t} has {len(rows)} rows total."]
                for col in cols[:6]:
                    vals = list(dict.fromkeys(str(r[col]) for r in rows if r.get(col) is not None))
                    lines.append(f"All values of {col}: {', '.join(vals[:20])}")
                chunks.append(_chunk("\n".join(lines), table=t, kind="count"))
                for i, row in enumerate(rows, 1):
                    parts = " | ".join(f"{k}:{v}" for k,v in row.items()
                                       if k!="_row_id" and v is not None and str(v).strip())
                    chunks.append(_chunk(f"[ROW] sheet:{t} row{i}: {parts}", table=t, kind="row"))
            except Exception as e:
                print(f"[RAG] sheet {t}: {e}")
    except Exception as e:
        print(f"[RAG] sheets: {e}")
    finally:
        if cur:   cur.close()
        if local: local.close()
    return chunks


def _load_web(session_id, get_fn):
    chunks = []
    local = cur = None
    try:
        local = _local_conn(get_fn)
        cur   = local.cursor(dictionary=True)
        cur.execute("SELECT title,url,brief,topic FROM saved_web_results WHERE session_id=%s", (session_id,))
        for r in cur.fetchall():
            chunks.append(_chunk(
                f"[WEB] title:{r['title']} url:{r['url']} topic:{r.get('topic','')} content:{r.get('brief','')}",
                kind="web"))
    except Exception as e:
        print(f"[RAG] web: {e}")
    finally:
        if cur:   cur.close()
        if local: local.close()
    return chunks


def _chunk(text, db="", table="", kind="row"):
    return {"text": text, "db": db, "table": table, "kind": kind}


# ══════════════════════════════════════════════════════
# VECTOR STORE (ChromaDB)
# ══════════════════════════════════════════════════════

def _get_or_create_lock(session_id):
    if session_id not in _LOCKS:
        _LOCKS[session_id] = threading.Lock()
    return _LOCKS[session_id]


def _col_safe_count(col):
    try:    return col.count()
    except: return 0


def _build_store(session_id, get_fn):
    import chromadb
    lock = _get_or_create_lock(session_id)
    with lock:
        now = time.time()
        if session_id in _CACHE:
            chunks, bm25, col, ts = _CACHE[session_id]
            if now - ts < CACHE_TTL and _col_safe_count(col) > 0:
                print(f"[RAG] cache hit — {len(chunks)} chunks")
                return chunks, bm25, col
            else:
                _CACHE.pop(session_id, None)

        print(f"[RAG] building store for {session_id[:8]}...")
        all_chunks = _load_all(session_id, get_fn)
        if not all_chunks:
            return None, None, None

        # OPTIMIZATION 4: Deduplicate chunks before indexing
        seen_texts = set()
        deduped    = []
        for c in all_chunks:
            if c["text"] not in seen_texts:
                seen_texts.add(c["text"])
                deduped.append(c)
        removed = len(all_chunks) - len(deduped)
        if removed > 0:
            print(f"[RAG] deduped {removed} duplicates → {len(deduped)} unique chunks")
        all_chunks = deduped

        texts    = [c["text"] for c in all_chunks]
        bm25_idx = BM25(texts)

        # Batch encode using global model + cache
        embeds = _encode_texts(texts)

        col_name = "s_" + hashlib.md5(session_id.encode()).hexdigest()[:12]
        if session_id not in _CLIENTS:
            _CLIENTS[session_id] = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
        client = _CLIENTS[session_id]
        try: client.delete_collection(col_name)
        except: pass
        col = client.create_collection(col_name)

        for i in range(0, len(all_chunks), 500):
            b = all_chunks[i:i+500]
            col.add(
                documents  = [c["text"]  for c in b],
                embeddings = embeds[i:i+500],
                metadatas  = [{"db":c["db"],"table":c["table"],"kind":c["kind"]} for c in b],
                ids        = [f"c{i+j}" for j in range(len(b))]
            )

        _CLIENTS[session_id] = client
        _CACHE[session_id]   = (all_chunks, bm25_idx, col, now)
        print(f"[RAG] ✓ {len(all_chunks)} chunks indexed")
        return all_chunks, bm25_idx, col


# ══════════════════════════════════════════════════════
# QUERY UNDERSTANDING
# ══════════════════════════════════════════════════════

def _understand(question, all_chunks):
    q      = question.lower()
    tokens = set(re.findall(r'\b\w{3,}\b', q))
    known_tables = list(dict.fromkeys(c["table"] for c in all_chunks if c["table"]))

    table_hints = []
    for t in known_tables:
        t_parts = set(re.findall(r'\b\w{3,}\b', t.lower()))
        overlap = tokens & t_parts
        if overlap: table_hints.append((t, len(overlap)))
    table_hints.sort(key=lambda x: -x[1])
    matched_tables = [t for t,_ in table_hints[:5]]

    intent = "lookup"
    if re.search(r'\bhow\s+many\b|\bcount\b|\btotal\b|\bnumber\s+of\b|\bhow\s+much\b', q):
        intent = "count"
    elif re.search(r'\blist\b|\ball\b|\beveryone\b|\bnames?\b|\bshow\s+(me\s+)?all\b', q):
        intent = "list"
    elif re.search(r'\bwho\b|\bwhich\s+user\b|\bwhose\b', q):
        intent = "who"
    elif re.search(r'\bcreated\s+by\b|\bbelongs?\s+to\b|\bby\s+whom\b|\bowned\s+by\b', q):
        intent = "join"
    elif re.search(r'\bwhat\s+is\b|\bwhat\s+are\b|\btell\s+me\b|\bfind\b|\bget\b', q):
        intent = "lookup"

    entities = re.findall(r"'([^']+)'|\"([^\"]+)\"", question)
    entities = [e[0] or e[1] for e in entities]

    queries = [question]
    if intent == "count" and matched_tables:
        for t in matched_tables[:3]:
            queries += [f"COUNT {t} total rows", f"Number of {t}", f"how many {t}", f"[COUNT] {t}"]
    elif intent == "list" and matched_tables:
        for t in matched_tables[:2]:
            queries += [f"All values of", f"list all {t}", f"[COUNT] {t}"]
    elif intent == "join":
        queries += ["[JOIN]"] + [f"user '{e}'" for e in entities]
    elif entities:
        queries += [f"'{e}'" for e in entities] + [f"{e}" for e in entities]

    if not matched_tables:
        for t in known_tables:
            for tok in tokens:
                if tok in t.lower() and len(tok) > 3:
                    matched_tables.append(t); break
        matched_tables = list(dict.fromkeys(matched_tables))[:5]

    return {
        "intent":      intent,
        "table_hints": matched_tables,
        "entities":    entities,
        "queries":     list(dict.fromkeys(queries))
    }


# ══════════════════════════════════════════════════════
# HYBRID RETRIEVAL (BM25 + Vector + Cross-Encoder Rerank)
# ══════════════════════════════════════════════════════

def _retrieve(all_chunks, bm25_idx, col, question, understanding):
    intent   = understanding["intent"]
    hints    = understanding["table_hints"]
    queries  = understanding["queries"]
    entities = understanding["entities"]

    scores = defaultdict(float)

    # BM25
    for q in queries:
        for idx, s in bm25_idx.score(q, top_k=80):
            scores[idx] += s * 1.0

    # OPTIMIZATION 3: Batch encode all queries at once
    q_embeds = _encode_texts(queries)
    per_q    = max(8, TOP_K // len(queries))
    seen     = set()
    for q_emb in q_embeds:
        n = min(per_q, _col_safe_count(col))
        if n == 0: continue
        res = col.query(query_embeddings=[q_emb], n_results=n,
                        include=["documents","metadatas"])
        for doc, meta in zip(res["documents"][0], res["metadatas"][0]):
            key = doc[:100]
            if key in seen: continue
            seen.add(key)
            for i, c in enumerate(all_chunks):
                if c["text"][:100] == key:
                    scores[i] += 2.0; break

    # Boosts
    for i, c in enumerate(all_chunks):
        if c["table"] in hints:                               scores[i] += 5.0
        if intent == "count" and c["kind"] == "count":        scores[i] += 8.0
        elif intent == "list" and c["kind"] == "count":       scores[i] += 6.0
        elif intent == "join" and c["kind"] == "join":        scores[i] += 8.0
        for ent in entities:
            if ent.lower() in c["text"].lower():              scores[i] += 4.0

    ranked = sorted(scores.items(), key=lambda x: -x[1])

    forced = {i for i, c in enumerate(all_chunks)
              if c["kind"] == "count" and c["table"] in hints}

    candidate_indices = list(forced)
    for i, _ in ranked:
        if i not in forced: candidate_indices.append(i)
        if len(candidate_indices) >= TOP_K: break

    # OPTIMIZATION 5: Cross-encoder reranking top-40 → keep best 20
    RERANK_TOP  = 40
    RERANK_KEEP = 20
    rerank_pool = candidate_indices[:RERANK_TOP]

    if len(rerank_pool) > RERANK_KEEP:
        try:
            ce_model  = _get_cross_encoder()
            pairs     = [(question, all_chunks[i]["text"][:512]) for i in rerank_pool]
            ce_scores = ce_model.predict(pairs)
            reranked  = sorted(zip(rerank_pool, ce_scores), key=lambda x: -x[1])
            forced_in = [i for i in rerank_pool if i in forced]
            reranked_nf = [i for i, _ in reranked if i not in forced]
            rerank_pool = forced_in + reranked_nf[:RERANK_KEEP]
            candidate_indices = rerank_pool + candidate_indices[RERANK_TOP:]
            print(f"[RAG] cross-encoder reranked {RERANK_TOP} → kept {len(rerank_pool)}")
        except Exception as e:
            print(f"[RAG] cross-encoder skipped: {e}")

    parts, total = [], 0
    for i in candidate_indices:
        txt   = all_chunks[i]["text"]
        if total + len(txt) > MAX_CTX_CHARS: break
        parts.append(txt)
        total += len(txt)

    return "\n\n".join(parts)


# ══════════════════════════════════════════════════════
# AUTO CHAT HISTORY SAVE
# ══════════════════════════════════════════════════════

_HISTORY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS session_chat_history (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    session_id          VARCHAR(100) NOT NULL,
    user_id             INT          NOT NULL,
    turn_index          INT          NOT NULL DEFAULT 0,
    visit_number        INT          NOT NULL DEFAULT 1,
    question            TEXT         NOT NULL,
    answer              LONGTEXT     NOT NULL,
    follow_up_questions JSON         DEFAULT NULL,
    visualizations      JSON         DEFAULT NULL,
    intent              VARCHAR(50)  DEFAULT NULL,
    mode                VARCHAR(30)  DEFAULT 'answer',
    created_at          DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session      (session_id),
    INDEX idx_user         (user_id),
    INDEX idx_session_user (session_id, user_id)
);
"""

def _save_history(get_fn, session_id, user_id, question, answer, follow_ups, intent, mode, visualizations=None, visit_number=1):
    if not user_id: return
    conn = cur = None
    try:
        conn = get_fn()
        cur  = conn.cursor(dictionary=True)
        cur.execute(_HISTORY_TABLE_SQL)
        cur.execute("""
            SELECT COALESCE(MAX(turn_index), -1) AS last_turn
            FROM session_chat_history
            WHERE session_id = %s AND user_id = %s
        """, (session_id, int(user_id)))
        row        = cur.fetchone()
        turn_index = (row["last_turn"] + 1) if row else 0
        cur.execute("""
            INSERT INTO session_chat_history
                (session_id, user_id, turn_index, visit_number, question, answer,
                 follow_up_questions, visualizations, intent, mode)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (session_id, int(user_id), turn_index, visit_number, question, answer,
              json.dumps(follow_ups) if follow_ups else None,
              json.dumps(visualizations) if visualizations else None,
              intent or None, mode))
        conn.commit()
    except Exception as e:
        print(f"[History] save error: {e}")
    finally:
        if cur:  cur.close()
        if conn: conn.close()


# ══════════════════════════════════════════════════════
# MISTRAL
# ══════════════════════════════════════════════════════

from model.llm_client import call_llm_chat

def _mistral(system, user, retries=2, temperature=0.15):
    # Trim from the middle if too long, preserving both context start and prompt instructions at the end
    if len(user) > 28000:
        half = 13500
        user = user[:half] + "\n\n[...context trimmed for token limit...]\n\n" + user[-half:]
        print(f"[LLM] prompt trimmed")
        
    messages = [
        {"role":"system","content":system},
        {"role":"user","content":user}
    ]
    
    for attempt in range(retries + 1):
        try:
            response = call_llm_chat(messages, json_mode=True, temperature=temperature)
            if response:
                if response.startswith("[LLM Error]"):
                    raise Exception(response)
                cleaned = response.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                elif cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                return json.loads(cleaned.strip())
            return None
        except Exception as e:
            print(f"[LLM] error attempt {attempt+1}: {e}")
            if attempt == retries: return None
            import time
            time.sleep(1)
    return None


def _history(raw):
    if not raw or not isinstance(raw, list): return ""
    lines = [f"{str(t.get('role','user')).capitalize()}: {str(t.get('content',''))}"
             for t in raw[-6:] if isinstance(t, dict)]
    return ("Chat history:\n" + "\n".join(lines) + "\n\n") if lines else ""


def _is_graph(q):  return bool(set(q.lower().split()) & GRAPH_KW)
def _is_report(q): return any(k in q.lower() for k in REPORT_KW)
def _is_greet(q):  return bool(GREET_RE.match(q.strip()))

ANALYTICAL_KW = {"top", "highest", "average", "total", "trend", "dashboard", "how many", "sum", "vs", "compare", "lowest", "distribution", "revenue", "sales", "discount", "count", "maximum", "minimum", "profit", "ratio", "fastest", "declining", "percentage"}
def _is_analytical(q): return bool(set(q.lower().split()) & ANALYTICAL_KW) or "how many" in q.lower()

# ─────────────────────────────────────────────
# VISUALIZATION SUPPORT
# ─────────────────────────────────────────────

def _normalize_visualizations(viz_list):

    if not isinstance(viz_list, list):
        return []

    normalized = []

    for v in viz_list:

        if not isinstance(v, dict):
            continue

        vtype = str(v.get("type","")).lower()

        if vtype in ("bar","barchart","bar-chart"):
            vtype = "bar_chart"

        elif vtype in ("line","linechart"):
            vtype = "line_chart"

        elif vtype in ("pie","piechart"):
            vtype = "pie_chart"

        elif vtype in ("table","grid"):
            vtype = "table"

        item = {
            "type": vtype,
            "title": v.get("title","")
        }

        # if vtype in ("bar_chart","line_chart"):

        #     item["xKey"] = v.get("xKey","")
        #     item["yKey"] = v.get("yKey","")
        #     item["data"] = v.get("data",[])

        if vtype in ("bar_chart","line_chart"):

            item["xKey"] = v.get("xKey","")
            item["yKey"] = v.get("yKey","")
            item["seriesKey"] = v.get("seriesKey","")
            item["data"] = v.get("data",[])

        elif vtype == "pie_chart":

            item["data"] = v.get("data",[])

        elif vtype == "table":

            item["columns"] = v.get("columns",[])
            item["data"] = v.get("data",[])

        normalized.append(item)

    return normalized

def _safe_visualizations(vizs):

    safe = []

    for v in vizs:

        if not isinstance(v, dict):
            continue

        if not v.get("type"):
            continue

        if not v.get("title"):
            continue

        safe.append(v)

    return safe


def _to_str(val):
    if isinstance(val, str): return val
    if isinstance(val, dict):
        lines = []
        for k, v in val.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                for item in v:
                    if isinstance(item, dict):
                        lines.append("  • " + " | ".join(f"{ik}: {iv}" for ik, iv in item.items()))
                    else:
                        lines.append(f"  • {item}")
            else:
                lines.append(f"{k}: {v}")
        return "\n".join(lines)
    if isinstance(val, list):
        lines = []
        for item in val:
            if isinstance(item, dict):
                lines.append("• " + " | ".join(f"{k}: {v}" for k, v in item.items()))
            else:
                lines.append(f"• {item}")
        return "\n".join(lines)
    return str(val) if val else ""


SYS = """You are a senior data analyst and database expert with deep analytical reasoning capabilities.
You have access to the user's actual database records as retrieved chunks.

Chunk types:
  [SCHEMA]           — table structure, column names, total row count
  [COUNT]            — exact row counts AND all distinct values per column — PRIMARY source for counts/lists
  [ROW]              — individual database records with all field values
  [JOIN]             — pre-computed cross-table joins: user X has N records in table Y with details
  [WEB]              — saved web content (raw)
  [ANALYSIS_WEB]     — web research grouped by topic with titles and summaries
  [ANALYSIS_DB_META] — database metadata: which databases and tables were analyzed

DEEP ANALYSIS RULES:
1. Read EVERY chunk exhaustively before forming your answer.
2. For COUNT questions: find [COUNT] chunk with "Number of X: N" — this is authoritative.
3. For LIST questions: find [COUNT] chunk "All values of column_name:" — gives complete list.
4. For JOIN/relationship questions: find [JOIN] chunks — they show cross-table activity per user.
5. For WHY questions: analyze patterns, dates, sequences, frequencies across chunks to infer reasons.
6. For TREND questions: compare timestamps, sequences, values across [ROW] chunks.
7. For COMPARISON questions: pull data from multiple tables and compare side by side.
8. For DEEP questions: combine ROW + JOIN + COUNT chunks to give comprehensive multi-part answers.
9. CRITICAL: If the requested data (e.g. specific columns or metrics) does NOT exist in the context, clearly state that it is unavailable. NEVER hallucinate or invent fake names, metrics, or records.
10. Always answer in full sentences with specifics — no vague responses.
11. DO NOT include source citations in the answer text — keep answer clean.
12. follow_up_questions MUST follow the EXACT format specified in the user prompt.
13. Respond ONLY in valid JSON."""


# ══════════════════════════════════════════════════════
# MAIN CONTROLLER
# ══════════════════════════════════════════════════════

def session_rag_chat_controller(get_connection_func):
    data       = request.json or {}
    session_id = (data.get("session_id") or "").strip()
    question   = (data.get("question")   or "").strip()
    history    = data.get("chat_history", [])
    user_id    = data.get("user_id")
    visit_number = data.get("visit_number")

    if not session_id:
        return jsonify({"status":"failed","statusCode":400,
                        "message":"session_id is required"}), 400

    v_raw = visit_number
    calc_new_visit = False
    if not v_raw or str(v_raw).lower() in ["new", "session_visit_new"]:
        calc_new_visit = True
        visit_number = 1
    else:
        try:
            visit_number = int(str(v_raw).replace("session_visit_", ""))
        except:
            calc_new_visit = True
            visit_number = 1

    if calc_new_visit:
        conn = cur = None
        try:
            conn = get_connection_func()
            cur  = conn.cursor(dictionary=True)
            cur.execute("""
                SELECT COALESCE(MAX(visit_number), 0) AS max_v
                FROM session_chat_history
                WHERE session_id = %s AND user_id = %s
            """, (session_id, int(user_id) if user_id else 0))
            row = cur.fetchone()
            visit_number = (row["max_v"] + 1) if row else 1
        except Exception as e:
            visit_number = 1
        finally:
            if cur: cur.close()
            if conn: conn.close()

    # Greeting
    if question and _is_greet(question):
        suggested = []
        if session_id in _CACHE:
            chunks, _, _, _ = _CACHE[session_id]
            sample = "\n".join(c["text"] for c in chunks if c["kind"] == "count")[:10000]
            res = _mistral(
                "Respond ONLY in valid JSON.",
                f"Data summary:\n{sample}\n\n"
                "Generate exactly 5 questions. Q1 starts with 'What ', Q2 starts with 'Where ', Q3 starts with 'Why '. "
                "Use natural, human-readable language. DO NOT mention internal system names, folder names, or long raw database table names (like 'd__project_backend...'). Use terms like 'the data' or 'the records' instead. "
                'Return ONLY: {"suggested_questions":["What ...?","Where ...?","Why ...?"]}'
            )
            if res: suggested = res.get("suggested_questions", [])
        return jsonify({
            "status":"success","statusCode":200,
            "answer":"Hi! I'm your advanced business intelligence assistant. I have full access to your session databases. Ask me anything about your business data!",
            "follow_up_questions": suggested,
            "visit_number": visit_number
        }), 200

    # Build/get store
    try:
        all_chunks, bm25_idx, col = _build_store(session_id, get_connection_func)
    except Exception as e:
        return jsonify({"status":"error","statusCode":500,
                        "message":f"Store error: {e}"}), 500

    if not all_chunks:
        return jsonify({"status":"no_data","statusCode":200,
                        "session_id":session_id,
                        "message":"No data found for this session."}), 200

    # Suggest / Default Report mode
    if not question or question.startswith("default_"):
        count_chunks = [c["text"] for c in all_chunks if c["kind"]=="count"]
        sample = "\n".join(count_chunks)[:15000]
        res = _mistral(SYS, f"""
Business data summary ({len(all_chunks)} total chunks):
{sample}

This is a business intelligence assistant. 
1. Write a brief "Executive Summary" (3-4 sentences) of the overall data trends.
2. Generate exactly 5 "What" critical questions about the actual business data above.
   ALL 5 questions MUST start with "What ". Focus on concerns, sudden changes, or trends.
   Use natural language. DO NOT mention internal system names or raw tables.
3. Generate a category-wise trend report as a "line_chart" visualization. Extract numeric/categorical trend values from the chunks.

Return ONLY valid JSON:
{{
  "answer": "Executive Summary: ...",
  "suggested_questions": ["What ...?", "What ...?", "What ...?", "What ...?", "What ...?"],
  "visualizations": [
    {{
      "type": "line_chart",
      "title": "Category-wise Trend Report",
      "xKey": "category",
      "yKey": "value",
      "data": [
        {{"category": "A", "value": 100}},
        {{"category": "B", "value": 200}}
      ]
    }}
  ]
}}

CRITICAL INSTRUCTIONS FOR VISUALIZATIONS:
1. The object keys inside the "data" array MUST exactly match what you specify for "xKey" and "yKey".
2. Only include categories/points that ACTUALLY EXIST in the data. Do NOT invent missing categories with 0 values.
""")
        if not res:
            return jsonify({"status":"error","statusCode":500,"message":"LLM failed"}), 500
            
        viz = res.get("visualizations", [])
        visualizations = _safe_visualizations(_normalize_visualizations(viz))

        return jsonify({
            "status":              "success",
            "statusCode":          200,
            "answer":              res.get("answer", ""),
            "suggested_questions": res.get("suggested_questions",[]),
            "visualizations":      visualizations,
            "visit_number":        visit_number
        }), 200

    # Understand + Retrieve
    understanding = _understand(question, all_chunks)
    hist          = _history(history)
    print(f"[RAG] intent={understanding['intent']} tables={understanding['table_hints']} entities={understanding['entities']}")

    # NEW ARCHITECTURE: INTENT ROUTER 
    intent = classify_intent(question)
    print(f"[RAG] Router classified intent: {intent}")
    context = ""

    if intent == "HYBRID":
        print("[RAG] HYBRID query detected! AQL/SQL First Then RAG...")
        schema_chunks = [c["text"] for c in all_chunks if c["kind"] in ("schema", "count")]
        schema_context = "\n".join(schema_chunks)
        # 1. AQL First: run execute_hybrid to get specific entity filter
        hybrid_entities = execute_hybrid(question, get_connection_func, schema_context)
        if hybrid_entities:
            print(f"[RAG] Hybrid found targeted entities: {hybrid_entities[:10]}")
            # Inject these entities so Vector Search focuses heavily on them
            understanding["entities"].extend(hybrid_entities)
            
        # 2. Then RAG
        context = _retrieve(all_chunks, bm25_idx, col, question, understanding)

    elif intent == "INSIGHT":
        print("[RAG] INSIGHT query detected! Standard RAG...")
        context = _retrieve(all_chunks, bm25_idx, col, question, understanding)

    # ─────────────────────────────────────────────
    # TEXT-TO-SQL (Bypass VectorDB for aggregations)
    # ─────────────────────────────────────────────
    if intent == "AGGREGATION":
        print(" Bypassing VectorDB. Routing to Structured Database (SQL/AQL)...")
        schema_chunks = [c["text"] for c in all_chunks if c["kind"] in ("schema", "count")]
        schema_context = "\n".join(schema_chunks)

        # ─────────────────────────────────────────────
        # 1. CANONICALIZATION STEP
        # ─────────────────────────────────────────────
        canon_sys = """You are a Query Canonicalizer for Business Intelligence.
Convert the user's natural language question into a structured JSON representation (Canonical Query).
Do not generate SQL yet. Extract the core analytical components.

Return ONLY a JSON object in this format:
{
  "analytical_intent": "e.g., dealer_ranking, sales_trend, total_revenue",
  "metric": "e.g., sales, volume, discount",
  "aggregation": "e.g., sum, count, avg",
  "sort": "e.g., desc, asc",
  "limit": 5
}
If a component is missing from the user's question, set it to null.
"""
        canon_json = _mistral(canon_sys, f"Natural Language Question: {question}", temperature=0.0)
        canonical_query_str = json.dumps(canon_json, indent=2) if canon_json else f'{{"raw_question": "{question}"}}'
        print(f"[CANONICAL_QUERY] {canonical_query_str}")

        # ─────────────────────────────────────────────
        # 2. SQL GENERATION STEP
        # ─────────────────────────────────────────────
        sql_sys = """You are a Senior Data Analyst, SQL Expert, and Business Intelligence Assistant.

PRIMARY OBJECTIVE

Generate SQL that computes answers from the FULL DATASET.

BUSINESS DEFINITIONS
- Dealer = Customer
- Sales = SUM(invoice_value)
- Revenue = SUM(invoice_value)
- Volume = SUM(qty)
- Net Sales = SUM(invoice_value) - SUM(total_discount)
- Invoice Count = COUNT(DISTINCT invoice_number)
- Product = Material
- Product Category = the `CATEGORY` column (join product on invoice.Material = product.Material)
- "category-wise" / "by category" / "product category wise" / "per category" => GROUP BY `CATEGORY`, NOT Material
- "product-wise" / "by product" => GROUP BY Material
- Top Dealer = Dealer ranked by Sales descending
- Worst Dealer = Dealer ranked by Sales ascending
- Best Performing Dealer = Dealer ranked by Sales descending
- Lowest Performing Dealer = Dealer ranked by Sales ascending
- Top Product = Product ranked by Sales descending
- Worst Product = Product ranked by Sales ascending
- Region Performance = SUM(invoice_value) grouped by region
- Zone Performance = SUM(invoice_value) grouped by zone
- Average Realization = SUM(invoice_value) / NULLIF(SUM(qty),0)

METRIC PRIORITY
- Whenever user asks: "Top Dealer", "Best Dealer", "Leading Dealer" -> Use: SUM(invoice_value)
- Whenever user asks: "Worst Dealer", "Lowest Dealer", "Poor Performing Dealer" -> Use: SUM(invoice_value)
- Never use: qty, taxable_value, gst, discount unless explicitly requested.

DATA RELIABILITY RULES

1. Use schema information only to identify:

   * tables
   * columns
   * relationships

2. Never use example values, retrieved rows, vector chunks, sample records, or context snippets to calculate business results.

3. Every ranking, trend, comparison, aggregation, KPI, sales metric, customer metric, dealer metric, category metric, region metric, and performance metric MUST be computed using SQL.

4. For Top N or Bottom N questions:

Return ONLY the ranking result unless the user explicitly asks for:
- monthwise analysis
- trend analysis
- yearly analysis
- time series analysis

Do not add monthly, yearly, trend, or detailed breakdowns unless explicitly requested.

5. For monthwise analysis:
   Use the actual date column and aggregate by month before ranking.

6. Never generate SQL that ranks monthly rows directly using:
   LIMIT N after GROUP BY month.

7. If the question asks for Top N entities (e.g., dealers, customers) month-wise or trend:
   NEVER use `IN (SELECT ... LIMIT N)` because MySQL does not support LIMIT inside IN subqueries.
   Instead, you MUST use a JOIN with a derived table:
   
   SELECT t.entity, DATE_FORMAT(STR_TO_DATE(t.date_col, '%Y-%m-%d'), '%Y-%m') as month, SUM(t.metric) as total_sales
   FROM `table` t
   JOIN (
       SELECT entity FROM `table`
       GROUP BY entity
       ORDER BY SUM(metric) DESC
       LIMIT 2
   ) as top_entities ON t.entity = top_entities.entity
   GROUP BY t.entity, month
   ORDER BY top_entities.total_sales DESC, month;
   
   Adjust the DATE_FORMAT and STR_TO_DATE depending on the actual date format in the table.

8. Use:
   SUM()
   COUNT()
   AVG()
   MIN()
   MAX()
   GROUP BY
   ORDER BY
   HAVING

9. If SQL execution is possible:
   SQL results are always more authoritative than retrieved context.

10. Never estimate.

11. Never infer missing values.

12. Never hallucinate business results.

13. PRESERVE EXACT DECIMALS: Never round monetary values in SQL unless explicitly asked. Return the exact sum with decimals intact.

COLUMN HYGIENE
- All numeric columns (sales, invoice_value, quantity, discount, tax) are strictly typed as DECIMAL or BIGINT in the database.
- DO NOT use CAST or REGEXP_REPLACE or REPLACE to clean numeric columns. Just use SUM(`col`).
- ONLY format strings if the column is explicitly a string format, but numeric columns are already typed.

PER-GROUP TOP-N — "CATEGORY-WISE", "PER", "EACH", "BY X", "X-WISE"

- "Top N customers per category", "category wise top N", "best N per region",
  "top N dealers for each zone" all mean: rank WITHIN each group and keep N rows
  from EVERY group. NEVER answer these with a single global ORDER BY ... LIMIT N
  (that returns only the N biggest pairs overall, not N per group).
- Use a window function partitioned by the group:
      WITH agg AS (
        SELECT `<group_col>` AS grp, `<entity_col>` AS entity,
               SUM(`<value_col>`) AS metric
        FROM `<fact>` JOIN `<dim>` ON ...
        GROUP BY `<group_col>`, `<entity_col>`
      ),
      ranked AS (
        SELECT grp, entity, metric,
               ROW_NUMBER() OVER (PARTITION BY grp ORDER BY metric DESC) AS rn
        FROM agg
      )
      SELECT grp, entity, metric FROM ranked WHERE rn <= N
      ORDER BY grp, metric DESC;
- Use a single global ORDER BY ... LIMIT N ONLY when the question has NO
  per-group qualifier (plain "top N customers").

PLAIN TOP-N vs WINDOWED TOP-N
- A plain "top N" / "worst N" with NO per-group qualifier needs only
  `... GROUP BY entity ORDER BY metric DESC LIMIT N`. Do NOT use a window
  function or CTE for it — that adds a needless alias that often breaks.
- Use the window-function pattern ONLY for per-group ("X-wise") questions.

RESERVED WORDS — NEVER USE AS ALIASES
- `RANK`, `ROW_NUMBER`, `ORDER`, `GROUP`, `DESC`, `ASC`, `ROWS`, `RANGE`,
  `COUNT`, `SUM`, `OVER`, `PARTITION`, `DENSE_RANK`, `LAG`, `LEAD` are reserved
  in MySQL 8.0 and will cause error 1064 if used as a column alias.
- Name the row-number column `rn` (never `rank`). Backtick EVERY alias and
  identifier without exception.
DETERMINISTIC ORDERING — MANDATORY TIE-BREAKER
- Many entities can tie on the same total (e.g. several customers at 0 sales).
  ORDER BY the metric alone returns boundary rows in arbitrary order.
- EVERY ranking ORDER BY must append the entity key as a tie-breaker:
      ORDER BY total_sales DESC, `customer` ASC   -- top N
      ORDER BY total_sales ASC,  `customer` ASC   -- worst N
- Same inside windows: ROW_NUMBER() OVER (PARTITION BY grp ORDER BY metric DESC, `entity` ASC)

DIALECT RULES

1. You MUST use valid MySQL syntax.
2. Do NOT use PostgreSQL functions like DATE_TRUNC.
3. For monthly grouping in MySQL, if the date is a string (e.g. 'DD-MM-YYYY'), parse it using STR_TO_DATE(date_col, '%d-%m-%Y') before grouping with DATE_FORMAT(..., '%Y-%m').
4. ALWAYS use backticks ` for table and column names.

OUTPUT RULES

Return ONLY valid JSON:

{
"db": "",
"sql": "",
"reasoning": ""
}

"""
        sql_user = f"Schemas available:\n{schema_context}\n\nOriginal Question: {question}\n\nCanonical Query (Structured Intent):\n{canonical_query_str}"
        sql_json = _mistral(sql_sys, sql_user, temperature=0.0)

        # Track failures so we never fall through to an empty-context LLM answer.
        agg_sql_error = None
        sql_results = []

        if sql_json and sql_json.get("sql"):
            target_db = sql_json.get("db", "").strip()
            sql_query = sql_json.get("sql", "").strip()
            print(f"[SQL_GEN] db: {target_db} | sql: {sql_query}")

            conn_sql = cur_sql = None
            sql_results = []
            try:
                # Determine connection
                if not target_db:
                    conn_sql = get_connection_func()
                    cur_sql = conn_sql.cursor(dictionary=True)
                else:
                    try:
                        conn_sql = mysql.connector.connect(
                            host=MYSQL_CONFIG["host"], port=MYSQL_CONFIG["port"],
                            user=MYSQL_CONFIG["user"], password=MYSQL_CONFIG["password"],
                            database=target_db, connection_timeout=10)
                        cur_sql = conn_sql.cursor(dictionary=True)
                    except Exception as e:
                        print(f"[SQL_GEN] MySQL failed, trying Postgres: {e}")
                        if PSYCOPG2_AVAILABLE:
                            temp_conn = get_connection_func()
                            temp_cur = temp_conn.cursor(dictionary=True)
                            temp_cur.execute("SELECT credential FROM database_credential WHERE session_id=%s AND db_type IN ('postgresql', 'postgres')", (session_id,))
                            pg_rows = temp_cur.fetchall()
                            temp_cur.close()
                            temp_conn.close()
                            
                            for r in pg_rows:
                                cred = json.loads(r["credential"]) if isinstance(r["credential"], str) else r["credential"]
                                if cred.get("database") == target_db:
                                    conn_sql = psycopg2.connect(
                                        host=cred.get("host"), port=cred.get("port", 5432),
                                        user=cred.get("username"), password=cred.get("password"),
                                        dbname=target_db, connect_timeout=10)
                                    cur_sql = conn_sql.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                                    break
                
                if cur_sql:
                    for _attempt in range(2):
                        try:
                            cur_sql.execute(sql_query)
                            rows = cur_sql.fetchall()
                            sql_results = [dict(r) for r in rows]

                            # Convert non-serializable objects to string
                            for row in sql_results:
                                for k, v in row.items():
                                    if v is not None and not isinstance(v, (str, int, float, bool)):
                                        row[k] = str(v)

                            agg_sql_error = None
                            print(f"[SQL_EXEC] Success! Returned {len(sql_results)} rows.")
                            break
                        except Exception as ex:
                            agg_sql_error = str(ex)
                            print(f"[SQL_EXEC] Attempt {_attempt + 1} failed: {ex}")
                            if _attempt == 1:
                                break
                            # Self-heal: send the error back to the model once.
                            repair_user = (
                                f"The following MySQL query FAILED. Fix it and return the same JSON shape.\n\n"
                                f"SQL:\n{sql_query}\n\nMySQL error:\n{ex}\n\n"
                                f"Common fixes: a reserved word is used as an alias (rank, order, group, "
                                f"desc, asc, count, sum, rows, range) — rename the row-number alias to `rn` "
                                f"and backtick every identifier; verify MySQL 8.0 window syntax; keep the "
                                f"follow the COLUMN HYGIENE rule in the system prompt for numeric columns.\n\n"
                                f"Schemas:\n{schema_context}\n\nOriginal Question: {question}"
                            )
                            fix_json = _mistral(sql_sys, repair_user, temperature=0.0)
                            if fix_json and fix_json.get("sql"):
                                sql_query = fix_json.get("sql", "").strip()
                                print(f"[SQL_REPAIR] Retrying with corrected SQL:\n{sql_query}")
                            else:
                                break
            except Exception as e:
                agg_sql_error = str(e)
                print(f"[SQL_EXEC] Execution failed: {e}")
            finally:
                if cur_sql: 
                    try: cur_sql.close() 
                    except: pass
                if conn_sql: 
                    try: conn_sql.close() 
                    except: pass

            if sql_results:
                # Override context with SQL results for final LLM generation
                context = f"SQL Query executed: {sql_query}\n\nSQL Results:\n" + json.dumps(sql_results, indent=2)

        # AGGREGATION fail-safe: if no SQL rows were produced, do NOT let the
        # model answer from an empty/stale context (that caused fabricated,
        # inconsistent numbers). Constrain it to an honest "could not compute".
        if intent == "AGGREGATION" and not sql_results:
            _detail = f" (error: {agg_sql_error})" if agg_sql_error else ""
            print(f"[AGGREGATION] No SQL rows — refusing to fabricate{_detail}")
            context = (
                "SQL_COMPUTATION_FAILED. The structured query returned no rows"
                f"{_detail}. You MUST NOT fabricate, estimate, infer, or guess "
                "any numbers, names, totals, or rankings. Reply that the result "
                "could not be computed from the database for this question and "
                "suggest the user rephrase or retry."
            )

    # Graph
    if _is_graph(question):
        ftype        = _next_followup_type(session_id)
        followup_ins = _followup_instruction(ftype)
        res = _mistral(SYS, f"""
Retrieved business data:
{context}

{hist}Chart request: "{question}"

Extract actual numeric/categorical values ONLY from the data above.
--- TREND DETECTION & LINE CHART RULES (MANDATORY CONTRACT) ---
If the question is trend-related (contains: trend, growth, decline, increase, decrease, over time, monthly, quarterly, yearly, seasonality, pattern, historical analysis, performance over time, month-on-month, MoM, YoY):
1. Visualization Type MUST be Line Chart ("type": "line_chart").
2. X-Axis (xKey) MUST be a Date/Month/Year field. IMPORTANT: Date values MUST be aggregated and formatted by month (e.g., 'Jan 2024' or 'January') on the X-Axis.
3. Y-Axis (yKey) MUST be a Numeric Measure.
4. MUST include "seriesKey": "series" at the visualization root level.
5. NEVER return multiple category fields like "category": "Tube", "construction": "RADIAL" separately for a line chart. Instead, combine them into a single "series" key.
   - Example (CATEGORY + CONSTRUCTION): "series": "Tube - RADIAL"
   - Example (CATEGORY + CONSTRUCTION + TYRE TYPE): "series": "Tyre - RADIAL - Truck"
   - Example (TYRE TYPE ONLY): "series": "Truck"
6. NEVER use Pie Chart or Table as primary visualization for trend queries.
7. NEVER auto-detect legend. Always use seriesKey.
8. Every row in "data" MUST contain the exact key "series" (matching seriesKey) and the xKey and yKey.
9. CRITICAL: For any time-series data or trend charts, the items inside the "data" array MUST be sorted strictly in chronological order (e.g., Jan, Feb, Mar or April, May, June) so the graph renders correctly from left to right.
9. For every line chart row:

REQUIRED FORMAT:

{{
  "month": "...",
  "invoice_value": 123,
  "series": "..."
}}

10. NEVER use keys like:

category
category_construction
category_type
group
legend

Use ONLY:

series

11. If CATEGORY + CONSTRUCTION + TYRE TYPE exists:

series =
CATEGORY + " - " + CONSTRUCTION + " - " + TYRE_TYPE

Example:

"Tyre - RADIAL - Truck"

12. seriesKey MUST ALWAYS be:

"series"
------------------------------------------
{followup_ins}
Return ONLY valid JSON in this format:
{{
  "answer": "A short analytical summary of the chart and trends shown.",
  "follow_up_questions": ["Question 1", "Question 2"],
  "visualizations": [
    {{
      "type": "line_chart",
      "title": "...",
      "xKey": "...",
      "yKey": "...",
      "seriesKey": "...",
      "data": [
        {{ "x_key_name": "...", "y_key_name": 123, "series": "..." }}
      ]
    }}
  ]
}}
""")
        if not res:
            return jsonify({"status":"error","statusCode":500,"message":"LLM failed"}), 500

        _advance_turn(session_id)

        fuq_raw = res.get("follow_up_questions",[])
        fuq = []
        if isinstance(fuq_raw, list):
            for q in fuq_raw:
                if isinstance(q, dict) and "question" in q:
                    fuq.append(q["question"])
                elif isinstance(q, str):
                    fuq.append(q)
                    
        visualizations = _safe_visualizations(_normalize_visualizations(res.get("visualizations", [])))

        _save_history(
            get_connection_func,
            session_id,
            user_id,
            question,
            json.dumps(res.get("datasets",[])),
            fuq,
            understanding["intent"],
            "graph",
            visualizations=visualizations,
            visit_number=visit_number
        )

        return jsonify({
            "status": "success",
            "statusCode": 200,
            "answer": res.get("answer", "Here is the visualization for your request."),
            "follow_up_questions": fuq,
            "visualizations": visualizations,
            "visit_number": visit_number
        }), 200



    # Report
    if _is_report(question):
        ftype        = _next_followup_type(session_id)
        followup_ins = _followup_instruction(ftype)
        res = _mistral(SYS, f"""
You are a senior business analyst. Write a comprehensive report from the business data below.
Retrieved data:
{context}

{hist}Report request: "{question}"

Write an analytical business report using ONLY the data above.
Be specific — use actual numbers, names, values from the data.
{followup_ins}
Return ONLY:
{{
  "report_title":"...",
  "sections":[{{"heading":"...","content":"..."}}],
  "key_findings":["Finding 1","Finding 2","Finding 3"],
  "follow_up_questions":[]
}}
""")
        if not res:
            return jsonify({"status":"error","statusCode":500,"message":"LLM failed"}), 500
        _advance_turn(session_id)
        fuq = res.get("follow_up_questions",[])
        _save_history(get_connection_func, session_id, user_id,
                      question, res.get("report_title",""), fuq, understanding["intent"], "report", visit_number=visit_number)
        return jsonify({
            "status":     "success",
            "statusCode": 200,
            "report": {
                "title":        res.get("report_title",""),
                "sections":     res.get("sections",[]),
                "key_findings": res.get("key_findings",[])
            },
            "follow_up_questions": fuq,
            "visit_number": visit_number
        }), 200

    # Answer
    ftype        = _next_followup_type(session_id)
    followup_ins = _followup_instruction(ftype)

    # Detect multi-part questions and add explicit instruction
    q_parts = [p.strip() for p in re.split(r'[?]\s+(?=[A-WY-Z])', question) if len(p.strip()) > 8]
    multi_hint = (
        f"\nNOTE: This question has {len(q_parts)} parts. Address EACH part with a clear numbered heading."
        if len(q_parts) > 1 else ""
    )

    res = _mistral(SYS, f"""
You are an advanced business intelligence AI — like Claude or GPT — specialized in analyzing actual business database records.
This is NOT a general chatbot. Every answer must be grounded in the business data provided below.

Retrieved data (read ALL carefully):
{context}

{hist}Business Question: "{question}"

Detected intent: {understanding['intent']}
Relevant tables: {understanding['table_hints']}

{multi_hint}
DEEP ANALYSIS PROTOCOL:

1. Exhaustively scan every piece of data.

2. If SQL execution results are present, SQL Results are the ONLY source of truth.

3. If SQL Results are present:

   * Use only the rows and columns returned by SQL.
   * Do not invent additional fields.
   * Do not invent customer names.
   * Do not invent dealer names.
   * Do not invent dates.
   * Do not invent transaction counts.
   * Do not invent averages.
   * Do not invent percentages.
   * Do not invent churn risk.
   * Do not invent engagement metrics.
   * Do not invent business explanations.

4. Never infer reasons, causes, operational issues, market conditions, pricing issues, supply chain issues, customer behavior, customer intent, customer satisfaction, loyalty, churn risk, promotional response, business strategy, or recommendations unless those values explicitly exist in the SQL result.

5. If SQL returns:

   * customer
   * invoice_value
   * qty

Then answer only from those fields.

6. If a field is not present in SQL Results, state that the information is not available.

7. Never convert customer IDs into names unless SQL explicitly returns a name column.

8. Never create fictional examples such as:

   * John Smith
   * Emily Davis
   * Customer 1003
   * Customer 1005
     or any other names not present in SQL results.

9. Never create:

   * last purchase date
   * average transaction value
   * engagement score
   * churn probability
   * campaign response
   * inactivity period
     unless explicitly returned by SQL.

10. Answer strictly from SQL Results and retrieved context.

11. Accuracy is more important than completeness.

12. If SQL Results exist, ignore any conflicting RAG content.

SQL RESULT PRIORITY RULE

When SQL Results are present:

SQL Results > Retrieved Context > General Reasoning

Always trust SQL Results.
Never override SQL Results with assumptions.

8. Do NOT include "(source:...)" tags in the answer text.
9. {followup_ins}

VISUALIZATION RULES:

If the question involves comparison, distribution, ranking, trends, or category breakdown,
generate up to 3 visualizations.

--- AGGREGATION VISUALIZATION RULES (MANDATORY CONTRACT) ---
If the question involves aggregate data:

1. Always include a Table visualization.

2. If the data contains a time dimension
   (month, date, quarter, year),
   also include a Line Chart.

3. For ranking or Top/Bottom questions without time,
   return only a Table
   (optional Bar Chart if useful).

4. Never generate a Line Chart when no time dimension exists.
--- TREND DETECTION & LINE CHART RULES (MANDATORY CONTRACT) ---
If the question is trend-related (contains: trend, growth, decline, increase, decrease, over time, monthly, quarterly, yearly, seasonality, pattern, historical analysis, performance over time, month-on-month, MoM, YoY):
1. Visualization Type MUST be Line Chart ("type": "line_chart").
2. X-Axis (xKey) MUST be a Date/Month/Year field. IMPORTANT: Date values MUST be aggregated and formatted by month (e.g., 'Jan 2024' or 'January') on the X-Axis.
3. Y-Axis (yKey) MUST be a Numeric Measure.
4. MUST include "seriesKey": "series" at the visualization root level.
5. NEVER return multiple category fields like "category": "Tube", "construction": "RADIAL" separately for a line chart. Instead, combine them into a single "series" key.
   - Example (CATEGORY + CONSTRUCTION): "series": "Tube - RADIAL"
   - Example (CATEGORY + CONSTRUCTION + TYRE TYPE): "series": "Tyre - RADIAL - Truck"
   - Example (TYRE TYPE ONLY): "series": "Truck"
6. NEVER use Pie Chart or Table as primary visualization for trend queries.
7. NEVER auto-detect legend. Always use seriesKey.
8. Every row in "data" MUST contain the exact key "series" (matching seriesKey) and the xKey and yKey.
9. CRITICAL: For any time-series data or trend charts, the items inside the "data" array MUST be sorted strictly in chronological order (e.g., Jan, Feb, Mar or April, May, June) so the graph renders correctly from left to right.
------------------------------------------

CRITICAL INSTRUCTIONS FOR ALL VISUALIZATIONS:
1. The object keys inside the "data" array MUST exactly match what you specify for "xKey" and "yKey".
2. Only include categories/points that ACTUALLY EXIST in the data. Do NOT invent missing categories with 0 values.

Supported visualization types:

1️⃣ Bar Chart

{{
"type":"bar_chart",
"title":"...",
"xKey":"...",
"yKey":"...",
"data":[
 {{"category":"A","value":100}},
 {{"category":"B","value":200}}
]
}}

2️⃣ Pie Chart

{{
"type":"pie_chart",
"title":"...",
"data":[
 {{"name":"Category A","value":120}},
 {{"name":"Category B","value":80}}
]
}}

3️⃣ Table

{{
"type":"table",
"title":"...",
"columns":[
 {{"key":"columnKey","label":"Column Label"}}
],
"data":[
 {{"columnKey":"value"}}
]
}}

Return ALL visualizations inside the "visualizations" array.
You may return multiple charts or tables if useful.




Return ONLY valid JSON (answer must be a plain text string):
{{"answer":"...","follow_up_questions":[], "visualizations":[]}}
""")

    if not res:
        return jsonify({"status":"error","statusCode":500,"message":"LLM failed"}), 500

    clean_answer = _to_str(res.get("answer",""))
    clean_answer = re.sub(r'\s*\(source:[^)]*\)', '', clean_answer).strip()
    clean_answer = re.sub(r'\s*\[source:[^\]]*\]', '', clean_answer).strip()

    fuq = res.get("follow_up_questions", [])

    visualizations = _safe_visualizations(
        _normalize_visualizations(res.get("visualizations", []))
    )

    # If user explicitly asked for table → keep only table
    if "table" in question.lower():
        visualizations = [v for v in visualizations if v.get("type") == "table"]



    _advance_turn(session_id)
    _save_history(get_connection_func, session_id, user_id,
                  question, clean_answer, fuq, understanding["intent"], "answer", visualizations=visualizations, visit_number=visit_number)

    return jsonify({
        "status": "success",
        "statusCode": 200,
        "answer": clean_answer,
        "follow_up_questions": fuq,
        "visualizations": visualizations,
        "visit_number": visit_number
    }), 200