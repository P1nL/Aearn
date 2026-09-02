"""Stable server-built code/diff identity for model review v2."""
from __future__ import annotations

from app.services.learning.practice.model_review_contracts import (
    ModelReviewArtifactV2,
    build_model_review_artifact_v2_contract,
)


def build_model_review_artifact_v2(
    *,
    language_id: str,
    runtime_label: str,
    modified_code: str,
    source_code: str | None = None,
) -> ModelReviewArtifactV2:
    """Return the canonical contract-owned code/diff presentation."""

    return build_model_review_artifact_v2_contract(
        language_id=language_id,
        runtime_label=runtime_label,
        modified_code=modified_code,
        source_code=source_code,
    )


__all__ = ("build_model_review_artifact_v2",)
