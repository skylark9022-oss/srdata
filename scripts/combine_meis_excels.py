"""MEIS 정기조사(정밀분석) 화면에서 한 페이지씩 내려받은 엑셀 파일들을 한 파일로 취합한다.

    python scripts/combine_meis_excels.py                       # data/raw/meis/*.xls* 전부
    python scripts/combine_meis_excels.py data/raw/meis/해수     # 폴더 지정
    python scripts/combine_meis_excels.py -o data/processed/meis_해양방사능_정기조사.xlsx

결과 시트:
    취합      원문 그대로(문자열). 마지막 열 "원본파일" 이 어느 파일에서 왔는지.
    분리      측정값 열("1.30 ± 0.16", "<0.43")을 값·불확도·부등호·최소·최대로 나눈 것
             (규칙은 srdata/analysis/measurements.py, PDF 보고서 분리 파일과 같음).
    파일목록  파일별 행수·열수·중복 제거 수·열 구성
    분리불가  분리 규칙에 안 맞아 비고에 원문을 둔 셀
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from srdata.analysis.measurements import split_measurement_columns
from srdata.config import PROCESSED_DIR, RAW_DIR, ensure_dirs
from srdata.excel import save_sheets
from srdata.meis import combine_files

log = logging.getLogger("meis")

DEFAULT_IN = RAW_DIR / "meis"
DEFAULT_OUT = PROCESSED_DIR / "meis_해양방사능_정기조사.xlsx"
PATTERNS = ("*.xlsx", "*.xls", "*.xlsm")


def find_files(folder: Path) -> list[Path]:
    files = sorted({p for pat in PATTERNS for p in folder.rglob(pat) if not p.name.startswith("~$")})
    return files


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", nargs="?", type=Path, default=DEFAULT_IN, help="엑셀 파일이 있는 폴더(하위 폴더 포함)")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-sort", action="store_true", help="파일 순서 그대로 둔다")
    parser.add_argument("--keep-duplicates", action="store_true", help="중복 행을 지우지 않는다")
    args = parser.parse_args()

    files = find_files(args.folder)
    if not files:
        raise SystemExit(f"엑셀 파일이 없습니다: {args.folder}")
    log.info("파일 %d개: %s …", len(files), ", ".join(p.name for p in files[:3]))

    r = combine_files(files, dedupe=not args.keep_duplicates, sort=not args.no_sort)
    if len(r.column_sets) > 1:
        log.warning("열 구성이 다른 파일 묶음 %d개(탭이 다른 파일이 섞였을 수 있음):", len(r.column_sets))
        for cols, names in r.column_sets:
            log.warning("  %s → %s", names[:3], cols)

    split = split_measurement_columns(r.frame)
    unparsed = pd.DataFrame(split.unparsed, columns=["행", "열", "원문"])
    sheets = {"취합": r.frame, "분리": split.frame, "파일목록": r.files, "분리불가": unparsed}
    save_sheets(args.out, sheets, freeze_header=True, numeric_text={"분리"})
    log.info("취합 %d행 × %d열 (중복 제거 %d행), 분리 열 %d개, 분리불가 %d셀 → %s",
             len(r.frame), len(r.frame.columns), int(r.files["중복제거"].sum()), len(split.split_columns), len(unparsed), args.out)


if __name__ == "__main__":
    main()
