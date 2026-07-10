"""EKEventStore 작업을 위한 스레드 안전 래퍼."""

import threading
from datetime import datetime, timedelta
from typing import Optional

import EventKit
from Cocoa import NSDate, NSDateComponents, NSCalendar, NSURL

from .tags import decode_tags, merge_notes_with_tags
from .permissions import (
    require_calendar_permission,
    require_reminders_permission,
    request_all_permissions,
)

# MCP로 생성한 항목에 붙이는 출처 표시
CREATED_BY_NOTE = "Created by Claude Desktop"


class EventKitStore:
    """EKEventStore 작업을 위한 스레드 안전 래퍼."""

    def __init__(self):
        self._store = EventKit.EKEventStore.alloc().init()
        self._lock = threading.Lock()

    def request_permissions(self) -> None:
        """시작 시 권한을 요청합니다 (논블로킹)."""
        request_all_permissions(self._store)

    # -------------------------------------------------------------------------
    # 캘린더 관련 작업
    # -------------------------------------------------------------------------

    def get_calendars(self) -> list[dict]:
        """이벤트용 캘린더를 모두 가져옵니다."""
        require_calendar_permission()
        with self._lock:
            calendars = self._store.calendarsForEntityType_(
                EventKit.EKEntityTypeEvent
            )
            return [self._calendar_to_dict(c) for c in (calendars or [])]

    def get_default_calendar(self) -> Optional[EventKit.EKCalendar]:
        """새 이벤트를 위한 기본 캘린더를 가져옵니다."""
        with self._lock:
            return self._store.defaultCalendarForNewEvents()

    def find_calendar_by_name(self, name: str) -> Optional[EventKit.EKCalendar]:
        """이름으로 캘린더를 찾습니다 (대소문자 구분 없음)."""
        with self._lock:
            return self._find_calendar_unlocked(name)

    def get_events(
        self,
        start: datetime,
        end: datetime,
        calendar_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """날짜 범위 내 이벤트를 가져옵니다."""
        require_calendar_permission()
        with self._lock:
            return self._get_events_unlocked(start, end, calendar_name, limit)

    def _get_events_unlocked(
        self,
        start: datetime,
        end: datetime,
        calendar_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        start_ns = self._datetime_to_nsdate(start)
        end_ns = self._datetime_to_nsdate(end)

        if calendar_name:
            cal = self._find_calendar_unlocked(calendar_name)
            calendars = [cal] if cal else []
        else:
            calendars = list(
                self._store.calendarsForEntityType_(EventKit.EKEntityTypeEvent) or []
            )

        if not calendars:
            return []

        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            start_ns, end_ns, calendars
        )

        events = self._store.eventsMatchingPredicate_(predicate) or []
        sorted_events = sorted(events, key=lambda e: e.startDate().timeIntervalSince1970())
        return [self._event_to_dict(e) for e in sorted_events[:limit]]

    def get_event_by_id(self, event_id: str) -> Optional[dict]:
        """식별자로 특정 이벤트를 가져옵니다."""
        require_calendar_permission()
        with self._lock:
            event = self._find_event_by_any_id(event_id)
            return self._event_to_dict(event) if event else None

    def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        calendar_name: Optional[str] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        url: Optional[str] = None,
        is_all_day: bool = False,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """새 캘린더 이벤트를 생성합니다."""
        require_calendar_permission()
        with self._lock:
            event = EventKit.EKEvent.eventWithEventStore_(self._store)
            event.setTitle_(title)
            event.setStartDate_(self._datetime_to_nsdate(start))
            event.setEndDate_(self._datetime_to_nsdate(end))
            event.setAllDay_(is_all_day)

            if calendar_name:
                cal = self._find_calendar_unlocked(calendar_name)
                event.setCalendar_(cal or self._store.defaultCalendarForNewEvents())
            else:
                event.setCalendar_(self._store.defaultCalendarForNewEvents())

            if location:
                event.setLocation_(location)
            if url:
                event.setURL_(NSURL.URLWithString_(url))

            notes_with_attribution = f"{CREATED_BY_NOTE}\n\n{notes}" if notes else CREATED_BY_NOTE
            final_notes = merge_notes_with_tags(notes_with_attribution, tags)
            event.setNotes_(final_notes)

            success, error = self._store.saveEvent_span_error_(
                event, EventKit.EKSpanThisEvent, None
            )
            if not success:
                raise Exception(f"Failed to save event: {error}")

            return self._event_to_dict(event)

    def edit_event(
        self,
        event_id: str,
        span: str = "this_event",
        title: Optional[str] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        location: Optional[str] = None,
        notes: Optional[str] = None,
        url: Optional[str] = None,
        tags: Optional[list[str]] = None,
        calendar_name: Optional[str] = None,
    ) -> dict:
        """기존 이벤트를 수정합니다."""
        require_calendar_permission()
        with self._lock:
            event = self._find_event_by_any_id(event_id)
            if not event:
                raise ValueError(f"Event not found: {event_id}")

            if calendar_name is not None:
                # EventKit은 반복 이벤트의 캘린더 이동을 허용하지 않습니다.
                if event.hasRecurrenceRules():
                    raise ValueError(
                        "Cannot move a recurring event to another calendar. "
                        "Remove the recurrence first, or delete and recreate the event."
                    )
                cal = self._find_calendar_unlocked(calendar_name)
                if cal is None:
                    raise ValueError(f"Calendar not found: {calendar_name}")
                event.setCalendar_(cal)

            if title is not None:
                event.setTitle_(title)
            if start is not None:
                event.setStartDate_(self._datetime_to_nsdate(start))
            if end is not None:
                event.setEndDate_(self._datetime_to_nsdate(end))
            if location is not None:
                event.setLocation_(location)
            if url is not None:
                event.setURL_(NSURL.URLWithString_(url) if url else None)

            if notes is not None or tags is not None:
                current_notes = event.notes() or ""
                clean_notes, existing_tags = decode_tags(current_notes)

                if notes is not None:
                    clean_notes = notes
                if tags is not None:
                    existing_tags = tags

                final_notes = merge_notes_with_tags(clean_notes, existing_tags)
                event.setNotes_(final_notes if final_notes else None)

            ek_span = (
                EventKit.EKSpanFutureEvents
                if span == "future_events"
                else EventKit.EKSpanThisEvent
            )

            success, error = self._store.saveEvent_span_error_(event, ek_span, None)
            if not success:
                raise Exception(f"Failed to update event: {error}")

            return self._event_to_dict(event)

    def delete_event(self, event_id: str, span: str = "this_event") -> bool:
        """이벤트를 삭제합니다."""
        require_calendar_permission()
        with self._lock:
            event = self._find_event_by_any_id(event_id)
            if not event:
                raise ValueError(f"Event not found: {event_id}")

            ek_span = (
                EventKit.EKSpanFutureEvents
                if span == "future_events"
                else EventKit.EKSpanThisEvent
            )

            success, error = self._store.removeEvent_span_error_(event, ek_span, None)
            if not success:
                raise Exception(f"Failed to delete event: {error}")

            return True

    def search_events(
        self,
        query: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        tags: Optional[list[str]] = None,
        limit: int = 50,
    ) -> list[dict]:
        """제목/장소/notes에서 텍스트로 이벤트를 검색합니다."""
        require_calendar_permission()

        if start is None:
            start = datetime.now() - timedelta(days=30)
        if end is None:
            end = datetime.now() + timedelta(days=90)

        events = self.get_events(start, end, limit=1000)

        query_lower = query.lower()
        results = []
        for event in events:
            searchable = " ".join([
                event.get("title", "") or "",
                event.get("location", "") or "",
                event.get("notes", "") or "",
            ]).lower()
            if query_lower in searchable:
                results.append(event)

        if tags:
            from .tags import filter_by_tags
            results = filter_by_tags(results, tags)

        return results[:limit]

    def get_events_wide(
        self,
        years_back: int = 6,
        years_forward: int = 6,
        window_years: int = 3,
        calendar_name: Optional[str] = None,
        limit: int = 5000,
    ) -> tuple[list[dict], bool]:
        """넓은 날짜 범위를 여러 구간으로 나눠 이벤트를 가져옵니다.

        EventKit의 날짜 범위 predicate는 문서화되지 않은 실질적 제한
        (~4년)이 있어서, 요청 범위를 더 작은 구간으로 나눠 조회한 뒤
        중복을 제거하며 합칩니다. "전체" 이벤트를 봐야 하는 태그 관리
        도구에서 사용합니다 (agenda처럼 범위가 정해진 조회가 아님).

        Returns:
            (events, truncated) 튜플. truncated는 결과가 limit에 도달해
            일부 이벤트가 누락되었을 수 있음을 의미합니다.
        """
        require_calendar_permission()
        now = datetime.now()
        window_start = now - timedelta(days=365 * years_back)
        overall_end = now + timedelta(days=365 * years_forward)

        seen_ids = set()
        merged: list[dict] = []
        truncated = False

        with self._lock:
            while window_start < overall_end:
                window_end = min(
                    window_start + timedelta(days=365 * window_years), overall_end
                )
                chunk = self._get_events_unlocked(
                    window_start, window_end, calendar_name, limit=limit
                )
                for ev in chunk:
                    key = ev.get("id") or ev.get("external_id")
                    if key and key not in seen_ids:
                        seen_ids.add(key)
                        merged.append(ev)
                        if len(merged) >= limit:
                            truncated = True
                            break
                if truncated:
                    break
                window_start = window_end

        return merged, truncated

    # -------------------------------------------------------------------------
    # 미리 알림 관련 작업
    # -------------------------------------------------------------------------

    def get_reminder_lists(self) -> list[dict]:
        """모든 미리 알림 목록을 가져옵니다."""
        require_reminders_permission()
        with self._lock:
            calendars = self._store.calendarsForEntityType_(
                EventKit.EKEntityTypeReminder
            )
            return [self._calendar_to_dict(c) for c in (calendars or [])]

    def get_default_reminder_list(self) -> Optional[EventKit.EKCalendar]:
        """기본 미리 알림 목록을 가져옵니다."""
        with self._lock:
            return self._store.defaultCalendarForNewReminders()

    def find_reminder_list_by_name(self, name: str) -> Optional[EventKit.EKCalendar]:
        """이름으로 미리 알림 목록을 찾습니다 (대소문자 구분 없음)."""
        with self._lock:
            return self._find_reminder_list_unlocked(name)

    def get_reminders(
        self,
        list_name: Optional[str] = None,
        include_completed: bool = False,
        due_before: Optional[datetime] = None,
        due_after: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """선택적 필터를 적용해 미리 알림을 가져옵니다."""
        require_reminders_permission()

        with self._lock:
            if list_name:
                cal = self._find_reminder_list_unlocked(list_name)
                calendars = [cal] if cal else []
            else:
                calendars = list(
                    self._store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
                    or []
                )

            if not calendars:
                return []

            if include_completed:
                predicate = self._store.predicateForRemindersInCalendars_(calendars)
            else:
                predicate = self._store.predicateForIncompleteRemindersWithDueDateStarting_ending_calendars_(
                    self._datetime_to_nsdate(due_after) if due_after else None,
                    self._datetime_to_nsdate(due_before) if due_before else None,
                    calendars,
                )

            reminders_result = []
            semaphore = threading.Semaphore(0)

            def fetch_callback(reminders):
                nonlocal reminders_result
                reminders_result = list(reminders) if reminders else []
                semaphore.release()

            self._store.fetchRemindersMatchingPredicate_completion_(
                predicate, fetch_callback
            )
            if not semaphore.acquire(timeout=30):
                raise Exception(
                    "Timed out waiting for EventKit to return reminders "
                    "(fetchRemindersMatchingPredicate:completion: never called back)"
                )

            results = [self._reminder_to_dict(r) for r in reminders_result]

            # predicateForRemindersInCalendars_는 완료 여부와 무관하게 가져오므로
            # due_before/due_after는 여기서 직접 필터링해야 합니다.
            if due_after and include_completed:
                cutoff = due_after.isoformat()
                results = [r for r in results if (r.get("due_date") or "") >= cutoff]
            if due_before and include_completed:
                cutoff = due_before.isoformat()
                results = [r for r in results if (r.get("due_date") or "9999-12-31") <= cutoff]

            results.sort(key=lambda r: r.get("due_date") or "9999-12-31")
            return results[:limit]

    def get_reminder_by_id(self, reminder_id: str) -> Optional[dict]:
        """식별자로 특정 미리 알림을 가져옵니다."""
        require_reminders_permission()
        with self._lock:
            item = self._find_reminder_by_any_id(reminder_id)
            return self._reminder_to_dict(item) if item else None

    def create_reminder(
        self,
        title: str,
        list_name: Optional[str] = None,
        notes: Optional[str] = None,
        due_date: Optional[datetime] = None,
        priority: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """새 미리 알림을 생성합니다."""
        require_reminders_permission()
        with self._lock:
            reminder = EventKit.EKReminder.reminderWithEventStore_(self._store)
            reminder.setTitle_(title)

            if list_name:
                cal = self._find_reminder_list_unlocked(list_name)
                reminder.setCalendar_(cal or self._store.defaultCalendarForNewReminders())
            else:
                reminder.setCalendar_(self._store.defaultCalendarForNewReminders())

            if due_date:
                reminder.setDueDateComponents_(self._datetime_to_components(due_date))

            if priority:
                priority_map = {"high": 1, "medium": 5, "low": 9, "none": 0}
                reminder.setPriority_(priority_map.get(priority.lower(), 0))

            notes_with_attribution = f"{CREATED_BY_NOTE}\n\n{notes}" if notes else CREATED_BY_NOTE
            final_notes = merge_notes_with_tags(notes_with_attribution, tags)
            reminder.setNotes_(final_notes)

            success, error = self._store.saveReminder_commit_error_(reminder, True, None)
            if not success:
                raise Exception(f"Failed to save reminder: {error}")

            return self._reminder_to_dict(reminder)

    def edit_reminder(
        self,
        reminder_id: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        due_date: Optional[datetime] = None,
        priority: Optional[str] = None,
        completed: Optional[bool] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """기존 미리 알림을 수정합니다."""
        require_reminders_permission()
        with self._lock:
            reminder = self._find_reminder_by_any_id(reminder_id)
            if not reminder:
                raise ValueError(f"Reminder not found: {reminder_id}")

            if title is not None:
                reminder.setTitle_(title)

            if due_date is not None:
                reminder.setDueDateComponents_(self._datetime_to_components(due_date))

            if priority is not None:
                priority_map = {"high": 1, "medium": 5, "low": 9, "none": 0}
                reminder.setPriority_(priority_map.get(priority.lower(), 0))

            if completed is not None:
                reminder.setCompleted_(completed)

            if notes is not None or tags is not None:
                current_notes = reminder.notes() or ""
                clean_notes, existing_tags = decode_tags(current_notes)

                if notes is not None:
                    clean_notes = notes
                if tags is not None:
                    existing_tags = tags

                final_notes = merge_notes_with_tags(clean_notes, existing_tags)
                reminder.setNotes_(final_notes if final_notes else None)

            success, error = self._store.saveReminder_commit_error_(reminder, True, None)
            if not success:
                raise Exception(f"Failed to update reminder: {error}")

            return self._reminder_to_dict(reminder)

    def complete_reminder(self, reminder_id: str) -> dict:
        """미리 알림을 완료로 표시합니다."""
        return self.edit_reminder(reminder_id, completed=True)

    def delete_reminder(self, reminder_id: str) -> bool:
        """미리 알림을 삭제합니다."""
        require_reminders_permission()
        with self._lock:
            reminder = self._find_reminder_by_any_id(reminder_id)
            if not reminder:
                raise ValueError(f"Reminder not found: {reminder_id}")

            success, error = self._store.removeReminder_commit_error_(reminder, True, None)
            if not success:
                raise Exception(f"Failed to delete reminder: {error}")

            return True

    def search_reminders(
        self,
        query: str,
        tags: Optional[list[str]] = None,
        include_completed: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        """제목이나 notes에서 텍스트로 미리 알림을 검색합니다."""
        require_reminders_permission()

        reminders = self.get_reminders(include_completed=include_completed, limit=1000)

        query_lower = query.lower()
        results = []
        for reminder in reminders:
            searchable = " ".join([
                reminder.get("title", "") or "",
                reminder.get("notes", "") or "",
            ]).lower()
            if query_lower in searchable:
                results.append(reminder)

        if tags:
            from .tags import filter_by_tags
            results = filter_by_tags(results, tags)

        return results[:limit]

    def get_all_reminders_wide(
        self, include_completed: bool = True, limit: int = 20000
    ) -> tuple[list[dict], bool]:
        """모든 목록에 걸쳐 (사실상) 모든 미리 알림을 가져옵니다.

        미리 알림 predicate는 이벤트 predicate처럼 날짜 범위 제한이 없어서
        한 번의 조회로 충분합니다. 태그 관리 도구에서 사용합니다.
        """
        results = self.get_reminders(include_completed=include_completed, limit=limit)
        return results, len(results) >= limit

    # -------------------------------------------------------------------------
    # 헬퍼 메서드
    # -------------------------------------------------------------------------

    def _datetime_to_nsdate(self, dt: datetime) -> NSDate:
        """Python datetime을 NSDate로 변환합니다 (로컬 타임존 기준)."""
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())

    def _nsdate_to_iso(self, ns_date: NSDate) -> Optional[str]:
        """NSDate를 ISO 8601 문자열로 변환합니다 (로컬 타임존 기준)."""
        if not ns_date:
            return None
        timestamp = ns_date.timeIntervalSince1970()
        return datetime.fromtimestamp(timestamp).isoformat()

    def _datetime_to_components(self, dt: datetime) -> NSDateComponents:
        """미리 알림 마감일을 위해 datetime을 NSDateComponents로 변환합니다."""
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))

        components = NSDateComponents.alloc().init()
        components.setYear_(dt.year)
        components.setMonth_(dt.month)
        components.setDay_(dt.day)
        components.setHour_(dt.hour)
        components.setMinute_(dt.minute)
        components.setSecond_(dt.second)
        return components

    def _components_to_iso(self, components: NSDateComponents) -> Optional[str]:
        """NSDateComponents를 ISO 문자열로 변환합니다."""
        if not components:
            return None

        try:
            calendar = NSCalendar.currentCalendar()
            ns_date = calendar.dateFromComponents_(components)
            if ns_date:
                return self._nsdate_to_iso(ns_date)
        except Exception:
            pass

        # 폴백: NSCalendar 변환이 실패하면 직접 datetime을 구성합니다.
        try:
            unset = 9223372036854775807
            dt = datetime(
                year=components.year() if components.year() != unset else 2000,
                month=components.month() if components.month() != unset else 1,
                day=components.day() if components.day() != unset else 1,
                hour=components.hour() if components.hour() != unset else 0,
                minute=components.minute() if components.minute() != unset else 0,
                second=components.second() if components.second() != unset else 0,
            )
            return dt.isoformat()
        except Exception:
            return None

    def _calendar_to_dict(self, calendar: EventKit.EKCalendar) -> dict:
        """EKCalendar를 dict로 변환합니다."""
        return {
            "id": calendar.calendarIdentifier(),
            "title": calendar.title(),
            "type": str(calendar.type()),
            "allows_modifications": calendar.allowsContentModifications(),
        }

    def _event_to_dict(self, event: EventKit.EKEvent) -> dict:
        """EKEvent를 dict로 변환합니다."""
        notes = event.notes() or ""
        clean_notes, tags = decode_tags(notes)

        return {
            "id": event.calendarItemIdentifier(),
            "external_id": event.calendarItemExternalIdentifier(),
            "title": event.title(),
            "start_date": self._nsdate_to_iso(event.startDate()),
            "end_date": self._nsdate_to_iso(event.endDate()),
            "location": event.location(),
            "notes": clean_notes,
            "tags": tags,
            "calendar": event.calendar().title() if event.calendar() else None,
            "is_all_day": event.isAllDay(),
            "url": str(event.URL()) if event.URL() else None,
            "has_recurrence": event.hasRecurrenceRules(),
        }

    def _reminder_to_dict(self, reminder: EventKit.EKReminder) -> dict:
        """EKReminder를 dict로 변환합니다."""
        notes = reminder.notes() or ""
        clean_notes, tags = decode_tags(notes)

        priority_val = reminder.priority()
        if priority_val == 1:
            priority = "high"
        elif priority_val == 5:
            priority = "medium"
        elif priority_val == 9:
            priority = "low"
        else:
            priority = "none"

        return {
            "id": reminder.calendarItemIdentifier(),
            "external_id": reminder.calendarItemExternalIdentifier(),
            "title": reminder.title(),
            "notes": clean_notes,
            "tags": tags,
            "list": reminder.calendar().title() if reminder.calendar() else None,
            "due_date": self._components_to_iso(reminder.dueDateComponents()),
            "priority": priority,
            "completed": reminder.isCompleted(),
            "completion_date": self._nsdate_to_iso(reminder.completionDate()),
        }

    def _find_calendar_unlocked(self, name: str) -> Optional[EventKit.EKCalendar]:
        """락을 잡지 않고 이름으로 캘린더를 찾습니다 (호출자가 락을 들고 있어야 함)."""
        calendars = self._store.calendarsForEntityType_(EventKit.EKEntityTypeEvent)
        for cal in (calendars or []):
            if cal.title().lower() == name.lower():
                return cal
        return None

    def _find_reminder_list_unlocked(self, name: str) -> Optional[EventKit.EKCalendar]:
        """락을 잡지 않고 이름으로 미리 알림 목록을 찾습니다."""
        calendars = self._store.calendarsForEntityType_(EventKit.EKEntityTypeReminder)
        for cal in (calendars or []):
            if cal.title().lower() == name.lower():
                return cal
        return None

    def _find_event_by_any_id(self, event_id: str) -> Optional[EventKit.EKEvent]:
        """내부 식별자 또는 외부 식별자로 이벤트를 찾습니다."""
        item = self._store.calendarItemWithIdentifier_(event_id)
        if item and isinstance(item, EventKit.EKEvent):
            return item
        return self._find_event_by_external_id(event_id)

    def _find_event_by_external_id(self, external_id: str) -> Optional[EventKit.EKEvent]:
        """외부 식별자로 이벤트를 찾습니다 (넓은 날짜 범위를 검색)."""
        start = datetime.now() - timedelta(days=365)
        end = datetime.now() + timedelta(days=365)

        start_ns = self._datetime_to_nsdate(start)
        end_ns = self._datetime_to_nsdate(end)

        calendars = list(
            self._store.calendarsForEntityType_(EventKit.EKEntityTypeEvent) or []
        )
        if not calendars:
            return None

        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            start_ns, end_ns, calendars
        )

        events = self._store.eventsMatchingPredicate_(predicate) or []
        for event in events:
            if event.calendarItemExternalIdentifier() == external_id:
                return event
        return None

    def _find_reminder_by_any_id(self, reminder_id: str) -> Optional[EventKit.EKReminder]:
        """내부 식별자 또는 외부 식별자로 미리 알림을 찾습니다."""
        item = self._store.calendarItemWithIdentifier_(reminder_id)
        if item and isinstance(item, EventKit.EKReminder):
            return item
        return self._find_reminder_by_external_id(reminder_id)

    def _find_reminder_by_external_id(self, external_id: str) -> Optional[EventKit.EKReminder]:
        """외부 식별자로 미리 알림을 찾습니다."""
        calendars = list(
            self._store.calendarsForEntityType_(EventKit.EKEntityTypeReminder) or []
        )
        if not calendars:
            return None

        predicate = self._store.predicateForRemindersInCalendars_(calendars)

        result = []
        semaphore = threading.Semaphore(0)

        def callback(reminders):
            nonlocal result
            if reminders:
                for r in reminders:
                    if r.calendarItemExternalIdentifier() == external_id:
                        result.append(r)
                        break
            semaphore.release()

        self._store.fetchRemindersMatchingPredicate_completion_(predicate, callback)
        if not semaphore.acquire(timeout=30):
            raise Exception(
                "Timed out waiting for EventKit to return reminders "
                "(fetchRemindersMatchingPredicate:completion: never called back)"
            )

        return result[0] if result else None
