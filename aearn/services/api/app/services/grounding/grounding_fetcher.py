from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx

from app.services.grounding.grounding_sources import GroundingSource, get_grounding_source, sources_for_language


GroundingFetchStatus = Literal["ok", "blocked", "failed"]


@dataclass(frozen=True, slots=True)
class GroundingHttpResponse:
    status_code: int
    final_url: str
    content_type: str
    text: str


class GroundingHttpClient(Protocol):
    def get(self, url: str, timeout_seconds: float) -> GroundingHttpResponse:
        ...


@dataclass(frozen=True, slots=True)
class GroundingFetchDocument:
    source_id: str
    language_id: str
    canonical_url: str
    final_url: str
    content_type: str
    fetched_at: datetime
    raw_content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class GroundingFetchResult:
    source_id: str
    url: str
    status: GroundingFetchStatus
    document: GroundingFetchDocument | None = None
    error_code: str | None = None
    error_message: str | None = None
    cache_hit: bool = False


class HttpxGroundingHttpClient:
    def get(self, url: str, timeout_seconds: float) -> GroundingHttpResponse:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(url)
        return GroundingHttpResponse(
            status_code=response.status_code,
            final_url=str(response.url),
            content_type=response.headers.get("content-type", ""),
            text=response.text,
        )


class GroundingDocsFetcher:
    def __init__(
        self,
        *,
        http_client: GroundingHttpClient | None = None,
        timeout_seconds: float = 5.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._http_client = http_client or HttpxGroundingHttpClient()
        self._timeout_seconds = timeout_seconds
        self._now = now or _utc_now
        self._cache: dict[tuple[str, str], GroundingFetchResult] = {}

    def fetch(self, source_id: str, url: str) -> GroundingFetchResult:
        source = get_grounding_source(source_id)
        canonical_url = url.strip()
        cache_key = (source_id.strip(), canonical_url)
        cached_result = self._cache.get(cache_key)
        if cached_result is not None:
            return replace(cached_result, cache_hit=True)

        if source is None:
            result = GroundingFetchResult(
                source_id=source_id,
                url=canonical_url,
                status="blocked",
                error_code="SOURCE_NOT_REGISTERED",
                error_message="Grounding source is not registered",
            )
            self._cache[cache_key] = result
            return result

        if not _url_is_allowlisted(canonical_url, source):
            result = GroundingFetchResult(
                source_id=source.source_id,
                url=canonical_url,
                status="blocked",
                error_code="URL_NOT_ALLOWLISTED",
                error_message="URL is outside the grounding source allowlist",
            )
            self._cache[cache_key] = result
            return result

        try:
            response = self._http_client.get(canonical_url, self._timeout_seconds)
        except Exception as exc:
            result = GroundingFetchResult(
                source_id=source.source_id,
                url=canonical_url,
                status="failed",
                error_code="FETCH_FAILED",
                error_message=_bounded_error_message(exc),
            )
            self._cache[cache_key] = result
            return result

        if response.status_code < 200 or response.status_code >= 300:
            result = GroundingFetchResult(
                source_id=source.source_id,
                url=canonical_url,
                status="failed",
                error_code="HTTP_STATUS",
                error_message=f"HTTP status {response.status_code}",
            )
            self._cache[cache_key] = result
            return result

        raw_content = response.text
        document = GroundingFetchDocument(
            source_id=source.source_id,
            language_id=source.language_id,
            canonical_url=canonical_url,
            final_url=response.final_url,
            content_type=response.content_type,
            fetched_at=self._now(),
            raw_content=raw_content,
            content_hash=hashlib.sha256(raw_content.encode("utf-8")).hexdigest(),
        )
        result = GroundingFetchResult(source_id=source.source_id, url=canonical_url, status="ok", document=document)
        self._cache[cache_key] = result
        return result

    def fetch_source_seed_documents(self, source_id: str) -> tuple[GroundingFetchResult, ...]:
        source = get_grounding_source(source_id)
        if source is None:
            return ()
        return tuple(self.fetch(source.source_id, seed_url) for seed_url in source.seed_urls)

    def fetch_language_seed_documents(self, language_id_or_alias: str) -> tuple[GroundingFetchResult, ...]:
        results: list[GroundingFetchResult] = []
        for source in sources_for_language(language_id_or_alias):
            results.extend(self.fetch(source.source_id, seed_url) for seed_url in source.seed_urls)
        return tuple(results)


def _url_is_allowlisted(url: str, source: GroundingSource) -> bool:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"}:
        return False
    hostname = (parsed_url.hostname or "").lower()
    return any(_hostname_matches_domain(hostname, domain) for domain in source.allowlisted_domains)


def _hostname_matches_domain(hostname: str, domain: str) -> bool:
    normalized_domain = domain.lower()
    return hostname == normalized_domain or hostname.endswith(f".{normalized_domain}")


def _bounded_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return type(exc).__name__
    return message[:200]


def _utc_now() -> datetime:
    return datetime.now(UTC)
