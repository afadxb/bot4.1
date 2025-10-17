"""Optional AI overlays for sentiment and regime gating layers."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
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
        metadata: dict[str, float] = {
            "sentiment": sentiment,
            "signal_base_score": signal.base_score,
            "signal_final_score": signal.final_score,
        }
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


def _decay_sentiment(raw: float, age_minutes: float, decay_hours: float) -> float:
    half_life_minutes = max(1.0, decay_hours * 60)
    decay_factor = math.exp(-age_minutes / half_life_minutes)
    return raw * decay_factor


def adjust_scores(
    signals: list[Signal],
    provenance_store,
    *,
    decay_hours: float = 12.0,
    min_headlines: int = 1,
    weak_setup_threshold: float = 0.55,
) -> list[Signal]:
    """Apply FinBERT sentiment overlays and persist provenance.

    Args:
        signals: Ranked signals awaiting AI adjustments.
        provenance_store: Persistence layer exposing ``record_ai_provenance``.
        decay_hours: Exponential decay horizon for sentiment scores.
        min_headlines: Minimum catalysts before trusting sentiment fully.
        weak_setup_threshold: Score threshold for soft veto consideration.
    """

    adjusted: list[Signal] = []
    for signal in signals:
        features = signal.features
        avg_sentiment = float(features.get("avg_sentiment", 0.0) or 0.0)
        age_minutes = float(features.get("fresh_catalyst_minutes", 0.0) or 0.0)
        headline_count = int(features.get("headline_count", 0))

        decayed = _decay_sentiment(avg_sentiment, age_minutes, decay_hours)
        if headline_count < min_headlines:
            decayed *= 0.5

        ai_adj = signal.base_score
        updated = signal
        sentiment_label = "neutral"

        if decayed < -0.4 and signal.base_score <= weak_setup_threshold:
            ai_adj = max(0.0, signal.base_score * 0.4)
            updated = replace(signal, reasons=signal.reasons + ("ai_soft_veto",))
            sentiment_label = "soft_veto"
        else:
            ai_adj = max(0.0, min(1.0, signal.base_score + decayed * 0.1))
            sentiment_label = "bullish" if decayed > 0 else "bearish" if decayed < 0 else "neutral"

        final_score = ai_adj
        updated = updated.with_scores(ai_adj_score=ai_adj, final_score=final_score)
        adjusted.append(updated)

        provenance_store.record_ai_provenance(
            symbol=signal.symbol,
            run_ts=signal.run_ts.isoformat(),
            source="finbert",
            sentiment_score=decayed,
            sentiment_label=sentiment_label,
            meta_json=json.dumps(
                {
                    "raw_sentiment": avg_sentiment,
                    "decayed": decayed,
                    "age_minutes": age_minutes,
                    "headline_count": headline_count,
                    "base_score": signal.base_score,
                    "ai_adj_score": ai_adj,
                }
            ),
        )

    return adjusted
