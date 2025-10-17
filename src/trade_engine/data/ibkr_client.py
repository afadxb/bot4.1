"""Thin abstraction around IBKR market data and order execution."""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Iterable, List

from ..models import Bar

LOGGER = logging.getLogger(__name__)


class IBKRClient:
    """Facade that would wrap IBKR connectivity.

    The implementation included here purposely avoids taking an actual IBKR dependency
    so the project can be executed in offline or CI environments.  The public surface
    mirrors the behaviour used elsewhere in the engine, allowing production builds to
    swap in a concrete implementation.
    """

    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        LOGGER.info("Connecting to IBKR gateway (stub)")
        self.connected = True

    def disconnect(self) -> None:
        LOGGER.info("Disconnecting from IBKR gateway (stub)")
        self.connected = False

    def ensure_connection(self) -> None:
        if not self.connected:
            self.connect()

    def fetch_historical_bars(self, symbol: str, timeframe: str, lookback: int = 20) -> List[Bar]:
        """Return a deterministic yet pseudo-random set of bars for testing.

        A real implementation would delegate to ``ib_insync`` or the native IB API.
        """

        self.ensure_connection()
        base_price = 100 + (hash(symbol) % 50)
        now = datetime.utcnow().replace(second=0, microsecond=0)
        delta = timedelta(minutes=1 if timeframe.endswith("m") else 1)
        bars: list[Bar] = []
        price = float(base_price)
        for i in range(lookback):
            ts = now - (lookback - i) * delta
            move = random.uniform(-1, 1)
            open_price = price
            close_price = max(1.0, price + move)
            high = max(open_price, close_price) + random.random()
            low = min(open_price, close_price) - random.random()
            volume = random.randint(1_000, 10_000)
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    ts=ts,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close_price,
                    volume=float(volume),
                )
            )
            price = close_price
        LOGGER.debug("Generated %d bars for %s", len(bars), symbol)
        return bars

    def place_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """Submit an order to IBKR.

        The stub returns a synthetic order id for journaling purposes.
        """

        self.ensure_connection()
        order_id = f"SIM-{symbol}-{datetime.utcnow().timestamp():.0f}"
        LOGGER.info(
            "Placing %s order for %s qty=%s limit=%s stop=%s",
            action,
            symbol,
            quantity,
            limit_price,
            stop_price,
        )
        return order_id

    def fetch_open_positions(self) -> Iterable[dict[str, float | str]]:
        """Return an empty collection in the stub.

        Production builds can hook into ``reqPositions`` for live book state.
        """

        return []

    def cancel_all_orders(self) -> None:
        """Stubbed order cancellation."""

        LOGGER.info("Cancelling all outstanding orders (stub)")
