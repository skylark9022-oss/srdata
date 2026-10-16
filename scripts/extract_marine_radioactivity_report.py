"""KINS 「해양환경방사능조사」 보고서 PDF의 표를 엑셀로 저장한다.

    python scripts/extract_marine_radioactivity_report.py
    python scripts/extract_marine_radioactivity_report.py data/raw/보고서.pdf -o data/processed/out.xlsx
    python scripts/extract_marine_radioactivity_report.py --all          # 제외 목록 무시, 캡션 있는 표 전부

결과 파일 구성:
    목록      시트명·구분·표번호·제목·PDF쪽·인쇄쪽·행수·열수·각주·비고
    각주표시  값에서 떼어 낸 각주 위첨자("1)" 등)의 위치와 원문 값
    표2.2 …   표 하나당 시트 하나. 여러 쪽에 걸친 표([계속])는 한 시트로 합침.

셀 값은 원문 텍스트 그대로("1.75±0.15", "<0.083"). 숫자만 있는 셀은 숫자로 바꾸되
소수 자릿수는 셀 표시 형식으로 원문대로 유지한다("1.60" → 1.6, 형식 0.00).
세로 병합 셀(해역·정점 등)은 아래 행에 같은 값을 채운다.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from srdata.config import PROCESSED_DIR, RAW_DIR, ensure_dirs
from srdata.excel import save_sheets
from srdata.pdf import ReportTable, extract_report_tables

log = logging.getLogger("marine")

DEFAULT_PDF = RAW_DIR / "2025년+해양환경방사능조사보고서(vol+21).pdf"
DEFAULT_OUT = PROCESSED_DIR / "2025_해양환경방사능조사_vol21_표.xlsx"

# 측정값이 아닌 부록 표(조사내용 요약, 생물 종명 목록)는 기본으로 제외한다.
DEFAULT_EXCLUDE = {"부록1_표1", "부록1_표2", "부록1_표3", "부록1_표4", "부록3_표1"}

# 원문 PDF 에서 확인한 특이사항. 목록 시트의 비고에 적는다.
KNOWN_NOTES = {
    "표2.11": "원문 PDF 에서 머리글 순서(Pu 2025년, Pu 2020~2024년, 동위원소비 2025년, 동위원소비 2020~2024년)와 "
    "값 순서(Pu 2025년, 동위원소비 2025년, Pu 2020~2024년, 동위원소비 2020~2024년)가 어긋나 있음. "
    "표 2.7 의 105-11 정점 값과 대조하면 확인됨. 원문 그대로 추출했으므로 열 이름에 주의.",
}


def build_sheets(tables: list[ReportTable]) -> dict[str, pd.DataFrame]:
    index_rows, marker_rows = [], []
    sheets: dict[str, pd.DataFrame] = {}
    for t in tables:
        sheet = t.table_id
        df = t.to_frame()
        notes = list(t.notes)
        if t.table_id in KNOWN_NOTES:
            notes.append(KNOWN_NOTES[t.table_id])
        if t.markers:
            notes.append(f"각주 위첨자 제거 {len(t.markers)}곳 (각주표시 시트 참고)")
        index_rows.append(
            {
                "시트명": sheet,
                "구분": t.section,
                "표번호": t.number,
                "제목": t.title,
                "PDF쪽": ", ".join(map(str, t.pages)),
                "인쇄쪽": ", ".join(t.printed_pages),
                "행수": len(df),
                "열수": len(df.columns),
                "각주": "\n".join(t.footnotes),
                "비고": "\n".join(notes),
            }
        )
        for m in t.markers:
            marker_rows.append(
                {
                    "시트명": sheet,
                    "엑셀행": m.row + 2,  # 머리글 1행 + 1부터 세는 행 번호
                    "열": m.column,
                    "원문값": m.original,
                    "제거한표시": m.marker,
                }
            )
        sheets[sheet] = df
    out = {"목록": pd.DataFrame(index_rows), "각주표시": pd.DataFrame(marker_rows)}
    out.update(sheets)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path, nargs="?", default=DEFAULT_PDF)
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--all", action="store_true", help="제외 목록을 무시하고 캡션 있는 표 전부 저장")
    parser.add_argument("--exclude", nargs="*", default=sorted(DEFAULT_EXCLUDE), help="제외할 표 ID (예: 부록1_표1)")
    args = parser.parse_args()

    if not args.pdf.exists():
        raise SystemExit(f"PDF 가 없습니다: {args.pdf}")

    tables = extract_report_tables(args.pdf)
    exclude = set() if args.all else set(args.exclude)
    kept = [t for t in tables if t.table_id not in exclude]
    log.info("표 %d개 추출, %d개 제외, %d개 저장", len(tables), len(tables) - len(kept), len(kept))
    for t in tables:
        if t.table_id in exclude:
            log.info("  제외: %s %s", t.table_id, t.title)

    sheets = build_sheets(kept)
    table_sheets = {name for name in sheets if name not in ("목록", "각주표시")}
    save_sheets(args.out, sheets, freeze_header=True, numeric_text=table_sheets)
    log.info("저장: %s", args.out)


if __name__ == "__main__":
    main()
