"""Soft preference ordering cannot create source or network authority."""
from __future__ import annotations

from .contracts import SourcePreference, revalidate


def preference_rank(source_handle: str, site: str, author: str,
                    preferences: tuple[SourcePreference, ...]) -> int:
    """Only rank pre-existing candidates; no eligibility or admission decision."""
    if len(preferences) > 8:
        raise ValueError("too many preferences")
    checked = [revalidate(item, SourcePreference) for item in preferences]
    values = {("source_handle", source_handle), ("site", site), ("author", author)}
    return next((i for i, item in enumerate(checked) if (item.kind, item.value) in values), 8)
