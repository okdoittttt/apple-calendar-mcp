# MCP Apps 미리보기용 얇은 진입점.
#
# `fastmcp dev apps`는 서버 스펙의 "콜론 앞"을 항상 파일 경로로 해석하기 때문에
# `src/apple_calendar_mcp/server.py:mcp` 를 주면 그 파일을 (패키지가 아닌)
# 단독 모듈로 로드하다가 상대 임포트(`from .eventkit_store import ...`)에서
# 실패합니다. 이 파일은 '절대' 임포트만 사용하므로 단독 로드에서도 안전하고,
# 설치된 패키지에서 완성된 `mcp` 서버 객체를 그대로 가져옵니다.
#
# 사용법 (브라우저 미리보기 - tool picker에서 event_composer 선택):
#     uv run fastmcp dev apps preview_app.py:mcp
from apple_calendar_mcp.server import mcp

__all__ = ["mcp"]
