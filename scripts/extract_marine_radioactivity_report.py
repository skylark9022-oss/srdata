"""KINS 「해양환경방사능조사」 보고서 PDF의 표를 엑셀로 저장한다.

    python scripts/extract_marine_radioactivity_report.py
    python scripts/extract_marine_radioactivity_report.py data/raw/보고서.pdf -o data/processed/out.xlsx
    python scripts/extract_marine_radioactivity_report.py --all          # 제외 목록 무시, 캡션 있는 표 전부

결과 파일 구성 (원문 그대로 파일):
    목록      시트명·구분·표번호·제목·PDF쪽·인쇄쪽·행수·열수·각주·비고
    각주표시  값에서 떼어 낸 각주 위첨자("1)" 등)의 위치와 원문 값
    표2.2 …   표 하나당 시트 하나. 여러 쪽에 걸친 표([계속])는 한 시트로 합침.

값·불확도 분리 파일(기본으로 같이 만든다, --no-split 으로 생략. 이름은 "…_분리.xlsx"):
    설명      분리 규칙
    목록      위와 같음 + 분리한 열 목록
    분리불가  분리 규칙에 맞지 않아 비고 열에 원문을 그대로 둔 셀
    표2.2 …   측정값 열을 "열이름 | 값", "열이름 | 불확도", "열이름 | 최소" … 로 나눈 표

수동 보정 분리 파일("…_분리_보정.xlsx"): 원문 PDF 의 표기 오류로 분리되지 않는 셀을 MANUAL_CORRECTIONS 에 따라
고친 뒤 분리한 것. "보정" 시트에 시트·행·열·원문·보정값·근거를 남긴다. 그 밖의 내용은 분리 파일과 같다.

셀 값은 원문 텍스트 그대로("1.75±0.15", "<0.083"). 숫자만 있는 셀은 숫자로 바꾸되
소수 자릿수는 셀 표시 형식으로 원문대로 유지한다("1.60" → 1.6, 형식 0.00).
세로 병합 셀(해역·정점 등)은 아래 행에 같은 값을 채운다.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from srdata.analysis.measurements import PART_NAMES, split_measurement_columns
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


# 원문 표기 오류 수동 보정: (시트, 열 이름, 원문 텍스트) -> (보정 텍스트, 근거).
# 같은 시트·열에서 원문 텍스트가 정확히 일치하는 셀에만 적용한다.
MANUAL_CORRECTIONS = {
    ("표2.22", "137Cs 방사능농도 (mBq/kg-fresh) / 2020~2024년", "(15.3(<10.0~21.4)"): (
        "15.3(<10.0~21.4)",
        "원문의 여는 괄호 중복. 같은 열의 다른 셀(표 2.23 '28.3(20.3~33.7)' 등)이 모두 '값(최소~최대)' 형식이고, "
        "같은 표 평균 행의 과거 범위 '<10.0~<51.3' 의 최소값 '<10.0' 과 일치.",
    ),
}

SPLIT_GUIDE = [
    ("원칙", "측정값이 들어 있는 열(±, 부등호, 숫자 범위 중 하나라도 있는 열)만 성분 열로 나눈다. 나머지 열은 원문 파일과 같다."),
    ("열 이름", "\"원래 열 이름 | 성분\". 성분은 비고, 부등호, 값, 불확도, 최소부등호, 최소, 최대부등호, 최대. 그 열에서 한 번도 쓰이지 않은 성분 열은 만들지 않는다."),
    ("1.75±0.15", "값 1.75, 불확도 0.15"),
    ("<0.083", "부등호 <, 값 0.083 (최소검출가능농도 MDA 미만)"),
    ("65.4", "값 65.4"),
    ("1.04~1.94", "최소 1.04, 최대 1.94"),
    ("<0.104~0.261", "최소부등호 <, 최소 0.104, 최대 0.261 (최대 쪽 부등호는 최대부등호)"),
    ("1.24±0.20 (0.738~1.85)", "값 1.24, 불확도 0.20, 최소 0.738, 최대 1.85"),
    ("112(107~121)", "값 112, 최소 107, 최대 121"),
    ("- (<0.558)", "비고 -, 최소부등호 <, 최소 0.558 (괄호 안 값이 하나면 범위의 최소로 본다)"),
    ("-, -*", "비고에 그대로. 값 없음"),
    ("분리 불가", "규칙에 맞지 않는 문자열은 비고에 원문 그대로 두고 '분리불가' 시트에 적는다."),
    ("숫자 표시", "유효숫자를 지키려고 소수 자릿수를 셀 표시 형식으로 남긴다(1.60 → 값 1.6, 표시 1.60)."),
]


def apply_corrections(tables: list[ReportTable]) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """MANUAL_CORRECTIONS 를 적용한 DataFrame 과 보정 기록을 돌려준다. 원본 ReportTable 은 바꾸지 않는다."""
    frames: dict[str, pd.DataFrame] = {}
    log_rows: list[dict] = []
    for t in tables:
        df = t.to_frame().copy()
        for (sheet, col, original), (fixed, reason) in MANUAL_CORRECTIONS.items():
            if sheet != t.table_id or col not in df.columns:
                continue
            for i in df.index[df[col] == original]:
                df.at[i, col] = fixed
                log_rows.append({"시트명": sheet, "엑셀행": int(i) + 2, "열": col, "원문": original, "보정값": fixed, "근거": reason})
        frames[t.table_id] = df
    return frames, log_rows


def build_split_sheets(
    tables: list[ReportTable], raw_sheets: dict[str, pd.DataFrame], *, corrected: bool = False
) -> dict[str, pd.DataFrame]:
    index = raw_sheets["목록"].copy()
    index["분리한 열"] = ""
    unparsed_rows = []
    out: dict[str, pd.DataFrame] = {}
    frames, corrections = apply_corrections(tables) if corrected else ({t.table_id: t.to_frame() for t in tables}, [])
    for t in tables:
        sheet = t.table_id
        r = split_measurement_columns(frames[sheet])
        out[sheet] = r.frame
        index.loc[index["시트명"] == sheet, "분리한 열"] = "\n".join(r.split_columns)
        for i, col, text in r.unparsed:
            unparsed_rows.append({"시트명": sheet, "엑셀행": i + 2, "열": col, "원문": text})
    guide = pd.DataFrame(SPLIT_GUIDE, columns=["항목", "설명"])
    unparsed = pd.DataFrame(unparsed_rows, columns=["시트명", "엑셀행", "열", "원문"])
    sheets = {"설명": guide, "목록": index, "분리불가": unparsed}
    if corrected:
        guide.loc[len(guide)] = ["수동 보정", "원문 표기 오류를 '보정' 시트대로 고친 뒤 분리한 파일. 보정하지 않은 분리 파일은 '…_분리.xlsx'."]
        sheets["보정"] = pd.DataFrame(corrections, columns=["시트명", "엑셀행", "열", "원문", "보정값", "근거"])
    return {**sheets, **out}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path, nargs="?", default=DEFAULT_PDF)
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--all", action="store_true", help="제외 목록을 무시하고 캡션 있는 표 전부 저장")
    parser.add_argument("--exclude", nargs="*", default=sorted(DEFAULT_EXCLUDE), help="제외할 표 ID (예: 부록1_표1)")
    parser.add_argument("--no-split", action="store_true", help="값·불확도 분리 파일을 만들지 않음")
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

    if not args.no_split:
        split_out = args.out.with_name(args.out.stem + "_분리" + args.out.suffix)
        split_sheets = build_split_sheets(kept, sheets)
        save_sheets(split_out, split_sheets, freeze_header=True, numeric_text=table_sheets)
        log.info("분리 불가 셀 %d개", len(split_sheets["분리불가"]))
        log.info("저장: %s", split_out)

        fixed_out = args.out.with_name(args.out.stem + "_분리_보정" + args.out.suffix)
        fixed_sheets = build_split_sheets(kept, sheets, corrected=True)
        save_sheets(fixed_out, fixed_sheets, freeze_header=True, numeric_text=table_sheets)
        log.info("수동 보정 %d곳, 보정 후 분리 불가 셀 %d개", len(fixed_sheets["보정"]), len(fixed_sheets["분리불가"]))
        log.info("저장: %s", fixed_out)


if __name__ == "__main__":
    main()
