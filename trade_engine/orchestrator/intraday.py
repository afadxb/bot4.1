"""Intraday orchestration pipeline for a single cycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from ..ai.gating import AIGating, adjust_scores
from ..config import EngineConfig
from ..data.hub import DataHub
from ..db import Database
from ..execution.trade_manager import TradeManager
from ..journal import Journal
from ..models import Position, Signal, TradeIntent
from ..risk.manager import RiskManager
from ..strategy.features_intraday import FeatureSnapshot, IntradayFeatureBuilder
from ..strategy.propulsion import PropulsionStrategy

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SessionState:
    trades_opened_today: int = 0
    halted_reason: str | None = None
    equity_snapshot: Mapping[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class IntradayContext:
    config: EngineConfig
    database: Database
    data_hub: DataHub
    feature_builder: IntradayFeatureBuilder
    strategy: PropulsionStrategy
    risk_manager: RiskManager
    trade_manager: TradeManager
    journal: Journal
    ai: AIGating | None = None


@dataclass(slots=True)
class IntradayResult:
    cycle_id: str
    signals: Sequence[Signal]
    approved: Sequence[Signal]
    rejected: Mapping[str, Sequence[str]]
    flatten_required: bool
    summary: Mapping[str, float | int | str]


def run_intraday_cycle(
    cycle_id: str,
    *,
    ctx: IntradayContext,
    session: SessionState,
    open_positions: Sequence[Position],
) -> IntradayResult:
    """Execute the deterministic intraday pipeline for ``cycle_id``."""

    LOGGER.info("Cycle %s: starting intraday evaluation", cycle_id)
    top_n = ctx.config.orchestrator.intraday_top_n
    watchlist = ctx.database.fetch_watchlist(top_n)
    if len(watchlist) < top_n:
        LOGGER.debug("Watchlist shorter than Top-N; loading full watchlist")
        watchlist = ctx.database.fetch_watchlist()
    symbols = [row["symbol"] for row in watchlist]
    if not symbols:
        LOGGER.warning("Cycle %s: no symbols available for evaluation", cycle_id)
        return IntradayResult(
            cycle_id=cycle_id,
            signals=[],
            approved=[],
            rejected={},
            flatten_required=False,
            summary={"signals": 0, "approved": 0, "timestamp": datetime.utcnow().isoformat()},
        )

    bars_by_symbol = ctx.data_hub.get_bars(
        symbols,
        tf="5m",
        lookback_min=max(ctx.config.strategy.consolidation_lookback, ctx.config.strategy.ema_slow * 3),
    )
    headlines = ctx.data_hub.get_headlines(symbols)
    snapshots: list[FeatureSnapshot] = []
    for symbol in symbols:
        bars = bars_by_symbol.get(symbol, [])
        if not bars:
            LOGGER.debug("%s: skipping due to missing bars", symbol)
            continue
        snapshot = ctx.feature_builder.build(symbol, bars, catalysts=headlines.get(symbol, ()))
        snapshots.append(snapshot)

    decisions = ctx.strategy.evaluate(snapshots, cycle_id=cycle_id)
    if ctx.config.ai.finbert.enable:
        adjusted_signals = adjust_scores([decision.signal for decision in decisions], ctx.database)
        for decision, updated_signal in zip(decisions, adjusted_signals):
            decision.signal = updated_signal
    signals = [decision.signal for decision in decisions]
    for signal in signals:
        ctx.journal.record_signal(signal)

    rejected: dict[str, list[str]] = {}
    approved_signals: list[Signal] = []
    processed = 0
    for decision in decisions:
        if decision.intent is None:
            continue
        if processed >= top_n:
            break
        processed += 1
        intent = decision.intent
        assessment, updated_signal = ctx.risk_manager.apply_guardrails(decision.signal)
        decision.signal = updated_signal
        if not assessment.allowed:
            rejected.setdefault(updated_signal.symbol, []).extend(assessment.reasons)
            continue
        if ctx.ai and ctx.config.ai.enable_gating:
            overlay = ctx.ai.evaluate(
                symbol=decision.signal.symbol,
                signal=decision.signal,
                catalysts=headlines.get(decision.signal.symbol, ()),
                features={**{k: float(v) for k, v in decision.signal.features.items()}, "score": decision.signal.base_score},
                require_positive_sentiment=ctx.config.ai.finbert.enable,
                require_favorable_regime=False,
            )
            ctx.journal.record_ai(overlay)
            if not overlay.approved:
                rejected.setdefault(decision.signal.symbol, []).append("ai_gating")
                continue
        approved_signals.append(decision.signal)

    drawdown = ctx.risk_manager.check_drawdown()
    if not drawdown.allowed:
        session.halted_reason = "; ".join(drawdown.reasons)
        LOGGER.warning("Cycle %s: drawdown threshold breached", cycle_id)
        halt_summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "signals": len(signals),
            "approved": 0,
            "status": "drawdown_halt",
        }
        ctx.journal.log_cycle(halt_summary)
        return IntradayResult(
            cycle_id=cycle_id,
            signals=signals,
            approved=[],
            rejected=rejected,
            flatten_required=True,
            summary=halt_summary,
        )

    planned_orders = ctx.trade_manager.plan_orders(approved_signals, equity_snapshot=session.equity_snapshot)
    pre_exec = ctx.risk_manager.pre_execution_checks(
        planned_orders,
        open_positions=open_positions,
        trades_opened_today=session.trades_opened_today,
        session=str(cycle_id),
    )
    if not pre_exec.allowed:
        LOGGER.warning("Cycle %s: pre-execution guardrails blocked orders", cycle_id)
        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "signals": len(signals),
            "approved": len(approved_signals),
            "status": "risk_block",
            "reasons": ",".join(pre_exec.reasons),
        }
        ctx.journal.log_cycle(summary)
        return IntradayResult(
            cycle_id=cycle_id,
            signals=signals,
            approved=[],
            rejected=rejected,
            flatten_required=False,
            summary=summary,
        )

    execution_results = ctx.trade_manager.execute(planned_orders)
    submitted = len([result for result in execution_results if result.get("status") == "submitted"])
    session.trades_opened_today += submitted
    exposure = ctx.risk_manager.assess_portfolio(open_positions)
    session.equity_snapshot = dict(exposure)

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "signals": len(signals),
        "approved": len(approved_signals),
        "fills": submitted,
    }
    summary.update({f"portfolio_{key}": value for key, value in exposure.items()})
    ctx.journal.log_cycle(summary)

    return IntradayResult(
        cycle_id=cycle_id,
        signals=signals,
        approved=approved_signals,
        rejected=rejected,
        flatten_required=False,
        summary=summary,
    )
