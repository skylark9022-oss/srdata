# srdata

국가 참조표준 데이터 구축을 위한 데이터 수집·분석 프로젝트.

- 공공 API 호출 → 원시 데이터 수집
- PDF 문서에서 텍스트/표 추출
- 정리한 결과를 엑셀(.xlsx)로 저장
- 수집한 데이터의 분석(개인용)

## 폴더 구조

```
srdata/
├── srdata/            # 파이썬 패키지 (재사용 가능한 코드)
│   ├── config.py      #   경로, 환경변수(.env) 로딩
│   ├── api/           #   API 호출 (재시도, 페이지네이션)
│   ├── pdf/           #   PDF 텍스트/표 추출
│   ├── excel/         #   엑셀 저장
│   └── analysis/      #   분석 코드
├── scripts/           # 실제로 실행하는 스크립트 (수집·변환 작업 단위)
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

PDF의 표를 모두 뽑아 엑셀로 저장:

```bash
python scripts/example_pipeline.py pdf data/raw/sample.pdf
```

패키지 코드 직접 사용:

```python
from srdata.pdf import extract_tables
from srdata.excel import save_sheets

tables = extract_tables("data/raw/sample.pdf")
save_sheets("data/processed/sample.xlsx", {f"table{i+1}": t for i, t in enumerate(tables)})
```

API 호출:

```python
from srdata.api import ApiClient
from srdata.config import env

client = ApiClient("https://api.example.go.kr", default_params={"serviceKey": env("DATA_GO_KR_KEY")})
rows = client.fetch_all("/items", items_path=["response", "body", "items", "item"])
```

## 테스트

```bash
pytest
```
