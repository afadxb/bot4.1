"""Rule based strategy core that scores and ranks opportunities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Sequence

from ..models import Signal, TradeIntent, Side

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class StrategyRule:
    name: str
    weight: float

    def evaluate(self, features: Mapping[str, float]) -> float:
        raise NotImplementedError


@dataclass(slots=True)
class MomentumRule(StrategyRule):
    threshold: float = 0.0

    def evaluate(self, features: Mapping[str, float]) -> float:
        momentum = features.get("momentum", 0.0)
        score = max(0.0, momentum - self.threshold)
        LOGGER.debug("Momentum rule %s -> %s", self.name, score)
        return score


@dataclass(slots=True)
class MeanReversionRule(StrategyRule):
    def evaluate(self, features: Mapping[str, float]) -> float:
        sma = features.get("sma", 0.0)
        last = features.get("last_close", 0.0)
        diff = sma - last
        score = diff
        LOGGER.debug("Mean reversion rule %s -> %s", self.name, score)
        return score


@dataclass(slots=True)
class RSIRule(StrategyRule):
    lower_bound: float = 30
    upper_bound: float = 70

    def evaluate(self, features: Mapping[str, float]) -> float:
        rsi = features.get("rsi", 50.0)
        if rsi < self.lower_bound:
            return (self.lower_bound - rsi) / self.lower_bound
        if rsi > self.upper_bound:
            return -((rsi - self.upper_bound) / (100 - self.upper_bound))
        return 0.0


class StrategyEngine:
    def __init__(self, rules: Sequence[StrategyRule] | None = None) -> None:
        if rules is None:
            rules = (
                MomentumRule(name="momentum", weight=0.4, threshold=0.5),
                MeanReversionRule(name="mean_reversion", weight=0.2),
                RSIRule(name="rsi", weight=0.4),
            )
        self.rules = rules

    def evaluate(self, symbol: str, features: Mapping[str, float]) -> Signal:
        score = 0.0
        contributions: dict[str, float] = {}
        for rule in self.rules:
            value = rule.evaluate(features)
            contributions[rule.name] = value * rule.weight
            score += contributions[rule.name]
        LOGGER.debug("Aggregated score for %s -> %s", symbol, score)
        base_score = max(0.0, min(1.0, (score + 1) / 2))
        return Signal(
            symbol=symbol,
            run_ts=datetime.utcnow(),
            cycle_id="strategy_engine",
            entry_hint=features.get("last_close"),
            stop_hint=features.get("last_close", 0.0) - features.get("atr", 0.0),
            base_score=base_score,
            ai_adj_score=base_score,
            final_score=base_score,
            reasons=tuple(contributions.keys()),
            rules_passed={name: value >= 0 for name, value in contributions.items()},
            features={k: float(v) for k, v in features.items()},
        )

    def rank(self, signals: Iterable[tuple[str, Mapping[str, float]]]) -> list[tuple[Signal, TradeIntent]]:
        scored: list[tuple[Signal, TradeIntent]] = []
        for symbol, features in signals:
            signal = self.evaluate(symbol, features)
            side = Side.LONG if signal.final_score >= 0.5 else Side.SHORT
            quantity = signal.final_score * 10
            intent = TradeIntent(
                symbol=symbol,
                side=side,
                confidence=signal.final_score,
                quantity=quantity,
                entry=features.get("last_close", 0.0),
                stop=features.get("last_close", 0.0) - features.get("atr", 0.0) * (1 if side == Side.LONG else -1),
                target=features.get("last_close", 0.0) + features.get("atr", 0.0) * (2 if side == Side.LONG else -2),
                metadata=signal.features,
            )
            scored.append((signal, intent))
        scored.sort(key=lambda item: item[0].final_score, reverse=True)
        return scored
