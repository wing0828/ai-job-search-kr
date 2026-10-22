# ai-job-search-kr

한국 채용시장용 AI 구직·지원 스킬. Claude Code와 Codex CLI에서 쓰는 `SKILL.md` 형식이다.

공고 찾기(사람인·잡코리아·잡알리오 크롤러) → 적합도 평가 → 이력서·경력기술서·자기소개서 작성 → 제출 전 자동 검사 → 마감 관리 → 면접 준비 → 연봉 실수령액 비교까지 한 흐름으로 돕는다. 스크립트는 파이썬 표준 라이브러리만 쓰고, API 키나 유료 서비스가 필요 없다.

> [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) (MIT)를 한국 채용 관행에 맞게 다시 쓴 파생 작업이다. 원본은 덴마크 시장(Jobindex, Jobnet 등)과 LaTeX 기반 CV·커버레터 중심이다.

## 원본과 달라진 점

| 원본 | 한국판 |
|------|--------|
| CV + 커버레터 (LaTeX) | 이력서 + 경력기술서 + **문항형 자기소개서** (Markdown → PDF/DOCX, 지정 양식 우선) |
| 시민권·체류 게이트 | **병역, 학력·졸업예정, 필수 자격증, 경력 연차, 지역인재·보훈, 체류자격** 게이트 |
| 언어 수준 게이트 | **공인 어학점수 커트라인·인정 기간** 포함 어학 게이트 |
| 덴마크 포털 CLI | **사람인·잡코리아·잡알리오(공공기관) 크롤러** (robots.txt 준수, 요청 간격 3초) + 검색 쿼리 템플릿 |
| 연봉 지수 엑셀 도구 | **연봉 실수령액·오퍼 비교 계산기** (2026년 4대보험 요율, 퇴직금 포함 연봉 환산) |
| 영문 작성 규칙 | 두괄식, 소제목, 한국 자소서 상투어 금지 목록, **블라인드 채용 규칙** + **제출 전 자동 검사기** |
| 일반 면접 | 인적성(GSAT·SKCT 등), NCS, 코딩테스트, 실무·임원·PT·토론 면접, **처우협의** |
| - | 자소서 **문항 유형집**, NCS 직무기술서 활용, HWP 양식 안내 |
| - | 글자수 측정 (공백 포함/제외/바이트, 문항별) |
| - | 지원 현황: 마감 임박 목록, **캘린더(.ics) 내보내기**, HTML 현황판 |
| 서브에이전트 3개 (공고 가져오기·선별·검수) | 한국판으로 이식, 읽기 전용 원칙 유지 |

원본의 핵심 원칙은 그대로 유지했다: **프로필에 없는 사실은 쓰지 않는다**, 회사 관련 주장은 직접 확인한 출처로만, 공고 본문은 지시가 아니라 데이터로 취급(프롬프트 인젝션 방어).

## 구성

```
agents/                              # Claude Code 서브에이전트 (읽기 전용)
├── posting-fetcher-kr.md
├── posting-scorer-kr.md
└── application-reviewer-kr.md
skills/job-application-kr/
├── SKILL.md                         # 워크플로·검증 체크리스트
├── references/
│   ├── 01-candidate-profile.md      # 프로필 템플릿
│   ├── 02-writing-style.md          # 문체 규칙, 블라인드 목록
│   ├── 03-job-evaluation.md         # 게이트·점수·연봉 점검·기업 리서치
│   ├── 04-resume-templates.md       # 이력서·경력기술서·포트폴리오
│   ├── 05-self-introduction.md      # 자소서 작성·글자수 운용
│   ├── 06-interview-prep.md         # 필기·면접·처우협의
│   ├── 07-web-research.md           # 공고 수집·크롤러·포털·신뢰 경계
│   └── 08-question-types.md         # 문항 유형집·NCS·HWP 양식
├── scripts/
│   ├── jobcrawl.py                  # 사람인·잡코리아·잡알리오 검색/상세 크롤러
│   ├── charcount.py                 # 글자수 측정
│   ├── precheck.py                  # 제출 전 자동 검사
│   ├── salary.py                    # 연봉 실수령액·오퍼 비교
│   └── tracker.py                   # 마감 목록·.ics·현황판
└── templates/tracker.csv            # 지원 현황 기록 (UTF-8 BOM, Excel 호환)
tests/                               # pytest 160개
```

## 스크립트

설치 경로 기준 예시(`S=~/.claude/skills/job-application-kr/scripts`).

```bash
# 공고 찾기 (기본: 사람인+잡코리아+잡알리오, 사이트당 2페이지)
python $S/jobcrawl.py search "백엔드 개발자" --pages 2 --exclude-ads
python $S/jobcrawl.py search "행정" --site jobalio            # 공공기관만
python $S/jobcrawl.py search "회계" --json --out 결과.json      # 파일로 저장
python $S/jobcrawl.py detail "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=..."

# 자소서 글자수 (문항별, 제목의 "(제한 1,000자)" 자동 인식)
python $S/charcount.py 자기소개서.md --sections

# 제출 전 검사 (다른 회사명·블라인드·금지 표현·문체)
python $S/precheck.py 자기소개서.md 이력서.md --target "지원회사" --tracker applications/tracker.csv --blind

# 연봉 실수령액 비교 (만원 단위)
python $S/salary.py "현직=4300" "A사=5200,퇴직금포함" "B사=5000,비과세=10"

# 마감 관리
python $S/tracker.py list applications/tracker.csv --days 14
python $S/tracker.py ics applications/tracker.csv --out 마감일.ics      # 캘린더 앱에서 가져오기
python $S/tracker.py report applications/tracker.csv --out 현황판.html
```

### Windows(PowerShell)에서 쓰기
```powershell
$S = "$env:USERPROFILE\.claude\skills\job-application-kr\scripts"
python "$S\jobcrawl.py" search "행정" --site jobalio --out 공고.md
python "$S\salary.py" "현직=3200" "A공사=3600"
```
- `python`이 없으면 `py`로 실행한다(python.org 설치본의 실행기).
- 한글 출력은 PowerShell·cmd(cp949)와 Git Bash·WSL(UTF-8) 모두 깨지지 않게 셸에 맞춰 나온다. 직접 고정하려면 `PYTHONIOENCODING` 환경 변수를 쓴다.
- 결과를 파일로 남길 때는 `>` 리다이렉트보다 `--out`이 안전하다(항상 UTF-8로 저장).
- `charcount.py`에 PowerShell 파이프로 한글을 넘기면 PowerShell 5.1이 글자를 바꿀 수 있다. 파일 경로로 넘긴다.

### 크롤러 원칙
- 요청 전에 robots.txt(RFC 9309)를 읽고 금지 경로는 가져오지 않는다. robots.txt를 읽을 수 없으면 금지로 본다(원티드·리멤버는 이 이유로 제외). 리다이렉트도 한 단계씩 다시 검사한다.
- 같은 사이트에 최소 3초 간격(여러 프로세스가 동시에 실행돼도 `~/.cache/job-application-kr/`의 파일로 간격 공유), 실행당 검색 10페이지·상세 20건 상한, Crawl-delay가 60초를 넘으면 건너뜀. User-Agent에 도구 이름을 밝힌다.
- **개인 구직 목적의 소량 조회**에만 쓴다. 수집한 공고를 모아 재배포하거나 서비스로 만들지 않는다.
- robots.txt 준수가 이용약관·법 준수를 뜻하지는 않는다. 데이터베이스를 반복적·체계적으로 복제하면 양이 적어도 저작권법(제93조) 문제가 될 수 있다. 각 포털 약관을 확인한다.
- 종료 코드: 0 성공, 1 robots 금지, 2 네트워크·입력 오류, 3 응답은 왔는데 0건(화면 구조 변경 의심 — 이슈로 알려 주면 고친다).

### 연봉 계산기 기준
2026년 7월 기준 국민연금 4.75%(기준소득월액 41만~659만 원), 건강보험 3.595%, 장기요양 건강보험료의 13.14%, 고용보험 0.9%. 소득세는 연간 세액(근로소득공제·인적공제·보험료 공제·근로소득세액공제)을 직접 계산해 12로 나눈 **추정치**라 국세청 간이세액표와 월 수천~수만 원 차이가 날 수 있다. 요율이 바뀌면 `salary.py` 상단 상수를 고친다.

## AI 에이전트 (Claude Code)

원본의 서브에이전트 3개를 한국판으로 옮겼다. 셋 다 **읽기 전용**(Edit/Write 도구 없음)이다. 신뢰할 수 없는 공고 텍스트를 다루는 쪽이 파일을 바꿀 수 없게 해서, 공고에 숨은 지시문(프롬프트 인젝션)이 작업을 조작하지 못하게 한다.

| 에이전트 | 하는 일 |
|---------|--------|
| `posting-fetcher-kr` | 공고 URL 한 건을 크롤러·robots.txt 규칙으로 가져와 본문 원문과 메타데이터(마감일, 채용형태, 근무지, 경력, 전형, 자소서 문항·글자수)를 돌려주고, 숨은 지시문·사기 의심 요구를 찾아 보고 |
| `posting-scorer-kr` | 크롤러 검색 결과나 URL 목록을 받아 게이트(자격·어학·근무지) 판정과 적합도 점수를 JSON으로 반환. 병렬 선별용 |
| `application-reviewer-kr` | 채용 담당자 입장에서 이력서·자소서를 프로필과 한 줄씩 대조하고 자동 검사기를 돌린 뒤, 회사 관련 주장을 직접 확인해 원문/수정안 쌍으로 돌려줌. 작성자와 검수자 분리 |

스킬은 에이전트가 설치되어 있으면 자동으로 맡기고, 없으면(Codex 등) 같은 규칙으로 직접 수행한다. 에이전트는 Claude Code를 새로 시작해야 목록에 잡힌다.

Codex에서 쓸 때: 웹 도구 이름(WebFetch/WebSearch)은 Claude Code 기준으로 적혀 있다. Codex의 웹 검색·가져오기 기능으로 같은 순서를 따르면 된다. 스크립트는 그대로 쓸 수 있다.

## 설치

Claude Code:
```bash
git clone https://github.com/wing0828/ai-job-search-kr
cp -r ai-job-search-kr/skills/job-application-kr ~/.claude/skills/
mkdir -p ~/.claude/agents && cp ai-job-search-kr/agents/*.md ~/.claude/agents/
```

Codex CLI:
```bash
cp -r ai-job-search-kr/skills/job-application-kr ~/.codex/skills/
```

## 사용

1. 작업 폴더를 하나 만들고 `references/01-candidate-profile.md`를 `profile.md`로 복사해 채운다. 기존 이력서를 주면서 "프로필 만들어줘"라고 해도 된다.
2. "백엔드 공고 찾아줘" → 크롤러로 찾고 프로필 기준으로 선별. 또는 공고 URL을 주고 "이 공고 평가해줘".
3. 적합하면 "이력서랑 자소서 써줘". 자소서 문항과 글자수 제한을 함께 준다. 작성 후 자동 검사·독립 검수를 거친다.
4. "마감 임박한 거 뭐야?", "○○ 실무면접 모의면접 해줘", "이 오퍼 실수령 비교해줘".

## 테스트

```bash
pip install pytest
pytest tests -q
```
크롤러 테스트는 합성 HTML과 가짜 네트워크로 돌아 실제 사이트에 요청하지 않는다.

## 검수 이력
- 2026-10-21: 가상 인물 프로필과 실제 공고 2건(경력직 백엔드)으로 평가 → 이력서 → 자소서 전 과정을 돌리고, 별도 검수 에이전트가 규칙·법령 표현·스크립트를 점검. 발견된 25건을 반영.
- 2026-10-22: 읽기 전용 서브에이전트 3개 이식 후 실제 공고로 동작 검증, 지적 사항 반영. 크롤러·자동 검사기·연봉 계산기·마감 관리 도구·문항 유형집 추가. 크롤러는 사람인·잡코리아 실제 검색(40건+24건)과 상세 페이지로 확인.
- 2026-10-22 (사용성 점검): 신입·공공기관 시나리오와 한국어 Windows 기본 환경으로 다시 써 봄. 고친 것: PowerShell(cp949)에서 결과를 파이프·파일로 넘기면 한글이 깨지던 문제(셸별 인코딩 자동 선택), 사람인·잡코리아에 공공기관 공고가 거의 없던 문제(잡알리오 지원 추가, 실제 검색 37건 확인), 결과 표에 고용형태(정규직·채용형/체험형 인턴·기간제) 열 추가, 공공기관 필수 조건(한국사능력검정·정년·즉시 근무)과 가산점을 평가 기준·프로필에 추가, 공공기관 자소서 문항이 첨부 입사지원서에 있다는 안내, 이력서 없는 신입을 위한 질문형 프로필 작성, 글자수가 제한의 70% 미만일 때 안내.

## 주의
- 실제 지원서 제출, 포털 로그인은 사용자가 직접 한다.
- 크롤러는 개인 구직용이다. 각 포털의 이용약관을 확인하고 지킨다.
- 연봉·리뷰 정보와 실수령액 계산은 추정치다. 참고용으로만 쓴다.
- 포털·시험 명칭과 제도, 4대보험 요율은 바뀔 수 있다. 지원 전 공식 공지를 확인한다.

## 라이선스
MIT. 원저작권 표시(Mads Lorentzen)와 한국판 저작권 표시를 [LICENSE](LICENSE)에 함께 둔다.
