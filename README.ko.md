# apple-calendar MCP 서버

macOS 캘린더 및 미리 알림을 위한 개인용 MCP 서버로,
[EventKit](https://developer.apple.com/documentation/eventkit)을 PyObjC를 통해
사용합니다. 로컬에서 stdio로 실행되며 - 네트워크 호출이나 클라우드 서비스가
없습니다. Claude Desktop과 함께 사용하도록 만들어졌지만(커넥터 이름:
`apple-calendar`), 모든 MCP stdio 클라이언트와 함께 작동합니다.

도구는 캘린더/미리 알림의 전체 CRUD 범위, 해시태그 기반 태그 시스템
(`tags_*`), 일정 관리 편의 도구(`agenda_*`, `quick_event`,
`reschedule_event`, `find_free_slots`), 그리고 핫 리스타트 관리 도구
(`server_status`, `server_restart`)를 다룹니다.

## 요구 사항

- macOS 14+ (최신 `requestFullAccessTo...` 권한 API를 사용하며, 이전 macOS에서는
  레거시 API로 폴백)
- Python 3.10+, [uv](https://docs.astral.sh/uv/)로 관리

## 설치

```bash
cd apple-calendar-mcp
uv sync
```

## 권한 부여

EventKit은 캘린더/미리 알림 권한을 최초로 요청한 프로세스("responsible
process")에 연결합니다. 접근 권한을 부여하는 두 가지 방법:

**옵션 A - 권장, 터미널에서 한 번 실행:**

```bash
uv run python scripts/setup_permissions.py
```

이렇게 하면 터미널의 식별자로 캘린더와 미리 알림에 대한 시스템 권한 대화상자가
표시되어야 합니다. 두 곳 모두 "허용"을 클릭하세요.

**옵션 B - 수동:**

**시스템 설정 > 개인 정보 보호 및 보안 > 캘린더** (및 **미리 알림**)를 열고
서버가 최소 한 번 실행된 후 목록에 표시되는 터미널, Python 인터프리터, 또는
Claude Desktop 중 해당하는 항목에 대해 접근 권한을 활성화하세요.

도구 호출이 `"error": "permission_denied"`를 반환하면, 현재 상태와 지침을
확인하기 위해 `eventkit_check_permissions`를 확인하거나 설정 스크립트를
다시 실행하세요.

> 참고: 이 서버가 Claude Desktop의 하위 프로세스로 실행될 때, macOS는
> 권한 프롬프트를 표시하지 않고 Claude Desktop에 귀속시킬 수 있습니다
> (백그라운드 하위 프로세스는 종종 UI를 표시할 수 없습니다). Claude Desktop에
> 서버를 추가한 후 대화상자가 나타나지 않으면, 먼저 터미널에서 설정 스크립트를
> 실행한 다음 Claude Desktop을 재시작하세요.

## Claude Desktop 구성

`~/Library/Application Support/Claude/claude_desktop_config.json`에 추가하세요
(이 저장소의 설정은 이 머신에서 이미 이 작업을 수행했습니다 - 아래 참조).
`mcpServers` 키가 Claude Desktop에 표시되는 커넥터 이름이 됩니다:

```json
{
  "mcpServers": {
    "apple-calendar": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/apple-calendar-mcp",
        "run", "python", "-m", "apple_calendar_mcp.server"
      ]
    }
  }
}
```

편집 후 Claude Desktop을 재시작하세요 (또는 아래 설명된 `server_restart`를
사용하세요).

## 도구

### 권한

| 도구 | 설명 |
|---|---|
| `eventkit_check_permissions` | 캘린더/미리 알림 권한 상태 + 지침 |

### 캘린더

| 도구 | 설명 |
|---|---|
| `calendar_list_calendars` | 모든 캘린더 목록 |
| `calendar_list_events` | 날짜 범위 내 이벤트 목록 |
| `calendar_get_event` | id로 이벤트 하나 가져오기 |
| `calendar_search_events` | 제목/위치/메모에 대한 텍스트 검색, 선택적 태그 필터 |
| `calendar_create_event` | 이벤트 생성 (위치, 메모, url, 태그) |
| `calendar_edit_event` | 이벤트 편집(`calendar_name`으로 카테고리 이동 포함); 반복 이벤트는 `span` 필수 |
| `calendar_delete_event` | 이벤트 삭제; 반복 이벤트는 `span` 필수 |

### 미리 알림

| 도구 | 설명 |
|---|---|
| `reminders_list_lists` | 모든 미리 알림 목록 나열 |
| `reminders_list` | 미리 알림 목록, 리스트/완료 여부/마감일로 필터링 |
| `reminders_get` | id로 미리 알림 하나 가져오기 |
| `reminders_search` | 제목/메모에 대한 텍스트 검색, 선택적 태그 필터 |
| `reminders_create` | 미리 알림 생성 (마감일, 우선순위, 태그) |
| `reminders_edit` | 미리 알림 편집 |
| `reminders_complete` | 미리 알림을 완료로 표시 |
| `reminders_delete` | 미리 알림 삭제 |

### 태그

태그는 메모 필드에 추가된 `#해시태그`로 저장됩니다 (EventKit에는 네이티브
태그 개념이 없습니다). 정규화: 소문자, 공백/하이픈 -> 밑줄, 영숫자가 아닌
문자 제거. `notes`에 저장되기 때문에 태그는 iCloud를 통해 동기화되며
기본 캘린더/미리 알림 앱에서 표시/검색 가능합니다.

| 도구 | 설명 |
|---|---|
| `tags_list` | 사용 중인 모든 태그, 항목 수와 함께 |
| `tags_rename(old_tag, new_tag, scope)` | 태그 이름 변경; `scope`: `events`\|`reminders`\|`all` |
| `tags_merge(from_tag, into_tag, scope)` | 한 태그를 다른 태그로 병합 |
| `tags_delete(tag, scope)` | 나타나는 모든 곳에서 태그 제거 |

이들은 대량의, 되돌릴 수 없는 편집이기 때문에 세 가지 모두 **정확한** 태그
이름을 사용합니다 (퍼지/부분 일치 없음). 이들은 `notes`의 해시태그 줄만
다시 작성하며 - 나머지 메모 본문은 정확히 보존됩니다.

**스캔 범위 주의 사항:** `tags_list`/`tags_rename`/`tags_merge`/`tags_delete`는
"모든" 이벤트를 봐야 하지만, EventKit의 날짜 범위 프레디케이트는 호출당
실질적으로 ~4년의 제한이 있습니다. 이 도구들은 스캔을 6년 전부터 6년 후까지
(총 12년, 최대 5000개 이벤트) 다루는 3년 단위 창으로 나눕니다 - 그보다 먼
이벤트는 보이지 않습니다. 미리 알림은 그러한 제한이 없으며 한 번의 호출로
가져옵니다 (최대 20000개). 스캔이 한도에 도달하면 응답에 `"warning"` 필드가
포함됩니다.

**반복 이벤트 주의 사항:** 대량 태그 편집은 `calendar_edit_event`와 동일한
`calendarItemWithIdentifier_` + `EKSpanThisEvent` 메커니즘을 재사용합니다.
반복 시리즈의 경우, 이는 보이는 모든 항목이 아닌 하나의 대표 항목으로
해석됩니다 - 기본 편집 도구가 가진 것과 동일한 제한입니다.

### 커스텀 일정 도구

| 도구 | 설명 |
|---|---|
| `agenda_today` | 오늘의 사람이 읽기 쉬운 일정 (이벤트 + 마감 미리 알림) |
| `agenda_range(start_date, end_date)` | 동일하지만 날짜 범위에 대해 |
| `quick_event(text)` | 짧은 자연어 문장으로 이벤트 생성 |
| `reschedule_event(event_id, new_start)` | 지속 시간을 유지하며 이벤트 이동 |
| `find_free_slots(date, working_hours, min_duration_minutes)` | 근무 시간 내 빈 시간대 (종일 이벤트는 무시) |

`quick_event`는 작은 휴리스틱 파서를 사용합니다 (외부 NLP 의존성 없이, 의도적으로
- 이 프로젝트는 `mcp[cli]`와 pyobjc에만 의존합니다). 다음을 인식합니다:

- 상대적인 날짜: `today`, `tomorrow`, `mon`..`sun` / 전체 요일 이름
- 명시적 날짜: `YYYY-MM-DD`
- 시간: `3pm`, `3:30pm`, `15:00` (앞에 `at`이 붙을 수 있음)
- 지속 시간: `for 30 minutes`, `for 2 hours`
- 끝에 오는 `#해시태그` -> 태그

기본값: 1시간 지속 시간; 시간이 발견되지 않으면 09:00 (또는 남은 제목에
아침/점심/저녁이 언급된 경우 08:00/12:00/19:00). 이 패턴들과 일치하지 않는
것은 제목에 남습니다. 최선을 다하는(best-effort) 방식이므로 - 시간에 민감한
용도로 사용하기 전에 반환된 `event`를 검토하세요.

### 서버 관리

| 도구 | 설명 |
|---|---|
| `server_status` | pid, 버전, 가동 시간, 도구 개수 |
| `server_restart` | Claude Desktop을 종료하지 않고 프로세스를 핫 리스타트 |
| `server_stop` | 프로세스 중지 (재실행 없음) - 캘린더/미리 알림 접근을 일시 중단할 때 사용 |

#### `server_restart`의 작동 방식과 검증한 내용

`server_restart`는 잠시 대기(기본 0.75초, `delay_seconds`로 설정 가능)하는
백그라운드 스레드를 생성하고, stdout/stderr를 플러시한 다음 `os.execv`를
호출하여 현재 프로세스 이미지를 새로운 `python -m apple_calendar_mcp.server`로
교체합니다 - 디스크의 코드 변경 사항을 반영합니다.

우리는 이것을 (이 환경에서 구동할 수 없는 Claude Desktop의 UI를 통해서가
아니라) 원시 MCP Python 클라이언트에 직접 테스트했고 다음을 관찰했습니다:

- stdio 파이프의 파일 디스크립터는 `execv`에서 **살아남습니다** - 클라이언트와
  새 프로세스 사이에 바이트가 계속 흐릅니다.
- 새 프로세스의 pid는 다르며 `uptime_seconds`는 ~0으로 재설정되어, 재시작이
  발생했음을 확인합니다 (이것이 `server_status`가 존재하는 이유입니다).
- **MCP/JSON-RPC 세션은 살아남지 못합니다** - 이는 프로세스 이미지가 교체될
  때 재설정되는 메모리 내 상태입니다. 재시작 직후 이전 세션으로 전송된
  도구 호출은 즉시 거부됩니다 (`Invalid request parameters` /
  "request before initialization was complete").
- 재시작 후 **동일한 stdio 파이프**에서 MCP `initialize` 핸드셰이크를
  다시 보내면 세션이 완전히 복구됩니다 - 새 pid, 재설정된 가동 시간, 모든
  도구가 다시 호출 가능합니다. 새 하위 프로세스도, Claude Desktop 재시작도
  필요 없습니다.

직접 검증할 수 **없었던** 것: Claude Desktop 자체 클라이언트가 방금 호출한
도구로부터 요청 거부 오류를 받은 후 자동으로 `initialize`를 다시 보내는지
여부입니다 (즉, 자체 복구하는지, 아니면 다시 상호작용할 때까지 커넥터가
"멈춘" 것처럼 보이는지). `server_restart`를 호출한 직후 도구가 응답을
멈추면:

1. 도구를 한두 번 다시 호출해 보세요 - 일부 MCP 클라이언트는 오류 시
   투명하게 재시도/재초기화합니다.
2. 그래도 도움이 되지 않으면, Claude Desktop 설정에서 `apple-calendar`
   커넥터를 껐다가 다시 켜세요. 이는 앱을 종료할 필요가 **없으며**, 새
   하위 프로세스에서 새로운 `initialize`를 강제합니다.
3. Claude Desktop을 종료했다가 다시 여는 것은 최후의 수단으로 항상
   작동하지만, 이 도구의 목적을 무색하게 합니다.

Claude Desktop이 수동 조작 없이 이를 우아하게 처리하거나, 오류 대신
멈춘다는 것을 발견하면 이 섹션을 업데이트하세요.

#### `server_stop`

`server_stop`은 재실행이 없는 `server_restart`입니다: 동일한 잠시 대기 후
플러시하는 패턴이지만, `os.execv` 대신 `os._exit(0)`을 호출하므로 프로세스는
그냥 종료됩니다. 원시 MCP 클라이언트에 직접 검증한 결과:

- 프로세스가 완전히 종료됩니다 (`ps -p <pid>`가 아무것도 반환하지 않는 것으로
  확인).
- 해당 세션의 이후 도구 호출은 즉시 `ClosedResourceError`로 실패합니다
  (stdio 파이프가 사라짐) - 작동했는지에 대한 모호함이 없습니다.

아무것도 자동으로 재시작하지 않습니다. 이후에 캘린더/미리 알림 도구 사용을
재개하려면, Claude Desktop에서 `apple-calendar` 커넥터를 껐다가 다시 켜거나
(새 하위 프로세스 생성), Claude Desktop을 재시작하세요. 설정 파일을 편집하지
않고 서버의 데이터 접근을 일시 중단하고 싶을 때(예: 자리를 비울 때)
사용하세요.

## 참고 사항

- 모든 데이터는 기기에 남아 있습니다; 서버는 stdio를 통해 MCP 클라이언트에게
  EventKit에 대해서만 이야기합니다.
- 이 서버로 생성된 항목은 메모 앞에 `"Created by Claude Desktop"` 줄이
  추가되어, 직접 만든 항목과 구별할 수 있습니다.
- 입출력 날짜는 ISO 8601 형식(`2026-03-15T14:00:00`)이며, 로컬 시간대로
  해석됩니다.
- 모든 도구는 자체 예외를 처리하고 예외를 발생시키는 대신
  `{"success": false, "error": ..., "message": ...}` 딕셔너리를 반환합니다
  - 잘못된 id, 잘못된 날짜, 또는 누락된 권한이 서버를 절대 충돌시키지
    않습니다.

## 개발

```bash
uv run python -m apple_calendar_mcp.server   # 독립 실행 (stdio 읽기/쓰기)
uv sync                                       # pyproject.toml 편집 후
```

공식 MCP Inspector로 도구를 대화형으로 검사하려면 (Node.js 필요, 이 프로젝트
빌드 시 설치되지 않음):

```bash
npx @modelcontextprotocol/inspector uv run python -m apple_calendar_mcp.server
```

Node를 사용할 수 없었기 때문에, 대신 `mcp` Python SDK 자체 클라이언트
(`ClientSession` + `stdio_client`)로 프로토콜 계층을 검증했습니다: 전체
`initialize` 핸드셰이크, `list_tools` (28개 도구), 그리고 대표적인 도구
호출(잘못된 날짜, 잘못된 span, 알 수 없는 id, 잘못된 우선순위/scope 등의
오류 경로 포함) 모두 서버가 충돌하지 않고 잘 구성된 응답을 반환했습니다.
태그 이름 변경/병합/삭제의 정확성(일치하는 항목만 업데이트, 메모 본문 보존,
관련 없는 태그는 건드리지 않음)은 실제 검증에는 이 머신에서 먼저 캘린더/미리
알림 권한이 부여되어야 하기 때문에, EventKit을 대신하는 가짜 인메모리
저장소로 검증했습니다.
