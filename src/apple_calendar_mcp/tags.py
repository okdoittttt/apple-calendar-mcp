"""EventKit 항목의 태그 인코딩/디코딩.

EventKit은 네이티브 태그를 지원하지 않으므로, 태그를 notes 필드에
해시태그 형태(예: #work #urgent)로 저장합니다. 사람이 읽기 쉽고,
iCloud로 동기화되며, 기본 캘린더/미리 알림 앱에서도 검색 가능합니다.
"""

import re
from typing import Optional, Tuple

# 줄바꿈 뒤에 오는, 해시태그로만 이루어진 마지막 줄을 매칭합니다
# (해시태그 사이 공백은 선택적).
HASHTAG_LINE_PATTERN = re.compile(r'\n*(?:^|\n)((?:#[a-z0-9_]+\s*)+)$', re.IGNORECASE)

# 해시태그 줄에서 개별 해시태그를 추출합니다.
HASHTAG_PATTERN = re.compile(r'#([a-z0-9_]+)', re.IGNORECASE)


def _normalize_tag(tag: str) -> str:
    """태그를 정규화합니다: 소문자로 변환, 공백/하이픈을 언더스코어로, 트림."""
    normalized = tag.strip().lower()
    normalized = re.sub(r'[\s-]+', '_', normalized)
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    return normalized


def normalize_tag(tag: str) -> str:
    """태그 정규화 함수의 공개용 래퍼 (소문자, 언더스코어, 영문/숫자만)."""
    return _normalize_tag(tag)


def encode_tags(tags: Optional[list[str]]) -> str:
    """태그 목록을 notes에 붙일 해시태그 문자열로 인코딩합니다.

    Args:
        tags: 태그 문자열 목록, 또는 None/빈 목록

    Returns:
        해시태그 문자열 (앞에 빈 줄 구분자 포함), 태그가 없으면 ""
    """
    if not tags:
        return ""

    normalized = [_normalize_tag(t) for t in tags if t.strip()]
    seen = set()
    unique = []
    for tag in normalized:
        if tag and tag not in seen:
            seen.add(tag)
            unique.append(tag)

    if not unique:
        return ""

    hashtags = " ".join(f"#{tag}" for tag in sorted(unique))
    return f"\n\n{hashtags}"


def decode_tags(notes: Optional[str]) -> Tuple[str, list[str]]:
    """notes에서 태그를 추출하고, 태그가 제거된 본문을 함께 반환합니다.

    Args:
        notes: notes 필드 내용. 끝부분에 해시태그가 있을 수 있음

    Returns:
        (clean_notes, tags_list) 튜플
    """
    if not notes:
        return "", []

    match = HASHTAG_LINE_PATTERN.search(notes)
    if not match:
        return notes, []

    hashtag_line = match.group(1)
    tags = [t.lower() for t in HASHTAG_PATTERN.findall(hashtag_line)]
    clean_notes = HASHTAG_LINE_PATTERN.sub("", notes).strip()

    return clean_notes, tags


def merge_notes_with_tags(notes: Optional[str], tags: Optional[list[str]]) -> str:
    """사용자 notes와 해시태그를 합칩니다. 기존 해시태그 줄은 새 것으로 대체됩니다.

    Args:
        notes: 사용자의 notes 내용 (태그가 제거된 상태여야 함)
        tags: 적용할 태그 목록

    Returns:
        해시태그가 붙은 최종 notes 문자열
    """
    clean_notes, _ = decode_tags(notes)
    tag_string = encode_tags(tags)

    if clean_notes and tag_string:
        return clean_notes + tag_string
    elif clean_notes:
        return clean_notes
    elif tag_string:
        return tag_string.strip()
    else:
        return ""


def update_tags(
    notes: Optional[str],
    add_tags: Optional[list[str]] = None,
    remove_tags: Optional[list[str]] = None,
) -> str:
    """notes의 태그를 추가/제거하여 갱신합니다.

    Args:
        notes: 태그가 포함될 수 있는 현재 notes 내용
        add_tags: 추가할 태그 (이미 있으면 무시)
        remove_tags: 제거할 태그 (있는 경우에만)

    Returns:
        태그가 갱신된 notes 문자열
    """
    clean_notes, existing_tags = decode_tags(notes)
    tag_set = set(_normalize_tag(t) for t in existing_tags if t)

    if add_tags:
        for tag in add_tags:
            normalized = _normalize_tag(tag)
            if normalized:
                tag_set.add(normalized)

    if remove_tags:
        for tag in remove_tags:
            tag_set.discard(_normalize_tag(tag))

    final_tags = sorted(tag_set) if tag_set else None
    return merge_notes_with_tags(clean_notes, final_tags)


def has_tag(notes: Optional[str], tag: str) -> bool:
    """notes에 특정 태그가 있는지 확인합니다 (대소문자 구분 없음)."""
    _, tags = decode_tags(notes)
    normalized = _normalize_tag(tag)
    return normalized in [_normalize_tag(t) for t in tags]


def filter_by_tags(
    items: list[dict],
    required_tags: list[str],
    notes_key: str = "notes",
) -> list[dict]:
    """필수 태그를 기준으로 항목 목록을 필터링합니다 (모두 포함해야 함).

    Args:
        items: notes 필드를 가진 항목 dict 목록
        required_tags: 모두 포함되어야 하는 태그들
        notes_key: 항목 dict에서 notes가 담긴 키 이름

    Returns:
        필수 태그를 모두 가진 항목만 남긴 목록
    """
    if not required_tags:
        return items

    normalized_required = [_normalize_tag(t) for t in required_tags if t.strip()]
    if not normalized_required:
        return items

    result = []
    for item in items:
        notes = item.get(notes_key, "")
        _, item_tags = decode_tags(notes)
        item_tags_normalized = [_normalize_tag(t) for t in item_tags]

        if all(req in item_tags_normalized for req in normalized_required):
            result.append(item)

    return result
