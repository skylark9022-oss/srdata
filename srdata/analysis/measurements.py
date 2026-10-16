"""측정값 문자열("1.75±0.15", "<0.083", "1.04~1.94" …)을 숫자 성분으로 분리한다.

지원하는 형태(앞뒤 공백 무시):
    1.75±0.15                → 값 1.75, 불확도 0.15
    <0.083                   → 부등호 "<", 값 0.083
    65.4                     → 값 65.4
    1.04~1.94                → 최소 1.04, 최대 1.94
    <0.104~0.261             → 최소부등호 "<", 최소 0.104, 최대 0.261
    1.24±0.20 (0.738~1.85)   → 값·불확도 + 최소·최대
    112(107~121)             → 값 + 최소·최대
    - (<0.558)               → 비고 "-", 최소부등호 "<", 최소 0.558 (괄호 안 값 하나는 최소로 본다)
    -, -*                    → 비고에 그대로

숫자는 유효숫자를 지키기 위해 문자열로 돌려준다("1.60" 은 "1.60"). 엑셀로 쓸 때
`srdata.excel.save_sheets(..., numeric_text=...)` 가 숫자로 바꾸고 소수 자릿수를 표시 형식으로 남긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

NUM = r"-?\d+(?:\.\d+)?"
INEQ = r"[<>≤≥]"
_VAL = re.compile(rf"^(?P<ineq>{INEQ})?\s*(?P<num>{NUM})$")
_PM = re.compile(rf"^(?P<ineq>{INEQ})?\s*(?P<num>{NUM})\s*±\s*(?P<unc>{NUM})$")
_RANGE = re.compile(rf"^(?P<ineq1>{INEQ})?\s*(?P<n1>{NUM})\s*~\s*(?P<ineq2>{INEQ})?\s*(?P<n2>{NUM})$")
_SPLIT = re.compile(r"^(?P<main>[^()]*?)\s*(?:\((?P<paren>[^()]*)\))?$")
_MARKER = re.compile(r"^-\*?$")  # "-" 또는 "-*"

PART_NAMES = ["비고", "부등호", "값", "불확도", "최소부등호", "최소", "최대부등호", "최대"]


def normalize(text: str) -> str:
    s = str(text).strip()
    s = s.replace("∼", "~").replace("～", "~").replace("–", "-").replace("−", "-").replace("＜", "<")
    return re.sub(r"\s+", " ", s)


def parse_measurement(text) -> dict[str, str] | None:
    """측정값 문자열을 {비고, 부등호, 값, 불확도, 최소부등호, 최소, 최대부등호, 최대} 로 분리한다.

    분리할 수 없으면 None. 빈 문자열은 모두 빈 값으로 돌려준다.
    """
    out = {k: "" for k in PART_NAMES}
    if text is None:
        return out
    s = normalize(text)
    if s == "":
        return out
    m = _SPLIT.match(s)
    if not m:
        return None
    main, paren = m.group("main").strip(), m.group("paren")

    if main:
        if _MARKER.match(main):
            out["비고"] = main
        elif (pm := _PM.match(main)):
            out["부등호"], out["값"], out["불확도"] = pm.group("ineq") or "", pm.group("num"), pm.group("unc")
        elif (rg := _RANGE.match(main)):
            _fill_range(out, rg)
        elif (v := _VAL.match(main)):
            out["부등호"], out["값"] = v.group("ineq") or "", v.group("num")
        else:
            return None
    if paren is not None:
        p = paren.strip()
        if (rg := _RANGE.match(p)):
            _fill_range(out, rg)
        elif (v := _VAL.match(p)):
            out["최소부등호"], out["최소"] = v.group("ineq") or "", v.group("num")
        elif p == "":
            pass
        else:
            return None
    return out


def _fill_range(out: dict[str, str], rg: re.Match) -> None:
    out["최소부등호"], out["최소"] = rg.group("ineq1") or "", rg.group("n1")
    out["최대부등호"], out["최대"] = rg.group("ineq2") or "", rg.group("n2")


def is_measurement_column(values) -> bool:
    """분리 규칙에 맞으면서 ±, 부등호, 범위 중 하나를 가진 셀이 하나라도 있는 열인가.

    순수 숫자만 있는 열(수심, 시료수 등)이나 "연 6~24회", "동해 (8)" 같은 문구 열은 아니다.
    """
    for v in values:
        if not isinstance(v, str):
            continue
        d = parse_measurement(v)
        if d and (d["불확도"] or d["부등호"] or d["최소"] or d["최대"]):
            return True
    return False


@dataclass
class SplitResult:
    frame: pd.DataFrame
    unparsed: list[tuple[int, str, str]] = field(default_factory=list)  # (행 번호 0부터, 열, 원문)
    split_columns: list[str] = field(default_factory=list)


def split_measurement_columns(df: pd.DataFrame, *, sep: str = " | ") -> SplitResult:
    """측정값 열을 성분 열로 바꾼 DataFrame 을 만든다.

    새 열 이름은 "{원래 열}{sep}{성분}". 그 열에서 한 번도 쓰이지 않은 성분 열은 만들지 않는다.
    분리할 수 없는 셀은 비고 열에 원문을 그대로 두고 unparsed 에 기록한다.
    """
    pieces: list[pd.DataFrame] = []
    unparsed: list[tuple[int, str, str]] = []
    split_cols: list[str] = []
    for col in df.columns:
        series = df[col]
        if not is_measurement_column(series.tolist()):
            pieces.append(series.to_frame())
            continue
        split_cols.append(str(col))
        rows = []
        for i, v in enumerate(series.tolist()):
            parsed = parse_measurement(v if v is not None else "")
            if parsed is None:
                parsed = {k: "" for k in PART_NAMES}
                parsed["비고"] = str(v)
                unparsed.append((i, str(col), str(v)))
            rows.append(parsed)
        part = pd.DataFrame(rows, index=df.index)
        keep = [k for k in PART_NAMES if (part[k] != "").any()]
        part = part[keep]
        part.columns = [f"{col}{sep}{k}" for k in keep]
        pieces.append(part)
    return SplitResult(pd.concat(pieces, axis=1), unparsed, split_cols)
