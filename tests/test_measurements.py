import pandas as pd

from srdata.analysis.measurements import is_measurement_column, parse_measurement, split_measurement_columns


def _p(s):
    d = parse_measurement(s)
    return {k: v for k, v in d.items() if v} if d is not None else None


def test_parse_basic_forms():
    assert _p("1.75±0.15") == {"값": "1.75", "불확도": "0.15"}
    assert _p("<0.083") == {"부등호": "<", "값": "0.083"}
    assert _p("65.4") == {"값": "65.4"}
    assert _p("1.04~1.94") == {"최소": "1.04", "최대": "1.94"}
    assert _p("<0.104~0.261") == {"최소부등호": "<", "최소": "0.104", "최대": "0.261"}
    assert _p("0.396~<0.971") == {"최소": "0.396", "최대부등호": "<", "최대": "0.971"}
    assert _p("<0.114~<0.208") == {"최소부등호": "<", "최소": "0.114", "최대부등호": "<", "최대": "0.208"}


def test_parse_with_parentheses_and_markers():
    assert _p("1.24±0.20 (0.738~1.85)") == {"값": "1.24", "불확도": "0.20", "최소": "0.738", "최대": "1.85"}
    assert _p("112(107~121)") == {"값": "112", "최소": "107", "최대": "121"}
    assert _p("- (<0.558)") == {"비고": "-", "최소부등호": "<", "최소": "0.558"}
    assert _p("-") == {"비고": "-"}
    assert _p("-*") == {"비고": "-*"}
    assert _p("") == {}
    assert _p("-0.40") == {"값": "-0.40"}


def test_parse_rejects_non_measurements():
    assert parse_measurement("연 6~24회") is None
    assert parse_measurement("(15.3(<10.0~21.4)") is None
    assert parse_measurement("3 kg ± 10%") is None
    assert parse_measurement("2025-01-16") is None


def test_split_columns():
    df = pd.DataFrame(
        {
            "정점": ["102-04", "103-11", "평균"],
            "수심": ["0", "200", ""],
            "137Cs": ["1.75±0.15", "<0.949", "1.24±0.20 (0.738~1.85)"],
            "과거": ["1.04~1.94", "1.05~1.76", "(15.3(<10.0~21.4)"],
        }
    )
    r = split_measurement_columns(df)
    assert list(r.frame.columns) == [
        "정점", "수심",
        "137Cs | 부등호", "137Cs | 값", "137Cs | 불확도", "137Cs | 최소", "137Cs | 최대",
        "과거 | 비고", "과거 | 최소", "과거 | 최대",
    ]
    assert r.frame.loc[1, "137Cs | 부등호"] == "<" and r.frame.loc[1, "137Cs | 값"] == "0.949"
    assert r.frame.loc[2, "137Cs | 최대"] == "1.85"
    assert r.unparsed == [(2, "과거", "(15.3(<10.0~21.4)")]
    assert r.frame.loc[2, "과거 | 비고"] == "(15.3(<10.0~21.4)"
    assert r.split_columns == ["137Cs", "과거"]
    assert not is_measurement_column(["0", "200", "500"])
