"""Risk management and guardrails for the trading engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from ..config import RiskConfig
from ..db import Database
from ..models import Position, TradeIntent

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RiskAssessment:
    allowed: bool
    reasons: list[str]

    @classmethod
    def ok(cls) -> "RiskAssessment":
        return cls(True, [])

    @classmethod
    def blocked(cls, *reasons: str) -> "RiskAssessment":
        return cls(False, list(reasons))


class RiskManager:
    def __init__(self, config: RiskConfig, database: Database) -> None:
        self.config = config
        self.database = database

    def check_trade(self, intent: TradeIntent, open_positions: Iterable[Position]) -> RiskAssessment:
        reasons: list[str] = []
        if intent.symbol in self.config.halted_symbols:
            reasons.append("symbol halted")
        positions = list(open_positions)
        symbol_positions = [p for p in positions if p.symbol == intent.symbol]
        if len(symbol_positions) >= self.config.max_position_per_symbol:
            reasons.append("symbol position cap reached")
        if len(positions) >= self.config.max_total_positions:
            reasons.append("portfolio position cap reached")
        notional = intent.quantity * intent.entry
        if notional > self.config.max_notional:
            reasons.append("notional exceeds limits")
        risk = abs(intent.entry - intent.stop) * intent.quantity
        if risk > self.config.per_trade_risk:
            reasons.append("per trade risk too high")
        if reasons:
            LOGGER.warning("Risk check blocked %s: %s", intent.symbol, ", ".join(reasons))
            self.database.record_risk_event(intent.symbol, "blocked", "high", "; ".join(reasons))
            return RiskAssessment(False, reasons)
        return RiskAssessment(True, [])

    def check_drawdown(self) -> RiskAssessment:
        stats = self.database.get_trade_stats()
        if abs(stats["realized_pnl"]) > self.config.max_drawdown and stats["realized_pnl"] < 0:
            message = f"Drawdown exceeded: {stats['realized_pnl']:.2f}"
            self.database.record_risk_event("", "drawdown", "critical", message)
            return RiskAssessment(False, [message])
        return RiskAssessment(True, [])

    def assess_portfolio(self, open_positions: Iterable[Position]) -> Mapping[str, float]:
        positions = list(open_positions)
        exposure = sum(p.quantity * p.entry_price for p in positions)
        return {
            "exposure": exposure,
            "max_notional": self.config.max_notional,
            "open_positions": len(positions),
        }
