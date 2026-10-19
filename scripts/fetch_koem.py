"""KOEM(해양환경공단) 오픈API → 엑셀.

    python scripts/fetch_koem.py list                                   # 등록된 데이터셋 목록
    python scripts/fetch_koem.py fetch auto_station                     # 데이터셋 전부 받기
    python scripts/fetch_koem.py fetch auto_station -p seaArea=서해 -p stationName=영산영암
    python scripts/fetch_koem.py fetch auto_station --max-pages 1       # 응답 모양만 먼저 확인할 때
    python scripts/fetch_koem.py url "http://apis.data.go.kr/B553931/service/.../getXxx" -p key=값 \
        --items-path response.body.items.item                           # 목록에 없는 주소를 바로 호출

인증키: .env 의 DATA_GO_KR_KEY (디코딩된 키). --key 로 직접 줄 수도 있다.

결과:
    data/raw/koem/<데이터셋>_<YYYYMMDD_HHMMSS>.json   원본 응답 행 + 요청 메타(인증키 제외)
    data/processed/koem_<데이터셋>.xlsx               시트 "데이터"(행), "메타"(요청 주소·파라미터·시각·건수)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from srdata.api import save_json
from srdata.config import PROCESSED_DIR, RAW_DIR, ensure_dirs
from srdata.excel import save_sheets
from srdata.koem import DATASETS, fetch, fetch_url, to_frame

log = logging.getLogger("koem")


def parse_params(pairs: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"-p 는 이름=값 형식이어야 합니다: {p}")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    return out


def save_outputs(name: str, rows: list[dict], meta: dict, out: Path | None) -> Path:
    stamp = meta["fetched_at"].replace("-", "").replace(":", "").replace("T", "_")
    raw_path = save_json({"meta": meta, "rows": rows}, RAW_DIR / "koem" / f"{name}_{stamp}.json")
    log.info("원본 저장: %s", raw_path)

    df = to_frame(rows)
    meta_df = pd.DataFrame(
        [{"항목": k, "값": json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v} for k, v in meta.items()]
    )
    out = out or PROCESSED_DIR / f"koem_{name}.xlsx"
    save_sheets(out, {"데이터": df, "메타": meta_df}, freeze_header=True)
    log.info("%d행 × %d열 → %s", len(df), len(df.columns), out)
    return out


def cmd_list() -> None:
    for ds in DATASETS.values():
        flag = "확인됨" if ds.verified else "미확인(첫 호출 때 응답 확인)"
        print(f"{ds.key:16s} {ds.title}  [{flag}]")
        print(f"{'':16s} {ds.url}")
        if ds.note:
            print(f"{'':16s} {ds.note}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="등록된 데이터셋 목록")

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("-p", "--param", action="append", help="요청 변수 이름=값 (여러 번 가능)")
        p.add_argument("--page-size", type=int, default=100)
        p.add_argument("--max-pages", type=int, help="받을 최대 페이지 수(시험 호출용)")
        p.add_argument("--key", help="인증키(없으면 .env 의 DATA_GO_KR_KEY)")
        p.add_argument("-o", "--out", type=Path, help="엑셀 저장 경로")

    p_fetch = sub.add_parser("fetch", help="등록된 데이터셋 받기")
    p_fetch.add_argument("dataset", choices=sorted(DATASETS))
    common(p_fetch)

    p_url = sub.add_parser("url", help="목록에 없는 주소를 바로 호출")
    p_url.add_argument("url")
    p_url.add_argument("--items-path", default="response.body.items.item", help="항목 리스트 키 경로(점으로 구분)")
    p_url.add_argument("--total-path", default="response.body.totalCount", help="전체 건수 키 경로. 'none' 이면 안 씀")
    p_url.add_argument("--name", default="adhoc", help="저장 파일 이름에 쓸 데이터셋 이름")
    common(p_url)

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list()
        return

    params = parse_params(args.param)
    if args.cmd == "fetch":
        rows, meta = fetch(args.dataset, params, service_key=args.key, page_size=args.page_size, max_pages=args.max_pages)
        name = args.dataset
    else:
        total = None if args.total_path.lower() == "none" else args.total_path.split(".")
        rows, meta = fetch_url(
            args.url, params, items_path=args.items_path.split("."), total_path=total,
            service_key=args.key, page_size=args.page_size, max_pages=args.max_pages, dataset_key=args.name,
        )
        name = args.name
    if not rows:
        log.warning("받은 행이 없습니다. 요청 변수나 응답 구조(items_path)를 확인하세요.")
        sys.exit(1)
    save_outputs(name, rows, meta, args.out)


if __name__ == "__main__":
    main()
