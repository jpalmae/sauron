from datetime import UTC, datetime

from sauron_api.scheduled_reports import next_report_run, report_period_start


def test_next_daily_report_uses_requested_timezone():
    after = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)  # 11:00 in Santiago

    result = next_report_run("daily", 8, 30, "America/Santiago", after=after)

    assert result == datetime(2026, 8, 20, 12, 30, tzinfo=UTC)


def test_report_periods_cover_expected_window():
    now = datetime(2026, 8, 19, tzinfo=UTC)
    assert (now - report_period_start("daily", now)).days == 1
    assert (now - report_period_start("weekly", now)).days == 7
    assert (now - report_period_start("monthly", now)).days == 31
