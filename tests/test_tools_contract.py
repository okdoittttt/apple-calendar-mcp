"""계층 2 - 프로토콜 계약 테스트: in-memory MCP Client 로 서버를 두드립니다.

실제 Calendar/Reminders 권한이 없어도 통과합니다. 검증 대상:
  - 도구 레지스트리(개수/이름) 회귀 방지
  - 항상 동작하는 도구(check_permissions, server_status)의 응답 형태
  - EventKit 접근 '전에' 결정되는 입력 검증 에러 경로
    (span/scope/priority/working_hours/날짜범위 등은 권한과 무관하게 결정적)
"""

import json

import pytest
from fastmcp import Client, FastMCP

from apple_calendar_mcp.ui_tools import register_ui_tools
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
    # MCP App (UI) - 진입점 도구만 모델에 노출됨(제출 핸들러는 visibility=app 로 숨김)
    "event_composer", "agenda_board",
}


class TestRegistry:
    async def test_tool_count(self, client):
        tools = await client.list_tools()
        assert len(tools) == 30

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
        assert data["tool_count"] == 30
        assert isinstance(data["pid"], int)
        assert "version" in data


class TestMcpApp:
    """MCP App(UI) 배선 검증 - event_composer 등록 폼.

    실제 렌더링은 클라이언트(브라우저/호스트)가 하지만, 서버가 UI 리소스와
    도구 호출 배선을 올바르게 '선언'하는지는 권한 없이도 결정적으로 검증할 수
    있습니다. (계약 회귀 방지)
    """

    async def test_ui_tool_has_app_meta(self, client):
        # event_composer 는 _meta.ui.resourceUri(렌더러) 가 스탬프되어 있어야 함
        tool = next(t for t in await client.list_tools() if t.name == "event_composer")
        assert tool.meta and "ui" in tool.meta
        assert tool.meta["ui"]["resourceUri"].startswith("ui://")
        assert tool.meta["fastmcp"]["app"] == "AppleCalendarUI"

    async def test_submit_handler_hidden_from_model(self, client):
        # 제출 핸들러(create_event_from_form)는 visibility=app 이라 모델 목록에 없어야 함
        names = {t.name for t in await client.list_tools()}
        assert "create_event_from_form" not in names

    async def test_form_wires_submit_to_backend_tool(self, client):
        # event_composer 를 호출하면 Prefab 폼이 나오고, 제출(onSubmit)이
        # 백엔드 핸들러로 toolCall 되도록 배선되어 있어야 함
        res = await client.call_tool("event_composer", {})
        sc = res.structured_content
        blob = json.dumps(sc, ensure_ascii=False)
        assert "$prefab" in sc                # Prefab 앱 래퍼
        assert '"Form"' in blob               # 폼 컴포넌트
        assert "toolCall" in blob             # 제출 → 도구 호출 배선
        assert "create_event_from_form" in blob  # 해시된 백엔드 도구명 포함

    async def test_agenda_board_renders_without_permission(self, client):
        # 읽기 보드는 권한이 없어도 크래시 없이 Prefab UI를 렌더해야 함
        # (권한 없으면 데이터 대신 Alert 안내를 그림)
        res = await client.call_tool("agenda_board", {})
        sc = res.structured_content
        assert "$prefab" in sc
        blob = json.dumps(sc, ensure_ascii=False)
        assert '"Metric"' in blob   # 요약 메트릭 카드
        # 권한 유무와 무관하게: 데이터가 있으면 DataTable, 없으면 Alert/Text 중 하나
        assert ('"DataTable"' in blob) or ('"Alert"' in blob) or ('"Text"' in blob)

    async def test_board_action_handlers_hidden_from_model(self, client):
        # 보드 액션 백엔드(완료/삭제)는 visibility=app 이라 모델 목록에 없어야 함
        names = {t.name for t in await client.list_tools()}
        assert "complete_reminder_from_board" not in names
        assert "delete_event_from_board" not in names


class _FakeStore:
    """권한/실데이터 없이 보드 액션 배선을 검증하기 위한 최소 스텁."""

    def get_events(self, start, end, limit):
        return [{
            "id": "EVT-1", "title": "팀 회의",
            "start_date": "2026-07-16T10:00:00", "end_date": "2026-07-16T11:00:00",
            "location": "3층", "calendar": "업무", "is_all_day": False, "tags": ["work"],
        }]

    def get_reminders(self, due_after, due_before, include_completed, limit):
        return [{
            "id": "REM-1", "title": "보고서 제출",
            "due_date": "2026-07-16T09:00:00", "priority": "high", "tags": [],
        }]


class TestBoardActionWiring:
    """agenda_board 의 행별 액션 버튼 배선 검증 (가짜 store 로 데이터 주입).

    실제 client 픽스처는 권한이 없어 행이 비어 버튼이 렌더되지 않으므로,
    샘플 이벤트/미리 알림을 주는 _FakeStore 로 별도 서버를 띄워 검증한다.
    """

    async def test_rows_render_action_buttons_wired_to_handlers(self):
        mcp = FastMCP("test-board")
        register_ui_tools(mcp, _FakeStore())
        async with Client(mcp) as client:
            res = await client.call_tool("agenda_board", {"start_date": "2026-07-16"})
            blob = json.dumps(res.structured_content, ensure_ascii=False)

        # 액션 버튼은 표 셀이 아니라 표 아래 일반 흐름(Button)으로 렌더된다.
        assert '"Button"' in blob
        assert "toolCall" in blob
        # 미리 알림 [완료] 버튼 → complete_reminder_from_board, id 인자 포함
        assert "complete_reminder_from_board" in blob
        assert "REM-1" in blob
        # 이벤트 [삭제] 버튼 → delete_event_from_board, id 인자 포함
        assert "delete_event_from_board" in blob
        assert "EVT-1" in blob
        # 표 셀에는 컴포넌트를 넣지 않는다(구버전 호스트 렌더러 호환) → Dialog 미사용
        assert '"Dialog"' not in blob


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
