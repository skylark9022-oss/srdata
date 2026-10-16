"""프로젝트 경로와 환경변수.

사용 예:
    from srdata.config import RAW_DIR, PROCESSED_DIR, env
    key = env("DATA_GO_KR_KEY")
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트 (이 파일: <root>/srdata/config.py)
ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"            # API 응답 원본, 원본 PDF
INTERIM_DIR = DATA_DIR / "interim"    # 중간 가공물
PROCESSED_DIR = DATA_DIR / "processed"  # 최종 엑셀 결과

# <root>/.env 를 읽어 환경변수로 올린다. 파일이 없으면 조용히 넘어간다.
load_dotenv(ROOT_DIR / ".env")


def env(name: str, default: str | None = None, *, required: bool = False) -> str | None:
    """환경변수를 읽는다. required=True 인데 값이 없으면 바로 에러를 낸다."""
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"환경변수 {name} 이(가) 설정되지 않았습니다. .env 파일을 확인하세요.")
    return value


def ensure_dirs() -> None:
    """data/ 하위 폴더가 없으면 만든다."""
    for d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR):
        d.mkdir(parents=True, exist_ok=True)
