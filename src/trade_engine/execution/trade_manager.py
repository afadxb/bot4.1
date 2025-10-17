"""Translate scored signals into executable orders and journal them."""

from __future__ import annotations

import json
import logging
import math
from typing import Mapping, Sequence

from ..config import ExecutionConfig, RiskConfig
from ..db import Database
from ..models import PlannedOrder, Signal
from .executor import Executor

LOGGER = logging.getLogger(__name__)


class TradeManager:
    def __init__(
        self,
        database: Database,
        executor: Executor,
        risk: RiskConfig,
        execution: ExecutionConfig,
    ) -> None:
        self.database = database
        self.executor = executor
        self.risk_config = risk
        self.execution_config = execution

    # ------------------------------------------------------------------ planning
    def plan_orders(
        self,
        signals: Sequence[Signal],
        *,
        equity_snapshot: Mapping[str, float] | None = None,
    ) -> list[PlannedOrder]:
        if not signals:
            return []

        equity_info = equity_snapshot or {}
        equity = float(equity_info.get("starting_equity", 0.0))
        if equity <= 0:
            latest = self.database.get_latest_equity()
            if latest:
                equity = float(latest.get("starting_equity", 0.0))
        if equity <= 0:
            equity = 100_000.0  # sensible default for dry-run environments

        dollar_risk = equity * self.risk_config.risk_per_trade_pct / 100
        max_position_value = equity * self.risk_config.max_position_value_pct / 100

        planned: list[PlannedOrder] = []
        for signal in signals:
            entry = float(signal.entry_hint or 0.0)
            stop = float(signal.stop_hint or 0.0)
            if entry <= 0 or stop <= 0 or math.isclose(entry, stop):
                LOGGER.debug("Skipping %s: invalid entry/stop hints", signal.symbol)
                continue

            side = "BUY" if signal.final_score >= 0.5 else "SELL"
            per_share_risk = max(abs(entry - stop), self.risk_config.min_tick_buffer)
            qty = math.floor(dollar_risk / per_share_risk)
            if qty <= 0:
                LOGGER.debug("Skipping %s: qty computed as zero", signal.symbol)
                continue

            notional = qty * entry
            if notional > max_position_value:
                qty = math.floor(max_position_value / entry)
                if qty <= 0:
                    LOGGER.debug("Skipping %s: capped position size zero", signal.symbol)
                    continue
                notional = qty * entry

            scale_out_r = self.execution_config.scale_out_at_r_multiple
            final_target_r = self.execution_config.final_target_r_multiple
            direction = 1 if side == "BUY" else -1
            scale_out = entry + direction * per_share_risk * scale_out_r
            target = entry + direction * per_share_risk * final_target_r

            risk_context = {
                "dollar_risk": dollar_risk,
                "per_share_risk": per_share_risk,
                "notional": notional,
                "risk_multiple_scale": scale_out_r,
                "risk_multiple_final": final_target_r,
            }

            planned.append(
                PlannedOrder(
                    symbol=signal.symbol,
                    side=side,
                    qty=qty,
                    entry=entry,
                    stop=stop,
                    scale_out=scale_out,
                    target=target,
                    trail_mode=self.execution_config.trail_mode,
                    risk_context=risk_context,
                )
            )

        return planned

    # ------------------------------------------------------------------ execution
    def execute(self, orders: Sequence[PlannedOrder]) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        for order in orders:
            if order.qty <= 0:
                continue
            if self.executor.dry_run:
                LOGGER.info(
                    "Dry run execution: %s %s qty=%s entry=%s stop=%s",
                    order.side,
                    order.symbol,
                    order.qty,
                    order.entry,
                    order.stop,
                )
                results.append({"symbol": order.symbol, "status": "dry_run", "qty": order.qty})
                continue

            order_id = self.executor.submit(
                symbol=order.symbol,
                action=order.side,
                quantity=float(order.qty),
                limit_price=order.entry,
                stop_price=order.stop,
            )
            trade_id = self.database.record_trade(
                symbol=order.symbol,
                direction="long" if order.side == "BUY" else "short",
                qty=order.qty,
                entry_price=order.entry,
                stop_price=order.stop,
                target_price=order.target,
                status="open",
                notes=f"scale_out={order.scale_out};trail={order.trail_mode};order_id={order_id}",
            )
            self.database.log(
                category="execution",
                message=f"Placed trade {trade_id} for {order.symbol}",
                payload=json.dumps(order.risk_context),
            )
            results.append(
                {
                    "symbol": order.symbol,
                    "status": "submitted",
                    "order_id": order_id,
                    "trade_id": trade_id,
                }
            )

        return results
