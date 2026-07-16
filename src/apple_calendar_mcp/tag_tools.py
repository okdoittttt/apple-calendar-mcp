"""태그 관리 도구: 이벤트/미리 알림에 걸친 해시태그 목록 조회/이름 변경/병합/삭제.

일괄 태그 편집은 기본 calendar_edit_event/reminders_edit 도구와 동일한
store.edit_event/edit_reminder 로직을 재사용하므로, 같은 EventKit 동작 방식을
그대로 물려받습니다: 반복 이벤트의 경우 calendarItemWithIdentifier_가 하나의
대표 occurrence로 resolve되고, 편집은 EKSpanThisEvent로 적용됩니다. 따라서
일괄 작업은 반복 시리즈마다 화면에 보이는 모든 occurrence가 아니라 대표
occurrence 하나에만 적용됩니다 - 자세한 내용은 README 참고.
"""

from typing import Callable, Optional

from fastmcp import FastMCP

from .eventkit_store import EventKitStore
from .permissions import PermissionError
from .tags import normalize_tag

VALID_SCOPES = ("events", "reminders", "all")

TRUNCATION_WARNING = (
    "Scan hit an internal safety limit; some items may not have been checked. "
    "See README for the scan window used by tag tools."
)


def _rewrite_tags(
    store: EventKitStore,
    scope: str,
    mutate_tags_fn: Callable[[list[str]], Optional[list[str]]],
) -> tuple[int, bool]:
    """scope 내 모든 이벤트/미리 알림의 태그 목록에 mutate_tags_fn을 적용합니다.

    mutate_tags_fn(current_tags)은 변경이 필요 없으면 None을, 다시 써야 하면
    새 태그 목록(빈 목록일 수도 있음)을 반환해야 합니다.

    Returns:
        (updated_count, truncated) - truncated는 내부 스캔이 안전 한도에
        도달해 일부 항목을 놓쳤을 수 있음을 의미합니다.
    """
    updated = 0
    truncated = False

    if scope in ("events", "all"):
        events, ev_truncated = store.get_events_wide()
        truncated = truncated or ev_truncated
        for ev in events:
            new_tags = mutate_tags_fn(ev.get("tags") or [])
            if new_tags is not None:
                store.edit_event(event_id=ev["id"], span="this_event", tags=new_tags)
                updated += 1

    if scope in ("reminders", "all"):
        reminders, rem_truncated = store.get_all_reminders_wide()
        truncated = truncated or rem_truncated
        for rem in reminders:
            new_tags = mutate_tags_fn(rem.get("tags") or [])
            if new_tags is not None:
                store.edit_reminder(reminder_id=rem["id"], tags=new_tags)
                updated += 1

    return updated, truncated


def register_tag_tools(mcp: FastMCP, store: EventKitStore) -> None:
    """태그 관리 도구를 모두 MCP 서버에 등록합니다."""

    @mcp.tool()
    def tags_list() -> dict:
        """현재 사용 중인 모든 해시태그와 각 태그를 사용하는 항목 수를 나열합니다.

        이벤트는 넓은 (구간으로 나눈) 날짜 범위를, 미리 알림은 완료된 것을
        포함한 모든 목록을 스캔합니다.
        """
        try:
            counts: dict[str, int] = {}

            events, ev_truncated = store.get_events_wide()
            for ev in events:
                for t in ev.get("tags") or []:
                    counts[t] = counts.get(t, 0) + 1

            reminders, rem_truncated = store.get_all_reminders_wide()
            for rem in reminders:
                for t in rem.get("tags") or []:
                    counts[t] = counts.get(t, 0) + 1

            tags_sorted = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

            result = {
                "success": True,
                "tags": [{"tag": t, "count": c} for t, c in tags_sorted],
                "count": len(tags_sorted),
            }
            if ev_truncated or rem_truncated:
                result["warning"] = TRUNCATION_WARNING
            return result
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def tags_rename(old_tag: str, new_tag: str, scope: str = "all") -> dict:
        """이벤트와/또는 미리 알림에서 태그 이름을 변경합니다.

        일치하는 항목의 notes 중 태그 영역에서만 #old_tag를 #new_tag로
        바꿉니다 - notes 본문의 나머지 부분은 그대로 둡니다. 항목이 이미
        두 태그를 모두 가지고 있으면 하나로 합쳐집니다 (중복 없음).
        정확한 태그 이름이 필요하며, 부분 일치로 추측하지 않습니다.

        Args:
            old_tag: 이름을 바꿀 정확한 태그, '#' 제외 (필수)
            new_tag: 새 태그 이름, '#' 제외 (필수)
            scope: 'events', 'reminders', 'all' 중 하나 (기본값: 'all')
        """
        if scope not in VALID_SCOPES:
            return {"success": False, "error": "invalid_scope", "message": "scope must be 'events', 'reminders', or 'all'"}

        old_norm = normalize_tag(old_tag)
        new_norm = normalize_tag(new_tag)
        if not old_norm or not new_norm:
            return {"success": False, "error": "invalid_tag", "message": "old_tag and new_tag must not be empty after normalization"}

        def mutate(tags: list[str]) -> Optional[list[str]]:
            if old_norm not in tags:
                return None
            return sorted(set(new_norm if t == old_norm else t for t in tags))

        try:
            updated, truncated = _rewrite_tags(store, scope, mutate)
            result = {
                "success": True,
                "updated_count": updated,
                "message": f"Renamed #{old_norm} to #{new_norm} on {updated} item(s)",
            }
            if truncated:
                result["warning"] = TRUNCATION_WARNING
            return result
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def tags_merge(from_tag: str, into_tag: str, scope: str = "all") -> dict:
        """이벤트와/또는 미리 알림에서 한 태그를 다른 태그로 병합합니다.

        #from_tag가 붙어 있던 모든 항목이 #into_tag로 바뀝니다
        (#from_tag는 제거되고, 없었다면 #into_tag가 추가됩니다).
        동작 방식은 tags_rename과 동일하며, "두 태그를 하나로 합친다"는
        용도를 위해 별도로 제공합니다. 정확한 태그 이름이 필요합니다.

        Args:
            from_tag: 제거할 태그, '#' 제외 (필수)
            into_tag: 병합해 넣을 태그, '#' 제외 (필수)
            scope: 'events', 'reminders', 'all' 중 하나 (기본값: 'all')
        """
        if scope not in VALID_SCOPES:
            return {"success": False, "error": "invalid_scope", "message": "scope must be 'events', 'reminders', or 'all'"}

        from_norm = normalize_tag(from_tag)
        into_norm = normalize_tag(into_tag)
        if not from_norm or not into_norm:
            return {"success": False, "error": "invalid_tag", "message": "from_tag and into_tag must not be empty after normalization"}

        def mutate(tags: list[str]) -> Optional[list[str]]:
            if from_norm not in tags:
                return None
            return sorted(set(into_norm if t == from_norm else t for t in tags))

        try:
            updated, truncated = _rewrite_tags(store, scope, mutate)
            result = {
                "success": True,
                "updated_count": updated,
                "message": f"Merged #{from_norm} into #{into_norm} on {updated} item(s)",
            }
            if truncated:
                result["warning"] = TRUNCATION_WARNING
            return result
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def tags_delete(tag: str, scope: str = "all") -> dict:
        """해당 태그를 가진 모든 이벤트와/또는 미리 알림에서 태그를 삭제합니다.

        이 작업은 되돌릴 수 없습니다: 정확히 일치하는 태그 이름만 제거하며
        (부분/유사 일치 없음), 각 항목의 notes 나머지 부분은 그대로 둡니다.

        Args:
            tag: 삭제할 정확한 태그 이름, '#' 제외 (필수)
            scope: 'events', 'reminders', 'all' 중 하나 (기본값: 'all')
        """
        if scope not in VALID_SCOPES:
            return {"success": False, "error": "invalid_scope", "message": "scope must be 'events', 'reminders', or 'all'"}

        tag_norm = normalize_tag(tag)
        if not tag_norm:
            return {"success": False, "error": "invalid_tag", "message": "tag must not be empty after normalization"}

        def mutate(tags: list[str]) -> Optional[list[str]]:
            if tag_norm not in tags:
                return None
            return [t for t in tags if t != tag_norm]

        try:
            updated, truncated = _rewrite_tags(store, scope, mutate)
            result = {
                "success": True,
                "updated_count": updated,
                "message": f"Removed #{tag_norm} from {updated} item(s)",
            }
            if truncated:
                result["warning"] = TRUNCATION_WARNING
            return result
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}
