"""기본 캘린더/미리 알림 도구 위에 얹은 커스텀 편의 도구 모음.

quick_event()는 완전한 NLP 날짜 라이브러리 대신 작은 휴리스틱 파서를
사용합니다 (이 프로젝트는 의도적으로 mcp[cli]와 pyobjc 외의 의존성을
두지 않음) - 흔한 표현들은 다루지만 완벽하지는 않은 best-effort 방식입니다.
정확히 인식하는 패턴과 한계는 README를 참고하세요.
"""

import re
from datetime import datetime, timedelta, date, time
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .eventkit_store import EventKitStore
from .permissions import PermissionError

DAY_ABBR = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}

DEFAULT_EVENT_DURATION = timedelta(hours=1)
MEAL_DEFAULT_TIMES = {"breakfast": time(8, 0), "lunch": time(12, 0), "dinner": time(19, 0)}


def _parse_date_only(value: str) -> date:
    """날짜만 있는 문자열 또는 전체 ISO datetime 문자열을 date로 파싱합니다."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _fmt_day_header(d: date) -> str:
    return d.strftime("%a %Y-%m-%d")


def _format_agenda(events: list[dict], reminders: list[dict], start: date, end: date) -> str:
    """한 줄에 한 항목씩, 사람이 읽기 좋은 일정 요약을 만듭니다."""
    by_day: dict[date, list[str]] = {}

    for ev in events:
        ev_start = datetime.fromisoformat(ev["start_date"])
        day = ev_start.date()
        if ev.get("is_all_day"):
            line = f"  All day: {ev['title']}"
        else:
            ev_end = datetime.fromisoformat(ev["end_date"])
            line = f"  {_fmt_time(ev_start)}-{_fmt_time(ev_end)} {ev['title']}"
        if ev.get("location"):
            line += f" @{ev['location']}"
        if ev.get("tags"):
            line += " " + " ".join(f"#{t}" for t in ev["tags"])
        by_day.setdefault(day, []).append(line)

    reminder_lines = []
    for rem in reminders:
        due = rem.get("due_date")
        due_str = f" (due {due[:16].replace('T', ' ')})" if due else ""
        reminder_lines.append(f"  [ ] {rem['title']}{due_str}")

    parts = []
    day = start
    while day <= end:
        parts.append(f"## {_fmt_day_header(day)}")
        lines = by_day.get(day)
        if lines:
            parts.extend(lines)
        else:
            parts.append("  (no events)")
        day += timedelta(days=1)

    if reminder_lines:
        parts.append("## Reminders due in range")
        parts.extend(reminder_lines)

    return "\n".join(parts)


def _quick_event_parse(text: str, now: Optional[datetime] = None) -> dict:
    """짧은 자연어 한 줄을 이벤트 필드로 best-effort 파싱합니다.

    인식하는 표현 (대소문자 구분 없음):
      - 상대적 날짜: today, tomorrow, mon/monday .. sun/sunday
      - "in N day(s)"
      - 명시적 날짜: YYYY-MM-DD
      - 시각: "3pm", "3:30pm", "15:00" (앞에 "at"가 붙을 수 있음)
      - 소요시간: "for 30 min(utes)", "for 2 hour(s)/hr(s)"
      - 끝부분의 #해시태그 -> tags
    나머지 (연결어 제외)는 제목이 됩니다.
    """
    now = now or datetime.now()
    working = text.strip()

    tags = re.findall(r"#([a-z0-9_]+)", working, re.IGNORECASE)
    working = re.sub(r"#[a-z0-9_]+", "", working, flags=re.IGNORECASE)

    target_date = now.date()
    date_matched = False

    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", working)
    if m:
        target_date = _parse_date_only(m.group(1))
        working = working[:m.start()] + working[m.end():]
        date_matched = True

    if not date_matched:
        m = re.search(r"\btomorrow\b", working, re.IGNORECASE)
        if m:
            target_date = now.date() + timedelta(days=1)
            working = working[:m.start()] + working[m.end():]
            date_matched = True

    if not date_matched:
        m = re.search(r"\btoday\b", working, re.IGNORECASE)
        if m:
            target_date = now.date()
            working = working[:m.start()] + working[m.end():]
            date_matched = True

    if not date_matched:
        m = re.search(r"\bin (\d+) days?\b", working, re.IGNORECASE)
        if m:
            target_date = now.date() + timedelta(days=int(m.group(1)))
            working = working[:m.start()] + working[m.end():]
            date_matched = True

    if not date_matched:
        m = re.search(r"\b(mon|monday|tue|tues|tuesday|wed|wednesday|thu|thur|thurs|thursday|fri|friday|sat|saturday|sun|sunday)\b", working, re.IGNORECASE)
        if m:
            word = m.group(1).lower()
            weekday_target = DAY_ABBR.get(word[:3])
            if weekday_target is not None:
                days_ahead = (weekday_target - now.weekday()) % 7
                days_ahead = days_ahead or 7  # 오늘이 아니라 다음번 해당 요일
                target_date = now.date() + timedelta(days=days_ahead)
                working = working[:m.start()] + working[m.end():]
                date_matched = True

    target_time = None
    m = re.search(r"\b(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?\b", working, re.IGNORECASE)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        ampm = m.group(3)
        if ampm and ampm.lower() == "pm" and hour < 12:
            hour += 12
        if ampm and ampm.lower() == "am" and hour == 12:
            hour = 0
        target_time = time(hour % 24, minute)
        working = working[:m.start()] + working[m.end():]

    if target_time is None:
        m = re.search(r"\b(?:at\s+)?(\d{1,2})\s*(am|pm)\b", working, re.IGNORECASE)
        if m:
            hour = int(m.group(1))
            ampm = m.group(2).lower()
            if ampm == "pm" and hour < 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
            target_time = time(hour % 24, 0)
            working = working[:m.start()] + working[m.end():]

    duration = DEFAULT_EVENT_DURATION
    m = re.search(r"\bfor\s+(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", working, re.IGNORECASE)
    if m:
        amount = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("h"):
            duration = timedelta(hours=amount)
        else:
            duration = timedelta(minutes=amount)
        working = working[:m.start()] + working[m.end():]

    title = re.sub(r"\s+", " ", working).strip(" -,.")
    title = re.sub(r"^(at|on|for)\s+", "", title, flags=re.IGNORECASE).strip()

    if target_time is None:
        for keyword, meal_time in MEAL_DEFAULT_TIMES.items():
            if keyword in title.lower():
                target_time = meal_time
                break
    if target_time is None:
        target_time = time(9, 0)

    start_dt = datetime.combine(target_date, target_time)
    end_dt = start_dt + duration

    return {
        "title": title or text.strip(),
        "start": start_dt,
        "end": end_dt,
        "tags": tags or None,
    }


def register_extra_tools(mcp: FastMCP, store: EventKitStore) -> None:
    """커스텀 편의 도구를 모두 MCP 서버에 등록합니다."""

    @mcp.tool()
    def agenda_today() -> dict:
        """오늘 일정을 한 줄씩 사람이 읽기 좋은 형식으로 가져옵니다.

        오늘의 이벤트(시간, 장소, 태그 포함)와 오늘 마감인 미완료
        미리 알림을 포함합니다.
        """
        today = date.today().isoformat()
        return agenda_range(today, today)

    @mcp.tool()
    def agenda_range(start_date: str, end_date: str) -> dict:
        """지정한 날짜 범위에 대한 사람이 읽기 좋은 일정을 가져옵니다.

        Args:
            start_date: 범위 시작일, YYYY-MM-DD (또는 전체 ISO datetime)
            end_date: 범위 종료일 (포함), YYYY-MM-DD (또는 전체 ISO datetime)
        """
        try:
            start_day = _parse_date_only(start_date)
            end_day = _parse_date_only(end_date)
            if end_day < start_day:
                return {"success": False, "error": "invalid_range", "message": "end_date must not be before start_date"}

            range_start = datetime.combine(start_day, time(0, 0))
            range_end = datetime.combine(end_day, time(23, 59, 59))

            events = store.get_events(start=range_start, end=range_end, limit=200)
            reminders = store.get_reminders(
                due_after=range_start, due_before=range_end, include_completed=False, limit=200
            )

            summary = _format_agenda(events, reminders, start_day, end_day)

            return {
                "success": True,
                "summary": summary,
                "events": events,
                "reminders_due": reminders,
                "event_count": len(events),
                "reminder_count": len(reminders),
            }
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_date", "message": f"Invalid date format: {e}"}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def quick_event(text: str, calendar_name: Optional[str] = None) -> dict:
        """짧은 자연어 한 줄로부터 이벤트를 생성합니다.

        Best-effort 파싱 (외부 NLP 의존성 없음) - 상대적 날짜
        (today/tomorrow/Fri), 명시적 날짜(YYYY-MM-DD), 시각
        (3pm, 3:30pm, 15:00), 소요시간("for 2 hours"), 끝부분의
        #해시태그를 인식합니다. 기본값: 소요시간 1시간, 시각이 없으면
        09:00 (제목에 lunch/dinner/breakfast가 있으면 각각
        12:00/19:00/08:00).

        Args:
            text: "lunch with Sara tomorrow at 1pm #personal" 같은 짧은 한 줄
            calendar_name: 대상 캘린더 (생략 시 기본 캘린더 사용)
        """
        try:
            parsed = _quick_event_parse(text)
            event = store.create_event(
                title=parsed["title"],
                start=parsed["start"],
                end=parsed["end"],
                calendar_name=calendar_name,
                tags=parsed["tags"],
            )
            return {
                "success": True,
                "event": event,
                "message": f"Created '{parsed['title']}' on {parsed['start'].strftime('%Y-%m-%d %H:%M')}",
                "parsed_from": text,
            }
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def reschedule_event(event_id: str, new_start: str, span: str = "this_event") -> dict:
        """이벤트를 새 시작 시각으로 옮기되, 기존 소요시간은 유지합니다.

        Args:
            event_id: 이벤트 식별자
            new_start: 새 시작 날짜/시간, ISO 8601 형식
            span: 반복 이벤트일 경우 'this_event' 또는 'future_events' (기본값: 'this_event')
        """
        if span not in ("this_event", "future_events"):
            return {"success": False, "error": "invalid_span", "message": "span must be 'this_event' or 'future_events'"}

        try:
            current = store.get_event_by_id(event_id)
            if not current:
                return {"success": False, "error": "not_found", "message": f"Event not found: {event_id}"}

            old_start = datetime.fromisoformat(current["start_date"])
            old_end = datetime.fromisoformat(current["end_date"])
            duration = old_end - old_start

            new_start_dt = datetime.fromisoformat(new_start.replace("Z", "+00:00"))
            new_end_dt = new_start_dt + duration

            event = store.edit_event(event_id=event_id, span=span, start=new_start_dt, end=new_end_dt)

            return {
                "success": True,
                "event": event,
                "message": f"Rescheduled to {new_start_dt.strftime('%Y-%m-%d %H:%M')} (duration kept at {duration})",
            }
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "not_found", "message": str(e)}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}

    @mcp.tool()
    def find_free_slots(
        date: str,
        working_hours: str = "09:00-18:00",
        min_duration_minutes: int = 30,
        calendar_name: Optional[str] = None,
    ) -> dict:
        """지정한 날짜의 근무시간 내에서 빈 시간대를 찾습니다.

        종일 이벤트는 무시합니다 (특정 시간대를 막지 않으므로).

        Args:
            date: 확인할 날짜, YYYY-MM-DD
            working_hours: 탐색할 "HH:MM-HH:MM" 범위 (기본값: "09:00-18:00")
            min_duration_minutes: 보고할 최소 슬롯 길이 (기본값: 30)
            calendar_name: 특정 캘린더로만 busy 시간을 조회 (선택)
        """
        try:
            day = _parse_date_only(date)

            wh_match = re.match(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$", working_hours.strip())
            if not wh_match:
                return {"success": False, "error": "invalid_working_hours", "message": "working_hours must be in 'HH:MM-HH:MM' format"}

            work_start = datetime.combine(day, time(int(wh_match.group(1)), int(wh_match.group(2))))
            work_end = datetime.combine(day, time(int(wh_match.group(3)), int(wh_match.group(4))))
            if work_end <= work_start:
                return {"success": False, "error": "invalid_working_hours", "message": "working_hours end must be after start"}

            day_events = store.get_events(
                start=datetime.combine(day, time(0, 0)),
                end=datetime.combine(day, time(23, 59, 59)),
                calendar_name=calendar_name,
                limit=200,
            )

            busy = []
            for ev in day_events:
                if ev.get("is_all_day"):
                    continue
                ev_start = max(datetime.fromisoformat(ev["start_date"]), work_start)
                ev_end = min(datetime.fromisoformat(ev["end_date"]), work_end)
                if ev_end > ev_start:
                    busy.append((ev_start, ev_end))

            busy.sort()
            merged: list[list[datetime]] = []
            for b_start, b_end in busy:
                if merged and b_start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], b_end)
                else:
                    merged.append([b_start, b_end])

            slots = []
            cursor = work_start
            for b_start, b_end in merged:
                if (b_start - cursor).total_seconds() / 60 >= min_duration_minutes:
                    slots.append((cursor, b_start))
                cursor = max(cursor, b_end)
            if (work_end - cursor).total_seconds() / 60 >= min_duration_minutes:
                slots.append((cursor, work_end))

            return {
                "success": True,
                "date": day.isoformat(),
                "working_hours": working_hours,
                "slots": [
                    {
                        "start": s.strftime("%H:%M"),
                        "end": e.strftime("%H:%M"),
                        "duration_minutes": int((e - s).total_seconds() // 60),
                    }
                    for s, e in slots
                ],
                "count": len(slots),
            }
        except PermissionError as e:
            return {"success": False, "error": "permission_denied", "message": str(e)}
        except ValueError as e:
            return {"success": False, "error": "invalid_date", "message": f"Invalid date format: {e}"}
        except Exception as e:
            return {"success": False, "error": "unexpected_error", "message": str(e)}
