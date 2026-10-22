#!/usr/bin/env python3
"""지원 현황(tracker.csv) 도구: 마감 임박 목록, 캘린더(.ics) 내보내기, HTML 현황판.

사용법:
    python tracker.py list applications/tracker.csv [--days 14]
    python tracker.py ics applications/tracker.csv --out 마감일.ics [--alarm-days 3]
    python tracker.py report applications/tracker.csv --out 현황판.html

tracker.csv 열: 회사,직무,공고URL,마감일,채용형태,상태,이력서파일,자소서파일,메모
마감일은 YYYY-MM-DD. "상시", "채용시 마감" 같은 값은 날짜 없는 공고로 따로 보여준다.
상태 순서: 작성중 → 지원완료 → 서류합격 → 필기합격 → 1차합격 → 최종합격 → 입사
           (종료: 불합격, 포기)
.ics 파일은 Google 캘린더·Outlook·iPhone 캘린더에서 '가져오기'로 등록한다.
"""
import argparse
import csv
import hashlib
import html
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Optional

STAGES = ["작성중", "지원완료", "서류합격", "필기합격", "1차합격", "최종합격", "입사"]
CLOSED = {"불합격", "포기", "입사", "최종합격"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load(path: str) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in list(row):
            row[key] = (row[key] or "").strip()
    return rows


def deadline_of(row: dict) -> Optional[date]:
    value = row.get("마감일", "")
    if not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def upcoming(rows: list, today: date, days: int) -> tuple:
    """(마감 임박, 날짜 없음, 마감 지났는데 아직 작성중)."""
    dated, undated, missed = [], [], []
    for row in rows:
        if row.get("상태", "") in CLOSED:
            continue
        due = deadline_of(row)
        if due is None:
            undated.append(row)
        elif due < today:
            if row.get("상태", "") == "작성중":
                missed.append(row)
        elif due <= today + timedelta(days=days):
            dated.append(((due - today).days, row))
    dated.sort(key=lambda x: x[0])
    return dated, undated, missed


def cmd_list(rows: list, today: date, days: int) -> str:
    dated, undated, missed = upcoming(rows, today, days)
    out = [f"## 마감 {days}일 이내 ({today.isoformat()} 기준)"]
    if missed:
        out = [f"## 마감 지남, 아직 작성중 → 상태를 '포기'로 바꾸거나 정리"] + \
              [f"- {r['마감일']} · {r.get('회사', '')} · {r.get('직무', '')}" for r in missed] + [""] + out
    if not dated:
        out.append("없음")
    for left, row in dated:
        flag = " ⚠ 아직 작성중" if row.get("상태") == "작성중" else ""
        out.append(f"- D-{left} {row['마감일']} · {row.get('회사', '')} · {row.get('직무', '')} "
                   f"· {row.get('상태', '')}{flag}")
    if undated:
        out.append("\n## 마감일 없음 (상시·채용시 마감 등, 조기 마감 주의)")
        out += [f"- {r.get('회사', '')} · {r.get('직무', '')} · {r.get('마감일') or '미확인'}" for r in undated]
    return "\n".join(out)


def ics_escape(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def event_uid(row: dict) -> str:
    """행 순서가 바뀌어도 같은 공고는 같은 UID(다시 가져오기 해도 중복 일정이 안 생김)."""
    key = "|".join(row.get(k, "") for k in ("회사", "직무", "공고URL"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + "@job-application-kr"


def fold(line: str, limit: int = 75) -> str:
    """RFC 5545: 75바이트가 넘는 줄은 CRLF + 공백으로 접는다(UTF-8 글자 중간에서 자르지 않음)."""
    out, current = [], ""
    for ch in line:
        width = len(current.encode("utf-8")) + len(ch.encode("utf-8"))
        if width > (limit if not out else limit - 1):
            out.append(current)
            current = ""
        current += ch
    out.append(current)
    return "\r\n ".join(out)


def cmd_ics(rows: list, alarm_days: int, now: datetime) -> str:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//job-application-kr//tracker//KO",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:지원 마감일"]
    for row in rows:
        due = deadline_of(row)
        if due is None or row.get("상태", "") in CLOSED:
            continue
        summary = f"[마감] {row.get('회사', '')} {row.get('직무', '')}".strip()
        desc = f"상태: {row.get('상태', '')}\n{row.get('공고URL', '')}"
        lines += ["BEGIN:VEVENT", f"UID:{event_uid(row)}",
                  f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
                  f"DTEND;VALUE=DATE:{(due + timedelta(days=1)).strftime('%Y%m%d')}",
                  f"SUMMARY:{ics_escape(summary)}", f"DESCRIPTION:{ics_escape(desc)}"]
        if alarm_days > 0:
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(summary)}",
                      f"TRIGGER:-P{alarm_days}D", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(ln) for ln in lines) + "\r\n"


def funnel(rows: list) -> list:
    """단계별로 그 단계 이상까지 간 건수.

    불합격은 어느 단계에서 떨어졌는지 상태만으로 알 수 없어 '지원완료'까지 간 것으로 센다.
    포기는 지원 전에 그만둔 경우가 많아 집계에서 뺀다(지원 수를 부풀리지 않도록).
    """
    reached = []
    for row in rows:
        status = row.get("상태", "")
        if status in STAGES:
            reached.append(STAGES.index(status))
        elif status == "불합격":
            reached.append(STAGES.index("지원완료"))
    return [(stage, sum(1 for r in reached if r >= i)) for i, stage in enumerate(STAGES)]


def cmd_report(rows: list, today: date) -> str:
    esc = html.escape
    counts = {}
    for row in rows:
        counts[row.get("상태", "") or "미기재"] = counts.get(row.get("상태", "") or "미기재", 0) + 1
    steps = funnel(rows)
    applied = dict(steps).get("지원완료", 0)
    funnel_rows = "".join(
        f"<tr><td>{esc(s)}</td><td>{n}</td><td>{(n / applied * 100):.0f}%</td></tr>" if applied and i >= 1
        else f"<tr><td>{esc(s)}</td><td>{n}</td><td>-</td></tr>"
        for i, (s, n) in enumerate(steps))
    body_rows = "".join(
        "<tr>" + "".join(f"<td>{esc(row.get(k, ''))}</td>" for k in ("회사", "직무", "마감일", "채용형태", "상태"))
        + (f"<td><a href=\"{esc(row['공고URL'])}\">공고</a></td>" if row.get("공고URL", "").startswith("http") else "<td></td>")
        + "</tr>" for row in sorted(rows, key=lambda r: r.get("마감일", "")))
    status_list = " · ".join(f"{esc(k)} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>지원 현황판</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d9;--accent:#2f5d50}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151614;--fg:#ecebe6;--muted:#a3a29b;--line:#2c2e2a;--accent:#8fc2b0}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 "Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
main{{max-width:960px;margin:0 auto;padding:32px 16px}}
h1{{font-size:28px;margin:0 0 4px}} .muted{{color:var(--muted)}}
table{{width:100%;border-collapse:collapse;margin:16px 0 32px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}
th{{font-weight:600;color:var(--muted);font-size:13px}} a{{color:var(--accent)}}
.wrap{{overflow-x:auto}}
</style></head><body><main>
<h1>지원 현황판</h1><p class="muted">{today.isoformat()} 기준 · 전체 {len(rows)}건 · {status_list}</p>
<h2>단계별 진행 (지원완료 대비)</h2><div class="wrap"><table><tr><th>단계</th><th>도달</th><th>비율</th></tr>{funnel_rows}</table></div>
<h2>전체 목록</h2><div class="wrap"><table><tr><th>회사</th><th>직무</th><th>마감일</th><th>채용형태</th><th>상태</th><th>링크</th></tr>{body_rows}</table></div>
<p class="muted">불합격은 도달 단계를 알 수 없어 '지원완료'까지 간 것으로 세고, 포기는 단계 집계에서 뺍니다.</p>
</main></body></html>
"""


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


def main(argv=None, today: Optional[date] = None, now: Optional[datetime] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding=console_encoding(stream), errors="replace")
    p = argparse.ArgumentParser(description="지원 현황 도구")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("list", "ics", "report"):
        s = sub.add_parser(name)
        s.add_argument("csv")
        if name == "list":
            s.add_argument("--days", type=int, default=14)
        else:
            s.add_argument("--out", required=True)
        if name == "ics":
            s.add_argument("--alarm-days", type=int, default=3)
    args = p.parse_args(argv)
    today = today or date.today()
    try:
        rows = load(args.csv)
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        print(f"입력을 읽을 수 없음: {e}", file=sys.stderr)
        return 2
    if args.cmd == "list":
        print(cmd_list(rows, today, args.days))
        return 0
    if args.cmd == "ics":
        content = cmd_ics(rows, args.alarm_days, now or datetime.now(timezone.utc))
        if "BEGIN:VEVENT" not in content:
            print("마감일이 있는 진행 중 공고가 없어 파일을 만들지 않음")
            return 0
    else:
        content = cmd_report(rows, today)
    newline = "" if args.cmd == "ics" else None
    with open(args.out, "w", encoding="utf-8", newline=newline) as f:
        f.write(content)
    print(f"저장: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
