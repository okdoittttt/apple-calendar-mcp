"""pytest 공통 설정: fixture, 헬퍼, 권한 기반 스킵 로직.

테스트는 3계층으로 나뉩니다 (README 및 대화 참고):
  1) 순수 유닛      - EventKit/MCP 불필요 (test_tags.py, test_quick_event_parser.py)
  2) 프로토콜 계약  - in-memory MCP Client 사용, 권한 불필요 (test_tools_contract.py)
  3) 통합           - 실제 Calendar/Reminders 권한 필요 (test_integration.py)

계층 3은 권한이 없으면 자동으로 skip 되고, 쓰기(변경) 테스트는
환경변수 APPLE_CAL_MCP_WRITE_TESTS=1 로 명시적으로 켜야만 실행됩니다.
"""

import os
import sys

import pytest
import pytest_asyncio

# src 레이아웃 패키지를 확실히 import 할 수 있게 함 (uv sync 시엔 이미 설치되어 있지만 안전장치)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fastmcp import Client

from apple_calendar_mcp.server import mcp
from apple_calendar_mcp.permissions import (
    check_calendar_permission,
    check_reminders_permission,
)


@pytest_asyncio.fixture
async def client():
    """실제 MCP 프로토콜 경로를 태우는 in-memory 클라이언트.

    서브프로세스가 없어 빠르고 macOS 권한 다이얼로그도 뜨지 않습니다.
    """
    async with Client(mcp) as c:
        yield c


def result_dict(res) -> dict:
    """CallToolResult 에서 도구가 반환한 dict를 꺼냅니다.

    fastmcp 3.x는 구조화 출력을 .data(역직렬화됨) / .structured_content(원본 dict)로
    노출합니다. 어느 쪽이든 dict를 돌려주도록 처리합니다.
    """
    data = getattr(res, "data", None)
    if isinstance(data, dict):
        return data
    sc = getattr(res, "structured_content", None)
    if isinstance(sc, dict):
        return sc
    raise AssertionError(f"도구 결과에서 dict를 찾을 수 없습니다: {res!r}")


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_calendar: 실제 Calendar 권한이 있어야 실행")
    config.addinivalue_line("markers", "requires_reminders: 실제 Reminders 권한이 있어야 실행")
    config.addinivalue_line(
        "markers",
        "write: 실제 데이터를 변경함. APPLE_CAL_MCP_WRITE_TESTS=1 일 때만 실행",
    )


def pytest_runtest_setup(item):
    """마커에 따라 권한이 없거나 opt-in이 아니면 테스트를 건너뜁니다."""
    if item.get_closest_marker("requires_calendar"):
        if not check_calendar_permission()["authorized"]:
            pytest.skip("Calendar 권한 없음 (scripts/setup_permissions.py 실행 필요)")

    if item.get_closest_marker("requires_reminders"):
        if not check_reminders_permission()["authorized"]:
            pytest.skip("Reminders 권한 없음 (scripts/setup_permissions.py 실행 필요)")

    if item.get_closest_marker("write"):
        if os.environ.get("APPLE_CAL_MCP_WRITE_TESTS") != "1":
            pytest.skip("쓰기 테스트는 opt-in: APPLE_CAL_MCP_WRITE_TESTS=1 로 실행하세요")
