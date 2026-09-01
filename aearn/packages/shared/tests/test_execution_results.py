from __future__ import annotations

import math

import pytest
from aearn_shared.execution import (
    MAX_TABLE_RESULT_CELL_CHARS,
    MAX_TABLE_RESULT_COLUMN_CHARS,
    MAX_TABLE_RESULT_COLUMNS,
    MAX_TABLE_RESULT_NUMBER_ABS,
    MAX_TABLE_RESULT_ROWS,
    SafeExecutionLocationV1,
    SafeExecutionPresentationNoneV1,
    SafeExecutionResultV1,
    SafeExecutionResultV2,
    SafeExecutionStatus,
    SafeTableResultPresentationV1,
    SafeTestFeedbackV1,
    SafeTestFeedbackV2,
    SandboxResultV1,
    SandboxTestFeedbackV1,
    adapt_safe_execution_result_v1,
    parse_safe_execution_result,
)
from pydantic import ValidationError


def test_v1_adapter_reads_history_and_reprojects_protected_content_as_v2_none() -> None:
    historical = SafeExecutionResultV1(
        status=SafeExecutionStatus.SUCCESS,
        stdout="answer=42\nC:\\work\\submission.py",
        stderr="authorization: bearer private-token",
        test_feedback=(
            SafeTestFeedbackV1(
                case_id="visible-1",
                passed=True,
                visible=True,
                message="Visible behavior passed.",
            ),
            SafeTestFeedbackV1(
                case_id="hidden-secret-case",
                passed=False,
                visible=False,
                message="expected input=secret and expected output=private",
            ),
        ),
        passed_test_count=1,
        total_test_count=2,
        diagnostic_code="completed",
    )

    adapted = adapt_safe_execution_result_v1(historical)
    parsed = parse_safe_execution_result(historical.model_dump(mode="json"))

    assert adapted == parsed
    assert adapted.schema_version == "safe-execution-result-v2"
    assert adapted.presentation == SafeExecutionPresentationNoneV1()
    assert adapted.stdout == "answer=42"
    assert adapted.stderr == ""
    assert adapted.test_feedback[1].case_id == "non-visible-1"
    assert adapted.test_feedback[1].message == "A non-visible scenario still failed."
    serialized = adapted.model_dump_json().casefold()
    for marker in ("hidden-secret-case", "expected input", "expected output", "c:\\work", "bearer"):
        assert marker not in serialized


def test_sandbox_to_v2_caps_safe_output_and_preserves_empty_streams() -> None:
    raw = SandboxResultV1(
        status=SafeExecutionStatus.SUCCESS,
        stdout="x" * 5_000,
        stderr="",
        test_feedback=(
            SandboxTestFeedbackV1(
                case_id="hidden-private-id",
                passed=True,
                visibility="hidden",
                message="private payload with expected value",
            ),
        ),
        passed_test_count=1,
        total_test_count=1,
        diagnostic_code="completed",
    )

    safe = SafeExecutionResultV2.from_sandbox_result(raw)

    assert len(safe.stdout) == 4_000
    assert safe.stdout.endswith("…")
    assert safe.stderr == ""
    assert safe.test_feedback[0].case_id == "non-visible-1"
    assert safe.test_feedback[0].message == "A non-visible scenario passed."
    assert safe.presentation.kind == "none"


def test_table_result_v1_strict_round_trip_accepts_only_public_json_scalars() -> None:
    result = SafeExecutionResultV2(
        schema_version="safe-execution-result-v2",
        status=SafeExecutionStatus.SUCCESS,
        stdout="2 rows",
        passed_test_count=2,
        total_test_count=2,
        diagnostic_code="completed",
        presentation=SafeTableResultPresentationV1(
            columns=("name", "score", "active", "note"),
            rows=(("Ada", 10, True, None), ("Grace", 9.5, False, "public")),
        ),
    )

    parsed = parse_safe_execution_result(result.model_dump(mode="json"))

    assert parsed == result
    assert parsed.model_dump(mode="json")["presentation"] == {
        "kind": "table_result_v1",
        "columns": ["name", "score", "active", "note"],
        "rows": [["Ada", 10, True, None], ["Grace", 9.5, False, "public"]],
    }


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": "safe-execution-result-v3",
            "status": "success",
            "presentation": {"kind": "none"},
        },
        {
            "schema_version": "safe-execution-result-v2",
            "status": "success",
            "presentation": {"kind": "preview_html_v1"},
        },
        {
            "schema_version": "safe-execution-result-v2",
            "status": "success",
            "presentation": {"kind": "none", "private_payload": "secret"},
        },
        {
            "schema_version": "safe-execution-result-v2",
            "status": "success",
            "presentation": {"kind": "none"},
            "command": "python /work/main.py",
        },
        {
            "status": "success",
            "presentation": {"kind": "none"},
        },
    ],
)
def test_parse_helper_fails_closed_on_unknown_extra_or_mixed_version_shapes(
    payload: dict[str, object],
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        parse_safe_execution_result(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stdout", "C:\\work\\submission.py"),
        ("stderr", "Traceback (most recent call last):"),
        ("stdout", "container aearn-exec-1"),
        ("stderr", "command: python main.py"),
        ("stdout", "api_key=sk-private"),
        ("stderr", "Bearer abcdefgh-private-token"),
    ],
)
def test_v2_rejects_protected_output_instead_of_serializing_it(field: str, value: str) -> None:
    payload: dict[str, object] = {
        "schema_version": "safe-execution-result-v2",
        "status": "runtime_error",
        "presentation": {"kind": "none"},
        field: value,
    }

    with pytest.raises(ValidationError, match="protected content"):
        SafeExecutionResultV2.model_validate(payload)


def test_v2_rejects_non_visible_private_identity_and_message() -> None:
    with pytest.raises(ValidationError, match="non-visible feedback"):
        SafeExecutionResultV2(
            schema_version="safe-execution-result-v2",
            status=SafeExecutionStatus.SUCCESS,
            test_feedback=(
                SafeTestFeedbackV2(
                    case_id="hidden-case-id",
                    passed=False,
                    visible=False,
                    message="expected secret output",
                ),
            ),
            passed_test_count=0,
            total_test_count=1,
            presentation=SafeExecutionPresentationNoneV1(),
        )


@pytest.mark.parametrize(
    "presentation",
    [
        lambda: SafeTableResultPresentationV1(
            columns=tuple(f"column-{index}" for index in range(MAX_TABLE_RESULT_COLUMNS + 1))
        ),
        lambda: SafeTableResultPresentationV1(
            columns=("value",),
            rows=tuple((index,) for index in range(MAX_TABLE_RESULT_ROWS + 1)),
        ),
        lambda: SafeTableResultPresentationV1(columns=("x" * (MAX_TABLE_RESULT_COLUMN_CHARS + 1),)),
        lambda: SafeTableResultPresentationV1(
            columns=("value",),
            rows=(("x" * (MAX_TABLE_RESULT_CELL_CHARS + 1),),),
        ),
        lambda: SafeTableResultPresentationV1(columns=("left", "right"), rows=((1,),)),
        lambda: SafeTableResultPresentationV1(columns=("value",), rows=(({"private": "value"},),)),
        lambda: SafeTableResultPresentationV1(columns=("value",), rows=((math.inf,),)),
        lambda: SafeTableResultPresentationV1(
            columns=("value",),
            rows=((MAX_TABLE_RESULT_NUMBER_ABS + 1,),),
        ),
        lambda: SafeTableResultPresentationV1(columns=("command",), rows=(("safe",),)),
        lambda: SafeTableResultPresentationV1(columns=("value",), rows=(("password=private",),)),
    ],
)
def test_table_result_rejects_bounds_shape_nested_and_protected_values(presentation) -> None:
    with pytest.raises((ValidationError, ValueError)):
        presentation()


def test_table_result_rejects_total_utf8_payload_above_hard_bound() -> None:
    rows = tuple(tuple("公开结果" * 15 for _ in range(16)) for _ in range(200))

    with pytest.raises(ValidationError, match="payload exceeds"):
        SafeTableResultPresentationV1(
            columns=tuple(f"column-{index}" for index in range(16)),
            rows=rows,
        )


def test_table_result_requires_successful_runtime_status() -> None:
    with pytest.raises(ValidationError, match="requires successful runtime execution"):
        SafeExecutionResultV2(
            schema_version="safe-execution-result-v2",
            status=SafeExecutionStatus.RUNTIME_ERROR,
            presentation=SafeTableResultPresentationV1(columns=("value",), rows=((1,),)),
        )


def test_v2_visible_failure_location_round_trips_without_a_path() -> None:
    result = SafeExecutionResultV2(
        schema_version="safe-execution-result-v2",
        status=SafeExecutionStatus.FAILED,
        test_feedback=(
            SafeTestFeedbackV2(
                case_id="visible-1",
                passed=False,
                visible=True,
                message="The returned value did not match the visible assertion.",
                location=SafeExecutionLocationV1(
                    line=7,
                    column=3,
                    end_line=7,
                    end_column=12,
                ),
            ),
        ),
        passed_test_count=0,
        total_test_count=1,
        presentation=SafeExecutionPresentationNoneV1(),
    )

    payload = result.model_dump(mode="json")

    assert payload["test_feedback"][0]["location"] == {
        "line": 7,
        "column": 3,
        "end_line": 7,
        "end_column": 12,
    }
    assert "path" not in payload["test_feedback"][0]["location"]
    assert parse_safe_execution_result(payload) == result


@pytest.mark.parametrize(
    "location",
    [
        {"line": 0},
        {"line": 8, "end_line": 7},
        {"line": 8, "column": 5, "end_line": 8, "end_column": 4},
        {"line": 8, "end_column": 4},
        {"line": 8, "path": "/work/main.py"},
    ],
)
def test_v2_rejects_invalid_or_path_bearing_locations(location: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SafeTestFeedbackV2.model_validate(
            {
                "case_id": "visible-1",
                "passed": False,
                "visible": True,
                "message": "Visible assertion failed.",
                "location": location,
            }
        )


def test_v2_non_visible_feedback_rejects_even_numeric_location() -> None:
    with pytest.raises(ValidationError, match="cannot expose a source location"):
        SafeTestFeedbackV2(
            case_id="non-visible-1",
            passed=False,
            visible=False,
            message="A non-visible scenario still failed.",
            location=SafeExecutionLocationV1(line=4),
        )
