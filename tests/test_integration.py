"""계층 3 - 통합 테스트: 실제 EventKit(Calendar/Reminders)에 접근합니다.

권한이 없으면 conftest.pytest_runtest_setup 에서 자동 skip 됩니다.
쓰기(변경) 테스트는 실제 캘린더를 건드리므로 이중 안전장치를 둡니다:
  - @pytest.mark.write 마커 + APPLE_CAL_MCP_WRITE_TESTS=1 환경변수가 있어야 실행
  - 생성한 항목은 finally 에서 반드시 삭제 (테스트가 실패해도 정리)

실행 예:
  uv run pytest tests/test_integration.py -v                       # 읽기만
  APPLE_CAL_MCP_WRITE_TESTS=1 uv run pytest tests/test_integration.py -v   # 쓰기 포함
"""

import pytest

from conftest import result_dict

pytestmark = pytest.mark.asyncio


class TestReadOnly:
    @pytest.mark.requires_calendar
    async def test_list_calendars(self, client):
        data = result_dict(await client.call_tool("calendar_list_calendars", {}))
        assert data["success"] is True
        assert isinstance(data["calendars"], list)
        assert data["count"] == len(data["calendars"])

    @pytest.mark.requires_calendar
    async def test_list_events_returns_list(self, client):
        data = result_dict(await client.call_tool(
            "calendar_list_events",
            {"start_date": "2026-07-01", "end_date": "2026-07-31"},
        ))
        assert data["success"] is True
        assert isinstance(data["events"], list)
        assert "today" in data  # 현재 시각 컨텍스트가 포함됨

    @pytest.mark.requires_reminders
    async def test_list_reminder_lists(self, client):
        data = result_dict(await client.call_tool("reminders_list_lists", {}))
        assert data["success"] is True
        assert isinstance(data["lists"], list)

    @pytest.mark.requires_calendar
    async def test_find_free_slots_valid(self, client):
        data = result_dict(await client.call_tool(
            "find_free_slots", {"date": "2026-07-16", "working_hours": "09:00-18:00"}
        ))
        assert data["success"] is True
        assert isinstance(data["slots"], list)


class TestWriteRoundTrip:
    """생성 -> 조회 -> 삭제 를 실제 캘린더에서 수행 (opt-in).

    이 방식은 통합 테스트에서 흔한 패턴입니다: 부수효과를 만든 뒤 반드시
    되돌려(cleanup) 테스트가 시스템 상태를 오염시키지 않게 합니다.
    """

    @pytest.mark.requires_calendar
    @pytest.mark.write
    async def test_create_get_delete_event(self, client):
        title = "【MCP 테스트】 삭제해도 됩니다"
        created = result_dict(await client.call_tool("calendar_create_event", {
            "title": title,
            "start_date": "2099-01-01T10:00:00",   # 실제 일정과 겹치지 않게 먼 미래
            "end_date": "2099-01-01T11:00:00",
            "notes": "pytest 통합 테스트에서 생성",
        }))
        assert created["success"] is True, created
        event_id = created["event"]["id"]

        try:
            # 조회로 생성 확인
            got = result_dict(await client.call_tool("calendar_get_event", {"event_id": event_id}))
            assert got["success"] is True
            assert got["event"]["title"] == title
        finally:
            # 성공/실패와 무관하게 정리
            deleted = result_dict(await client.call_tool(
                "calendar_delete_event", {"event_id": event_id, "span": "this_event"}
            ))
            assert deleted["success"] is True, deleted
