from datetime import date

from bookmarks_pi import calendar_service


def test_build_calendar_months_returns_requested_count():
    months = calendar_service.build_calendar_months(date(2026, 1, 15), 3, [], [], None)
    assert len(months) == 3
    assert "January" in months[0]["label"]
    assert "February" in months[1]["label"]
    assert "March" in months[2]["label"]


def _find_day(months, day_number):
    for week in months[0]["weeks"]:
        for day in week:
            if day is not None and day["day"] == day_number:
                return day
    raise AssertionError(f"day {day_number} not found")


def test_birthday_is_marked_on_future_occurrence():
    birthdays = [{"month": 1, "day": 20, "title": "Alex"}]
    months = calendar_service.build_calendar_months(date(2026, 1, 15), 1, birthdays, [], None)
    assert _find_day(months, 20)["birthday_title"] == "Alex"
    assert _find_day(months, 10)["birthday_title"] is None


def test_vacation_range_is_marked():
    vacations = [{"start_date": "2026-01-18", "end_date": "2026-01-20", "title": "Trip"}]
    months = calendar_service.build_calendar_months(date(2026, 1, 15), 1, [], vacations, None)
    assert _find_day(months, 19)["vacation_title"] == "Trip"
    assert _find_day(months, 17)["vacation_title"] is None


def test_work_shift_cycle_is_six_on_three_off():
    months = calendar_service.build_calendar_months(date(2026, 1, 1), 1, [], [], "2026-01-01")
    rest_days = [d["day"] for week in months[0]["weeks"] for d in week if d and d["is_rest_day"]]
    assert rest_days[:3] == [7, 8, 9]


def test_past_days_are_not_marked():
    birthdays = [{"month": 1, "day": 10, "title": "Alex"}]
    months = calendar_service.build_calendar_months(date(2026, 1, 15), 1, birthdays, [], "2026-01-01")
    past_day = _find_day(months, 10)
    assert past_day["is_past"] is True
    assert past_day["birthday_title"] is None
    assert past_day["is_rest_day"] is False
