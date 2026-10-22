#!/usr/bin/env python3
"""제출 전 자동 검사: 블라인드 위반, 다른 회사명, 금지 표현, 문체.

사용법:
    python precheck.py 자기소개서.md 이력서.md [--blind] [--target 회사명]
                       [--tracker applications/tracker.csv] [--companies "A사,B사"]

규칙의 근거는 references/02-writing-style.md다.
- ERROR: 다른 회사명 잔존, 블라인드 채용에서 학교명·학교 이메일·사진
- WARN : 금지 표현, 블라인드 채용에서 학교 줄임말(○○대 졸업)·지역·가족·나이·성별 표현, 줄표·이모지
- INFO : 같은 어미 3연속, 80자 넘는 문장, 제출 파일 안의 내부 메모
`>` 메모 줄과 코드펜스는 문체 검사에서 빼고, 회사명·블라인드 검사에는 포함한다.

종료 코드: 0 ERROR 없음, 1 ERROR 있음, 2 입력 오류.
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from typing import NamedTuple

BANNED = {
    "귀사": "회사명을 직접 쓴다",
    "열정": "열정을 보여준 사례로 바꾼다",
    "성실함": "성실함이 드러나는 사례로 바꾼다",
    "책임감이 강한": "책임을 진 사례로 바꾼다",
    "소통을 잘하는": "조율한 사례로 바꾼다",
    "최선을 다하겠습니다": "구체적으로 할 일로 바꾼다",
    "뽑아주신다면": "삭제",
    "배우는 자세로": "무엇을 어떻게 배울지 쓴다",
    "누구보다": "비교 근거가 있는 수치로 바꾼다",
    "최고의 인재": "삭제",
    "어려서부터": "현재의 일하는 방식을 만든 사건 하나로 바꾼다",
    "글로벌 인재": "근거가 되는 경험으로 바꾼다",
    "시너지": "구체적 결과로 바꾼다",
}
FAMILY_RE = re.compile(r"부모님|아버지|어머니|형제|자매|장남|장녀|차남|차녀|외동|\d남 ?\d녀")
AGE_RE = re.compile(r"(?<!\d)\d{2}세(?!기|대)|\d{2,4}년생|만 ?\d{1,2}세")
GENDER_RE = re.compile(r"(?<![가-힣])(남성|여성|남자|여자)(?![가-힣])")
REGION_RE = re.compile(
    r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|충청|전북|전남|전라|경북|경남|경상|제주)"
    r"(특별시|광역시|도)?\s?(출신|에서 태어|토박이|에서 자라)")
# 학교명: "○○대학교/대학원/대학/고등학교" + 조사·띄어쓰기. 일반명사(일반대학원, 전문대학 등)는 제외.
SCHOOL_RE = re.compile(
    r"(?<![가-힣A-Za-z])([가-힣A-Za-z]{2,12})(대학교|대학원|대학|고등학교)"
    r"(?=에서|의|을|를|에|과|와|로|은|는|이며|이고|이었|도|졸업|재학|학부|출신|[\s,.)·/]|$)")
GENERIC_SCHOOL_STEMS = {"일반", "전문", "공과", "사이버", "지방", "단과", "경영", "공학", "의과", "인문",
                        "자연과학", "사회과학", "법학전문", "교육", "특수", "방송통신", "국공립", "사립",
                        "명문", "해외", "국내", "외국", "지역", "수도권", "주요", "희망", "목표",
                        "출신", "소속", "졸업", "협력", "참여", "협약", "해당", "지정", "거점", "연합",
                        "재학", "모교", "편입", "타", "각", "여러"}
# "○○대 졸업/에서" 같은 줄임말은 WARN. 부대·현대·세대·시대 같은 일반어는 제외.
SCHOOL_ABBR_RE = re.compile(r"(?<![가-힣])([가-힣]{1,4})대\s?(학부|재학|졸업|출신|동문|학생|학과|에서|의\s)")
ABBR_EXCLUDE = {"부", "현", "세", "시", "교", "근", "고", "상", "절", "최", "확", "무", "반", "기", "군", "해병", "특전", "연령"}
SCHOOL_KNOWN_RE = re.compile(r"(?<![A-Za-z가-힣])(KAIST|POSTECH|UNIST|DGIST|GIST|카이스트|포스텍|유니스트|디지스트|지스트)")
SCHOOL_EN_RE = re.compile(r"\b(University of [A-Z][A-Za-z]+|[A-Z][A-Za-z]+ (University|College|Institute of Technology))\b")
SCHOOL_MAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)*\.ac\.kr", re.I)
PHOTO_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b", re.I)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF]")
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]")
LONG_SENTENCE = 80


class Finding(NamedTuple):
    level: str
    line: int
    rule: str
    text: str


def iter_lines(text: str):
    """(줄번호, 줄, 문체검사대상 여부)."""
    in_fence = False
    for no, line in enumerate(text.splitlines(), 1):
        if re.match(r"^\s*(```|~~~)", line):
            in_fence = not in_fence
            yield no, line, False
            continue
        prose = not in_fence and not line.lstrip().startswith((">", "#", "|"))
        yield no, line, prose


def _inside_target(line: str, start: int, end: int, target: str) -> bool:
    if not target:
        return False
    for m in re.finditer(re.escape(target), line):
        if m.start() <= start and end <= m.end():
            return True
    return False


def _name_pattern(name: str) -> re.Pattern:
    """2글자 이하 이름(SK, LG 등)은 다른 단어 속에서 잡히지 않게 경계를 요구한다."""
    if len(name) <= 2:
        return re.compile(r"(?<![가-힣A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])")
    return re.compile(re.escape(name))


def check_companies(lines: list, companies: list, target: str = "") -> list:
    out = []
    for no, line, _ in lines:
        for name in companies:
            if not name:
                continue
            for m in _name_pattern(name).finditer(line):
                if not _inside_target(line, m.start(), m.end(), target):
                    out.append(Finding("ERROR", no, "다른 회사명", name))
                    break
    return out


def find_schools(line: str) -> list:
    """(level, 찾은 문자열). 확실한 학교명은 ERROR, 줄임말(○○대 졸업 등)은 WARN."""
    found = []
    for m in SCHOOL_RE.finditer(line):
        if m.group(1) not in GENERIC_SCHOOL_STEMS:
            found.append(("ERROR", m.group(1) + m.group(2)))
    for pattern in (SCHOOL_KNOWN_RE, SCHOOL_EN_RE):
        found += [("ERROR", m.group(0)) for m in pattern.finditer(line)]
    found += [("WARN", m.group(0).strip()) for m in SCHOOL_ABBR_RE.finditer(line)
              if m.group(1) not in ABBR_EXCLUDE and m.group(1) not in GENERIC_SCHOOL_STEMS]
    return found


def check_blind(lines: list) -> list:
    out = []
    rules = [("ERROR", "블라인드: 학교 이메일", SCHOOL_MAIL_RE), ("ERROR", "블라인드: 사진", PHOTO_RE),
             ("WARN", "블라인드: 출신지", REGION_RE), ("WARN", "블라인드: 가족", FAMILY_RE),
             ("WARN", "블라인드: 나이", AGE_RE), ("WARN", "블라인드: 성별", GENDER_RE)]
    for no, line, _ in lines:
        out += [Finding(level, no, "블라인드: 학교명", text) for level, text in find_schools(line)]
        for level, rule, pattern in rules:
            m = pattern.search(line)
            if m:
                out.append(Finding(level, no, rule, m.group(0)))
    return out


def ending(sentence: str) -> str:
    """마지막 어절의 끝 4글자. '습니다'체 공통 꼬리 대신 '했습니다'/'였습니다'를 구분한다."""
    words = sentence.strip().rstrip(".!?").split()
    return words[-1][-4:] if words else ""


def check_style(lines: list) -> list:
    out, run_end, run_len, run_start = [], None, 0, 0
    in_memo = False
    for no, line, prose in lines:
        is_memo = line.lstrip().startswith(">")
        if is_memo and not in_memo:
            out.append(Finding("INFO", no, "내부 메모", "제출 전 삭제"))
        in_memo = is_memo
        if not prose:
            continue
        for word, fix in BANNED.items():
            if word in line:
                out.append(Finding("WARN", no, "금지 표현", f"{word} → {fix}"))
        if "—" in line or "――" in line:
            out.append(Finding("WARN", no, "줄표", "쉼표나 마침표로 바꾼다"))
        if EMOJI_RE.search(line):
            out.append(Finding("WARN", no, "이모지", "삭제"))
        for sent in SENTENCE_RE.findall(line):
            if len(sent.strip()) > LONG_SENTENCE:
                out.append(Finding("INFO", no, "긴 문장", f"{len(sent.strip())}자: {sent.strip()[:30]}…"))
            end = ending(sent)
            if end and end == run_end:
                run_len += 1
            else:
                run_end, run_len, run_start = end, 1, no
            if run_len == 3:
                out.append(Finding("INFO", run_start, "어미 반복", f"'{end}' 3번 연속"))
    return out


def tracker_companies(path: str, target: str) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        names = {(row.get("회사") or "").strip() for row in csv.DictReader(f)}
    return sorted(n for n in names if n and n != target)


def run(path: str, blind: bool, companies: list, target: str = "") -> list:
    with open(path, encoding="utf-8-sig") as f:
        text = unicodedata.normalize("NFC", f.read())
    lines = list(iter_lines(text))
    findings = check_companies(lines, companies, target)
    if blind:
        findings += check_blind(lines)
    findings += check_style(lines)
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    return sorted(findings, key=lambda f: (order[f.level], f.line))


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


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding=console_encoding(stream), errors="replace")
    p = argparse.ArgumentParser(description="자소서·이력서 제출 전 자동 검사")
    p.add_argument("files", nargs="+")
    p.add_argument("--blind", action="store_true", help="블라인드 채용 규칙 적용")
    p.add_argument("--target", default="", help="지원하는 회사명 (다른 회사명 검사에서 제외)")
    p.add_argument("--tracker", help="tracker.csv 경로 (이전 지원 회사명을 읽음)")
    p.add_argument("--companies", default="", help="추가로 검사할 회사명, 쉼표로 구분")
    args = p.parse_args(argv)

    companies = [c.strip() for c in args.companies.split(",") if c.strip() and c.strip() != args.target]
    try:
        if args.tracker:
            companies = sorted(set(companies) | set(tracker_companies(args.tracker, args.target)))
        results = {path: run(path, args.blind, companies, args.target) for path in args.files}
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        print(f"입력을 읽을 수 없음: {e}", file=sys.stderr)
        return 2

    errors = 0
    for path, findings in results.items():
        print(f"\n## {path}")
        if not findings:
            print("문제 없음")
        for f in findings:
            print(f"{f.line:>4}줄 [{f.level}] {f.rule}: {f.text}")
        errors += sum(1 for f in findings if f.level == "ERROR")
    counts = {lvl: sum(f.level == lvl for fs in results.values() for f in fs) for lvl in ("ERROR", "WARN", "INFO")}
    print(f"\n합계: ERROR {counts['ERROR']} · WARN {counts['WARN']} · INFO {counts['INFO']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
