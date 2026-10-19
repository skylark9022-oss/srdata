"""공공데이터포털(data.go.kr) 방식의 KOEM 오픈API 호출.

공공데이터포털 오픈API 공통 규격:
    요청   serviceKey(인증키), pageNo(페이지 번호, 1부터), numOfRows(한 페이지 건수)
    응답   response > header > resultCode("00" 이면 정상) / resultMsg
           response > body > items > item (항목 리스트), totalCount, pageNo, numOfRows
    인증·호출 한도 오류는 다른 모양으로 온다:
           OpenAPI_ServiceResponse > cmmMsgHeader > returnReasonCode / returnAuthMsg / errMsg

인증키는 .env 의 DATA_GO_KR_KEY 에 "디코딩된" 키를 넣는다(requests 가 URL 인코딩을 한 번 하므로
이미 인코딩된 키를 넣으면 %25 로 두 번 인코딩되어 SERVICE_KEY_IS_NOT_REGISTERED 류의 오류가 난다).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from srdata.api import ApiClient
from srdata.api.client import _dig
from srdata.config import env

from .datasets import DATASETS, Dataset

log = logging.getLogger(__name__)

SERVICE_KEY_ENV = "DATA_GO_KR_KEY"

# 공공데이터포털 오픈API 공통 오류 코드(resultCode / returnReasonCode). 참고용이며,
# 예외 메시지에는 응답에 들어 있는 resultMsg/returnAuthMsg 를 그대로 붙인다.
RESULT_CODES = {
    "00": "NORMAL_SERVICE",
    "01": "APPLICATION_ERROR",
    "02": "DB_ERROR",
    "03": "NODATA_ERROR",
    "04": "HTTP_ERROR",
    "05": "SERVICETIME_OUT",
    "10": "INVALID_REQUEST_PARAMETER_ERROR",
    "11": "NO_MANDATORY_REQUEST_PARAMETERS_ERROR",
    "12": "NO_OPENAPI_SERVICE_ERROR",
    "20": "SERVICE_ACCESS_DENIED_ERROR",
    "21": "TEMPORARILY_DISABLE_THE_SERVICEKEY_ERROR",
    "22": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
    "30": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "31": "DEADLINE_HAS_EXPIRED_ERROR",
    "32": "UNREGISTERED_IP_ERROR",
    "33": "UNSIGNED_CALL_ERROR",
    "99": "UNKNOWN_ERROR",
}
NODATA = "03"


class DataGoKrError(RuntimeError):
    def __init__(self, code: str | None, msg: str | None) -> None:
        name = RESULT_CODES.get(code or "", "")
        super().__init__(f"API 오류 resultCode={code} ({name}) {msg or ''}".strip())
        self.code = code
        self.msg = msg


def check_result(data: Any) -> None:
    """응답 dict 를 보고 오류면 DataGoKrError 를 낸다. 정상("00")이나 자료 없음("03")은 통과."""
    hdr = _dig(data, ["OpenAPI_ServiceResponse", "cmmMsgHeader"])
    if isinstance(hdr, dict):  # 인증키·트래픽 오류 (게이트웨이 응답)
        raise DataGoKrError(hdr.get("returnReasonCode"), hdr.get("returnAuthMsg") or hdr.get("errMsg"))
    header = _dig(data, ["response", "header"])
    if not isinstance(header, dict):
        raise DataGoKrError(None, f"알 수 없는 응답 형식: {str(data)[:200]}")
    code = str(header.get("resultCode", ""))
    if code not in ("00", "0", NODATA):
        raise DataGoKrError(code, header.get("resultMsg"))


def fetch(
    dataset: str | Dataset,
    params: dict[str, Any] | None = None,
    *,
    service_key: str | None = None,
    page_size: int = 100,
    max_pages: int | None = None,
    timeout: float = 30.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """DATASETS 의 데이터셋 하나를 전부 받아 (행 리스트, 메타정보) 로 돌려준다.

    params: 데이터셋 기본 파라미터에 덮어쓸 요청 변수.
    service_key: 없으면 환경변수 DATA_GO_KR_KEY.
    meta: 요청 주소·파라미터(키는 가림)·호출 시각·건수. 엑셀 "메타" 시트와 원본 JSON 에 함께 남긴다.
    """
    ds = DATASETS[dataset] if isinstance(dataset, str) else dataset
    merged = {**ds.params, **(params or {})}
    return fetch_url(
        ds.url,
        merged,
        items_path=list(ds.items_path),
        total_path=list(ds.total_path) if ds.total_path else None,
        page_param=ds.page_param,
        size_param=ds.size_param,
        service_key=service_key,
        page_size=page_size,
        max_pages=max_pages,
        timeout=timeout,
        dataset_key=ds.key,
        title=ds.title,
    )


def fetch_url(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    items_path: list[str] | None = None,
    total_path: list[str] | None = ("response", "body", "totalCount"),
    page_param: str = "pageNo",
    size_param: str = "numOfRows",
    service_key: str | None = None,
    page_size: int = 100,
    max_pages: int | None = None,
    timeout: float = 30.0,
    dataset_key: str = "",
    title: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """DATASETS 에 없는 주소를 바로 호출할 때. 반환값은 fetch 와 같다."""
    key = service_key or env(SERVICE_KEY_ENV, required=True)
    items_path = items_path or ["response", "body", "items", "item"]
    client = ApiClient(url, default_params={"serviceKey": key}, timeout=timeout)
    started = dt.datetime.now()
    rows = client.fetch_all(
        url,
        params or {},
        items_path=items_path,
        total_path=list(total_path) if total_path else None,
        page_param=page_param,
        size_param=size_param,
        page_size=page_size,
        max_pages=max_pages,
        check=check_result,
    )
    meta = {
        "dataset": dataset_key,
        "title": title,
        "url": url,
        "params": {k: v for k, v in (params or {}).items()},  # 인증키는 넣지 않는다
        "page_size": page_size,
        "fetched_at": started.isoformat(timespec="seconds"),
        "rows": len(rows),
    }
    log.info("%s: %d행 (%s)", dataset_key or url, len(rows), started.strftime("%Y-%m-%d %H:%M"))
    return rows, meta
