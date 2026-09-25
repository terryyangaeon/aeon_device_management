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

# Site codes shown on the dashboard's location pills (device_management.js SITE_NAMES).
SITES = [
    {"code": "BO",   "name": "Back Office 總辦工室"},
    {"code": "CHT",  "name": "Cross Harbour Tunnel 紅磡海底隧道"},
    {"code": "KTT",  "name": "Kai Tak Tunnel 啓德隧道"},
    {"code": "KWH",  "name": "Kwong Wah Hospital 廣華醫院"},
    {"code": "LRT",  "name": "Lion Rock Tunnel 獅子山隧道"},
    {"code": "PWH",  "name": "Prince of Wales 威爾斯親王醫院"},
    {"code": "SMT",  "name": "Shing Mun Tunnel 城門隧道"},
    {"code": "TKOT", "name": "Tseung Kwan O Tunnel 將軍澳隧道"},
]
SITE_CODES = {s["code"] for s in SITES}


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
    _bootstrap_admin()
    _schema_ready = True


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
    sites = [s for s in (sites or []) if s in SITE_CODES]
    query("DELETE FROM account_sites WHERE email = %s", (email,))
    for code in sites:
        query("INSERT INTO account_sites (email, site_code) VALUES (%s,%s) ON CONFLICT DO NOTHING", (email, code))


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
