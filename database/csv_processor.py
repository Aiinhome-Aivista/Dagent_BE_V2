"""
csv_processor.py  —  hardened CSV → SQL ingester.

Why this rewrite exists
-----------------------
The previous version loaded every column with dtype=str, so all columns landed
in MySQL as VARCHAR. Monetary values such as "10,409.00" and "-1,518.78 INR"
were stored as text, and MySQL's SUM() on a text column coerces each string
left-to-right and STOPS at the first non-digit (the comma) — so
SUM(invoice_value) returned ~0.4% of the true total. Every ranking/aggregation
was therefore wrong and unstable.

This version:
  * detects each column's real type (numeric / integer / date / text),
  * cleans thousands separators, currency tokens (INR, RS, ₹, $, …) and
    parenthesis-negatives BEFORE casting,
  * creates the SQL table with explicit DECIMAL / BIGINT / DATE / TEXT types,
  * never silently drops rows (it reconciles row counts and warns loudly).

Drop-in replacement: same function name and signature, same return value.
"""

import re
import numpy as np
import pandas as pd
from urllib.parse import quote_plus
from sqlalchemy import create_engine
from sqlalchemy.types import DECIMAL, BigInteger, Date, Text

# ──────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────
CHUNK_SIZE          = 300_000
SAMPLE_ROWS         = 50_000          # rows used to infer column types
NUMERIC_THRESHOLD   = 0.99            # ≥99% of non-blank values parse as number (strict to protect text data)
DATE_THRESHOLD      = 0.80            # ≥80% of non-blank values parse as a date
MONEY_PRECISION     = 30              # DECIMAL(precision, scale) for numeric cols
MONEY_SCALE         = 8

# Strip these currency / unit tokens before numeric parsing.
CURRENCY_RE = re.compile(r'(?i)\b(?:INR|RS|USD|EUR|GBP|AUD|CAD|JPY)\b|[₹$€£]')

# Date formats tried in order; the one parsing the most sample values wins.
DATE_FORMATS = [
    '%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d',
    '%d-%b-%Y', '%d %b %Y', '%d-%m-%y', '%m-%d-%Y',
]

# Columns whose values are pure digits but are really identifiers (so we must
# NOT turn them into integers, e.g. to preserve leading zeros). Matches a
# sanitized column name ending in an id-ish suffix, or an exact known key.
ID_SUFFIX_RE = re.compile(r'(?:_id|_code|_no|_number|_num|_pin|_zip|_gstin|_pan)$', re.I)
ID_EXACT     = {'invoice_number'}     # add others here if needed


def _sanitize(name: str) -> str:
    """Mirror the original column/table sanitization: alnum/underscore, lower."""
    return "".join(c if c.isalnum() else "_" for c in str(name)).lower()


def _looks_like_id(col: str) -> bool:
    return col in ID_EXACT or bool(ID_SUFFIX_RE.search(col))


def _clean_numeric(series: pd.Series) -> pd.Series:
    """Return a float Series; values that cannot be parsed become NaN.

    Handles: thousands commas, currency tokens/symbols, surrounding spaces,
    and accounting negatives written as (123).
    """
    x = series.astype(str).str.strip()
    x = x.str.replace(CURRENCY_RE, '', regex=True)
    # (123)  ->  -123
    x = x.str.replace(r'^\((.*)\)$', r'-\1', regex=True)
    x = x.str.replace(',', '', regex=False)
    x = x.str.replace(r'\s+', '', regex=True)
    x = x.replace({'': np.nan, 'nan': np.nan, 'none': np.nan,
                   'None': np.nan, '-': np.nan, 'null': np.nan, 'NULL': np.nan})
    return pd.to_numeric(x, errors='coerce')


def _best_date_format(series: pd.Series):
    """Return (format, parse_ratio) for the best-matching date format, or (None, 0)."""
    nonblank = series.dropna().astype(str).str.strip()
    nonblank = nonblank[(nonblank != '') & (nonblank.str.lower() != 'nan')]
    if nonblank.empty:
        return None, 0.0
    sample = nonblank.head(2000)
    best_fmt, best_ratio = None, 0.0
    for fmt in DATE_FORMATS:
        ratio = pd.to_datetime(sample, format=fmt, errors='coerce').notna().mean()
        if ratio > best_ratio:
            best_fmt, best_ratio = fmt, float(ratio)
    return best_fmt, best_ratio


def _infer_schema(sample: pd.DataFrame) -> dict:
    """Map each (already-sanitized) column name -> dict(kind, fmt)."""
    schema = {}
    for col in sample.columns:
        col_lower = col.lower()
        nonblank = sample[col].dropna().astype(str).str.strip()
        nonblank = nonblank[(nonblank != '') & (nonblank.str.lower() != 'nan')]

        if nonblank.empty:
            schema[col] = {'kind': 'text', 'fmt': None}
            continue
                # --------------------------------------------------
        # BUSINESS COLUMN OVERRIDES (HIGHEST PRIORITY)
        # --------------------------------------------------

        if "date" in col_lower:
            schema[col] = {"kind": "date", "fmt": None}
            continue

        INT_COLUMNS = {
            "qty",
            "quantity"
        }

        DECIMAL_COLUMNS = {
            "ndp",
            "qtd",
            "invoice_value",
            "taxable_value",
            "discount",
            "total_discount",
            "claim_discount",
            "ppd",
            "acer",
            "add_on",
            "ladder_discount",
            "cgst",
            "sgst",
            "utgst",
            "igst",
            "total_gst",
            "tcs",
            "round_off",
            "fraight"
        }

        if col_lower in INT_COLUMNS:
            schema[col] = {"kind": "int", "fmt": None}
            continue

        if col_lower in DECIMAL_COLUMNS:
            schema[col] = {"kind": "numeric", "fmt": None}
            continue    
        # 1) date?
        fmt, date_ratio = _best_date_format(nonblank)

        # 2) numeric?
        num = _clean_numeric(nonblank)
        num_ratio = float(num.notna().mean())

        if date_ratio >= DATE_THRESHOLD and date_ratio >= num_ratio:
            schema[col] = {'kind': 'date', 'fmt': fmt}
        elif num_ratio >= NUMERIC_THRESHOLD and not _looks_like_id(col):
            vals = num.dropna()
            is_int = (not vals.empty
                      and np.all(vals == np.floor(vals))
                      and vals.abs().max() < 9.0e18)
            schema[col] = {'kind': 'int' if is_int else 'numeric', 'fmt': None}
        else:
            schema[col] = {'kind': 'text', 'fmt': None}
    return schema


def _sqlalchemy_dtype(schema: dict) -> dict:
    out = {}
    for col, spec in schema.items():
        k = spec['kind']
        if k == 'numeric':
            out[col] = DECIMAL(MONEY_PRECISION, MONEY_SCALE)
        elif k == 'int':
            out[col] = BigInteger()
        elif k == 'date':
            out[col] = Date()
        else:
            out[col] = Text()
    return out


def _apply_schema(chunk: pd.DataFrame, schema: dict) -> pd.DataFrame:
    """Transform a raw (string) chunk into typed values according to schema."""
    for col, spec in schema.items():
        if col not in chunk.columns:
            continue
        k = spec['kind']
        if k in ('numeric', 'int'):
            chunk[col] = _clean_numeric(chunk[col])
            if k == 'int':
                # nullable integer so NaN survives as NULL
                chunk[col] = chunk[col].round().astype('Int64')
        elif k == 'date':
            # chunk[col] = pd.to_datetime(
            #     chunk[col].astype(str).str.strip(),
            #     format=spec['fmt'], errors='coerce'
            # ).dt.date
            
            if spec.get("fmt"):
                chunk[col] = pd.to_datetime(
                    chunk[col].astype(str).str.strip(),
                    format=spec["fmt"],
                    errors="coerce"
                ).dt.strftime('%Y-%m-%d')
            else:
                chunk[col] = pd.to_datetime(
                    chunk[col].astype(str).str.strip(),
                    errors="coerce",
                    dayfirst=True
                ).dt.strftime('%Y-%m-%d')
    return chunk


def _detect_encoding(path: str) -> str:
    """Cheap encoding sniff: prefer utf-8, fall back to cp1252/latin1."""
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin1'):
        try:
            with open(path, encoding=enc) as f:
                for _ in range(2000):
                    if f.readline() == '':
                        break
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return 'latin1'


def process_csv_job(file_paths, allocated_db_name, db_host, db_user, db_pass, db_port):
    safe_user = quote_plus(db_user)
    safe_pass = quote_plus(db_pass)
    base_url = f"mysql+pymysql://{safe_user}:{safe_pass}@{db_host}:{db_port}"

    target_engine = create_engine(
        f"{base_url}/{allocated_db_name}",
        pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=3600,
    )

    tables_created = []

    # [NEW] Track if any new data was inserted across all files
    any_incremental = False
    
    # [NEW] Inspector to check if tables exist and fetch their schemas for Header Matching
    from sqlalchemy import inspect, text
    inspector = inspect(target_engine)
    existing_tables = inspector.get_table_names()
    
    # Pre-fetch existing tables and their schemas to enable smart merging
    schema_map = {}
    with target_engine.connect() as conn:
        for t in existing_tables:
            cols_res = conn.execute(text(f"SHOW COLUMNS FROM `{t}`"))
            schema_map[t] = set([row[0] for row in cols_res])

    import os
    # Sort file_paths by original filename (ignoring UUID prefix) so base files come first
    file_paths.sort(key=lambda p: os.path.basename(p).split('_', 1)[-1] if '_' in os.path.basename(p) else os.path.basename(p))

    for path in file_paths:
        print(f"\n🚀 Starting processing for file: {path}")
        encoding = _detect_encoding(path)
        print(f"🔤 Encoding detected: {encoding}")

        # Total data rows (minus header) for progress + loss reconciliation.
        with open(path, encoding=encoding) as f:
            total_rows = max(sum(1 for _ in f) - 1, 0)
        print(f"📊 Total data rows detected: {total_rows}")

        raw_name = path.split("/")[-1].rsplit('.', 1)[0]
        default_table_name = _sanitize(raw_name)[:60]

        # ── Pass 1: infer schema from a sample ────────────────────────────
        sample = pd.read_csv(
            path, dtype=str, encoding=encoding, engine="python",
            on_bad_lines="warn", nrows=SAMPLE_ROWS,
        )
        sample.columns = [_sanitize(c) for c in sample.columns]
        
        # [NEW] Header Matching: Check if columns match any existing table
        df_cols_set = set(sample.columns)
        matched_table = None
        for t_name, t_cols_set in schema_map.items():
            if df_cols_set == t_cols_set:
                matched_table = t_name
                break
                
        table_name = matched_table if matched_table else default_table_name
        table_exists = matched_table is not None
        target_table_name = f"temp_{table_name}" if table_exists else table_name
        
        if table_exists and not matched_table:
            # Fallback if names match but columns didn't (unlikely in this flow, but safe)
            table_exists = table_name in existing_tables
            target_table_name = f"temp_{table_name}" if table_exists else table_name
        schema = _infer_schema(sample)
        sa_dtype = _sqlalchemy_dtype(schema)
        print("🧬 Inferred column types:")
        for c, s in schema.items():
            extra = f" [{s['fmt']}]" if s['fmt'] else ""
            print(f"     {c:<24} -> {s['kind']}{extra}")

        # ── Pass 2: stream the full file, typed, into SQL ─────────────────
        first_chunk = True
        processed_rows = 0
        for chunk in pd.read_csv(
            path, chunksize=CHUNK_SIZE, dtype=str, encoding=encoding,
            engine="python", on_bad_lines="warn",
        ):
            chunk.columns = [_sanitize(c) for c in chunk.columns]
            chunk = _apply_schema(chunk, schema)
            processed_rows += len(chunk)

            pct = (processed_rows / total_rows * 100) if total_rows else 100.0
            print(f"[PROGRESS] {table_name} → {pct:6.2f}% "
                  f"({processed_rows}/{total_rows} rows)")

            # [MODIFIED] Write to target_table_name (temp table if exists, else main table)
            chunk.to_sql(
                target_table_name, target_engine,
                if_exists='replace' if first_chunk else 'append',
                index=False, method='multi', chunksize=1000,
                dtype=sa_dtype,
            )
            first_chunk = False

        # Loud reconciliation — never lose rows silently.
        if processed_rows != total_rows:
            print(f"⚠️  ROW COUNT MISMATCH for {table_name}: "
                  f"loaded {processed_rows} of {total_rows} "
                  f"({total_rows - processed_rows} unparsed). "
                  f"Check the CSV for malformed lines.")

        # [NEW] If table existed, we wrote to a temp table. Now merge incrementally using SQL.
        if table_exists:
            with target_engine.begin() as conn:
                # Build join conditions for duplicate checking
                columns = [f"`{c}`" for c in sample.columns]
                join_conds = " AND ".join([f"`{table_name}`.{c} <=> `{target_table_name}`.{c}" for c in columns])
                
                cols_str = ", ".join(columns)
                merge_sql = f"""
                    INSERT INTO `{table_name}` ({cols_str})
                    SELECT {cols_str} FROM `{target_table_name}`
                    WHERE NOT EXISTS (
                        SELECT 1 FROM `{table_name}`
                        WHERE {join_conds}
                    )
                """
                result = conn.execute(text(merge_sql))
                inserted_rows = result.rowcount
                print(f"🔄 Incremental Merge: Inserted {inserted_rows} new rows into {table_name}")
                
                if inserted_rows > 0:
                    any_incremental = True
                
                # Note: pandas to_sql creates a regular table. Drop it after merge.
                conn.execute(text(f"DROP TABLE IF EXISTS `{target_table_name}`"))
        else:
            # New table created
            any_incremental = True

        tables_created.append(table_name)
        print(f"✅ Finished loading table: {table_name} ({processed_rows} rows)")

    print("\n🎉 All files processed successfully!")
    # ──────────────────────────────────────────────────────────────
    # KNOWLEDGE GRAPH BUILDER TRIGGER
    # ──────────────────────────────────────────────────────────────
    try:
        from database.kgraph_builder import build_kgraph
        # [MODIFIED] Pass force=any_incremental to avoid useless rebuilds
        build_kgraph(allocated_db_name, db_host, db_user, db_pass, db_port, force=any_incremental)
    except Exception as e:
        print(f"[KGRAPH] post-CSV build skipped: {e}")
    return tables_created
