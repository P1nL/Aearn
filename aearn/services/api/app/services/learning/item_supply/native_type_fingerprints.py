"""Finite semantic fingerprints from checked actual tasks, not family labels.

Same finite decision with changed seed, names, prose or option order is deliberately
conservative: it remains a clone. No raw answer letter or scalar-output key.
"""
from __future__ import annotations

from typing import cast
from uuid import NAMESPACE_URL, uuid5

from app.services.learning.item_bank.contracts import LearningItemKnowledgeCheckContentV1, LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.native_publication_contracts import NativePublicationProofV1
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_targets.python_kc import KcTaskKind, python_kc_fixture
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.diagnostic_policy import ReviewBundle
from app.services.learning.item_supply.type_evidence import ContentIdentityV2

FINGERPRINT_VERSION = "native-finite-semantic-v1"


def semantic_payload(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1) -> dict[str, str]:
    # The original native validation reconstruction checks the actual task. The
    # family selects a registered structure, but its ID is not a fingerprint.
    profile: str
    kind: str
    if spec.python_goal is not None:
        profile, kind = "python", spec.python_goal.task_kind
    elif spec.sql_target is not None:
        profile, kind = "sqlite", spec.sql_target.task_kind
    elif spec.target_id == "python-kc-binding-v1":
        family = next(f for f in families_for_course(spec.target_id) if f.family_id == spec.allocation.family_id)
        fixture = python_kc_fixture(cast(KcTaskKind, family.task_kind), guided=spec.allocation.slot == "remediation")
        public = source.public.content
        if (not isinstance(public, LearningItemKnowledgeCheckContentV1)
                or sorted(o.label for o in public.options)
                != sorted(o.label for o in fixture.public_content.options)):
            raise ValueError("native_kc_actual_options_mismatch")
        profile, kind = "kc", fixture.task_kind
    else:
        raise ValueError("native_type_profile_unsupported")
    return {"version": FINGERPRINT_VERSION, "profile": profile, "decision": kind}


def native_content_identity(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1,
                            publication: NativePublicationProofV1, bundle: ReviewBundle) -> ContentIdentityV2:
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=publication.materials)
    semantics = semantic_payload(source, spec)
    fixture_hash = inputs.static_facts.instance_hash if inputs.static_facts is not None else (
        None if inputs.probe_plan is None else inputs.probe_plan.server_fixture_hash)
    if fixture_hash is None:
        raise ValueError("native_type_fixture_missing")
    return ContentIdentityV2(item_handle=publication.item_handle, version_id=publication.version_id,
        content_hash=source.content_hash, actual_public_task_hash=source.public.public_hash,
        actual_fixture_hash=fixture_hash,
        decision_signature=canonical_hash({"domain": "decision", "semantics": semantics}),
        answer_leakage_signature=canonical_hash({"domain": "contextual-solution", "semantics": semantics}),
        author_id=uuid5(NAMESPACE_URL, "aearn:item-author:" + bundle.author_identity))
