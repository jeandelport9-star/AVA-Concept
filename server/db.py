"""SQLite storage. One file, created on first run. Small helpers keep the routes short."""
import json
import os
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("AVA_DATA", ROOT / "data"))
UPLOADS = DATA / "uploads"
DB_PATH = DATA / "ava.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL, name TEXT NOT NULL,
  phone TEXT, role TEXT NOT NULL, company TEXT, active INTEGER DEFAULT 1, verified INTEGER DEFAULT 0,
  pm_id INTEGER, commission_pct REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS properties (
  id INTEGER PRIMARY KEY, pm_id INTEGER, landlord_id INTEGER, title TEXT NOT NULL, kind TEXT DEFAULT 'rental',
  type TEXT, address TEXT, suburb TEXT, city TEXT, province TEXT, lat REAL, lng REAL, erf TEXT,
  bedrooms REAL DEFAULT 0, bathrooms REAL DEFAULT 0, parking INTEGER DEFAULT 0, size_m2 REAL, erf_size REAL, published_at TEXT,
  features TEXT DEFAULT '[]', pets INTEGER DEFAULT 0, furnished INTEGER DEFAULT 0,
  rent INTEGER, deposit INTEGER, available_from TEXT, headline TEXT, description TEXT,
  listing_status TEXT DEFAULT 'draft', featured INTEGER DEFAULT 0, insured INTEGER DEFAULT 1,
  views INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS media (
  id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, kind TEXT DEFAULT 'photo', url TEXT NOT NULL,
  caption TEXT, room TEXT, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS favourites (user_id INTEGER, property_id INTEGER, PRIMARY KEY (user_id, property_id));
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, user_id INTEGER, query TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS viewings (
  id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, user_id INTEGER, name TEXT, email TEXT, phone TEXT,
  slot TEXT NOT NULL, status TEXT DEFAULT 'requested', notes TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, user_id INTEGER, name TEXT, email TEXT, phone TEXT,
  employer TEXT, income INTEGER, other_income INTEGER DEFAULT 0, occupants INTEGER DEFAULT 1, pets INTEGER DEFAULT 0,
  move_in TEXT, message TEXT, docs TEXT DEFAULT '[]', credit_score INTEGER, rental_history TEXT,
  score INTEGER, score_notes TEXT, status TEXT DEFAULT 'submitted', decision_note TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS leases (
  id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, tenant_id INTEGER NOT NULL, application_id INTEGER,
  start_date TEXT, end_date TEXT, rent INTEGER, base_rent INTEGER, deposit INTEGER, escalation_pct REAL DEFAULT 8,
  due_day INTEGER DEFAULT 1, status TEXT DEFAULT 'draft', terms TEXT,
  tenant_sig TEXT, tenant_signed_at TEXT, landlord_sig TEXT, landlord_signed_at TEXT,
  renewal_of INTEGER, ended_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY, property_id INTEGER, lease_id INTEGER, account TEXT NOT NULL, kind TEXT NOT NULL,
  date TEXT NOT NULL, period TEXT, description TEXT, amount REAL NOT NULL, ref TEXT, ticket_id INTEGER,
  payment_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY, lease_id INTEGER, amount REAL NOT NULL, method TEXT, reference TEXT,
  status TEXT DEFAULT 'pending', gateway_id TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS contractors (
  user_id INTEGER PRIMARY KEY, trades TEXT DEFAULT '[]', areas TEXT DEFAULT '[]', approved INTEGER DEFAULT 0,
  vetted INTEGER DEFAULT 0, callout_fee INTEGER DEFAULT 0, bio TEXT, bee_level TEXT, registration TEXT);
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY, ref TEXT, property_id INTEGER NOT NULL, lease_id INTEGER, reported_by INTEGER,
  title TEXT NOT NULL, description TEXT, category TEXT, trade TEXT, priority TEXT DEFAULT 'Medium',
  status TEXT DEFAULT 'new', room TEXT, responsible TEXT DEFAULT 'landlord', contractor_id INTEGER,
  approved_quote_id INTEGER, cost REAL, deduct_from_rent INTEGER DEFAULT 1, quote_deadline TEXT,
  scheduled_for TEXT, source TEXT DEFAULT 'tenant', inspection_item_id INTEGER, snag_id INTEGER,
  photos TEXT DEFAULT '[]', after_photos TEXT DEFAULT '[]', ai_notes TEXT, sentiment TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT, deducted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ticket_events (
  id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, user_id INTEGER, kind TEXT, text TEXT, photo TEXT,
  internal INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS quotes (
  id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, contractor_id INTEGER NOT NULL, amount REAL,
  eta_days INTEGER, notes TEXT, file TEXT, status TEXT DEFAULT 'requested', rank_score REAL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, submitted_at TEXT);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY, target_type TEXT, target_id INTEGER, author_id INTEGER, rating INTEGER, text TEXT,
  status TEXT DEFAULT 'published', ticket_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS inspections (
  id INTEGER PRIMARY KEY, property_id INTEGER NOT NULL, lease_id INTEGER, type TEXT NOT NULL, date TEXT,
  status TEXT DEFAULT 'draft', inspector_id INTEGER, compare_to_id INTEGER, round INTEGER DEFAULT 1,
  summary TEXT, tenant_present INTEGER DEFAULT 1, tenant_sig TEXT, tenant_signed_at TEXT,
  agent_sig TEXT, agent_signed_at TEXT, contractor_sig TEXT, contractor_signed_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, finalised_at TEXT);
CREATE TABLE IF NOT EXISTS insp_rooms (
  id INTEGER PRIMARY KEY, inspection_id INTEGER NOT NULL, name TEXT, sort INTEGER DEFAULT 0,
  pano_url TEXT, pano_yaw REAL DEFAULT 0, photos TEXT DEFAULT '[]', notes TEXT);
CREATE TABLE IF NOT EXISTS insp_items (
  id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL, inspection_id INTEGER NOT NULL, name TEXT,
  condition INTEGER, clean INTEGER, working INTEGER, notes TEXT, photos TEXT DEFAULT '[]', pin TEXT,
  charge REAL, charge_to TEXT, ticket_id INTEGER, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS snags (
  id INTEGER PRIMARY KEY, ref TEXT, property_id INTEGER NOT NULL, inspection_id INTEGER, room TEXT,
  room_id INTEGER, pin TEXT, title TEXT NOT NULL, description TEXT, trade TEXT, contractor_id INTEGER,
  priority TEXT DEFAULT 'Medium', category TEXT DEFAULT 'Workmanship', qty REAL DEFAULT 1, unit TEXT DEFAULT 'no.',
  rate REAL, due_date TEXT, status TEXT DEFAULT 'open', photos_before TEXT DEFAULT '[]', photos_after TEXT DEFAULT '[]',
  contractor_note TEXT, rework_count INTEGER DEFAULT 0, raised_at TEXT DEFAULT CURRENT_TIMESTAMP,
  ready_at TEXT, closed_at TEXT, closed_by INTEGER, closed_inspection_id INTEGER);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, thread TEXT NOT NULL, property_id INTEGER, from_id INTEGER, body TEXT NOT NULL,
  sentiment TEXT, bot INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS thread_reads (thread TEXT, user_id INTEGER, last_id INTEGER, PRIMARY KEY (thread, user_id));
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT, body TEXT, link TEXT, kind TEXT,
  read INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY, pm_id INTEGER, property_id INTEGER, kind TEXT, title TEXT, detail TEXT, link TEXT,
  priority INTEGER DEFAULT 2, due TEXT, status TEXT DEFAULT 'open', dedupe TEXT UNIQUE,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, done_at TEXT);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY, pm_id INTEGER, property_id INTEGER, actor TEXT, text TEXT, link TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY, property_id INTEGER, lease_id INTEGER, user_id INTEGER, name TEXT, url TEXT, kind TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS agent_log (
  id INTEGER PRIMARY KEY, session TEXT, user_id INTEGER, property_id INTEGER, role TEXT, text TEXT, reply TEXT,
  intent TEXT, handoff INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
-- ===== trust accounting: the agency's real bank accounts =====
CREATE TABLE IF NOT EXISTS cashbooks (
  id INTEGER PRIMARY KEY, code TEXT UNIQUE, name TEXT, bank TEXT, branch_code TEXT, account_no TEXT,
  opening_balance REAL DEFAULT 0, opening_date TEXT, feed TEXT DEFAULT 'simulated', last_feed_at TEXT);
CREATE TABLE IF NOT EXISTS cashbook_tx (
  id INTEGER PRIMARY KEY, cashbook TEXT NOT NULL, date TEXT NOT NULL, amount REAL NOT NULL, description TEXT, reference TEXT,
  source TEXT, ledger_id INTEGER, payment_id INTEGER, batch_id INTEGER, journal_id INTEGER, property_id INTEGER, lease_id INTEGER,
  bank_line_id INTEGER, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS bank_lines (
  id INTEGER PRIMARY KEY, cashbook TEXT NOT NULL, date TEXT NOT NULL, amount REAL NOT NULL, description TEXT, reference TEXT,
  balance REAL, source TEXT, fingerprint TEXT UNIQUE, matched_tx INTEGER, status TEXT DEFAULT 'unmatched', note TEXT,
  imported_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS recons (
  id INTEGER PRIMARY KEY, cashbook TEXT, period TEXT, statement_balance REAL, cashbook_balance REAL, difference REAL,
  outstanding TEXT, by_user INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(cashbook, period));
CREATE TABLE IF NOT EXISTS periods (period TEXT PRIMARY KEY, locked_at TEXT, locked_by INTEGER);
CREATE TABLE IF NOT EXISTS year_ends (
  id INTEGER PRIMARY KEY, fy TEXT UNIQUE, start_period TEXT, end_period TEXT, snapshot TEXT, by_user INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS journals (
  id INTEGER PRIMARY KEY, ref TEXT, date TEXT, reason TEXT, by_user INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS bank_accounts (
  id INTEGER PRIMARY KEY, user_id INTEGER UNIQUE, holder TEXT, bank TEXT, branch_code TEXT, account_no TEXT, account_type TEXT,
  verified INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY, ref TEXT, kind TEXT, period TEXT, cashbook TEXT DEFAULT 'trust', status TEXT DEFAULT 'draft', total REAL DEFAULT 0,
  created_by INTEGER, authorised_by INTEGER, authorised_at TEXT, released_by INTEGER, released_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS batch_lines (
  id INTEGER PRIMARY KEY, batch_id INTEGER, payee TEXT, payee_user INTEGER, control TEXT, ledger_id INTEGER, property_id INTEGER,
  amount REAL, reference TEXT, bank TEXT, branch_code TEXT, account_no TEXT, account_type TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS mandates (
  id INTEGER PRIMARY KEY, lease_id INTEGER, tenant_id INTEGER, ref TEXT, holder TEXT, bank TEXT, branch_code TEXT, account_no TEXT,
  account_type TEXT, debit_day INTEGER, max_amount REAL, debicheck TEXT DEFAULT 'pending', status TEXT DEFAULT 'active',
  sim_result TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, approved_at TEXT, cancelled_at TEXT);
CREATE TABLE IF NOT EXISTS debit_runs (
  id INTEGER PRIMARY KEY, ref TEXT, action_date TEXT, status TEXT DEFAULT 'submitted', total REAL, count INTEGER, file TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT);
CREATE TABLE IF NOT EXISTS debit_items (
  id INTEGER PRIMARY KEY, run_id INTEGER, mandate_id INTEGER, lease_id INTEGER, amount REAL, status TEXT DEFAULT 'pending',
  reason TEXT, payment_id INTEGER);
CREATE TABLE IF NOT EXISTS deposit_accounts (
  id INTEGER PRIMARY KEY, lease_id INTEGER UNIQUE, bank TEXT, account_no TEXT, rate REAL, opened_at TEXT, status TEXT DEFAULT 'open',
  closed_at TEXT);
CREATE INDEX IF NOT EXISTS ix_ctx_book ON cashbook_tx(cashbook, date);
CREATE INDEX IF NOT EXISTS ix_ctx_ledger ON cashbook_tx(ledger_id);
CREATE INDEX IF NOT EXISTS ix_ledger_lease ON ledger(lease_id, account);
CREATE INDEX IF NOT EXISTS ix_ledger_prop ON ledger(property_id, account, period);
CREATE INDEX IF NOT EXISTS ix_tickets_prop ON tickets(property_id, status);
CREATE INDEX IF NOT EXISTS ix_snags_prop ON snags(property_id, status);
CREATE INDEX IF NOT EXISTS ix_msg_thread ON messages(thread, id);
"""

_local = threading.local()
_lock = threading.RLock()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        DATA.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.c = c
    return c


def init():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn().executescript(SCHEMA)
        for table, col, typ in MIGRATIONS:      # add columns to databases made by older versions
            if col not in [r[1] for r in conn().execute(f"PRAGMA table_info({table})")]:
                conn().execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
        conn().commit()


MIGRATIONS = [("properties", "erf_size", "REAL"), ("properties", "published_at", "TEXT"),
              ("contractors", "lat", "REAL"), ("contractors", "lng", "REAL"), ("contractors", "base_address", "TEXT"),
              ("contractors", "radius_km", "REAL DEFAULT 25"), ("contractors", "sub_until", "TEXT"), ("contractors", "website", "TEXT"),
              ("contractors", "years", "INTEGER"), ("contractors", "insured", "INTEGER DEFAULT 0"),
              ("reviews", "quality", "INTEGER"), ("reviews", "punctuality", "INTEGER"), ("reviews", "price_score", "INTEGER"),
              ("reviews", "communication", "INTEGER"), ("reviews", "reply", "TEXT"), ("reviews", "author_role", "TEXT"),
              ("quotes", "distance_km", "REAL"), ("quotes", "kind", "TEXT DEFAULT 'quote'"), ("ticket_events", "audio", "TEXT"),
              ("tickets", "paid_contractor", "INTEGER DEFAULT 0"), ("tickets", "auto_closed", "INTEGER DEFAULT 0"), ("tickets", "radius_km", "REAL"), ("quotes", "applied", "INTEGER DEFAULT 0"), ("ledger", "journal_id", "INTEGER")]


JSON_COLS = {"features", "docs", "trades", "areas", "photos", "after_photos", "pin", "photos_before", "photos_after"}


def row(r):
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


def q(sql, *args):
    return [row(r) for r in conn().execute(sql, args).fetchall()]


def q1(sql, *args):
    return row(conn().execute(sql, args).fetchone())


def val(sql, *args):
    r = conn().execute(sql, args).fetchone()
    return r[0] if r else None


def _enc(v):
    return json.dumps(v) if isinstance(v, (list, dict)) else v


def ins(table, **kw):
    kw = {k: _enc(v) for k, v in kw.items()}
    with _lock:
        cur = conn().execute(f"INSERT INTO {table} ({','.join(kw)}) VALUES ({','.join('?' * len(kw))})", tuple(kw.values()))
        conn().commit()
        return cur.lastrowid


def upd(table, id_, **kw):
    if not kw:
        return
    kw = {k: _enc(v) for k, v in kw.items()}
    with _lock:
        conn().execute(f"UPDATE {table} SET {','.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), id_))
        conn().commit()


def exe(sql, *args):
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur


def today():
    return date.today().isoformat()


def now():
    return datetime.now().isoformat(timespec="seconds")


def get_setting(key, default=None):
    v = val("SELECT value FROM settings WHERE key=?", key)
    return json.loads(v) if v is not None else default


def set_setting(key, value):
    exe("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", key, json.dumps(value))


def rands(x):
    """Money is kept in whole rands, rounded off (half up): no cents anywhere in AVA."""
    if x is None or x == "":
        return None
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def month_name(per):
    """'2026-05' -> 'May 2026'."""
    try:
        y, m = per.split("-")[:2]
        return ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][int(m) - 1] + " " + y
    except Exception:
        return per
