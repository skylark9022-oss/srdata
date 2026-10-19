"""DataFrame 을 엑셀 파일로 저장한다."""

from __future__ import annotations

from pathlib import Path
from typing import Collection, Mapping

import re

import pandas as pd

_MAX_SHEET_NAME = 31
_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
_LEADING_ZERO_RE = re.compile(r"^-?0\d")  # "007", "0012" (코드). "0", "0.5" 는 해당 없음
_FORBIDDEN = set('[]:*?/\\')


def save_sheets(
    path: str | Path,
    sheets: Mapping[str, pd.DataFrame] | pd.DataFrame,
    *,
    index: bool = False,
    autofit: bool = True,
    freeze_header: bool = False,
    numeric_text: bool | Collection[str] = False,
    keep_leading_zeros: bool = False,
) -> Path:
    """여러 DataFrame 을 시트별로 한 파일에 저장한다.

    sheets: {시트이름: DataFrame}. DataFrame 하나만 주면 "Sheet1" 로 저장.
    시트 이름은 엑셀 규칙(31자, 금지문자)에 맞게 자동 보정한다.
    freeze_header=True 이면 첫 행(머리글)을 틀 고정한다.
    numeric_text=True 이면 "12.20" 같은 숫자 문자열을 숫자로 바꾸되, 표시 형식으로 소수 자릿수를 원문대로 유지한다.
    시트 이름 집합을 주면 그 시트에만 적용한다.
    keep_leading_zeros=True 이면 "0012" 처럼 0 으로 시작하는 정수 문자열은 코드로 보고 문자열로 둔다.
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
            if freeze_header:
                writer.sheets[sheet].freeze_panes = "A2"
            if numeric_text is True or (numeric_text and name in numeric_text):
                numeric_strings_to_numbers(writer.sheets[sheet], skip_rows=1, keep_leading_zeros=keep_leading_zeros)
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


def numeric_strings_to_numbers(ws, *, skip_rows: int = 1, keep_leading_zeros: bool = False) -> int:
    """숫자만 있는 문자열 셀을 숫자로 바꾸고, 소수 자릿수를 표시 형식으로 남긴다.

    "1.60" → 1.6 (형식 0.00), "0" → 0, "102-04"·"2025.05.29" 는 그대로. 바꾼 셀 수를 돌려준다.
    """
    n = 0
    for row in ws.iter_rows(min_row=skip_rows + 1):
        for cell in row:
            v = cell.value
            if isinstance(v, str) and _NUMBER_RE.match(v):
                if keep_leading_zeros and _LEADING_ZERO_RE.match(v):
                    continue
                if "." in v:
                    cell.value = float(v)
                    cell.number_format = "0." + "0" * len(v.split(".")[1])
                else:
                    cell.value = int(v)
                n += 1
    return n
