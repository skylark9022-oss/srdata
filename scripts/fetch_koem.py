"""공공데이터포털 오픈API(해양방사능 조사정보 등) → 엑셀.

인증키는 실행할 때 직접 입력한다(화면에 보이지 않게 입력받음). 다른 방법:
    --key <인증키>          명령에 바로 적기
    .env 의 DATA_GO_KR_KEY  파일에 적어 두기(--save-key 로 입력한 키를 .env 에 저장할 수 있음)
Encoding 키(%2B 등 포함)와 Decoding 키 어느 쪽을 넣어도 된다.

순서:
    python scripts/fetch_koem.py list
    # 1) 응답 구조 확인: 한 번만 호출해 결과코드·항목 경로·항목 이름을 보여 주고 원문을 저장
    python scripts/fetch_koem.py probe ocean_radio_solid --op <오퍼레이션이름>
    # 2) 전부 받아 엑셀로
    python scripts/fetch_koem.py fetch ocean_radio_solid --op <오퍼레이션이름> -p 요청변수=값 -p ...
    python scripts/fetch_koem.py fetch ocean_radio_solid --op <오퍼레이션이름> --max-pages 1   # 시험
    # 목록에 없는 주소를 바로 호출
    python scripts/fetch_koem.py url "https://apis.data.go.kr/.../getXxx" -p 이름=값 --name xxx

결과:
    data/raw/koem/<데이터셋>_<YYYYMMDD_HHMMSS>.json   받은 행 + 요청 메타(인증키 제외)
    data/raw/koem/probe_<데이터셋>_<시각>.txt          probe 의 응답 원문
    data/processed/koem_<데이터셋>.xlsx               시트 "데이터", "메타", (항목 설명이 등록돼 있으면) "열설명"
"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import logging
import sys
from pathlib import Path

import pandas as pd

from srdata.api import save_json
from srdata.config import PROCESSED_DIR, RAW_DIR, ROOT_DIR, ensure_dirs, env
from srdata.excel import save_sheets
from srdata.koem import DATASETS, endpoint, fetch, fetch_url, normalize_key, probe, to_frame
from srdata.koem.api import SERVICE_KEY_ENV

log = logging.getLogger("koem")


def parse_params(pairs: list[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"-p 는 이름=값 형식이어야 합니다: {p}")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    return out


def get_key(args) -> str:
    """--key → .env/환경변수 → 직접 입력 순서로 인증키를 얻는다."""
    key = args.key or env(SERVICE_KEY_ENV)
    if key and not args.ask_key:
        return normalize_key(key)
    if not sys.stdin.isatty():
        raise SystemExit("인증키가 없습니다. --key 로 주거나 .env 의 DATA_GO_KR_KEY 에 적으세요.")
    key = getpass.getpass("공공데이터포털 인증키를 붙여 넣고 Enter (입력 내용은 화면에 보이지 않음): ")
    if not key.strip():
        raise SystemExit("인증키가 비어 있습니다.")
    key = normalize_key(key)
    if args.save_key:
        save_key_to_env(key)
    return key


def save_key_to_env(key: str) -> None:
    """입력한 키를 <프로젝트>/.env 의 DATA_GO_KR_KEY 로 저장한다(.env 는 git 에 올라가지 않음)."""
    path = ROOT_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{SERVICE_KEY_ENV}=")] + [f"{SERVICE_KEY_ENV}={key}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("인증키를 %s 에 저장했습니다.", path)


def save_outputs(name: str, rows: list[dict], meta: dict, out: Path | None, labels: dict[str, str] | None = None) -> Path:
    stamp = meta["fetched_at"].replace("-", "").replace(":", "").replace("T", "_")
    raw_path = save_json({"meta": meta, "rows": rows}, RAW_DIR / "koem" / f"{name}_{stamp}.json")
    log.info("원본 저장: %s", raw_path)

    # 값은 문자열로 넘기고 엑셀에 쓸 때 숫자로 바꾼다: "1.00" → 1 (표시 형식 0.00) 처럼 유효숫자 유지
    df = to_frame(rows, numeric=False)
    meta_df = pd.DataFrame(
        [{"항목": k, "값": json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v} for k, v in meta.items()]
    )
    sheets = {"데이터": df, "메타": meta_df}
    if labels:
        sheets["열설명"] = pd.DataFrame([{"항목": c, "설명": labels.get(c, "")} for c in df.columns])
    out = out or PROCESSED_DIR / f"koem_{name}.xlsx"
    save_sheets(out, sheets, freeze_header=True, numeric_text={"데이터"}, keep_leading_zeros=True)
    log.info("%d행 × %d열 → %s", len(df), len(df.columns), out)
    return out


def cmd_list() -> None:
    for ds in DATASETS.values():
        flag = "확인됨" if ds.verified else "미확인(첫 호출 때 응답 확인)"
        print(f"{ds.key:18s} {ds.title}  [{flag}]")
        print(f"{'':18s} {endpoint(ds.url, ds.operation) if ds.operation else ds.url + '  (+ /오퍼레이션)'}")
        if ds.note:
            print(f"{'':18s} {ds.note}")


def cmd_probe(name: str, url: str, params: dict, key: str, page_size: int) -> None:
    r = probe(url, params, service_key=key, page_size=page_size)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    raw = RAW_DIR / "koem" / f"probe_{name}_{stamp}.txt"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(r["text"], encoding="utf-8")
    print(f"요청 주소   : {url}")
    print(f"요청 변수   : {params or '(없음)'}  + pageNo=1, numOfRows={page_size}")
    print(f"HTTP 상태   : {r['status']}  ({r['content_type']})")
    print(f"결과        : {r['result']}")
    if r.get("items_path"):
        print(f"항목 경로   : {' > '.join(r['items_path'])}")
        print(f"전체 건수   : {r.get('total')}")
        print(f"항목 이름   : {', '.join(r['fields'])}")
    else:
        print("항목 리스트 : 찾지 못함(오퍼레이션 이름·필수 요청변수를 확인하세요)")
    print(f"응답 원문   : {raw}")
    print("--- 응답 앞부분 ---")
    print(r["text"][:1500])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="등록된 데이터셋 목록")

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("-p", "--param", action="append", help="요청 변수 이름=값 (여러 번 가능)")
        p.add_argument("--key", help="인증키(없으면 .env 의 DATA_GO_KR_KEY, 그것도 없으면 입력받음)")
        p.add_argument("--ask-key", action="store_true", help=".env 에 키가 있어도 새로 입력받는다")
        p.add_argument("--save-key", action="store_true", help="입력한 키를 .env 에 저장")

    def paging(p: argparse.ArgumentParser) -> None:
        p.add_argument("--page-size", type=int, default=100)
        p.add_argument("--max-pages", type=int, help="받을 최대 페이지 수(시험 호출용)")
        p.add_argument("-o", "--out", type=Path, help="엑셀 저장 경로")

    p_probe = sub.add_parser("probe", help="한 번 호출해 응답 구조 확인")
    p_probe.add_argument("dataset", choices=sorted(DATASETS))
    p_probe.add_argument("--op", help="오퍼레이션 이름(End Point 뒤에 붙음)")
    p_probe.add_argument("--rows", type=int, default=3, help="받아 볼 행 수")
    common(p_probe)

    p_fetch = sub.add_parser("fetch", help="등록된 데이터셋 전부 받기")
    p_fetch.add_argument("dataset", choices=sorted(DATASETS))
    p_fetch.add_argument("--op", help="오퍼레이션 이름(End Point 뒤에 붙음)")
    common(p_fetch)
    paging(p_fetch)

    p_url = sub.add_parser("url", help="목록에 없는 주소를 바로 호출")
    p_url.add_argument("url")
    p_url.add_argument("--items-path", default="response.body.items.item", help="항목 리스트 키 경로(점으로 구분)")
    p_url.add_argument("--total-path", default="response.body.totalCount", help="전체 건수 키 경로. 'none' 이면 안 씀")
    p_url.add_argument("--name", default="adhoc", help="저장 파일 이름에 쓸 데이터셋 이름")
    common(p_url)
    paging(p_url)

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list()
        return

    params = parse_params(args.param)
    if args.cmd in ("probe", "fetch"):
        ds = DATASETS[args.dataset]
        op = args.op if args.op is not None else ds.operation
        if not op:
            log.warning("오퍼레이션 이름 없이 End Point 만으로 호출합니다. 오류가 나면 --op 를 주세요.")
    key = get_key(args)

    if args.cmd == "probe":
        cmd_probe(args.dataset, endpoint(ds.url, op), {**ds.params, **params}, key, args.rows)
        return
    if args.cmd == "fetch":
        rows, meta = fetch(ds, params, service_key=key, page_size=args.page_size, max_pages=args.max_pages, operation=op)
        name, labels = args.dataset, ds.labels
    else:
        total = None if args.total_path.lower() == "none" else args.total_path.split(".")
        rows, meta = fetch_url(
            args.url, params, items_path=args.items_path.split("."), total_path=total,
            service_key=key, page_size=args.page_size, max_pages=args.max_pages, dataset_key=args.name,
        )
        name, labels = args.name, None
    if not rows:
        log.warning("받은 행이 없습니다. 먼저 probe 로 결과코드와 응답 구조를 확인하세요.")
        sys.exit(1)
    save_outputs(name, rows, meta, args.out, labels)


if __name__ == "__main__":
    main()
