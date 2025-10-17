"""Deterministic intraday orchestrator for the trading engine."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Iterable

from .ai.gating import AIGating
from .config import EngineConfig
from .data.catalyst_client import CatalystClient
from .data.ibkr_client import IBKRClient
from .db import Database
from .execution.executor import Executor
from .execution.trade_manager import TradeManager
from .features.feature_engine import FeatureEngine
from .journal import Journal
from .models import Position
from .risk.manager import RiskManager
from .strategy.engine import StrategyEngine

LOGGER = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.database = Database(config.database_path)
        self.ibkr = IBKRClient()
        self.feature_engine = FeatureEngine()
        self.strategy = StrategyEngine()
        self.ai_gating = AIGating()
        self.catalyst_client = CatalystClient()
        self.executor = Executor(dry_run=config.dry_run)
        self.trade_manager = TradeManager(self.database, self.executor)
        self.journal = Journal(self.database)
        self.risk_manager = RiskManager(config.risk, self.database)

    async def cycle(self) -> None:
        watchlist = self.database.fetch_watchlist(self.config.top_n)
        LOGGER.info("Loaded %d watchlist symbols", len(watchlist))
        raw_signals: list[tuple[str, dict[str, float]]] = []
        for row in watchlist:
            symbol = row["symbol"]
            bars = self.ibkr.fetch_historical_bars(symbol, timeframe="5m")
            features = dict(self.feature_engine.build_features(bars))
            raw_signals.append((symbol, features))
        ranked = self.strategy.rank(raw_signals)
        LOGGER.info("Evaluated %d ranked opportunities", len(ranked))

        open_positions = self._load_positions()
        approved_intents = []
        for signal, intent in ranked[: self.config.top_n]:
            self.journal.record_signal(signal)
            ai_overlay = None
            if self.config.ai.enabled:
                catalysts = list(self.catalyst_client.fetch_recent(intent.symbol))
                ai_overlay = self.ai_gating.evaluate(
                    symbol=intent.symbol,
                    signal=signal,
                    catalysts=catalysts,
                    features=signal.metadata | {"score": signal.score},
                    require_positive_sentiment=self.config.ai.require_positive_sentiment,
                    require_favorable_regime=self.config.ai.require_favorable_regime,
                )
                self.journal.record_ai(ai_overlay)
                if not ai_overlay.approved:
                    LOGGER.info("AI gating rejected %s", intent.symbol)
                    continue
            risk = self.risk_manager.check_trade(intent, open_positions)
            if not risk.allowed:
                continue
            approved_intents.append(intent)

        drawdown = self.risk_manager.check_drawdown()
        if not drawdown.allowed:
            LOGGER.warning("Drawdown breached: flattening portfolio")
            return

        self.trade_manager.execute(approved_intents, open_positions)

        exposure = self.risk_manager.assess_portfolio(open_positions)
        cycle_payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "signals": len(ranked),
            "approved": len(approved_intents),
            "exposure": exposure.get("exposure", 0.0),
        }
        self.journal.log_cycle(cycle_payload)

    async def run(self) -> None:
        interval = timedelta(seconds=self.config.cycle.interval_seconds)
        next_run = datetime.utcnow()
        while True:
            now = datetime.utcnow()
            if now >= next_run:
                await self.cycle()
                next_run = now + interval
            await asyncio.sleep(1)

    def _load_positions(self) -> list[Position]:
        positions = []
        for item in self.ibkr.fetch_open_positions():
            positions.append(
                Position(
                    symbol=str(item.get("symbol")),
                    side=self._side_from(item.get("side", "long")),
                    quantity=float(item.get("quantity", 0.0)),
                    entry_price=float(item.get("entry", 0.0)),
                    mark=float(item.get("mark", 0.0)),
                    unrealized_pnl=float(item.get("unrealized_pnl", 0.0)),
                )
            )
        return positions

    def _side_from(self, value: object):
        from .models import Side

        try:
            return Side(str(value))
        except ValueError:
            return Side.LONG
