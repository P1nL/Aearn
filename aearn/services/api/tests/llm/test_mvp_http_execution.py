"""Zero HTTP tests at the original complete_json / raw Responses parser seam."""

from __future__ import annotations

import asyncio
import io
import json
import threading
import time
import urllib.error
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from email.message import Message
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from app.core.config import Settings
from app.services.llm import http_execution as http_scope
from app.services.llm.http_execution import (
    LLMHTTPExecution, LLMHTTPExecutionError, current_http_execution, use_http_execution,
)
from app.services.llm.llm_client import LLMInvalidResponseError, OpenAICompatibleClient
from app.services.llm.provider_diagnostics import ProviderBodyCapture, ProviderDiagnosticStore


MESSAGES = [{"role": "user", "content": "Return JSON"}]


def _settings() -> Settings:
    return Settings(
        llm_type="openai", openai_api_key="fake", openai_base_url="https://provider.invalid",
        openai_model="fake-model", llm_timeout_seconds=600,
    )


def _frame(event: dict[str, object]) -> bytes:
    return ("data: " + json.dumps(event) + "\n\n").encode()


def _completed() -> bytes:
    return _frame({"type": "response.completed", "response": {
        "model": "observed-model", "status": "completed",
        "output": [{"type": "message", "content": [{
            "type": "output_text", "text": '{"ok": true}',
        }]}],
        "usage": {"input_tokens": 12, "output_tokens": 9},
    }})


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request, int], Awaitable[httpx.Response]] | None = None,
    *, sent: bool = True,
) -> tuple[list[httpx.Request], list[httpx.AsyncClient]]:
    real_client = httpx.AsyncClient
    requests: list[httpx.Request] = []
    clients: list[httpx.AsyncClient] = []

    async def receive(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert threading.current_thread().name == "mvp-llm-http"
        if sent:
            await request.extensions["trace"]("http11.send_request_headers.started", {})
        if handler is not None:
            return await handler(request, len(requests))
        return httpx.Response(200, content=_completed())

    def client(*, timeout: float, follow_redirects: bool) -> httpx.AsyncClient:
        instance = real_client(
            transport=httpx.MockTransport(receive), timeout=timeout, follow_redirects=follow_redirects,
        )
        clients.append(instance)
        return instance

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("scoped request reached legacy urllib")

    monkeypatch.setattr(http_scope.httpx, "AsyncClient", client)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    return requests, clients


class _Observer:
    def __init__(self) -> None:
        self.thread = threading.get_ident()
        self.events: list[str] = []

    def _record(self, event: str) -> None:
        assert threading.get_ident() == self.thread
        self.events.append(event)

    def on_stream_start(self) -> None:
        self._record("start")

    def on_text_delta(self, delta: str) -> None:
        self._record(delta)

    def on_stream_restart(self) -> None:
        self._record("restart")

    def on_stream_complete(self) -> None:
        self._record("complete")


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], *, delay: float = 0.0) -> None:
        self.chunks, self.delay = chunks, delay
        self.closed = False
        self.yielded = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            self.yielded += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _no_worker() -> None:
    assert not any(t.name == "mvp-llm-http" for t in threading.enumerate())


def test_original_responses_parser_usage_capture_and_visible_sink_on_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _frame({"type": "response.output_text.delta", "delta": '{"ok": true}'}) + _completed()
    stream = _Chunks([raw[:19], raw[19:]])

    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    requests, clients = _wire(monkeypatch, receive)
    observer = _Observer()
    capture = ProviderBodyCapture(store=cast(ProviderDiagnosticStore, object()), max_bytes=4096)
    captured: list[bytes] = []
    caller = threading.get_ident()
    original_append = capture.append

    def append(data: bytes) -> None:
        assert threading.get_ident() == caller
        captured.append(data)
        original_append(data)

    monkeypatch.setattr(capture, "append", append)
    store = cast(ProviderDiagnosticStore, SimpleNamespace(begin_capture=lambda: capture))
    calls: list[tuple[str, int]] = []

    def before_send() -> float:
        calls.append(("fence", threading.get_ident()))
        return 20

    execution = LLMHTTPExecution(
        before_send,
        lambda: calls.append(("lease", threading.get_ident())),
        lambda n: calls.append((str(n), threading.get_ident())),
    )
    with use_http_execution(execution):
        result = OpenAICompatibleClient(_settings(), diagnostic_store=store).complete_json(
            MESSAGES, timeout_seconds=2, capture_provider_body=True,
            visible_output_observer=observer,
        )
    assert result.content == {"ok": True}
    assert result.model == "observed-model"
    assert result.usage is not None and result.usage.input_tokens == 12
    assert result.response_diagnostics is not None
    assert result.response_diagnostics.response_status == "completed"
    assert observer.events == ["start", '{"ok": true}', "complete"]
    assert b"".join(captured) == raw
    assert all(t == caller for _, t in calls)
    assert execution.physical_attempts == len(requests) == 1
    assert requests[0].extensions["timeout"]["read"] <= 2
    assert stream.closed and all(c.is_closed for c in clients)
    assert current_http_execution() is None
    _no_worker()


def test_continuous_chunks_obey_total_wall_clock_not_socket_inactivity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert http_scope._MAX_HTTP_SECONDS == 300
    monkeypatch.setattr(http_scope, "_MAX_HTTP_SECONDS", 0.06)
    stream = _Chunks([b": keepalive\n\n"] * 100, delay=0.004)

    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    requests, clients = _wire(monkeypatch, receive)
    execution = LLMHTTPExecution(lambda: 300, lambda: None)
    start = time.monotonic()
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
    assert caught.value.reason == "request_timeout" and caught.value.outcome_unknown
    assert time.monotonic() - start < 0.7
    assert 1 <= stream.yielded < 100
    assert len(requests) == execution.physical_attempts == 1
    assert stream.closed and all(c.is_closed for c in clients)
    _no_worker()


@pytest.mark.parametrize("lose_lease", [False, True])
def test_silent_http_pumps_original_lease_on_caller_and_cancels_on_loss(
    monkeypatch: pytest.MonkeyPatch, lose_lease: bool,
) -> None:
    # Keep the accelerated pump above Windows' scheduler tick; do not weaken
    # the production late-renewal fence to accommodate a 15ms test timer.
    monkeypatch.setattr(http_scope, "_LEASE_PUMP_SECONDS", 0.05)
    stream = _Chunks([_completed()], delay=0.25)

    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    requests, clients = _wire(monkeypatch, receive)
    caller = threading.get_ident()
    renewals: list[float] = []

    def renew() -> None:
        assert threading.get_ident() == caller
        renewals.append(time.monotonic())
        if lose_lease and len(renewals) == 3:
            raise RuntimeError("owner generation changed")

    execution = LLMHTTPExecution(lambda: 1, renew)
    with use_http_execution(execution):
        if lose_lease:
            with pytest.raises(LLMHTTPExecutionError) as caught:
                OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
            assert caught.value.reason == "lease_lost" and caught.value.outcome_unknown
            assert stream.yielded == 0
        else:
            assert OpenAICompatibleClient(_settings()).complete_json(MESSAGES).content == {"ok": True}
    assert len(renewals) >= 3
    assert len(requests) == 1 and stream.closed and all(c.is_closed for c in clients)
    _no_worker()


def test_blocked_visible_pg_sink_cannot_leave_http_running_without_lease_pump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_scope, "_LEASE_PUMP_SECONDS", 0.05)
    delta = _frame({"type": "response.output_text.delta", "delta": '{"ok": true}'})

    class WaitingStream(_Chunks):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield delta
            await asyncio.sleep(1)
            yield _completed()

    stream = WaitingStream([])

    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    requests, clients = _wire(monkeypatch, receive)
    observer = _Observer()

    def slow_sink(delta: str) -> None:
        observer._record(delta)
        time.sleep(0.3)
        # The worker closed while the CALLER was blocked, before lease30 could lapse.
        assert stream.closed

    monkeypatch.setattr(observer, "on_text_delta", slow_sink)
    execution = LLMHTTPExecution(lambda: 1, lambda: None)
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(MESSAGES, visible_output_observer=observer)
    assert caught.value.reason == "lease_lost" and caught.value.outcome_unknown
    assert len(requests) == 1 and all(c.is_closed for c in clients)
    _no_worker()


def test_late_queued_renewal_does_not_revive_expired_pump(monkeypatch: pytest.MonkeyPatch) -> None:
    rescheduled: list[float] = []
    worker = http_scope._RequestWorker("https://provider.invalid", {}, {}, deadline=100)
    worker.pump_deadline = 20
    monkeypatch.setattr(worker, "loop", SimpleNamespace(is_closed=lambda: False, call_soon_threadsafe=lambda callback: callback()))
    monkeypatch.setattr(worker, "task", SimpleNamespace(done=lambda: False))
    monkeypatch.setattr(worker, "timer", SimpleNamespace(expired=lambda: False, reschedule=rescheduled.append))
    monkeypatch.setattr(http_scope, "time", SimpleNamespace(monotonic=lambda: 21))
    worker.renewed()
    assert worker.pump_deadline == 20 and rescheduled == []


def test_complete_response_keeps_usage_when_caller_parse_finishes_after_http_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.llm import llm_client

    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(http_scope, "time", SimpleNamespace(monotonic=lambda: clock.now))
    requests, _ = _wire(monkeypatch)
    original = llm_client._parse_responses_stream

    def slow_parse(response: Iterable[bytes], **kwargs: Any) -> Mapping[str, object]:
        parsed = original(response, **kwargs)
        clock.now += 2
        return parsed

    monkeypatch.setattr(llm_client, "_parse_responses_stream", slow_parse)
    execution = LLMHTTPExecution(lambda: 1, lambda: None)
    with use_http_execution(execution):
        response = OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
    assert response.content == {"ok": True}
    assert response.usage is not None and response.usage.input_tokens == 12 and response.usage.output_tokens == 9
    assert len(requests) == execution.physical_attempts == 1
    _no_worker()


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_only_proven_pre_send_has_two_retries_and_single_retry_layer(
    monkeypatch: pytest.MonkeyPatch, error_type: type[httpx.RequestError],
) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        raise error_type("not sent", request=request)

    requests, clients = _wire(monkeypatch, receive, sent=False)
    waits: list[float] = []
    monkeypatch.setattr(LLMHTTPExecution, "_retry_wait", lambda self, delay: waits.append(delay))
    monkeypatch.setattr(http_scope.random, "uniform", lambda low, high: 0)
    observer = _Observer()
    observed: list[int] = []
    execution = LLMHTTPExecution(lambda: 10, lambda: None, observed.append)
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings(), max_http_attempts=3).complete_json(
            MESSAGES, visible_output_observer=observer,
        )
    assert caught.value.reason == "pre_send_retries_exhausted"
    assert not caught.value.outcome_unknown
    assert execution.physical_attempts == len(requests) == 3
    assert observed == [1, 2, 3] and waits == [1, 3]
    assert observer.events == ["start", "restart", "start", "restart", "start"]
    assert all(c.is_closed for c in clients)
    _no_worker()


def test_attempt1_semantic_repair_and_safe_retry_share_same_sixteen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        if number == 1:
            raise httpx.ConnectError("DNS transient", request=request)
        raw = _completed().replace(b'{\\"ok\\": true}', b'not-json') if number == 2 else _completed()
        return httpx.Response(200, content=raw)

    requests, clients = _wire(monkeypatch, receive, sent=False)
    monkeypatch.setattr(LLMHTTPExecution, "_retry_wait", lambda self, delay: None)
    observed: list[int] = []
    execution = LLMHTTPExecution(lambda: 20, lambda: None, observed.append)
    client = OpenAICompatibleClient(_settings())
    with use_http_execution(execution), pytest.raises(LLMInvalidResponseError):
        client.complete_json(MESSAGES)
    # A new provider.decide / semantic repair scope must reuse, not reset, this object.
    with use_http_execution(execution):
        for _ in range(14):
            assert client.complete_json(MESSAGES).content == {"ok": True}
        with pytest.raises(LLMHTTPExecutionError) as caught:
            client.complete_json(MESSAGES)
    assert caught.value.reason == "physical_attempts_exhausted"
    assert not caught.value.outcome_unknown
    assert len(requests) == execution.physical_attempts == 16
    assert observed == list(range(1, 17)) and all(c.is_closed for c in clients)
    _no_worker()


@pytest.mark.parametrize("error_type", [
    httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.WriteError, httpx.ConnectError,
])
def test_sent_timeout_disconnect_or_partial_write_never_retries(
    monkeypatch: pytest.MonkeyPatch, error_type: type[httpx.RequestError],
) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        raise error_type("sent or partial write", request=request)

    requests, clients = _wire(monkeypatch, receive)
    execution = LLMHTTPExecution(lambda: 20, lambda: None)
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
    assert caught.value.reason in {"request_timeout", "transport_unknown"}
    assert caught.value.outcome_unknown and len(requests) == execution.physical_attempts == 1
    assert all(c.is_closed for c in clients)
    _no_worker()


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_http_status_is_not_safe_to_retry(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        return httpx.Response(status, content=b"provider-error")

    requests, clients = _wire(monkeypatch, receive)
    execution = LLMHTTPExecution(lambda: 20, lambda: None)
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
    assert caught.value.reason == "http_error"
    assert caught.value.status_code == status
    assert len(requests) == execution.physical_attempts == 1
    assert all(c.is_closed for c in clients)
    _no_worker()


def test_partial_stream_eof_is_unknown_not_semantic_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        return httpx.Response(200, content=_frame({
            "type": "response.output_text.delta", "delta": '{"partial":',
        }))

    requests, _ = _wire(monkeypatch, receive)
    observer = _Observer()
    execution = LLMHTTPExecution(lambda: 20, lambda: None)
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(MESSAGES, visible_output_observer=observer)
    assert caught.value.reason == "transport_unknown" and caught.value.outcome_unknown
    assert caught.value.response_diagnostics is not None
    assert caught.value.response_diagnostics.visible_output_chars == len('{"partial":')
    assert observer.events == ["start", '{"partial":'] and len(requests) == 1
    _no_worker()


def test_slow_retry_wait_rechecks_tight_budget_without_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = SimpleNamespace(now=100.0)

    def sleep(seconds: float) -> None:
        clock.now += seconds

    monkeypatch.setattr(http_scope, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=sleep))
    monkeypatch.setattr(http_scope.random, "uniform", lambda low, high: 0)

    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        raise httpx.ConnectError("not sent", request=request)

    requests, _ = _wire(monkeypatch, receive, sent=False)
    fences: list[float] = []

    def before_send() -> float:
        fences.append(clock.now)
        return 100.5 - clock.now

    execution = LLMHTTPExecution(before_send, lambda: None)
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
    assert caught.value.reason == "before_send_rejected" and not caught.value.outcome_unknown
    assert clock.now == 101 and fences[-1] == 101
    assert len(requests) == execution.physical_attempts == 1
    _no_worker()


def test_initial_fence_rejection_is_zero_http_and_not_a_transport_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests, _ = _wire(monkeypatch)
    execution = LLMHTTPExecution(lambda: 0, lambda: None)
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
    assert caught.value.reason == "before_send_rejected"
    assert execution.physical_attempts == len(requests) == 0


@pytest.mark.parametrize("observer_delay", [0.75, 1.25])
def test_attempt_observer_uses_one_full_fence_and_never_resets_its_deadline(
    monkeypatch: pytest.MonkeyPatch, observer_delay: float,
) -> None:
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(http_scope, "time", SimpleNamespace(monotonic=lambda: clock.now))
    requests, clients = _wire(monkeypatch)
    fences: list[float] = []
    renewals: list[float] = []
    attempts: list[int] = []

    def before_send() -> float:
        fences.append(clock.now)
        return 1

    def on_attempt(number: int) -> None:
        attempts.append(number)
        clock.now += observer_delay

    execution = LLMHTTPExecution(before_send, lambda: renewals.append(clock.now), on_attempt)
    with use_http_execution(execution):
        if observer_delay < 1:
            assert OpenAICompatibleClient(_settings()).complete_json(MESSAGES).content == {"ok": True}
            assert requests[0].extensions["timeout"]["read"] == 0.25
        else:
            with pytest.raises(LLMHTTPExecutionError) as caught:
                OpenAICompatibleClient(_settings()).complete_json(MESSAGES)
            assert caught.value.reason == "before_send_rejected"
            assert not caught.value.outcome_unknown and requests == []
    assert fences == [100]  # no second ~90s source/current reconstruction
    assert renewals == [100, 100 + observer_delay]
    assert attempts == [1] and execution.physical_attempts == 1
    assert all(c.is_closed for c in clients)
    _no_worker()


def test_legacy_urllib_retry_and_max_timeout_remain_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    timeouts: list[float] = []

    def urlopen(request: object, *, timeout: float) -> io.BytesIO:
        timeouts.append(timeout)
        if len(timeouts) < 3:
            raise urllib.error.HTTPError("https://provider.invalid", 503, "busy", Message(), None)
        return io.BytesIO(_completed())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("app.services.llm.llm_client._sleep_before_retry", lambda attempt: None)
    assert current_http_execution() is None
    result = OpenAICompatibleClient(_settings()).complete_json(MESSAGES, timeout_seconds=0.01)
    assert result.content == {"ok": True}
    assert timeouts == [600, 600, 600]
    _no_worker()
