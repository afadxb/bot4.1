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
        reasons_text = "\n".join(signal.reasons)
        self.database.record_signal(
            symbol=signal.symbol,
            run_ts=signal.run_ts.isoformat(),
            cycle_id=signal.cycle_id,
            base_score=signal.base_score,
            ai_adj_score=signal.ai_adj_score,
            final_score=signal.final_score,
            rank=signal.rank,
            reasons_text=reasons_text,
            rules_passed_json=json.dumps(signal.rules_passed),
            features_json=json.dumps(signal.features),
        )

    def record_ai(self, overlay: AIOverlay) -> None:
        metadata_json = json.dumps(overlay.metadata)
        self.database.record_ai_provenance(
            symbol=overlay.symbol,
            run_ts=overlay.ts.isoformat(),
            source=overlay.regime,
            sentiment_score=overlay.sentiment,
            sentiment_label="approved" if overlay.approved else "blocked",
            meta_json=metadata_json,
        )

    def log_cycle(self, payload: Mapping[str, float | str]) -> None:
        self.database.log("cycle", "Cycle summary", json.dumps(payload))
