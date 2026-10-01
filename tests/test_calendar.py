from __future__ import annotations

from datetime import date

from flows import calendar


def test_holidays_and_carnival_are_not_business_days():
    assert not calendar.is_business_day(date(2026, 9, 7))     # Independence Day
    assert not calendar.is_business_day(date(2026, 2, 17))    # Carnival Tuesday
    assert not calendar.is_business_day(date(2025, 11, 20))   # national since 2024
    assert calendar.is_business_day(date(2026, 9, 8))


def test_lag_counts_business_days_after_the_competence_day():
    friday = date(2026, 9, 25)
    assert calendar.lag(friday, friday) == 0
    assert calendar.lag(friday, date(2026, 9, 27)) == 0       # Sunday
    assert calendar.lag(friday, date(2026, 9, 28)) == 1       # Monday
    assert calendar.lag(date(2026, 9, 4), date(2026, 9, 8)) == 1   # over the 7 Sep holiday
