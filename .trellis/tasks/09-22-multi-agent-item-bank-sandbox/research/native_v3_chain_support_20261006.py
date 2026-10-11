"""Offline plans/journal only; no credentials, provider, database or runner IO."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

TARGETS = ("python-kc-binding-v1", "python-state-update-v1", "sqlite-predicate-order-v1")
ADMISSION_POLICIES = ("strict-v2", "diagnostic-v3")
REVIEW_PROTOCOLS = ("legacy-v2", "evidenced-v1")
SLOTS = ("practice-1", "practice-2", "assessment-1", "assessment-2", "guided-remediation")
AUTHOR_INPUT = 131_072
AUTHOR_OUTPUT = 8192
REVIEW_INPUT = 262_144
REVIEW_OUTPUT = 2048
RELATION_CALLS = 4
ITEM_CALLS = 8
PROVIDER_TIMEOUT_SECONDS = 100
CONTROL_MARGIN_SECONDS = 300


class OperatorPending(ValueError):
    """Only program-owned fixed codes may reach the operator's failure receipt."""


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf8")).hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf8"))


def save(path: Path, value: Any) -> None:
    """Exclusive, fsynced checkpoint. A retry never overwrites an earlier fact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False, default=str)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def save_exact(path: Path, value: Any) -> None:
    if path.exists():
        if read(path) != value:
            raise OperatorPending("IMMUTABLE_CHECKPOINT_CONFLICT")
    else:
        save(path, value)


def campaign_cases(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Freeze exactly the immutable scope before the first paid call."""
    validate_plan(plan)
    slots = tuple(row["slot"] for row in plan["slots"])
    checkpoint = path / "campaign-candidates.json"
    if checkpoint.exists():
        cases = read(checkpoint)
        validate_cases(cases, plan)
        return cases
    cases = {}
    for slot in slots:
        identity = uuid4()
        cases[slot] = dict(candidate_id=str(identity), item_key=f"native.v3.{plan['target']}.{slot}.{identity.hex}")
    value = dict(plan_hash=digest(plan), cases=cases)
    save(checkpoint, value)
    return value


def campaign_path(raw: str, runtime: Path) -> Path:
    """Keep private receipts under the exact runtime, rejecting reparse components."""
    path = Path(raw)
    if not path.is_absolute():
        if path.name != raw or raw in (".", ".."):
            raise OperatorPending("CAMPAIGN_PATH_INVALID")
        path = runtime / raw
    path = path.absolute()
    for component in (path, *path.parents):
        if component.exists():
            attrs = getattr(component.lstat(), "st_file_attributes", 0)
            if component.is_symlink() or attrs & 0x400:
                raise OperatorPending("CAMPAIGN_REPARSE_PATH_DENIED")
    if not path.resolve().is_relative_to(runtime.resolve()) or path.resolve() == runtime.resolve():
        raise OperatorPending("CAMPAIGN_PATH_OUTSIDE_RUNTIME")
    return path


def selected_admission_policy(plan: dict[str, Any]) -> Any:
    """Closed policy selection, not caller-supplied DTOs or billing authority.

    Absence is the exact historical strict plan. Only a newly hashed campaign
    carries this complete diagnostic selection; partial/mixed markers fail shut.
    """
    from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
    from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3

    if "admission_policy" not in plan:
        return AutonomousEvidencePolicyV2()
    policy = AutonomousEvidencePolicyV3()
    expected = dict(mode="diagnostic-v3", policy_version=policy.policy_version, policy_hash=policy.policy_hash)
    if type(plan["admission_policy"]) is not dict or plan["admission_policy"] != expected:
        raise OperatorPending("PLAN_ADMISSION_POLICY_INVALID")
    return policy


def selected_review_protocol(plan: dict[str, Any]) -> Any:
    from app.services.learning.item_supply.review_protocol import evidenced_protocol_marker
    from app.services.learning.item_supply.review_rubrics import EVIDENCED_REVIEW_PROTOCOL, LEGACY_REVIEW_PROTOCOL

    if "review_protocol" not in plan:
        return LEGACY_REVIEW_PROTOCOL
    if type(plan["review_protocol"]) is not dict or plan["review_protocol"] != evidenced_protocol_marker():
        raise OperatorPending("PLAN_REVIEW_PROTOCOL_INVALID")
    return EVIDENCED_REVIEW_PROTOCOL


def production_peer_output_cap() -> int:
    """Reuse the verified production Flash request limit, not Decision/model max."""
    from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
    return DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS


def peer_output_marker() -> dict[str, Any]:
    return dict(schema_version="native_v3_peer_output_budget_v1",
        limit_source="production_deepseek_flash_tutor_output_v1", peer_max_output_tokens=production_peer_output_cap(),
        blind_max_output_tokens=REVIEW_OUTPUT, relation_max_output_tokens=REVIEW_OUTPUT)


def selected_peer_output_cap(plan: dict[str, Any]) -> int:
    """A closed server option, never an arbitrary caller-supplied token limit."""
    if "production_output_budget" in plan:
        _validate_production_output_budget(plan)
        return production_peer_output_cap()
    if "peer_review_output_budget" not in plan:
        return REVIEW_OUTPUT
    marker = plan["peer_review_output_budget"]
    if (type(marker) is not dict or marker != peer_output_marker()
            or selected_review_protocol(plan) != "evidenced-v1"):
        raise OperatorPending("PLAN_PEER_OUTPUT_BUDGET_INVALID")
    return production_peer_output_cap()


def production_output_marker() -> dict[str, Any]:
    cap = production_peer_output_cap()
    return dict(schema_version="native_v3_production_output_budget_v1",
        limit_source="production_deepseek_flash_tutor_output_v1",
        author_max_output_tokens=cap, blind_max_output_tokens=cap,
        peer_max_output_tokens=cap, relation_max_output_tokens=REVIEW_OUTPUT)


def _validate_production_output_budget(plan: dict[str, Any]) -> None:
    marker = plan.get("production_output_budget")
    if ("peer_review_output_budget" in plan or type(marker) is not dict
            or digest(marker) != digest(production_output_marker())
            or selected_review_protocol(plan) != "evidenced-v1"):
        raise OperatorPending("PLAN_PRODUCTION_OUTPUT_BUDGET_INVALID")


def selected_author_output_cap(plan: dict[str, Any]) -> int:
    selected_peer_output_cap(plan)  # Reject mixed/malformed markers as one unit.
    return production_peer_output_cap() if "production_output_budget" in plan else AUTHOR_OUTPUT


def selected_blind_output_cap(plan: dict[str, Any]) -> int:
    selected_peer_output_cap(plan)
    return production_peer_output_cap() if "production_output_budget" in plan else REVIEW_OUTPUT


def probe_marker(slot: str) -> dict[str, Any]:
    return dict(schema_version="native_v3_single_slot_probe_v1", mode="single-slot-probe",
        slot=slot, pack_ready=False, relation_anchor_eligible=False)


def selected_probe_slot(plan: dict[str, Any]) -> str | None:
    if "execution_scope" not in plan:
        return None
    marker = plan["execution_scope"]
    if (type(marker) is not dict or type(marker.get("slot")) is not str
            or marker["slot"] not in SLOTS or marker != probe_marker(marker["slot"])):
        raise OperatorPending("PLAN_PROBE_SCOPE_INVALID")
    return marker["slot"]


def validate_plan(plan: dict[str, Any], *, slot_name: str | None = None) -> None:
    """Reconstruct the complete trusted plan before reservation or external IO.

    Digest comparison also rejects extras, bool/int substitutions, mixed caps
    and edited allocations. Historical marker-absent plans stay exact.
    """
    if type(plan) is not dict:
        raise OperatorPending("PLAN_FROZEN_CONTENT_INVALID")
    selected_admission_policy(plan)
    protocol = selected_review_protocol(plan)
    peer_cap = selected_peer_output_cap(plan)
    probe = selected_probe_slot(plan)
    try:
        row = plan["slots"][0]
        seed = row["seed"] - SLOTS.index(probe) if probe is not None else row["seed"]
        expected = build_plan(plan["target"], seed,
            admission_policy="diagnostic-v3" if "admission_policy" in plan else "strict-v2",
            review_protocol=protocol, peer_review_max_output_tokens=peer_cap, probe_slot=probe,
            production_output_limits="production_output_budget" in plan)
        exact = digest(plan) == digest(expected)
    except (KeyError, IndexError, TypeError, ValueError):
        raise OperatorPending("PLAN_FROZEN_CONTENT_INVALID") from None
    if not exact:
        raise OperatorPending("PLAN_FROZEN_CONTENT_INVALID")
    if slot_name is not None and slot_name not in {s["slot"] for s in expected["slots"]}:
        raise OperatorPending("PLAN_SELECTED_SLOT_OUTSIDE_SCOPE")


def validate_cases(cases: dict[str, Any], plan: dict[str, Any]) -> None:
    slots = {row["slot"] for row in plan["slots"]}
    if cases["plan_hash"] != digest(plan) or set(cases["cases"]) != slots:
        raise OperatorPending("IMMUTABLE_CAMPAIGN_CASES_CONFLICT")
    identities = [str(UUID(row["candidate_id"])) for row in cases["cases"].values()]
    if len(set(identities)) != len(slots):
        raise OperatorPending("DISTINCT_CAMPAIGN_CANDIDATES_REQUIRED")
    for slot, row in cases["cases"].items():
        expected = f"native.v3.{plan['target']}.{slot}.{UUID(row['candidate_id']).hex}"
        if row["item_key"] != expected:
            raise OperatorPending("IMMUTABLE_CAMPAIGN_ITEM_KEY_CONFLICT")


def validate_campaign_state(path: Path, plan: dict[str, Any], *, slot_name: str | None = None) -> None:
    """Read-only freeze check shared by CLI and both imported execution seams."""
    validate_plan(plan, slot_name=slot_name)
    campaign_plan = path / "campaign-plan.json"
    if campaign_plan.exists() and read(campaign_plan) != plan:
        raise OperatorPending("IMMUTABLE_CAMPAIGN_POLICY_PLAN_CONFLICT")
    cases = path / "campaign-candidates.json"
    if cases.exists():
        validate_cases(read(cases), plan)
    window = path / "resource-window.json"
    if window.exists() and read(window)["plan_hash"] != digest(plan):
        raise OperatorPending("IMMUTABLE_CAMPAIGN_ACCOUNTING_PLAN_CONFLICT")
    slots = {row["slot"] for row in plan["slots"]}
    if selected_probe_slot(plan) is not None and (path / "slots").exists():
        if any(child.name not in slots for child in (path / "slots").iterdir()):
            raise OperatorPending("PROBE_EXISTING_SLOT_OUTSIDE_SCOPE")
    for slot in slots:
        intent = path / "slots" / slot / "candidate-intent.json"
        if intent.exists():
            frozen = read(intent)
            if frozen["plan_hash"] != digest(plan) or frozen["slot"] != slot:
                raise OperatorPending("IMMUTABLE_CANDIDATE_INTENT_CONFLICT")


def build_plan(target: str, seed: int = 0, *, admission_policy: str = "strict-v2",
               review_protocol: str = "legacy-v2", peer_review_max_output_tokens: int = REVIEW_OUTPUT,
               probe_slot: str | None = None, production_output_limits: bool = False) -> dict[str, Any]:
    """Historical defaults reconstruct old plans; NEW CLI uses production limits."""
    from app.services.learning.item_supply.finite_candidate_factory import build_finite_slot_allocation
    from app.services.learning.item_supply.finite_task_families import families_for_course

    if type(admission_policy) is not str or admission_policy not in ADMISSION_POLICIES:
        raise OperatorPending("PLAN_ADMISSION_POLICY_INVALID")
    if type(review_protocol) is not str or review_protocol not in REVIEW_PROTOCOLS:
        raise OperatorPending("PLAN_REVIEW_PROTOCOL_INVALID")
    if (type(peer_review_max_output_tokens) is not int or (peer_review_max_output_tokens != REVIEW_OUTPUT and
            (peer_review_max_output_tokens != production_peer_output_cap() or review_protocol != "evidenced-v1"))):
        raise OperatorPending("PLAN_PEER_OUTPUT_BUDGET_INVALID")
    if (type(production_output_limits) is not bool or (production_output_limits and
            (peer_review_max_output_tokens != production_peer_output_cap() or review_protocol != "evidenced-v1"))):
        raise OperatorPending("PLAN_PRODUCTION_OUTPUT_BUDGET_INVALID")
    if probe_slot is not None and (type(probe_slot) is not str or probe_slot not in SLOTS):
        raise OperatorPending("PLAN_PROBE_SCOPE_INVALID")
    if target not in TARGETS or type(seed) is not int or not 0 <= seed <= 251:
        raise OperatorPending("PLAN_TARGET_OR_SEED_INVALID")
    kinds = {
        TARGETS[0]: ("diagnose", "diagnose", "trace", "counterexample", "diagnose"),
        TARGETS[1]: ("accumulate", "accumulate", "refresh", "transfer", "accumulate"),
        TARGETS[2]: ("conjunction", "conjunction", "override_fallback", "keyset_after", "conjunction"),
    }[target]
    families = {f.task_kind: f for f in families_for_course(target)}
    rows = []
    for index, (slot, kind) in enumerate(zip(SLOTS, kinds, strict=True)):
        family = families.get(kind)
        if family is None:
            raise OperatorPending("REGISTERED_FAMILY_REQUIRED")
        role = "remediation" if slot == "guided-remediation" else slot.rsplit("-", 1)[0]
        allocation = build_finite_slot_allocation(target_id=target, family_id=family.family_id,
            slot=role, slot_index=1 if role == "remediation" else int(slot[-1]))
        rows.append({"slot": slot, "seed": seed + index, "allocation": allocation.model_dump(mode="json"),
            "allocation_hash": allocation.definition_hash, "max_HTTP_attempts": ITEM_CALLS})
    input_item = AUTHOR_INPUT + 7 * REVIEW_INPUT
    author_cap = production_peer_output_cap() if production_output_limits else AUTHOR_OUTPUT
    blind_cap = production_peer_output_cap() if production_output_limits else REVIEW_OUTPUT
    output_item = author_cap + blind_cap + 6 * peer_review_max_output_tokens
    caps = dict(requests=44, input_tokens=5 * input_item + RELATION_CALLS * REVIEW_INPUT,
        output_tokens=5 * output_item + RELATION_CALLS * REVIEW_OUTPUT, execution_seconds=4500,
        fetches=0, candidates=5, revision_rounds=0, investigation_rounds=0)
    if target == TARGETS[0]:
        caps["execution_seconds"] = 0
    primary = rows[0]["allocation"]["purpose"]
    root_caps = {
        primary: dict(requests=36, tokens=4 * (input_item + output_item)
            + RELATION_CALLS * (REVIEW_INPUT + REVIEW_OUTPUT), resources=3600 if target != TARGETS[0] else 0),
        "remediation": dict(requests=8, tokens=input_item + output_item,
            resources=900 if target != TARGETS[0] else 0),
    }
    plan = dict(schema_version="native_v3_campaign_plan_20261006", target=target,
        public_spec_version="finite-public-spec-v3", database="aearn_b1d_sandbox_20261001", slots=rows,
        global_caps=caps, root_caps=root_caps, **time_bounds(target),
        recommended_execution_order=["practice-1", "practice-2", "assessment-1", "guided-remediation", "assessment-2"],
        relation_anchor_purpose=primary,
        max_author_calls=5, max_blind_and_item_role_calls=35, reserved_relation_calls=4,
        max_HTTP_attempts=44, operator_HTTP_attempts=40, relation_execution_in_this_operator=False,
        max_http_attempts_each=1, new_GETs=0, signing_key_reads=0,
        monetary_cost=None, monetary_budget_reset=False, seeds_prove_independence=False,
        course_inventory_ready=False, public_release=False, E_complete=False)
    # Never add even a default marker to historical plans: their JSON/hash are
    # immutable. Admission selection does NOT change factory coverage or roots.
    if admission_policy == "diagnostic-v3":
        from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3
        policy = AutonomousEvidencePolicyV3()
        plan["admission_policy"] = dict(mode=admission_policy, policy_version=policy.policy_version,
            policy_hash=policy.policy_hash)
    if review_protocol == "evidenced-v1":
        from app.services.learning.item_supply.review_protocol import evidenced_protocol_marker
        plan["review_protocol"] = evidenced_protocol_marker()
    if production_output_limits:
        plan["production_output_budget"] = production_output_marker()
    elif peer_review_max_output_tokens != REVIEW_OUTPUT:
        plan["peer_review_output_budget"] = peer_output_marker()
    if probe_slot is not None:
        row = next(row for row in rows if row["slot"] == probe_slot)
        purpose = row["allocation"]["purpose"]
        resources = 900 if target != TARGETS[0] else 0
        plan.update(execution_scope=probe_marker(probe_slot), slots=[row],
            global_caps=dict(caps, requests=ITEM_CALLS, input_tokens=input_item,
                output_tokens=output_item, execution_seconds=resources, candidates=1),
            root_caps={purpose: dict(requests=ITEM_CALLS, tokens=input_item + output_item, resources=resources)},
            recommended_execution_order=[probe_slot], relation_anchor_purpose=None,
            pack_ready=False, relation_anchor_eligible=False,
            max_author_calls=1, max_blind_and_item_role_calls=7, reserved_relation_calls=0,
            max_HTTP_attempts=ITEM_CALLS, operator_HTTP_attempts=ITEM_CALLS,
            minimum_campaign_seconds=ITEM_CALLS * PROVIDER_TIMEOUT_SECONDS + resources + CONTROL_MARGIN_SECONDS,
            minimum_anchor_seconds=0)
    return plan


def required_remaining(plan: dict[str, Any], occupied: set[str], *, review_pending: set[str] | None = None) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Preserve relation headroom for full campaigns; probes never acquire it."""
    validate_plan(plan)
    slots = {row["slot"] for row in plan["slots"]}
    if not occupied <= slots or not (review_pending or set()) <= slots:
        raise OperatorPending("PLAN_SELECTED_SLOT_OUTSIDE_SCOPE")
    input_item = AUTHOR_INPUT + 7 * REVIEW_INPUT
    output_review = selected_blind_output_cap(plan) + 6 * selected_peer_output_cap(plan)
    output_item = selected_author_output_cap(plan) + output_review
    relation_calls = plan["reserved_relation_calls"]
    remaining = [s for s in plan["slots"] if s["slot"] not in occupied]
    totals = dict(plan["global_caps"])
    totals.update(requests=8 * len(remaining) + relation_calls,
        input_tokens=len(remaining) * input_item + relation_calls * REVIEW_INPUT,
        output_tokens=len(remaining) * output_item + relation_calls * REVIEW_OUTPUT,
        candidates=len(remaining), execution_seconds=900 * len(remaining) if plan["global_caps"]["execution_seconds"] else 0)
    roots = {purpose: dict(requests=0, tokens=0, resources=0) for purpose in plan["root_caps"]}
    primary = plan["slots"][0]["allocation"]["purpose"]
    roots[primary].update(requests=relation_calls, tokens=relation_calls * (REVIEW_INPUT + REVIEW_OUTPUT))
    for slot in remaining:
        amounts = roots[slot["allocation"]["purpose"]]
        amounts["requests"] += 8
        amounts["tokens"] += input_item + output_item
        amounts["resources"] += 900 if plan["global_caps"]["execution_seconds"] else 0
    for slot in plan["slots"]:
        if slot["slot"] not in (review_pending or set()):
            continue
        if slot["slot"] not in occupied:
            raise OperatorPending("CONTINUATION_MUST_HAVE_ORIGINAL_AUTHOR")
        totals["requests"] += 7
        totals["input_tokens"] += 7 * REVIEW_INPUT
        totals["output_tokens"] += output_review
        totals["execution_seconds"] += 900 if plan["global_caps"]["execution_seconds"] else 0
        amounts = roots[slot["allocation"]["purpose"]]
        amounts["requests"] += 7
        amounts["tokens"] += 7 * REVIEW_INPUT + output_review
        amounts["resources"] += 900 if plan["global_caps"]["execution_seconds"] else 0
    return totals, roots


def time_bounds(target: str) -> dict[str, int]:
    """Generous NEW profiles only; never extend existing windows or leases."""
    executable = target != TARGETS[0]
    return dict(period_seconds=14_400 if executable else 7_200,
        lease_seconds=3_600 if executable else 1_800,
        parent_seconds=3_600 if executable else 1_800,
        provider_timeout_seconds=PROVIDER_TIMEOUT_SECONDS,
        item_execution_seconds=900 if executable else 0,
        control_margin_seconds=CONTROL_MARGIN_SECONDS,
        minimum_campaign_seconds=44 * PROVIDER_TIMEOUT_SECONDS + (4500 if executable else 0) + 5 * CONTROL_MARGIN_SECONDS,
        minimum_anchor_seconds=12 * PROVIDER_TIMEOUT_SECONDS + (900 if executable else 0) + CONTROL_MARGIN_SECONDS)


def remaining_time_plan(plan: dict[str, Any], occupied: set[str], *, review_pending: set[str] | None = None) -> tuple[int, dict[str, int]]:
    """Serial declared IO plus control margin, separately from spend counters."""
    totals, roots = required_remaining(plan, occupied, review_pending=review_pending)
    outstanding = [s for s in plan["slots"] if s["slot"] not in occupied or s["slot"] in (review_pending or set())]
    wall = (totals["requests"] * PROVIDER_TIMEOUT_SECONDS + totals["execution_seconds"]
        + CONTROL_MARGIN_SECONDS * max(1, len(outstanding)))
    per_root = {}
    for purpose, amounts in roots.items():
        jobs = sum(s["allocation"]["purpose"] == purpose for s in outstanding)
        per_root[purpose] = (amounts["requests"] * PROVIDER_TIMEOUT_SECONDS + amounts["resources"]
            + CONTROL_MARGIN_SECONDS * max(1, jobs)) if amounts["requests"] else 0
    return wall, per_root


def resume_decision(folder: Path, *, artifact_exists: bool, publication_exists: bool) -> str:
    if publication_exists:
        return "published_readback_only"
    if (folder / "review-invoked.json").exists() or (folder / "review-prepared.json").exists():
        return "pending_original_review_owner_lost_no_retry"
    if artifact_exists:
        if (folder / "continuation-intent.json").exists():
            return "pending_continuation_already_attempted"
        return "fresh_491_continuation_required"
    return "pending_author_owner_lost_no_second_call"
