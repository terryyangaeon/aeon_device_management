"""Database connection layer for the Smart Toilet dashboard.

Supports:
  - PostgreSQL (via psycopg2, always available)
  - Microsoft SQL Server (via pyodbc; requires ODBC Driver 17/18)

The active connection is defined by dashboard/db_config.json (created by the
Configuration page). When that file is absent, we fall back to the DATABASE_URL
environment variable — so a fresh deploy behaves exactly like before.

Only reads run through here. Writes still go through app.py's helpers, which
use the same pool.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

log = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "db_config.json"

# Soft-import pyodbc — MSSQL is opt-in. Postgres-only hosts install cleanly.
try:
    import pyodbc  # type: ignore
    PYODBC_AVAILABLE = True
except ImportError:
    pyodbc = None  # type: ignore
    PYODBC_AVAILABLE = False


# ── Config load / save ──────────────────────────────────────────────

def load_config() -> Dict[str, Any]:
    """Read db_config.json, or synthesize one from DATABASE_URL as fallback.

    Returned shape (always includes 'engine' and 'source'):
      {
        "engine": "postgresql" | "mssql",
        "source": "file" | "env",
        "host": "...", "port": 5432, "database": "...",
        "user": "...", "password": "...",
        "sslmode": "prefer",       # PG only
        "trust_certificate": True,  # MSSQL only
        "server_type": "cloud",     # cosmetic label
        "odbc_driver": "ODBC Driver 18 for SQL Server",  # MSSQL only
      }
    """
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg.setdefault("engine", "postgresql")
            cfg["source"] = "file"
            return cfg
        except Exception as exc:
            log.warning(f"db_config.json unreadable, falling back to env: {exc}")

    # Fallback: parse DATABASE_URL env into a PG config
    db_url = os.environ.get("DATABASE_URL", "postgresql://sa:sa1234@localhost:5432/IoT")
    return _parse_pg_url(db_url)


def save_config(cfg: Dict[str, Any]) -> None:
    """Persist config to db_config.json (plain text — user's chosen risk)."""
    to_save = {k: v for k, v in cfg.items() if k != "source"}
    CONFIG_FILE.write_text(json.dumps(to_save, indent=2), encoding="utf-8")
    log.info(f"Saved db_config.json (engine={to_save.get('engine')})")


def delete_config() -> None:
    """Revert to DATABASE_URL env by removing the config file."""
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        log.info("Deleted db_config.json — will fall back to DATABASE_URL")


def _parse_pg_url(url: str) -> Dict[str, Any]:
    """Turn postgresql://user:pw@host:port/db into a config dict."""
    from urllib.parse import urlparse, unquote
    p = urlparse(url)
    return {
        "engine":      "postgresql",
        "source":      "env",
        "host":        p.hostname or "localhost",
        "port":        p.port or 5432,
        "database":    (p.path or "/").lstrip("/") or "postgres",
        "user":        unquote(p.username or ""),
        "password":    unquote(p.password or ""),
        "sslmode":     "prefer",
        "server_type": "cloud" if p.hostname and "." in (p.hostname or "") else "local",
    }


# ── DSN builders ────────────────────────────────────────────────────

def _pg_dsn(cfg: Dict[str, Any]) -> str:
    parts = [
        f"host={cfg.get('host', 'localhost')}",
        f"port={cfg.get('port', 5432)}",
        f"dbname={cfg.get('database', 'postgres')}",
        f"user={cfg.get('user', '')}",
        f"password={cfg.get('password', '')}",
    ]
    sslmode = cfg.get("sslmode")
    if sslmode:
        parts.append(f"sslmode={sslmode}")
    return " ".join(parts)


def _mssql_conn_str(cfg: Dict[str, Any]) -> str:
    driver = cfg.get("odbc_driver") or "ODBC Driver 18 for SQL Server"
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={cfg.get('host', 'localhost')},{cfg.get('port', 1433)}",
        f"DATABASE={cfg.get('database', 'master')}",
        f"UID={cfg.get('user', '')}",
        f"PWD={cfg.get('password', '')}",
    ]
    if cfg.get("trust_certificate", True):
        parts.append("TrustServerCertificate=yes")
    parts.append("Encrypt=yes")
    return ";".join(parts)


# ── Connection pool (rebuilt on config change) ──────────────────────

_pool: Optional[ThreadedConnectionPool] = None
_mssql_active: bool = False
_active_engine: str = "postgresql"
_pool_lock = Lock()


def _build_pool() -> None:
    """Build the pool from current config. Called lazily and after save."""
    global _pool, _mssql_active, _active_engine
    cfg = load_config()
    engine = cfg.get("engine", "postgresql")

    with _pool_lock:
        # Tear down any existing pool first
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None

        _active_engine = engine
        if engine == "mssql":
            if not PYODBC_AVAILABLE:
                raise RuntimeError(
                    "pyodbc not installed on this server — "
                    "MSSQL selected but the driver is missing. "
                    "Run: pip install pyodbc"
                )
            _mssql_active = True
            log.info(f"DB pool: MSSQL @ {cfg.get('host')}:{cfg.get('port')}/{cfg.get('database')}")
        else:
            _mssql_active = False
            _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=_pg_dsn(cfg))
            log.info(f"DB pool: PostgreSQL @ {cfg.get('host')}:{cfg.get('port')}/{cfg.get('database')}")


def reset_pool() -> None:
    """Public entry: force pool rebuild (called after Save)."""
    _build_pool()


def active_engine() -> str:
    """Return the currently active engine name."""
    if _pool is None and not _mssql_active:
        _build_pool()
    return _active_engine


# ── Query API ───────────────────────────────────────────────────────

class _MssqlDictCursor:
    """Wrap a pyodbc cursor so it returns dicts (like psycopg2 RealDictCursor)."""
    def __init__(self, cur):
        self.cur = cur

    def execute(self, sql, params=None):
        # Translate %s → ? for pyodbc
        translated = sql.replace("%s", "?") if params else sql
        if params:
            self.cur.execute(translated, params)
        else:
            self.cur.execute(translated)
        return self

    def fetchone(self):
        row = self.cur.fetchone()
        if row is None:
            return None
        cols = [c[0] for c in self.cur.description]
        return dict(zip(cols, row))

    def fetchall(self):
        cols = [c[0] for c in self.cur.description]
        return [dict(zip(cols, row)) for row in self.cur.fetchall()]

    def close(self):
        self.cur.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def query(sql: str, params: Optional[Tuple] = None, fetchone: bool = False):
    """Engine-agnostic read OR write.

    - SELECT with RETURNING: pass fetchone=True (or leave default for many rows)
    - INSERT / UPDATE / DELETE with no RETURNING: leave fetchone=False; the
      caller gets [] back and the transaction is committed.
    - Commits on success, rolls back on exception, so writes through the pool
      actually persist (default psycopg2 pool connections are autocommit=False)."""
    if _pool is None and not _mssql_active:
        _build_pool()

    if _mssql_active:
        cfg = load_config()
        conn = pyodbc.connect(_mssql_conn_str(cfg), timeout=10)
        try:
            with _MssqlDictCursor(conn.cursor()) as cur:
                cur.execute(sql, params or ())
                if cur.cur.description is not None:
                    result = cur.fetchone() if fetchone else cur.fetchall()
                else:
                    result = None if fetchone else []
            conn.commit()
            return result
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            conn.close()
    else:
        assert _pool is not None
        conn = _pool.getconn()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params or ())
                if cur.description is not None:
                    result = cur.fetchone() if fetchone else cur.fetchall()
                else:
                    result = None if fetchone else []
            conn.commit()
            return result
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            _pool.putconn(conn)


def getconn():
    """Legacy path for write helpers that need a raw psycopg2 connection.
    Only usable while PostgreSQL is active."""
    if _pool is None and not _mssql_active:
        _build_pool()
    if _mssql_active:
        raise RuntimeError(
            "Raw connection requested but MSSQL is active. "
            "Writes are not yet wired for MSSQL — switch back to Postgres."
        )
    assert _pool is not None
    return _pool.getconn()


def putconn(conn):
    if _pool is not None:
        _pool.putconn(conn)


# ── Test connection (used by the Configuration page) ────────────────

def test_connection(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """One-shot connection test. Returns {ok, message, elapsed_ms, engine}."""
    engine = cfg.get("engine", "postgresql")
    started = time.time()

    try:
        if engine == "mssql":
            if not PYODBC_AVAILABLE:
                return {
                    "ok": False,
                    "engine": engine,
                    "elapsed_ms": 0,
                    "message": "pyodbc not installed. Run: pip install pyodbc "
                               "(and install Microsoft ODBC Driver 18 on this host).",
                }
            conn = pyodbc.connect(_mssql_conn_str(cfg), timeout=8)
            cur = conn.cursor()
            cur.execute("SELECT @@VERSION")
            version = (cur.fetchone() or [""])[0] or ""
            cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES")
            table_count = (cur.fetchone() or [0])[0]
            conn.close()
            elapsed = int((time.time() - started) * 1000)
            return {
                "ok": True,
                "engine": engine,
                "elapsed_ms": elapsed,
                "message": f"Connected ({elapsed} ms, {table_count} tables)",
                "server_version": (version or "").split("\n")[0].strip()[:120],
            }
        else:
            conn = psycopg2.connect(_pg_dsn(cfg), connect_timeout=8)
            cur = conn.cursor()
            cur.execute("SELECT version()")
            version = (cur.fetchone() or [""])[0] or ""
            cur.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog','information_schema')"
            )
            table_count = (cur.fetchone() or [0])[0]
            conn.close()
            elapsed = int((time.time() - started) * 1000)
            return {
                "ok": True,
                "engine": engine,
                "elapsed_ms": elapsed,
                "message": f"Connected ({elapsed} ms, {table_count} tables)",
                "server_version": (version or "").split(",")[0].strip()[:120],
            }
    except Exception as exc:
        elapsed = int((time.time() - started) * 1000)
        return {
            "ok": False,
            "engine": engine,
            "elapsed_ms": elapsed,
            "message": f"{type(exc).__name__}: {exc}",
        }
