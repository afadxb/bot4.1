"""Intraday feature construction utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from ..config import StrategyConfig
from ..data.hub import Headline
from ..models import Bar


@dataclass(slots=True)
class FeatureSnapshot:
    symbol: str
    bars: Sequence[Bar]
    features: Mapping[str, float]
    catalysts: Sequence[Headline] = field(default_factory=tuple)
    fundamentals: Mapping[str, float] = field(default_factory=dict)


class IntradayFeatureBuilder:
    """Build the deterministic indicator set required by the strategy."""

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config

    def build(
        self,
        symbol: str,
        bars: Sequence[Bar],
        *,
        fundamentals: Mapping[str, float] | None = None,
        catalysts: Sequence[Headline] | None = None,
    ) -> FeatureSnapshot:
        features = self._compute_indicators(bars)
        if fundamentals:
            features.update({f"fund_{key}": float(value) for key, value in fundamentals.items()})
        if catalysts:
            latest = max((event.published_at for event in catalysts), default=None)
            if latest:
                age_minutes = max(0.0, (datetime.utcnow() - latest).total_seconds() / 60)
                features["fresh_catalyst_minutes"] = age_minutes
                features["has_fresh_catalyst"] = 1.0 if age_minutes <= 120 else 0.0
            avg_sentiment = sum(event.sentiment for event in catalysts) / len(catalysts)
            features["avg_sentiment"] = avg_sentiment
        else:
            features["fresh_catalyst_minutes"] = 1e9
            features["has_fresh_catalyst"] = 0.0
            features["avg_sentiment"] = 0.0
        return FeatureSnapshot(
            symbol=symbol,
            bars=bars,
            features=features,
            catalysts=catalysts or tuple(),
            fundamentals=fundamentals or {},
        )

    # ------------------------------------------------------------------ helpers
    def _compute_indicators(self, bars: Sequence[Bar]) -> dict[str, float]:
        if not bars:
            return {
                "last_close": 0.0,
                "ema_fast": 0.0,
                "ema_slow": 0.0,
                "ema_50": 0.0,
                "ema_bias": 0.0,
                "vwap": 0.0,
                "atr": 0.0,
                "rsi": 50.0,
                "volume_spike": 0.0,
                "consolidation": 0.0,
                "supertrend_bullish": 0.0,
                "spread_bp": 0.0,
            }
        closes = [bar.close for bar in bars]
        highs = [bar.high for bar in bars]
        lows = [bar.low for bar in bars]
        volumes = [bar.volume for bar in bars]

        ema_fast = self._ema(closes, self.config.ema_fast)
        ema_slow = self._ema(closes, self.config.ema_slow)
        ema_50 = self._ema(closes, max(self.config.ema_bias, 1))
        last_close = closes[-1]
        vwap = self._vwap(bars)
        atr = self._atr(highs, lows, closes)
        rsi = self._rsi(closes)
        volume_spike = self._volume_spike(volumes)
        consolidation = self._consolidation(highs, lows, last_close)
        supertrend_bullish = 1.0 if self._supertrend(bars) else 0.0
        spread_bp = max(0.0, (highs[-1] - lows[-1]) / last_close * 10_000 if last_close else 0.0)

        return {
            "last_close": last_close,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_50": ema_50,
            "ema_bias": ema_fast - ema_slow,
            "vwap": vwap,
            "atr": atr,
            "rsi": rsi,
            "volume_spike": volume_spike,
            "consolidation": consolidation,
            "supertrend_bullish": supertrend_bullish,
            "spread_bp": spread_bp,
        }

    def _ema(self, values: Sequence[float], period: int) -> float:
        if not values:
            return 0.0
        alpha = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = alpha * value + (1 - alpha) * ema
        return ema

    def _vwap(self, bars: Sequence[Bar]) -> float:
        cumulative_price_volume = sum(bar.close * bar.volume for bar in bars)
        cumulative_volume = sum(bar.volume for bar in bars) or 1.0
        return cumulative_price_volume / cumulative_volume

    def _atr(self, highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14) -> float:
        if not closes:
            return 0.0
        trs: list[float] = []
        prev_close = closes[0]
        for high, low, close in zip(highs, lows, closes):
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        window = trs[-period:]
        return sum(window) / len(window)

    def _rsi(self, closes: Sequence[float], period: int = 14) -> float:
        if len(closes) < 2:
            return 50.0
        gains: list[float] = []
        losses: list[float] = []
        for prev, curr in zip(closes, closes[1:]):
            delta = curr - prev
            if delta >= 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))
        avg_gain = sum(gains[-period:]) / max(1, min(period, len(gains)))
        avg_loss = sum(losses[-period:]) / max(1, min(period, len(losses)))
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _volume_spike(self, volumes: Sequence[float], lookback: int = 20) -> float:
        if not volumes:
            return 0.0
        window = volumes[-lookback:]
        if len(window) <= 1:
            return 0.0
        avg = sum(window[:-1]) / max(1, len(window) - 1)
        if avg == 0:
            return 0.0
        return window[-1] / avg

    def _consolidation(self, highs: Sequence[float], lows: Sequence[float], last_close: float) -> float:
        if not highs or not lows or not last_close:
            return 0.0
        window_high = max(highs[-self.config.consolidation_lookback :])
        window_low = min(lows[-self.config.consolidation_lookback :])
        return (window_high - window_low) / last_close

    def _supertrend(self, bars: Sequence[Bar]) -> bool:
        if not bars or not self.config.enable_supertrend:
            return False
        atr = self._atr([bar.high for bar in bars], [bar.low for bar in bars], [bar.close for bar in bars], self.config.supertrend.atr_period)
        hl2 = (bars[-1].high + bars[-1].low) / 2
        trend = hl2 - self.config.supertrend.atr_mult * atr
        return bars[-1].close >= trend
