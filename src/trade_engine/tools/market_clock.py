"""Utilities for coordinating trading session windows."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


class MarketClock:
    """Intraday session helper aware of the configured timezone."""

    def __init__(self, timezone: str, open_time: time | None = None, close_time: time | None = None) -> None:
        self.zone = ZoneInfo(timezone)
        self.open_time = open_time or time(9, 30)
        self.close_time = close_time or time(16, 0)

    def now(self) -> datetime:
        return datetime.now(self.zone)

    def session_window(self, reference: datetime | None = None) -> tuple[datetime, datetime]:
        ref = (reference or self.now()).astimezone(self.zone)
        start = ref.replace(
            hour=self.open_time.hour,
            minute=self.open_time.minute,
            second=0,
            microsecond=0,
        )
        end = ref.replace(
            hour=self.close_time.hour,
            minute=self.close_time.minute,
            second=0,
            microsecond=0,
        )
        while start.weekday() >= 5:
            start += timedelta(days=1)
            end = start.replace(
                hour=self.close_time.hour,
                minute=self.close_time.minute,
                second=0,
                microsecond=0,
            )
        if end <= start:
            end += timedelta(days=1)
        if ref < start:
            return start, end
        if ref > end:
            return self.session_window(ref + timedelta(days=1))
        return start, end

    def combine_time(self, value: time, reference: datetime | None = None) -> datetime:
        ref = (reference or self.now()).astimezone(self.zone)
        return ref.replace(hour=value.hour, minute=value.minute, second=0, microsecond=0)

    def next_session_open(self, reference: datetime | None = None) -> datetime:
        ref = (reference or self.now()).astimezone(self.zone)
        start, _ = self.session_window(ref)
        candidate = start if ref < start else start + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate

