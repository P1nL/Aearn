"""Read-only parent provenance checks; a CLI label never proves a real provider run."""
from __future__ import annotations

from typing import Any

VERSION = "rag_d_real_parent_v2"
RECEIPT_FIELDS = (
    "id", "run_id", "input_revision", "decision_iteration", "attempt_index",
    "provider_type", "model", "protocol", "outcome", "diagnostic_code",
    "input_tokens", "output_tokens", "reported_total_tokens", "reasoning_tokens", "usage_available",
)


class ParentProvenanceDenied(ValueError):
    pass


def load_receipts(conn: Any, *, user_id: str, conversation_id: str,
                  runs: list[dict[str, object]]) -> list[dict[str, object]]:
    if not 1 <= len(runs) <= 2 or len({(r["run_id"], r["input_revision"]) for r in runs}) != len(runs):
        raise ParentProvenanceDenied("PARENT_RUN_SCOPE_DENIED")
    receipts: list[dict[str, object]] = []
    for run in runs:
        rows = conn.execute(
            "SELECT " + ",".join(RECEIPT_FIELDS) + " FROM tutor_provider_attempt_receipts "
            "WHERE user_id=%s AND conversation_id=%s AND run_id=%s AND input_revision=%s "
            "ORDER BY decision_iteration,attempt_index",
            (user_id, conversation_id, run["run_id"], run["input_revision"]),
        ).fetchall()
        for row in rows:
            receipts.append({key: str(row[key]) if key in {"id", "run_id"} else row[key]
                             for key in RECEIPT_FIELDS})
    return receipts


def verify_parent_provenance(conn: Any, *, audit: dict[str, Any], parent: dict[str, Any],
                             database_name: str, conversation_id: str,
                             subject_id: str, subject_version: str,
                             expected_runtime_profile: dict[str, object], profile: str,
                             prior_http_attempts: int, cumulative_http_cap: int) -> dict[str, object]:
    """Audit + exact durable provider receipts + immutable draft coordinates.

    The root-owned audit is an operator execution record, not a new source grant
    or a cryptographic provider attestation. DB receipts alone do not prove live
    traffic; this runner additionally requires its observed transport counts.
    """
    try:
        exact = {
            "database_name": database_name, "user_id": str(parent["user_id"]),
            "session_id": str(parent["session_id"]), "conversation_id": conversation_id,
            "parent_draft_id": str(parent["id"]), "parent_content_hash": parent["content_hash"],
            "source_run_id": str(parent["source_run_id"]),
            "source_input_revision": parent["source_input_revision"],
            "subject_id": subject_id, "subject_version": subject_version,
        }
        if (audit.get("format") != VERSION or audit.get("status") != "parent_persisted"
                or any(audit.get(k) != v for k, v in exact.items())
                or parent["predecessor_draft_id"] is not None or parent["draft_version"] != 1
                or audit.get("provider_type") not in {"openai", "deepseek"}
                or not isinstance(audit.get("model"), str) or not audit["model"]
                or audit.get("runtime_profile") != expected_runtime_profile
                or audit.get("profile") != profile
                or audit.get("prior_http_attempts") != prior_http_attempts
                or audit.get("cumulative_http_cap") != cumulative_http_cap):
            raise ParentProvenanceDenied("PARENT_PROVENANCE_MISMATCH")
        count = audit["model_http_attempts"]
        if (type(count) is not int or not 1 <= count <= 8 or audit["client_calls"] != count
                or len(audit["usage_per_call"]) != count or len(audit["response_models"]) != count
                or type(audit["phase_http_cap"]) is not int or not 1 <= audit["phase_http_cap"] <= 8
                or count > audit["phase_http_cap"] or type(prior_http_attempts) is not int
                or prior_http_attempts < 0 or type(cumulative_http_cap) is not int
                or prior_http_attempts + audit["phase_http_cap"] > cumulative_http_cap):
            raise ParentProvenanceDenied("PARENT_TRANSPORT_PROOF_MISSING")
        runs = audit["runs"]
        if {"run_id": exact["source_run_id"], "input_revision": exact["source_input_revision"]} not in runs:
            raise ParentProvenanceDenied("PARENT_RUN_SCOPE_DENIED")
        receipts = load_receipts(conn, user_id=exact["user_id"], conversation_id=conversation_id, runs=runs)
        if (len(receipts) != count or receipts != audit["provider_receipts"]
                or any(r["provider_type"] != audit["provider_type"] or r["model"] != observed
                       for r, observed in zip(receipts, audit["response_models"], strict=True))
                or not any(r["run_id"] == exact["source_run_id"] and r["outcome"] == "accepted" for r in receipts)):
            raise ParentProvenanceDenied("PARENT_PROVIDER_RECEIPTS_DENIED")
        return {"parent_kind": "real_provider", "parent_http_attempts": count,
                "parent_receipt_ids": [r["id"] for r in receipts],
                "prior_http_attempts": prior_http_attempts + count,
                "cumulative_http_cap": cumulative_http_cap,
                "profile": profile, "runtime_profile": expected_runtime_profile}
    except ParentProvenanceDenied:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ParentProvenanceDenied("PARENT_PROVENANCE_INVALID") from exc
