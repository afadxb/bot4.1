"""Deterministic intraday orchestrator for the trading engine."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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


@dataclass(slots=True)
class MarketClock:
    """Utility class for session awareness and cadence alignment."""

    timezone: ZoneInfo
    market_open: time = time(9, 30)
    market_close: time = time(16, 0)
    flatten_time: time | None = None

    def __post_init__(self) -> None:
        if self.flatten_time is None or self.flatten_time > self.market_close:
            object.__setattr__(self, "flatten_time", self.market_close)

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    def session_bounds(self, moment: datetime) -> tuple[datetime, datetime, datetime]:
        session_date = moment.date()
        open_dt = datetime.combine(session_date, self.market_open, self.timezone)
        close_dt = datetime.combine(session_date, self.market_close, self.timezone)
        flatten_dt = datetime.combine(session_date, self.flatten_time or self.market_close, self.timezone)
        if flatten_dt > close_dt:
            flatten_dt = close_dt
        return open_dt, close_dt, flatten_dt

    def is_trading_day(self, moment: datetime) -> bool:
        return moment.weekday() < 5

    def in_trading_window(self, moment: datetime) -> bool:
        if not self.is_trading_day(moment):
            return False
        open_dt, _, flatten_dt = self.session_bounds(moment)
        return open_dt <= moment < flatten_dt

    def should_flatten(self, moment: datetime) -> bool:
        if not self.is_trading_day(moment):
            return False
        _, close_dt, flatten_dt = self.session_bounds(moment)
        return flatten_dt <= moment < close_dt

    def flatten_deadline(self, moment: datetime) -> datetime:
        _, _, flatten_dt = self.session_bounds(moment)
        return flatten_dt

    def next_active_start(self, moment: datetime) -> datetime:
        if not self.is_trading_day(moment):
            return self.next_session_open(moment)
        open_dt, _, flatten_dt = self.session_bounds(moment)
        if moment < open_dt:
            return open_dt
        if moment >= flatten_dt:
            return self.next_session_open(moment)
        return moment

    def next_session_open(self, moment: datetime) -> datetime:
        next_date = moment.date()
        if next_date.weekday() >= 5:
            while next_date.weekday() >= 5:
                next_date += timedelta(days=1)
            return datetime.combine(next_date, self.market_open, self.timezone)

        open_dt = datetime.combine(next_date, self.market_open, self.timezone)
        if moment >= open_dt:
            next_date += timedelta(days=1)
            while next_date.weekday() >= 5:
                next_date += timedelta(days=1)
            return datetime.combine(next_date, self.market_open, self.timezone)
        return open_dt


class Orchestrator:
    def __init__(self, config: EngineConfig) -> None:
        self.config = config
        tz = ZoneInfo(config.orchestrator.timezone)
        self.clock = MarketClock(timezone=tz, flatten_time=config.orchestrator.flatten_time)
        self.database = Database(config.database_path)
        self.ibkr = IBKRClient()
        self.feature_engine = FeatureEngine()
        self.strategy = StrategyEngine()
        self.ai_gating = AIGating()
        self.catalyst_client = CatalystClient()
        dry_run = config.orchestrator.start_with_dry_run or not config.execution.enable_orders
        self.executor = Executor(dry_run=dry_run)
        self.trade_manager = TradeManager(self.database, self.executor)
        self.journal = Journal(self.database)
        self.risk_manager = RiskManager(config.risk, self.database)
        self._cycle_id = 0
        self._last_flatten_date: date | None = None
        self._last_heartbeat: datetime | None = None

    async def run_intraday_cycle(self, cycle_id: int, as_of: datetime | None = None) -> None:
        cycle_time = as_of or self.clock.now()
        LOGGER.info("Starting intraday cycle %s at %s", cycle_id, cycle_time.isoformat())
        watchlist = self.database.fetch_watchlist(self.config.orchestrator.intraday_top_n)
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
        for signal, intent in ranked[: self.config.orchestrator.intraday_top_n]:
            self.journal.record_signal(signal)
            if self.config.ai.enable_gating:
                catalysts = list(self.catalyst_client.fetch_recent(intent.symbol))
                if self.config.ai.finbert.enable and len(catalysts) < self.config.ai.finbert.min_headlines:
                    LOGGER.info("AI gating skipped %s due to insufficient headlines", intent.symbol)
                    continue
                overlay = self.ai_gating.evaluate(
                    symbol=intent.symbol,
                    signal=signal,
                    catalysts=catalysts,
                    features=signal.metadata | {"score": signal.score},
                    require_positive_sentiment=self.config.ai.require_positive_sentiment,
                    require_favorable_regime=self.config.ai.require_favorable_regime,
                )
                self.journal.record_ai(overlay)
                if not overlay.approved:
                    LOGGER.info("AI gating rejected %s", intent.symbol)
                    continue
            risk = self.risk_manager.check_trade(intent, open_positions, cycle_time)
            if not risk.allowed:
                continue
            approved_intents.append(intent)

        session_start = self.clock.session_bounds(cycle_time)[0]
        drawdown = self.risk_manager.check_drawdown(
            since=session_start,
            max_drawdown_pct=self.config.orchestrator.drawdown_halt_pct,
        )
        if not drawdown.allowed:
            LOGGER.warning("Drawdown breached: flattening portfolio")
            await self.run_flatten_guard()
            return

        if approved_intents:
            self.trade_manager.execute(approved_intents, open_positions)
        exposure = self.risk_manager.assess_portfolio(open_positions)
        cycle_payload = {
            "cycle_id": cycle_id,
            "timestamp": datetime.utcnow().isoformat(),
            "signals": len(ranked),
            "approved": len(approved_intents),
            "exposure": exposure.get("exposure", 0.0),
        }
        self.journal.log_cycle(cycle_payload)

    async def run_flatten_guard(self) -> None:
        LOGGER.info("Executing flatten guard")
        positions = self._load_positions()
        self.trade_manager.flatten_all(positions)
        self.executor.cancel_all_orders()
        self.database.log("risk", "flatten_guard", "")

    async def health_heartbeat(self) -> None:
        now = datetime.utcnow()
        if self._last_heartbeat and (now - self._last_heartbeat).total_seconds() < 60:
            return
        self._last_heartbeat = now
        self.database.log("heartbeat", "alive", now.isoformat())

    async def run(self) -> None:
        cadence = timedelta(minutes=self.config.orchestrator.cadence_min)
        while True:
            now = self.clock.now()
            if self.clock.should_flatten(now):
                if self._last_flatten_date != now.date():
                    await self.run_flatten_guard()
                    self._last_flatten_date = now.date()
                next_open = self.clock.next_session_open(now)
                await self._sleep_until(next_open)
                continue

            if not self.clock.in_trading_window(now):
                next_start = self.clock.next_active_start(now)
                await self._sleep_until(next_start)
                continue

            self._cycle_id += 1
            await self.run_intraday_cycle(self._cycle_id, as_of=now)
            await self.health_heartbeat()
            next_time = now + cadence
            deadline = self.clock.flatten_deadline(now)
            if next_time >= deadline:
                next_time = deadline
            await self._sleep_until(next_time)

    async def _sleep_until(self, target: datetime) -> None:
        while True:
            now = self.clock.now()
            seconds = (target - now).total_seconds()
            if seconds <= 0:
                break
            await asyncio.sleep(min(seconds, 60))

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
