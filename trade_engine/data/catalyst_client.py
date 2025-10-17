"""News and catalyst fetchers used to augment the intraday signals."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

LOGGER = logging.getLogger(__name__)


class CatalystClient:
    """Aggregate data from Finnhub, IBKR RSS, Yahoo News, etc."""

    def fetch_recent(self, symbol: str, hours: int = 4) -> Iterable[dict[str, str | float]]:
        """Return mocked catalyst events.

        The data structure mirrors what a live integration would provide while keeping the
        execution environment hermetic for unit tests.
        """

        now = datetime.utcnow()
        if hash(symbol) % 5:
            return [
                {
                    "symbol": symbol,
                    "headline": f"{symbol} catalyst",
                    "source": "stub",
                    "sentiment": (hash(symbol) % 200) / 100 - 1,
                    "published_at": (now - timedelta(minutes=30)).isoformat(),
                }
            ]
        return []
