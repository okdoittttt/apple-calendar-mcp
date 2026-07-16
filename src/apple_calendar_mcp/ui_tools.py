"""MCP Apps(인터랙티브 UI) 도구 - Prefab 기반.

대화 안에서 렌더링되는 MCP App들을 제공합니다. 모두 하나의 FastMCPApp
provider(`AppleCalendarUI`) 아래 묶여 있습니다.

  - `@app.ui()`  : 모델이 호출하는 진입점. Prefab UI를 반환(visibility=model).
  - `@app.tool()`: UI가 CallTool로 호출하는 백엔드 핸들러(visibility=app,
                   모델의 도구 목록에는 노출되지 않음).

제공 UI:
  1. event_composer : 새 일정 등록 폼. 제출 시 create_event_from_form 호출.
  2. agenda_board   : 지정 기간(기본=오늘)의 이벤트 + 마감 미리 알림 관리 보드.
                      메트릭 카드 + 읽기 전용 DataTable 로 요약하고, 표 아래에
                      행별 액션 버튼을 '일반 흐름'(Row+Button)으로 제공합니다.
                        - 미리 알림: [완료] → complete_reminder_from_board
                        - 이벤트:    [삭제] → delete_event_from_board
                      (표 셀에 컴포넌트를 넣으면 일부 호스트 렌더러에서 빈 화면이
                       나므로, 버튼은 표 밖 일반 흐름에 둔다.)

무손상 원칙: 기존 도구의 반환 타입(dict)은 전혀 바뀌지 않습니다. UI는
FastMCPApp provider 하나로만 추가됩니다.
"""

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, Field

from fastmcp import FastMCP, FastMCPApp
from prefab_ui.actions import CallTool, ShowToast
from prefab_ui.components import (
    Alert,
    AlertDescription,
    AlertTitle,
    Button,
    Column,
    DataTable,
    DataTableColumn,
    Form,
    Heading,
    Metric,
    Row,
    Text,
)

from .eventkit_store import EventKitStore

# ─────────────────────────── 등록 폼 ───────────────────────────


class EventForm(BaseModel):
    """이벤트 등록 폼의 필드 정의.

    각 필드는 `calendar_create_event`(그리고 그 하위 `store.create_event`)의
    인자에 1:1로 매핑됩니다. Pydantic Field 메타데이터(title/description 등)는
    Prefab이 라벨·플레이스홀더·입력 타입을 결정하는 데 사용합니다.
    """

    title: str = Field(title="제목", min_length=1, description="이벤트 제목")
    start: datetime = Field(title="시작", description="시작 날짜/시간")
    end: datetime = Field(title="종료", description="종료 날짜/시간")
    calendar_name: Optional[str] = Field(
        default=None, title="캘린더", description="대상 캘린더 (비우면 기본 캘린더)"
    )
    location: Optional[str] = Field(default=None, title="장소")
    notes: Optional[str] = Field(
        default=None,
        title="메모",
        json_schema_extra={"ui": {"type": "textarea"}},
    )
    is_all_day: bool = Field(default=False, title="종일 이벤트")
    tags: Optional[str] = Field(
        default=None, title="태그", description="쉼표로 구분 (예: work, urgent)"
    )


def _parse_tags(raw: Optional[str]) -> Optional[list[str]]:
    """쉼표로 구분된 태그 문자열을 리스트로 변환합니다. 비어 있으면 None."""
    if not raw:
        return None
    tags = [t.strip() for t in raw.split(",") if t.strip()]
    return tags or None


# ─────────────────────────── 조회 보드 helpers ───────────────────────────

_PRIORITY_LABEL = {"high": "높음", "medium": "보통", "low": "낮음", "none": "-"}


def _parse_day(value: Optional[str], fallback: date) -> date:
    """YYYY-MM-DD(또는 전체 ISO)을 date로. 실패하면 fallback."""
    if not value:
        return fallback
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return fallback


def _fmt_dt(iso: Optional[str]) -> Optional[datetime]:
    """ISO 문자열을 datetime으로 (타임존/‘Z’ 관대 처리). 실패하면 None."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _range_label(start_day: date, end_day: date) -> str:
    if start_day == end_day:
        if start_day == date.today():
            return f"오늘 · {start_day:%Y-%m-%d}"
        return f"{start_day:%Y-%m-%d}"
    return f"{start_day:%Y-%m-%d} ~ {end_day:%Y-%m-%d}"


def _event_to_row(ev: dict) -> dict:
    """이벤트 dict → DataTable 행(dict). 키는 컬럼 key와 일치해야 함."""
    if ev.get("is_all_day"):
        when = "종일"
        start = _fmt_dt(ev.get("start_date"))
        if start:
            when = f"{start:%m/%d} 종일"
    else:
        start = _fmt_dt(ev.get("start_date"))
        end = _fmt_dt(ev.get("end_date"))
        if start and end:
            when = f"{start:%m/%d %H:%M}–{end:%H:%M}"
        elif start:
            when = f"{start:%m/%d %H:%M}"
        else:
            when = ev.get("start_date") or ""
    tags = ev.get("tags") or []
    return {
        "time": when,
        "title": ev.get("title") or "(제목 없음)",
        "location": ev.get("location") or "",
        "calendar": ev.get("calendar") or "",
        "tags": " ".join(f"#{t}" for t in tags),
    }


def _reminder_to_row(r: dict) -> dict:
    """미리 알림 dict → DataTable 행(dict)."""
    due = _fmt_dt(r.get("due_date"))
    if due:
        # 자정(00:00)이면 날짜만, 아니면 시각까지
        due_str = f"{due:%m/%d}" if (due.hour, due.minute) == (0, 0) else f"{due:%m/%d %H:%M}"
    else:
        due_str = ""
    tags = r.get("tags") or []
    return {
        "title": r.get("title") or "(제목 없음)",
        "due": due_str,
        "priority": _PRIORITY_LABEL.get(r.get("priority", "none"), "-"),
        "tags": " ".join(f"#{t}" for t in tags),
    }


_EVENT_COLUMNS = [
    DataTableColumn(key="time", header="시간", sortable=True),
    DataTableColumn(key="title", header="제목", sortable=True),
    DataTableColumn(key="location", header="장소"),
    DataTableColumn(key="calendar", header="캘린더", sortable=True),
    DataTableColumn(key="tags", header="태그"),
]

_REMINDER_COLUMNS = [
    DataTableColumn(key="title", header="제목", sortable=True),
    DataTableColumn(key="due", header="마감", sortable=True),
    DataTableColumn(key="priority", header="우선순위", sortable=True),
    DataTableColumn(key="tags", header="태그"),
]


def register_ui_tools(mcp: FastMCP, store: EventKitStore) -> None:
    """캘린더 MCP App(등록 폼 + 조회 보드)을 서버에 등록합니다."""
    app = FastMCPApp("AppleCalendarUI")

    # ── 등록 폼 백엔드 핸들러 (visibility=app) ──
    @app.tool()
    def create_event_from_form(data: EventForm) -> dict:
        """등록 폼 제출을 처리해 새 캘린더 이벤트를 생성합니다(내부용).

        폼 UI(event_composer)의 제출 버튼이 CallTool로 호출합니다. 실제
        생성은 기존 EventKitStore.create_event에 위임합니다.
        """
        try:
            event = store.create_event(
                title=data.title,
                start=data.start,
                end=data.end,
                calendar_name=data.calendar_name or None,
                location=data.location or None,
                notes=data.notes or None,
                url=None,
                is_all_day=data.is_all_day,
                tags=_parse_tags(data.tags),
            )
            return {
                "success": True,
                "event": event,
                "message": f"일정 '{data.title}' 이(가) 등록되었습니다",
            }
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_input", "message": str(e)}
        except Exception as e:  # noqa: BLE001 - 폼에 오류 메시지로 표시
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    # ── 보드 액션 백엔드 핸들러 (visibility=app) ──
    @app.tool()
    def complete_reminder_from_board(reminder_id: str) -> dict:
        """보드의 [완료] 버튼이 호출하는 미리 알림 완료 처리(내부용).

        agenda_board 의 미리 알림 행 버튼이 CallTool 로 호출합니다. 실제
        완료 처리는 기존 EventKitStore.complete_reminder 에 위임합니다.
        """
        try:
            reminder = store.complete_reminder(reminder_id)
            return {
                "success": True,
                "reminder": reminder,
                "message": "미리 알림을 완료 처리했습니다",
            }
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:  # noqa: BLE001 - 토스트로 오류 표시
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @app.tool()
    def delete_event_from_board(event_id: str) -> dict:
        """보드의 [삭제] 버튼이 호출하는 이벤트 삭제(내부용).

        agenda_board 의 이벤트 행 삭제 다이얼로그가 CallTool 로 호출합니다.
        반복 이벤트는 해당 회차만(this_event) 삭제합니다.
        """
        try:
            store.delete_event(event_id, span="this_event")
            return {"success": True, "message": "일정을 삭제했습니다"}
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:  # noqa: BLE001 - 토스트로 오류 표시
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    # 액션 버튼은 표 셀이 아니라 표 아래 '일반 흐름'(Row+Button)으로 렌더한다.
    # 표 셀 값에 컴포넌트를 넣는 방식은 일부 호스트(구버전 Claude Desktop 렌더러)
    # 에서 렌더 실패(빈 화면)를 일으켜서, 등록 폼과 동일하게 검증된 흐름만 쓴다.

    # ── 등록 폼 UI (visibility=model) ──
    @app.ui()
    def event_composer() -> Column:
        """새 일정을 등록하는 폼 UI를 엽니다.

        제목·시작·종료·캘린더·장소·메모·종일·태그를 입력하는 폼을 대화 안에
        렌더링합니다. 제출하면 캘린더에 이벤트가 생성됩니다.
        """
        with Column(gap=4) as view:
            Heading("새 일정 등록", level=2)
            Form.from_model(
                EventForm,
                submit_label="일정 등록",
                on_submit=CallTool(
                    create_event_from_form,
                    on_success=ShowToast(
                        "일정이 등록되었습니다 ✅", variant="success"
                    ),
                ),
            )
        return view

    # ── 조회 보드 UI (visibility=model, 읽기 전용) ──
    @app.ui()
    def agenda_board(
        start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Column:
        """지정 기간(기본=오늘)의 이벤트와 마감 미리 알림을 한눈에 보는 보드.

        메트릭 카드와 검색·정렬이 가능한 표로 요약합니다. 읽기 전용이며,
        캘린더/미리 알림 접근 권한이 필요합니다.

        Args:
            start_date: 조회 시작일 YYYY-MM-DD (생략 시 오늘)
            end_date: 조회 종료일 YYYY-MM-DD (생략 시 start_date와 동일)
        """
        today = date.today()
        start_day = _parse_day(start_date, today)
        end_day = _parse_day(end_date, start_day)
        if end_day < start_day:
            start_day, end_day = end_day, start_day

        range_start = datetime.combine(start_day, time(0, 0))
        range_end = datetime.combine(end_day, time(23, 59, 59))

        error: Optional[str] = None
        events: list[dict] = []
        reminders: list[dict] = []
        try:
            events = store.get_events(start=range_start, end=range_end, limit=200)
            reminders = store.get_reminders(
                due_after=range_start,
                due_before=range_end,
                include_completed=False,
                limit=200,
            )
        except PermissionError as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001 - 보드에 안내로 표시
            error = str(e)

        # 읽기 전용 표 행(문자열 셀만). 액션은 표 아래 별도 버튼으로 뺀다.
        event_rows = [_event_to_row(ev) for ev in events]
        reminder_rows = [_reminder_to_row(r) for r in reminders]

        with Column(gap=6) as view:
            Heading(_range_label(start_day, end_day), level=2)

            if error is not None:
                with Alert(variant="warning"):
                    AlertTitle("데이터를 불러오지 못했습니다")
                    AlertDescription(
                        "캘린더/미리 알림 접근 권한이 필요할 수 있습니다. "
                        f"({error})"
                    )

            with Row(gap=4):
                Metric(label="이벤트", value=len(events))
                Metric(label="마감 미리 알림", value=len(reminders))

            # ── 이벤트: 읽기 전용 표 + 행별 [삭제] 버튼(표 아래 일반 흐름) ──
            Heading("이벤트", level=3)
            if event_rows:
                DataTable(
                    columns=_EVENT_COLUMNS,
                    rows=event_rows,
                    search=len(event_rows) > 5,
                    paginated=len(event_rows) > 15,
                    page_size=15,
                )
                with Column(gap=2):
                    for ev, row in zip(events, event_rows):
                        eid = ev.get("id")
                        if not eid:
                            continue
                        with Row(gap=3):
                            Text(f"{row['time']} · {row['title']}")
                            Button(
                                "삭제",
                                variant="destructive",
                                size="sm",
                                on_click=CallTool(
                                    delete_event_from_board,
                                    arguments={"event_id": eid},
                                    on_success=ShowToast(
                                        "일정을 삭제했습니다 🗑️", variant="success"
                                    ),
                                ),
                            )
            else:
                Text("이 기간에 이벤트가 없습니다.")

            # ── 미리 알림: 읽기 전용 표 + 행별 [완료] 버튼 ──
            Heading("마감 미리 알림", level=3)
            if reminder_rows:
                DataTable(
                    columns=_REMINDER_COLUMNS,
                    rows=reminder_rows,
                    search=len(reminder_rows) > 5,
                )
                with Column(gap=2):
                    for r, row in zip(reminders, reminder_rows):
                        rid = r.get("id")
                        if not rid:
                            continue
                        with Row(gap=3):
                            Text(row["title"])
                            Button(
                                "완료",
                                variant="success",
                                size="sm",
                                on_click=CallTool(
                                    complete_reminder_from_board,
                                    arguments={"reminder_id": rid},
                                    on_success=ShowToast(
                                        "완료 처리했습니다 ✅", variant="success"
                                    ),
                                ),
                            )
            else:
                Text("이 기간에 마감 예정인 미리 알림이 없습니다.")

        return view

    mcp.add_provider(app)
