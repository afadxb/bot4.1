"""Unified market data access used by the intraday orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, MutableMapping, Sequence

from ..config import FeedsConfig
from ..db import Database
from ..models import Bar
from .feeds import FinnhubClient, IBKRFeed, YahooClient


@dataclass(slots=True)
class Headline:
    symbol: str
    headline: str
    source: str
    sentiment: float
    published_at: datetime


class DataHub:
    """Provide cached access to bars, quotes, and catalysts."""

    def __init__(
        self,
        database: Database,
        feeds: FeedsConfig,
        *,
        ibkr: IBKRFeed | None = None,
        finnhub: FinnhubClient | None = None,
        yahoo: YahooClient | None = None,
    ) -> None:
        self._database = database
        self._ibkr = ibkr or IBKRFeed()
        self._finnhub = finnhub or FinnhubClient(enabled=feeds.finnhub.enable)
        self._yahoo = yahoo or YahooClient(enabled=feeds.yahoo_rss.enable)
        self._retention_minutes: MutableMapping[str, int] = {
            "1m": 720,  # 12 hours
            "5m": 5 * 24 * 12,  # five days
            "15m": 10 * 24 * 4,
        }

    # ------------------------------------------------------------------ bars
    def get_bars(
        self,
        symbols: Sequence[str],
        tf: str,
        lookback_min: int,
        *,
        cache: bool = True,
    ) -> dict[str, list[Bar]]:
        bars: dict[str, list[Bar]] = {}
        for symbol in symbols:
            cached: list[Bar] = []
            if cache:
                cached = self._load_cached_bars(symbol, tf, lookback_min)
            if len(cached) >= lookback_min:
                bars[symbol] = cached[-lookback_min:]
                continue
            fetched = list(self._ibkr.get_bars(symbol, timeframe=tf, lookback=max(lookback_min, 50)))
            if cache:
                self._store_bars(fetched)
            bars[symbol] = fetched[-lookback_min:]
        return bars

    def _load_cached_bars(self, symbol: str, timeframe: str, lookback: int) -> list[Bar]:
        with self._database.connection() as conn:
            cur = conn.execute(
                "SELECT ts, open, high, low, close, volume FROM bars_cache "
                "WHERE symbol = ? AND timeframe = ? ORDER BY ts DESC LIMIT ?",
                (symbol, timeframe, lookback),
            )
            rows = cur.fetchall()
        result: list[Bar] = []
        for row in reversed(rows):
            result.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=datetime.fromisoformat(row["ts"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            )
        return result

    def _store_bars(self, bars: Sequence[Bar]) -> None:
        if not bars:
            return
        timeframe = bars[0].timeframe
        self._prune_cache(timeframe)
        payload = [
            (
                bar.symbol,
                bar.timeframe,
                bar.ts.isoformat(),
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
            )
            for bar in bars
        ]
        with self._database.connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO bars_cache (symbol, timeframe, ts, open, high, low, close, volume)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                payload,
            )

    def _prune_cache(self, timeframe: str) -> None:
        retention = self._retention_minutes.get(timeframe)
        if not retention:
            return
        cutoff = datetime.utcnow() - timedelta(minutes=retention)
        with self._database.connection() as conn:
            conn.execute(
                "DELETE FROM bars_cache WHERE timeframe = ? AND ts < ?",
                (timeframe, cutoff.isoformat()),
            )

    # ----------------------------------------------------------------- quotes
    def get_quotes(self, symbols: Sequence[str]) -> dict[str, float]:
        self._ibkr.ensure_connection()
        return self._ibkr.get_quotes(symbols)

    # --------------------------------------------------------------- catalysts
    def get_headlines(self, symbols: Sequence[str]) -> dict[str, list[Headline]]:
        streams: list[Iterable[Mapping[str, object]]] = []
        streams.append(self._yahoo.get_headlines(symbols))
        finnhub_events = self._finnhub.get_headlines(symbols)
        if finnhub_events:
            streams.append(finnhub_events)
        merged = self.merge_catalysts(*streams)
        by_symbol: dict[str, list[Headline]] = {symbol: [] for symbol in symbols}
        for headline in merged:
            by_symbol.setdefault(headline.symbol, []).append(headline)
        return by_symbol

    @staticmethod
    def merge_catalysts(*streams: Iterable[Mapping[str, object]]) -> list[Headline]:
        dedup: dict[tuple[str, str], Headline] = {}
        for stream in streams:
            for item in stream:
                symbol = str(item.get("symbol"))
                headline = str(item.get("headline"))
                key = (symbol, headline)
                published_raw = item.get("published_at")
                if isinstance(published_raw, datetime):
                    published = published_raw
                else:
                    published = datetime.fromisoformat(str(published_raw))
                candidate = Headline(
                    symbol=symbol,
                    headline=headline,
                    source=str(item.get("source", "unknown")),
                    sentiment=float(item.get("sentiment", 0.0)),
                    published_at=published,
                )
                existing = dedup.get(key)
                if existing is None or existing.published_at < candidate.published_at:
                    dedup[key] = candidate
        sorted_items = sorted(dedup.values(), key=lambda item: item.published_at, reverse=True)
        return sorted_items
