from __future__ import annotations

import asyncio
import html.parser
import logging
from typing import Any

import httpx
from agents import function_tool

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 5.0
_MAX_TOC_LENGTH = 2000
_MAX_SEARCH_RESULTS = 5


class _HeadingExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._headings: list[tuple[int, str]] = []
        self._current_level: int | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("h1", "h2", "h3"):
            self._current_level = int(tag[1])
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2", "h3") and self._current_level is not None:
            text = " ".join(self._current_text).strip()
            if text:
                self._headings.append((self._current_level, text))
            self._current_level = None
            self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_level is not None:
            self._current_text.append(data.strip())

    @property
    def headings(self) -> list[tuple[int, str]]:
        return self._headings


def _extract_headings(html_content: str) -> str:
    parser = _HeadingExtractor()
    parser.feed(html_content)
    lines: list[str] = []
    for level, text in parser.headings:
        indent = "  " * (level - 1)
        lines.append(f"{indent}- {text}")
    result = "\n".join(lines)
    if len(result) > _MAX_TOC_LENGTH:
        return result[:_MAX_TOC_LENGTH] + "\n..."
    return result


def fetch_doc_toc_text(url: str, *, timeout: float = _REQUEST_TIMEOUT) -> str:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("fetch_doc_toc failed for %s: %s", url, exc)
        return f"无法获取页面内容: {url}"
    toc = _extract_headings(response.text)
    if not toc:
        return f"未能从页面提取到目录结构: {url}"
    return toc


async def _exa_search(query: str, api_key: str, max_results: int) -> list[dict[str, str]]:
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={
                "query": query,
                "numResults": max_results,
                "type": "keyword",
                "category": "programming",
            },
        )
        response.raise_for_status()
        data = response.json()
    results: list[dict[str, str]] = []
    for item in data.get("results", [])[:max_results]:
        results.append({"title": item.get("title", ""), "url": item.get("url", "")})
    return results


def build_web_tools(settings: Settings | None = None) -> list[Any]:
    effective_settings = settings or get_settings()
    api_key = effective_settings.exa_api_key
    if not api_key:
        return []

    @function_tool(
        name_override="web_search",
        description_override="Search for authoritative programming documentation. Returns a list of titles and URLs.",
        strict_mode=False,
    )
    async def web_search(query: str, max_results: int = _MAX_SEARCH_RESULTS) -> str:
        try:
            bounded_max_results = max(1, min(max_results, _MAX_SEARCH_RESULTS))
            results = await _exa_search(query, api_key, bounded_max_results)
        except Exception as exc:
            logger.warning("web_search failed: %s", exc)
            return "搜索失败，请使用已知的文档 URL。"
        if not results:
            return "未找到相关结果。"
        lines = [f"- {r['title']}: {r['url']}" for r in results]
        return "\n".join(lines)

    @function_tool(
        name_override="fetch_doc_toc",
        description_override="Fetch the table of contents (heading structure) from a documentation page URL.",
    )
    async def fetch_doc_toc(url: str) -> str:
        return await asyncio.to_thread(fetch_doc_toc_text, url)

    return [web_search, fetch_doc_toc]
