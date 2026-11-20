"""Timezone-aware date/time parsing, quiet hours, and recurrence calculation helpers."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

UZBEK_WEEKDAYS = {
    0: "Dushanba",
    1: "Seshanba",
    2: "Chorshanba",
    3: "Payshanba",
    4: "Juma",
    5: "Shanba",
    6: "Yakshanba",
}

UZBEK_WEEKDAYS_SHORT = {
    0: "Du",
    1: "Se",
    2: "Ch",
    3: "Pa",
    4: "Ju",
    5: "Sh",
    6: "Ya",
}

UZBEK_MONTHS = {
    1: "yanvar",
    2: "fevral",
    3: "mart",
    4: "aprel",
    5: "may",
    6: "iyun",
    7: "iyul",
    8: "avgust",
    9: "sentabr",
    10: "oktabr",
    11: "noyabr",
    12: "dekabr",
}


def get_zone(tz_name: str = "Asia/Tashkent") -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Asia/Tashkent")


def now_in_tz(tz_name: str = "Asia/Tashkent") -> datetime:
    return datetime.now(get_zone(tz_name))


def to_tz(dt: datetime, tz_name: str = "Asia/Tashkent") -> datetime:
    zone = get_zone(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone)
    return dt.astimezone(zone)


def parse_user_date(raw: str, tz_name: str = "Asia/Tashkent") -> Optional[date]:
    text = raw.strip().lower()
    today = now_in_tz(tz_name).date()
    if text in {"bugun", "bugungi"}:
        return today
    if text in {"ertaga", "ertangi"}:
        return today + timedelta(days=1)
    if text in {"indinga", "ertadan keyin"}:
        return today + timedelta(days=2)

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_user_time(raw: str) -> Optional[time]:
    text = raw.strip().replace(".", ":")
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def parse_quiet_range(raw: str) -> Optional[tuple[str, str]]:
    """Parse '23:00-07:00' quiet hours range into normalized HH:MM tuple."""
    cleaned = raw.strip().replace("–", "-").replace(" ", "")
    if "-" not in cleaned:
        return None
    left, right = cleaned.split("-", 1)
    t1 = parse_user_time(left)
    t2 = parse_user_time(right)
    if t1 is None or t2 is None:
        return None
    return (t1.strftime("%H:%M"), t2.strftime("%H:%M"))


def is_in_quiet_hours(
    dt: datetime,
    quiet_start: str = "23:00",
    quiet_end: str = "07:00",
    tz_name: str = "Asia/Tashkent",
) -> bool:
    """Return True if local time falls inside quiet hours (supports overnight ranges)."""
    local_t = to_tz(dt, tz_name).time().replace(second=0, microsecond=0)
    start_t = parse_user_time(quiet_start) or time(23, 0)
    end_t = parse_user_time(quiet_end) or time(7, 0)

    if start_t == end_t:
        return False
    if start_t < end_t:
        return start_t <= local_t < end_t
    # Overnight window (e.g., 23:00 -> 07:00)
    return local_t >= start_t or local_t < end_t


def next_allowed_after_quiet_hours(
    dt: datetime,
    quiet_start: str = "23:00",
    quiet_end: str = "07:00",
    tz_name: str = "Asia/Tashkent",
) -> datetime:
    """If dt is inside quiet hours, shift it to quiet_end + 1 minute."""
    local = to_tz(dt, tz_name)
    if not is_in_quiet_hours(local, quiet_start, quiet_end, tz_name):
        return local

    start_t = parse_user_time(quiet_start) or time(23, 0)
    end_t = parse_user_time(quiet_end) or time(7, 0)
    target_date = local.date()
    if start_t > end_t and local.time() >= start_t:
        target_date = target_date + timedelta(days=1)

    resumed = datetime.combine(target_date, end_t).replace(tzinfo=get_zone(tz_name))
    return resumed + timedelta(minutes=1)


def combine_local(d: date, t: time, tz_name: str = "Asia/Tashkent") -> datetime:
    return datetime.combine(d, t).replace(tzinfo=get_zone(tz_name))


def format_uz_datetime(dt: datetime, tz_name: str = "Asia/Tashkent") -> str:
    local = to_tz(dt, tz_name)
    month_name = UZBEK_MONTHS.get(local.month, str(local.month))
    weekday_name = UZBEK_WEEKDAYS.get(local.weekday(), "")
    return f"{local.day:02d}-{month_name} ({weekday_name}), {local.strftime('%H:%M')}"


def compute_next_occurrence(
    current_dt: datetime,
    recurrence_type: str,
    recurrence_days: Optional[str] = None,
    tz_name: str = "Asia/Tashkent",
    reference_now: Optional[datetime] = None,
) -> Optional[datetime]:
    """Compute the next execution datetime for recurring reminders."""
    local = to_tz(current_dt, tz_name)
    ref = to_tz(reference_now or now_in_tz(tz_name), tz_name)

    if recurrence_type == "once":
        return None

    candidate = local
    if recurrence_type == "daily":
        while candidate <= ref:
            candidate += timedelta(days=1)
        return candidate

    if recurrence_type == "weekly":
        while candidate <= ref:
            candidate += timedelta(weeks=1)
        return candidate

    if recurrence_type == "monthly":
        while candidate <= ref:
            year = candidate.year + (1 if candidate.month == 12 else 0)
            month = 1 if candidate.month == 12 else candidate.month + 1
            max_day = calendar.monthrange(year, month)[1]
            day = min(local.day, max_day)
            candidate = candidate.replace(year=year, month=month, day=day)
        return candidate

    if recurrence_type == "custom_days":
        allowed_days = sorted(
            {
                int(x.strip())
                for x in (recurrence_days or "").split(",")
                if x.strip().isdigit() and 0 <= int(x.strip()) <= 6
            }
        )
        if not allowed_days:
            return None
        probe = local + timedelta(days=1)
        for _ in range(366):
            if probe.weekday() in allowed_days and probe > ref:
                return probe
            probe += timedelta(days=1)
        return None

    return None


def format_recurrence_uz(recurrence_type: str, recurrence_days: Optional[str] = None) -> str:
    mapping = {
        "once": "Bir martalik",
        "daily": "Har kuni",
        "weekly": "Har hafta",
        "monthly": "Har oy",
        "custom_days": "Belgilangan kunlarda",
    }
    base = mapping.get(recurrence_type, recurrence_type)
    if recurrence_type == "custom_days" and recurrence_days:
        labels = [
            UZBEK_WEEKDAYS_SHORT.get(int(d.strip()), d.strip())
            for d in recurrence_days.split(",")
            if d.strip().isdigit()
        ]
        if labels:
            return f"{base} ({', '.join(labels)})"
    return base
