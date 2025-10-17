"""Risk management and guardrails for the trading engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence, Tuple

from ..config import RiskConfig
from ..db import Database
from ..models import PlannedOrder, Position, Signal

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
    """Apply configurable risk guardrails at different pipeline stages."""

    def __init__(self, config: RiskConfig, database: Database) -> None:
        self.config = config
        self.database = database

    # ------------------------------------------------------------------ logging helpers
    def log_risk_event(
        self,
        event_type: str,
        *,
        symbol: str | None = None,
        value: float | None = None,
        meta: Mapping[str, object] | None = None,
        session: str | None = None,
    ) -> None:
        self.database.record_risk_event(
            event_type=event_type,
            symbol=symbol,
            value=value,
            meta=dict(meta or {}),
            session=session,
        )

    # ------------------------------------------------------------------ upstream guards
    def apply_guardrails(self, signal: Signal) -> Tuple[RiskAssessment, Signal]:
        """Evaluate scorer-level guardrails and veto if necessary."""

        reasons: list[str] = []
        features = signal.features
        updated_signal = signal

        if self.config.illiquidity_veto:
            avg_volume = float(features.get("avg_volume", 0.0))
            if avg_volume and avg_volume < 250_000:
                reasons.append("illiquidity_veto")

        spread_bp = float(features.get("spread_bp", 0.0))
        if spread_bp > self.config.spread_penalty_bp:
            reasons.append("spread_too_wide")

        if self.config.earnings_blackout:
            minutes_to_catalyst = float(features.get("fresh_catalyst_minutes", 1e9))
            if minutes_to_catalyst < 60:
                mode = self.config.earnings_blackout_mode.lower()
                if mode == "veto":
                    reasons.append("earnings_blackout_veto")
                elif mode == "cap" and signal.final_score > 0.6:
                    updated_signal = replace(
                        signal,
                        reasons=signal.reasons + ("earnings_cap",),
                    ).with_scores(final_score=0.6)

        if reasons:
            LOGGER.info("Signal %s failed guardrails: %s", signal.symbol, ", ".join(reasons))
            self.log_risk_event("guardrail_veto", symbol=signal.symbol, meta={"reasons": reasons})
            return RiskAssessment(False, reasons), updated_signal

        return RiskAssessment.ok(), updated_signal

    # ------------------------------------------------------------------ execution guards
    def pre_execution_checks(
        self,
        planned_orders: Sequence[PlannedOrder],
        *,
        open_positions: Iterable[Position],
        trades_opened_today: int,
        session: str | None = None,
    ) -> RiskAssessment:
        """Evaluate portfolio level guardrails before sending orders."""

        if not planned_orders:
            return RiskAssessment.ok()

        reasons: list[str] = []

        # Daily trade cap
        if trades_opened_today + len(planned_orders) > self.config.daily_trade_cap:
            reasons.append("daily_trade_cap")

        # Drawdown halt based on equity telemetry
        equity = self.database.get_latest_equity() or {}
        starting_equity = equity.get("starting_equity", 0.0)
        net_pnl = equity.get("realized_pnl", 0.0) + equity.get("unrealized_pnl", 0.0)
        drawdown_pct = (net_pnl / starting_equity * 100) if starting_equity else 0.0
        if starting_equity and abs(drawdown_pct) >= self.config.daily_drawdown_halt_pct and net_pnl < 0:
            reasons.append("drawdown_halt")

        # Exposure guard
        open_positions_list = list(open_positions)
        current_exposure = sum(abs(pos.quantity * pos.entry_price) for pos in open_positions_list)
        planned_exposure = sum(order.entry * order.qty for order in planned_orders)
        starting_equity = starting_equity or 1.0
        gross_exposure_pct = (current_exposure + planned_exposure) / starting_equity * 100
        if gross_exposure_pct > self.config.max_portfolio_exposure_pct:
            reasons.append("exposure_cap")

        if reasons:
            LOGGER.warning("Pre-execution checks blocked orders: %s", ", ".join(reasons))
            for reason in reasons:
                value: float | None = None
                if reason == "exposure_cap":
                    value = gross_exposure_pct
                elif reason == "drawdown_halt":
                    value = drawdown_pct
                elif reason == "daily_trade_cap":
                    value = float(trades_opened_today + len(planned_orders))
                self.log_risk_event(reason, value=value, session=session)
            return RiskAssessment(False, reasons)

        return RiskAssessment.ok()

    # ------------------------------------------------------------------ compatibility helpers
    def check_drawdown(self) -> RiskAssessment:
        equity = self.database.get_latest_equity() or {}
        starting_equity = equity.get("starting_equity", 0.0)
        if not starting_equity:
            return RiskAssessment.ok()
        net_pnl = equity.get("realized_pnl", 0.0) + equity.get("unrealized_pnl", 0.0)
        drawdown_pct = net_pnl / starting_equity * 100
        if drawdown_pct <= -self.config.daily_drawdown_halt_pct:
            reason = f"drawdown {drawdown_pct:.2f}% exceeds limit"
            self.log_risk_event("drawdown_halt", value=drawdown_pct)
            return RiskAssessment(False, [reason])
        return RiskAssessment.ok()

    def assess_portfolio(self, open_positions: Iterable[Position]) -> Mapping[str, float]:
        positions = list(open_positions)
        exposure = sum(abs(p.quantity * p.entry_price) for p in positions)
        return {
            "exposure": exposure,
            "open_positions": len(positions),
        }
