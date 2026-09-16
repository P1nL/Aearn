"""Closed field locations let the existing single repair fix the actual field."""

import json

import pytest

from app.services.learning.lesson_authoring import (
    LessonAuthoringFailure,
    _parse_author_candidate,
)
from app.services.learning.lesson_authoring_feedback import LessonFeedbackIssue
from app.services.learning.lesson_contracts import (
    LESSON_DOCUMENT_SCHEMA_VERSION,
    LESSON_CONTENT_STANDARD_VERSION,
    lesson_author_block_examples,
)


def _payload() -> dict:
    blocks = list(
        lesson_author_block_examples(
            language_id="python", citation_handle="S1"
        ).values()
    )
    for index, block in enumerate(blocks):
        block["order_index"] = index
    return {
        "schema_version": LESSON_DOCUMENT_SCHEMA_VERSION,
        "title": "变量",
        "language_id": "python",
        "knowledge_key": "n2_1",
        "content_standard_version": LESSON_CONTENT_STANDARD_VERSION,
        "coverage_keys": ["core.behavior"],
        "blocks": blocks,
    }


@pytest.mark.parametrize(
    "case,location",
    [
        ("wrong_type", "blocks[2].paragraphs"),
        ("missing", "blocks[2].paragraphs"),
        ("too_long", "blocks[2].title"),
        ("execution_claim", "blocks[4].execution_claim"),
        ("extra", "blocks[2]"),
    ],
)
def test_validation_identifies_only_closed_fields(case: str, location: str) -> None:
    payload = _payload()
    if case == "wrong_type":
        payload["blocks"][2]["paragraphs"] = "candidate-value-never-echo"
    elif case == "missing":
        del payload["blocks"][2]["paragraphs"]
    elif case == "too_long":
        payload["blocks"][2]["title"] = "x" * 241
    elif case == "execution_claim":
        payload["blocks"][4]["execution_claim"] = "candidate-value-never-echo"
    else:
        payload["blocks"][2]["candidate-value-never-echo"] = (
            "candidate-value-never-echo"
        )
    with pytest.raises(LessonAuthoringFailure) as caught:
        _parse_author_candidate(payload, {"S1": "cite_0000000000000001"})
    issue = caught.value.issues[0]
    assert issue.code == "LESSON_BLOCK_FIELDS_INVALID"
    assert issue.location == location
    assert "candidate-value-never-echo" not in json.dumps(issue.payload())


def test_feedback_locations_do_not_accept_arbitrary_provider_fields() -> None:
    with pytest.raises(ValueError):
        LessonFeedbackIssue("LESSON_BLOCK_FIELDS_INVALID", "blocks[2].candidate_secret")
