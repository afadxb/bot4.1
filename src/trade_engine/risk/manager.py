"""Risk management and guardrails for the trading engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
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

    def check_trade(
        self,
        intent: TradeIntent,
        open_positions: Iterable[Position],
        as_of: datetime,
    ) -> RiskAssessment:
        if not self.config.enable_limits:
            return RiskAssessment.ok()

        reasons: list[str] = []
        positions = list(open_positions)
        trade_count = self.database.count_trades_for_date(as_of.date())
        if trade_count >= self.config.daily_trade_cap:
            reasons.append("daily trade cap reached")

        stop_distance = abs(intent.entry - intent.stop)
        if stop_distance < self.config.min_tick_buffer:
            reasons.append("stop distance below minimum buffer")

        per_trade_limit = self.config.account_equity * self.config.risk_per_trade_pct / 100
        max_risk = stop_distance * abs(intent.quantity)
        if max_risk > per_trade_limit:
            reasons.append("per trade risk limit breached")

        notional = abs(intent.quantity) * abs(intent.entry)
        position_cap = self.config.account_equity * self.config.max_position_value_pct / 100
        if notional > position_cap:
            reasons.append("position value exceeds cap")

        portfolio_exposure = sum(abs(p.quantity) * abs(p.entry_price) for p in positions)
        exposure_limit = self.config.account_equity * self.config.max_portfolio_exposure_pct / 100
        if portfolio_exposure + notional > exposure_limit:
            reasons.append("portfolio exposure limit breached")

        if reasons:
            message = "; ".join(reasons)
            LOGGER.warning("Risk check blocked %s: %s", intent.symbol, message)
            self.database.record_risk_event(intent.symbol, "blocked", "high", message)
            return RiskAssessment.blocked(*reasons)
        return RiskAssessment.ok()

    def check_drawdown(self, since: datetime, max_drawdown_pct: float | None = None) -> RiskAssessment:
        if not self.config.enable_limits:
            return RiskAssessment.ok()
        limit_pct = max_drawdown_pct if max_drawdown_pct is not None else self.config.daily_drawdown_halt_pct
        realized = self.database.realized_pnl_since(since)
        if realized >= 0:
            return RiskAssessment.ok()
        drawdown_pct = abs(realized) / max(self.config.account_equity, 1.0) * 100
        if drawdown_pct >= limit_pct:
            message = f"Daily drawdown {drawdown_pct:.2f}% breached limit {limit_pct:.2f}%"
            LOGGER.error(message)
            self.database.record_risk_event("", "drawdown", "critical", message)
            return RiskAssessment.blocked(message)
        return RiskAssessment.ok()

    def assess_portfolio(self, open_positions: Iterable[Position]) -> Mapping[str, float]:
        positions = list(open_positions)
        exposure = sum(abs(p.quantity) * abs(p.entry_price) for p in positions)
        exposure_limit = self.config.account_equity * self.config.max_portfolio_exposure_pct / 100
        return {
            "exposure": exposure,
            "exposure_limit": exposure_limit,
            "open_positions": len(positions),
        }
