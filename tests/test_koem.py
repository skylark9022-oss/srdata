"""KOEM 호출 코드를 가짜 응답으로 검증한다(실제 네트워크 호출 없음)."""

import json

import pandas as pd
import pytest
import requests

from srdata.api import ApiClient, xml_to_dict
from srdata.koem import DataGoKrError, Dataset, check_result, fetch, to_frame


def _resp(body: str, status: int = 200) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = body.encode("utf-8")
    r.encoding = "utf-8"
    return r


def _json_page(items, total, page, size):
    return json.dumps(
        {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                      "body": {"items": {"item": items}, "numOfRows": size, "pageNo": page, "totalCount": total}}},
        ensure_ascii=False,
    )


class FakeSession:
    """requests.Session 대역. 호출 파라미터를 기록하고 페이지별 응답을 돌려준다."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.pages[int(params["pageNo"]) - 1]


def test_fetch_pages_until_total_count(monkeypatch):
    items1 = [{"stationName": "A", "lat": "35.1", "lon": "129.0"}, {"stationName": "B", "lat": "35.2", "lon": "129.1"}]
    items2 = [{"stationName": "C", "lat": "35.3", "lon": "129.2"}]
    fake = FakeSession([_resp(_json_page(items1, 3, 1, 2)), _resp(_json_page(items2, 3, 2, 2))])
    monkeypatch.setattr(ApiClient, "__init__", _fake_init(fake))

    ds = Dataset(key="t", title="시험", url="http://example.invalid/getX")
    rows, meta = fetch(ds, {"seaArea": "남해"}, service_key="KEY", page_size=2)
    assert [r["stationName"] for r in rows] == ["A", "B", "C"]
    assert len(fake.calls) == 2
    url, params = fake.calls[0]
    assert params == {"serviceKey": "KEY", "seaArea": "남해", "pageNo": 1, "numOfRows": 2}
    assert meta["rows"] == 3 and "serviceKey" not in json.dumps(meta)

    df = to_frame(rows)
    assert list(df.columns) == ["stationName", "lat", "lon"]
    assert df["lat"].dtype.kind == "f" and not pd.api.types.is_numeric_dtype(df["stationName"])


def test_single_item_dict_and_xml(monkeypatch):
    xml = (
        "<response><header><resultCode>00</resultCode><resultMsg>OK</resultMsg></header>"
        "<body><items><item><stationName>A</stationName><val>1.5</val></item></items>"
        "<totalCount>1</totalCount></body></response>"
    )
    fake = FakeSession([_resp(xml)])
    monkeypatch.setattr(ApiClient, "__init__", _fake_init(fake))
    ds = Dataset(key="t", title="시험", url="http://example.invalid/getX")
    rows, _ = fetch(ds, service_key="KEY")
    assert rows == [{"stationName": "A", "val": "1.5"}]


def test_check_result_errors():
    check_result({"response": {"header": {"resultCode": "00"}, "body": {}}})
    check_result({"response": {"header": {"resultCode": "03", "resultMsg": "NODATA"}, "body": {}}})
    with pytest.raises(DataGoKrError, match="resultCode=22"):
        check_result({"response": {"header": {"resultCode": "22", "resultMsg": "LIMITED"}}})
    gateway = xml_to_dict(
        "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    with pytest.raises(DataGoKrError, match="SERVICE_KEY_IS_NOT_REGISTERED_ERROR"):
        check_result(gateway)


def test_xml_to_dict_repeated_children():
    d = xml_to_dict("<r><items><item><a>1</a></item><item><a>2</a></item></items><n/></r>")
    assert d == {"r": {"items": {"item": [{"a": "1"}, {"a": "2"}]}, "n": None}}


def test_to_frame_keeps_mixed_text():
    df = to_frame([{"code": "102-04", "v": "<0.5"}, {"code": "105-11", "v": "1.2"}])
    assert df["code"].tolist() == ["102-04", "105-11"]
    assert df["v"].tolist() == ["<0.5", "1.2"]


def _fake_init(fake):
    def __init__(self, base_url, *, default_params=None, headers=None, timeout=30.0, retries=3, backoff=1.5):
        self.base_url = base_url.rstrip("/")
        self.default_params = default_params or {}
        self.timeout, self.retries, self.backoff = timeout, retries, backoff
        self.session = fake
    return __init__
