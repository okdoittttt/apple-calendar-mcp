"""계층 2 - 프로토콜 계약 테스트: in-memory MCP Client 로 서버를 두드립니다.

실제 Calendar/Reminders 권한이 없어도 통과합니다. 검증 대상:
  - 도구 레지스트리(개수/이름) 회귀 방지
  - 항상 동작하는 도구(check_permissions, server_status)의 응답 형태
  - EventKit 접근 '전에' 결정되는 입력 검증 에러 경로
    (span/scope/priority/working_hours/날짜범위 등은 권한과 무관하게 결정적)
"""

import pytest

from conftest import result_dict

# 이 파일의 모든 테스트는 async
pytestmark = pytest.mark.asyncio

EXPECTED_TOOLS = {
    # calendar
    "calendar_list_calendars", "calendar_list_events", "calendar_get_event",
    "calendar_search_events", "calendar_create_event", "calendar_edit_event",
    "calendar_delete_event",
    # reminders
    "reminders_list_lists", "reminders_list", "reminders_get", "reminders_search",
    "reminders_create", "reminders_edit", "reminders_complete", "reminders_delete",
    # tags
    "tags_list", "tags_rename", "tags_merge", "tags_delete",
    # extras
    "agenda_today", "agenda_range", "quick_event", "reschedule_event", "find_free_slots",
    # admin
    "server_status", "server_restart", "server_stop",
    # permissions
    "eventkit_check_permissions",
}


class TestRegistry:
    async def test_tool_count(self, client):
        tools = await client.list_tools()
        assert len(tools) == 28

    async def test_tool_names_match(self, client):
        names = {t.name for t in await client.list_tools()}
        assert names == EXPECTED_TOOLS

    async def test_every_tool_has_description(self, client):
        for t in await client.list_tools():
            assert t.description, f"{t.name} 에 설명(docstring)이 없습니다"


class TestAlwaysAvailableTools:
    """권한과 무관하게 항상 동작하는 도구들."""

    async def test_check_permissions_shape(self, client):
        data = result_dict(await client.call_tool("eventkit_check_permissions", {}))
        assert "calendar" in data and "reminders" in data
        assert "all_authorized" in data
        assert set(data["calendar"]) >= {"status", "authorized", "can_request"}

    async def test_server_status_shape(self, client):
        data = result_dict(await client.call_tool("server_status", {}))
        assert data["success"] is True
        assert data["tool_count"] == 28
        assert isinstance(data["pid"], int)
        assert "version" in data


class TestInputValidation:
    """EventKit 접근 이전에 결정되는 검증 에러 (권한 없이도 결정적)."""

    async def test_edit_event_bad_span(self, client):
        data = result_dict(await client.call_tool(
            "calendar_edit_event", {"event_id": "x", "span": "nope"}
        ))
        assert data["success"] is False
        assert data["error"] == "invalid_span"

    async def test_delete_event_bad_span(self, client):
        data = result_dict(await client.call_tool(
            "calendar_delete_event", {"event_id": "x", "span": "nope"}
        ))
        assert data["error"] == "invalid_span"

    async def test_reschedule_bad_span(self, client):
        data = result_dict(await client.call_tool(
            "reschedule_event", {"event_id": "x", "new_start": "2026-07-16T10:00", "span": "nope"}
        ))
        assert data["error"] == "invalid_span"

    @pytest.mark.parametrize("tool", ["tags_rename", "tags_merge", "tags_delete"])
    async def test_tag_tools_bad_scope(self, client, tool):
        args = {"scope": "bogus"}
        if tool == "tags_rename":
            args |= {"old_tag": "a", "new_tag": "b"}
        elif tool == "tags_merge":
            args |= {"from_tag": "a", "into_tag": "b"}
        else:
            args |= {"tag": "a"}
        data = result_dict(await client.call_tool(tool, args))
        assert data["error"] == "invalid_scope"

    async def test_tags_rename_empty_tag(self, client):
        data = result_dict(await client.call_tool(
            "tags_rename", {"old_tag": "  ", "new_tag": "  ", "scope": "all"}
        ))
        assert data["error"] == "invalid_tag"

    async def test_reminders_create_bad_priority(self, client):
        data = result_dict(await client.call_tool(
            "reminders_create", {"title": "t", "priority": "urgent"}
        ))
        assert data["error"] == "invalid_priority"

    async def test_find_free_slots_bad_working_hours(self, client):
        data = result_dict(await client.call_tool(
            "find_free_slots", {"date": "2026-07-16", "working_hours": "not-a-range"}
        ))
        assert data["error"] == "invalid_working_hours"

    async def test_agenda_range_end_before_start(self, client):
        data = result_dict(await client.call_tool(
            "agenda_range", {"start_date": "2026-07-20", "end_date": "2026-07-10"}
        ))
        assert data["error"] == "invalid_range"

    async def test_list_events_bad_date_format(self, client):
        data = result_dict(await client.call_tool(
            "calendar_list_events", {"start_date": "16-07-2026", "end_date": "2026-07-20"}
        ))
        # 잘못된 날짜 -> invalid_date (권한이 있으면 permission_denied 가 아닌 이 경로로 옴)
        assert data["success"] is False
        assert data["error"] in {"invalid_date", "unexpected_error"}
