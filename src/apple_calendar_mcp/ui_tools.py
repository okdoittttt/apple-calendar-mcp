"""MCP Apps(인터랙티브 UI) 도구 - Prefab 기반.

이 모듈은 대화 안에서 렌더링되는 첫 MCP App인 "이벤트 등록 폼"을 제공합니다.
설계 핵심은 FastMCPApp 패턴입니다:

  - `@app.ui()`  : 모델이 호출하는 진입점. Prefab 폼 UI를 반환(visibility=model).
  - `@app.tool()`: 폼 제출 버튼이 CallTool로 호출하는 백엔드 핸들러
                   (visibility=app - 모델의 도구 목록에는 노출되지 않음).

폼은 `Form.from_model(EventForm, ...)`로 Pydantic 모델에서 자동 생성됩니다.
제출 시 필드 값이 `data` 키로 묶여 `create_event_from_form(data=...)`로 전달되고,
핸들러는 기존 `EventKitStore.create_event`에 위임합니다(로직 중복 없음).

무손상 원칙: 기존 28개 도구의 반환 타입(dict)은 전혀 바뀌지 않습니다. UI는
FastMCPApp provider 하나로만 추가됩니다.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from fastmcp import FastMCP, FastMCPApp
from prefab_ui.actions import CallTool, ShowToast
from prefab_ui.components import Column, Form, Heading

from .eventkit_store import EventKitStore


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


def register_ui_tools(mcp: FastMCP, store: EventKitStore) -> None:
    """이벤트 등록 폼 MCP App을 서버에 등록합니다."""
    app = FastMCPApp("EventComposer")

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

    mcp.add_provider(app)
