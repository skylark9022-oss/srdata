"""재시도와 페이지네이션을 갖춘 단순 REST 클라이언트.

공공데이터포털 류의 API(serviceKey, pageNo, numOfRows)를 염두에 두고 만들었지만
파라미터 이름을 바꿔서 다른 API에도 쓸 수 있다.
"""

from __future__ import annotations

import json
import logging
import time
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

    # ------------------------------------------------------------------ 페이지네이션
    def iter_pages(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        items_path: list[str],
        page_param: str = "pageNo",
        size_param: str = "numOfRows",
        page_size: int = 100,
        start_page: int = 1,
        max_pages: int | None = None,
    ) -> Iterator[list[dict[str, Any]]]:
        """페이지를 순서대로 돌며 각 페이지의 항목 리스트를 낸다.

        items_path: 응답 JSON에서 항목 리스트까지 가는 키 경로.
                    예) ["response", "body", "items", "item"]
        항목이 비어 있으면 끝난 것으로 본다.
        """
        page = start_page
        while True:
            if max_pages is not None and page - start_page >= max_pages:
                return
            data = self.get_json(path, {**(params or {}), page_param: page, size_param: page_size})
            items = _dig(data, items_path)
            if not items:
                return
            if isinstance(items, dict):  # 결과가 1건이면 리스트 대신 dict로 오는 API가 있다
                items = [items]
            yield items
            if len(items) < page_size:
                return
            page += 1

    def fetch_all(self, path: str, params: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        """iter_pages 의 결과를 하나의 리스트로 합친다. kwargs 는 iter_pages 와 같다."""
        rows: list[dict[str, Any]] = []
        for items in self.iter_pages(path, params, **kwargs):
            rows.extend(items)
        return rows


def save_json(data: Any, path: str | Path) -> Path:
    """원본 응답을 data/raw 등에 보관할 때 사용."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _dig(data: Any, keys: list[str]) -> Any:
    for k in keys:
        if not isinstance(data, dict) or k not in data:
            return None
        data = data[k]
    return data
