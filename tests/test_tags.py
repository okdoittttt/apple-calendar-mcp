"""계층 1 - 순수 유닛 테스트: tags.py 의 태그 인코딩/디코딩 로직.

EventKit도 MCP도 필요 없어 가장 빠르고 결정적입니다. 순수 함수는
입력→출력이 명확해 테스트의 교과서적 대상입니다.
"""

import pytest

from apple_calendar_mcp.tags import (
    normalize_tag,
    encode_tags,
    decode_tags,
    merge_notes_with_tags,
    update_tags,
    has_tag,
    filter_by_tags,
)


class TestNormalizeTag:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Work", "work"),               # 소문자화
            ("Work Item", "work_item"),     # 공백 -> 언더스코어
            ("multi-word", "multi_word"),   # 하이픈 -> 언더스코어
            ("  trim  ", "trim"),           # 트림
            ("#hello", "hello"),            # 특수문자 제거
            ("a@b!c", "abc"),               # 영숫자/언더스코어만 남김
            ("", ""),                        # 빈 문자열
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_tag(raw) == expected


class TestEncodeTags:
    def test_none_and_empty(self):
        assert encode_tags(None) == ""
        assert encode_tags([]) == ""

    def test_sorted_and_prefixed(self):
        # 정규화 + 정렬 + '#' 접두 + 앞에 빈 줄 구분자
        assert encode_tags(["work", "apple"]) == "\n\n#apple #work"

    def test_dedupe_and_normalize(self):
        # 대소문자/중복은 하나로 합쳐짐
        assert encode_tags(["Work", "work", "WORK"]) == "\n\n#work"


class TestDecodeTags:
    def test_no_tags(self):
        assert decode_tags("just a note") == ("just a note", [])

    def test_none(self):
        assert decode_tags(None) == ("", [])

    def test_extracts_trailing_tags(self):
        clean, tags = decode_tags("Meeting notes\n\n#work #urgent")
        assert clean == "Meeting notes"
        assert tags == ["work", "urgent"]

    def test_only_tags(self):
        clean, tags = decode_tags("#a #b")
        assert clean == ""
        assert tags == ["a", "b"]


class TestRoundTrip:
    """encode -> notes -> decode 가 원래 태그를 복원하는지."""

    @pytest.mark.parametrize(
        "tags",
        [
            ["work"],
            ["work", "personal"],
            ["z", "a", "m"],
        ],
    )
    def test_encode_then_decode(self, tags):
        notes = "본문 내용" + encode_tags(tags)
        clean, decoded = decode_tags(notes)
        assert clean == "본문 내용"
        assert decoded == sorted(normalize_tag(t) for t in tags)


class TestMergeNotesWithTags:
    def test_body_and_tags(self):
        assert merge_notes_with_tags("body", ["b", "a"]) == "body\n\n#a #b"

    def test_body_only(self):
        assert merge_notes_with_tags("body", None) == "body"

    def test_tags_only(self):
        assert merge_notes_with_tags("", ["x"]) == "#x"

    def test_replaces_existing_tag_line(self):
        # 기존 태그 줄은 새 태그로 대체됨 (중복 누적 방지)
        result = merge_notes_with_tags("body\n\n#old", ["new"])
        assert result == "body\n\n#new"


class TestUpdateTags:
    def test_add(self):
        assert update_tags("body", add_tags=["new"]) == "body\n\n#new"

    def test_remove(self):
        assert update_tags("body\n\n#old", remove_tags=["old"]) == "body"

    def test_add_and_remove(self):
        assert update_tags("body\n\n#old", add_tags=["new"], remove_tags=["old"]) == "body\n\n#new"

    def test_add_is_idempotent(self):
        # 이미 있는 태그를 다시 추가해도 중복되지 않음
        assert update_tags("body\n\n#dup", add_tags=["dup"]) == "body\n\n#dup"


class TestHasTag:
    def test_present_case_insensitive(self):
        assert has_tag("note\n\n#work_item", "Work Item") is True

    def test_absent(self):
        assert has_tag("note\n\n#work", "personal") is False

    def test_no_notes(self):
        assert has_tag(None, "work") is False


class TestFilterByTags:
    def test_requires_all_tags(self):
        items = [
            {"id": 1, "notes": "a\n\n#work #urgent"},
            {"id": 2, "notes": "b\n\n#work"},
            {"id": 3, "notes": "c"},
        ]
        result = filter_by_tags(items, ["work", "urgent"])
        assert [i["id"] for i in result] == [1]

    def test_empty_required_returns_all(self):
        items = [{"id": 1, "notes": "x"}]
        assert filter_by_tags(items, []) == items
