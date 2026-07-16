"""MCP 서버용 미리 알림 도구."""

from datetime import datetime
from typing import Optional

from fastmcp import FastMCP

from .eventkit_store import EventKitStore
from .permissions import PermissionError

VALID_PRIORITIES = ("none", "low", "medium", "high")


def register_reminder_tools(mcp: FastMCP, store: EventKitStore) -> None:
    """미리 알림 관련 도구를 모두 MCP 서버에 등록합니다."""

    @mcp.tool()
    def reminders_list_lists() -> dict:
        """모든 미리 알림 목록을 나열합니다.

        미리 알림 생성 시 사용할 수 있는 목록들을 반환합니다.
        """
        try:
            lists = store.get_reminder_lists()
            return {"success": True, "lists": lists, "count": len(lists)}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reminders_list(
        list_name: Optional[str] = None,
        include_completed: bool = False,
        due_before: Optional[str] = None,
        limit: int = 100,
    ) -> dict:
        """선택적 필터를 적용해 미리 알림을 나열합니다.

        Args:
            list_name: 특정 목록으로 필터링 (선택)
            include_completed: 완료된 미리 알림 포함 여부 (기본값: false)
            due_before: 마감일로 필터링 - ISO 8601 형식 (선택)
            limit: 반환할 최대 미리 알림 수 (기본값: 100)
        """
        try:
            due_date = datetime.fromisoformat(due_before.replace("Z", "+00:00")) if due_before else None

            reminders = store.get_reminders(
                list_name=list_name,
                include_completed=include_completed,
                due_before=due_date,
                limit=limit,
            )

            return {"success": True, "reminders": reminders, "count": len(reminders)}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_date", "message": f"Invalid date format: {e}"}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reminders_get(reminder_id: str) -> dict:
        """특정 미리 알림의 상세 정보를 가져옵니다.

        Args:
            reminder_id: 미리 알림 식별자 (목록 결과의 id 또는 external_id)
        """
        try:
            reminder = store.get_reminder_by_id(reminder_id)
            if reminder:
                return {"success": True, "reminder": reminder}
            return {"success": False, "error": "not_found", "message": f"Reminder not found: {reminder_id}"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reminders_search(
        query: str,
        tags: Optional[list[str]] = None,
        include_completed: bool = False,
        limit: int = 50,
    ) -> dict:
        """제목이나 notes에서 텍스트로 미리 알림을 검색합니다.

        Args:
            query: 검색할 텍스트
            tags: 태그로 필터링 (선택)
            include_completed: 완료된 미리 알림 포함 여부 (기본값: false)
            limit: 반환할 최대 미리 알림 수 (기본값: 50)
        """
        try:
            reminders = store.search_reminders(
                query=query, tags=tags, include_completed=include_completed, limit=limit
            )
            return {"success": True, "reminders": reminders, "count": len(reminders), "query": query}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reminders_create(
        title: str,
        list_name: Optional[str] = None,
        notes: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """새 미리 알림을 생성합니다.

        Args:
            title: 미리 알림 제목
            list_name: 대상 목록 (생략 시 기본 목록 사용)
            notes: 추가 메모 (선택)
            due_date: 마감일, ISO 8601 형식 (선택)
            priority: 'none', 'low', 'medium', 'high' 중 하나 (선택)
            tags: 적용할 태그 (선택)
        """
        try:
            due = datetime.fromisoformat(due_date.replace("Z", "+00:00")) if due_date else None

            if priority and priority not in VALID_PRIORITIES:
                return {"success": False, "error": "invalid_priority", "message": "priority must be 'none', 'low', 'medium', or 'high'"}

            reminder = store.create_reminder(
                title=title, list_name=list_name, notes=notes, due_date=due, priority=priority, tags=tags
            )

            return {"success": True, "reminder": reminder, "message": f"Reminder '{title}' created successfully"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_input", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reminders_edit(
        reminder_id: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[str] = None,
        completed: Optional[bool] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """기존 미리 알림을 수정합니다.

        Args:
            reminder_id: 미리 알림 식별자
            title: 새 제목 (선택)
            notes: 새 메모 (선택)
            due_date: 새 마감일, ISO 8601 형식 (선택)
            priority: 새 우선순위 - 'none', 'low', 'medium', 'high' 중 하나 (선택)
            completed: 완료/미완료 표시 (선택)
            tags: 새 태그 - 기존 태그를 대체함 (선택)
        """
        try:
            due = datetime.fromisoformat(due_date.replace("Z", "+00:00")) if due_date else None

            if priority and priority not in VALID_PRIORITIES:
                return {"success": False, "error": "invalid_priority", "message": "priority must be 'none', 'low', 'medium', or 'high'"}

            reminder = store.edit_reminder(
                reminder_id=reminder_id,
                title=title,
                notes=notes,
                due_date=due,
                priority=priority,
                completed=completed,
                tags=tags,
            )

            return {"success": True, "reminder": reminder, "message": "Reminder updated successfully"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reminders_complete(reminder_id: str) -> dict:
        """미리 알림을 완료로 표시합니다.

        Args:
            reminder_id: 미리 알림 식별자
        """
        try:
            reminder = store.complete_reminder(reminder_id)
            return {"success": True, "reminder": reminder, "message": "Reminder marked as completed"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reminders_delete(reminder_id: str) -> dict:
        """미리 알림을 삭제합니다.

        Args:
            reminder_id: 미리 알림 식별자
        """
        try:
            store.delete_reminder(reminder_id)
            return {"success": True, "message": "Reminder deleted successfully"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}
