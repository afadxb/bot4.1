"""SQLite persistence helpers and migrations."""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS watchlist (
        symbol TEXT PRIMARY KEY,
        name TEXT,
        sector TEXT,
        enabled INTEGER DEFAULT 1,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS bars_cache (
        symbol TEXT,
        timeframe TEXT,
        ts DATETIME,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        PRIMARY KEY (symbol, timeframe, ts)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        ts DATETIME,
        signal_type TEXT,
        score REAL,
        strength REAL,
        metadata TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_overlays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        ts DATETIME,
        sentiment REAL,
        regime TEXT,
        approved INTEGER DEFAULT 0,
        metadata TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        direction TEXT,
        qty REAL,
        entry_price REAL,
        stop_price REAL,
        target_price REAL,
        status TEXT,
        opened_at DATETIME,
        closed_at DATETIME,
        realized_pnl REAL,
        notes TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP,
        symbol TEXT,
        event_type TEXT,
        severity TEXT,
        message TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS journals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP,
        category TEXT,
        message TEXT,
        payload TEXT
    );
    """,
)


class Database:
    """SQLite wrapper with automatic migrations and convenience helpers."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self.apply_migrations()

    def apply_migrations(self) -> None:
        cur = self._conn.cursor()
        for migration in MIGRATIONS:
            cur.executescript(migration)
        self._conn.commit()

    @contextlib.contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
        finally:
            self._conn.commit()

    def fetch_watchlist(self, limit: Optional[int] = None) -> list[sqlite3.Row]:
        query = "SELECT symbol, name, sector FROM watchlist WHERE enabled = 1 ORDER BY symbol"
        if limit:
            query += " LIMIT ?"
            params: Iterable[object] = (limit,)
        else:
            params = ()
        with self.connection() as conn:
            cur = conn.execute(query, params)
            return list(cur.fetchall())

    def upsert_watchlist(self, entries: Iterable[tuple[str, str | None, str | None]]) -> None:
        sql = (
            "INSERT INTO watchlist (symbol, name, sector, enabled) "
            "VALUES (?, ?, ?, 1) "
            "ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, sector=excluded.sector, "
            "enabled=1, updated_at=CURRENT_TIMESTAMP"
        )
        with self.connection() as conn:
            conn.executemany(sql, entries)

    def record_signal(
        self,
        symbol: str,
        ts: str,
        signal_type: str,
        score: float,
        strength: float,
        metadata: str,
    ) -> None:
        sql = (
            "INSERT INTO signals (symbol, ts, signal_type, score, strength, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        with self.connection() as conn:
            conn.execute(sql, (symbol, ts, signal_type, score, strength, metadata))

    def record_ai_overlay(
        self,
        symbol: str,
        ts: str,
        sentiment: float,
        regime: str,
        approved: bool,
        metadata: str,
    ) -> None:
        sql = (
            "INSERT INTO ai_overlays (symbol, ts, sentiment, regime, approved, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        with self.connection() as conn:
            conn.execute(sql, (symbol, ts, sentiment, regime, int(approved), metadata))

    def record_trade(
        self,
        symbol: str,
        direction: str,
        qty: float,
        entry_price: float,
        stop_price: float,
        target_price: float,
        status: str,
        notes: str,
    ) -> int:
        sql = (
            "INSERT INTO trades (symbol, direction, qty, entry_price, stop_price, target_price, status, opened_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)"
        )
        with self.connection() as conn:
            cur = conn.execute(
                sql,
                (symbol, direction, qty, entry_price, stop_price, target_price, status, notes),
            )
            return int(cur.lastrowid)

    def close_trade(self, trade_id: int, exit_price: float, pnl: float, notes: str = "") -> None:
        sql = (
            "UPDATE trades SET status = ?, closed_at = CURRENT_TIMESTAMP, realized_pnl = ?, notes = ? "
            "WHERE id = ?"
        )
        with self.connection() as conn:
            conn.execute(sql, ("closed", pnl, notes, trade_id))

    def record_risk_event(self, symbol: str, event_type: str, severity: str, message: str) -> None:
        sql = (
            "INSERT INTO risk_events (symbol, event_type, severity, message) "
            "VALUES (?, ?, ?, ?)"
        )
        with self.connection() as conn:
            conn.execute(sql, (symbol, event_type, severity, message))

    def log(self, category: str, message: str, payload: str = "") -> None:
        sql = "INSERT INTO journals (category, message, payload) VALUES (?, ?, ?)"
        with self.connection() as conn:
            conn.execute(sql, (category, message, payload))

    def get_open_trades(self) -> list[sqlite3.Row]:
        with self.connection() as conn:
            cur = conn.execute("SELECT * FROM trades WHERE status = 'open'")
            return list(cur.fetchall())

    def get_trade_stats(self) -> dict[str, float]:
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0), COUNT(*) FROM trades WHERE closed_at IS NOT NULL"
            )
            pnl, count = cur.fetchone()
            return {"realized_pnl": float(pnl or 0.0), "closed_trades": float(count or 0)}

    def count_trades_for_date(self, target: date) -> int:
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM trades WHERE DATE(opened_at) = ?",
                (target.isoformat(),),
            )
            result = cur.fetchone()
            return int(result[0] if result and result[0] is not None else 0)

    def realized_pnl_since(self, since: datetime) -> float:
        with self.connection() as conn:
            cur = conn.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades WHERE closed_at IS NOT NULL AND closed_at >= ?",
                (since.isoformat(),),
            )
            (value,) = cur.fetchone()
            return float(value or 0.0)
