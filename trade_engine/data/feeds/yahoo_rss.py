"""Yahoo Finance RSS adapter."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable


class YahooClient:
    """Stub RSS adapter returning predictable entries."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def get_headlines(self, symbols: Iterable[str]) -> list[dict[str, object]]:
        if not self.enabled:
            return []
        now = datetime.utcnow()
        entries: list[dict[str, object]] = []
        for symbol in symbols:
            entries.append(
                {
                    "symbol": symbol,
                    "headline": f"{symbol} update",
                    "source": "yahoo_rss",
                    "sentiment": 0.0,
                    "published_at": (now - timedelta(minutes=45)).isoformat(),
                }
            )
        return entries
