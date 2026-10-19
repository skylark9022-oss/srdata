"""KOEM(해양환경공단, Korea Marine Environment Management Corporation) 데이터 수집.

공공데이터포털(data.go.kr)에 등록된 해양환경공단 오픈API 를 호출해 표(DataFrame)로 만든다.

    from srdata.koem import DATASETS, fetch, to_frame
    rows, meta = fetch("wemo_station", {"seaArea": "..."})
    df = to_frame(rows)

데이터셋 목록은 datasets.py 의 DATASETS 에 둔다(주소·파라미터는 data.go.kr 상세 페이지에서 확인해 추가).
"""

from .api import DataGoKrError, check_result, endpoint, fetch, fetch_url, find_items, normalize_key, probe
from .datasets import DATASETS, Dataset
from .tidy import to_frame

__all__ = ["DATASETS", "Dataset", "DataGoKrError", "check_result", "endpoint", "fetch", "fetch_url", "find_items",
           "normalize_key", "probe", "to_frame"]
