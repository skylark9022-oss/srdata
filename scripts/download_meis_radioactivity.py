"""MEIS(해양환경정보포털) 해양방사능 정기조사(정밀분석) 분석결과의 엑셀을 페이지마다 내려받는다.

화면: https://www.meis.go.kr/oceansafety/analysis/analysisOceanPeriodic.do
사람이 하는 순서를 그대로 자동화한다(Playwright + Chromium):
    1. 접속 → "정기조사(정밀분석) 분석결과" 탭 → "해수" 탭
    2. 관측기간 2025년 1월 ~ 2025년 12월 → "검색"
    3. 각 페이지에서 "엑셀" → "엑셀 다운로드 목적 선택" 창에서 "연구(학술)" → "확인" → 파일 저장
    4. 다음 페이지로 이동해 3 을 반복

준비(로컬 PC, 하루 한 번):
    pip install -e .[web]
    playwright install chromium

실행:
    python scripts/download_meis_radioactivity.py --show          # 첫 실행: 브라우저 창을 보면서
    python scripts/download_meis_radioactivity.py                 # 창 없이
    python scripts/download_meis_radioactivity.py --pages 1 2 3   # 특정 페이지만
    python scripts/download_meis_radioactivity.py --from 2025 1 --to 2025 12 --purpose "연구(학술)"
    python scripts/download_meis_radioactivity.py --mode click    # 요청 재현 없이 매 페이지 클릭만

결과: data/raw/meis/해수/해수_p01.xlsx, 해수_p02.xlsx …  (서버가 주는 확장자 그대로. .xls 일 수 있음)
      이미 받은 페이지는 건너뛴다(--overwrite 로 다시 받기). 중간에 끊기면 그냥 다시 실행하면 이어 받는다.
      _debug/ 폴더에 화면 HTML·스크린샷·가로챈 엑셀 요청(requests.json)·select 목록을 남긴다.
      받은 뒤 파일별 행 수 합계를 화면의 "총 N건" 과 비교해 알려 준다.

화면 HTML 을 미리 알지 못해도 동작하도록, 요소는 화면에 보이는 글자로 찾는다.
    - 탭/버튼: "정기조사(정밀분석) 분석결과", "해수", "검색", "엑셀", "연구(학술)", "확인" 글자
    - 관측기간: 옵션이 "2025년"/"1월" 꼴인 <select> 를 화면 순서대로 시작연·시작월·끝연·끝월로 사용
    - 페이지 수: 본문의 "총 N건 … (p / P 페이지)" 문구
    - 페이지 이동: 쪽 번호 링크의 onclick/href 에 있는 함수(예: fn_link_page(2))를 직접 부르고,
      없으면 쪽 번호 링크를 누른다(10쪽 단위 블록은 "다음" 화살표로 넘김)
--mode auto(기본)는 1·2쪽을 클릭으로 받으면서 브라우저가 보내는 엑셀 요청을 가로채, 1→2 로 바뀐
파라미터를 페이지 번호로 보고 3쪽부터는 그 요청을 직접 보낸다(빠름). 실패하거나 앞쪽과 같은 파일이
오면 곧바로 클릭 방식으로 바꾼다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from srdata.config import RAW_DIR, ensure_dirs

log = logging.getLogger("meis-download")

URL = "https://www.meis.go.kr/oceansafety/analysis/analysisOceanPeriodic.do"
RESULT_TAB = "정기조사(정밀분석) 분석결과"
MEDIA_TABS = ["해수", "해저퇴적물", "해양생물(패류)", "해양생물(어류)"]
DEFAULT_PURPOSE = "연구(학술)"

YEAR_OPT = re.compile(r"^\s*(\d{4})\s*년?\s*$")
MONTH_OPT = re.compile(r"^\s*(\d{1,2})\s*월?\s*$")
TOTAL_RE = re.compile(r"총\s*([\d,]+)\s*건")
PAGE_RE = re.compile(r"\(\s*(\d+)\s*/\s*(\d+)\s*페이지")
JS_CALL_RE = re.compile(r"([A-Za-z_$][\w$.]*)\s*\(\s*['\"]?(\d+)['\"]?\s*\)")
EXCEL_MAGIC = (b"PK", b"\xd0\xcf\x11\xe0")

# 버튼·링크처럼 누를 수 있는 요소. 표 셀(td)의 "해수" 글자와 구분하기 위해 이것만 대상으로 한다.
CLICKABLE = "a, button, input[type=button], input[type=submit], [role=tab], [role=button], [onclick], label"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ensure_dirs()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=URL, help="화면 주소")
    parser.add_argument("--tab", choices=MEDIA_TABS, default="해수")
    parser.add_argument("--from", dest="start", nargs=2, type=int, default=[2025, 1], metavar=("연", "월"))
    parser.add_argument("--to", dest="end", nargs=2, type=int, default=[2025, 12], metavar=("연", "월"))
    parser.add_argument("--purpose", default=DEFAULT_PURPOSE, help="엑셀 다운로드 목적(창에 보이는 글자 그대로)")
    parser.add_argument("--out", type=Path, help="저장 폴더(기본 data/raw/meis/<탭>)")
    parser.add_argument("--pages", type=int, nargs="*", help="받을 페이지 번호(기본 전부)")
    parser.add_argument("--mode", choices=["auto", "click"], default="auto",
                        help="auto: 1·2쪽 클릭으로 요청을 알아낸 뒤 3쪽부터 재현(실패 시 클릭). click: 매 페이지 클릭")
    parser.add_argument("--show", action="store_true", help="브라우저 창을 보이게 실행")
    parser.add_argument("--wait", type=float, default=1.0, help="화면 이동 후 기다리는 초")
    parser.add_argument("--delay", type=float, default=0.5, help="페이지 사이 쉬는 초(서버 부담 줄이기)")
    parser.add_argument("--overwrite", action="store_true", help="이미 받은 파일도 다시 받는다")
    parser.add_argument("--browser-path", help="Chromium 실행 파일 경로(보통 필요 없음)")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright 가 없습니다. `pip install -e .[web]` 후 `playwright install chromium` 을 실행하세요.")
        return 2

    out = args.out or RAW_DIR / "meis" / args.tab
    debug = out / "_debug"
    debug.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        launch = {"headless": not args.show}
        if args.browser_path:
            launch["executable_path"] = args.browser_path
        browser = pw.chromium.launch(**launch)
        context = browser.new_context(accept_downloads=True, locale="ko-KR", viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(30_000)
        dl = Downloader(page, out, debug, args)
        code = 0
        try:
            dl.open()
            dl.select_tabs()
            dl.set_period()
            dl.search()
            total, cur, last = dl.read_total()
            dl.total = total
            log.info("검색 결과: 총 %s건, %d페이지 (현재 %d쪽)", total, last, cur)
            wanted = sorted(set(args.pages)) if args.pages else list(range(1, last + 1))
            bad = [n for n in wanted if n < 1 or n > last]
            if bad:
                raise RuntimeError(f"없는 페이지 번호: {bad} (1~{last})")
            dl.run(wanted)
        except Exception:
            dl.snapshot("99_error")
            log.exception("중단됨. %s 의 HTML·스크린샷·requests.json 을 확인하세요. 다시 실행하면 받은 쪽은 건너뜁니다.", debug)
            code = 1
        finally:
            browser.close()

    dl.report(full=not args.pages)
    if code == 0:
        log.info("취합: python scripts/combine_meis_excels.py \"%s\"", out)
    return code


# ----------------------------------------------------------------------------- 내려받기
class Downloader:
    def __init__(self, page, out: Path, debug: Path, args) -> None:
        self.page = page
        self.context = page.context
        self.out = out
        self.debug = debug
        self.args = args
        self.wait_ms = int(args.wait * 1000)
        self.total: str | None = None
        self.captured: dict[int, dict] = {}  # 쪽 번호 → 가로챈 엑셀 요청
        self.hashes: dict[int, str] = {}
        self.page_fn: str | None = None
        self.page_fn_checked = False
        self.dialogs: list[str] = []
        self.context.on("page", self._on_new_page)
        page.on("dialog", self._on_dialog)

    # ---- 브라우저 이벤트
    def _on_dialog(self, dialog) -> None:
        """alert/confirm("다운로드 하시겠습니까?" 등)은 기록하고 수락한다."""
        self.dialogs.append(dialog.message)
        log.info("알림창: %s", dialog.message.strip()[:100])
        dialog.accept()

    def _on_new_page(self, p) -> None:
        p.on("dialog", self._on_dialog)

    # ---- 화면 조작
    def open(self) -> None:
        log.info("열기: %s", self.args.url)
        self.page.goto(self.args.url, wait_until="domcontentloaded")
        self._settle()
        self.snapshot("01_loaded")

    def select_tabs(self) -> None:
        self._click_text(RESULT_TAB, "결과 탭")
        self._click_text(self.args.tab, "시료 탭")
        self.snapshot("02_tabs")

    def _click_text(self, text: str, what: str) -> None:
        """글자가 정확히 text 인 '누를 수 있는' 요소 중 화면에 보이는 첫 번째를 누른다."""
        exact = re.compile(rf"^\s*{re.escape(text)}\s*$")
        loc = self.page.locator(CLICKABLE).filter(has_text=exact)
        target = _first_visible(loc)
        if target is None:  # 탭이 <li> 등 일반 요소로 되어 있는 경우
            target = _first_visible(self.page.get_by_text(text, exact=True))
        if target is None:
            raise RuntimeError(f"{what} '{text}' 를 찾지 못함. _debug/01_loaded.html 확인")
        target.click()
        self._settle()
        log.info("%s 선택: %s", what, text)

    def set_period(self) -> None:
        """옵션 내용으로 연·월 select 를 찾아 화면 순서대로 시작연·시작월·끝연·끝월에 고른다."""
        info = self.page.evaluate(
            """() => Array.from(document.querySelectorAll('select')).map((s, i) => {
                 const r = s.getBoundingClientRect();
                 return {index: i, name: s.name || '', id: s.id || '',
                         visible: !!(r.width || r.height) && getComputedStyle(s).visibility !== 'hidden',
                         options: Array.from(s.options).map(o => ({text: o.text.trim(), value: o.value}))};
               })"""
        )
        (self.debug / "selects.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

        def is_year(s):
            return sum(bool(YEAR_OPT.match(o["text"])) for o in s["options"]) >= 2

        def is_month(s):
            return sum(bool(MONTH_OPT.match(o["text"])) for o in s["options"]) >= 12

        # 숨은 select(다른 탭용)가 있으면 보이는 것만 쓴다
        pool = [s for s in info if s["visible"]] or info
        years = [s for s in pool if is_year(s)]
        months = [s for s in pool if is_month(s) and not is_year(s)]
        if len(years) < 2 or len(months) < 2:
            raise RuntimeError(f"연 select {len(years)}개, 월 select {len(months)}개를 찾음(각 2개 필요). _debug/selects.json 확인")
        (y1, y2), (m1, m2) = years[:2], months[:2]
        start, end = self.args.start, self.args.end
        # 끝연을 먼저 고르면 시작연 목록이 바뀌는 화면도 있어 시작 → 끝 순서로 고르고, 끝에 다시 확인한다.
        for sel, want, rx in ((y1, start[0], YEAR_OPT), (m1, start[1], MONTH_OPT), (y2, end[0], YEAR_OPT), (m2, end[1], MONTH_OPT)):
            self._choose(sel, want, rx)
        for sel, want, rx in ((y1, start[0], YEAR_OPT), (m1, start[1], MONTH_OPT), (y2, end[0], YEAR_OPT), (m2, end[1], MONTH_OPT)):
            cur = self.page.locator("select").nth(sel["index"]).evaluate("s => s.options[s.selectedIndex]?.text || ''")
            m = rx.match(cur)
            if not m or int(m.group(1)) != want:
                raise RuntimeError(f"관측기간 select {sel['name'] or sel['index']} 이 {want} 가 아니라 {cur!r} 로 되어 있음")
        log.info("관측기간: %d년 %d월 ~ %d년 %d월", start[0], start[1], end[0], end[1])

    def _choose(self, sel: dict, want: int, rx: re.Pattern) -> None:
        live = self.page.locator("select").nth(sel["index"])
        options = live.evaluate("s => Array.from(s.options).map(o => ({text: o.text.trim(), value: o.value}))")
        opt = next((o for o in options if (m := rx.match(o["text"])) and int(m.group(1)) == want), None)
        if opt is None:
            raise RuntimeError(f"select {sel['name'] or sel['index']} 에 {want} 옵션이 없음: {[o['text'] for o in options][:20]}")
        live.select_option(value=opt["value"])
        self.page.wait_for_timeout(200)

    def search(self) -> None:
        btn = _first_visible(self.page.locator(CLICKABLE).filter(has_text=re.compile(r"^\s*검색\s*$")))
        if btn is None:
            btn = _first_visible(self.page.locator("input[type=submit][value*='검색'], input[type=button][value*='검색']"))
        if btn is None:
            raise RuntimeError("'검색' 버튼을 찾지 못함")
        btn.click()
        self._settle()
        self.snapshot("03_searched")

    def read_total(self) -> tuple[str, int, int]:
        body = self.page.inner_text("body").replace("\n", " ")
        t, p = TOTAL_RE.search(body), PAGE_RE.search(body)
        if not p:
            raise RuntimeError("본문에서 '(p / P 페이지)' 문구를 찾지 못함. 검색 결과가 없거나 화면 구조가 다름")
        return (t.group(1).replace(",", "") if t else "?"), int(p.group(1)), int(p.group(2))

    def current_page(self) -> int:
        return self.read_total()[1]

    def goto_page(self, n: int) -> None:
        if not self.page_fn_checked:
            self.page_fn = self._detect_page_fn()
            self.page_fn_checked = True
        if self.page_fn:
            self.page.evaluate(f"{self.page_fn}({n})")
        else:
            self._click_page_link(n)
        self._settle()
        cur = self.current_page()
        if cur != n:
            raise RuntimeError(f"{n}쪽으로 이동하지 못함(현재 {cur}쪽)")

    def _detect_page_fn(self) -> str | None:
        """쪽 번호 링크의 onclick/href 에서 'fn(번호)' 꼴을 찾아 함수 이름을 돌려준다."""
        links = self.page.evaluate(
            """() => Array.from(document.querySelectorAll('a, button')).filter(a => /^\\s*\\d+\\s*$/.test(a.textContent))
                 .map(a => ({text: a.textContent.trim(), href: a.getAttribute('href') || '', onclick: a.getAttribute('onclick') || ''}))"""
        )
        for link in links:
            for src in (link["onclick"], link["href"]):
                m = JS_CALL_RE.search(src)
                if m and m.group(2) == link["text"]:
                    fn = m.group(1)
                    if self.page.evaluate(f"typeof {fn} === 'function'"):
                        log.info("쪽 이동 함수: %s(n)", fn)
                        return fn
        log.info("쪽 이동 함수를 못 찾음 → 쪽 번호 링크를 눌러 이동")
        return None

    def _click_page_link(self, n: int) -> None:
        num = re.compile(rf"^\s*{n}\s*$")
        for _ in range(60):
            link = _first_visible(self.page.locator("a, button").filter(has_text=num))
            if link is not None:
                link.click()
                return
            cur = self.current_page()
            arrow = "a[title*='다음'], a[class*='next'], button[class*='next'], a:has-text('›'), a:has-text('>')" if n > cur else \
                    "a[title*='이전'], a[class*='prev'], button[class*='prev'], a:has-text('‹'), a:has-text('<')"
            nxt = _first_visible(self.page.locator(arrow))
            if nxt is None:
                break
            nxt.click()
            self._settle()
        raise RuntimeError(f"{n}쪽 링크를 찾지 못함")

    # ---- 엑셀
    def target(self, n: int, suffix: str) -> Path:
        return self.out / f"{self.args.tab}_p{n:02d}{suffix}"

    def existing(self, n: int) -> Path | None:
        return next(iter(sorted(self.out.glob(f"{self.args.tab}_p{n:02d}.*"))), None)

    def click_excel(self, n: int) -> Path:
        """현재 쪽에서 엑셀 → 목적 선택 → 확인. 그때 나간 요청을 가로채 self.captured[n] 에 둔다."""
        seen: list[dict] = []
        downloads: list = []

        def on_request(req):
            if req.resource_type in ("image", "stylesheet", "font", "script"):
                return
            seen.append({"url": req.url, "method": req.method, "post_data": req.post_data,
                         "content_type": req.headers.get("content-type", "")})

        def on_download(d):
            downloads.append(d)

        pages = list(self.context.pages)
        self.context.on("request", on_request)
        for p in pages:
            p.on("download", on_download)
        self.context.on("page", lambda p: p.on("download", on_download))
        try:
            excel = _first_visible(self.page.locator(CLICKABLE).filter(has_text=re.compile(r"^\s*엑셀\s*$")))
            if excel is None:
                excel = _first_visible(self.page.locator("[title*='엑셀'], [alt*='엑셀'], input[value*='엑셀']"))
            if excel is None:
                raise RuntimeError("'엑셀' 버튼을 찾지 못함")
            excel.click()
            self.choose_purpose()
            deadline = time.time() + 120
            while not downloads and time.time() < deadline:
                self.page.wait_for_timeout(250)
            if not downloads:
                self.snapshot(f"err_p{n:02d}_no_download")
                raise RuntimeError(f"{n}쪽: 엑셀 다운로드가 시작되지 않음")
            download = downloads[0]
            suffix = Path(download.suggested_filename or "").suffix or ".xlsx"
            target = self.target(n, suffix)
            download.save_as(target)
            if download.failure():
                raise RuntimeError(f"{n}쪽 다운로드 실패: {download.failure()}")
        finally:
            self.context.remove_listener("request", on_request)
            for p in self.context.pages:
                try:
                    p.remove_listener("download", on_download)
                except Exception:
                    pass
            for p in self.context.pages:  # 다운로드 때문에 열린 새 창은 닫는다
                if p is not self.page:
                    p.close()
        req = next((r for r in reversed(seen) if r["url"] == download.url), None)
        if req is None:  # 다운로드 주소가 리다이렉트된 경우: 엑셀처럼 보이는 마지막 요청
            req = next((r for r in reversed(seen) if re.search(r"excel|xls|down", r["url"], re.I)), seen[-1] if seen else None)
        if req:
            self.captured[n] = req
            (self.debug / "requests.json").write_text(json.dumps(self.captured, ensure_ascii=False, indent=2), encoding="utf-8")
        self._check_file(n, target)
        log.info("%d쪽 클릭 → %s (%d bytes, %s %s)", n, target.name, target.stat().st_size,
                 req["method"] if req else "?", (req["url"] if req else "?")[:90])
        return target

    def choose_purpose(self) -> None:
        """'엑셀 다운로드 목적 선택' 창에서 목적을 고르고 '확인'을 누른다. 창이 안 뜨면 그냥 넘어간다."""
        purpose = self.args.purpose
        exact = re.compile(rf"^\s*{re.escape(purpose)}\s*$")
        deadline = time.time() + 10
        chosen = None
        while time.time() < deadline:
            # 라디오/체크박스의 라벨, 또는 버튼·링크로 된 선택지
            for loc in (self.page.get_by_label(purpose, exact=True),
                        self.page.locator("label").filter(has_text=exact),
                        self.page.locator(CLICKABLE).filter(has_text=exact),
                        self.page.get_by_text(purpose, exact=True)):
                chosen = _first_visible(loc)
                if chosen is not None:
                    break
            if chosen is not None:
                break
            sel = self._purpose_select(purpose)
            if sel:
                chosen = sel
                break
            self.page.wait_for_timeout(250)
        if chosen is None:
            log.info("목적 선택 창이 보이지 않음 → 바로 다운로드를 기다림")
            return
        if chosen != "select":
            try:
                if chosen.evaluate("e => e.tagName === 'INPUT' && (e.type === 'radio' || e.type === 'checkbox')"):
                    chosen.check()
                else:
                    chosen.click()
            except Exception:
                chosen.click(force=True)
        self.snapshot("04_purpose", screenshot_only=True)

        ok = self._find_confirm()
        if ok is None:
            raise RuntimeError("목적 선택 창의 '확인' 버튼을 찾지 못함. _debug/04_purpose.png 확인")
        ok.click()
        log.debug("목적 '%s' 선택 후 확인", purpose)

    def _purpose_select(self, purpose: str):
        """목적이 <select> 로 되어 있는 경우 그 옵션을 고르고 'select' 를 돌려준다."""
        sels = self.page.locator("select")
        for i in range(sels.count()):
            s = sels.nth(i)
            if not s.is_visible():
                continue
            texts = s.evaluate("s => Array.from(s.options).map(o => o.text.trim())")
            if purpose in texts:
                s.select_option(label=purpose)
                return "select"
        return None

    def _find_confirm(self):
        """보이는 '확인' 버튼. 여러 개면 목적 글자가 있는 창 안의 것을 고른다."""
        exact = re.compile(r"^\s*확인\s*$")
        btns = self.page.locator("button, a, input[type=button], input[type=submit]").filter(has_text=exact)
        visible = [btns.nth(i) for i in range(btns.count()) if btns.nth(i).is_visible()]
        if not visible:
            inputs = self.page.locator("input[type=button][value='확인'], input[type=submit][value='확인']")
            visible = [inputs.nth(i) for i in range(inputs.count()) if inputs.nth(i).is_visible()]
        if len(visible) <= 1:
            return visible[0] if visible else None
        for b in visible:  # 목적 글자를 포함하는 가장 가까운 조상 안에 있는 확인 버튼
            if b.evaluate("(b, t) => { for (let e = b.parentElement; e; e = e.parentElement) if (e.innerText && e.innerText.includes(t)) return e !== document.body; return false; }",
                          self.args.purpose):
                return b
        return visible[-1]

    def find_page_param(self) -> tuple[str, str] | None:
        """1쪽·2쪽 요청을 비교해 (위치, 이름)을 찾는다. 위치는 'query' 또는 'body'."""
        a, b = self.captured.get(1), self.captured.get(2)
        if not a or not b or a["method"] != b["method"]:
            return None
        if "multipart" in (a.get("content_type") or "") or "json" in (a.get("content_type") or ""):
            return None
        qa = dict(parse_qsl(urlsplit(a["url"]).query, keep_blank_values=True))
        qb = dict(parse_qsl(urlsplit(b["url"]).query, keep_blank_values=True))
        pa = dict(parse_qsl(a["post_data"] or "", keep_blank_values=True))
        pb = dict(parse_qsl(b["post_data"] or "", keep_blank_values=True))
        cands = [("query", k) for k in qa if qa.get(k) == "1" and qb.get(k) == "2"]
        cands += [("body", k) for k in pa if pa.get(k) == "1" and pb.get(k) == "2"]
        # 페이지 번호 말고도 바뀐 값이 있으면(토큰 등) 재현이 위험하므로 쓰지 않는다
        other = [k for k in set(qa) | set(qb) if qa.get(k) != qb.get(k)] + [k for k in set(pa) | set(pb) if pa.get(k) != pb.get(k)]
        if len(cands) == 1 and len(other) == 1:
            return cands[0]
        if cands:
            log.info("페이지 파라미터 후보 %s, 그 밖에 바뀐 값 %s → 재현 대신 클릭", cands, other)
        return None

    def replay(self, n: int, where: str, key: str) -> Path:
        """가로챈 1쪽 요청에서 페이지 번호만 n 으로 바꿔 같은 브라우저 세션(쿠키 포함)으로 보낸다."""
        base = self.captured[1]
        parts = urlsplit(base["url"])
        query = parse_qsl(parts.query, keep_blank_values=True)
        body = parse_qsl(base["post_data"] or "", keep_blank_values=True)
        if where == "query":
            query = [(k, str(n) if k == key else v) for k, v in query]
        else:
            body = [(k, str(n) if k == key else v) for k, v in body]
        url = urlunsplit(parts._replace(query=urlencode(query)))
        req = self.context.request
        headers = {"Referer": self.page.url}
        if base["method"].upper() == "POST":
            headers["Content-Type"] = base.get("content_type") or "application/x-www-form-urlencoded"
            resp = req.post(url, data=urlencode(body), headers=headers)
        else:
            resp = req.get(url, headers=headers)
        data = resp.body()
        ctype = resp.headers.get("content-type", "")
        disp = resp.headers.get("content-disposition", "")
        looks_excel = data.startswith(EXCEL_MAGIC) or "attachment" in disp or "excel" in ctype or "spreadsheet" in ctype
        if not resp.ok or not looks_excel:
            raise RuntimeError(f"응답이 엑셀이 아님 (status {resp.status}, {ctype!r}, {len(data)} bytes)")
        suffix = next(iter(sorted(self.out.glob(f"{self.args.tab}_p01.*"))), Path("x.xlsx")).suffix
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp)
        if m and Path(m.group(1)).suffix:
            suffix = Path(m.group(1)).suffix
        target = self.target(n, suffix)
        target.write_bytes(data)
        self._check_file(n, target)
        log.info("%d쪽 재현 → %s (%d bytes)", n, target.name, len(data))
        return target

    def _check_file(self, n: int, path: Path) -> None:
        """빈 파일·오류 화면·바로 앞쪽과 똑같은 파일이면 예외."""
        data = path.read_bytes()
        if len(data) < 100:
            raise RuntimeError(f"{n}쪽 파일이 너무 작음({len(data)} bytes)")
        if not data.startswith(EXCEL_MAGIC) and b"<table" not in data[:200_000].lower():
            raise RuntimeError(f"{n}쪽 파일이 엑셀도 HTML 표도 아님(앞부분 {data[:80]!r})")
        h = hashlib.sha256(data).hexdigest()
        same = [k for k, v in self.hashes.items() if v == h and k != n]
        self.hashes[n] = h
        if same:
            path.unlink()
            raise RuntimeError(f"{n}쪽 파일이 {same[0]}쪽과 똑같음(페이지가 바뀌지 않았을 수 있음)")

    # ---- 전체 흐름
    def run(self, wanted: list[int]) -> None:
        if not self.args.overwrite:
            for n in wanted:
                if (p := self.existing(n)):
                    self.hashes[n] = hashlib.sha256(p.read_bytes()).hexdigest()
        todo = [n for n in wanted if self.args.overwrite or not self.existing(n)]
        skipped = [n for n in wanted if n not in todo]
        if skipped:
            log.info("이미 받은 쪽 %d개 건너뜀 (--overwrite 로 다시 받기)", len(skipped))
        if not todo:
            return

        param = None
        if self.args.mode == "auto" and len(todo) > 2 and 1 in wanted and 2 in wanted:
            # 1·2쪽은 클릭으로 받으면서 요청을 가로챈다(이미 받았어도 분석을 위해 다시 받는다).
            for n in (1, 2):
                self._ensure_page(n)
                self.click_excel(n)
                self._pause()
            param = self.find_page_param()
            if param:
                log.info("엑셀 요청의 페이지 파라미터: %s (%s) → 3쪽부터 직접 요청", param[1], param[0])
            else:
                log.info("페이지 파라미터를 특정하지 못함 → 매 페이지 클릭 (_debug/requests.json 참고)")
            todo = [n for n in todo if n not in (1, 2)]

        for i, n in enumerate(todo, 1):
            if param:
                try:
                    self.replay(n, *param)
                    self._pause()
                    continue
                except Exception as exc:
                    log.warning("%d쪽 직접 요청 실패(%s) → 이후 클릭 방식", n, exc)
                    param = None
            self._ensure_page(n)
            self.click_excel(n)
            self._pause()
            if i % 10 == 0:
                log.info("진행: %d/%d", i, len(todo))

    def _ensure_page(self, n: int) -> None:
        if self.current_page() != n:
            self.goto_page(n)

    def _pause(self) -> None:
        if self.args.delay > 0:
            self.page.wait_for_timeout(int(self.args.delay * 1000))

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        self.page.wait_for_timeout(self.wait_ms)

    # ---- 확인·진단
    def report(self, *, full: bool) -> None:
        """받은 파일별 행 수와 합계를 화면의 총 건수와 비교한다(취합은 하지 않음)."""
        files = sorted(self.out.glob(f"{self.args.tab}_p*.*"))
        log.info("받은 파일 %d개 → %s", len(files), self.out)
        if not files:
            return
        try:
            from srdata.meis import read_meis_table
        except Exception:
            return
        rows, problems = 0, []
        for f in files:
            try:
                rows += len(read_meis_table(f))
            except Exception as exc:
                problems.append(f"{f.name}: {exc}")
        for p in problems:
            log.warning("읽기 실패 %s", p)
        if full and self.total and self.total.isdigit():
            flag = "일치" if rows == int(self.total) else "불일치 — 빠진 쪽이나 중복이 있는지 확인"
            log.info("행 수 합계 %d / 화면 총 %s건 → %s", rows, self.total, flag)
        else:
            log.info("행 수 합계 %d", rows)

    def snapshot(self, name: str, *, screenshot_only: bool = False) -> None:
        try:
            if not screenshot_only:
                (self.debug / f"{name}.html").write_text(self.page.content(), encoding="utf-8")
            self.page.screenshot(path=str(self.debug / f"{name}.png"), full_page=not screenshot_only)
        except Exception as exc:  # 진단 실패는 본 작업을 막지 않는다
            log.debug("스냅샷 실패 %s: %s", name, exc)


def _first_visible(locator):
    try:
        n = locator.count()
    except Exception:
        return None
    for i in range(n):
        el = locator.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


if __name__ == "__main__":
    sys.exit(main())
