#!/usr/bin/env python3
"""연봉 실수령액 추정과 오퍼 비교.

사용법:
    python salary.py "현직=4300" "A사=5200,퇴직금포함" "B사=5000,비과세=10,부양=2"

각 오퍼: 라벨=연봉(만원)[,옵션...]
  퇴직금포함   연봉에 퇴직금이 들어 있음 → 실질 연봉 = 연봉 × 12/13
  비과세=N     월 비과세 수당(만원, 기본 20 = 식대)
  부양=N       본인 포함 기본공제 대상 인원(기본 1)
  성과급=N     연봉과 별도 성과급(만원, 세전) → '연간총액(세전)' 행에만 더함(월 실수령 계산엔 미포함)

계산 기준 (2026년 7월 기준, 매년 바뀜):
- 국민연금 4.75% (기준소득월액 41만~659만 원, 천 원 미만 절사), 건강보험 3.595%,
  장기요양 = 건강보험료 × 13.14%, 고용보험 0.9%
- 소득세: 연간 근로소득세를 직접 계산해 12로 나눔(근로소득공제, 인적공제,
  연금보험료 공제, 건강·고용보험료 특별소득공제, 세율표, 근로소득세액공제). 지방소득세 10%.
  특별소득공제를 받으므로 표준세액공제(13만 원)는 적용하지 않는다(소득세법 제59조의4).
국세청 간이세액표와 월 수천~수만 원 차이가 날 수 있는 **추정치**다. 연말정산 결과와도 다르다.
"""
import argparse
import os
import sys
from typing import NamedTuple

RATES = {
    "pension": 0.0475, "pension_min": 410_000, "pension_max": 6_590_000,
    "health": 0.03595, "ltc_of_health": 0.1314, "employment": 0.009,
}
RATES_AS_OF = "2026-07"
TAX_BRACKETS = [  # (상한, 세율, 누진공제)
    (14_000_000, 0.06, 0), (50_000_000, 0.15, 1_260_000), (88_000_000, 0.24, 5_760_000),
    (150_000_000, 0.35, 15_440_000), (300_000_000, 0.38, 19_940_000),
    (500_000_000, 0.40, 25_940_000), (1_000_000_000, 0.42, 35_940_000),
    (float("inf"), 0.45, 65_940_000),
]
PERSONAL_DEDUCTION = 1_500_000


class Offer(NamedTuple):
    label: str
    annual_won: int
    severance_included: bool
    nontax_month: int
    dependents: int
    bonus_won: int


def floor10(x: float) -> int:
    return int(x // 10 * 10)


def earned_income_deduction(total: float) -> float:
    if total <= 5_000_000:
        d = total * 0.7
    elif total <= 15_000_000:
        d = 3_500_000 + (total - 5_000_000) * 0.4
    elif total <= 45_000_000:
        d = 7_500_000 + (total - 15_000_000) * 0.15
    elif total <= 100_000_000:
        d = 12_000_000 + (total - 45_000_000) * 0.05
    else:
        d = 14_750_000 + (total - 100_000_000) * 0.02
    return min(d, 20_000_000)


def progressive_tax(base: float) -> float:
    for limit, rate, deduction in TAX_BRACKETS:
        if base <= limit:
            return max(0.0, base * rate - deduction)
    return 0.0


def earned_tax_credit(tax: float, total: float) -> float:
    credit = tax * 0.55 if tax <= 1_300_000 else 715_000 + (tax - 1_300_000) * 0.30
    if total <= 33_000_000:
        cap = 740_000
    elif total <= 70_000_000:
        cap = max(740_000 - (total - 33_000_000) * 0.008, 660_000)
    elif total <= 120_000_000:
        cap = max(660_000 - (total - 70_000_000) * 0.5, 500_000)
    else:
        cap = max(500_000 - (total - 120_000_000) * 0.5, 200_000)
    return min(credit, cap)


def monthly(offer: Offer) -> dict:
    annual = offer.annual_won * 12 / 13 if offer.severance_included else offer.annual_won
    gross = annual / 12
    taxable = max(0.0, gross - min(offer.nontax_month, gross))
    base = min(max(taxable // 1000 * 1000, RATES["pension_min"]), RATES["pension_max"])
    pension = floor10(base * RATES["pension"])
    health = floor10(taxable * RATES["health"])
    ltc = floor10(health * RATES["ltc_of_health"])
    employment = floor10(taxable * RATES["employment"])

    total = taxable * 12
    income = total - earned_income_deduction(total)
    tax_base = max(0.0, income - PERSONAL_DEDUCTION * offer.dependents
                   - pension * 12 - (health + ltc + employment) * 12)
    calc = progressive_tax(tax_base)
    determined = max(0.0, calc - earned_tax_credit(calc, total))
    income_tax = floor10(determined / 12)
    local_tax = floor10(income_tax * 0.1)

    deductions = pension + health + ltc + employment + income_tax + local_tax
    net = gross - deductions
    return {
        "실질연봉": annual, "월세전": gross, "비과세": float(offer.nontax_month),
        "국민연금": pension, "건강보험": health, "장기요양": ltc, "고용보험": employment,
        "소득세": income_tax, "지방소득세": local_tax, "공제합계": deductions,
        "월실수령": net, "연실수령": net * 12, "성과급(세전)": float(offer.bonus_won),
        "연간총액(세전)": annual + offer.bonus_won,
    }


def parse_offer(spec: str) -> Offer:
    if "=" not in spec:
        raise ValueError(f"형식 오류(라벨=연봉): {spec}")
    label, rest = spec.split("=", 1)
    parts = [p.strip() for p in rest.split(",") if p.strip()]
    if not parts:
        raise ValueError(f"연봉이 없음: {spec}")
    annual = float(parts[0].replace("만원", "").replace("만", ""))
    if annual <= 0:
        raise ValueError(f"연봉은 0보다 커야 함: {spec}")
    opts = {"nontax": 20.0, "dependents": 1, "bonus": 0.0, "severance": False}
    for p in parts[1:]:
        if p in ("퇴직금포함", "퇴직금 포함"):
            opts["severance"] = True
        elif p.startswith("비과세="):
            opts["nontax"] = float(p.split("=", 1)[1])
        elif p.startswith("부양="):
            opts["dependents"] = max(1, int(p.split("=", 1)[1]))
        elif p.startswith("성과급="):
            opts["bonus"] = float(p.split("=", 1)[1])
        else:
            raise ValueError(f"알 수 없는 옵션 '{p}' ({spec})")
    if opts["nontax"] < 0 or opts["bonus"] < 0:
        raise ValueError(f"비과세·성과급은 0 이상이어야 함: {spec}")
    return Offer(label.strip(), int(annual * 10_000), opts["severance"],
                 int(opts["nontax"] * 10_000), opts["dependents"], int(opts["bonus"] * 10_000))


def won(x: float) -> str:
    return f"{int(round(x)):,}"


def render(offers: list, results: list) -> str:
    keys = list(results[0].keys())
    lines = ["| 항목 (원) | " + " | ".join(o.label for o in offers) + " |",
             "|---|" + "---|" * len(offers)]
    for k in keys:
        lines.append(f"| {k} | " + " | ".join(won(r[k]) for r in results) + " |")
    if len(offers) > 1:
        base = results[0]["월실수령"]
        diffs = " | ".join(("기준" if i == 0 else f"{won(r['월실수령'] - base)}") for i, r in enumerate(results))
        lines.append(f"| 월실수령 차이 | {diffs} |")
    notes = [o.label for o in offers if o.severance_included]
    tail = [f"\n요율 기준: {RATES_AS_OF}. 간이세액표와 다를 수 있는 추정치."]
    if notes:
        tail.append(f"퇴직금 포함 연봉({', '.join(notes)})은 12/13으로 환산해 계산함. 같은 숫자의 퇴직금 별도 연봉보다 약 7.7% 낮다.")
    return "\n".join(lines + tail)


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
    p = argparse.ArgumentParser(description="연봉 실수령액 추정·오퍼 비교 (만원 단위 입력)")
    p.add_argument("offers", nargs="+", help='예: "A사=5200,퇴직금포함"')
    args = p.parse_args(argv)
    try:
        offers = [parse_offer(s) for s in args.offers]
    except ValueError as e:
        print(f"입력 오류: {e}", file=sys.stderr)
        return 2
    print(render(offers, [monthly(o) for o in offers]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
