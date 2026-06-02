"""
etl_pipeline.py
---------------
Metals Risk Dashboard — End-to-End ETL Pipeline

Extracts CSV files → Validates schema & data quality →
Transforms (type coercion, cleaning, derived fields) →
Loads into SQLite database → Logs every run with row counts & errors

Replaces manual Excel refreshes (FR-01 through FR-06 in BRD).

Usage:
    # Full pipeline — all four tables
    python python/etl_pipeline.py

    # Custom paths
    python python/etl_pipeline.py --data-dir data --db metals.db

    # Single table only
    python python/etl_pipeline.py --table trades

    # Dry run (validate only, no DB writes)
    python python/etl_pipeline.py --dry-run

    # Full reset (drop and recreate all tables)
    python python/etl_pipeline.py --reset
"""

import argparse
import csv
import json
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging setup — structured log lines for audit trail (NFR-05)
# ---------------------------------------------------------------------------

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("etl_pipeline.log", mode="a"),
    ],
)
log = logging.getLogger("etl.main")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SYMBOLS   = {"XAU","XAG","XPT","XPD","HG","AL","ZN","NI"}
VALID_STATUSES  = {"Confirmed","Pending","Settled","Cancelled"}
VALID_BUY_SELL  = {"Buy","Sell"}
VALID_DESKS     = {"Precious Metals","Base Metals"}
VALID_TRADE_TYPES = {"Spot","Forward","Option","Swap"}
VALID_LONG_SHORT  = {"Long","Short","Flat"}

DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"]

# Schema: (col_name, py_type, nullable, validator_fn_name)
# Used for validation AND transform steps
SCHEMAS = {
    "trades": [
        ("trade_id",        str,   False, "nonempty"),
        ("trade_date",      str,   False, "is_date"),
        ("settlement_date", str,   False, "is_date"),
        ("metal",           str,   False, "nonempty"),
        ("symbol",          str,   False, "valid_symbol"),
        ("desk",            str,   False, "valid_desk"),
        ("book",            str,   False, "nonempty"),
        ("trader",          str,   True,  None),
        ("counterparty",    str,   True,  None),
        ("buy_sell",        str,   False, "valid_buy_sell"),
        ("trade_type",      str,   True,  "valid_trade_type"),
        ("quantity",        float, False, "positive_number"),
        ("unit",            str,   True,  None),
        ("trade_price",     float, False, "positive_number"),
        ("spot_at_trade",   float, True,  None),
        ("currency",        str,   True,  None),
        ("notional_usd",    float, True,  None),
        ("status",          str,   False, "valid_status"),
    ],
    "price_history": [
        ("price_date",  str,   False, "is_date"),
        ("metal",       str,   False, "nonempty"),
        ("symbol",      str,   False, "valid_symbol"),
        ("spot_price",  float, False, "positive_number"),
        ("currency",    str,   True,  None),
        ("unit",        str,   True,  None),
        ("source",      str,   True,  None),
    ],
    "positions": [
        ("as_of_date",     str,   False, "is_date"),
        ("book",           str,   False, "nonempty"),
        ("desk",           str,   False, "valid_desk"),
        ("metal",          str,   False, "nonempty"),
        ("symbol",         str,   False, "valid_symbol"),
        ("net_quantity",   float, False, None),
        ("unit",           str,   True,  None),
        ("avg_cost_usd",   float, True,  None),
        ("total_cost_usd", float, True,  None),
        ("trade_count",    int,   True,  None),
        ("long_short",     str,   False, "valid_long_short"),
    ],
    "pnl_daily": [
        ("pnl_date",       str,   False, "is_date"),
        ("book",           str,   False, "nonempty"),
        ("desk",           str,   True,  None),
        ("metal",          str,   False, "nonempty"),
        ("symbol",         str,   False, "valid_symbol"),
        ("net_quantity",   float, True,  None),
        ("unit",           str,   True,  None),
        ("spot_price_usd", float, True,  None),
        ("mtm_value_usd",  float, True,  None),
        ("cost_basis_usd", float, True,  None),
        ("unrealised_pnl", float, True,  None),
        ("pnl_pct",        float, True,  None),
        ("long_short",     str,   True,  None),
    ],
}

# CSV filename → DB table name
CSV_TABLE_MAP = {
    "trades.csv":        "trades",
    "price_history.csv": "price_history",
    "positions.csv":     "positions",
    "pnl_summary.csv":   "pnl_daily",
}


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def parse_date(value: str) -> str | None:
    """Try multiple date formats, return ISO string or None."""
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def is_date(value: str) -> bool:
    return parse_date(value) is not None

def nonempty(value: str) -> bool:
    return bool(value and str(value).strip())

def valid_symbol(value: str) -> bool:
    return str(value).strip().upper() in VALID_SYMBOLS

def valid_status(value: str) -> bool:
    return str(value).strip() in VALID_STATUSES

def valid_buy_sell(value: str) -> bool:
    return str(value).strip() in VALID_BUY_SELL

def valid_desk(value: str) -> bool:
    return str(value).strip() in VALID_DESKS

def valid_trade_type(value: str) -> bool:
    return str(value).strip() in VALID_TRADE_TYPES

def valid_long_short(value: str) -> bool:
    return str(value).strip() in VALID_LONG_SHORT

def positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False

VALIDATOR_MAP = {
    "nonempty":        nonempty,
    "is_date":         is_date,
    "valid_symbol":    valid_symbol,
    "valid_status":    valid_status,
    "valid_buy_sell":  valid_buy_sell,
    "valid_desk":      valid_desk,
    "valid_trade_type":valid_trade_type,
    "valid_long_short":valid_long_short,
    "positive_number": positive_number,
}


# ---------------------------------------------------------------------------
# Transform helpers
# ---------------------------------------------------------------------------

def coerce_value(value: str, py_type: type, nullable: bool) -> Any:
    """
    Cast string → target Python type.
    Returns None for empty strings if nullable.
    Raises ValueError on bad cast if not nullable.
    """
    stripped = str(value).strip() if value is not None else ""

    if stripped == "":
        if nullable:
            return None
        raise ValueError(f"Required field is empty")

    if py_type == str:
        return stripped

    if py_type == float:
        try:
            # Handle comma-formatted numbers: "1,234.56" → 1234.56
            return float(stripped.replace(",", ""))
        except ValueError:
            raise ValueError(f"Cannot convert '{stripped}' to float")

    if py_type == int:
        try:
            return int(float(stripped))
        except ValueError:
            raise ValueError(f"Cannot convert '{stripped}' to int")

    return stripped


def transform_row(row: dict, schema: list, table: str) -> dict:
    """
    Apply type coercion + field-level transforms to a raw CSV row.
    Returns transformed dict.
    """
    out = {}

    # Map CSV column names → schema (handles minor header variations)
    # e.g. 'book' in CSV maps to 'book_id' in DB for some tables
    col_remap = {
        "book":     "book_id"   if table in ("positions",)   else "book",
        "book_id":  "book_id",
    }

    for col_name, py_type, nullable, _ in schema:
        # Find value from raw row (try exact name first, then remapped)
        raw_val = row.get(col_name)
        if raw_val is None:
            # Try alternate column names from the CSV
            alternates = {v: k for k, v in col_remap.items()}
            alt = alternates.get(col_name)
            if alt:
                raw_val = row.get(alt)

        # Type coercion
        try:
            coerced = coerce_value(raw_val, py_type, nullable)
        except ValueError as e:
            raise ValueError(f"Column '{col_name}': {e}")

        # Date normalisation
        if py_type == str and col_name.endswith("_date") and coerced:
            normalised = parse_date(coerced)
            if normalised:
                coerced = normalised

        # Strip & uppercase symbol
        if col_name == "symbol" and coerced:
            coerced = coerced.upper()

        out[col_name] = coerced

    # Derived fields for trades table
    if table == "trades":
        # Recalculate notional if missing
        if out.get("notional_usd") is None:
            qty   = out.get("quantity")
            price = out.get("trade_price")
            if qty and price:
                out["notional_usd"] = round(qty * price, 2)

    return out


# ---------------------------------------------------------------------------
# Validation pass
# ---------------------------------------------------------------------------

class ValidationResult:
    def __init__(self):
        self.valid_rows:    list[dict] = []
        self.rejected_rows: list[dict] = []
        self.warnings:      list[str]  = []
        self.errors:        list[str]  = []

    @property
    def rejection_rate(self) -> float:
        total = len(self.valid_rows) + len(self.rejected_rows)
        return len(self.rejected_rows) / total if total else 0.0


def validate_rows(raw_rows: list[dict], schema: list, table: str) -> ValidationResult:
    """
    Validate a list of raw CSV dicts against the schema.
    Returns ValidationResult with valid/rejected buckets.
    """
    result = ValidationResult()
    seen_pks: set = set()

    pk_col = {
        "trades":        "trade_id",
        "price_history": None,          # composite key checked below
        "positions":     None,
        "pnl_daily":     None,
    }.get(table)

    for i, row in enumerate(raw_rows, 1):
        errors = []

        # 1. Required columns present
        for col_name, py_type, nullable, validator_fn_name in schema:
            val = row.get(col_name, "")
            if not nullable and (val is None or str(val).strip() == ""):
                errors.append(f"Row {i}: required field '{col_name}' is empty")
                continue

            # 2. Validator function
            if validator_fn_name and val and str(val).strip():
                fn = VALIDATOR_MAP.get(validator_fn_name)
                if fn and not fn(str(val).strip()):
                    errors.append(
                        f"Row {i}: '{col_name}'='{val}' failed validator '{validator_fn_name}'"
                    )

        # 3. Duplicate PK check (trades only)
        if pk_col:
            pk_val = row.get(pk_col, "")
            if pk_val in seen_pks:
                errors.append(f"Row {i}: duplicate {pk_col}='{pk_val}'")
            else:
                seen_pks.add(pk_val)

        # 4. Business rule: settlement_date >= trade_date
        if table == "trades":
            td = parse_date(row.get("trade_date", ""))
            sd = parse_date(row.get("settlement_date", ""))
            if td and sd and sd < td:
                result.warnings.append(
                    f"Row {i}: settlement_date {sd} < trade_date {td} — back-dated?"
                )

        if errors:
            rejected = dict(row)
            rejected["_rejection_reasons"] = " | ".join(errors)
            rejected["_rejected_at"]       = datetime.utcnow().isoformat()
            result.rejected_rows.append(rejected)
            result.errors.extend(errors)
        else:
            result.valid_rows.append(row)

    return result


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

DB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metals (
    symbol       TEXT PRIMARY KEY,
    metal_name   TEXT NOT NULL,
    asset_class  TEXT NOT NULL,
    unit         TEXT,
    price_source TEXT
);

CREATE TABLE IF NOT EXISTS books (
    book_id    TEXT PRIMARY KEY,
    desk       TEXT NOT NULL,
    book_type  TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id        TEXT PRIMARY KEY,
    trade_date      TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    metal           TEXT,
    symbol          TEXT NOT NULL,
    desk            TEXT,
    book            TEXT,
    trader          TEXT,
    counterparty    TEXT,
    buy_sell        TEXT NOT NULL,
    trade_type      TEXT,
    quantity        REAL NOT NULL,
    unit            TEXT,
    trade_price     REAL NOT NULL,
    spot_at_trade   REAL,
    currency        TEXT,
    notional_usd    REAL,
    status          TEXT DEFAULT 'Confirmed'
);

CREATE TABLE IF NOT EXISTS price_history (
    price_date  TEXT NOT NULL,
    metal       TEXT,
    symbol      TEXT NOT NULL,
    spot_price  REAL NOT NULL,
    currency    TEXT,
    unit        TEXT,
    source      TEXT,
    PRIMARY KEY (price_date, symbol)
);

CREATE TABLE IF NOT EXISTS positions (
    as_of_date     TEXT NOT NULL,
    book           TEXT NOT NULL,
    desk           TEXT,
    metal          TEXT,
    symbol         TEXT NOT NULL,
    net_quantity   REAL,
    unit           TEXT,
    avg_cost_usd   REAL,
    total_cost_usd REAL,
    trade_count    INTEGER,
    long_short     TEXT,
    PRIMARY KEY (as_of_date, book, symbol)
);

CREATE TABLE IF NOT EXISTS pnl_daily (
    pnl_date       TEXT NOT NULL,
    book           TEXT NOT NULL,
    desk           TEXT,
    metal          TEXT,
    symbol         TEXT NOT NULL,
    net_quantity   REAL,
    unit           TEXT,
    spot_price_usd REAL,
    mtm_value_usd  REAL,
    cost_basis_usd REAL,
    unrealised_pnl REAL,
    pnl_pct        REAL,
    long_short     TEXT,
    PRIMARY KEY (pnl_date, book, symbol)
);

CREATE TABLE IF NOT EXISTS etl_run_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp   TEXT NOT NULL,
    table_name      TEXT NOT NULL,
    source_file     TEXT,
    rows_read       INTEGER,
    rows_valid      INTEGER,
    rows_rejected   INTEGER,
    rows_inserted   INTEGER,
    rows_updated    INTEGER,
    duration_ms     INTEGER,
    status          TEXT,
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS rejection_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at        TEXT NOT NULL,
    run_timestamp    TEXT NOT NULL,
    table_name       TEXT NOT NULL,
    source_file      TEXT,
    row_data         TEXT,
    rejection_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_date    ON trades (trade_date);
CREATE INDEX IF NOT EXISTS idx_trades_symbol  ON trades (symbol);
CREATE INDEX IF NOT EXISTS idx_trades_book    ON trades (book);
CREATE INDEX IF NOT EXISTS idx_price_date_sym ON price_history (price_date, symbol);
CREATE INDEX IF NOT EXISTS idx_pnl_date       ON pnl_daily (pnl_date);
"""

SEED_REFERENCE_SQL = """
INSERT OR IGNORE INTO metals VALUES ('XAU','Gold',     'Precious','troy oz','LBMA');
INSERT OR IGNORE INTO metals VALUES ('XAG','Silver',   'Precious','troy oz','LBMA');
INSERT OR IGNORE INTO metals VALUES ('XPT','Platinum', 'Precious','troy oz','LBMA');
INSERT OR IGNORE INTO metals VALUES ('XPD','Palladium','Precious','troy oz','LBMA');
INSERT OR IGNORE INTO metals VALUES ('HG', 'Copper',   'Base',    'lbs',    'LME');
INSERT OR IGNORE INTO metals VALUES ('AL', 'Aluminium','Base',    'MT',     'LME');
INSERT OR IGNORE INTO metals VALUES ('ZN', 'Zinc',     'Base',    'MT',     'LME');
INSERT OR IGNORE INTO metals VALUES ('NI', 'Nickel',   'Base',    'MT',     'LME');

INSERT OR IGNORE INTO books VALUES ('PM-PROP-01',  'Precious Metals','Prop');
INSERT OR IGNORE INTO books VALUES ('PM-HEDGE-01', 'Precious Metals','Hedge');
INSERT OR IGNORE INTO books VALUES ('PM-CLIENT-01','Precious Metals','Client');
INSERT OR IGNORE INTO books VALUES ('BM-PROP-01',  'Base Metals',    'Prop');
INSERT OR IGNORE INTO books VALUES ('BM-HEDGE-01', 'Base Metals',    'Hedge');
INSERT OR IGNORE INTO books VALUES ('BM-CLIENT-01','Base Metals',    'Client');
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def initialise_db(conn: sqlite3.Connection, reset: bool = False):
    if reset:
        log.warning("--reset flag set: dropping all tables")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [r[0] for r in cursor.fetchall()]
        for t in tables:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
        log.info("All tables dropped")

    conn.executescript(DB_SCHEMA_SQL)
    conn.executescript(SEED_REFERENCE_SQL)
    conn.commit()
    log.info("Database schema initialised")


def upsert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: list[dict],
    schema: list,
) -> tuple[int, int]:
    """
    Insert rows using INSERT OR REPLACE (upsert).
    Returns (inserted_count, skipped_count).
    """
    if not rows:
        return 0, 0

    cols = [col_name for col_name, *_ in schema]
    placeholders = ", ".join("?" for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"

    inserted = 0
    skipped  = 0

    for row in rows:
        try:
            transformed = transform_row(row, schema, table)
            values = [transformed.get(col) for col in cols]
            conn.execute(sql, values)
            inserted += 1
        except (ValueError, sqlite3.Error) as e:
            log.warning(f"Skipped row in {table}: {e}")
            skipped += 1

    conn.commit()
    return inserted, skipped


def log_run(
    conn: sqlite3.Connection,
    run_ts: str,
    table: str,
    source_file: str,
    rows_read: int,
    rows_valid: int,
    rows_rejected: int,
    rows_inserted: int,
    rows_updated: int,
    duration_ms: int,
    status: str,
    error_message: str = None,
):
    conn.execute("""
        INSERT INTO etl_run_log
            (run_timestamp, table_name, source_file, rows_read, rows_valid,
             rows_rejected, rows_inserted, rows_updated, duration_ms, status, error_message)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (run_ts, table, source_file, rows_read, rows_valid,
          rows_rejected, rows_inserted, rows_updated, duration_ms, status, error_message))
    conn.commit()


def log_rejections(
    conn: sqlite3.Connection,
    run_ts: str,
    table: str,
    source_file: str,
    rejected_rows: list[dict],
):
    for row in rejected_rows:
        reason = row.get("_rejection_reasons", "Unknown")
        row_copy = {k: v for k, v in row.items()
                    if not k.startswith("_")}
        conn.execute("""
            INSERT INTO rejection_log
                (logged_at, run_timestamp, table_name, source_file, row_data, rejection_reason)
            VALUES (?,?,?,?,?,?)
        """, (
            datetime.utcnow().isoformat(),
            run_ts,
            table,
            source_file,
            json.dumps(row_copy),
            reason,
        ))
    conn.commit()


# ---------------------------------------------------------------------------
# Main ETL runner
# ---------------------------------------------------------------------------

class ETLPipeline:

    def __init__(self, data_dir: str, db_path: str, dry_run: bool = False):
        self.data_dir  = Path(data_dir)
        self.db_path   = db_path
        self.dry_run   = dry_run
        self.run_ts    = datetime.utcnow().isoformat()
        self.summary: list[dict] = []
        self.log       = logging.getLogger("etl.pipeline")

    def run(self, tables: list[str] | None = None, reset: bool = False):
        self.log.info(f"{'='*60}")
        self.log.info(f"ETL PIPELINE START  run_ts={self.run_ts}")
        self.log.info(f"  data_dir : {self.data_dir}")
        self.log.info(f"  db_path  : {self.db_path}")
        self.log.info(f"  dry_run  : {self.dry_run}")
        self.log.info(f"{'='*60}")

        conn = get_connection(self.db_path)
        initialise_db(conn, reset=reset)

        target_files = {k: v for k, v in CSV_TABLE_MAP.items()
                        if tables is None or v in tables}

        for csv_file, table in target_files.items():
            self._run_table(conn, csv_file, table)

        self._print_summary()
        conn.close()

        # Return non-zero exit code if any table had rejections > 10%
        any_failed = any(
            s["rejection_rate"] > 0.10 for s in self.summary
        )
        return 1 if any_failed else 0

    def _run_table(self, conn: sqlite3.Connection, csv_file: str, table: str):
        logger = logging.getLogger(f"etl.{table}")
        csv_path = self.data_dir / csv_file
        t_start  = datetime.utcnow()

        logger.info(f"--- {table.upper()} ---  source={csv_path}")

        if not csv_path.exists():
            logger.warning(f"File not found: {csv_path} — skipping")
            self.summary.append({
                "table": table, "file": csv_file,
                "rows_read": 0, "valid": 0, "rejected": 0,
                "inserted": 0, "rejection_rate": 0.0, "status": "SKIPPED"
            })
            return

        # --- EXTRACT ---
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                raw_rows = list(csv.DictReader(f))
        except Exception as e:
            logger.error(f"Failed to read {csv_path}: {e}")
            self.summary.append({
                "table": table, "file": csv_file,
                "rows_read": 0, "valid": 0, "rejected": 0,
                "inserted": 0, "rejection_rate": 0.0, "status": "ERROR",
                "error": str(e)
            })
            return

        logger.info(f"  Extracted {len(raw_rows):,} rows")

        # --- VALIDATE ---
        schema = SCHEMAS.get(table, [])
        result = validate_rows(raw_rows, schema, table)

        if result.rejected_rows:
            logger.warning(
                f"  Rejected {len(result.rejected_rows):,} rows "
                f"({result.rejection_rate:.1%} rejection rate)"
            )
            for err in result.errors[:5]:    # log first 5 errors
                logger.warning(f"    {err}")
            if len(result.errors) > 5:
                logger.warning(f"    ... and {len(result.errors)-5} more errors")

        if result.warnings:
            for w in result.warnings[:3]:
                logger.warning(f"  ⚠ {w}")

        logger.info(f"  Valid rows: {len(result.valid_rows):,}")

        # --- LOAD ---
        inserted = 0
        if not self.dry_run:
            inserted, skipped = upsert_rows(conn, table, result.valid_rows, schema)
            logger.info(f"  Loaded {inserted:,} rows into '{table}'")
            if skipped:
                logger.warning(f"  Skipped {skipped:,} rows during load (transform errors)")

            # Persist rejection log to DB
            if result.rejected_rows:
                log_rejections(conn, self.run_ts, table, csv_file, result.rejected_rows)
                logger.info(f"  Rejection log: {len(result.rejected_rows)} rows written to rejection_log")

            # Persist run log
            duration_ms = int(
                (datetime.utcnow() - t_start).total_seconds() * 1000
            )
            status = "COMPLETE" if result.rejection_rate <= 0.10 else "COMPLETE_WITH_WARNINGS"
            log_run(
                conn, self.run_ts, table, csv_file,
                rows_read=len(raw_rows),
                rows_valid=len(result.valid_rows),
                rows_rejected=len(result.rejected_rows),
                rows_inserted=inserted,
                rows_updated=0,
                duration_ms=duration_ms,
                status=status,
            )
        else:
            logger.info("  DRY RUN — no DB writes")

        self.summary.append({
            "table":          table,
            "file":           csv_file,
            "rows_read":      len(raw_rows),
            "valid":          len(result.valid_rows),
            "rejected":       len(result.rejected_rows),
            "inserted":       inserted,
            "rejection_rate": result.rejection_rate,
            "status":         "DRY_RUN" if self.dry_run else "COMPLETE",
        })

    def _print_summary(self):
        self.log.info("")
        self.log.info("=" * 60)
        self.log.info("ETL PIPELINE SUMMARY")
        self.log.info("=" * 60)
        self.log.info(
            f"{'Table':<18} {'Read':>6} {'Valid':>6} {'Rejected':>9} "
            f"{'Inserted':>9} {'Rej%':>6}  Status"
        )
        self.log.info("-" * 60)
        for s in self.summary:
            self.log.info(
                f"{s['table']:<18} {s['rows_read']:>6,} {s['valid']:>6,} "
                f"{s['rejected']:>9,} {s['inserted']:>9,} "
                f"{s['rejection_rate']:>5.1%}  {s['status']}"
            )
        self.log.info("=" * 60)


# ---------------------------------------------------------------------------
# Post-load verification queries
# ---------------------------------------------------------------------------

def run_verification(db_path: str):
    """
    Run a set of sanity-check queries after loading.
    Mirrors BRD Acceptance Criteria AC-01 through AC-03.
    """
    log.info("")
    log.info("POST-LOAD VERIFICATION")
    log.info("-" * 40)

    conn = get_connection(db_path)

    checks = [
        # (description, SQL, expected_operator, expected_value)
        ("Trades loaded > 0",
         "SELECT COUNT(*) FROM trades WHERE status != 'Cancelled'",
         ">", 0),

        ("Price history > 0",
         "SELECT COUNT(*) FROM price_history",
         ">", 0),

        ("Positions calculated",
         "SELECT COUNT(*) FROM positions",
         ">", 0),

        ("PnL records exist",
         "SELECT COUNT(*) FROM pnl_daily",
         ">", 0),

        ("No null symbols in trades",
         "SELECT COUNT(*) FROM trades WHERE symbol IS NULL OR symbol = ''",
         "==", 0),

        ("No null prices in price_history",
         "SELECT COUNT(*) FROM price_history WHERE spot_price IS NULL OR spot_price <= 0",
         "==", 0),

        ("PnL = MTM - Cost basis (tolerance $1)",
         """SELECT COUNT(*) FROM pnl_daily
            WHERE ABS(unrealised_pnl - (mtm_value_usd - cost_basis_usd)) > 1.0""",
         "==", 0),

        ("All trade symbols in metals reference",
         """SELECT COUNT(*) FROM trades t
            LEFT JOIN metals m ON t.symbol = m.symbol
            WHERE m.symbol IS NULL""",
         "==", 0),

        ("Rejection rate < 10%",
         """SELECT CAST(rows_rejected AS FLOAT) / NULLIF(rows_read,0)
            FROM etl_run_log
            WHERE table_name = 'trades'
            ORDER BY run_id DESC LIMIT 1""",
         "<", 0.10),
    ]

    passed = 0
    failed = 0
    for desc, sql, op, expected in checks:
        try:
            cursor = conn.execute(sql)
            value = cursor.fetchone()[0]
            if value is None:
                value = 0

            result = {
                ">":  value > expected,
                "==": value == expected,
                "<":  value < expected,
            }.get(op, False)

            icon = "✓" if result else "✗"
            status = "PASS" if result else "FAIL"
            log.info(f"  {icon} [{status}]  {desc}  (got {value})")

            if result:
                passed += 1
            else:
                failed += 1

        except sqlite3.Error as e:
            log.error(f"  ✗ [ERROR] {desc}: {e}")
            failed += 1

    log.info(f"\n  Results: {passed} passed, {failed} failed")
    conn.close()
    return failed == 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Metals Risk Dashboard — ETL Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python python/etl_pipeline.py
  python python/etl_pipeline.py --dry-run
  python python/etl_pipeline.py --reset
  python python/etl_pipeline.py --table trades --table pnl_daily
  python python/etl_pipeline.py --db /tmp/test_metals.db --verify
        """,
    )
    parser.add_argument("--data-dir", default="data",      help="Directory containing CSVs")
    parser.add_argument("--db",       default="metals.db", help="SQLite database path")
    parser.add_argument("--table",    action="append",      dest="tables",
                        help="Load specific table(s) only. Repeat for multiple.")
    parser.add_argument("--dry-run",  action="store_true",  help="Validate only, no DB writes")
    parser.add_argument("--reset",    action="store_true",  help="Drop and recreate all tables")
    parser.add_argument("--verify",   action="store_true",  help="Run post-load verification queries")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG","INFO","WARNING","ERROR"])
    args = parser.parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    pipeline = ETLPipeline(
        data_dir=args.data_dir,
        db_path=args.db,
        dry_run=args.dry_run,
    )

    exit_code = pipeline.run(tables=args.tables, reset=args.reset)

    if args.verify and not args.dry_run:
        ok = run_verification(args.db)
        if not ok:
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
