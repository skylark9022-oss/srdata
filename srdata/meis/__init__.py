"""MEIS(해양환경정보포털, Marine Environment Information System; 해양환경공단 운영) 해양방사능 자료.

포털의 "분석결과 > 해양방사능 > 정기조사(정밀분석)" 화면
(https://www.meis.go.kr/oceansafety/analysis/analysisOceanPeriodic.do)에서 한 페이지씩 내려받은
엑셀 파일들을 하나로 취합한다. 내려받기는 scripts/download_meis_radioactivity.py(브라우저 자동화) 또는 수동.
"""

from .combine import CombineResult, combine_files, read_meis_table

__all__ = ["CombineResult", "combine_files", "read_meis_table"]
