"""수집 대상 KOEM 데이터셋 목록.

각 항목은 공공데이터포털(data.go.kr)의 오픈API 상세 페이지에서 확인한 값을 적는다.
    url         요청 주소(엔드포인트). 상세 페이지 "요청주소"란 그대로.
    operation   상세기능(오퍼레이션) 이름. 있으면 url 뒤에 "/operation" 을 붙여 호출한다.
                End Point 만 알고 오퍼레이션을 모르면 비워 두고 실행할 때 --op 로 준다.
    labels      응답 항목 이름 → 한글 설명(상세 페이지 "출력결과" 표). 엑셀 "열설명" 시트에 쓴다.
    items_path  응답에서 항목 리스트까지의 키 경로. 공공데이터포털 표준 응답은
                response > body > items > item.
    total_path  전체 건수(totalCount)까지의 키 경로.
    params      기본으로 붙일 파라미터(서비스키·페이지 파라미터 제외).
    page_param / size_param  페이지 번호·페이지 크기 파라미터 이름(기본 pageNo / numOfRows).
    source      출처(상세 페이지 URL).
    verified    실제 호출로 확인했으면 True. False 면 명세를 보고 적은 것이므로 첫 호출 때 응답을 확인할 것.

새 데이터셋은 아래 DATASETS 에 한 줄 추가하면 scripts/fetch_koem.py 에서 바로 쓸 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    url: str
    operation: str = ""
    items_path: tuple[str, ...] = ("response", "body", "items", "item")
    total_path: tuple[str, ...] | None = ("response", "body", "totalCount")
    params: dict[str, str] = field(default_factory=dict)
    page_param: str = "pageNo"
    size_param: str = "numOfRows"
    labels: dict[str, str] = field(default_factory=dict)
    source: str = ""
    note: str = ""
    verified: bool = False


_STD = ("response", "body", "items", "item")

DATASETS: dict[str, Dataset] = {
    # 사용자가 활용신청·승인 후 받은 End Point (2026-10-19). 기관코드 1192000 = 해양수산부.
    # 상세 페이지: data.go.kr 15114322 "해양수산부_해양방사성물질 조사 정보 조회 서비스"(사용자 확인).
    # 오퍼레이션 이름·요청변수·출력결과는 아직 모름 → 첫 호출은 `fetch_koem.py probe ocean_radio_solid --op <오퍼레이션>`.
    "ocean_radio_solid": Dataset(
        key="ocean_radio_solid",
        title="해양방사능 조사정보(OceanRadioactiveSolidExaminationInfoService)",
        url="https://apis.data.go.kr/1192000/service/OceanRadioactiveSolidExaminationInfoService",
        operation="",
        source="https://www.data.go.kr/data/15114322/openapi.do",
        note="오퍼레이션 이름을 모름. data.go.kr 상세 페이지의 '상세기능'에서 확인해 operation 에 적거나 --op 로 준다.",
        verified=False,
    ),
    # 해양환경공단_해양수질자동측정망 하구 및 만 정점조회 서비스 (data.go.kr 15059971)
    # 해역명·정점명으로 정점 한글명, 해역코드, 경도·위도를 조회. 주소는 상세 페이지의 "요청주소"란에서 옮겨 적은 것.
    "auto_station": Dataset(
        key="auto_station",
        title="해양수질자동측정망 하구 및 만 정점조회",
        url="http://apis.data.go.kr/B553931/service/OceansWemoReInfoService1/getOceansWemoReInfo1",
        items_path=_STD,
        source="https://www.data.go.kr/data/15059971/openapi.do",
        note="요청 변수(해역명·정점명 등)는 상세 페이지의 요청변수 표를 보고 -p 로 넘긴다.",
        verified=False,
    ),
    # 아래는 자리만 잡아 둔 것. data.go.kr 상세 페이지에서 요청주소를 확인한 뒤 url 을 채운다.
    # "ctd": Dataset(key="ctd", title="해양환경측정망 CTD 관측서비스", url="…",
    #                source="https://www.data.go.kr/data/15059974/openapi.do"),
}
