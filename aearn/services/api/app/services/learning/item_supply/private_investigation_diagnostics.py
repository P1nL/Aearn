"""Bounded private investigation DATA; never receiver or dispatch authority."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy

PrivateInvestigationAuditSink = Callable[[Mapping[str, object]], None]


def investigation_rejection_details(request_payload: Mapping[str, object],
                                   output_payload: Mapping[str, object]) -> dict[str, object]:
    """Pure, bounded DATA comparison. No DTO hydration, prose parsing or acceptance."""
    issues: list[dict[str, object]] = []
    issue_count = 0

    def issue(code: str, key: object = None, pointer: object = None,
              expected_hash: object = None, actual_hash: object = None) -> None:
        nonlocal issue_count
        issue_count += 1
        if len(issues) < 128:
            issues.append({"code": code,
                "dispute_key": key if isinstance(key, str) and len(key) <= 64 else None,
                "pointer": pointer if isinstance(pointer, str) and len(pointer) <= 512 else None,
                "expected_hash": expected_hash if isinstance(expected_hash, str) and len(expected_hash) <= 64 else None,
                "actual_hash": actual_hash if isinstance(actual_hash, str) and len(actual_hash) <= 64 else None})

    disputes = request_payload.get("disputes")
    evidence = request_payload.get("evidence_index")
    analyses = output_payload.get("analyses")
    if (not isinstance(disputes, (list, tuple)) or not 1 <= len(disputes) <= 144
            or not isinstance(evidence, (list, tuple)) or len(evidence) > 1024
            or not isinstance(analyses, (list, tuple)) or len(analyses) > 144):
        return {"state": "unavailable_bounded_shape", "issues": [], "issue_count": 0,
                "acceptance_asserted": False}
    originals = {d.get("dispute_key"): d for d in disputes
                 if isinstance(d, dict) and isinstance(d.get("dispute_key"), str)
                 and len(d["dispute_key"]) <= 64}
    index = {r.get("pointer"): r.get("value_hash") for r in evidence
             if isinstance(r, dict) and isinstance(r.get("pointer"), str)
             and len(r["pointer"]) <= 512}
    seen: set[str] = set()
    for analysis in analyses:
        if not isinstance(analysis, dict):
            issue("invalid_analysis_shape")
            continue
        key = analysis.get("dispute_key")
        if not isinstance(key, str) or len(key) > 64:
            issue("invalid_dispute_key")
            continue
        if key in seen:
            issue("duplicate_dispute_key", key)
        seen.add(key)
        if key not in originals:
            issue("unexpected_dispute_key", key)
        refs = analysis.get("references")
        if not isinstance(refs, (list, tuple)) or not 1 <= len(refs) <= 6:
            issue("invalid_references_shape", key)
            continue
        pointers: set[str] = set()
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("pointer"), str) or len(ref["pointer"]) > 512:
                issue("invalid_reference_shape", key)
                continue
            pointer, value_hash = ref["pointer"], ref.get("value_hash")
            if pointer in pointers:
                issue("duplicate_reference_pointer", key, pointer)
            pointers.add(pointer)
            if pointer not in index:
                issue("pointer_absent_from_scalar_index", key, pointer, actual_hash=value_hash)
            elif index[pointer] != value_hash:
                issue("reference_hash_mismatch", key, pointer, index[pointer], value_hash)
        original = originals.get(key)
        if original is not None:
            regions = original.get("references")
            if isinstance(regions, (list, tuple)) and regions and not any(
                    isinstance(r, dict) and isinstance(r.get("pointer"), str)
                    and (p == r["pointer"] or p.startswith(r["pointer"] + "/"))
                    for p in pointers for r in regions[:6]):
                issue("no_original_region_overlap", key)
    for key in sorted(set(originals) - seen):
        issue("missing_dispute_key", key)
    return {"state": "compared_private_data", "issues": issues, "issue_count": issue_count,
            "omitted_issue_count": max(0, issue_count - len(issues)), "acceptance_asserted": False}


class PrivateInvestigationAudit:
    """Sink exceptions/limits are an independent observability gap, not run state."""
    def __init__(self, sink: PrivateInvestigationAuditSink, *, context: Mapping[str, object]) -> None:
        self._sink = sink
        self._context = dict(context)
        self._status: dict[str, object] = {"enabled": True, "attempted": 0, "written": 0,
            "failed": 0, "audit_failure_code": None, "parsed_output_write_acknowledged": False,
            "private_only": True, "data_only": True, "acceptance_asserted": False}

    def emit(self, event: str, details: Mapping[str, object]) -> bool:
        self._status["attempted"] = int(self._status["attempted"]) + 1
        try:
            if self._status["attempted"] > 16:
                raise ValueError("private event count bound")
            payload = {"schema_version": "private_investigation_audit_event_v1", "event": event,
                "context": self._context, "details": dict(details), "private_only": True,
                "data_only": True, "dispatch_authority": False, "accounting_authority": False,
                "admission_eligible": False, "publication_enabled": False}
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > 262144:
                raise ValueError("private event byte bound")
            detached = json.loads(encoded)
        except Exception:
            self._status["failed"] = int(self._status["failed"]) + 1
            self._status["audit_failure_code"] = "private_event_build_or_bound_failed"
            return False
        try:
            self._sink(detached)
        except Exception:
            self._status["failed"] = int(self._status["failed"]) + 1
            self._status["audit_failure_code"] = "private_sink_write_failed"
            return False
        self._status["written"] = int(self._status["written"]) + 1
        return True

    def started(self, run_id: str) -> None:
        self._context["run_id"] = run_id
        self.emit("run_started", {"parsed_output_available": False})

    def parsed(self, request_payload: Mapping[str, object], output_payload: object) -> None:
        try:
            # Only the investigation output projection is eligible for raw parsed
            # retention. Unknown extra fields could contain private reasoning.
            allowed = {"dispute_key", "finding_status", "analysis", "verification_question",
                       "proposed_revision", "references"}
            safe = isinstance(output_payload, dict) and set(output_payload) <= {"schema_version", "analyses"}
            safe = safe and (output_payload.get("schema_version") is None or isinstance(output_payload.get("schema_version"), str))
            analyses = output_payload.get("analyses") if isinstance(output_payload, dict) else None
            if isinstance(analyses, list):
                safe = safe and len(analyses) <= 144 and all(
                    isinstance(a, dict) and set(a) <= allowed and
                    all(value is None or isinstance(value, str) for field, value in a.items() if field != "references") and
                    (a.get("references") is None or isinstance(a.get("references"), list) and
                     len(a["references"]) <= 6 and all(isinstance(r, dict) and set(r) <= {"pointer", "value_hash"}
                                                      and all(value is None or isinstance(value, str) for value in r.values())
                                                      for r in a["references"])) for a in analyses)
            else:
                safe = False
            if safe:
                acknowledged = self.emit("parsed_response", {"parsed_output": output_payload,
                    "raw_HTTP_retained": False, "reasoning_trace_retained": False,
                    "strict_DTO_verified": False})
                self._status["parsed_output_write_acknowledged"] = acknowledged
            else:
                self.emit("parsed_response", {"parsed_output": None,
                    "parsed_output_state": "unavailable_unallowlisted_shape",
                    "raw_HTTP_retained": False, "reasoning_trace_retained": False,
                    "strict_DTO_verified": False})
            if isinstance(output_payload, dict):
                self.emit("rejection_details", investigation_rejection_details(request_payload, output_payload))
        except Exception:
            self._status["failed"] = int(self._status["failed"]) + 1
            self._status["audit_failure_code"] = "private_diagnostic_build_failed"

    def failure(self, *, phase: str, safe_code: str, binding_fields: tuple[str, ...] = ()) -> None:
        self.emit("failure", {"phase": phase, "safe_code": safe_code,
            "binding_mismatch_fields": list(binding_fields), "exception_prose_retained": False})

    def status(self) -> dict[str, object]:
        return deepcopy(self._status)

