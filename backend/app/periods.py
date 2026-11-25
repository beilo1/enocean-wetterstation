"""Zeiträume und Auflösungen für Wetterdaten, Sonnenzeiten und Export."""
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone

FIVE_MINUTES = 300
HOUR = 3600
DAY = 86400

_BUCKET_SQL = {
    FIVE_MINUTES: "date_bin('5 minutes', time, timestamptz 'epoch')",
    HOUR: "date_trunc('hour', time)",
    DAY: "date_trunc('day', time)",
}


def bucket_expression(seconds: int) -> str:
    return _BUCKET_SQL[seconds]


@dataclass(frozen=True)
class Period:
    name: str
    seconds: int
    lookback: str
    days: int
    start_day: date | None = None
    stop_day: date | None = None

    def bounds(self, now: datetime) -> tuple[datetime, datetime]:
        if self.start_day is not None and self.stop_day is not None:
            return (
                datetime.combine(self.start_day, time.min, timezone.utc),
                datetime.combine(self.stop_day, time.min, timezone.utc),
            )
        return now - timedelta(days=self.days), now

    def where(self, column: str, first_parameter: int = 1, *, daily: bool = False) -> tuple[str, tuple]:
        if self.start_day is None or self.stop_day is None:
            lower = f"(now() - interval '{self.lookback}')"
            return f"{column} >= {lower}{'::date' if daily else ''}", ()
        args = (self.start_day, self.stop_day) if daily else (
            datetime.combine(self.start_day, time.min, timezone.utc),
            datetime.combine(self.stop_day, time.min, timezone.utc),
        )
        return f"{column} >= ${first_parameter} AND {column} < ${first_parameter + 1}", args


_PRESETS = {
    "24h": Period("24h", FIVE_MINUTES, "24 hours", 1),
    "7d": Period("7d", HOUR, "7 days", 7),
    "30d": Period("30d", HOUR, "30 days", 30),
    "365d": Period("365d", DAY, "365 days", 365),
}


def resolve(name: str, start: str | None, end: str | None) -> Period:
    if name != "custom":
        return _PRESETS.get(name, _PRESETS["24h"])
    if not start or not end:
        return replace(_PRESETS["24h"], name="custom")
    try:
        first = date.fromisoformat(start)
        last = date.fromisoformat(end)
        days = (last - first).days + 1
        if days < 1 or first.year < 2 or last.year > 9998:
            raise ValueError
        stop = last + timedelta(days=1)
    except ValueError as exc:
        raise ValueError("Start und Ende als aufsteigenden Zeitraum im Format JJJJ-MM-TT angeben.") from exc
    seconds = FIVE_MINUTES if days <= 2 else HOUR if days <= 45 else DAY
    return Period("custom", seconds, "", days, first, stop)
