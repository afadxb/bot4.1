"""Translate trade intents into executable orders and journal them."""

from __future__ import annotations

import json
import logging
from typing import Iterable

from ..db import Database
from ..models import Position, TradeIntent
from .executor import Executor

LOGGER = logging.getLogger(__name__)


class TradeManager:
    def __init__(self, database: Database, executor: Executor) -> None:
        self.database = database
        self.executor = executor

    def execute(self, intents: Iterable[TradeIntent], open_positions: Iterable[Position]) -> int:
        positions_by_symbol = {pos.symbol: pos for pos in open_positions}
        filled = 0
        for intent in intents:
            existing = positions_by_symbol.get(intent.symbol)
            action = "BUY" if intent.side.value == "long" else "SELL"
            if existing and existing.side == intent.side:
                LOGGER.info("Skipping %s: position already open", intent.symbol)
                continue
            order_id = self.executor.submit(
                symbol=intent.symbol,
                action=action,
                quantity=round(intent.quantity, 2),
                limit_price=intent.entry,
                stop_price=intent.stop,
            )
            trade_id = self.database.record_trade(
                symbol=intent.symbol,
                direction=intent.side.value,
                qty=intent.quantity,
                entry_price=intent.entry,
                stop_price=intent.stop,
                target_price=intent.target,
                status="open",
                notes=f"order_id={order_id}",
            )
            self.database.log(
                category="execution",
                message=f"Placed trade {trade_id} for {intent.symbol}",
                payload=json.dumps(intent.metadata),
            )
            filled += 1
        return filled
