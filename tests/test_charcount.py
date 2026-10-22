import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/job-application-kr/scripts/charcount.py"
spec = importlib.util.spec_from_file_location("charcount", SCRIPT)
charcount = importlib.util.module_from_spec(spec)
spec.loader.exec_module(charcount)


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["charcount.py", *argv])
    return charcount.main()


def test_counts_with_and_without_spaces_and_bytes():
    c = charcount.count("가나 다a\r\n라\n")
    assert c == {"with": 7, "without": 5, "utf8": 15, "bytes": 11}


def test_trailing_and_leading_blank_lines_are_ignored():
    assert charcount.count("\n\n가나\n\n")["with"] == 2


def test_limit_pass_and_fail_exit_codes(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("가나다", encoding="utf-8")
    assert run(monkeypatch, str(f), "--limit", "3") == 0
    assert run(monkeypatch, str(f), "--limit", "2") == 1


def test_bytes_basis(tmp_path, monkeypatch):
    f = tmp_path / "a.txt"
    f.write_text("한글 abc", encoding="utf-8")
    assert run(monkeypatch, str(f), "--limit", "8", "--basis", "bytes") == 0
    assert run(monkeypatch, str(f), "--limit", "7", "--basis", "bytes") == 1


def test_missing_file_returns_2(monkeypatch):
    assert run(monkeypatch, "does-not-exist.txt") == 2


def test_utf8_bom_is_not_counted(tmp_path):
    f = tmp_path / "bom.txt"
    f.write_bytes("﻿가나".encode("utf-8"))
    assert charcount.count(charcount.read_input(str(f)))["with"] == 2


MARKDOWN = """# 제목은 세지 않음
작성일 줄도 세지 않음

## 1. 지원동기 (제한 1,000자)
[소제목]
본문입니다.

> 메모는 세지 않음

### 축약안
짧은 본문

## 2. 자유 문항
제한 없는 본문
"""


def test_split_sections_titles_limits_and_memo_exclusion():
    sections = charcount.split_sections(MARKDOWN)
    assert [s.title for s in sections] == ["1. 지원동기 (제한 1,000자)", "축약안", "2. 자유 문항"]
    assert sections[0].body == "[소제목]\n본문입니다."
    assert sections[0].limit == 1000
    assert sections[1].limit == 1000  # ### inherits the parent ## limit
    assert sections[2].limit is None


def test_sections_mode_fails_when_any_section_over_limit(tmp_path, monkeypatch):
    f = tmp_path / "s.md"
    f.write_text("## 1 (제한 3자)\n가나다라\n\n## 2 (제한 10자)\n가나\n", encoding="utf-8")
    assert run(monkeypatch, str(f), "--sections") == 1


def test_sections_mode_cli_limit_overrides_heading(tmp_path, monkeypatch):
    f = tmp_path / "s.md"
    f.write_text("## 1 (제한 3자)\n가나다라\n", encoding="utf-8")
    assert run(monkeypatch, str(f), "--sections", "--limit", "10") == 0


def test_sections_mode_without_headings_returns_2(tmp_path, monkeypatch):
    f = tmp_path / "s.md"
    f.write_text("제목 없는 본문", encoding="utf-8")
    assert run(monkeypatch, str(f), "--sections") == 2


@pytest.mark.parametrize(
    "title, expected",
    [
        ("1. 지원동기 (제한 1,000자)", 1000),
        ("1. 지원동기 (1,000자 이내)", 1000),
        ("1. 지원동기 (제한: 5자)", 5),
        ("1. 지원동기 (최대 700자)", 700),
        ("1. 경험을 500자 이내로 서술 (제한 1,000자)", 1000),
        ("1. 500자 이내로 서술 (1,000자 이내)", 1000),
        ("1. 지원동기 (제한 ,자)", None),
        ("1. 지원동기", None),
    ],
)
def test_parse_limit_variants(title, expected):
    assert charcount.parse_limit(title) == expected


def test_nfd_hangul_counts_as_composed():
    nfd = "가나"  # 가나 in conjoining jamo
    assert charcount.count(nfd)["with"] == 2


def test_lone_carriage_return_is_one_char():
    assert charcount.count("가\r나")["with"] == 3


def test_code_fence_content_is_not_split_or_counted():
    md = "## 1 (제한 10자)\n본문\n```\n## 가짜 제목\n코드\n```\n"
    sections = charcount.split_sections(md)
    assert [s.title for s in sections] == ["1 (제한 10자)"]
    assert sections[0].body == "본문"


def test_sections_without_limit_return_3(tmp_path, monkeypatch):
    f = tmp_path / "s.md"
    f.write_text("## 1. 제한 표기 없음\n가나\n", encoding="utf-8")
    assert run(monkeypatch, str(f), "--sections") == 3


def test_empty_section_is_reported_with_exit_3(tmp_path, monkeypatch):
    f = tmp_path / "s.md"
    f.write_text("## 1 (제한 10자)\n가나\n\n## 2 (제한 10자)\n\n> 메모만\n", encoding="utf-8")
    assert [s.body for s in charcount.split_sections(f.read_text(encoding="utf-8"))] == ["가나", ""]
    assert run(monkeypatch, str(f), "--sections") == 3


def test_unclosed_fence_returns_2(tmp_path, monkeypatch):
    f = tmp_path / "s.md"
    f.write_text("## 1 (제한 10자)\n가나\n```\n## 2 (제한 1자)\n가나다\n", encoding="utf-8")
    assert run(monkeypatch, str(f), "--sections") == 2


@pytest.mark.parametrize("limit", [0])
def test_zero_limit_does_not_divide_by_zero(tmp_path, monkeypatch, limit):
    f = tmp_path / "e.txt"
    f.write_text("", encoding="utf-8")
    assert run(monkeypatch, str(f), "--limit", str(limit)) == 0
