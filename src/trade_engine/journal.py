"""High level journaling helpers for observability and analytics."""

from __future__ import annotations

import json
import logging
from typing import Mapping

from .db import Database
from .models import AIOverlay, Signal

LOGGER = logging.getLogger(__name__)


class Journal:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record_signal(self, signal: Signal) -> None:
        metadata_json = json.dumps(signal.metadata)
        self.database.record_signal(
            symbol=signal.symbol,
            ts=signal.ts.isoformat(),
            signal_type=signal.signal_type,
            score=signal.score,
            strength=signal.strength,
            metadata=metadata_json,
        )

    def record_ai(self, overlay: AIOverlay) -> None:
        metadata_json = json.dumps(overlay.metadata)
        self.database.record_ai_overlay(
            symbol=overlay.symbol,
            ts=overlay.ts.isoformat(),
            sentiment=overlay.sentiment,
            regime=overlay.regime,
            approved=overlay.approved,
            metadata=metadata_json,
        )

    def log_cycle(self, payload: Mapping[str, float | str]) -> None:
        self.database.log("cycle", "Cycle summary", json.dumps(payload))
