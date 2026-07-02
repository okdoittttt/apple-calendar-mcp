"""macOS에서 EventKit 접근 권한을 처리하는 모듈.

책임 프로세스(responsible process) 관련 참고: EventKit은 EKEventStore를
실행한 프로세스를 기준으로 권한을 부여합니다. 이 서버가 Claude Desktop의
서브프로세스로 실행되면 첫 권한 다이얼로그가 "Claude" 이름으로 뜨거나
(백그라운드 서브프로세스는 UI를 띄우지 못하는 경우가 많아) 전혀 뜨지 않을 수
있습니다. 다이얼로그가 뜨지 않으면 System Settings > Privacy & Security >
Calendar / Reminders에서 직접 권한을 부여하거나, 터미널에서
scripts/setup_permissions.py를 실행해 시스템 다이얼로그를 확실하게 띄우세요.
"""

import threading
from enum import Enum
from typing import Callable, Optional

import EventKit


class AuthorizationStatus(Enum):
    """EventKit 인증 상태 값."""
    NOT_DETERMINED = 0
    RESTRICTED = 1
    DENIED = 2
    AUTHORIZED = 3
    WRITE_ONLY = 4  # macOS 14+ / iOS 17+ (Calendar 엔티티에만 존재)


def get_status_name(status: int) -> str:
    """인증 상태 정수를 읽기 쉬운 이름으로 변환합니다."""
    try:
        return AuthorizationStatus(status).name.lower()
    except ValueError:
        return "unknown"


def check_calendar_permission() -> dict:
    """현재 캘린더 권한 상태를 확인합니다."""
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(
        EventKit.EKEntityTypeEvent
    )
    return {
        "status": get_status_name(status),
        "authorized": status == AuthorizationStatus.AUTHORIZED.value,
        "can_request": status == AuthorizationStatus.NOT_DETERMINED.value,
    }


def check_reminders_permission() -> dict:
    """현재 미리 알림 권한 상태를 확인합니다."""
    status = EventKit.EKEventStore.authorizationStatusForEntityType_(
        EventKit.EKEntityTypeReminder
    )
    return {
        "status": get_status_name(status),
        "authorized": status == AuthorizationStatus.AUTHORIZED.value,
        "can_request": status == AuthorizationStatus.NOT_DETERMINED.value,
    }


def check_permissions() -> dict:
    """캘린더와 미리 알림 권한 상태를 모두 확인합니다."""
    calendar = check_calendar_permission()
    reminders = check_reminders_permission()

    result = {
        "calendar": calendar,
        "reminders": reminders,
        "all_authorized": calendar["authorized"] and reminders["authorized"],
    }

    if not result["all_authorized"]:
        result["instructions"] = get_permission_instructions(calendar, reminders)

    return result


def get_permission_instructions(calendar: dict, reminders: dict) -> str:
    """권한 부여를 위한 사용자 안내 문구를 생성합니다."""
    instructions = []

    if not calendar["authorized"]:
        if calendar["status"] == "denied":
            instructions.append(
                "Calendar access denied. Please enable in: "
                "System Settings > Privacy & Security > Calendar > "
                "Enable access for Claude Desktop (or Terminal)."
            )
        elif calendar["status"] == "restricted":
            instructions.append("Calendar access is restricted by device policy.")
        elif calendar["status"] == "write_only":
            instructions.append(
                "Calendar access is write-only. Reading events requires full "
                "access - re-run scripts/setup_permissions.py or grant full "
                "access in System Settings > Privacy & Security > Calendar."
            )
        else:
            instructions.append(
                "Calendar access not yet requested. "
                "Run `uv run python scripts/setup_permissions.py` from Terminal."
            )

    if not reminders["authorized"]:
        if reminders["status"] == "denied":
            instructions.append(
                "Reminders access denied. Please enable in: "
                "System Settings > Privacy & Security > Reminders > "
                "Enable access for Claude Desktop (or Terminal)."
            )
        elif reminders["status"] == "restricted":
            instructions.append("Reminders access is restricted by device policy.")
        else:
            instructions.append(
                "Reminders access not yet requested. "
                "Run `uv run python scripts/setup_permissions.py` from Terminal."
            )

    return "\n".join(instructions)


def _request_access(
    store: EventKit.EKEventStore,
    entity_type: int,
    full_access_selector: str,
    callback: Callable[[bool, object], None],
) -> None:
    """가능하면 macOS 14+ full-access API를 사용해 권한을 요청하고,
    없으면 예전 requestAccessToEntityType:completion: API로 폴백합니다.
    """
    full_access_method = getattr(store, full_access_selector, None)
    if full_access_method is not None:
        full_access_method(callback)
    else:
        store.requestAccessToEntityType_completion_(entity_type, callback)


def request_calendar_access(
    store: EventKit.EKEventStore,
    callback: Optional[Callable[[bool, object], None]] = None,
) -> None:
    """캘린더 접근 권한을 요청합니다 (결과를 기다리지 않는 논블로킹 방식).

    참고: macOS에서는 UI를 띄울 수 있는 컨텍스트에서 실행할 때만 다이얼로그가
    표시됩니다. Claude Desktop의 서브프로세스로 실행 중이라면 수동으로
    권한을 부여하거나 setup_permissions.py를 실행해야 할 수 있습니다.
    """
    def default_callback(granted: bool, error: object) -> None:
        pass

    _request_access(
        store,
        EventKit.EKEntityTypeEvent,
        "requestFullAccessToEventsWithCompletion_",
        callback or default_callback,
    )


def request_reminders_access(
    store: EventKit.EKEventStore,
    callback: Optional[Callable[[bool, object], None]] = None,
) -> None:
    """미리 알림 접근 권한을 요청합니다 (결과를 기다리지 않는 논블로킹 방식)."""
    def default_callback(granted: bool, error: object) -> None:
        pass

    _request_access(
        store,
        EventKit.EKEntityTypeReminder,
        "requestFullAccessToRemindersWithCompletion_",
        callback or default_callback,
    )


def request_all_permissions(store: EventKit.EKEventStore) -> None:
    """캘린더와 미리 알림 권한을 모두 요청합니다 (논블로킹).

    아직 결정되지 않은 권한이 있으면 시스템 다이얼로그를 띄웁니다.
    서버 시작 시 사용되며, 이 시점에는 다이얼로그 응답을 기다리며 블로킹하면
    MCP 초기화가 멈추게 되므로 논블로킹으로 동작합니다.
    """
    calendar = check_calendar_permission()
    reminders = check_reminders_permission()

    if calendar["can_request"]:
        request_calendar_access(store)

    if reminders["can_request"]:
        request_reminders_access(store)


def request_all_permissions_sync(
    store: EventKit.EKEventStore, timeout: float = 60.0
) -> dict:
    """두 권한을 모두 요청하고, 콜백이 모두 호출되거나 타임아웃될 때까지 대기합니다.

    대화형 사용(scripts/setup_permissions.py)을 위한 것으로, 사용자가 시스템
    다이얼로그에 응답할 때까지 기다리는 것이 자연스러운 상황에서 사용합니다.
    """
    results = {"calendar": None, "reminders": None}

    calendar_status = check_calendar_permission()
    reminders_status = check_reminders_permission()

    pending_events = []

    if calendar_status["can_request"]:
        calendar_done = threading.Event()
        pending_events.append(calendar_done)

        def calendar_callback(granted: bool, error: object) -> None:
            results["calendar"] = bool(granted)
            calendar_done.set()

        request_calendar_access(store, calendar_callback)
    else:
        results["calendar"] = calendar_status["authorized"]

    if reminders_status["can_request"]:
        reminders_done = threading.Event()
        pending_events.append(reminders_done)

        def reminders_callback(granted: bool, error: object) -> None:
            results["reminders"] = bool(granted)
            reminders_done.set()

        request_reminders_access(store, reminders_callback)
    else:
        results["reminders"] = reminders_status["authorized"]

    for event in pending_events:
        event.wait(timeout=timeout)

    return results


class PermissionError(Exception):
    """EventKit 권한이 충분하지 않을 때 발생시키는 예외."""

    def __init__(self, entity_type: str, status: str):
        self.entity_type = entity_type
        self.status = status
        instructions = self._get_instructions()
        super().__init__(f"{entity_type} access {status}. {instructions}")

    def _get_instructions(self) -> str:
        if self.status == "denied":
            return (
                f"Please enable access in System Settings > Privacy & Security > "
                f"{self.entity_type}. Add Claude Desktop (or Terminal) to allowed apps."
            )
        elif self.status == "restricted":
            return "Access is restricted by device policy."
        return "Please run `uv run python scripts/setup_permissions.py` to request permissions."


def require_calendar_permission() -> None:
    """캘린더 접근 권한이 없으면 PermissionError를 발생시킵니다."""
    perm = check_calendar_permission()
    if not perm["authorized"]:
        raise PermissionError("Calendar", perm["status"])


def require_reminders_permission() -> None:
    """미리 알림 접근 권한이 없으면 PermissionError를 발생시킵니다."""
    perm = check_reminders_permission()
    if not perm["authorized"]:
        raise PermissionError("Reminders", perm["status"])
