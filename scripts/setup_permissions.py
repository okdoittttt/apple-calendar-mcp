#!/usr/bin/env python3
"""
macOS에서 캘린더/미리 알림 권한을 요청하기 위한 설정 스크립트.

macOS 권한 다이얼로그를 띄우기 위해 터미널에서 이 스크립트를 한 번
실행하세요. MCP 서버가 Claude Desktop의 서브프로세스로 실행될 때는
권한 다이얼로그를 직접 띄우지 못할 수 있어 이 스크립트가 필요합니다
(EventKit은 이벤트 스토어를 실행한 프로세스를 기준으로 다이얼로그를
띄웁니다 - 자세한 내용은 apple_calendar_mcp/permissions.py 참고).

사용법:
    uv run python scripts/setup_permissions.py

실행 후 캘린더와 미리 알림에 대한 권한 다이얼로그가 보여야 합니다.
둘 다 허용해주세요. 이 스크립트가 아니라 Claude Desktop의 서브프로세스로
MCP 서버를 실행하는 경우라면, System Settings > Privacy & Security에서
Claude Desktop을 직접 추가해야 할 수도 있습니다.

다이얼로그가 뜨지 않으면 수동으로 권한을 부여하세요:
1. System Settings > Privacy & Security > Calendar 열기
2. Terminal(또는 이 스크립트를 실행한 앱)을 허용 목록에 추가
3. Reminders에서도 동일하게 반복
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

try:
    import EventKit
except ImportError:
    print("Error: pyobjc-framework-EventKit is required.")
    print("Install it with: uv sync")
    sys.exit(1)

from apple_calendar_mcp.permissions import (
    get_status_name,
    check_calendar_permission,
    check_reminders_permission,
    request_all_permissions_sync,
)


def print_status():
    cal = check_calendar_permission()
    rem = check_reminders_permission()
    print("\n=== Current Permission Status ===")
    print(f"Calendar:  {cal['status']}")
    print(f"Reminders: {rem['status']}")
    return cal, rem


def main():
    print("=" * 60)
    print("apple-calendar MCP Server - Permission Setup")
    print("=" * 60)
    print()
    print("This will request Calendar and Reminders permissions.")
    print("You should see system dialogs asking for permission -")
    print("this may take a few seconds to appear.")
    print()

    store = EventKit.EKEventStore.alloc().init()
    cal_before, rem_before = print_status()

    if cal_before["can_request"] or rem_before["can_request"]:
        print("\nWaiting for permission dialog(s) (up to 60s)...")
        results = request_all_permissions_sync(store, timeout=60)
        print(f"\nCalendar granted:  {results['calendar']}")
        print(f"Reminders granted: {results['reminders']}")
    else:
        print("\nBoth permissions were already determined (no dialog to show).")

    print("\n" + "=" * 60)
    final_cal, final_rem = print_status()
    print("=" * 60)

    if final_cal["authorized"] and final_rem["authorized"]:
        print("\nSUCCESS: All permissions granted.")
        print("You can now use the apple-calendar MCP server with Claude Desktop.")
    else:
        print("\nSome permissions are still missing.")
        print("\nTo grant them manually:")
        print("1. Open System Settings > Privacy & Security > Calendar")
        print("   Enable access for Terminal (or your terminal app) or Claude Desktop")
        print("2. Open System Settings > Privacy & Security > Reminders")
        print("   Enable access the same way")
        print("\nSee README.md for the responsible-process caveat and more detail.")


if __name__ == "__main__":
    main()
