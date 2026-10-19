"""임의의 PDF 에서 표를 모두 뽑아 엑셀로 저장한다(범용, 캡션·각주 처리 없음).

    python scripts/pdf_tables_to_excel.py data/raw/sample.pdf
    python scripts/pdf_tables_to_excel.py data/raw/sample.pdf --pages 3 4 5 -o data/processed/out.xlsx

KINS 해양환경방사능조사 보고서처럼 "표 N.N 제목" 캡션이 있는 보고서는
scripts/extract_marine_radioactivity_report.py 를 쓴다.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from srdata.config import PROCESSED_DIR, ensure_dirs
from srdata.excel import save_sheets
from srdata.pdf import extract_tables

log = logging.getLogger("pdf")


def run_pdf(pdf: Path, out: Path | None, pages: list[int] | None) -> Path:
    tables = extract_tables(pdf, pages)
    if not tables:
        raise SystemExit(f"표를 찾지 못했습니다: {pdf}")
    sheets = {f"p{t.attrs['page']}_t{t.attrs['index'] + 1}": t for t in tables}
    out = out or PROCESSED_DIR / f"{pdf.stem}.xlsx"
    save_sheets(out, sheets)
    log.info("표 %d개 → %s", len(tables), out)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", type=int, nargs="*", help="추출할 페이지 번호(1부터). 생략하면 전체")
    parser.add_argument("-o", "--out", type=Path)
    args = parser.parse_args()
    run_pdf(args.pdf, args.out, args.pages)


if __name__ == "__main__":
    main()
