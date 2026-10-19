"""MEIS 정기조사(정밀분석) 엑셀 파일들을 읽어 하나의 표로 합친다.

내려받은 파일의 실제 형식은 세 가지 중 하나일 수 있어 내용(앞 바이트)으로 구분한다.
    - 진짜 .xlsx (zip, "PK")           → openpyxl
    - 진짜 .xls  (OLE2, D0 CF 11 E0)   → xlrd
    - HTML 표를 .xls 로 저장한 것 ("<")  → pandas.read_html (국내 공공 사이트의 "엑셀" 버튼에 흔함)

머리글 행은 "정점명" 이 들어 있는 행으로 찾는다(위에 제목 행이 있어도 됨).
셀 값은 문자열 그대로 둔다("1.30 ± 0.16", "<0.43"). 값·불확도 분리는 srdata.analysis.measurements 가 한다.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import pandas as pd

HEADER_KEY = "정점명"
SOURCE_COL = "원본파일"
SORT_KEYS = ["분석항목", "시료채취일자", "생태구명", "정점명", "수심"]


def read_meis_table(path: str | Path) -> pd.DataFrame:
    """엑셀(또는 엑셀 모양 HTML) 파일 하나를 읽어 머리글을 맞춘 문자열 DataFrame 으로 돌려준다."""
    path = Path(path)
    head = path.read_bytes()[:8]
    if head.startswith(b"PK"):
        raw = pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
    elif head.startswith(b"\xd0\xcf\x11\xe0"):
        raw = pd.read_excel(path, header=None, dtype=str, engine="xlrd")
    else:
        text = path.read_bytes().decode("utf-8", errors="replace")
        if "<" not in text[:200]:
            raise ValueError(f"엑셀도 HTML 도 아닌 파일: {path}")
        tables = pd.read_html(io.StringIO(text), header=None)
        if not tables:
            raise ValueError(f"HTML 안에 표가 없음: {path}")
        raw = max(tables, key=len)
        if not isinstance(raw.columns, pd.RangeIndex):  # <th> 가 있으면 read_html 이 머리글로 올려 버린다
            raw = pd.concat([pd.DataFrame([list(raw.columns)]), raw.set_axis(range(len(raw.columns)), axis=1)], ignore_index=True)
        raw = raw.astype(str).replace({"nan": None, "None": None})
    return _promote_header(raw)


def _promote_header(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    hdr = None
    for i in range(min(len(raw), 20)):
        if any(_clean(v) == HEADER_KEY for v in raw.iloc[i].tolist()):
            hdr = i
            break
    if hdr is None:
        raise ValueError(f"머리글 행({HEADER_KEY!r} 포함)을 찾지 못함")
    cols = [_clean(v) for v in raw.iloc[hdr].tolist()]
    df = raw.iloc[hdr + 1 :].reset_index(drop=True)
    df.columns = _unique(cols)
    df = df.dropna(how="all")
    for c in df.columns:
        df[c] = df[c].map(lambda v: _clean(v) if v is not None and v == v else None)
    return df.reset_index(drop=True)


def _clean(v) -> str:
    s = "" if v is None or (isinstance(v, float) and v != v) else str(v)
    s = s.replace(" ", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, n in enumerate(names):
        n = n or f"col{i + 1}"
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 0
        out.append(n)
    return out


@dataclass
class CombineResult:
    frame: pd.DataFrame  # 취합 결과(중복 제거, 정렬). 마지막 열 원본파일.
    files: pd.DataFrame  # 파일별 행 수·열 수·중복으로 빠진 행 수
    column_sets: list[tuple[str, list[str]]] = field(default_factory=list)  # 열 구성이 다른 파일 묶음


def combine_files(paths: Iterable[str | Path], *, dedupe: bool = True, sort: bool = True) -> CombineResult:
    """여러 파일을 세로로 이어 붙인다.

    - 열은 합집합. 파일마다 열 구성이 다르면(해수/퇴적물/생물 탭) 없는 열은 빈 값.
    - 같은 행이 두 파일에 있으면(페이지 경계 중복 등) 하나만 남기고 파일별로 몇 행 빠졌는지 기록한다.
    - 정렬 키는 SORT_KEYS 중 있는 열(문자열 정렬). sort=False 면 파일 순서 그대로.
    """
    frames, info = [], []
    for p in paths:
        p = Path(p)
        df = read_meis_table(p)
        df[SOURCE_COL] = p.name
        frames.append(df)
        info.append({"파일": p.name, "행수": len(df), "열수": len(df.columns) - 1, "열": ", ".join(c for c in df.columns if c != SOURCE_COL)})
    if not frames:
        raise ValueError("취합할 파일이 없음")
    all_df = pd.concat(frames, ignore_index=True)
    data_cols = [c for c in all_df.columns if c != SOURCE_COL]

    removed = {f["파일"]: 0 for f in info}
    if dedupe:
        dup = all_df.duplicated(subset=data_cols, keep="first")
        for name, n in all_df.loc[dup, SOURCE_COL].value_counts().items():
            removed[name] = int(n)
        all_df = all_df.loc[~dup].reset_index(drop=True)
    for f in info:
        f["중복제거"] = removed[f["파일"]]

    if sort:
        keys = [k for k in SORT_KEYS if k in all_df.columns]
        if keys:
            all_df = all_df.sort_values(keys, kind="stable", na_position="last").reset_index(drop=True)

    groups: dict[tuple[str, ...], list[str]] = {}
    for f in info:
        groups.setdefault(tuple(f["열"].split(", ")), []).append(f["파일"])
    column_sets = [(", ".join(k), v) for k, v in groups.items()]
    return CombineResult(all_df[data_cols + [SOURCE_COL]], pd.DataFrame(info), column_sets)
