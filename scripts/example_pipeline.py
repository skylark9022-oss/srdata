"""실행 예시 스크립트.

PDF 의 표를 모두 뽑아 엑셀로 저장:
    python scripts/example_pipeline.py pdf data/raw/sample.pdf
    python scripts/example_pipeline.py pdf data/raw/sample.pdf --pages 3 4 5 -o data/processed/out.xlsx

API 호출 뼈대(주소·파라미터는 실제 API 에 맞게 수정):
    python scripts/example_pipeline.py api
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from srdata.api import ApiClient
from srdata.api.client import save_json
from srdata.config import PROCESSED_DIR, RAW_DIR, ensure_dirs, env
from srdata.excel import save_sheets
from srdata.pdf import extract_tables

log = logging.getLogger("pipeline")


def run_pdf(pdf: Path, out: Path | None, pages: list[int] | None) -> Path:
    tables = extract_tables(pdf, pages)
    if not tables:
        raise SystemExit(f"표를 찾지 못했습니다: {pdf}")
    sheets = {f"p{t.attrs['page']}_t{t.attrs['index'] + 1}": t for t in tables}
    out = out or PROCESSED_DIR / f"{pdf.stem}.xlsx"
    save_sheets(out, sheets)
    log.info("표 %d개 → %s", len(tables), out)
    return out


def run_api(out: Path | None) -> Path:
    # TODO: 실제 API 주소, 경로, items_path 로 바꾼다.
    client = ApiClient(
        "https://apis.data.go.kr/EXAMPLE",
        default_params={"serviceKey": env("DATA_GO_KR_KEY", required=True), "type": "json"},
    )
    rows = client.fetch_all("/items", items_path=["response", "body", "items", "item"])
    save_json(rows, RAW_DIR / "items.json")  # 원본 보관
    df = pd.DataFrame(rows)
    out = out or PROCESSED_DIR / "items.xlsx"
    save_sheets(out, {"items": df})
    log.info("%d행 → %s", len(df), out)
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pdf = sub.add_parser("pdf", help="PDF 표 → 엑셀")
    p_pdf.add_argument("pdf", type=Path)
    p_pdf.add_argument("--pages", type=int, nargs="*", help="추출할 페이지 번호(1부터). 생략하면 전체")
    p_pdf.add_argument("-o", "--out", type=Path)

    p_api = sub.add_parser("api", help="API → 엑셀")
    p_api.add_argument("-o", "--out", type=Path)

    args = parser.parse_args()
    if args.cmd == "pdf":
        run_pdf(args.pdf, args.out, args.pages)
    elif args.cmd == "api":
        run_api(args.out)


if __name__ == "__main__":
    main()
