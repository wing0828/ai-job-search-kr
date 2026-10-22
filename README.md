# ai-job-search-kr

한국 채용시장용 AI 구직·지원 스킬. Claude Code와 Codex CLI에서 쓰는 `SKILL.md` 형식이다.

채용공고 적합도 평가, 이력서·경력기술서 맞춤 작성, 자기소개서 문항별 작성(글자수 측정 포함), 인적성·코딩테스트·면접 준비, 처우협의까지 한 흐름으로 돕는다.

> [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) (MIT)를 한국 채용 관행에 맞게 다시 쓴 파생 작업이다. 원본은 덴마크 시장(Jobindex, Jobnet 등)과 LaTeX 기반 CV·커버레터 중심이다.

## 원본과 달라진 점

| 원본 | 한국판 |
|------|--------|
| CV + 커버레터 (LaTeX) | 이력서 + 경력기술서 + **문항형 자기소개서** (Markdown → PDF/DOCX, 지정 양식 우선) |
| 시민권·체류 게이트 | **병역, 학력·졸업예정, 필수 자격증, 경력 연차, 지역인재·보훈, 체류자격** 게이트 |
| 언어 수준 게이트 | **공인 어학점수 커트라인·유효기간(2년)** 포함 어학 게이트 |
| 덴마크 포털 CLI | 사람인, 잡코리아, 원티드, 리멤버, 잡알리오, 나라일터, 고용24 등 검색 쿼리 템플릿 |
| 연봉 지수 엑셀 도구 | 만원 단위, **퇴직금 포함 여부·포괄임금제·수습 조건** 점검, 크레딧잡·DART 참고 |
| 영문 작성 규칙 | 두괄식, 소제목, 한국 자소서 상투어 금지 목록, **블라인드 채용 규칙** |
| 일반 면접 | 인적성(GSAT·SKCT 등), NCS, 코딩테스트, 실무·임원·PT·토론 면접, **처우협의** |
| - | 글자수 측정 스크립트 (공백 포함/제외/바이트, 문항별) |
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
│   ├── 02-writing-style.md          # 문체 규칙
│   ├── 03-job-evaluation.md         # 게이트·점수·연봉 점검·기업 리서치
│   ├── 04-resume-templates.md       # 이력서·경력기술서·포트폴리오
│   ├── 05-self-introduction.md      # 자소서 문항 유형별 가이드
│   ├── 06-interview-prep.md         # 필기·면접·처우협의
│   └── 07-web-research.md           # 공고 수집·포털·검색 쿼리·신뢰 경계
├── scripts/charcount.py             # 글자수 측정
└── templates/tracker.csv            # 지원 현황 기록
tests/test_charcount.py              # 글자수 스크립트 테스트 (pytest)
```

Codex에서 쓸 때: 웹 도구 이름(WebFetch/WebSearch)은 Claude Code 기준으로 적혀 있다. Codex의 웹 검색·가져오기 기능으로 같은 순서를 따르면 된다.

## AI 에이전트 (Claude Code)

원본의 서브에이전트 3개를 한국판으로 옮겼다. 셋 다 **읽기 전용**(Edit/Write 도구 없음)이다. 신뢰할 수 없는 공고 텍스트를 다루는 쪽이 파일을 바꿀 수 없게 해서, 공고에 숨은 지시문(프롬프트 인젝션)이 작업을 조작하지 못하게 한다.

| 에이전트 | 하는 일 |
|---------|--------|
| `posting-fetcher-kr` | 공고 URL 한 건을 robots.txt 규칙에 맞게 가져와 본문 원문과 메타데이터(마감일, 채용형태, 근무지, 경력, 전형, 자소서 문항·글자수)를 돌려주고, 숨은 지시문·사기 의심 요구를 찾아 보고 |
| `posting-scorer-kr` | 여러 공고를 한꺼번에 가져와 게이트(자격·어학·근무지) 판정과 적합도 점수를 JSON으로 반환. 병렬 선별용 |
| `application-reviewer-kr` | 채용 담당자 입장에서 이력서·자소서를 프로필과 한 줄씩 대조하고, 회사 관련 주장을 직접 확인해 원문/수정안 쌍으로 돌려줌. 작성자와 검수자 분리 |

스킬은 에이전트가 설치되어 있으면 자동으로 맡기고, 없으면(Codex 등) 같은 규칙으로 직접 수행한다. 에이전트는 Claude Code를 새로 시작해야 목록에 잡힌다.

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
2. 채용공고 URL이나 본문을 주고 "이 공고 평가해줘".
3. 적합하면 "이력서랑 자소서 써줘". 자소서 문항과 글자수 제한을 함께 준다.
4. "○○ 실무면접 모의면접 해줘".

글자수 측정만 따로 (설치 경로 기준):
```bash
python ~/.claude/skills/job-application-kr/scripts/charcount.py 자기소개서.md --sections
python ~/.claude/skills/job-application-kr/scripts/charcount.py 자소서1.txt --limit 700
```
`--sections`는 Markdown `##` 문항마다 따로 재고, 제목의 "(제한 1,000자)"·"(1,000자 이내)"를 제한으로 읽는다. 조합형(NFD) 한글도 정상 글자수로 센다.

`templates/tracker.csv`는 UTF-8(BOM)으로 저장되어 Excel에서 바로 열린다.

## 테스트

```bash
pip install pytest
pytest tests -q
```

## 검수 이력
- 2026-10-21: 가상 인물 프로필과 실제 공고 2건(경력직 백엔드)으로 평가 → 이력서 → 자소서 전 과정을 돌리고, 별도 검수 에이전트가 규칙·법령 표현·스크립트를 점검. 발견된 25건(게이트 이후 진행 규칙, 미확인 항목 점수 처리, 채용절차법·연령·수습 표현, 블라인드 목록 통일, 원문 보관 방식, 글자수 스크립트의 제한 인식·NFC·코드펜스 처리 등)을 반영.

## 주의
- 실제 지원서 제출, 포털 로그인은 사용자가 직접 한다.
- 포털 이용약관과 robots.txt를 존중한다. 대량 크롤링 도구가 아니다.
- 연봉·리뷰 정보는 추정치나 개인 제보다. 참고용으로만 쓴다.
- 포털·시험 명칭과 제도는 바뀔 수 있다. 지원 전 공식 공지를 확인한다.

## 라이선스
MIT. 원저작권 표시(Mads Lorentzen)와 한국판 저작권 표시를 [LICENSE](LICENSE)에 함께 둔다.
