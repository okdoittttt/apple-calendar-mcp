"""계층 1 - 순수 유닛 테스트: quick_event 의 자연어 파서(_quick_event_parse).

파서는 now 를 인자로 받으므로 고정 시각을 주입해 결정적으로 테스트합니다.
(datetime.now() 에 의존하면 실행 시각마다 결과가 달라져 테스트가 흔들립니다.)
"""

from datetime import datetime, timedelta

import pytest

from apple_calendar_mcp.extras import _quick_event_parse

# 2026-07-16 은 목요일. 상대 날짜 계산의 기준점으로 고정.
NOW = datetime(2026, 7, 16, 10, 30)


def test_tomorrow_and_meal_default_time():
    r = _quick_event_parse("lunch tomorrow", now=NOW)
    assert r["start"].date() == (NOW + timedelta(days=1)).date()
    assert r["start"].hour == 12  # 'lunch' -> 기본 12:00
    assert "lunch" in r["title"].lower()


def test_today_with_explicit_time_and_duration():
    r = _quick_event_parse("meeting today at 3pm for 30 min", now=NOW)
    assert r["start"].date() == NOW.date()
    assert r["start"].hour == 15                      # 3pm -> 15:00
    assert (r["end"] - r["start"]) == timedelta(minutes=30)
    assert r["title"] == "meeting"


def test_explicit_date_and_tags():
    r = _quick_event_parse("call 2026-08-01 at 9am #work #urgent", now=NOW)
    assert r["start"].date() == datetime(2026, 8, 1).date()
    assert r["start"].hour == 9
    assert r["tags"] == ["work", "urgent"]


def test_in_n_days():
    r = _quick_event_parse("standup in 3 days", now=NOW)
    assert r["start"].date() == (NOW + timedelta(days=3)).date()


def test_weekday_points_to_next_occurrence():
    r = _quick_event_parse("team sync mon", now=NOW)  # NOW 는 목요일
    assert r["start"].weekday() == 0                  # 다음 월요일
    assert r["start"].date() > NOW.date()


def test_default_time_and_duration_when_unspecified():
    r = _quick_event_parse("review notes tomorrow", now=NOW)
    assert r["start"].hour == 9                        # 기본 09:00
    assert (r["end"] - r["start"]) == timedelta(hours=1)  # 기본 1시간


def test_24h_time_format():
    r = _quick_event_parse("deploy today at 15:00", now=NOW)
    assert (r["start"].hour, r["start"].minute) == (15, 0)


def test_full_sentence_title_is_cleaned():
    r = _quick_event_parse("lunch with Sara tomorrow at 1pm #personal", now=NOW)
    assert r["title"] == "lunch with Sara"
    assert r["start"].hour == 13
    assert r["tags"] == ["personal"]
    assert r["start"].date() == (NOW + timedelta(days=1)).date()


def test_no_tags_returns_none():
    r = _quick_event_parse("plain event tomorrow", now=NOW)
    assert r["tags"] is None
