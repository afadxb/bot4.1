"""SQLite persistence helpers and migrations."""

from __future__ import annotations

import contextlib
import json
import sqlite3
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
    CREATE TABLE IF NOT EXISTS journals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP,
        category TEXT,
        message TEXT,
        payload TEXT
    );
    """,
)

MIGRATIONS_DIR = Path(__file__).with_name("storage").joinpath("migrations")


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
        if MIGRATIONS_DIR.exists():
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                cur.executescript(path.read_text())
        self._conn.commit()

    @contextlib.contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
        finally:
            self._conn.commit()

    # ------------------------------------------------------------------ watchlist helpers
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

    # ------------------------------------------------------------------ signal capture
    def record_signal(
        self,
        *,
        symbol: str,
        run_ts: str,
        cycle_id: str,
        base_score: float,
        ai_adj_score: float,
        final_score: float,
        rank: int | None,
        reasons_text: str,
        rules_passed_json: str,
        features_json: str,
    ) -> None:
        sql = (
            "INSERT INTO signals (symbol, run_ts, features_json, rules_passed_json, base_score, ai_adj_score, final_score, rank, reasons_text, cycle_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    symbol,
                    run_ts,
                    features_json,
                    rules_passed_json,
                    base_score,
                    ai_adj_score,
                    final_score,
                    rank,
                    reasons_text,
                    cycle_id,
                ),
            )

    def record_ai_provenance(
        self,
        *,
        symbol: str,
        run_ts: str,
        source: str,
        sentiment_score: float,
        sentiment_label: str,
        meta_json: str,
    ) -> None:
        sql = (
            "INSERT INTO ai_provenance (symbol, run_ts, source, sentiment_score, sentiment_label, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    symbol,
                    run_ts,
                    source,
                    sentiment_score,
                    sentiment_label,
                    meta_json,
                ),
            )

    # ------------------------------------------------------------------ trade journal
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

    # ------------------------------------------------------------------ risk telemetry
    def record_risk_event(
        self,
        *,
        event_type: str,
        session: str | None = None,
        symbol: str | None = None,
        value: float | None = None,
        meta: dict[str, object] | None = None,
    ) -> None:
        sql = "INSERT INTO risk_events (session, type, symbol, value, meta_json) VALUES (?, ?, ?, ?, ?)"
        payload = json.dumps(meta or {})
        with self.connection() as conn:
            conn.execute(sql, (session, event_type, symbol, value, payload))

    def log(self, category: str, message: str, payload: str = "") -> None:
        sql = "INSERT INTO journals (category, message, payload) VALUES (?, ?, ?)"
        with self.connection() as conn:
            conn.execute(sql, (category, message, payload))

    # ------------------------------------------------------------------ analytics
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

    def get_latest_equity(self) -> dict[str, float] | None:
        sql = (
            "SELECT starting_equity, realized_pnl, unrealized_pnl FROM metrics_equity ORDER BY ts DESC LIMIT 1"
        )
        with self.connection() as conn:
            cur = conn.execute(sql)
            row = cur.fetchone()
            if not row:
                return None
            return {
                "starting_equity": float(row["starting_equity"]),
                "realized_pnl": float(row["realized_pnl"]),
                "unrealized_pnl": float(row["unrealized_pnl"]),
            }
