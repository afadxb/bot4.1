"""Entrypoint wiring the orchestrator for manual runs."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .config import AIConfig, EngineConfig, ExecutionConfig, OrchestratorConfig
from .orchestrator import Orchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Intraday trading orchestrator")
    parser.add_argument("--database", default="trade_engine.db", help="SQLite database path")
    parser.add_argument("--top-n", type=int, default=20, help="Number of symbols to rank per cycle")
    parser.add_argument("--cadence-min", type=int, default=5, help="Cycle cadence in minutes")
    parser.add_argument(
        "--flatten-time",
        default="15:55",
        help="Time in ET to trigger the flatten guard (HH:MM)",
    )
    parser.add_argument(
        "--timezone",
        default="America/Toronto",
        help="Timezone for market scheduling",
    )
    parser.add_argument("--enable-ai", action="store_true", help="Enable AI gating overlays")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Send real orders (omit for dry-run mode)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single intraday cycle instead of the continuous scheduler",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    orchestrator_config = OrchestratorConfig(
        timezone=args.timezone,
        cadence_min=args.cadence_min,
        intraday_top_n=args.top_n,
        flatten_time_et=args.flatten_time,
        start_with_dry_run=not args.live,
    )
    config = EngineConfig(
        database_path=args.database,
        orchestrator=orchestrator_config,
        execution=ExecutionConfig(enable_orders=args.live),
        ai=AIConfig(enable_gating=args.enable_ai),
    )
    orchestrator = Orchestrator(config)
    if args.once:
        asyncio.run(orchestrator.run_intraday_cycle(1))
    else:
        asyncio.run(orchestrator.run())


if __name__ == "__main__":
    main()
