"""Dashboard data helpers for Streamlit or other viewers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from ..db import Database


class DashboardData:
    """Utility helpers to fetch dashboard friendly payloads."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def signals(self) -> List[dict[str, object]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT symbol, run_ts, base_score, ai_adj_score, final_score, rank, reasons_text, cycle_id FROM signals ORDER BY run_ts DESC LIMIT 200"
            ).fetchall()
        return [dict(row) for row in rows]

    def ai_overlays(self) -> List[dict[str, object]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT symbol, run_ts, source, sentiment_score, sentiment_label, meta_json FROM ai_provenance ORDER BY run_ts DESC LIMIT 200"
            ).fetchall()
        return [dict(row) for row in rows]

    def risk_events(self) -> List[dict[str, object]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT ts, session, type, symbol, value, meta_json FROM risk_events ORDER BY ts DESC LIMIT 200"
            ).fetchall()
        return [dict(row) for row in rows]

    def trades(self) -> List[dict[str, object]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                "SELECT symbol, direction, qty, entry_price, stop_price, target_price, status, opened_at, closed_at, realized_pnl FROM trades ORDER BY opened_at DESC LIMIT 200"
            ).fetchall()
        return [dict(row) for row in rows]


def export_json(database: Database, path: str | Path) -> None:
    payload: dict[str, Iterable[dict[str, str | float]]] = {}
    queries = {
        "signals": "SELECT * FROM signals ORDER BY run_ts DESC LIMIT 200",
        "ai_provenance": "SELECT * FROM ai_provenance ORDER BY run_ts DESC LIMIT 200",
        "risk_events": "SELECT * FROM risk_events ORDER BY ts DESC LIMIT 200",
        "trades": "SELECT * FROM trades ORDER BY opened_at DESC LIMIT 200",
    }
    with database.connection() as conn:
        for table, query in queries.items():
            rows = conn.execute(query).fetchall()
            payload[table] = [dict(row) for row in rows]
    Path(path).write_text(json.dumps(payload, indent=2))
