"""MEIS 엑셀 취합을 가짜 파일(xlsx, HTML-as-xls)로 검증한다."""

import pandas as pd

from srdata.meis import combine_files, read_meis_table

COLS = ["조사연도", "조사월", "분석항목", "생태구명", "정점명", "시료채취일자", "수심", "134Cs(mBq/kg)", "137Cs(mBq/kg)"]
ROWS1 = [
    ["2026", "6", "해수", "서남해역", "CW2311", "2026-06-11", "표층", "<0.43", "1.30 ± 0.16"],
    ["2026", "6", "해수", "서남해역", "CW2328", "2026-06-11", "표층", "<0.47", "1.25 ± 0.16"],
]
ROWS2 = [
    ["2026", "6", "해수", "서남해역", "CW2328", "2026-06-11", "표층", "<0.47", "1.25 ± 0.16"],  # 1쪽과 중복
    ["2025", "1", "해수", "대한해협", "CK2405", "2025-01-15", "표층", "<0.78", "1.48 ± 0.20"],
]


def _xlsx(path, rows, title=True):
    body = ([["정기조사(정밀분석) 분석결과"] + [None] * (len(COLS) - 1)] if title else []) + [COLS] + rows
    pd.DataFrame(body).to_excel(path, header=False, index=False)


def _html_xls(path, rows):
    html = "<html><body><table><tr>" + "".join(f"<th>{c}</th>" for c in COLS) + "</tr>"
    for r in rows:
        html += "<tr>" + "".join(f"<td>{v}</td>" for v in r) + "</tr>"
    html += "</table></body></html>"
    path.write_text(html, encoding="utf-8")


def test_read_xlsx_with_title_row(tmp_path):
    p = tmp_path / "p01.xlsx"
    _xlsx(p, ROWS1)
    df = read_meis_table(p)
    assert list(df.columns) == COLS
    assert df.iloc[0].tolist() == ROWS1[0]


def test_read_html_disguised_as_xls(tmp_path):
    p = tmp_path / "p02.xls"
    _html_xls(p, ROWS2)
    df = read_meis_table(p)
    assert list(df.columns) == COLS
    assert df["137Cs(mBq/kg)"].tolist() == ["1.25 ± 0.16", "1.48 ± 0.20"]


def test_combine_dedupes_and_sorts(tmp_path):
    _xlsx(tmp_path / "p01.xlsx", ROWS1)
    _html_xls(tmp_path / "p02.xls", ROWS2)
    r = combine_files([tmp_path / "p01.xlsx", tmp_path / "p02.xls"])
    assert len(r.frame) == 3
    assert r.frame["시료채취일자"].tolist() == ["2025-01-15", "2026-06-11", "2026-06-11"]
    assert r.frame["원본파일"].tolist() == ["p02.xls", "p01.xlsx", "p01.xlsx"]
    assert r.files.set_index("파일")["중복제거"].to_dict() == {"p01.xlsx": 0, "p02.xls": 1}
    assert len(r.column_sets) == 1


def test_combine_union_of_columns(tmp_path):
    _xlsx(tmp_path / "a.xlsx", ROWS1)
    extra = [r + ["0.10 ± 0.02"] for r in ROWS2]
    body = [COLS + ["3H(mBq/kg)"]] + extra
    pd.DataFrame(body).to_excel(tmp_path / "b.xlsx", header=False, index=False)
    r = combine_files([tmp_path / "a.xlsx", tmp_path / "b.xlsx"], sort=False)
    assert "3H(mBq/kg)" in r.frame.columns
    assert r.frame["3H(mBq/kg)"].isna().sum() == 2
    assert len(r.column_sets) == 2
