"""Isolated Codex App Server protocol spike utilities.

This package is intentionally not wired into the production Tutor runtime.
"""

from .deepseek_fixture import DeepSeekFixtureError, DeepSeekResponsesFixture
from .isolated_home import IsolatedCodexHome, build_isolated_codex_home
from .preflight import CodexExecutableProbe, CodexProtocolPreflight, probe_codex_executable, run_codex_protocol_preflight
from .real_smoke import RealDeepSeekSmokeError, RealDeepSeekSmokeResult, run_real_deepseek_smoke
from .runtime import JsonRpcChildExitedError, JsonRpcProtocolError, JsonRpcRemoteError, JsonRpcTimeoutError, StdioJsonRpcClient, ToolScenarioHost

__all__ = [
    "CodexExecutableProbe", "CodexProtocolPreflight", "DeepSeekFixtureError", "DeepSeekResponsesFixture",
    "IsolatedCodexHome", "RealDeepSeekSmokeError", "RealDeepSeekSmokeResult", "JsonRpcChildExitedError", "JsonRpcProtocolError", "JsonRpcRemoteError",
    "JsonRpcTimeoutError", "StdioJsonRpcClient", "ToolScenarioHost", "build_isolated_codex_home",
    "probe_codex_executable", "run_codex_protocol_preflight", "run_real_deepseek_smoke",
]
