"""재시도와 페이지네이션을 갖춘 단순 REST 클라이언트.

공공데이터포털(data.go.kr) 류의 API(serviceKey, pageNo, numOfRows)를 염두에 두고 만들었지만
파라미터 이름을 바꿔서 다른 API에도 쓸 수 있다. 응답이 JSON 이든 XML 이든 dict 로 바꿔 준다.
"""

from __future__ import annotations

import json
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterator

import requests

log = logging.getLogger(__name__)


class ApiClient:
    def __init__(
        self,
        base_url: str,
        *,
        default_params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        retries: int = 3,
        backoff: float = 1.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_params = default_params or {}
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.session = requests.Session()
        if headers:
            self.session.headers.update(headers)

    # ------------------------------------------------------------------ 기본 호출
    def get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        """GET 요청. 네트워크 오류나 5xx 응답이면 backoff 간격으로 재시도한다."""
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"
        merged = {**self.default_params, **(params or {})}

        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(url, params=merged, timeout=self.timeout)
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"{resp.status_code} server error", response=resp)
                resp.raise_for_status()
                return resp
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
                last_exc = exc
                if attempt == self.retries:
                    break
                wait = self.backoff ** attempt
                log.warning("요청 실패 (%d/%d): %s — %.1fs 후 재시도", attempt, self.retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"요청 실패: {url}") from last_exc

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.get(path, params).json()

    def get_data(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """응답 본문을 dict 로 돌려준다. JSON 이면 그대로, XML 이면 xml_to_dict 로 바꾼다.

        공공데이터포털 API 는 type/_type 파라미터가 없거나 오류일 때 XML 로 답하는 경우가 많아
        둘 다 받아 준다.
        """
        return parse_body(self.get(path, params))

    # ------------------------------------------------------------------ 페이지네이션
    def iter_pages(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        items_path: list[str],
        total_path: list[str] | None = None,
        page_param: str = "pageNo",
        size_param: str = "numOfRows",
        page_size: int = 100,
        start_page: int = 1,
        max_pages: int | None = None,
        check: Any = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """페이지를 순서대로 돌며 각 페이지의 항목 리스트를 낸다.

        items_path: 응답에서 항목 리스트까지 가는 키 경로. 예) ["response", "body", "items", "item"]
        total_path: 전체 건수까지 가는 키 경로. 주면 그 건수만큼 받은 뒤 멈춘다.
                    없으면 항목이 비거나 page_size 보다 적을 때 멈춘다.
        check: 응답 dict 를 받아 오류면 예외를 내는 함수(선택).
        """
        page = start_page
        received = 0
        while True:
            if max_pages is not None and page - start_page >= max_pages:
                return
            data = self.get_data(path, {**(params or {}), page_param: page, size_param: page_size})
            if check is not None:
                check(data)
            items = _dig(data, items_path)
            if not items:
                return
            if isinstance(items, dict):  # 결과가 1건이면 리스트 대신 dict로 오는 API가 있다
                items = [items]
            yield items
            received += len(items)
            total = _to_int(_dig(data, total_path)) if total_path else None
            if total is not None:
                if received >= total:
                    return
            elif len(items) < page_size:
                return
            page += 1

    def fetch_all(self, path: str, params: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        """iter_pages 의 결과를 하나의 리스트로 합친다. kwargs 는 iter_pages 와 같다."""
        rows: list[dict[str, Any]] = []
        for items in self.iter_pages(path, params, **kwargs):
            rows.extend(items)
        return rows


def parse_body(resp: requests.Response) -> Any:
    """응답 본문을 dict 로. JSON 이 아니면 XML 로 시도한다."""
    text = resp.text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)
    if text.startswith("<"):
        return xml_to_dict(text)
    try:
        return resp.json()
    except ValueError as exc:
        raise RuntimeError(f"JSON/XML 이 아닌 응답: {text[:200]!r}") from exc


def xml_to_dict(text: str) -> dict[str, Any]:
    """XML 문자열을 {태그: 값} 중첩 dict 로 바꾼다.

    같은 이름의 자식이 여럿이면 리스트, 하나면 dict/문자열. 빈 요소는 None.
    예) <response><body><items><item>…</item><item>…</item></items></body></response>
        → {"response": {"body": {"items": {"item": [ {...}, {...} ]}}}}
    """
    root = ET.fromstring(text)
    return {_local(root.tag): _elem_to_obj(root)}


def _elem_to_obj(elem: ET.Element) -> Any:
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        return text if text else None
    out: dict[str, Any] = {}
    for child in children:
        key = _local(child.tag)
        value = _elem_to_obj(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(value)
        else:
            out[key] = value
    return out


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def save_json(data: Any, path: str | Path) -> Path:
    """원본 응답을 data/raw 등에 보관할 때 사용."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _dig(data: Any, keys: list[str] | None) -> Any:
    if keys is None:
        return None
    for k in keys:
        if not isinstance(data, dict) or k not in data:
            return None
        data = data[k]
    return data


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
