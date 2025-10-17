"""Market-aware orchestrator wiring the intraday pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Mapping

from ..ai.gating import AIGating
from ..config import EngineConfig
from ..data.feeds import IBKRFeed
from ..data.hub import DataHub
from ..data.ibkr_client import IBKRClient
from ..db import Database
from ..execution.executor import Executor
from ..execution.trade_manager import TradeManager
from ..journal import Journal
from ..models import Position, Side
from ..risk.manager import RiskManager
from ..strategy.features_intraday import IntradayFeatureBuilder
from ..strategy.propulsion import PropulsionStrategy
from ..tools.market_clock import MarketClock
from .intraday import IntradayContext, SessionState, run_intraday_cycle

LOGGER = logging.getLogger(__name__)


class Orchestrator:
    """Coordinate scheduling, market windows, and the intraday pipeline."""

    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        self.database = Database(config.database_path)
        self.ibkr = IBKRClient()
        self.executor = Executor(dry_run=config.dry_run)
        self.trade_manager = TradeManager(self.database, self.executor, config.risk, config.execution)
        self.journal = Journal(self.database)
        self.risk_manager = RiskManager(config.risk, self.database)
        self.market_clock = MarketClock(config.orchestrator.timezone)
        self.data_hub = DataHub(self.database, config.feeds, ibkr=IBKRFeed(self.ibkr))
        self.feature_builder = IntradayFeatureBuilder(config.strategy)
        self.strategy = PropulsionStrategy(config.strategy, config.risk)
        self.ai_gating = AIGating() if config.ai.enable_gating else None
        self.session_state = SessionState()
        self.intraday_context = IntradayContext(
            config=config,
            database=self.database,
            data_hub=self.data_hub,
            feature_builder=self.feature_builder,
            strategy=self.strategy,
            risk_manager=self.risk_manager,
            trade_manager=self.trade_manager,
            journal=self.journal,
            ai=self.ai_gating,
        )

    async def run_intraday_cycle(self, cycle_id: int) -> None:
        LOGGER.info("Starting intraday cycle %s", cycle_id)
        open_positions = self._load_positions()
        result = run_intraday_cycle(
            str(cycle_id),
            ctx=self.intraday_context,
            session=self.session_state,
            open_positions=open_positions,
        )
        if result.flatten_required:
            LOGGER.warning("Cycle %s requested portfolio flatten", cycle_id)
            await self.run_flatten_guard()
            return
        LOGGER.info("Cycle %s summary: %s", cycle_id, json.dumps(result.summary))
        self.health_heartbeat(result.summary)

    async def run(self) -> None:
        interval = timedelta(minutes=self.config.orchestrator.cadence_min)
        cycle_id = 0
        next_run = self.market_clock.now()
        flatten_executed = False
        while True:
            now = self.market_clock.now()
            session_open, session_close = self.market_clock.session_window(now)
            flatten_dt = self.market_clock.combine_time(self.config.orchestrator.flatten_time_et, reference=now)

            if now < session_open:
                next_run = session_open
                flatten_executed = False
                cycle_id = 0
                self.session_state = SessionState()
                await asyncio.sleep(min((session_open - now).total_seconds(), 60))
                continue

            if now >= session_close:
                next_session = self.market_clock.next_session_open(now)
                next_run = next_session
                flatten_executed = False
                cycle_id = 0
                self.session_state = SessionState()
                await asyncio.sleep(min((next_session - now).total_seconds(), 300))
                continue

            if not flatten_executed and now >= flatten_dt:
                await self.run_flatten_guard()
                flatten_executed = True

            if now >= next_run:
                cycle_id += 1
                await self.run_intraday_cycle(cycle_id)
                next_run = now + interval

            await asyncio.sleep(1)

    async def cycle(self) -> None:  # pragma: no cover - legacy shim
        await self.run_intraday_cycle(0)

    async def run_flatten_guard(self) -> None:
        LOGGER.warning("Executing flatten guard: flattening all positions")
        positions = self._load_positions()
        if not positions:
            LOGGER.info("Flatten guard: portfolio already flat")
            return
        flattened = 0
        for position in positions:
            action = "SELL" if position.side is Side.LONG else "BUY"
            self.executor.submit(symbol=position.symbol, action=action, quantity=position.quantity)
            flattened += 1
        payload = json.dumps({"flattened_positions": flattened})
        self.database.log("risk", "Flatten guard executed", payload)

    def health_heartbeat(self, extra: Mapping[str, object] | None = None) -> None:
        payload: dict[str, object] = {
            "timestamp": datetime.utcnow().isoformat(),
            "dry_run": self.config.dry_run,
            "timezone": self.config.orchestrator.timezone,
            "trades_today": self.session_state.trades_opened_today,
        }
        if self.session_state.halted_reason:
            payload["halted_reason"] = self.session_state.halted_reason
        if self.session_state.equity_snapshot:
            payload.update({f"equity_{k}": v for k, v in self.session_state.equity_snapshot.items()})
        if extra:
            payload.update(extra)
        self.database.log("heartbeat", "orchestrator_alive", json.dumps(payload))

    def _load_positions(self) -> list[Position]:
        positions: list[Position] = []
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

    def _side_from(self, value: object) -> Side:
        try:
            return Side(str(value))
        except ValueError:
            return Side.LONG
