# srdata — Claude 작업 지침

이 파일은 Claude Code가 세션을 열 때 자동으로 읽는다. 어느 컴퓨터, 어느 세션에서든 같은 맥락으로 작업을 이어가기 위한 문서다.

## 프로젝트

- 목적: 국가 참조표준 데이터 구축을 위한 데이터 수집·분석.
- 흐름: (1) KINS 해양환경방사능조사 보고서 PDF 표 → 엑셀 (완료),
  (2) MEIS(해양환경정보포털, meis.go.kr) 해양방사능 정기조사(정밀분석) 화면의 페이지별 엑셀 내려받기 → 취합 (코드 작성, 실행은 로컬),
  (3) 해양방사능 조사정보 오픈API → 엑셀 (End Point: https://apis.data.go.kr/1192000/service/OceanRadioactiveSolidExaminationInfoService,
  데이터셋 키 `ocean_radio_solid`. 오퍼레이션·요청변수·출력결과 명세는 아직 없음), (2)와 (3) 대조,
  (4) PDF 데이터와 병합(merge) → 분석 (예정).
- 언어: Python 3.10+ 위주. 필요하면 다른 언어·도구 추가 가능.
- 사용자 혼자 쓴다. 배포·공유 계획 없음. 과한 추상화나 배포용 설정은 만들지 않는다.
- 대화는 한국어로 한다.

## 작업 환경 (중요)

- 사용자의 PC는 **매일 전부 초기화**된다. 로컬에만 있는 것(Claude 메모리, 설치한 프로그램, 커밋 안 한 파일)은 다음 날 없어진다.
- 따라서 **맥락은 전부 이 저장소 안에** 둔다: 이 파일, `docs/WORKLOG.md`, `docs/sessions/`.
- 로컬 세션에서는 git이 PATH에 없을 수 있다. GitHub Desktop에 내장된 git을 쓴다:
  `%LOCALAPPDATA%\GitHubDesktop\app-*\resources\app\git\cmd\git.exe`
- 클라우드 세션에서는 `pip install -e .[dev]` 로 의존성을 설치한 뒤 시작한다.
- API 키는 `.env`(git 제외)에 둔다. 클라우드 세션에서는 환경 설정의 환경변수로 넣는다. `.env.example` 참고.

## 세션 시작 시

1. `docs/WORKLOG.md` 를 읽고 "다음 할 일"부터 이어간다.
2. 필요하면 `docs/sessions/` 의 최근 대화 기록을 참고한다.

## 세션 끝날 때 (반드시)

1. `docs/WORKLOG.md` 에 오늘 날짜로 한 일·결정·다음 할 일을 추가한다.
2. 사용자가 원하면 대화 기록을 `docs/sessions/YYYY-MM-DD-<주제>.md` 로 남긴다.
   로컬(데스크톱 앱) 세션에서는 세션 내보내기(zip)의 `transcript.jsonl` 을 `tools/convert-transcript.ps1` 로 변환한다:
   `powershell -ExecutionPolicy Bypass -File tools/convert-transcript.ps1 -In <transcript.jsonl> -Out docs/sessions/2026-01-01-topic.md -Title "제목"`
3. 모두 커밋하고 `origin main` 에 푸시한다. 푸시하지 않은 작업은 사라진다.

## 코드 규칙

- 재사용 코드는 `srdata/` 패키지에, 실행 스크립트는 `scripts/`에, 탐색은 `notebooks/`에.
- 원본 데이터는 `data/raw/`, 중간물은 `data/interim/`, 최종 엑셀은 `data/processed/`. `data/` 내용은 git에 올리지 않는다.
- 엑셀 저장은 `srdata.excel.save_sheets`, PDF 추출은 `srdata.pdf.extract_tables` / `extract_report_tables`,
  API 호출은 `srdata.api.ApiClient`(범용) 위에 기관별 패키지(`srdata.koem`)를 둔다.
- KOEM 데이터셋은 `srdata/koem/datasets.py` 의 `DATASETS` 에 등록한다(요청주소·응답 경로는 data.go.kr 상세 페이지에서 확인).
  실행은 `scripts/fetch_koem.py`(인증키는 실행 때 직접 입력, `--key`, `.env` 중 하나; Encoding/Decoding 키 모두 가능).
  명세를 모르면 `probe` 로 한 번 호출해 결과코드·항목 경로·항목 이름을 본다. 원본 응답은 `data/raw/koem/`, 엑셀은 `data/processed/koem_<데이터셋>.xlsx`.
- MEIS 엑셀: 내려받기는 `scripts/download_meis_radioactivity.py`(Playwright, `pip install -e .[web]` + `playwright install chromium`),
  취합은 `scripts/combine_meis_excels.py` → `srdata.meis.combine_files`. 원본은 `data/raw/meis/<탭>/`, 결과는 `data/processed/meis_*.xlsx`.
- 클라우드 세션은 네트워크 정책 때문에 `data.go.kr`·`apis.data.go.kr`·`meis.go.kr`·`mof.go.kr`·`web.archive.org` 에
  접속하지 못한다(프록시 403, 2026-10-19 두 차례 확인). WebFetch 도구도 같은 호스트를 못 연다.
  API 실제 호출은 로컬 PC 에서 하고, 클라우드에서는 가짜 응답 테스트(`tests/test_koem.py`)로 검증한다.
- 테스트는 `pytest` (tests/).
