"""API 응답 행(dict 리스트)을 DataFrame 으로 정리한다."""

from __future__ import annotations

import re
from typing import Any, Iterable

import pandas as pd

_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def to_frame(rows: Iterable[dict[str, Any]], *, numeric: bool = True, columns: list[str] | None = None) -> pd.DataFrame:
    """행 리스트 → DataFrame.

    numeric=True 이면 값이 전부 숫자 문자열(빈 값 제외)인 열을 숫자로 바꾼다.
    "<0.5" 같은 부등호 값이나 정점 코드("102-04")가 섞인 열은 문자열로 남긴다.
    columns 를 주면 그 순서대로 열을 앞에 두고 나머지는 뒤에 붙인다.
    """
    df = pd.DataFrame(list(rows))
    if df.empty:
        return df
    if columns:
        front = [c for c in columns if c in df.columns]
        df = df[front + [c for c in df.columns if c not in front]]
    if numeric:
        for col in df.columns:
            s = df[col]
            if pd.api.types.is_numeric_dtype(s):
                continue
            vals = s.dropna().astype(str).str.strip()
            vals = vals[vals != ""]
            if len(vals) and vals.map(lambda v: bool(_NUMBER_RE.match(v))).all():
                df[col] = pd.to_numeric(s.replace({"": None}), errors="coerce")
    return df
