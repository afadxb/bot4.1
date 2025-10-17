"""Entrypoint wiring the orchestrator for manual runs."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .config import EngineConfig, load_engine_config
from .orchestrator import Orchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Intraday trading orchestrator")
    parser.add_argument("--config", help="Path to YAML configuration file")
    parser.add_argument("--env-file", help="Path to .env overrides", dest="env_file")
    parser.add_argument("--database", help="Override SQLite database path")
    parser.add_argument("--top-n", type=int, help="Override number of symbols to rank per cycle")
    parser.add_argument("--cadence", type=int, help="Override cadence in minutes")
    parser.add_argument("--live", action="store_true", help="Send real orders (omit for dry-run mode)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if args.config or args.env_file:
        config = load_engine_config(args.config, args.env_file)
    else:
        config = EngineConfig()

    overrides: dict[str, object] = {}
    if args.database:
        overrides["database_path"] = args.database
    orchestrator_overrides: dict[str, object] = {}
    if args.top_n is not None:
        orchestrator_overrides["intraday_top_n"] = args.top_n
    if args.cadence is not None:
        orchestrator_overrides["cadence_min"] = args.cadence
    if orchestrator_overrides:
        overrides.setdefault("orchestrator", {}).update(orchestrator_overrides)  # type: ignore[assignment]
    if args.live:
        overrides.setdefault("execution", {}).update({"enable_orders": True})  # type: ignore[assignment]
    if overrides:
        config = config.merge(overrides)
    orchestrator = Orchestrator(config)
    asyncio.run(orchestrator.cycle())


if __name__ == "__main__":
    main()
