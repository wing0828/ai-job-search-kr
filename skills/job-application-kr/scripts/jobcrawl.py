#!/usr/bin/env python3
"""채용 포털 검색 결과 크롤러 (개인 구직용, 표준 라이브러리만 사용).

사용법:
    python jobcrawl.py search "백엔드 개발자" [--site saramin,jobkorea] [--pages 1] [--json]
    python jobcrawl.py detail <URL> [<URL> ...] [--max-chars 6000]
    python jobcrawl.py robots <URL>

지키는 것:
- 요청 전에 robots.txt(RFC 9309)를 읽고, 금지 경로는 가져오지 않는다. robots.txt를
  읽을 수 없으면(404 제외) 금지로 본다. 리다이렉트도 한 단계씩 같은 검사를 거친다.
- 같은 호스트에 최소 3초 간격(Crawl-delay가 더 길면 그 값, 60초 초과면 그 사이트는
  건너뜀). 간격은 ~/.cache/job-application-kr/ 의 파일로 프로세스끼리 공유한다.
- 한 번 실행에 검색은 사이트당 최대 10페이지, 상세는 최대 20건.
- User-Agent에 도구 이름을 정직하게 밝힌다. 로그인이 필요한 페이지는 다루지 않는다.
robots.txt 준수가 이용약관·법 준수를 뜻하지는 않는다. 개인 구직 목적의 소량 조회에만 쓴다.

종료 코드: 0 성공, 1 robots.txt 금지, 2 네트워크·입력 오류, 3 응답은 왔는데 결과 0건(화면 구조 변경 의심).
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

USER_AGENT = "job-application-kr/1.0 (+https://github.com/wing0828/ai-job-search-kr; personal job search)"
UA_TOKEN = "job-application-kr"
MIN_DELAY_SECONDS = 3.0
MAX_CRAWL_DELAY = 60.0
MAX_PAGES = 10
MAX_DETAILS = 20
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 20
MAX_BYTES = 8 * 1024 * 1024
STATE_PATH = Path.home() / ".cache" / "job-application-kr" / "host-clock.json"
LOCK_STALE_SECONDS = 180
PATH_SAFE = "/?=&*$:@!,;~+"


# ---------------------------------------------------------------- robots.txt

def normalize_path(path: str) -> str:
    """퍼센트 인코딩을 한 가지 형태로 맞춘다(/검색 과 /%EA%B2%80%EC%83%89 를 같게)."""
    return urllib.parse.quote(urllib.parse.unquote(path), safe=PATH_SAFE)


def parse_robots(text: str) -> list:
    """robots.txt를 [(user_agents, [(allow, pattern)])] 그룹 목록으로 파싱한다.

    빈 줄은 그룹을 끝내지 않는다. 규칙 뒤에 User-agent가 다시 나오면 새 그룹이다.
    값이 빈 User-agent 줄은 무시한다.
    """
    groups, agents, rules, seen_rule = [], [], [], False
    for raw in text.lstrip("﻿").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower().lstrip("﻿")
        if key == "user-agent":
            if seen_rule:
                groups.append((agents, rules))
                agents, rules, seen_rule = [], [], False
            if value:
                agents.append(value.split("/", 1)[0].strip().lower())  # "name/1.0" → "name"
        elif key in ("allow", "disallow") and agents:
            seen_rule = True
            if value:
                rules.append((key == "allow", value))
        elif key == "crawl-delay" and agents:
            seen_rule = True
            rules.append(("delay", value))
    if agents:
        groups.append((agents, rules))
    return groups


def _select_rules(groups: list, ua_token: str) -> list:
    """제품 토큰과 정확히 같은 그룹들을 합친다. 없으면 '*' 그룹들을 합친다(RFC 9309 2.2.1)."""
    token = ua_token.lower()
    named = [r for agents, rules in groups if token in agents for r in rules]
    if named:
        return named
    return [r for agents, rules in groups if "*" in agents for r in rules]


def _pattern_regex(pattern: str) -> re.Pattern:
    anchored = pattern.endswith("$")
    body = re.escape(normalize_path(pattern.rstrip("$"))).replace(r"\*", ".*")
    return re.compile(body + ("$" if anchored else ""))


def is_allowed(groups: list, path: str, ua_token: str = UA_TOKEN) -> bool:
    """가장 긴 일치 규칙이 이긴다. 길이가 같으면 금지가 이긴다."""
    best_len, allowed = -1, True
    target = normalize_path(path)
    for allow, pattern in _select_rules(groups, ua_token):
        if allow == "delay":
            continue
        if _pattern_regex(pattern).match(target):
            length = len(normalize_path(pattern))
            if length > best_len or (length == best_len and not allow):
                best_len, allowed = length, allow
    return allowed


def crawl_delay(groups: list, ua_token: str = UA_TOKEN) -> float:
    values = []
    for kind, value in _select_rules(groups, ua_token):
        if kind == "delay":
            try:
                values.append(float(value))
            except ValueError:
                continue
    return max(values, default=0.0)


# ---------------------------------------------------------------- host clock

class HostClock:
    """호스트별 마지막 요청 시각. state_path가 있으면 파일 잠금으로 프로세스끼리 공유한다."""

    def __init__(self, state_path: Optional[Path], sleep=time.sleep, clock=time.time):
        self._path, self._sleep, self._clock = state_path, sleep, clock
        self._memory = {}

    def wait(self, host: str, delay: float) -> None:
        """잠금 안에서는 다음 요청 시각을 예약만 하고, 잠금을 푼 뒤에 기다린다."""
        if self._path is None:
            wait_for = self._reserve(self._memory, host, delay)
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lock = self._path.with_suffix(".lock")
            self._acquire(lock)
            try:
                state = self._read()
                wait_for = self._reserve(state, host, delay)
                tmp = self._path.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_text(json.dumps(state), encoding="utf-8")
                os.replace(tmp, self._path)
            finally:
                lock.unlink(missing_ok=True)
        if wait_for > 0:
            self._sleep(wait_for)

    def _reserve(self, state: dict, host: str, delay: float) -> float:
        now = self._clock()
        last = state.get(host)
        slot = now if last is None else max(now, last + delay)
        state[host] = slot
        return slot - now

    def _read(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _acquire(self, lock: Path) -> None:
        deadline = time.time() + LOCK_STALE_SECONDS
        while True:
            try:
                os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                        lock.unlink(missing_ok=True)
                        continue
                except OSError:
                    continue
                if time.time() > deadline:
                    raise TimeoutError(f"다른 실행이 잠금을 오래 잡고 있음: {lock}")
                time.sleep(0.2)


# ---------------------------------------------------------------- fetching

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_get(url: str) -> tuple:
    """(status, charset, body, location). 리다이렉트는 따라가지 않는다."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"})
    try:
        with _OPENER.open(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read(MAX_BYTES + 1)
            return resp.status, resp.headers.get_content_charset(), body[:MAX_BYTES], None
    except urllib.error.HTTPError as e:
        return e.code, None, b"", e.headers.get("Location") if e.headers else None


class PoliteFetcher:
    """robots.txt 확인, 리다이렉트 단계별 재검사, 호스트별 요청 간격을 지키는 HTTP GET."""

    def __init__(self, opener=None, sleep=time.sleep, clock=time.time,
                 state_path: Optional[Path] = STATE_PATH):
        self._open = opener or http_get
        self._clock = HostClock(state_path, sleep, clock)
        self._robots, self.robots_errors = {}, {}

    def robots(self, url: str) -> Optional[list]:
        """그룹 목록, 또는 읽을 수 없으면 None(=금지로 취급)."""
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc.lower()
        if host in self._robots:
            return self._robots[host]
        target = f"{parts.scheme}://{parts.netloc}/robots.txt"
        result = None
        try:
            for _ in range(MAX_REDIRECTS + 1):
                if urllib.parse.urlsplit(target).scheme not in ("http", "https"):
                    break
                self._clock.wait(urllib.parse.urlsplit(target).netloc.lower(), MIN_DELAY_SECONDS)
                status, charset, body, location = self._open(target)
                if status in (301, 302, 303, 307, 308) and location:
                    target = urllib.parse.urljoin(target, location)
                    continue
                if status == 200:
                    result = parse_robots(body.decode(charset or "utf-8-sig", "replace"))
                elif status in (404, 410):
                    result = []
                break
        except (OSError, TimeoutError) as e:
            self.robots_errors[host] = str(e)
        self._robots[host] = result
        return result

    def check(self, url: str) -> tuple:
        groups = self.robots(url)
        host = urllib.parse.urlsplit(url).netloc.lower()
        if groups is None:
            if host in self.robots_errors:
                return False, f"robots.txt 요청 실패({self.robots_errors[host]}) → 금지로 간주"
            return False, "robots.txt를 읽을 수 없음 → 금지로 간주"
        parts = urllib.parse.urlsplit(url)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        if not is_allowed(groups, path or "/"):
            return False, "robots.txt가 이 경로를 금지함"
        if crawl_delay(groups) > MAX_CRAWL_DELAY:
            return False, f"Crawl-delay {crawl_delay(groups):.0f}초가 상한({MAX_CRAWL_DELAY:.0f}초)을 넘어 건너뜀"
        return True, "허용"

    def get(self, url: str) -> str:
        for _ in range(MAX_REDIRECTS + 1):
            if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
                raise PermissionError(f"http(s)가 아닌 주소는 가져오지 않음: {url}")
            ok, reason = self.check(url)
            if not ok:
                raise PermissionError(f"{reason}: {url}")
            host = urllib.parse.urlsplit(url).netloc.lower()
            self._clock.wait(host, max(MIN_DELAY_SECONDS, crawl_delay(self._robots.get(host) or [])))
            status, charset, body, location = self._open(url)
            if status in (301, 302, 303, 307, 308) and location:
                url = urllib.parse.urljoin(url, location)
                continue
            if status != 200:
                raise ConnectionError(f"HTTP {status}: {url}")
            return decode(body, charset)
        raise ConnectionError(f"리다이렉트가 {MAX_REDIRECTS}번을 넘음: {url}")


def decode(body: bytes, charset: Optional[str]) -> str:
    candidates = [charset] if charset else []
    meta = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', body[:4096])
    if meta:
        candidates.append(meta.group(1).decode("ascii"))
    candidates += ["utf-8", "cp949"]
    for enc in candidates:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


# ---------------------------------------------------------------- parsing

def clean(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_deadline(raw: str, today: date) -> str:
    """'~ 12/19(금)', '오늘마감', '내일마감' → YYYY-MM-DD. 그 밖은 원문 그대로."""
    text = raw.strip()
    if "오늘마감" in text.replace(" ", ""):
        return today.isoformat()
    if "내일마감" in text.replace(" ", ""):
        return (today + timedelta(days=1)).isoformat()
    m = re.search(r"(\d{1,2})/(\d{1,2})", text)
    if not m:
        return text
    month, day = int(m.group(1)), int(m.group(2))
    year = today.year + (1 if month < today.month - 1 else 0)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return text


EMPLOYMENT_WORDS = ("정규직", "계약직", "인턴", "파견", "프리랜서", "아르바이트", "위촉직", "전환형")


def classify_conditions(items: list) -> dict:
    out = {"career": "", "education": "", "employment": "", "extra": []}
    for item in items:
        if not out["career"] and re.search(r"신입|경력", item):
            out["career"] = item
        elif not out["education"] and re.search(r"학력|졸|대졸|고졸|석사|박사", item):
            out["education"] = item
        elif not out["employment"] and any(w in item for w in EMPLOYMENT_WORDS):
            out["employment"] = item
        else:
            out["extra"].append(item)
    return out


def parse_saramin(page: str, today: date) -> list:
    jobs = []
    for block in page.split('<div class="item_recruit"')[1:]:
        rec = re.search(r'^\s*value="(\d+)"', block)
        title = re.search(r'class="job_tit">\s*<a[^>]*title="([^"]*)"', block)
        corp = re.search(r'class="corp_name">\s*<a[^>]*>(.*?)</a>', block, re.S)
        if not (rec and title and corp):
            continue
        cond = re.search(r'class="job_condition">(.*?)</div>', block, re.S)
        spans = [clean(s) for s in re.findall(r"<span>(.*?)</span>", cond.group(1), re.S)] if cond else []
        when = re.search(r'<span class="date">(.*?)</span>', block, re.S)
        info = classify_conditions(spans[1:])
        jobs.append({
            "site": "saramin",
            "title": html.unescape(title.group(1)).strip(),
            "company": clean(corp.group(1)),
            "location": spans[0] if spans else "",
            "career": info["career"], "education": info["education"],
            "employment": info["employment"],
            "deadline": normalize_deadline(clean(when.group(1)), today) if when else "",
            "url": f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={rec.group(1)}",
            "is_ad": "paid_y" in block[:400],
        })
    return jobs


def parse_jobkorea(page: str, today: date) -> list:
    jobs, seen = [], set()
    for block in page.split('data-sentry-component="CardJob"')[1:]:
        link = re.search(r'href="https://www\.jobkorea\.co\.kr/Recruit/GI_Read/(\d+)', block)
        title = re.search(r'data-sentry-component="Title"[^>]*>\s*<span[^>]*>(.*?)</span>', block, re.S)
        corp = re.search(r'<span class="truncate text-gray700 text-typo-b2-16">(.*?)</span>', block, re.S)
        if not (link and title and corp) or link.group(1) in seen:
            continue
        seen.add(link.group(1))
        chips = [clean(c) for c in re.findall(
            r'data-sentry-component="GrayChip".*?<span class="truncate[^"]*">(.*?)</span>', block, re.S)]
        conds = [clean(c) for c in re.findall(r'text-gray700 text-typo-c1-13">(.*?)</span>', block, re.S)]
        info = classify_conditions([c for c in conds if c and c != "•"])
        jobs.append({
            "site": "jobkorea",
            "title": clean(title.group(1)),
            "company": clean(corp.group(1)),
            "location": chips[0] if chips else "",
            "career": info["career"], "education": info["education"],
            "employment": info["employment"],
            "deadline": "",
            "url": f"https://www.jobkorea.co.kr/Recruit/GI_Read/{link.group(1)}",
            "is_ad": ">AD<" in block,
        })
    return jobs


SITES = {
    "saramin": ("https://www.saramin.co.kr/zf_user/search/recruit?searchword={q}"
                "&recruitPage={page}&recruitPageCount=40", parse_saramin),
    "jobkorea": ("https://www.jobkorea.co.kr/Search/?stext={q}&tabType=recruit&Page_No={page}",
                 parse_jobkorea),
}


# ---------------------------------------------------------------- commands

def search(fetcher: PoliteFetcher, keyword: str, sites: list, pages: int, today: date) -> tuple:
    """(공고 목록, 오류 목록, 상태). 상태: blocked=robots 금지 사이트 수, empty=첫 쪽부터 0건인 사이트 수."""
    jobs, errors, seen = [], [], set()
    status = {"blocked": 0, "empty": 0, "network": 0}
    for site in sites:
        template, parser = SITES[site]
        for page in range(1, pages + 1):
            url = template.format(q=urllib.parse.quote(keyword), page=page)
            try:
                found = parser(fetcher.get(url), today)
            except PermissionError as e:
                errors.append(f"{site}: {e}")
                status["blocked"] += 1
                break
            except (ConnectionError, OSError) as e:
                errors.append(f"{site} {page}쪽: {e}")
                status["network"] += 1
                break
            if not found:
                if page == 1:
                    errors.append(f"{site}: 응답은 왔지만 0건 (검색 결과 없음 또는 화면 구조 변경 의심)")
                    status["empty"] += 1
                break
            for job in found:
                key = (job["company"], job["title"])
                if key not in seen:
                    seen.add(key)
                    jobs.append(job)
    return jobs, errors, status


def search_exit_code(jobs: list, status: dict, site_count: int) -> int:
    if jobs:
        return 0
    if status["blocked"] == site_count:
        return 1
    if status["network"]:
        return 2
    return 3


def to_table(jobs: list) -> str:
    rows = ["| # | 사이트 | 회사 | 공고 | 지역 | 경력 | 마감 | 광고 | URL |",
            "|---|---|---|---|---|---|---|---|---|"]
    for i, j in enumerate(jobs, 1):
        cells = [str(i), j["site"], j["company"], j["title"], j["location"], j["career"],
                 j["deadline"] or "미확인", "AD" if j["is_ad"] else "", j["url"]]
        rows.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(rows)


def detail_url(url: str) -> str:
    """사람인 공고 URL은 본문이 별도로 로드되므로 본문 전용 경로로 바꾼다."""
    parts = urllib.parse.urlsplit(url)
    if parts.netloc.endswith("saramin.co.kr") and parts.path.rstrip("/").endswith("/jobs/relay/view"):
        rec = urllib.parse.parse_qs(parts.query).get("rec_idx")
        if rec:
            return f"https://www.saramin.co.kr/zf_user/jobs/relay/view-detail?rec_idx={rec[0]}&rec_seq=0"
    return url


def extract_text(page: str) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr)>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines())
    return "\n".join(ln for ln in lines if ln)


def run_detail(fetcher: PoliteFetcher, urls: list, max_chars: int) -> int:
    worst = 0
    for url in urls:
        print(f"\n===== {url}")
        try:
            print(extract_text(fetcher.get(detail_url(url)))[:max_chars])
        except PermissionError as e:
            print(f"가져오지 않음: {e}", file=sys.stderr)
            worst = max(worst, 1)
        except (ConnectionError, OSError) as e:
            print(f"오류: {e}", file=sys.stderr)
            worst = 2
    return worst


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="채용 포털 검색 결과 크롤러 (robots.txt 준수)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="키워드로 공고 목록 수집")
    s.add_argument("keyword")
    s.add_argument("--site", default="saramin,jobkorea", help="saramin,jobkorea 중 쉼표로")
    s.add_argument("--pages", type=int, default=1, help=f"사이트당 페이지 수 (최대 {MAX_PAGES})")
    s.add_argument("--exclude-ads", action="store_true", help="광고(AD) 표시 공고 제외")
    s.add_argument("--json", action="store_true", help="JSON으로 출력")
    r = sub.add_parser("robots", help="URL이 robots.txt상 허용되는지 확인")
    r.add_argument("url")
    d = sub.add_parser("detail", help=f"공고 상세 본문 텍스트 추출 (한 번에 최대 {MAX_DETAILS}건, 순차)")
    d.add_argument("urls", nargs="+")
    d.add_argument("--max-chars", type=int, default=6000)
    return p


def main(argv: Optional[list] = None, fetcher: Optional[PoliteFetcher] = None,
         today: Optional[date] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    fetcher = fetcher or PoliteFetcher()
    today = today or date.today()

    if args.cmd == "robots":
        ok, reason = fetcher.check(args.url)
        print(f"{'허용' if ok else '금지'}: {reason}")
        if not ok and urllib.parse.urlsplit(args.url).netloc.lower() in fetcher.robots_errors:
            return 2
        return 0 if ok else 1

    if args.cmd == "detail":
        if len(args.urls) > MAX_DETAILS:
            print(f"입력 오류: 상세는 한 번에 최대 {MAX_DETAILS}건", file=sys.stderr)
            return 2
        return run_detail(fetcher, args.urls, args.max_chars)

    sites = [s.strip() for s in args.site.split(",") if s.strip()]
    unknown = [s for s in sites if s not in SITES]
    if unknown or not sites or not 1 <= args.pages <= MAX_PAGES:
        print(f"입력 오류: 사이트 {unknown or '-'}, 페이지는 1~{MAX_PAGES}", file=sys.stderr)
        return 2
    jobs, errors, status = search(fetcher, args.keyword, sites, args.pages, today)
    if args.exclude_ads:
        jobs = [j for j in jobs if not j["is_ad"]]
    print(json.dumps(jobs, ensure_ascii=False, indent=2) if args.json else to_table(jobs))
    for err in errors:
        print(f"경고: {err}", file=sys.stderr)
    return search_exit_code(jobs, status, len(sites))


if __name__ == "__main__":
    sys.exit(main())
