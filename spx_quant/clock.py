"""Time zones and the trading calendar without tzdata.

Windows ships no IANA database, so zoneinfo would need a pip install there. US
daylight time has one rule since 2007 (second Sunday of March to first Sunday of
November, 2:00 local), which is all this project needs.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

UTC = timezone.utc

# NYSE full-day closures. Source: nyse.com/markets/hours-calendars (2026 and 2027 schedules).
HOLIDAYS = {
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
    date(2026, 6, 19), date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15), date(2027, 3, 26), date(2027, 5, 31),
    date(2027, 6, 18), date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25), date(2027, 12, 24),
}
# NYSE 1:00 PM early closes; SPX options stop trading at 1:15 PM ET those days instead of 4:15 PM.
EARLY_CLOSES = {date(2026, 11, 27), date(2026, 12, 24), date(2027, 11, 26)}
ZONES = {"ET": -5, "PT": -8}  # standard-time offsets in hours


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def offset(zone: str, dt_utc: datetime) -> timedelta:
    std = timedelta(hours=ZONES[zone])
    y = dt_utc.year
    start = datetime.combine(_nth_sunday(y, 3, 2), time(2), UTC) - std
    end = datetime.combine(_nth_sunday(y, 11, 1), time(2), UTC) - std - timedelta(hours=1)
    return std + timedelta(hours=1) if start <= dt_utc.astimezone(UTC) < end else std


def to_local(zone: str, dt_utc: datetime) -> datetime:
    off = offset(zone, dt_utc)
    return dt_utc.astimezone(timezone(off, zone))


def local_to_utc(zone: str, wall: datetime) -> datetime:
    """Naive wall-clock time in ET or PT -> aware UTC."""
    std = timedelta(hours=ZONES[zone])
    guess = (wall - std - timedelta(hours=1)).replace(tzinfo=UTC)
    if offset(zone, guess) == std + timedelta(hours=1):
        return guess
    return (wall - std).replace(tzinfo=UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def options_close(d: date) -> datetime:
    """When SPX options stop trading on day d, in UTC."""
    return local_to_utc("ET", datetime.combine(d, time(13, 15) if d in EARLY_CLOSES else time(16, 15)))


def market_date(dt_utc: datetime) -> date:
    return to_local("ET", dt_utc).date()


def fmt(dt_utc: datetime | None, zone: str = "PT") -> str:
    if dt_utc is None:
        return "n/a"
    loc = to_local(zone, dt_utc)
    return f"{loc:%Y-%m-%d %H:%M} {zone}"


def parse_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
