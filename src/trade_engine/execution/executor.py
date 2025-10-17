"""Order execution wrappers that speak to IBKR."""

from __future__ import annotations

import logging

from ..data.ibkr_client import IBKRClient

LOGGER = logging.getLogger(__name__)


class Executor:
    def __init__(self, client: IBKRClient | None = None, dry_run: bool = True) -> None:
        self.client = client or IBKRClient()
        self.dry_run = dry_run

    def submit(
        self,
        symbol: str,
        action: str,
        quantity: float,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        if self.dry_run:
            order_id = f"DRY-{symbol}-{action}"
            LOGGER.info(
                "Dry run: %s %s qty=%s limit=%s stop=%s",
                action,
                symbol,
                quantity,
                limit_price,
                stop_price,
            )
            return order_id
        return self.client.place_order(symbol, action, quantity, limit_price, stop_price)

    def cancel_all_orders(self) -> None:
        if self.dry_run:
            LOGGER.info("Dry run: cancel_all_orders noop")
            return
        self.client.cancel_all_orders()
