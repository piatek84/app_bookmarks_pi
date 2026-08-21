"""Builds the month-grid data the calendar template renders: which days are
today/past, birthdays, vacations, or work-shift rest days.
"""
import calendar as stdlib_calendar
from datetime import date, timedelta
from typing import Optional

WORK_DAYS = 6
REST_DAYS = 3
CYCLE_LENGTH = WORK_DAYS + REST_DAYS


def _add_months(first_of_month: date, months: int) -> date:
    month_index = first_of_month.month - 1 + months
    year = first_of_month.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _is_rest_day(day: date, shift_start: date) -> bool:
    cycle_position = (day - shift_start).days % CYCLE_LENGTH
    return cycle_position >= WORK_DAYS


def build_calendar_months(
    today: date,
    num_months: int,
    birthdays,
    vacations,
    shift_start: Optional[str],
    holidays=(),
    tasks=(),
    months_offset: int = 0,
) -> list[dict]:
    birthday_lookup = {(b["month"], b["day"]): b["title"] for b in birthdays}
    holiday_lookup = {(h["month"], h["day"]): h["title"] for h in holidays}
    task_lookup = {date.fromisoformat(t["task_date"]): t["title"] for t in tasks}
    vacation_ranges = [
        (date.fromisoformat(v["start_date"]), date.fromisoformat(v["end_date"]), v["title"])
        for v in vacations
    ]
    shift_start_date = date.fromisoformat(shift_start) if shift_start else None

    months = []
    first_of_month = _add_months(date(today.year, today.month, 1), months_offset)
    cursor = first_of_month
    for i in range(num_months):
        month_dict, cursor = _build_month(
            _add_months(first_of_month, i),
            cursor,
            today,
            birthday_lookup,
            holiday_lookup,
            vacation_ranges,
            shift_start_date,
            task_lookup,
        )
        months.append(month_dict)
    return months


def _build_month(
    first_day: date,
    start_date: date,
    today: date,
    birthday_lookup,
    holiday_lookup,
    vacation_ranges,
    shift_start: Optional[date],
    task_lookup,
) -> tuple[dict, date]:
    """Builds one month card starting from `start_date` (>= first_day, e.g. when the
    previous card's last week already ran into this month). Weeks are always complete:
    if the month's last week doesn't end on a Sunday, it's filled with the following
    month's opening days instead of blank cells, and the date those days stopped at is
    returned so the next card can pick up right after them.
    """
    days_in_month = stdlib_calendar.monthrange(first_day.year, first_day.month)[1]
    month_end = date(first_day.year, first_day.month, days_in_month)

    def build_day(current: date) -> dict:
        is_future_or_today = current >= today
        birthday_title = birthday_lookup.get((current.month, current.day)) if is_future_or_today else None
        holiday_title = holiday_lookup.get((current.month, current.day)) if is_future_or_today else None
        task_title = task_lookup.get(current) if is_future_or_today else None
        vacation_title = None
        if is_future_or_today:
            for start, end, title in vacation_ranges:
                if start <= current <= end:
                    vacation_title = title
                    break
        is_rest_day = (
            is_future_or_today and shift_start is not None and _is_rest_day(current, shift_start)
        )

        hint_parts = []
        if birthday_title:
            hint_parts.append(f"Birthday: {birthday_title}")
        if holiday_title:
            hint_parts.append(f"Holiday: {holiday_title}")
        if vacation_title:
            hint_parts.append(f"Vacation: {vacation_title}")
        if is_rest_day:
            hint_parts.append("Rest day")
        if task_title:
            hint_parts.append(f"Task: {task_title}")

        return {
            "day": current.day,
            "is_today": current == today,
            "is_past": current < today,
            "birthday_title": birthday_title,
            "holiday_title": holiday_title,
            "vacation_title": vacation_title,
            "is_rest_day": is_rest_day,
            "task_title": task_title,
            "hint": "\n".join(hint_parts) if hint_parts else None,
        }

    weeks: list[list[Optional[dict]]] = []
    week: list[Optional[dict]] = [None] * start_date.weekday()

    current = start_date
    while current <= month_end:
        week.append(build_day(current))
        if len(week) == 7:
            weeks.append(week)
            week = []
        current += timedelta(days=1)

    next_start = _add_months(date(first_day.year, first_day.month, 1), 1)
    if week:
        overflow = next_start
        while len(week) < 7:
            week.append(build_day(overflow))
            overflow += timedelta(days=1)
        weeks.append(week)
        next_start = overflow

    return {"label": first_day.strftime("%B %Y"), "weeks": weeks}, next_start
