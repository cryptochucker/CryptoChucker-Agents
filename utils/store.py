from __future__ import annotations

import json
import sqlite3
from typing import Any


_DDL = """
CREATE TABLE IF NOT EXISTS signals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol    TEXT    NOT NULL,
    tf        TEXT    NOT NULL,
    state     TEXT    NOT NULL,
    strength  REAL,
    price     REAL,
    ts        TEXT    DEFAULT (datetime('now')),
    extra     TEXT
);

CREATE TABLE IF NOT EXISTS scans (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT    DEFAULT (datetime('now')),
    payload   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT    NOT NULL,
    mode         TEXT    NOT NULL DEFAULT 'paper',
    side         TEXT    NOT NULL DEFAULT 'long',
    entry_price  REAL,
    qty          REAL,
    stop_price   REAL,
    opened_at    TEXT    DEFAULT (datetime('now')),
    closed_at    TEXT,
    status       TEXT    DEFAULT 'open',
    extra        TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol       TEXT    NOT NULL,
    mode         TEXT    NOT NULL DEFAULT 'paper',
    side         TEXT    NOT NULL,
    entry_price  REAL,
    exit_price   REAL,
    qty          REAL,
    pnl          REAL,
    fee          REAL,
    opened_at    TEXT,
    closed_at    TEXT    DEFAULT (datetime('now')),
    extra        TEXT
);

CREATE TABLE IF NOT EXISTS equity (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT    DEFAULT (datetime('now')),
    balance  REAL    NOT NULL
);
"""


class Store:
    """SQLite persistence layer using stdlib sqlite3.

    Args:
        path: File system path for the SQLite database. Use ':memory:' for in-memory.
    """

    def __init__(self, path: str = "data/cryptochucker.db") -> None:
        self._path = path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Create tables (idempotent)."""
        import os

        if self._path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_DDL)

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def save_signal(self, data: dict[str, Any]) -> None:
        extra = {k: v for k, v in data.items() if k not in {"symbol", "tf", "state", "strength", "price"}}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO signals (symbol, tf, state, strength, price, extra) VALUES (?,?,?,?,?,?)",
                (
                    data.get("symbol"),
                    data.get("tf"),
                    data.get("state"),
                    data.get("strength"),
                    data.get("price"),
                    json.dumps(extra) if extra else None,
                ),
            )

    def load_signals(self, limit: int = 500) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Scans
    # ------------------------------------------------------------------

    def save_scan(self, payload: Any) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO scans (payload) VALUES (?)", (json.dumps(payload),))

    def load_scans(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def save_position(self, data: dict[str, Any]) -> int:
        keys = ["symbol", "mode", "side", "entry_price", "qty", "stop_price"]
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO positions (symbol, mode, side, entry_price, qty, stop_price, extra) VALUES (?,?,?,?,?,?,?)",
                tuple(data.get(k) for k in keys) + (json.dumps({k: v for k, v in data.items() if k not in keys}) or None,),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def load_positions(self, status: str = "open") -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE status=? ORDER BY id DESC", (status,)
            ).fetchall()
        return [dict(r) for r in rows]

    def close_position(self, position_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE positions SET status='closed', closed_at=datetime('now') WHERE id=?",
                (position_id,),
            )

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def save_trade(self, data: dict[str, Any]) -> None:
        keys = ["symbol", "mode", "side", "entry_price", "exit_price", "qty", "pnl", "fee", "opened_at"]
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO trades (symbol, mode, side, entry_price, exit_price, qty, pnl, fee, opened_at, extra)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                tuple(data.get(k) for k in keys)
                + (json.dumps({k: v for k, v in data.items() if k not in keys}) or None,),
            )

    def load_trades(self, limit: int = 500) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Equity
    # ------------------------------------------------------------------

    def save_equity(self, balance: float) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO equity (balance) VALUES (?)", (balance,))

    def load_equity(self, limit: int = 1000) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM equity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn
