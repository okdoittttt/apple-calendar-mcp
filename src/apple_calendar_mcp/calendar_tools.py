"""MCP 서버용 캘린더 도구."""

from datetime import datetime, timedelta
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .eventkit_store import EventKitStore
from .permissions import PermissionError


def _get_current_datetime_context() -> dict:
    """일정 관리에 도움이 되는 현재 날짜/시간 정보를 가져옵니다.

    현재 날짜, 시간, 요일, 앞으로 며칠간의 날짜 매핑을 담은 dict를 반환합니다.
    """
    try:
        tz_name = str(datetime.now().astimezone().tzinfo)
    except Exception:
        tz_name = "local"

    now = datetime.now()

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    upcoming_days = {}
    for i in range(1, 8):
        future_date = now + timedelta(days=i)
        upcoming_days[day_names[future_date.weekday()]] = future_date.strftime("%Y-%m-%d")

    return {
        "current_date": now.strftime("%Y-%m-%d"),
        "current_time": now.strftime("%H:%M:%S"),
        "day_of_week": day_names[now.weekday()],
        "timezone": tz_name,
        "upcoming_days": upcoming_days,
    }


def register_calendar_tools(mcp: FastMCP, store: EventKitStore) -> None:
    """캘린더 관련 도구를 모두 MCP 서버에 등록합니다."""

    @mcp.tool()
    def calendar_list_calendars() -> dict:
        """사용 가능한 모든 캘린더를 나열합니다.

        이벤트 생성 시 사용할 수 있는 캘린더 목록을 반환합니다.
        """
        try:
            calendars = store.get_calendars()
            return {"success": True, "calendars": calendars, "count": len(calendars)}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def calendar_list_events(
        start_date: str,
        end_date: str,
        calendar_name: Optional[str] = None,
        limit: int = 50,
    ) -> dict:
        """지정한 날짜 범위 내의 캘린더 이벤트를 나열합니다.

        Args:
            start_date: 시작 날짜, ISO 8601 형식 (YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS)
            end_date: 종료 날짜, ISO 8601 형식
            calendar_name: 특정 캘린더로 필터링 (선택)
            limit: 반환할 최대 이벤트 수 (기본값: 50)
        """
        try:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

            events = store.get_events(
                start=start, end=end, calendar_name=calendar_name, limit=limit
            )

            return {
                "success": True,
                "today": _get_current_datetime_context(),
                "events": events,
                "count": len(events),
            }
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_date", "message": f"Invalid date format: {e}"}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def calendar_get_event(event_id: str) -> dict:
        """특정 캘린더 이벤트의 상세 정보를 가져옵니다.

        Args:
            event_id: 이벤트 식별자 (목록 결과의 id 또는 external_id)
        """
        try:
            event = store.get_event_by_id(event_id)
            if event:
                return {"success": True, "event": event}
            return {"success": False, "error": "not_found", "message": f"Event not found: {event_id}"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def calendar_search_events(
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        tags: Optional[list[str]] = None,
        limit: int = 50,
    ) -> dict:
        """제목, 장소, notes에서 텍스트로 이벤트를 검색합니다.

        Args:
            query: 검색할 텍스트
            start_date: 검색 범위 시작일 (선택, 기본값은 30일 전)
            end_date: 검색 범위 종료일 (선택, 기본값은 90일 후)
            tags: 태그로 필터링 (선택)
            limit: 반환할 최대 이벤트 수 (기본값: 50)
        """
        try:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else None

            events = store.search_events(query=query, start=start, end=end, tags=tags, limit=limit)

            return {"success": True, "events": events, "count": len(events), "query": query}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_date", "message": f"Invalid date format: {e}"}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def calendar_create_event(
        title: str,
        start_date: str,
        end_date: str,
        calendar_name: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        url: Optional[str] = None,
        is_all_day: bool = False,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """새 캘린더 이벤트를 생성합니다.

        Args:
            title: 이벤트 제목
            start_date: 시작 날짜/시간, ISO 8601 형식
            end_date: 종료 날짜/시간, ISO 8601 형식
            calendar_name: 대상 캘린더 (생략 시 기본 캘린더 사용)
            location: 이벤트 장소 (선택)
            notes: 이벤트 메모/설명 (선택)
            url: 연결할 URL (선택)
            is_all_day: 종일 이벤트 여부 (기본값: false)
            tags: 적용할 태그 (선택)
        """
        try:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

            event = store.create_event(
                title=title,
                start=start,
                end=end,
                calendar_name=calendar_name,
                location=location,
                notes=notes,
                url=url,
                is_all_day=is_all_day,
                tags=tags,
            )

            return {"success": True, "event": event, "message": f"Event '{title}' created successfully"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_input", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def calendar_edit_event(
        event_id: str,
        span: str,
        title: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        url: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """기존 캘린더 이벤트를 수정합니다.

        Args:
            event_id: 이벤트 식별자
            span: 반복 이벤트일 경우 'this_event' 또는 'future_events' (필수)
            title: 새 제목 (선택)
            start_date: 새 시작 날짜/시간 (선택)
            end_date: 새 종료 날짜/시간 (선택)
            location: 새 장소 (선택)
            notes: 새 메모 (선택)
            url: 새 URL (선택)
            tags: 새 태그 - 기존 태그를 대체함 (선택)
        """
        if span not in ("this_event", "future_events"):
            return {"success": False, "error": "invalid_span", "message": "span must be 'this_event' or 'future_events'"}

        try:
            start = datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None
            end = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else None

            event = store.edit_event(
                event_id=event_id,
                span=span,
                title=title,
                start=start,
                end=end,
                location=location,
                notes=notes,
                url=url,
                tags=tags,
            )

            return {"success": True, "event": event, "message": "Event updated successfully"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def calendar_delete_event(event_id: str, span: str) -> dict:
        """캘린더 이벤트를 삭제합니다.

        Args:
            event_id: 이벤트 식별자
            span: 반복 이벤트일 경우 'this_event' 또는 'future_events' (필수)
        """
        if span not in ("this_event", "future_events"):
            return {"success": False, "error": "invalid_span", "message": "span must be 'this_event' or 'future_events'"}

        try:
            store.delete_event(event_id=event_id, span=span)
            return {"success": True, "message": "Event deleted successfully"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}
