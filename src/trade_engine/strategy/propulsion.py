"""Intraday strategy implementation using engineered features."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ..config import RiskConfig, StrategyConfig
from ..models import Signal, TradeIntent, Side
from .features_intraday import FeatureSnapshot


@dataclass(slots=True)
class StrategyDecision:
    signal: Signal
    intent: TradeIntent | None


class PropulsionStrategy:
    """Evaluate engineered features to produce ranked trade plans."""

    def __init__(self, strategy: StrategyConfig, risk: RiskConfig) -> None:
        self.strategy = strategy
        self.risk = risk

    def evaluate(self, batch: Iterable[FeatureSnapshot], *, cycle_id: str) -> list[StrategyDecision]:
        decisions: list[StrategyDecision] = []
        for snapshot in batch:
            signal = self._score_snapshot(snapshot, cycle_id=cycle_id)
            intent = self._build_intent(snapshot, signal)
            decisions.append(StrategyDecision(signal=signal, intent=intent))
        decisions.sort(key=lambda decision: decision.signal.final_score, reverse=True)
        for rank, decision in enumerate(decisions, start=1):
            decision.signal.rank = rank
        return decisions

    # ------------------------------------------------------------------ helpers
    def _score_snapshot(self, snapshot: FeatureSnapshot, *, cycle_id: str) -> Signal:
        features = snapshot.features
        last_close = features.get("last_close", 0.0)
        atr = features.get("atr", 0.0)

        base_score = 0.0
        reasons: list[str] = []
        rules: dict[str, bool] = {}

        if features.get("ema_fast", 0.0) > features.get("ema_slow", 0.0):
            base_score += 0.35
            reasons.append("ema_fast_gt_slow")
            rules["ema_trend"] = True
        else:
            base_score -= 0.4
            rules["ema_trend"] = False

        if features.get("ema_slow", 0.0) > features.get("ema_50", 0.0):
            base_score += 0.2
            reasons.append("ema_stack")
            rules["ema_stack"] = True
        else:
            rules["ema_stack"] = False

        if self.strategy.vwap_required:
            if last_close >= features.get("vwap", 0.0):
                base_score += 0.2
                reasons.append("above_vwap")
                rules["above_vwap"] = True
            else:
                base_score -= 0.5
                rules["above_vwap"] = False

        vol_spike = features.get("volume_spike", 0.0)
        if vol_spike >= self.strategy.vol_spike_multiple:
            bump = min(0.25, (vol_spike - self.strategy.vol_spike_multiple) * 0.1)
            base_score += bump
            reasons.append("volume_spike")
            rules["volume_spike"] = True
        else:
            rules["volume_spike"] = False

        consolidation = features.get("consolidation", 1.0)
        if consolidation <= 0.03:
            base_score += 0.15
            reasons.append("tight_range")
            rules["tight_range"] = True
        else:
            rules["tight_range"] = False

        if features.get("has_fresh_catalyst", 0.0):
            base_score += 0.15
            reasons.append("fresh_catalyst")
            rules["fresh_catalyst"] = True
        elif self.strategy.catalyst_required:
            base_score -= 0.3
            rules["fresh_catalyst"] = False

        if self.strategy.enable_supertrend and features.get("supertrend_bullish", 0.0):
            base_score += 0.1
            reasons.append("supertrend")
            rules["supertrend"] = True
        else:
            if self.strategy.enable_supertrend:
                rules["supertrend"] = False

        spread_penalty = features.get("spread_bp", 0.0) / max(1.0, self.risk.spread_penalty_bp)
        if spread_penalty > 0:
            base_score -= spread_penalty
            rules["tight_spread"] = False
        else:
            rules.setdefault("tight_spread", True)

        avg_sentiment = features.get("avg_sentiment", 0.0)
        if avg_sentiment < -0.2:
            cap = max(0.2, abs(avg_sentiment))
            base_score -= cap
            rules["sentiment"] = False
        else:
            rules["sentiment"] = True

        if self.risk.earnings_blackout and features.get("fresh_catalyst_minutes", float("inf")) < 30:
            base_score -= 0.2
            rules["earnings_blackout"] = False
        else:
            rules.setdefault("earnings_blackout", True)

        base_score = max(0.0, min(1.0, base_score))
        entry_hint = last_close
        stop_hint = last_close - atr if atr else last_close * 0.99

        return Signal(
            symbol=snapshot.symbol,
            run_ts=datetime.utcnow(),
            cycle_id=cycle_id,
            entry_hint=entry_hint,
            stop_hint=stop_hint,
            base_score=base_score,
            ai_adj_score=base_score,
            final_score=base_score,
            reasons=tuple(reasons),
            rules_passed={key: bool(value) for key, value in rules.items()},
            features={key: float(value) for key, value in features.items()},
        )

    def _build_intent(self, snapshot: FeatureSnapshot, signal: Signal) -> TradeIntent | None:
        entry = signal.entry_hint or 0.0
        stop = signal.stop_hint or 0.0
        if entry <= 0 or stop <= 0 or math.isclose(entry, stop):
            return None
        risk_per_share = abs(entry - stop)
        risk_budget = self.risk.per_trade_risk
        if risk_budget <= 0 or risk_per_share <= 0:
            return None
        quantity = max(0.0, risk_budget / risk_per_share)
        side = Side.LONG if signal.final_score >= 0.5 else Side.SHORT
        atr = snapshot.features.get("atr", 0.0)
        target = entry + (atr * 2 if side is Side.LONG else -atr * 2)
        metadata = {key: float(value) for key, value in snapshot.features.items()}
        return TradeIntent(
            symbol=snapshot.symbol,
            side=side,
            confidence=min(1.0, signal.final_score),
            quantity=quantity,
            entry=entry,
            stop=stop,
            target=target,
            metadata=metadata,
        )
