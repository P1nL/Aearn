from __future__ import annotations

import hashlib
import html.parser
from dataclasses import dataclass
from datetime import datetime

from app.services.grounding.grounding_fetcher import GroundingFetchDocument, _url_is_allowlisted
from app.services.grounding.grounding_provenance import GroundingProvenance
from app.services.grounding.grounding_sources import SourceContentType, SourceTrustTier, SourceVersionKind, get_grounding_source


@dataclass(frozen=True, slots=True)
class GroundingSection:
    title: str
    section_path: tuple[str, ...]
    text: str


@dataclass(frozen=True, slots=True)
class GroundingChunk:
    chunk_id: str
    source_id: str
    language_id: str
    title: str
    section_path: tuple[str, ...]
    canonical_url: str
    source_type: SourceContentType
    source_trust_tier: SourceTrustTier
    fetched_at: datetime
    content_hash: str
    text: str
    topic_tags: tuple[str, ...]
    source_version_label: str = "unversioned"
    source_version_kind: SourceVersionKind = "rolling"
    document_content_hash: str = ""
    provenance: GroundingProvenance = GroundingProvenance()


@dataclass(slots=True)
class _SectionBuffer:
    section_path: tuple[str, ...]
    blocks: list[str]

    @property
    def title(self) -> str:
        if self.section_path:
            return self.section_path[-1]
        return "Document"


class _DocumentationHTMLParser(html.parser.HTMLParser):
    _HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3}
    _BLOCK_TAGS = {"p", "li", "pre", "code"}
    _SKIP_TAGS = {"script", "style", "head", "nav", "footer", "aside"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._current_heading_level: int | None = None
        self._current_heading_text: list[str] = []
        self._current_block_tag: str | None = None
        self._current_block_text: list[str] = []
        self._current_path: tuple[str, ...] = ()
        self._sections: list[_SectionBuffer] = []

    @property
    def sections(self) -> tuple[GroundingSection, ...]:
        items: list[GroundingSection] = []
        for section in self._sections:
            text = "\n\n".join(block for block in section.blocks if block).strip()
            if text:
                items.append(
                    GroundingSection(
                        title=section.title,
                        section_path=section.section_path or ("Document",),
                        text=text,
                    ),
                )
        return tuple(items)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._HEADING_TAGS:
            self._current_heading_level = self._HEADING_TAGS[tag]
            self._current_heading_text = []
            return
        if tag in self._BLOCK_TAGS and self._current_block_tag is None:
            self._current_block_tag = tag
            self._current_block_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in self._HEADING_TAGS and self._current_heading_level is not None:
            text = _normalize_text(" ".join(self._current_heading_text))
            if text:
                self._current_path = self._path_for_heading(self._current_heading_level, text)
            self._current_heading_level = None
            self._current_heading_text = []
            return
        if tag == self._current_block_tag:
            text = _normalize_text(" ".join(self._current_block_text))
            if text:
                self._append_block(text)
            self._current_block_tag = None
            self._current_block_text = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._current_heading_level is not None:
            self._current_heading_text.append(data)
            return
        if self._current_block_tag is not None:
            self._current_block_text.append(data)

    def _append_block(self, text: str) -> None:
        if not self._sections or self._sections[-1].section_path != self._current_path:
            self._sections.append(_SectionBuffer(section_path=self._current_path, blocks=[]))
        self._sections[-1].blocks.append(text)

    def _path_for_heading(self, level: int, text: str) -> tuple[str, ...]:
        depth = max(0, level - 1)
        return (*self._current_path[:depth], text)


def clean_and_chunk_document(document: GroundingFetchDocument, *, max_chars: int = 1200) -> tuple[GroundingChunk, ...]:
    source = get_grounding_source(document.source_id)
    if source is None or max_chars <= 0:
        return ()

    provenance = document.provenance
    if (
        provenance.source_id != document.source_id
        or provenance.requested_url != document.canonical_url
        or provenance.final_url != document.final_url
        or provenance.document_content_hash != document.content_hash
        or document.content_hash != _sha256(document.raw_content)
    ):
        provenance = GroundingProvenance()
    parser = _DocumentationHTMLParser()
    parser.feed(document.raw_content)

    chunks: list[GroundingChunk] = []
    for section in parser.sections:
        for chunk_index, text in enumerate(_split_text(section.text, max_chars=max_chars)):
            if not text:
                continue
            content_hash = _sha256(text)
            chunk_id = _chunk_id(document.source_id, document.canonical_url, section.section_path, chunk_index, text)
            chunks.append(
                GroundingChunk(
                    chunk_id=chunk_id,
                    source_id=document.source_id,
                    language_id=document.language_id,
                    title=section.title,
                    section_path=section.section_path,
                    canonical_url=document.canonical_url,
                    source_type=source.content_type,
                    source_trust_tier=source.trust_tier,
                    fetched_at=document.fetched_at,
                    content_hash=content_hash,
                    text=text,
                    topic_tags=source.topic_tags,
                    source_version_label=document.source_version_label,
                    source_version_kind=document.source_version_kind,
                    document_content_hash=document.content_hash,
                    provenance=provenance,
                ),
            )
    return tuple(chunks)


def is_admissible_lesson_source(chunk: GroundingChunk, *, allow_fixtures_for_tests: bool = False) -> bool:
    """Admission for new managed lessons only; never relabel historical evidence."""
    allowed = ("http_fetch", "fixture") if allow_fixtures_for_tests else ("http_fetch",)
    provenance = chunk.provenance
    source = get_grounding_source(chunk.source_id)
    return (
        provenance.kind in allowed
        and source is not None
        and source.language_id == chunk.language_id
        and source.trust_tier in ("official", "trusted_de_facto")
        and source.trust_tier == chunk.source_trust_tier
        and source.content_type == chunk.source_type
        and provenance.source_id == chunk.source_id
        and provenance.requested_url == chunk.canonical_url
        and _url_is_allowlisted(chunk.canonical_url, source)
        and _url_is_allowlisted(provenance.final_url, source)
        and provenance.document_content_hash == chunk.document_content_hash
        and len(chunk.document_content_hash) == 64
        and all(char in "0123456789abcdef" for char in chunk.document_content_hash)
        and chunk.document_content_hash != "0" * 64
        and bool(chunk.text.strip())
        and chunk.content_hash == _sha256(chunk.text)
        and chunk.fetched_at.tzinfo is not None
    )


def _split_text(text: str, *, max_chars: int) -> tuple[str, ...]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    chunks: list[str] = []
    current = ""

    for block in blocks:
        if len(block) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split(block, max_chars=max_chars))
            continue
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = block

    if current:
        chunks.append(current)
    return tuple(chunks)


def _hard_split(text: str, *, max_chars: int) -> tuple[str, ...]:
    chunks: list[str] = []
    current = ""
    for word in text.split():
        if len(word) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
            continue
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return tuple(chunks)


def _chunk_id(source_id: str, canonical_url: str, section_path: tuple[str, ...], chunk_index: int, text: str) -> str:
    body = "\n".join((source_id, canonical_url, "/".join(section_path), str(chunk_index), text))
    return _sha256(body)[:24]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()
