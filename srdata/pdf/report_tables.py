"""보고서 PDF의 '표 N.N 제목' 형식 표를 캡션·각주와 함께 뽑는다.

`extract.extract_tables` 보다 한 단계 더 처리한다.

- 병합 셀: pdfplumber 가 주는 셀 사각형(bbox)으로 세로 병합과 가로 병합을 구분한다.
  세로 병합은 아래 행에 같은 값을 채우고(아래로 채우기), 가로 병합은 빈 칸으로 둔다.
- 다단 머리글: 첫 열 머리글 셀이 세로로 차지하는 행 수만큼을 머리글로 보고
  "상위 / 하위" 형태의 한 줄 열 이름으로 합친다.
- 각주 위첨자: 본문보다 작은 글자로 찍힌 "1)" 같은 표시는 값에서 떼어 내고 위치를 기록한다.
- 캡션/각주: 표 바로 위의 "표 N.N …" 줄을 캡션으로, 표 아래의 "1) …" 줄을 각주로 잡는다.
- [계속] 표: 캡션이 같은 연속 표는 하나로 합친다(머리글은 첫 표의 것만).

한글(HWP)에서 만든 PDF 처럼 표 선이 분명한 문서를 가정한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import pdfplumber

log = logging.getLogger(__name__)

BBox = tuple[float, float, float, float]  # (x0, top, x1, bottom)

CAPTION_RE = re.compile(r"^표\s*(\d+(?:\.\d+)?)\.?\s+(.*)$")
CONTINUED_RE = re.compile(r"\s*[\[(]\s*계\s*속\s*[\])]\s*$")
FOOTNOTE_RE = re.compile(r"^\s*(\d+\)|※|\*|<\s*:|주\s*\))")
PAGE_NO_RE = re.compile(r"^-\s*([ivx\d]+)\s*-$", re.I)
FIGURE_RE = re.compile(r"^그림\s*\d")
APPENDIX_RE = re.compile(r"^부록\s*(\d+)\.")
NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass
class StrippedMarker:
    """각주 위첨자를 떼어 낸 셀의 기록."""

    row: int  # 본문 행 번호 (0부터, 머리글 제외)
    column: str
    original: str
    marker: str


@dataclass
class ReportTable:
    table_id: str  # 예: "표2.2", "부록1_표5"
    section: str  # "본문" 또는 "부록N"
    number: str  # "2.2", "5"
    title: str
    caption: str
    pages: list[int] = field(default_factory=list)  # PDF 쪽 번호(1부터)
    printed_pages: list[str] = field(default_factory=list)  # 쪽 하단에 찍힌 번호
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    markers: list[StrippedMarker] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=self.columns)


# ----------------------------------------------------------------------------
# 셀 격자 해석 (순수 함수 — 테스트 가능)
# ----------------------------------------------------------------------------

def resolve_grid(
    cells: list[list[BBox | None]],
    texts: list[list[str | None]],
    *,
    tol: float = 1.0,
) -> list[list[tuple[str, str]]]:
    """병합 셀을 풀어 (값, 종류) 격자를 만든다.

    종류: "cell"(실제 셀), "vmerge"(위 셀이 세로로 이어짐), "hmerge"(왼쪽 셀이 가로로 이어짐),
    "none"(셀 없음). vmerge/hmerge 모두 원본 셀의 값을 넣는다(본문에서 hmerge 는 호출 쪽이 비운다).
    """
    nrows = len(cells)
    ncols = max((len(r) for r in cells), default=0)
    col_x0 = [None] * ncols
    for row in cells:
        for j, c in enumerate(row):
            if c is not None and (col_x0[j] is None or c[0] < col_x0[j]):
                col_x0[j] = c[0]
    row_top = []
    for row in cells:
        tops = [c[1] for c in row if c is not None]
        row_top.append(min(tops) if tops else None)

    out: list[list[tuple[str, str]]] = []
    for i in range(nrows):
        line: list[tuple[str, str]] = []
        for j in range(ncols):
            c = cells[i][j] if j < len(cells[i]) else None
            if c is not None:
                t = texts[i][j] if j < len(texts[i]) else None
                line.append((t or "", "cell"))
                continue
            kind, value = "none", ""
            # 세로 병합: 같은 열의 위쪽 셀이 이 행까지 내려오는가
            if row_top[i] is not None:
                for r in range(i - 1, -1, -1):
                    up = cells[r][j] if j < len(cells[r]) else None
                    if up is not None:
                        if up[3] > row_top[i] + tol:
                            kind, value = "vmerge", out[r][j][0]
                        break
            # 가로 병합: 같은 행의 왼쪽 셀이 이 열까지 뻗는가
            if kind == "none" and col_x0[j] is not None:
                for k in range(j - 1, -1, -1):
                    left = cells[i][k] if k < len(cells[i]) else None
                    if left is not None:
                        if left[2] > col_x0[j] + tol:
                            kind, value = "hmerge", line[k][0]
                        break
                    # 왼쪽도 병합으로 비어 있으면 그 해석을 따른다
                    if line[k][1] == "vmerge":
                        # 왼쪽 위 셀이 세로+가로로 동시에 병합된 경우
                        src = _vmerge_source(cells, i, k, row_top, tol)
                        if src is not None and src[2] > col_x0[j] + tol:
                            kind, value = "vmerge", line[k][0]
                        break
                    if line[k][1] == "hmerge":
                        kind, value = "hmerge", line[k][0]
                        break
            line.append((value, kind))
        out.append(line)
    return out


def _vmerge_source(cells, i, j, row_top, tol) -> BBox | None:
    for r in range(i - 1, -1, -1):
        up = cells[r][j] if j < len(cells[r]) else None
        if up is not None:
            return up if up[3] > row_top[i] + tol else None
    return None


def header_row_count(cells: list[list[BBox | None]], *, tol: float = 1.0) -> int:
    """첫 열 머리글 셀(0,0)이 세로로 덮는 행 수. 최소 1."""
    if not cells or not cells[0] or cells[0][0] is None:
        return 1
    bottom = cells[0][0][3]
    n = 1
    for row in cells[1:]:
        tops = [c[1] for c in row if c is not None]
        if tops and min(tops) < bottom - tol:
            n += 1
        else:
            break
    return n


def flatten_headers(grid: list[list[tuple[str, str]]], nheader: int) -> list[str]:
    """머리글 행들을 열마다 "상위 / 하위" 로 합친다. 비거나 겹치는 이름은 보정."""
    ncols = len(grid[0]) if grid else 0
    names: list[str] = []
    for j in range(ncols):
        parts: list[str] = []
        for i in range(nheader):
            text = _one_line(grid[i][j][0])
            if text and (not parts or parts[-1] != text):
                parts.append(text)
        names.append(" / ".join(parts))
    return _unique(names)


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\n", " ")).strip()


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, n in enumerate(names):
        name = n or f"col{i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def coerce_number(value: Any) -> Any:
    """'12.2' 처럼 숫자만 있는 문자열은 숫자로. 나머지는 그대로."""
    if isinstance(value, str) and NUMBER_RE.match(value):
        return int(value) if "." not in value else float(value)
    return value


# ----------------------------------------------------------------------------
# 페이지 단위 처리
# ----------------------------------------------------------------------------

def footnote_marker_keys(page, *, body_size: float | None = None, ratio: float = 0.8) -> set[tuple]:
    """작은 글자로 찍힌 각주 표시("1)", "2)" …)의 글자 키 집합.

    같은 줄에서 작은 숫자 뒤에 작은 ')' 가 바로 따라오는 경우만 각주로 본다.
    동위원소 질량수("137Cs")처럼 뒤에 글자가 오는 위첨자는 건드리지 않는다.
    """
    chars = page.chars
    if not chars:
        return set()
    if body_size is None:
        sizes = pd.Series([round(c["size"], 1) for c in chars])
        body_size = float(sizes.mode().iloc[0])
    small = body_size * ratio
    keys: set[tuple] = set()
    # 읽기 순서 정렬: 줄(top) → x0
    order = sorted(range(len(chars)), key=lambda k: (round(chars[k]["top"]), chars[k]["x0"]))
    run: list[int] = []
    for k in order:
        c = chars[k]
        is_small = c["size"] < small
        adjacent = bool(run) and abs(chars[run[-1]]["top"] - c["top"]) <= 2 and c["x0"] - chars[run[-1]]["x1"] < 1.5
        if is_small and c["text"].isdigit():
            if not adjacent:
                run = []
            run.append(k)
        elif is_small and c["text"] == ")" and adjacent:
            for r in run:
                keys.add(_char_key(chars[r]))
            keys.add(_char_key(c))
            run = []
        else:
            run = []
    return keys


def _char_key(c) -> tuple:
    return (round(c["x0"], 2), round(c["top"], 2), c["text"])


def page_lines(page) -> list[dict]:
    try:
        return page.extract_text_lines()
    except Exception:  # pragma: no cover - 구버전 pdfplumber
        return []


def printed_page_number(lines: list[dict]) -> str | None:
    for line in reversed(lines[-3:]):
        m = PAGE_NO_RE.match(line["text"].strip())
        if m:
            return m.group(1)
    return None


def find_caption(lines: list[dict], table_top: float, prev_bottom: float) -> tuple[str, dict] | None:
    """표 위쪽(이전 표 아래쪽부터)에서 가장 가까운 '표 N.N …' 줄."""
    best = None
    for line in lines:
        if line["bottom"] > table_top + 2 or line["top"] < prev_bottom - 2:
            continue
        if CAPTION_RE.match(line["text"].strip()):
            if best is None or line["top"] > best["top"]:
                best = line
    return (best["text"].strip(), best) if best else None


def find_footnotes(lines: list[dict], table_bottom: float, next_top: float) -> list[str]:
    """표 아래쪽(다음 표 캡션 전까지)의 각주 줄. 들여쓴 다음 줄은 이어 붙인다."""
    notes: list[str] = []
    last_x0 = None
    for line in sorted(lines, key=lambda l: l["top"]):
        if line["top"] < table_bottom - 2 or line["bottom"] > next_top + 2:
            continue
        text = line["text"].strip()
        if CAPTION_RE.match(text) or FIGURE_RE.match(text) or PAGE_NO_RE.match(text):
            break
        if FOOTNOTE_RE.match(text):
            notes.append(text)
            last_x0 = line["x0"]
        elif notes and last_x0 is not None and line["x0"] > last_x0 + 4:
            notes[-1] += " " + text
        else:
            last_x0 = None
    return notes


def extract_report_tables(
    pdf_path: str | Path,
    pages: Iterable[int] | None = None,
    *,
    fill_down: bool = True,
    numbers: bool = False,
    merge_continued: bool = True,
) -> list[ReportTable]:
    """PDF 전체(또는 지정한 쪽)의 캡션 있는 표를 ReportTable 목록으로 돌려준다.

    캡션이 없는 표는 건너뛰고 로그로 남긴다.
    numbers=True 이면 숫자만 있는 셀을 숫자로 바꾼다(유효숫자 자릿수는 사라진다. 기본은 문자열 유지).
    """
    wanted = set(pages) if pages is not None else None
    tables: list[ReportTable] = []
    section = "본문"
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            no = page.page_number
            lines = page_lines(page)
            first = lines[0]["text"].strip() if lines else ""
            m = APPENDIX_RE.match(first)
            if m:
                section = f"부록{m.group(1)}"
            if wanted is not None and no not in wanted:
                continue
            printed = printed_page_number(lines)
            marker_keys = footnote_marker_keys(page)
            clean_page = page.filter(
                lambda obj: obj.get("object_type") != "char" or _char_key(obj) not in marker_keys
            ) if marker_keys else page

            raw_tables = page.find_tables()
            clean_tables = clean_page.find_tables() if marker_keys else raw_tables
            if len(clean_tables) != len(raw_tables):  # 선 구조는 같아야 한다
                log.warning("p%d: 각주 제거 전후 표 개수가 다름(%d/%d) — 원본 사용", no, len(raw_tables), len(clean_tables))
                clean_tables = raw_tables

            prev_bottom = 0.0
            for idx, (raw_t, clean_t) in enumerate(zip(raw_tables, clean_tables)):
                x0, top, x1, bottom = raw_t.bbox
                next_top = raw_tables[idx + 1].bbox[1] if idx + 1 < len(raw_tables) else page.height
                cap = find_caption(lines, top, prev_bottom)
                prev_bottom = bottom
                if cap is None:
                    log.info("p%d 표%d: 캡션 없음 — 건너뜀", no, idx + 1)
                    continue
                caption, _ = cap
                continued = bool(CONTINUED_RE.search(caption))
                base_caption = CONTINUED_RE.sub("", caption).strip()
                cm = CAPTION_RE.match(base_caption)
                number, title = cm.group(1), cm.group(2).strip()
                table_id = ("표" if section == "본문" else f"{section}_표") + number

                cells = [list(r.cells) for r in raw_t.rows]
                raw_texts = raw_t.extract()
                clean_texts = clean_t.extract()
                grid = resolve_grid(cells, clean_texts)
                nheader = header_row_count(cells)
                columns = flatten_headers(grid, nheader)
                raw_grid = resolve_grid(cells, raw_texts)

                rows: list[list[Any]] = []
                markers: list[StrippedMarker] = []
                for i in range(nheader, len(grid)):
                    row: list[Any] = []
                    for j, (val, kind) in enumerate(grid[i]):
                        if kind == "hmerge" or (kind == "vmerge" and not fill_down):
                            val = ""
                        raw_val = raw_grid[i][j][0]
                        if kind == "cell" and raw_val != val:
                            markers.append(StrippedMarker(len(rows), columns[j], _one_line(raw_val), _marker_diff(raw_val, val)))
                        val = _one_line(val)
                        row.append(coerce_number(val) if numbers else val)
                    if any(v != "" for v in row):
                        rows.append(row)

                rt = ReportTable(
                    table_id=table_id, section=section, number=number, title=title, caption=base_caption,
                    pages=[no], printed_pages=[printed] if printed else [], columns=columns, rows=rows,
                    footnotes=find_footnotes(lines, bottom, next_top), markers=markers,
                )
                if merge_continued and tables and tables[-1].table_id == table_id and (
                    continued or tables[-1].pages[-1] == no - 1
                ):
                    _append_continued(tables[-1], rt)
                else:
                    if continued:
                        rt.notes.append("[계속] 표인데 앞 표를 찾지 못함")
                    tables.append(rt)
    return tables


def _marker_diff(raw: str, clean: str) -> str:
    """원문과 제거본의 차이(떼어 낸 글자)를 돌려준다."""
    r, c = raw.replace("\n", ""), clean.replace("\n", "")
    out, k = [], 0
    for ch in r:
        if k < len(c) and c[k] == ch:
            k += 1
        else:
            out.append(ch)
    return "".join(out)


def _append_continued(base: ReportTable, cont: ReportTable) -> None:
    if cont.columns != base.columns:
        base.notes.append(f"p{cont.pages[0]} [계속] 표의 머리글이 다름: {cont.columns}")
        if len(cont.columns) != len(base.columns):
            base.notes.append(f"p{cont.pages[0]} 열 수가 달라 이어 붙이지 못함")
            return
    offset = len(base.rows)
    base.rows.extend(cont.rows)
    base.pages.extend(cont.pages)
    base.printed_pages.extend(cont.printed_pages)
    for f in cont.footnotes:
        if f not in base.footnotes:
            base.footnotes.append(f)
    for mk in cont.markers:
        mk.row += offset
        base.markers.append(mk)
