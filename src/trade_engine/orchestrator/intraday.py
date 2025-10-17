"""Intraday orchestration pipeline for a single cycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from ..ai.gating import AIGating
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
    approved: Sequence[TradeIntent]
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

    decisions = ctx.strategy.evaluate(snapshots)
    signals = [decision.signal for decision in decisions]
    for signal in signals:
        ctx.journal.record_signal(signal)

    rejected: dict[str, list[str]] = {}
    approved: list[TradeIntent] = []
    processed = 0
    for decision in decisions:
        if decision.intent is None:
            continue
        if processed >= top_n:
            break
        processed += 1
        intent = decision.intent
        if ctx.ai and ctx.config.ai.enable_gating:
            overlay = ctx.ai.evaluate(
                symbol=intent.symbol,
                signal=decision.signal,
                catalysts=headlines.get(intent.symbol, ()),
                features=decision.signal.metadata | {"score": decision.signal.score},
                require_positive_sentiment=ctx.config.ai.finbert.enable,
                require_favorable_regime=False,
            )
            ctx.journal.record_ai(overlay)
            if not overlay.approved:
                rejected.setdefault(intent.symbol, []).append("ai_gating")
                continue
        risk = ctx.risk_manager.check_trade(intent, open_positions)
        if not risk.allowed:
            rejected.setdefault(intent.symbol, []).extend(risk.reasons)
            continue
        approved.append(intent)

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

    fills = ctx.trade_manager.execute(approved, open_positions)
    session.trades_opened_today += fills
    exposure = ctx.risk_manager.assess_portfolio(open_positions)
    session.equity_snapshot = dict(exposure)

    summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "signals": len(signals),
        "approved": len(approved),
        "fills": fills,
    }
    summary.update({f"portfolio_{key}": value for key, value in exposure.items()})
    ctx.journal.log_cycle(summary)

    return IntradayResult(
        cycle_id=cycle_id,
        signals=signals,
        approved=approved,
        rejected=rejected,
        flatten_required=False,
        summary=summary,
    )
