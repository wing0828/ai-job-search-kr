#!/usr/bin/env python3
"""자기소개서 글자수 측정.

사용법:
    python charcount.py 파일.txt [--limit 700] [--basis with|without|bytes]
    echo "텍스트" | python charcount.py - --limit 500
    python charcount.py 자기소개서.md --sections

출력: 공백 포함 / 공백 제외 / UTF-8 바이트 / 2바이트 기준(한글 2, 영문·숫자 1).
--limit을 주면 --basis 기준으로 초과 여부와 남은 글자수를 보여준다.
--sections는 Markdown의 `##`/`###` 제목마다 따로 센다. 제목 줄과 `>` 메모 줄,
코드펜스 안의 내용은 세지 않는다. 제목에 "제한 1,000자", "1,000자 이내",
"최대: 500자" 같은 표기가 있으면 그 값을 제한으로 쓴다(`###`는 바로 위 `##`의
제한을 물려받는다). --limit을 주면 모든 문항에 그 값을 쓴다.
제한을 찾지 못한 문항이 있으면 경고하고 종료 코드 3을 낸다.
텍스트는 NFC로 정규화해서 센다(조합형 한글이 2~3배로 부풀지 않도록).
줄바꿈은 공백 포함 글자수에 1자로 센다(포털마다 다르므로 여유를 두는 것을 권장).

종료 코드: 0 통과, 1 제한 초과, 2 입력 오류, 3 제한을 알 수 없는 문항 있음.
"""
import argparse
import os
import re
import sys
import unicodedata
from typing import NamedTuple, Optional

LOW_FILL_PERCENT = 70
BASIS_LABELS = {"with": "공백 포함", "without": "공백 제외", "bytes": "2바이트 기준"}
HEADING_RE = re.compile(r"^(#{2,3})\s+(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# "제한/최대 N자"를 "N자 이내"보다 우선한다. 문항 원문 속 "500자 이내로 서술"보다
# 괄호의 "(제한 1,000자)"가 실제 입력창 제한이기 때문. 같은 종류가 여럿이면 마지막 값.
EXPLICIT_LIMIT_RE = re.compile(r"(?:제한|최대)\s*:?\s*(\d[\d,]*)\s*자")
WITHIN_LIMIT_RE = re.compile(r"(\d[\d,]*)\s*자\s*이내")


class Section(NamedTuple):
    title: str
    body: str
    limit: Optional[int]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def count(text: str) -> dict:
    normalized = normalize(text).strip("\n")
    without_space = sum(1 for ch in normalized if not ch.isspace())
    two_byte = sum(1 if ord(ch) < 128 else 2 for ch in normalized)
    return {
        "with": len(normalized),
        "without": without_space,
        "utf8": len(normalized.encode("utf-8")),
        "bytes": two_byte,
    }


def parse_limit(title: str) -> Optional[int]:
    for pattern in (EXPLICIT_LIMIT_RE, WITHIN_LIMIT_RE):
        matches = pattern.findall(title)
        if matches:
            return int(matches[-1].replace(",", ""))
    return None


def split_sections(markdown: str) -> list:
    """`##`/`###` 제목별 Section 목록. 본문이 빈 문항도 포함한다.

    코드펜스가 닫히지 않으면 그 아래 문항이 측정에서 빠지므로 ValueError.
    """
    sections = []
    title, limit, parent_limit, lines = None, None, None, []
    in_fence = False

    def flush() -> None:
        if title is not None:
            sections.append(Section(title, "\n".join(lines).strip(), limit))

    for line in normalize(markdown).split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = HEADING_RE.match(line)
        if heading:
            flush()
            level, title = heading.group(1), heading.group(2).strip()
            own_limit = parse_limit(title)
            if level == "##":
                parent_limit = own_limit
                limit = own_limit
            else:
                limit = own_limit if own_limit is not None else parent_limit
            lines = []
        elif title is not None and not line.lstrip().startswith(">"):
            lines.append(line)
    if in_fence:
        raise ValueError("코드펜스(```)가 닫히지 않아 그 아래 문항을 측정할 수 없음")
    flush()
    return sections


def report(text: str, limit: Optional[int], basis: str) -> bool:
    """측정값을 출력하고, 제한을 넘지 않으면 True."""
    c = count(text)
    print(f"공백 포함: {c['with']}자")
    print(f"공백 제외: {c['without']}자")
    print(f"UTF-8 바이트: {c['utf8']}")
    print(f"2바이트 기준: {c['bytes']}")
    if c["with"] == 0:
        print("경고: 본문이 비어 있음", file=sys.stderr)
    if limit is None:
        return True
    used = c[basis]
    label = BASIS_LABELS[basis]
    if used > limit:
        print(f"초과: {label} {used}/{limit} ({used - limit}자 넘침)")
        return False
    ratio = used / limit * 100 if limit else 0
    print(f"통과: {label} {used}/{limit} ({ratio:.0f}%, {limit - used}자 남음)")
    if limit and ratio < LOW_FILL_PERCENT:
        print(f"  참고: 제한의 {LOW_FILL_PERCENT}% 미만이라 성의 없어 보일 수 있음. 보통 90% 이상 채운다"
              " (없는 내용으로 채우지 말고 사례의 행동·결과를 구체화).")
    return True


def read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def run_sections(text: str, cli_limit: Optional[int], basis: str) -> int:
    try:
        sections = split_sections(text)
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 2
    if not sections:
        print("측정할 문항이 없음: ## 또는 ### 제목이 필요함", file=sys.stderr)
        return 2
    all_ok, unknown, empty = True, [], []
    for section in sections:
        print(f"\n[{section.title}]")
        limit = cli_limit if cli_limit is not None else section.limit
        if limit is None:
            unknown.append(section.title)
        if not section.body:
            empty.append(section.title)
        all_ok = report(section.body, limit, basis) and all_ok
    if not all_ok:
        return 1
    if unknown:
        print(
            "경고: 제한을 찾지 못한 문항 → 제목에 '(제한 N자)'를 넣거나 --limit 지정: "
            + ", ".join(unknown),
            file=sys.stderr,
        )
    if empty:
        print("경고: 본문이 빈 문항: " + ", ".join(empty), file=sys.stderr)
    return 3 if unknown or empty else 0


def console_encoding(stream) -> str:
    """출력 인코딩. 셸마다 기대가 달라서 한 가지로 고정하면 한쪽에서 한글이 깨진다.
    - PYTHONIOENCODING을 지정했으면 그대로
    - Git Bash·WSL·맥/리눅스 터미널(MSYSTEM, TERM 있음) → UTF-8
    - PowerShell·cmd → 현재 인코딩(한국어 Windows는 cp949)이 한글을 쓸 수 있으면 그대로
    """
    current = stream.encoding or "utf-8"
    if os.environ.get("PYTHONIOENCODING"):
        return current
    if os.environ.get("MSYSTEM") or os.environ.get("TERM"):
        return "utf-8"
    try:
        "한글".encode(current)
        return current
    except (LookupError, UnicodeEncodeError):
        return "utf-8"


def main() -> int:
    parser = argparse.ArgumentParser(description="자기소개서 글자수 측정")
    parser.add_argument("path", help="텍스트 파일 경로, 표준입력은 -")
    parser.add_argument("--limit", type=int, help="글자수 제한")
    parser.add_argument(
        "--basis",
        choices=list(BASIS_LABELS),
        default="with",
        help="제한 기준: with=공백 포함(기본), without=공백 제외, bytes=2바이트 기준",
    )
    parser.add_argument(
        "--sections", action="store_true", help="Markdown ##/### 제목별로 따로 측정"
    )
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding=console_encoding(stream), errors="replace")
    if args.path == "-" and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    try:
        text = read_input(args.path)
    except (OSError, UnicodeDecodeError) as e:
        print(f"입력을 읽을 수 없음: {e}", file=sys.stderr)
        return 2

    if args.sections:
        return run_sections(text, args.limit, args.basis)
    return 0 if report(text, args.limit, args.basis) else 1


if __name__ == "__main__":
    sys.exit(main())
