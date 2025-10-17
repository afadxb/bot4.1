"""IBKR market data adapter used by :class:`~trade_engine.data.hub.DataHub`."""

from __future__ import annotations

from typing import Iterable, Sequence

from ...models import Bar
from ..ibkr_client import IBKRClient


class IBKRFeed:
    """Lightweight wrapper around :class:`IBKRClient` for market data."""

    def __init__(self, client: IBKRClient | None = None) -> None:
        self._client = client or IBKRClient()

    def get_bars(self, symbol: str, timeframe: str, lookback: int) -> Sequence[Bar]:
        return self._client.fetch_historical_bars(symbol, timeframe=timeframe, lookback=lookback)

    def get_quotes(self, symbols: Iterable[str]) -> dict[str, float]:
        quotes: dict[str, float] = {}
        for symbol in symbols:
            bars = self.get_bars(symbol, timeframe="1m", lookback=1)
            quotes[symbol] = bars[-1].close if bars else 0.0
        return quotes

    def ensure_connection(self) -> None:
        self._client.ensure_connection()
