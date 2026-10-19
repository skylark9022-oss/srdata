"""MEIS(해양환경정보포털) 해양방사능 정기조사(정밀분석) 화면의 엑셀을 페이지마다 내려받는다.

화면: https://www.meis.go.kr/oceansafety/analysis/analysisOceanPeriodic.do
화면은 한 번에 한 페이지(10건)만 엑셀로 주므로, 브라우저(Playwright + Chromium)를 자동으로 움직여
관측기간을 맞추고 → 검색 → 각 페이지에서 "엑셀" 클릭 → 다음 페이지 … 를 반복한다.

준비(로컬 PC, 하루 한 번):
    pip install -e .[web]
    playwright install chromium

실행:
    python scripts/download_meis_radioactivity.py                      # 해수 탭, 2025년 1월 ~ 현재
    python scripts/download_meis_radioactivity.py --tab 해저퇴적물
    python scripts/download_meis_radioactivity.py --from 2025 1 --to 2026 10 --out data/raw/meis/해수
    python scripts/download_meis_radioactivity.py --show               # 브라우저 창을 띄워 보면서 실행
    python scripts/download_meis_radioactivity.py --pages 1 2 3        # 특정 페이지만

결과: <out>/<탭>_p01.xlsx, <탭>_p02.xlsx … (서버가 주는 확장자를 그대로 둔다. .xls 일 수 있음)
이어서 scripts/combine_meis_excels.py 로 취합한다.

※ 이 스크립트는 화면의 글자(관측기간, 검색, 엑셀, 페이지 번호)를 기준으로 요소를 찾는다.
   화면 구조를 직접 확인하지 못한 상태에서 작성했으므로 첫 실행은 --show 로 눈으로 보면서 하고,
   요소를 못 찾으면 아래 SELECTORS 의 값을 화면에 맞게 고친다(브라우저 F12 로 확인).
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import sys
from pathlib import Path

from srdata.config import RAW_DIR, ensure_dirs

log = logging.getLogger("meis-download")

URL = "https://www.meis.go.kr/oceansafety/analysis/analysisOceanPeriodic.do"
TABS = ["해수", "해저퇴적물", "해양생물(패류)", "해양생물(어류)"]

# 화면 요소를 찾는 기준. 화면이 바뀌면 여기만 고친다.
SELECTORS = {
    "period_row": "tr:has(th:text-is('관측기간')), tr:has(td:text-is('관측기간')), li:has-text('관측기간'), div:has-text('관측기간')",
    "search_button": "button:has-text('검색'), a:has-text('검색'), input[type=submit][value*='검색']",
    "excel_button": "button:has-text('엑셀'), a:has-text('엑셀'), input[value*='엑셀']",
    "total_text": "text=/총\\s*[\\d,]+\\s*건/",
    "pagination": ".paging, .pagination, .paginate, div[class*='pag'], ul[class*='pag'], nav",
    "next_block": "a[title*='다음'], a:has-text('›'), a:has-text('>'), a[class*='next']",
}
TOTAL_RE = re.compile(r"총\s*([\d,]+)\s*건.*?\(\s*(\d+)\s*/\s*(\d+)\s*페이지")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    now = dt.date.today()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tab", choices=TABS, default="해수")
    parser.add_argument("--from", dest="start", nargs=2, type=int, default=[2025, 1], metavar=("연", "월"))
    parser.add_argument("--to", dest="end", nargs=2, type=int, default=[now.year, now.month], metavar=("연", "월"))
    parser.add_argument("--out", type=Path, help="저장 폴더(기본 data/raw/meis/<탭>)")
    parser.add_argument("--pages", type=int, nargs="*", help="받을 페이지 번호(기본 전부)")
    parser.add_argument("--show", action="store_true", help="브라우저 창을 보이게 실행")
    parser.add_argument("--wait", type=float, default=1.0, help="페이지 이동 후 기다리는 초")
    args = parser.parse_args()

    try:
        from playwright.sync_api import TimeoutError as PwTimeout, sync_playwright
    except ImportError:
        raise SystemExit("playwright 가 없습니다. `pip install -e .[web]` 후 `playwright install chromium` 을 실행하세요.")

    out = args.out or RAW_DIR / "meis" / args.tab
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.show)
        page = browser.new_page(accept_downloads=True)
        page.set_default_timeout(20_000)
        log.info("열기: %s", URL)
        page.goto(URL, wait_until="networkidle")

        # 1) 탭
        if args.tab != "해수":
            page.get_by_text(args.tab, exact=True).first.click()
            page.wait_for_load_state("networkidle")

        # 2) 관측기간: "관측기간" 글자가 있는 줄의 select 4개 = 시작연, 시작월, 끝연, 끝월
        row = page.locator(SELECTORS["period_row"]).first
        selects = row.locator("select")
        n = selects.count()
        if n < 4:
            raise SystemExit(f"관측기간 select 를 4개 찾지 못했습니다({n}개). SELECTORS['period_row'] 를 확인하세요.")
        _select(selects.nth(0), f"{args.start[0]}년", str(args.start[0]))
        _select(selects.nth(1), f"{args.start[1]}월", str(args.start[1]))
        _select(selects.nth(2), f"{args.end[0]}년", str(args.end[0]))
        _select(selects.nth(3), f"{args.end[1]}월", str(args.end[1]))

        # 3) 검색
        page.locator(SELECTORS["search_button"]).first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(int(args.wait * 1000))

        total, cur, last = _read_total(page)
        log.info("총 %s건, %d 페이지", total, last)
        wanted = args.pages or list(range(1, last + 1))

        # 4) 페이지마다 엑셀
        for p in wanted:
            if p != cur:
                _goto_page(page, p, args.wait)
                _, cur, _ = _read_total(page)
                if cur != p:
                    log.error("페이지 %d 로 이동하지 못함(현재 %d). 중단.", p, cur)
                    break
            try:
                with page.expect_download(timeout=60_000) as dl:
                    page.locator(SELECTORS["excel_button"]).first.click()
                download = dl.value
            except PwTimeout:
                log.error("페이지 %d: 엑셀 다운로드가 시작되지 않음. --show 로 확인하세요.", p)
                break
            suffix = Path(download.suggested_filename).suffix or ".xlsx"
            target = out / f"{args.tab}_p{p:02d}{suffix}"
            download.save_as(target)
            log.info("페이지 %d/%d → %s (%d bytes)", p, last, target.name, target.stat().st_size)
        browser.close()
    log.info("끝. 취합: python scripts/combine_meis_excels.py %s", out)


def _select(locator, label: str, value: str) -> None:
    """option 을 글자(label)로 고르고, 안 되면 value 로 고른다."""
    try:
        locator.select_option(label=label)
    except Exception:
        locator.select_option(value=value)


def _read_total(page) -> tuple[str, int, int]:
    """'총 372건 입니다.(1 / 38 페이지)' → ("372", 1, 38)"""
    text = page.locator(SELECTORS["total_text"]).first.inner_text()
    text = page.locator(SELECTORS["total_text"]).first.locator("xpath=..").inner_text() if "페이지" not in text else text
    m = TOTAL_RE.search(text.replace("\n", " "))
    if not m:
        raise SystemExit(f"건수/페이지 문구를 해석하지 못함: {text!r}")
    return m.group(1), int(m.group(2)), int(m.group(3))


def _goto_page(page, p: int, wait: float) -> None:
    """페이지 번호 링크를 누른다. 보이지 않으면(10개 블록 밖) '다음' 화살표를 눌러 블록을 옮긴 뒤 다시 찾는다."""
    for _ in range(50):
        link = page.locator(SELECTORS["pagination"]).get_by_text(str(p), exact=True)
        if link.count():
            link.first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(int(wait * 1000))
            return
        nxt = page.locator(SELECTORS["pagination"]).locator(SELECTORS["next_block"])
        if not nxt.count():
            break
        nxt.first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(int(wait * 1000))
    raise SystemExit(f"페이지 {p} 링크를 찾지 못했습니다. SELECTORS['pagination'] 을 확인하세요.")


if __name__ == "__main__":
    sys.exit(main())
