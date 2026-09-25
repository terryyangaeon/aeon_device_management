"""App-level accounts + business-unit (site) permission control.

Independent of ADMIN_PASSWORD, which only gates the DB /config page.
Sessions are Flask's own signed cookie (no server-side session table).
"""
import os
from functools import wraps

from flask import session, request, jsonify, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

import db as dbmod

query = dbmod.query

# Seeded once on first run — the same 8 codes device_management.js's pills
# already derive from laptops.category / sim_cards.contract_site. Business
# units are now a real table (managed from Configuration → Business Unit),
# this is only the starting set so existing deploys don't lose grants.
_SEED_BUSINESS_UNITS = [
    ("BO",   "Back Office 總辦工室"),
    ("CHT",  "Cross Harbour Tunnel 紅磡海底隧道"),
    ("KTT",  "Kai Tak Tunnel 啓德隧道"),
    ("KWH",  "Kwong Wah Hospital 廣華醫院"),
    ("LRT",  "Lion Rock Tunnel 獅子山隧道"),
    ("PWH",  "Prince of Wales 威爾斯親王醫院"),
    ("SMT",  "Shing Mun Tunnel 城門隧道"),
    ("TKOT", "Tseung Kwan O Tunnel 將軍澳隧道"),
]


_schema_ready = False


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    query("""
        CREATE TABLE IF NOT EXISTS accounts (
            email       TEXT PRIMARY KEY,
            name        TEXT,
            pass_hash   TEXT NOT NULL,
            role        TEXT NOT NULL DEFAULT 'user',
            active      BOOLEAN NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    query("""
        CREATE TABLE IF NOT EXISTS account_sites (
            email       TEXT NOT NULL REFERENCES accounts(email) ON DELETE CASCADE,
            site_code   TEXT NOT NULL,
            PRIMARY KEY (email, site_code)
        )
    """)
    query("""
        CREATE TABLE IF NOT EXISTS business_units (
            code        TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            active      BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order  INTEGER NOT NULL DEFAULT 0
        )
    """)
    _bootstrap_admin()
    _seed_business_units()
    _schema_ready = True


def _seed_business_units():
    existing = query("SELECT COUNT(*) AS c FROM business_units", fetchone=True)
    if existing and existing["c"] > 0:
        return
    for i, (code, name) in enumerate(_SEED_BUSINESS_UNITS):
        query(
            "INSERT INTO business_units (code, name, active, sort_order) VALUES (%s,%s,TRUE,%s) ON CONFLICT (code) DO NOTHING",
            (code, name, i),
        )


def _bootstrap_admin():
    """Seed one admin account on first run, from env vars, so there's always
    a way in. No-op once any account already exists."""
    existing = query("SELECT COUNT(*) AS c FROM accounts", fetchone=True)
    if existing and existing["c"] > 0:
        return
    email = (os.environ.get("BOOTSTRAP_ADMIN_EMAIL") or "itdept@aeondelightasia.com").strip().lower()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
    if not password:
        return   # nothing to seed without a password
    query(
        "INSERT INTO accounts (email, name, pass_hash, role, active) VALUES (%s,%s,%s,'admin',TRUE) ON CONFLICT (email) DO NOTHING",
        (email, "IT Department", generate_password_hash(password)),
    )


# ── Row helpers ──────────────────────────────────────────────────────

def _row_to_user(row, sites=None):
    if not row:
        return None
    return {
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "active": row["active"],
        "sites": sites if sites is not None else get_account_sites(row["email"]),
    }


def get_account_raw(email):
    return query("SELECT * FROM accounts WHERE email = %s", (str(email or "").strip().lower(),), fetchone=True)


def get_account_sites(email):
    rows = query("SELECT site_code FROM account_sites WHERE email = %s", (str(email).strip().lower(),))
    return [r["site_code"] for r in rows]


def list_accounts():
    rows = query("SELECT * FROM accounts ORDER BY role, email")
    return [_row_to_user(r) for r in rows]


def verify_login(email, password):
    row = get_account_raw(email)
    if not row or not row["active"]:
        return None
    if not check_password_hash(row["pass_hash"], password or ""):
        return None
    return _row_to_user(row)


def create_account(email, name, password, role, sites):
    email = str(email).strip().lower()
    if not email or "@" not in email:
        raise ValueError("A valid email is required.")
    if not password or len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if role not in ("admin", "user"):
        raise ValueError("Role must be 'admin' or 'user'.")
    if get_account_raw(email):
        raise ValueError("An account with this email already exists.")
    query(
        "INSERT INTO accounts (email, name, pass_hash, role, active) VALUES (%s,%s,%s,%s,TRUE)",
        (email, (name or "").strip() or None, generate_password_hash(password), role),
    )
    _set_sites(email, sites)
    return _row_to_user(get_account_raw(email))


def update_account(email, name, role, active, sites, password=None):
    email = str(email).strip().lower()
    cur = get_account_raw(email)
    if not cur:
        raise ValueError("Account not found.")
    if role not in ("admin", "user"):
        raise ValueError("Role must be 'admin' or 'user'.")
    if password:
        if len(password) < 6:
            raise ValueError("New password must be at least 6 characters.")
        query("UPDATE accounts SET name=%s, role=%s, active=%s, pass_hash=%s WHERE email=%s",
              ((name or "").strip() or None, role, bool(active), generate_password_hash(password), email))
    else:
        query("UPDATE accounts SET name=%s, role=%s, active=%s WHERE email=%s",
              ((name or "").strip() or None, role, bool(active), email))
    _set_sites(email, sites)
    return _row_to_user(get_account_raw(email))


def _set_sites(email, sites):
    email = str(email).strip().lower()
    known = {bu["code"] for bu in list_business_units()}
    sites = [s for s in (sites or []) if s in known]
    query("DELETE FROM account_sites WHERE email = %s", (email,))
    for code in sites:
        query("INSERT INTO account_sites (email, site_code) VALUES (%s,%s) ON CONFLICT DO NOTHING", (email, code))


# ── Business units (sites) — managed from Configuration → Business Unit ────

def list_business_units(active_only=False):
    if active_only:
        rows = query("SELECT code, name, active FROM business_units WHERE active = TRUE ORDER BY sort_order, code")
    else:
        rows = query("SELECT code, name, active FROM business_units ORDER BY sort_order, code")
    return [{"code": r["code"], "name": r["name"], "active": r["active"]} for r in rows]


def create_business_unit(code, name):
    code = str(code or "").strip().upper()
    name = str(name or "").strip()
    if not code:
        raise ValueError("Code is required.")
    if not name:
        raise ValueError("Name is required.")
    if query("SELECT 1 FROM business_units WHERE code = %s", (code,), fetchone=True):
        raise ValueError("A business unit with this code already exists.")
    max_order = query("SELECT COALESCE(MAX(sort_order), 0) AS m FROM business_units", fetchone=True)["m"]
    query("INSERT INTO business_units (code, name, active, sort_order) VALUES (%s,%s,TRUE,%s)",
          (code, name, max_order + 1))


def update_business_unit(code, name, active):
    code = str(code or "").strip().upper()
    name = str(name or "").strip()
    if not query("SELECT 1 FROM business_units WHERE code = %s", (code,), fetchone=True):
        raise ValueError("Business unit not found.")
    if not name:
        raise ValueError("Name is required.")
    query("UPDATE business_units SET name=%s, active=%s WHERE code=%s", (name, bool(active), code))


def delete_account(email):
    query("DELETE FROM accounts WHERE email = %s", (str(email).strip().lower(),))


def set_own_password(email, current_password, new_password):
    row = get_account_raw(email)
    if not row:
        raise ValueError("Account not found.")
    if not check_password_hash(row["pass_hash"], current_password or ""):
        raise ValueError("Current password is incorrect.")
    if not new_password or len(new_password) < 6:
        raise ValueError("New password must be at least 6 characters.")
    query("UPDATE accounts SET pass_hash=%s WHERE email=%s", (generate_password_hash(new_password), row["email"]))


# ── Session helpers (Flask signed cookie — no server-side session store) ──

def login_session(user):
    session["acct_email"] = user["email"]


def logout_session():
    session.pop("acct_email", None)


def current_user():
    email = session.get("acct_email")
    if not email:
        return None
    row = get_account_raw(email)
    if not row or not row["active"]:
        return None
    return _row_to_user(row)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        ensure_schema()
        if current_user() is None:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "Not signed in"}), 401
            return redirect(url_for("login_page", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        ensure_schema()
        u = current_user()
        if u is None:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "Not signed in"}), 401
            return redirect(url_for("login_page", next=request.path))
        if u["role"] != "admin":
            return jsonify({"ok": False, "message": "Admin access required"}), 403
        return view(*args, **kwargs)
    return wrapped
