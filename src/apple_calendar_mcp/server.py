"""apple-calendar MCP 서버 - MCP를 통해 Apple 캘린더와 미리 알림에 접근합니다."""

from fastmcp import FastMCP

from .eventkit_store import EventKitStore
from .calendar_tools import register_calendar_tools
from .reminder_tools import register_reminder_tools
from .tag_tools import register_tag_tools
from .extras import register_extra_tools
from .admin import register_admin_tools
from .ui_tools import register_ui_tools
from .permissions import check_permissions


# FastMCP 서버 초기화
mcp = FastMCP("apple-calendar")

# EventKit 스토어 초기화 (싱글턴)
store = EventKitStore()


@mcp.tool()
def eventkit_check_permissions() -> dict:
    """캘린더와 미리 알림의 권한 상태를 확인합니다.

    캘린더와 미리 알림 각각의 현재 인증 상태와, 권한이 필요한 경우
    안내 문구를 함께 반환합니다.
    """
    return check_permissions()


register_calendar_tools(mcp, store)
register_reminder_tools(mcp, store)
register_tag_tools(mcp, store)
register_extra_tools(mcp, store)
register_admin_tools(mcp)
register_ui_tools(mcp, store)


def main():
    """MCP 서버의 진입점."""
    # 시작 시 권한 요청을 시도합니다 (서브프로세스에서는 UI가 뜨지 않을 수 있음;
    # 확실한 방법은 scripts/setup_permissions.py 참고).
    try:
        store.request_permissions()
    except Exception:
        pass

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
