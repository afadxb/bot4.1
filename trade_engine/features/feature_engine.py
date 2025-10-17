"""Feature engineering utilities for the intraday strategy."""

from __future__ import annotations

import statistics
from collections import deque
from typing import Iterable, Mapping

from ..models import Bar


class FeatureEngine:
    """Compute deterministic features from price/volume history."""

    def build_features(self, bars: Iterable[Bar]) -> Mapping[str, float]:
        recent = list(bars)
        if not recent:
            return {"sma": 0.0, "ema": 0.0, "rsi": 50.0, "atr": 0.0}

        closes = [bar.close for bar in recent]
        highs = [bar.high for bar in recent]
        lows = [bar.low for bar in recent]

        sma = sum(closes[-5:]) / min(5, len(closes))
        ema = self._ema(closes)
        rsi = self._rsi(closes)
        atr = self._atr(highs, lows, closes)

        return {
            "last_close": closes[-1],
            "sma": sma,
            "ema": ema,
            "rsi": rsi,
            "atr": atr,
            "momentum": closes[-1] - closes[0],
            "volatility": statistics.pstdev(closes) if len(closes) > 1 else 0.0,
        }

    def _ema(self, values: list[float], period: int = 10) -> float:
        if not values:
            return 0.0
        alpha = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = alpha * value + (1 - alpha) * ema
        return ema

    def _rsi(self, closes: list[float], period: int = 14) -> float:
        if len(closes) < 2:
            return 50.0
        gains: deque[float] = deque(maxlen=period)
        losses: deque[float] = deque(maxlen=period)
        for prev, curr in zip(closes, closes[1:]):
            delta = curr - prev
            if delta >= 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
        avg_gain = sum(gains) / (len(gains) or 1)
        avg_loss = sum(losses) / (len(losses) or 1)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _atr(self, highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
        if not closes:
            return 0.0
        trs: deque[float] = deque(maxlen=period)
        prev_close = closes[0]
        for high, low, close in zip(highs, lows, closes):
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        return sum(trs) / len(trs)
