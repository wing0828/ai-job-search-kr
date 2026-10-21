#!/usr/bin/env python3
"""자기소개서 글자수 측정.

사용법:
    python charcount.py 파일.txt [--limit 700] [--basis with|without|bytes]
    echo "텍스트" | python charcount.py - --limit 500

출력: 공백 포함 / 공백 제외 / UTF-8 바이트 / 2바이트 기준(한글 2, 영문·숫자 1).
--limit을 주면 --basis 기준으로 초과 여부와 남은 글자수를 보여준다.
줄바꿈은 공백 포함 글자수에 1자로 센다(포털마다 다르므로 여유를 두는 것을 권장).
"""
import argparse
import sys


def count(text: str) -> dict:
    # Windows 줄바꿈(\r\n)은 한 글자로 센다.
    normalized = text.replace("\r\n", "\n").rstrip("\n")
    without_space = sum(1 for ch in normalized if not ch.isspace())
    two_byte = sum(1 if ord(ch) < 128 else 2 for ch in normalized)
    return {
        "with": len(normalized),
        "without": without_space,
        "utf8": len(normalized.encode("utf-8")),
        "bytes": two_byte,
    }


def read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="자기소개서 글자수 측정")
    parser.add_argument("path", help="텍스트 파일 경로, 표준입력은 -")
    parser.add_argument("--limit", type=int, help="글자수 제한")
    parser.add_argument(
        "--basis",
        choices=["with", "without", "bytes"],
        default="with",
        help="제한 기준: with=공백 포함(기본), without=공백 제외, bytes=2바이트 기준",
    )
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if args.path == "-" and hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    try:
        text = read_input(args.path)
    except (OSError, UnicodeDecodeError) as e:
        print(f"입력을 읽을 수 없음: {e}", file=sys.stderr)
        return 2

    c = count(text)
    print(f"공백 포함: {c['with']}자")
    print(f"공백 제외: {c['without']}자")
    print(f"UTF-8 바이트: {c['utf8']}")
    print(f"2바이트 기준: {c['bytes']}")

    if args.limit is None:
        return 0
    used = c[args.basis]
    label = {"with": "공백 포함", "without": "공백 제외", "bytes": "2바이트 기준"}[args.basis]
    ratio = used / args.limit * 100 if args.limit else 0
    if used > args.limit:
        print(f"초과: {label} {used}/{args.limit} ({used - args.limit}자 넘침)")
        return 1
    print(f"통과: {label} {used}/{args.limit} ({ratio:.0f}%, {args.limit - used}자 남음)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
