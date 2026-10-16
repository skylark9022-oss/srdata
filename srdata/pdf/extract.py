"""pdfplumber 로 PDF에서 텍스트와 표를 뽑는다.

표 구조가 복잡한 PDF는 pdfplumber 기본 설정으로 잘 안 잡힐 수 있다.
그럴 때는 extract_tables(..., table_settings={...}) 로 조정한다.
(참고: https://github.com/jsvine/pdfplumber#table-extraction-settings)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Iterator

import pandas as pd
import pdfplumber


def iter_pages(pdf_path: str | Path, pages: Iterable[int] | None = None) -> Iterator[tuple[int, Any]]:
    """(페이지 번호(1부터), pdfplumber Page) 를 순서대로 낸다. pages 가 None 이면 전체."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        wanted = set(pages) if pages is not None else None
        for page in pdf.pages:
            no = page.page_number
            if wanted is None or no in wanted:
                yield no, page


def extract_text(pdf_path: str | Path, pages: Iterable[int] | None = None) -> dict[int, str]:
    """페이지별 텍스트. {페이지번호: 텍스트}"""
    return {no: (page.extract_text() or "") for no, page in iter_pages(pdf_path, pages)}


def extract_tables(
    pdf_path: str | Path,
    pages: Iterable[int] | None = None,
    *,
    header: bool = True,
    table_settings: dict[str, Any] | None = None,
    drop_empty: bool = True,
) -> list[pd.DataFrame]:
    """모든 페이지의 표를 DataFrame 리스트로 돌려준다.

    각 DataFrame 의 .attrs["page"] 에 페이지 번호, .attrs["index"] 에 페이지 내 순번이 들어 있다.
    header=True 이면 첫 행을 열 이름으로 쓴다.
    """
    frames: list[pd.DataFrame] = []
    for no, page in iter_pages(pdf_path, pages):
        for idx, table in enumerate(page.extract_tables(table_settings or {})):
            rows = [[_clean(c) for c in row] for row in table]
            if not rows:
                continue
            if header and len(rows) > 1:
                df = pd.DataFrame(rows[1:], columns=_unique(rows[0]))
            else:
                df = pd.DataFrame(rows)
            if drop_empty:
                df = df.dropna(how="all").dropna(axis=1, how="all")
            if df.empty:
                continue
            df.attrs["page"] = no
            df.attrs["index"] = idx
            frames.append(df)
    return frames


def _clean(cell: Any) -> Any:
    if cell is None:
        return None
    s = str(cell).replace("\n", " ").strip()
    return s or None


def _unique(names: list[Any]) -> list[str]:
    """열 이름이 비어 있거나 겹치면 col1, col2 … 식으로 보정한다."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, n in enumerate(names):
        name = str(n) if n else f"col{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out
