"""패키지가 임포트되고 기본 기능이 도는지 확인하는 최소 테스트."""

import pandas as pd

from srdata import config
from srdata.excel import save_sheets
from srdata.excel.writer import _safe_sheet_name


def test_paths_are_under_root():
    assert config.RAW_DIR.is_relative_to(config.ROOT_DIR)
    assert config.PROCESSED_DIR.is_relative_to(config.ROOT_DIR)


def test_save_sheets_roundtrip(tmp_path):
    df = pd.DataFrame({"이름": ["가", "나"], "값": [1, 2]})
    # "표/1" 과 "표:1" 은 금지문자 치환 후 둘 다 "표_1" 이 되므로 두 번째는 "_2" 가 붙어야 한다.
    out = save_sheets(tmp_path / "t.xlsx", {"표/1": df, "표:1": df})
    back = pd.read_excel(out, sheet_name=None)
    assert list(back) == ["표_1", "표_1_2"]
    assert back["표_1"].equals(df)


def test_sheet_name_dedup_and_length():
    used: set[str] = set()
    a = _safe_sheet_name("x" * 40, used)
    b = _safe_sheet_name("x" * 40, used)
    assert len(a) == 31 and len(b) == 31 and a != b
