from __future__ import annotations

from collections.abc import AsyncIterator

from app.agents.runtime.contracts import RuntimeEvent, RuntimeHealthSnapshot, RuntimeHealthStatus
from app.agents.runtime.worker_host import CodexRuntimeWorkerHost


class FakeRuntime:
    def __init__(self) -> None:
        self.starts = 0
        self.stopped = False

    async def start(self) -> RuntimeHealthSnapshot:
        self.starts += 1
        return RuntimeHealthSnapshot(RuntimeHealthStatus.READY, 1, version="fixture", model="deepseek-v4-flash", model_provider="aearn_deepseek")

    async def shutdown(self) -> None:
        self.stopped = True

    async def health(self): raise NotImplementedError
    async def start_thread(self, request): raise NotImplementedError
    async def resume_thread(self, thread_id): raise NotImplementedError
    async def run_turn(self, request): raise NotImplementedError
    async def steer(self, thread, turn_id, input): raise NotImplementedError
    async def interrupt(self, thread, turn_id): raise NotImplementedError
    async def events(self) -> AsyncIterator[RuntimeEvent]:
        if False:
            yield RuntimeEvent  # pragma: no cover


def test_worker_host_owns_one_runtime_loop_and_shuts_down() -> None:
    created: list[FakeRuntime] = []
    def factory():  # type: ignore[no-untyped-def]
        runtime = FakeRuntime()
        created.append(runtime)
        return runtime

    host = CodexRuntimeWorkerHost(runtime_factory=factory)  # type: ignore[arg-type]
    first = host.health(timeout_s=2)
    second = host.health(timeout_s=2)
    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert len(created) == 1
    assert created[0].starts == 2
    stopped = host.shutdown(timeout_s=2)
    assert stopped["status"] == "stopped"
    assert created[0].stopped is True
