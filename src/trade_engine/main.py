"""Entrypoint wiring the orchestrator for manual runs."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .config import AIConfig, CycleConfig, EngineConfig
from .orchestrator import Orchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Intraday trading orchestrator")
    parser.add_argument("--database", default="trade_engine.db", help="SQLite database path")
    parser.add_argument("--top-n", type=int, default=20, help="Number of symbols to rank per cycle")
    parser.add_argument("--interval", type=int, default=300, help="Cycle interval in seconds")
    parser.add_argument("--enable-ai", action="store_true", help="Enable AI gating overlays")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Send real orders (omit for dry-run mode)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = EngineConfig(
        database_path=args.database,
        top_n=args.top_n,
        cycle=CycleConfig(interval_seconds=args.interval),
        ai=AIConfig(enabled=args.enable_ai),
        dry_run=not args.live,
    )
    orchestrator = Orchestrator(config)
    asyncio.run(orchestrator.cycle())


if __name__ == "__main__":
    main()
