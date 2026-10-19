# srdata

국가 참조표준 데이터 구축을 위한 데이터 수집·분석 프로젝트.

- PDF 보고서(KINS 해양환경방사능조사)에서 표 추출 → 엑셀
- MEIS(해양환경정보포털) 해양방사능 정기조사 화면의 페이지별 엑셀 내려받기 → 취합 엑셀
- 해양방사능 조사정보 오픈API(공공데이터포털, 해양수산부 1192000) 호출 → 엑셀
- (예정) 두 데이터를 정점·시기 기준으로 병합(merge) → 분석

## 폴더 구조

```
srdata/
├── srdata/            # 파이썬 패키지 (재사용 가능한 코드)
│   ├── config.py      #   경로, 환경변수(.env) 로딩
│   ├── api/           #   범용 REST 클라이언트 (재시도, 페이지네이션, JSON/XML)
│   ├── koem/          #   KOEM 오픈API: 데이터셋 목록(datasets.py), 호출(api.py), 정리(tidy.py)
│   ├── meis/          #   MEIS 화면에서 내려받은 엑셀 취합(combine.py)
│   ├── pdf/           #   PDF 텍스트/표 추출 (extract.py 범용, report_tables.py 보고서용)
│   ├── excel/         #   엑셀 저장
│   └── analysis/      #   분석 코드 (measurements.py: 측정값 문자열 분리)
├── scripts/           # 실제로 실행하는 스크립트
│   ├── extract_marine_radioactivity_report.py   # KINS 보고서 PDF → 엑셀
│   ├── download_meis_radioactivity.py           # MEIS 정기조사 화면 엑셀을 페이지마다 내려받기(Playwright)
│   ├── combine_meis_excels.py                   # 내려받은 엑셀들 → 취합 엑셀(취합·분리 시트)
│   ├── fetch_koem.py                            # KOEM API → 엑셀
│   └── pdf_tables_to_excel.py                   # 임의 PDF 표 → 엑셀 (범용)
├── notebooks/         # 탐색용 주피터 노트북
├── data/
│   ├── raw/           #   API 응답 원본, 원본 PDF (git 제외)
│   ├── interim/       #   중간 가공물 (git 제외)
│   └── processed/     #   최종 엑셀 결과 (git 제외)
├── tests/             # 테스트
├── .env.example       # API 키 등 환경변수 예시 (.env로 복사해서 사용)
└── pyproject.toml     # 의존성 정의
```

`data/` 안의 파일은 `.gitkeep`만 빼고 모두 git에서 제외됩니다. 결과물을 저장소에 올리고 싶으면 `.gitignore`를 수정하세요.

## 설치

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
```

`.env`에 API 키를 적습니다. `.env`는 git에 올라가지 않습니다.

## 사용 예

KINS 해양환경방사능조사 보고서 PDF → 엑셀(원문 그대로 / 값·불확도 분리 / 수동 보정):

```bash
python scripts/extract_marine_radioactivity_report.py
```

MEIS 해양방사능 정기조사 엑셀 내려받기 → 취합:

```bash
pip install -e .[web] && playwright install chromium      # 하루 한 번
python scripts/download_meis_radioactivity.py --show       # 해수 탭, 2025년 1월~, data/raw/meis/해수/
python scripts/combine_meis_excels.py data/raw/meis/해수 -o data/processed/meis_해양방사능_해수.xlsx
```

자동 내려받기가 안 되면 화면에서 직접 페이지마다 "엑셀"을 눌러 `data/raw/meis/<탭>/` 에 모은 뒤 취합 스크립트만 돌린다.

해양방사능 조사정보 오픈API → 엑셀. 인증키는 실행하면 직접 입력하라고 묻는다(`--key`, `.env` 도 가능):

```bash
python scripts/fetch_koem.py list
python scripts/fetch_koem.py probe ocean_radio_solid --op <오퍼레이션이름>          # 응답 구조 확인(한 번 호출)
python scripts/fetch_koem.py fetch ocean_radio_solid --op <오퍼레이션이름> -p 이름=값  # 전부 받아 엑셀로
```

결과는 `data/processed/koem_ocean_radio_solid.xlsx`(시트 데이터·메타), 원본은 `data/raw/koem/`.

임의 PDF의 표를 모두 뽑아 엑셀로 저장:

```bash
python scripts/pdf_tables_to_excel.py data/raw/sample.pdf
```

패키지 코드 직접 사용:

```python
from srdata.pdf import extract_tables
from srdata.excel import save_sheets

tables = extract_tables("data/raw/sample.pdf")
save_sheets("data/processed/sample.xlsx", {f"table{i+1}": t for i, t in enumerate(tables)})
```

KOEM API 호출:

```python
from srdata.koem import fetch, to_frame

rows, meta = fetch("ocean_radio_solid", {"이름": "값"}, operation="<오퍼레이션이름>", service_key="...")
df = to_frame(rows)
```

새 데이터셋은 `srdata/koem/datasets.py` 의 `DATASETS` 에 요청주소·응답 경로를 추가한다.

## 테스트

```bash
pytest
```
