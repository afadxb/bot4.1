"""Finnhub news and sentiment feed adapter."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable


class FinnhubClient:
    """Return deterministic sentiment snapshots for testing."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def get_headlines(self, symbols: Iterable[str]) -> list[dict[str, object]]:
        if not self.enabled:
            return []
        now = datetime.utcnow()
        headlines: list[dict[str, object]] = []
        for symbol in symbols:
            if hash(symbol) % 3:
                headlines.append(
                    {
                        "symbol": symbol,
                        "headline": f"{symbol} sentiment improves",
                        "source": "finnhub",
                        "sentiment": (hash(symbol) % 100) / 100 - 0.5,
                        "published_at": (now - timedelta(minutes=15)).isoformat(),
                    }
                )
        return headlines
