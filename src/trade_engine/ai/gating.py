"""Optional AI overlays for sentiment/regime gating."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping

from ..models import AIOverlay, Signal


@dataclass(slots=True)
class SentimentModel:
    """Deterministic stub sentiment model."""

    def score(self, text: str | None) -> float:
        if not text:
            return 0.0
        val = float(sum(ord(ch) for ch in text) % 100) / 50 - 1
        return max(-1.0, min(1.0, val))


@dataclass(slots=True)
class RegimeModel:
    """Simplistic market regime classifier based on volatility features."""

    def classify(self, features: Mapping[str, float]) -> str:
        vol = features.get("volatility", 0.0)
        atr = features.get("atr", 0.0)
        if vol > 2 * (atr or 1):
            return "volatile"
        if vol < max(0.5, atr * 0.5):
            return "calm"
        return "normal"


class AIGating:
    def __init__(self, sentiment: SentimentModel | None = None, regime: RegimeModel | None = None) -> None:
        self.sentiment_model = sentiment or SentimentModel()
        self.regime_model = regime or RegimeModel()

    def evaluate(
        self,
        symbol: str,
        signal: Signal,
        catalysts: Iterable[Mapping[str, str | float]],
        features: Mapping[str, float],
        require_positive_sentiment: bool,
        require_favorable_regime: bool,
    ) -> AIOverlay:
        sentiment_scores = [self.sentiment_model.score(event.get("headline")) for event in catalysts]
        sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.0
        regime = self.regime_model.classify(features)

        approved = True
        metadata: dict[str, float] = {"sentiment": sentiment, "signal_score": signal.score}
        if require_positive_sentiment and sentiment <= 0:
            approved = False
        if require_favorable_regime and regime == "volatile" and math.fabs(features.get("volatility", 0.0)) > 2:
            approved = False

        return AIOverlay(
            symbol=symbol,
            ts=datetime.utcnow(),
            sentiment=sentiment,
            regime=regime,
            approved=approved,
            metadata=metadata,
        )
