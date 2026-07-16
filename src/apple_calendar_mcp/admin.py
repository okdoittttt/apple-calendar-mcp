"""서버 관리 도구: 상태 조회, 무중단(hot) 재시작, 정지.

server_restart는 현재 프로세스를 os.execv로 그 자리에서 다시 실행하므로,
Claude Desktop과 이 서브프로세스 사이의 stdio 파이프가 코드 리로드 중에도
그대로 유지됩니다 - 코드 변경을 반영하기 위해 Claude Desktop을 종료할
필요가 없습니다. server_stop은 재실행 없이 프로세스를 그냥 종료합니다 -
다시 띄우려면 Claude Desktop에서 커넥터를 껐다 켜거나 앱을 재시작해야
합니다. 이 방식들이 실제 MCP 세션에 어떤 영향을 주는지, 그리고 이후
Claude Desktop에서 수동으로 해야 할 일이 있는지는 README를 참고하세요.
"""

import os
import sys
import threading
import time as _time

from fastmcp import FastMCP

from . import __version__

_START_TIME = _time.time()
_START_PID = os.getpid()

# sys.argv에서 유도하지 않고 하드코딩한 이유: `python -m apple_calendar_mcp.server`로
# 실행하면 sys.argv[0]이 server.py의 실제 파일 경로로 재작성되는데, 이걸 그대로
# 재사용하면 모듈이 아니라 일반 스크립트로 실행되어 패키지의 relative import가 깨집니다.
RESTART_ARGV = [sys.executable, "-m", "apple_calendar_mcp.server"]


def register_admin_tools(mcp: FastMCP) -> None:
    """서버 관리 도구를 모두 MCP 서버에 등록합니다."""

    @mcp.tool()
    async def server_status() -> dict:
        """이 서버 프로세스의 pid, 버전, 가동 시간, 도구 개수를 보고합니다.

        server_restart 전후로 호출해서 재시작이 실제로 적용됐는지
        (pid가 바뀌고 uptime이 ~0으로 초기화되는지) 확인할 수 있습니다.
        """
        tools = await mcp.list_tools()
        return {
            "success": True,
            "pid": os.getpid(),
            "version": __version__,
            "uptime_seconds": round(_time.time() - _START_TIME, 1),
            "tool_count": len(tools),
        }

    @mcp.tool()
    def server_restart(delay_seconds: float = 0.75) -> dict:
        """Claude Desktop을 종료하지 않고 이 서버 프로세스를 그 자리에서 재시작합니다.

        짧은 지연 후 백그라운드 스레드에서 동일한 Python 프로세스 이미지를
        os.execv로 다시 실행합니다. 지연을 두는 이유는 프로세스 이미지가
        교체되기 전에 이 도구 호출 자체의 응답이 stdio 파이프로 먼저
        전달될 시간을 주기 위함입니다. 파일 디스크립터(Claude Desktop과의
        stdio 파이프)는 execv를 거쳐도 유지되지만, MCP/JSON-RPC 세션을
        포함한 모든 메모리 상태는 새 프로세스이므로 초기화됩니다.

        중요: 이후 Claude Desktop이 커넥터를 투명하게 재사용하는지는
        클라이언트 버전에 따라 다르며, 테스트에서 항상 안정적으로
        동작함이 보장되지는 않았습니다. 재시작 직후 server_status를
        호출해 pid가 바뀌었는지 확인하세요; 이후 도구 호출이 응답하지
        않으면 Claude Desktop 설정에서 커넥터를 껐다 켜보세요 (앱 종료는
        필요 없음). 자세한 내용은 README 참고.

        Args:
            delay_seconds: 재실행 전 대기 시간 - 이 응답이 먼저 클라이언트에
                도달할 시간을 주기 위함 (기본값: 0.75)
        """
        pid_before = os.getpid()

        def _do_restart():
            _time.sleep(delay_seconds)
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            os.execv(sys.executable, RESTART_ARGV)

        threading.Thread(target=_do_restart, daemon=True).start()

        return {
            "success": True,
            "message": (
                f"Restarting in {delay_seconds}s (pid {pid_before} will be replaced). "
                "Call server_status shortly to confirm the pid changed."
            ),
            "pid_before": pid_before,
        }

    @mcp.tool()
    def server_stop(delay_seconds: float = 0.75) -> dict:
        """이 서버 프로세스를 재실행 없이 완전히 정지시킵니다.

        server_restart와 달리 새 프로세스를 다시 띄우지 않습니다 - 짧은
        지연(이 응답이 stdio 파이프로 먼저 전달될 시간을 주기 위함) 후
        프로세스가 그대로 종료됩니다. 종료되면 stdio 파이프가 닫히므로,
        이 MCP 커넥터는 무언가가 다시 띄워주기 전까지 응답하지 않습니다:
        Claude Desktop 설정에서 apple-calendar 커넥터를 껐다 켜거나,
        Claude Desktop을 재시작하세요. Calendar/Reminders 접근을 잠시
        멈추고 싶을 때(예: 자리를 비울 때) 사용하기 위한 도구입니다.

        Args:
            delay_seconds: 종료 전 대기 시간 - 이 응답이 먼저 클라이언트에
                도달할 시간을 주기 위함 (기본값: 0.75)
        """
        pid = os.getpid()

        def _do_stop():
            _time.sleep(delay_seconds)
            try:
                sys.stdout.flush()
                sys.stderr.flush()
            except Exception:
                pass
            os._exit(0)

        threading.Thread(target=_do_stop, daemon=True).start()

        return {
            "success": True,
            "message": (
                f"Stopping in {delay_seconds}s (pid {pid} will exit and will NOT "
                "restart on its own). To bring it back, toggle the apple-calendar "
                "connector off/on in Claude Desktop, or restart Claude Desktop."
            ),
            "pid": pid,
        }
