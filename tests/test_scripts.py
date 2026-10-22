import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/job-application-kr/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


jobcrawl = load("jobcrawl")
precheck = load("precheck")
salary = load("salary")
tracker = load("tracker")
TODAY = date(2026, 10, 22)


# ------------------------------------------------------------ jobcrawl: robots

ROBOTS = """
User-agent: GPTBot
Disallow: /

User-agent: *

Disallow: /zf_user/recruit/view/
Disallow: /zf_user/jobs/view*innerCampaign=headhuntingView
Allow   : /zf_user/jobs/relay/recruit-view
Disallow: /private
Allow: /private/open$
Crawl-delay: 5
"""


@pytest.mark.parametrize("path, allowed", [
    ("/zf_user/search/recruit?searchword=a", True),
    ("/zf_user/recruit/view/123", False),
    ("/zf_user/jobs/view?x=1&innerCampaign=headhuntingView", False),
    ("/zf_user/jobs/relay/view?rec_idx=1", True),
    ("/private/x", False),
    ("/private/open", True),
    ("/private/open/more", False),
])
def test_robots_star_group_longest_match(path, allowed):
    groups = jobcrawl.parse_robots(ROBOTS)
    assert jobcrawl.is_allowed(groups, path) is allowed


def test_robots_named_group_wins_over_star():
    groups = jobcrawl.parse_robots("User-agent: job-application-kr\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert jobcrawl.is_allowed(groups, "/anything") is False


def test_robots_tie_goes_to_disallow():
    groups = jobcrawl.parse_robots("User-agent: *\nAllow: /a\nDisallow: /a\n")
    assert jobcrawl.is_allowed(groups, "/a/b") is False


def test_crawl_delay_read_from_group():
    assert jobcrawl.crawl_delay(jobcrawl.parse_robots(ROBOTS)) == 5.0


def test_robots_bom_does_not_fail_open():
    groups = jobcrawl.parse_robots("﻿User-agent: *\nDisallow: /\n")
    assert jobcrawl.is_allowed(groups, "/x") is False


def test_robots_empty_user_agent_line_is_ignored():
    groups = jobcrawl.parse_robots("User-agent:\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert jobcrawl.is_allowed(groups, "/x") is True


def test_robots_partial_token_does_not_match():
    groups = jobcrawl.parse_robots("User-agent: kr\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert jobcrawl.is_allowed(groups, "/x") is True


def test_robots_versioned_user_agent_matches_product_token():
    groups = jobcrawl.parse_robots("User-agent: job-application-kr/1.0\nDisallow: /\n\nUser-agent: *\nAllow: /\n")
    assert jobcrawl.is_allowed(groups, "/x") is False


def test_redirect_to_non_http_scheme_is_refused():
    fetcher, net, _ = make_fetcher({"https://x.kr/a": (302, None, b"", "file:///etc/passwd")})
    with pytest.raises(PermissionError):
        fetcher.get("https://x.kr/a")
    assert not any(c.startswith("file:") for c in net.calls)


def test_robots_multiple_star_groups_are_merged():
    groups = jobcrawl.parse_robots("User-agent: *\nDisallow: /a\n\nUser-agent: Foo\nDisallow: /\n\nUser-agent: *\nDisallow: /b\n")
    assert jobcrawl.is_allowed(groups, "/b/1") is False and jobcrawl.is_allowed(groups, "/a") is False


def test_robots_percent_encoding_normalized():
    groups = jobcrawl.parse_robots("User-agent: *\nDisallow: /검색\n")
    assert jobcrawl.is_allowed(groups, "/%EA%B2%80%EC%83%89?q=1") is False


class FakeNet:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, url):
        self.calls.append(url)
        resp = self.responses.get(url, (404, None, b""))
        if isinstance(resp, Exception):
            raise resp
        return resp if len(resp) == 4 else (*resp, None)


class FakeClock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def time(self):
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def make_fetcher(responses):
    net, clock = FakeNet(responses), FakeClock()
    fetcher = jobcrawl.PoliteFetcher(opener=net, sleep=clock.sleep, clock=clock.time, state_path=None)
    return fetcher, net, clock.slept


def test_unreadable_robots_blocks_fetch():
    fetcher, net, _ = make_fetcher({"https://x.kr/robots.txt": (403, None, b"")})
    with pytest.raises(PermissionError):
        fetcher.get("https://x.kr/page")
    assert net.calls == ["https://x.kr/robots.txt"]


def test_robots_network_error_is_deny_and_robots_cmd_exits_2(capsys):
    fetcher, _, _ = make_fetcher({"https://x.kr/robots.txt": OSError("timeout")})
    assert jobcrawl.main(["robots", "https://x.kr/a"], fetcher=fetcher) == 2


def test_wait_uses_at_least_three_seconds_between_requests():
    fetcher, net, slept = make_fetcher({"https://x.kr/p": (200, "utf-8", "본문".encode())})
    assert fetcher.get("https://x.kr/p") == "본문"
    assert net.calls == ["https://x.kr/robots.txt", "https://x.kr/p"]
    assert slept and slept[0] == pytest.approx(3.0, abs=0.05)


def test_crawl_delay_longer_than_minimum_is_used():
    robots = b"User-agent: *\nCrawl-delay: 5\n"
    fetcher, _, slept = make_fetcher({"https://x.kr/robots.txt": (200, "utf-8", robots),
                                      "https://x.kr/p": (200, "utf-8", b"ok")})
    fetcher.get("https://x.kr/p")
    assert slept[-1] == pytest.approx(5.0, abs=0.05)


def test_excessive_crawl_delay_skips_site():
    fetcher, net, _ = make_fetcher({"https://x.kr/robots.txt": (200, "utf-8", b"User-agent: *\nCrawl-delay: 86400\n")})
    with pytest.raises(PermissionError):
        fetcher.get("https://x.kr/p")
    assert "https://x.kr/p" not in net.calls


def test_disallowed_path_never_requested():
    fetcher, net, _ = make_fetcher({"https://x.kr/robots.txt": (200, "utf-8", b"User-agent: *\nDisallow: /no\n")})
    with pytest.raises(PermissionError):
        fetcher.get("https://x.kr/no/1")
    assert "https://x.kr/no/1" not in net.calls


def test_redirect_to_disallowed_path_is_not_followed():
    fetcher, net, _ = make_fetcher({
        "https://x.kr/robots.txt": (200, "utf-8", b"User-agent: *\nDisallow: /secret\n"),
        "https://x.kr/ok": (302, None, b"", "/secret/1")})
    with pytest.raises(PermissionError):
        fetcher.get("https://x.kr/ok")
    assert "https://x.kr/secret/1" not in net.calls


def test_redirect_to_other_host_checks_that_hosts_robots():
    fetcher, net, _ = make_fetcher({
        "https://x.kr/a": (301, None, b"", "https://y.kr/b"),
        "https://y.kr/robots.txt": (403, None, b"")})
    with pytest.raises(PermissionError):
        fetcher.get("https://x.kr/a")
    assert "https://y.kr/b" not in net.calls


def test_redirect_loop_is_bounded():
    fetcher, _, _ = make_fetcher({"https://x.kr/a": (302, None, b"", "/a")})
    with pytest.raises(ConnectionError):
        fetcher.get("https://x.kr/a")


def test_host_clock_shared_through_state_file(tmp_path):
    state = tmp_path / "clock.json"
    clock = FakeClock()
    first = jobcrawl.HostClock(state, sleep=clock.sleep, clock=clock.time)
    second = jobcrawl.HostClock(state, sleep=clock.sleep, clock=clock.time)  # 다른 프로세스 흉내
    first.wait("x.kr", 3.0)
    second.wait("x.kr", 3.0)
    assert clock.slept and clock.slept[0] == pytest.approx(3.0, abs=0.05)
    assert not (tmp_path / "clock.lock").exists()


def test_decode_falls_back_to_cp949():
    assert jobcrawl.decode("한글".encode("cp949"), None) == "한글"


# ------------------------------------------------------------ jobcrawl: parsing

SARAMIN = """
<div class="item_recruit" value="111" data-data_layer="x">
 <h2 class="job_tit"><a title="[예시] 백엔드 &amp; 서버" href="/zf_user/jobs/relay/view?rec_idx=111&amp;x=1"><span>t</span></a></h2>
 <div class="job_date"><span class="date">~ 12/19(금)</span></div>
 <div class="job_condition"><span><a>서울</a> <a>송파구</a></span> <span>경력 2~12년</span> <span>학력무관</span> <span>정규직</span></div>
 <div class="area_corp"><strong class="corp_name"><a href="/c">(주)예시</a></strong></div>
</div>
<div class="item_recruit" value="222">
 <h2 class="job_tit"><a title="두번째" href="/x"></a></h2>
 <div class="job_date"><span class="date">상시채용</span></div>
 <div class="job_condition"><span>부산</span> <span>신입·경력</span></div>
 <strong class="corp_name"><a>둘째회사</a></strong>
</div>
"""

JOBKOREA = """
<div data-sentry-component="CardJob"><a href="https://www.jobkorea.co.kr/Recruit/GI_Read/555?Oem_Code=C1"></a>
<a href="https://www.jobkorea.co.kr/Recruit/GI_Read/555?x" data-sentry-component="Title" data-sentry-source-file="i"><span class="truncate">[A] 백엔드</span></a>
<span class="truncate text-gray700 text-typo-b2-16">에이주식회사</span>
<div data-sentry-component="GrayChip"><span class="emoji"></span></div><span class="truncate text-gray900">서울 강남구</span>
<span class="flex-shrink-0 text-gray700 text-typo-c1-13">경력3년↑</span><span class="truncate text-gray700 text-typo-c1-13">•</span>
<span class="truncate text-gray700 text-typo-c1-13">정규직</span>
</div>
<div data-sentry-component="CardJob"><a href="https://www.jobkorea.co.kr/Recruit/GI_Read/666"></a>
<a data-sentry-component="Title"><span>광고공고</span></a><span class="truncate text-gray700 text-typo-b2-16">비회사</span>
<span>AD</span><span class="x text-gray700 text-typo-c1-13">경력무관</span></div>
"""


JOBALIO = """
<table><thead><tr><th>번호</th></tr></thead><tbody>
<tr>
 <td><input type="checkbox" name="idxs" value="306272" /></td><td>37</td>
 <td class="left"><a href="/recruitview.do?idx=306272" target="_blank"/>NCS 및 블라인드 기반 신입직원(채용형 인턴) 채용 공고</a></td>
 <td>울산항만공사</td><td>
   울산 </td><td>
   청년인턴(채용형)
 외 1 </td><td>2026.10.22</td><td>26.11.05</br><span class="orange">D-13</span></td>
 <td><span class="orange"> 진행중</span></td>
</tr>
</tbody></table>
"""


def test_parse_jobalio_fields():
    jobs = jobcrawl.parse_jobalio(JOBALIO, TODAY)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["company"] == "울산항만공사" and job["location"] == "울산"
    assert job["employment"] == "청년인턴(채용형) 외 1"
    assert job["deadline"] == "2026-11-05"
    assert job["url"] == "https://job.alio.go.kr/recruitview.do?idx=306272"
    assert job["title"].startswith("NCS 및 블라인드")


def test_default_sites_include_jobalio():
    args = jobcrawl.build_parser().parse_args(["search", "행정"])
    assert "jobalio" in args.site.split(",")


def test_search_out_writes_utf8_file(tmp_path, capsys):
    page = jobcrawl.SITES["saramin"][0].format(q="a", page=1)
    fetcher, _, _ = make_fetcher({page: (200, "utf-8", SARAMIN.encode())})
    out = tmp_path / "결과.json"
    assert jobcrawl.main(["search", "a", "--site", "saramin", "--json", "--out", str(out)],
                         fetcher=fetcher, today=TODAY) == 0
    assert "(주)예시" in out.read_text(encoding="utf-8")


def test_table_has_employment_column():
    table = jobcrawl.to_table(jobcrawl.parse_jobalio(JOBALIO, TODAY))
    assert "고용형태" in table.splitlines()[0] and "청년인턴(채용형)" in table


class FakeStream:
    def __init__(self, encoding):
        self.encoding = encoding


@pytest.mark.parametrize("env, encoding, expected", [
    ({}, "cp949", "cp949"),                       # PowerShell/cmd (한국어 Windows)
    ({"MSYSTEM": "MINGW64"}, "cp949", "utf-8"),   # Git Bash
    ({"TERM": "xterm"}, "cp949", "utf-8"),        # WSL·맥·리눅스 터미널
    ({}, "cp1252", "utf-8"),                      # 한글을 못 쓰는 인코딩
    ({"PYTHONIOENCODING": "utf-8"}, "utf-8", "utf-8"),
    ({"PYTHONIOENCODING": "cp949", "TERM": "x"}, "cp949", "cp949"),  # 사용자 지정 우선
])
@pytest.mark.parametrize("module", ["jobcrawl", "charcount", "precheck", "salary", "tracker"])
def test_console_encoding_by_shell(monkeypatch, env, encoding, expected, module):
    for key in ("MSYSTEM", "TERM", "PYTHONIOENCODING"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    mod = load(module) if module == "charcount" else globals()[module]
    assert mod.console_encoding(FakeStream(encoding)) == expected


def test_charcount_warns_when_too_short(tmp_path, capsys, monkeypatch):
    charcount = load("charcount")
    f = tmp_path / "a.md"
    f.write_text("## 1 (제한 100자)\n" + "가" * 50 + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["charcount.py", str(f), "--sections"])
    assert charcount.main() == 0
    assert "70% 미만" in capsys.readouterr().out


def test_parse_saramin_fields():
    jobs = jobcrawl.parse_saramin(SARAMIN, TODAY)
    assert len(jobs) == 2
    first = jobs[0]
    assert first["title"] == "[예시] 백엔드 & 서버"
    assert first["company"] == "(주)예시"
    assert first["location"] == "서울 송파구"
    assert (first["career"], first["education"], first["employment"]) == ("경력 2~12년", "학력무관", "정규직")
    assert first["deadline"] == "2026-12-19"
    assert first["url"].endswith("rec_idx=111")
    assert jobs[1]["deadline"] == "상시채용"


def test_parse_jobkorea_fields_and_ad_flag():
    jobs = jobcrawl.parse_jobkorea(JOBKOREA, TODAY)
    assert [j["company"] for j in jobs] == ["에이주식회사", "비회사"]
    assert jobs[0]["title"] == "[A] 백엔드"
    assert jobs[0]["url"] == "https://www.jobkorea.co.kr/Recruit/GI_Read/555"
    assert jobs[0]["career"] == "경력3년↑" and jobs[0]["employment"] == "정규직"
    assert jobs[0]["is_ad"] is False and jobs[1]["is_ad"] is True


@pytest.mark.parametrize("raw, expected", [
    ("~ 12/19(금)", "2026-12-19"),
    ("~ 01/05(월)", "2027-01-05"),
    ("오늘마감", "2026-10-22"),
    ("내일마감", "2026-10-23"),
    ("채용시", "채용시"),
    ("~ 02/30", "~ 02/30"),
])
def test_normalize_deadline(raw, expected):
    assert jobcrawl.normalize_deadline(raw, TODAY) == expected


def test_detail_url_rewrites_saramin_only():
    assert jobcrawl.detail_url("https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=search&rec_idx=9") \
        == "https://www.saramin.co.kr/zf_user/jobs/relay/view-detail?rec_idx=9&rec_seq=0"
    assert jobcrawl.detail_url("https://www.jobkorea.co.kr/Recruit/GI_Read/1") == "https://www.jobkorea.co.kr/Recruit/GI_Read/1"


def test_search_dedupes_across_pages():
    tpl = jobcrawl.SITES["saramin"][0]
    fetcher, _, _ = make_fetcher({tpl.format(q="a", page=1): (200, "utf-8", SARAMIN.encode()),
                                  tpl.format(q="a", page=2): (200, "utf-8", SARAMIN.encode())})
    jobs, errors, status = jobcrawl.search(fetcher, "a", ["saramin"], 2, TODAY)
    assert len(jobs) == 2 and errors == [] and status["blocked"] == 0


def test_search_exit_codes(capsys):
    blocked, _, _ = make_fetcher({"https://www.saramin.co.kr/robots.txt": (200, "utf-8", b"User-agent: *\nDisallow: /\n")})
    assert jobcrawl.main(["search", "a", "--site", "saramin"], fetcher=blocked, today=TODAY) == 1
    page = jobcrawl.SITES["saramin"][0].format(q="a", page=1)
    empty, _, _ = make_fetcher({page: (200, "utf-8", b"<html>changed layout</html>")})
    assert jobcrawl.main(["search", "a", "--site", "saramin"], fetcher=empty, today=TODAY) == 3


def test_cli_rejects_too_many_pages_and_details(capsys):
    assert jobcrawl.main(["search", "a", "--pages", "50"], fetcher=make_fetcher({})[0]) == 2
    urls = [f"https://x.kr/{i}" for i in range(jobcrawl.MAX_DETAILS + 1)]
    assert jobcrawl.main(["detail", *urls], fetcher=make_fetcher({})[0]) == 2


def test_detail_batch_runs_sequentially_with_waits(capsys):
    fetcher, net, slept = make_fetcher({"https://x.kr/1": (200, "utf-8", b"<p>one</p>"),
                                        "https://x.kr/2": (200, "utf-8", b"<p>two</p>")})
    assert jobcrawl.main(["detail", "https://x.kr/1", "https://x.kr/2"], fetcher=fetcher) == 0
    out = capsys.readouterr().out
    assert "one" in out and "two" in out
    assert len([s for s in slept if s >= 2.9]) == 2


# ------------------------------------------------------------ precheck

def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_precheck_blind_and_company_errors(tmp_path):
    path = write(tmp_path, "a.md", "## 1\n예시대학교에서 배웠고 me@uni.ac.kr 입니다. 다른회사에 지원합니다.\n")
    findings = precheck.run(path, blind=True, companies=["다른회사"])
    rules = {(f.level, f.rule) for f in findings}
    assert ("ERROR", "다른 회사명") in rules
    assert ("ERROR", "블라인드: 학교명") in rules
    assert ("ERROR", "블라인드: 학교 이메일") in rules


def test_precheck_banned_phrase_and_exit_code(tmp_path):
    path = write(tmp_path, "a.md", "귀사에 최선을 다하겠습니다.\n")
    findings = precheck.run(path, blind=False, companies=[])
    assert sum(f.rule == "금지 표현" for f in findings) == 2
    assert precheck.main([path]) == 0  # WARN only
    bad = write(tmp_path, "b.md", "A사 지원\n")
    assert precheck.main([bad, "--companies", "A사"]) == 1


def test_precheck_target_company_is_not_flagged(tmp_path):
    path = write(tmp_path, "a.md", "A사의 결제 서비스\n")
    assert precheck.main([path, "--companies", "A사", "--target", "A사"]) == 0


def test_precheck_memo_reported_once_and_skipped_for_style(tmp_path):
    path = write(tmp_path, "a.md", "본문입니다.\n> 메모 귀사\n> 메모2\n")
    findings = precheck.run(path, blind=False, companies=[])
    assert [f.rule for f in findings] == ["내부 메모"]


def test_precheck_repeated_ending_uses_last_four_chars(tmp_path):
    same = write(tmp_path, "s.md", "줄였습니다. 줄였습니다. 줄였습니다.\n")
    varied = write(tmp_path, "v.md", "줄였습니다. 만들었습니다. 맡았습니다.\n")
    assert any(f.rule == "어미 반복" for f in precheck.run(same, False, []))
    assert not any(f.rule == "어미 반복" for f in precheck.run(varied, False, []))


@pytest.mark.parametrize("text, level", [
    ("서울대학교졸업 후", "ERROR"), ("한양대학교이며", "ERROR"), ("고려대학교도", "ERROR"),
    ("KAIST에서 연구", "ERROR"), ("카이스트 대학원", "ERROR"), ("Seoul National University", "ERROR"),
    ("서울대 졸업", "WARN"), ("서울대에서 공부", "WARN"),
])
def test_precheck_school_detection(text, level):
    assert (level, ) in {(lv,) for lv, _ in precheck.find_schools(text)}


@pytest.mark.parametrize("text", ["일반대학원에서 공부", "전문대학을 나와", "공과대학에서", "지방대학 출신",
                                  "사이버대학", "대학원생 시절", "대학 시절", "산학협력 과제",
                                  "출신대학", "소속대학에서", "졸업대학교", "협력대학과", "참여대학 ",
                                  "부대 출신으로", "현대 학생들", "MZ 세대 출신", "시대의 흐름"])
def test_precheck_school_false_positives(text):
    assert precheck.find_schools(text) == []


def test_precheck_age_not_confused_with_century(tmp_path):
    path = write(tmp_path, "a.md", "21세기 산업과 100세 시대를 준비합니다.\n")
    assert not any(f.rule == "블라인드: 나이" for f in precheck.run(path, True, []))


def test_precheck_target_containing_tracker_name(tmp_path):
    path = write(tmp_path, "a.md", "카카오뱅크의 대출 서비스\n")
    assert precheck.main([path, "--companies", "카카오", "--target", "카카오뱅크"]) == 0
    other = write(tmp_path, "b.md", "카카오뱅크와 카카오페이\n")
    assert precheck.main([other, "--companies", "카카오페이", "--target", "카카오뱅크"]) == 1


def test_precheck_short_company_needs_word_boundary(tmp_path):
    path = write(tmp_path, "a.md", "SKILL 개발과 TASK 관리\n")
    assert precheck.main([path, "--companies", "SK"]) == 0


def test_precheck_bullet_symbols_are_not_emoji(tmp_path):
    path = write(tmp_path, "a.md", "✓ 완료했습니다. ★ 강점입니다.\n")
    assert not any(f.rule == "이모지" for f in precheck.run(path, False, []))


def test_precheck_tracker_companies(tmp_path):
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("﻿회사,직무\nA사,x\nB사,y\n", encoding="utf-8")
    assert precheck.tracker_companies(str(csv_path), "A사") == ["B사"]


# ------------------------------------------------------------ salary

def test_earned_income_deduction_and_tax_brackets():
    assert salary.earned_income_deduction(50_000_000) == 12_250_000
    assert salary.earned_income_deduction(1_000_000_000) == 20_000_000
    assert salary.progressive_tax(30_000_000) == pytest.approx(3_240_000)
    assert salary.progressive_tax(14_000_000) == pytest.approx(840_000)


def test_pension_is_capped_and_floored():
    high = salary.monthly(salary.parse_offer("x=20000"))
    low = salary.monthly(salary.parse_offer("y=300,비과세=0"))
    assert high["국민연금"] == salary.floor10(6_590_000 * 0.0475)
    assert low["국민연금"] == salary.floor10(410_000 * 0.0475)


def test_severance_included_reduces_real_salary():
    plain = salary.monthly(salary.parse_offer("a=5200"))
    incl = salary.monthly(salary.parse_offer("b=5200,퇴직금포함"))
    assert incl["실질연봉"] == pytest.approx(48_000_000)
    assert incl["월실수령"] < plain["월실수령"]


def test_net_increases_with_salary():
    nets = [salary.monthly(salary.parse_offer(f"x={a}"))["월실수령"] for a in (3000, 4000, 5000, 8000)]
    assert nets == sorted(nets)


def test_income_tax_reference_values():
    """연 5,000만 원, 비과세 월 20만, 본인 1명 기준 소득세 계산 경로 고정(회귀 방지)."""
    r = salary.monthly(salary.parse_offer("x=5000"))
    total = (50_000_000 / 12 - 200_000) * 12
    income = total - salary.earned_income_deduction(total)
    insurance = (r["건강보험"] + r["장기요양"] + r["고용보험"]) * 12
    base = income - 1_500_000 - r["국민연금"] * 12 - insurance
    calc = salary.progressive_tax(base)
    expected = salary.floor10((calc - salary.earned_tax_credit(calc, total)) / 12)
    assert r["소득세"] == expected
    assert r["지방소득세"] == salary.floor10(expected * 0.1)


def test_bonus_only_in_annual_total():
    with_bonus = salary.monthly(salary.parse_offer("x=5000,성과급=500"))
    plain = salary.monthly(salary.parse_offer("x=5000"))
    assert with_bonus["월실수령"] == plain["월실수령"]
    assert with_bonus["연간총액(세전)"] == pytest.approx(55_000_000)


@pytest.mark.parametrize("spec", ["x", "x=", "x=-1", "x=5000,모름", "x=5000,비과세=-100", "x=5000,성과급=-1"])
def test_parse_offer_rejects_bad_input(spec):
    with pytest.raises(ValueError):
        salary.parse_offer(spec)


def test_salary_cli(capsys):
    assert salary.main(["A=5000", "B=5200,퇴직금포함"]) == 0
    out = capsys.readouterr().out
    assert "월실수령 차이" in out and "12/13" in out
    assert salary.main(["bad"]) == 2


# ------------------------------------------------------------ tracker

CSV = ("﻿회사,직무,공고URL,마감일,채용형태,상태,이력서파일,자소서파일,메모\n"
       "가사,백엔드,https://a.kr,2026-10-25,정규직,작성중,,,\n"
       "나사,서버,https://b.kr,2026-10-28,정규직,지원완료,,,\n"
       "다사,서버,https://c.kr,채용시 마감,정규직,서류합격,,,\n"
       "라사,서버,https://d.kr,2026-09-01,정규직,불합격,,,\n"
       "마사,<b>x</b>,javascript:alert(1),2026-12-30,정규직,1차합격,,,\n")


@pytest.fixture
def rows(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text(CSV, encoding="utf-8")
    return tracker.load(str(p))


def test_tracker_list_orders_and_flags(rows):
    out = tracker.cmd_list(rows, TODAY, 14)
    assert out.index("가사") < out.index("나사")
    assert "⚠ 아직 작성중" in out and "다사" in out and "라사" not in out and "마사" not in out


def test_tracker_ics_events_and_folding(rows):
    ics = tracker.cmd_ics(rows, 3, datetime(2026, 10, 22, tzinfo=timezone.utc))
    assert ics.count("BEGIN:VEVENT") == 3  # 가사, 나사, 마사 (불합격·날짜없음 제외)
    assert "DTSTART;VALUE=DATE:20261025" in ics and "TRIGGER:-P3D" in ics
    assert all(len(line.encode("utf-8")) <= 75 for line in ics.split("\r\n"))


def test_tracker_fold_keeps_utf8_intact():
    folded = tracker.fold("SUMMARY:" + "가" * 60)
    assert folded.replace("\r\n ", "") == "SUMMARY:" + "가" * 60


def test_tracker_funnel_counts(rows):
    steps = dict(tracker.funnel(rows))
    assert steps["작성중"] == 5 and steps["지원완료"] == 4 and steps["서류합격"] == 2 and steps["1차합격"] == 1


def test_tracker_funnel_excludes_withdrawn():
    steps = dict(tracker.funnel([{"상태": "포기"}, {"상태": "지원완료"}]))
    assert steps["지원완료"] == 1


def test_tracker_uid_stable_when_rows_reordered(rows):
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    uids = lambda rs: sorted(l for l in tracker.cmd_ics(rs, 0, now).split("\r\n") if l.startswith("UID:"))
    assert uids(rows) == uids(list(reversed(rows)))


def test_tracker_ics_escapes_carriage_return():
    assert tracker.ics_escape("a\r\nb\rc") == r"a\nb\nc"


def test_tracker_ics_without_events_writes_nothing(tmp_path, capsys):
    p = tmp_path / "t.csv"
    p.write_text("﻿회사,직무,공고URL,마감일,채용형태,상태\n가사,x,u,상시,정규직,작성중\n", encoding="utf-8")
    out = tmp_path / "x.ics"
    assert tracker.main(["ics", str(p), "--out", str(out)], today=TODAY) == 0
    assert not out.exists()


def test_tracker_list_shows_missed_deadlines():
    rows = [{"회사": "가사", "직무": "x", "마감일": "2026-10-01", "상태": "작성중"}]
    assert "마감 지남" in tracker.cmd_list(rows, TODAY, 14)


def test_tracker_report_escapes_html_and_blocks_js_links(rows):
    report = tracker.cmd_report(rows, TODAY)
    assert "<b>x</b>" not in report and "&lt;b&gt;x&lt;/b&gt;" in report
    assert "javascript:" not in report


def test_tracker_cli_bad_path():
    assert tracker.main(["list", "nope.csv"], today=TODAY) == 2
