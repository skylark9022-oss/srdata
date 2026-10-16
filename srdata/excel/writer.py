"""DataFrame 을 엑셀 파일로 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

_MAX_SHEET_NAME = 31
_FORBIDDEN = set('[]:*?/\\')


def save_sheets(
    path: str | Path,
    sheets: Mapping[str, pd.DataFrame] | pd.DataFrame,
    *,
    index: bool = False,
    autofit: bool = True,
) -> Path:
    """여러 DataFrame 을 시트별로 한 파일에 저장한다.

    sheets: {시트이름: DataFrame}. DataFrame 하나만 주면 "Sheet1" 로 저장.
    시트 이름은 엑셀 규칙(31자, 금지문자)에 맞게 자동 보정한다.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(sheets, pd.DataFrame):
        sheets = {"Sheet1": sheets}

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        used: set[str] = set()
        for name, df in sheets.items():
            sheet = _safe_sheet_name(name, used)
            df.to_excel(writer, sheet_name=sheet, index=index)
            if autofit:
                _autofit(writer.sheets[sheet], df, index=index)
    return path


def _safe_sheet_name(name: str, used: set[str]) -> str:
    base = "".join("_" if c in _FORBIDDEN else c for c in str(name)).strip("'") or "Sheet"
    base = base[:_MAX_SHEET_NAME]
    candidate, n = base, 1
    while candidate in used:
        n += 1
        suffix = f"_{n}"
        candidate = base[: _MAX_SHEET_NAME - len(suffix)] + suffix
    used.add(candidate)
    return candidate


def _autofit(ws, df: pd.DataFrame, *, index: bool, min_width: int = 6, max_width: int = 60) -> None:
    """열 너비를 내용 길이에 맞춘다(대략적인 값, 한글은 2칸으로 계산)."""
    cols = ([df.index.name or ""] if index else []) + [str(c) for c in df.columns]
    for i, col in enumerate(cols):
        series = df.index if (index and i == 0) else df.iloc[:, i - (1 if index else 0)]
        lengths = [_display_len(col)] + [_display_len(v) for v in series.head(500)]
        width = max(min_width, min(max_width, max(lengths) + 2))
        ws.column_dimensions[ws.cell(row=1, column=i + 1).column_letter].width = width


def _display_len(value) -> int:
    s = "" if value is None or (isinstance(value, float) and value != value) else str(value)
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)
