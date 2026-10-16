# 작업 일지

세션이 끝날 때마다 맨 위에 새 항목을 추가한다. 형식: 날짜 → 한 일 → 결정 사항 → 다음 할 일.

---

## 2026-10-16

### 한 일
- GitHub 저장소 `skylark9022-oss/srdata` 생성(비어 있음) 후 로컬 `Z:\srdata` 에 클론.
- 프로젝트 기본 구조 생성:
  - `srdata/` 패키지: `config.py`(경로·.env), `api/client.py`(재시도·페이지네이션 REST 클라이언트), `pdf/extract.py`(pdfplumber 텍스트·표 추출), `excel/writer.py`(DataFrame → xlsx, 시트명 보정·열 너비 자동), `analysis/`(빈 패키지).
  - `scripts/example_pipeline.py`: `pdf <파일>` 로 표 → 엑셀, `api` 는 뼈대만.
  - `tests/test_smoke.py`, `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`.
- `CLAUDE.md`, 이 일지, `docs/sessions/` 대화 기록 추가.

### 결정 사항
- 맥락 보존은 저장소 안의 문서(CLAUDE.md, WORKLOG, sessions)로 한다. PC가 매일 초기화되기 때문.
- `data/` 내용은 git에 올리지 않는다(.gitkeep만).
- 브랜치는 `main` 하나로 작업. 클라우드 세션이 PR을 만들면 바로 머지.

### 미완료 / 확인 못 한 것
- 로컬 PC에 Python이 없어서 코드 실행·임포트·테스트를 한 번도 돌리지 못했다. **첫 실행 시 오류가 있을 수 있음.**

### 다음 할 일
1. 환경 준비: `pip install -e .[dev]` 후 `pytest` 실행, 오류 수정.
2. 실제로 수집할 참조표준 데이터 소스(API 주소, PDF 종류) 정하기.
3. `scripts/example_pipeline.py` 의 `run_api` 를 실제 API에 맞게 수정.
4. 샘플 PDF 하나로 `extract_tables` 결과 확인, 필요하면 `table_settings` 조정.
