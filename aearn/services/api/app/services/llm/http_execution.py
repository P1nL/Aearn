"""Explicit run-scoped MVP HTTP budget; absent scope leaves legacy transport alone."""

from __future__ import annotations

import asyncio
import math
import queue
import random
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypeVar

import httpx

from app.agents.harness.contracts import TutorExecutionProfile
from app.services.llm.completion_policy import COMPLETION_MAX_HTTP_SECONDS
from app.services.llm.contracts import LLMResponseDiagnostics, LLMUsage
from app.services.llm.provider_diagnostics import ProviderBodyCapture


_MAX_HTTP_SECONDS = 300.0
LEASE_PUMP_GUARD_SECONDS = 20.0
_LEASE_PUMP_SECONDS = LEASE_PUMP_GUARD_SECONDS / 2
_T = TypeVar("_T")


class LLMHTTPExecutionError(RuntimeError):
    """A terminal execution stop, not a semantic repair or legacy retry signal."""

    def __init__(
        self, reason: str, *, outcome_unknown: bool, physical_attempts: int,
    ) -> None:
        super().__init__(f"MVP HTTP execution stopped: {reason}")
        self.reason = reason
        self.outcome_unknown = outcome_unknown
        self.physical_attempts = physical_attempts
        self.status_code: int | None = None
        self.diagnostic_capture: ProviderBodyCapture | None = None
        self.usage: LLMUsage | None = None
        self.model: str | None = None
        self.response_diagnostics: LLMResponseDiagnostics | None = None

    def attach_diagnostic_capture(self, capture: ProviderBodyCapture | None) -> None:
        if self.diagnostic_capture is None:
            self.diagnostic_capture = capture


@dataclass(frozen=True)
class _Failure:
    error: BaseException
    proven_not_sent: bool = False


@dataclass
class _HTTPFailure(Exception):
    status: int
    body: bytes


class _LeasePumpMissed(Exception):
    pass


_END = object()


class _RequestWorker:
    """Only HTTP and raw bytes run here. No owner, DB, parser, or visible sink."""

    def __init__(
        self, url: str, headers: Mapping[str, str], payload: Mapping[str, object],
        deadline: float, *, completion_driven: bool = False,
    ) -> None:
        self.url, self.headers, self.payload = url, headers, payload
        self.deadline = deadline
        self.completion_driven = completion_driven
        self.events: queue.Queue[object] = queue.Queue()
        self.cancelled = threading.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task[None] | None = None
        self.timer: asyncio.Timeout | None = None
        # A blocked caller/visible PG sink cannot leave HTTP running past a missed
        # pump. This is stricter than, and never extends, the original 30s lease.
        self.pump_deadline = time.monotonic() + 2 * _LEASE_PUMP_SECONDS
        self.headers_started = False
        self.response_started = False
        self.completed_at: float | None = None
        self.thread = threading.Thread(target=self._run, name="mvp-llm-http")

    async def _trace(self, name: str, info: Mapping[str, object]) -> None:
        del info
        if name.endswith(".send_request_headers.started"):
            # Started, not completed: even a partial write is UNKNOWN.
            self.headers_started = True

    async def _read(self) -> None:
        remaining = min(self.deadline, self.pump_deadline) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        async with asyncio.timeout(remaining) as timer:
            self.timer = timer
            # The watchdog is renewable; a socket timeout is not. New-profile
            # silent reads use the stage deadline while connect/write/pool retain
            # the short bound. Missing owner pumps still cancel the whole task.
            timeout: float | httpx.Timeout = remaining
            if self.completion_driven:
                timeout = httpx.Timeout(remaining, read=max(0.0, self.deadline - time.monotonic()))
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                if time.monotonic() >= self.deadline:
                    raise TimeoutError
                async with client.stream(
                    "POST", self.url, headers=self.headers, json=self.payload,
                    extensions={"trace": self._trace},
                ) as response:
                    self.response_started = True
                    if not response.is_success:
                        raise _HTTPFailure(response.status_code, await response.aread())
                    pending = bytearray()
                    async for chunk in response.aiter_bytes():
                        pending.extend(chunk)
                        while (end := pending.find(b"\n")) >= 0:
                            self.events.put(bytes(pending[:end + 1]))
                            del pending[:end + 1]
                    if pending:
                        self.events.put(bytes(pending))

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self.loop = loop
        try:
            self.task = loop.create_task(self._read())
            if self.cancelled.is_set():
                self.task.cancel()
            loop.run_until_complete(self.task)
            self.completed_at = time.monotonic()
        except BaseException as exc:
            safe = (
                isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
                and not self.headers_started and not self.response_started
            )
            if (isinstance(exc, TimeoutError) and time.monotonic() >= self.pump_deadline
                    and self.pump_deadline < self.deadline):
                exc = _LeasePumpMissed()
            self.events.put(_Failure(exc, safe))
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            self.events.put(_END)

    def read_completed_in_budget(self) -> bool:
        return self.completed_at is not None and self.completed_at <= self.deadline

    def renewed(self) -> None:
        deadline = time.monotonic() + 2 * _LEASE_PUMP_SECONDS
        loop = self.loop
        if loop is None:
            return

        def reschedule() -> None:
            if (self.timer is not None and not self.timer.expired()
                    and time.monotonic() < self.pump_deadline
                    and self.task is not None and not self.task.done()):
                self.pump_deadline = deadline
                self.timer.reschedule(
                    loop.time() + min(self.deadline, self.pump_deadline) - time.monotonic(),
                )

        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(reschedule)
            except RuntimeError:
                pass  # Already closed; the finished result is still consumed below.

    def close(self) -> None:
        self.cancelled.set()
        loop, task = self.loop, self.task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                # The worker completed and closed its loop between the two checks.
                pass
        # Cancellation unwinds response/client context managers before this returns.
        # Do not return a caller-only timeout while an HTTP request continues.
        self.thread.join()


class LLMHTTPExecution:
    def __init__(
        self, before_send: Callable[[], float], renew_lease: Callable[[], None],
        on_attempt: Callable[[int], None] | None = None, max_attempts: int = 16,
        *, execution_profile: TutorExecutionProfile | None = None,
    ) -> None:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 16:
            raise ValueError("MVP HTTP max_attempts must be between 1 and 16")
        self.before_send = before_send
        self.renew_lease = renew_lease
        self.on_attempt = on_attempt
        self.max_attempts = max_attempts
        if execution_profile is not None and not isinstance(execution_profile, TutorExecutionProfile):
            raise ValueError("execution_profile must be a typed Tutor execution profile")
        self.execution_profile = execution_profile
        self.physical_attempts = 0

    def _stop(self, reason: str, *, unknown: bool = False) -> LLMHTTPExecutionError:
        return LLMHTTPExecutionError(
            reason, outcome_unknown=unknown, physical_attempts=self.physical_attempts,
        )

    def _renew(self, *, in_flight: bool = False) -> None:
        try:
            self.renew_lease()
        except Exception as exc:
            raise self._stop("lease_lost", unknown=in_flight) from exc

    def _timeout(self, requested: float) -> float:
        try:
            fresh = float(self.before_send())
        except Exception as exc:
            raise self._stop("before_send_rejected") from exc
        if not math.isfinite(fresh) or fresh <= 0:
            raise self._stop("before_send_rejected")
        maximum = (
            COMPLETION_MAX_HTTP_SECONDS
            if self.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1
            else _MAX_HTTP_SECONDS
        )
        return min(maximum, requested, fresh)

    def _retry_wait(self, delay: float) -> None:
        end = time.monotonic() + delay
        while (remaining := end - time.monotonic()) > 0:
            time.sleep(min(remaining, _LEASE_PUMP_SECONDS))
            self._renew()

    def post(
        self, url: str, headers: Mapping[str, str], payload: Mapping[str, object],
        timeout: float, consume: Callable[[Iterable[bytes]], _T], *,
        on_start: Callable[[bool], None] | None = None,
        capture: ProviderBodyCapture | None = None,
    ) -> _T:
        """One logical request, <=3 proven-not-sent attempts, shared run budget."""

        if not math.isfinite(timeout) or timeout <= 0:
            raise self._stop("before_send_rejected")
        # New stages have one total request deadline, including safe retries and
        # their backoff. A fresh owner fence may shorten it, never reset it.
        request_deadline = (
            time.monotonic() + min(COMPLETION_MAX_HTTP_SECONDS, timeout)
            if self.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1
            else None
        )
        for attempt in range(3):
            if request_deadline is not None and time.monotonic() >= request_deadline:
                raise self._stop("before_send_rejected")
            if self.physical_attempts >= self.max_attempts:
                raise self._stop("physical_attempts_exhausted")
            if on_start is not None:
                on_start(attempt > 0)
            # Visible start/restart can do DB work: fence AFTER it, on the caller.
            self._renew()
            bounded = self._timeout(timeout)
            deadline = time.monotonic() + bounded
            if request_deadline is not None:
                request_deadline = min(request_deadline, deadline)
                deadline = request_deadline
            self.physical_attempts += 1
            if self.on_attempt is not None:
                try:
                    self.on_attempt(self.physical_attempts)
                except Exception as exc:
                    raise self._stop("attempt_observer_rejected") from exc
                # This observer only records the dispatch. Do not repeat the slow
                # full source/current fence or renew the deadline it just issued.
                self._renew()
            if time.monotonic() >= deadline:
                raise self._stop("before_send_rejected")
            worker = _RequestWorker(
                url, headers, payload, deadline,
                completion_driven=self.execution_profile is TutorExecutionProfile.COMPLETION_DRIVEN_V1,
            )
            worker.thread.start()
            try:
                result = consume(self._lines(worker))
                # Parsing/visible callbacks run on the caller. A complete response
                # read in budget remains known even if those callbacks ran slowly;
                # the original post-IO owner/current fence still decides its use.
                if not worker.read_completed_in_budget():
                    raise self._stop("request_timeout", unknown=True)
                return result
            except _PreSendFailure as exc:
                if attempt >= 2:
                    raise self._stop("pre_send_retries_exhausted") from exc.error
            except _HTTPFailure as exc:
                if capture is not None:
                    capture.append(exc.body)
                error = self._stop("http_error")
                error.status_code = exc.status
                raise error from None
            finally:
                worker.close()
            # Only this layer retries. A slow wait is followed by before_send again.
            delay = (1.0, 3.0)[attempt] + random.uniform(0.0, 0.1)
            if request_deadline is not None:
                delay = min(delay, max(0.0, request_deadline - time.monotonic()))
            self._retry_wait(delay)
        raise AssertionError("unreachable HTTP attempt loop")

    def _lines(self, worker: _RequestWorker) -> Iterator[bytes]:
        next_renewal = time.monotonic() + _LEASE_PUMP_SECONDS
        while True:
            now = time.monotonic()
            completed = worker.read_completed_in_budget()
            if not completed and now >= worker.deadline:
                raise self._stop("request_timeout", unknown=True)
            if not completed and now >= next_renewal:
                try:
                    self._renew(in_flight=True)
                except LLMHTTPExecutionError:
                    # A slow owner check may finish after HTTP already completed.
                    # Preserve its known result; RunLoop retains the owner stop and
                    # persists the receipt before its original post-IO fence.
                    if not worker.read_completed_in_budget():
                        raise
                else:
                    worker.renewed()
                next_renewal = time.monotonic() + _LEASE_PUMP_SECONDS
                continue
            try:
                event = worker.events.get(timeout=None if completed else min(worker.deadline - now, next_renewal - now))
            except queue.Empty:
                continue
            if event is _END:
                return
            if isinstance(event, _Failure):
                if event.proven_not_sent:
                    raise _PreSendFailure(event.error)
                if isinstance(event.error, _HTTPFailure):
                    raise event.error
                if isinstance(event.error, _LeasePumpMissed):
                    raise self._stop("lease_lost", unknown=True) from event.error
                reason = "request_timeout" if isinstance(
                    event.error, (TimeoutError, httpx.TimeoutException),
                ) else "transport_unknown"
                raise self._stop(reason, unknown=True) from event.error
            if isinstance(event, bytes):
                yield event


@dataclass
class _PreSendFailure(Exception):
    error: BaseException


_EXECUTION: ContextVar[LLMHTTPExecution | None] = ContextVar("mvp_http_execution", default=None)


def current_http_execution() -> LLMHTTPExecution | None:
    return _EXECUTION.get()


@contextmanager
def use_http_execution(execution: LLMHTTPExecution) -> Iterator[None]:
    token = _EXECUTION.set(execution)
    try:
        yield
    finally:
        _EXECUTION.reset(token)
