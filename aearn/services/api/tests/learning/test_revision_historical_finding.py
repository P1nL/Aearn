"""Offline historical DATA/routing regressions, not source-cap or live authority acceptance."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner
from app.services.learning.item_supply.native_type_contracts import NativeTypeEvidencePending
from app.services.learning.item_supply.native_type_evidence import require_content_mapping_identity
from app.services.learning.item_supply.persistent_pack_committed_revision import RevisionOnlyContext
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError


def historical_data():
    # Shapes for the extracted pure comparison only: no fake issuer/DB claim.
    scope = SimpleNamespace(**{key: key for key in (
        "runtime_profile_id", "runtime_profile_hash", "scorer_version", "assistance_policy_hash",
        "subject_id", "subject_version", "required_facets", "required_capabilities", "assessment_contract_version")})
    content = SimpleNamespace(consumption=None, spec=SimpleNamespace(target_id="python-kc-binding-v1",
        target_definition_hash="a" * 64, allocation=SimpleNamespace(slot="assessment"),
        coverage_blueprint=SimpleNamespace(scope=scope)),
        facts=SimpleNamespace(root_id=uuid4(), target_proof=SimpleNamespace(
            mappings=(SimpleNamespace(clause_id="c1", clause_hash="b" * 64),))),
        publication=SimpleNamespace(version_id=uuid4(), generation_artifact_id=uuid4()))
    mapping = SimpleNamespace(target_id=content.spec.target_id, target_definition_hash=content.spec.target_definition_hash,
        pack_request=SimpleNamespace(demands=(SimpleNamespace(slot="assessment", demand=SimpleNamespace(scope=deepcopy(scope))),),
        clause_mapping=(("C1", "b" * 64, "original-clause", "c" * 64),)))
    return content, mapping


def test_historical_identity_without_consumption_preserves_scope_and_clauses():
    content, mapping = historical_data()
    assert content.consumption is None
    entry = require_content_mapping_identity(content, mapping)
    assert entry.slot == content.spec.allocation.slot
    bad = deepcopy(content)
    bad.spec.coverage_blueprint.scope.runtime_profile_hash = "0" * 64
    with pytest.raises(NativeTypeEvidencePending, match="native_candidate_mapping_mismatch"):
        require_content_mapping_identity(bad, mapping)
    bad = deepcopy(content)
    bad.facts.target_proof.mappings[0].clause_hash = "0" * 64
    with pytest.raises(NativeTypeEvidencePending, match="native_clause_mapping_mismatch"):
        require_content_mapping_identity(bad, mapping)
    mapping.pack_request.demands = ()
    with pytest.raises(NativeTypeEvidencePending, match="native_candidate_mapping_mismatch"):
        require_content_mapping_identity(content, mapping)


def test_historical_content_reads_original_data_but_rejects_changed_version():
    content, mapping = historical_data()
    calls = []

    def resolve(version_id, *, current):
        calls.append((version_id, current))
        return content

    public_task = uuid4()
    phase = SimpleNamespace(owner=SimpleNamespace(type_owner=SimpleNamespace(resolve_content=resolve)),
                            record=SimpleNamespace(public_task_id=public_task))
    version = SimpleNamespace(published_version_id=content.publication.version_id, specification=content.spec,
        artifact_id=content.publication.generation_artifact_id, root_id=content.facts.root_id, public_task_id=public_task)
    owner = object.__new__(NativeReviewInvestigationOwner)
    assert owner._historical_revision_content(phase, version, mapping) is content
    assert calls == [(content.publication.version_id, False)]
    version.artifact_id = uuid4()
    with pytest.raises(PipelineRepositoryError, match="PERSISTENT_IMMUTABLE_BOUND_PARENT_PAIR_REQUIRED"):
        owner._historical_revision_content(phase, version, mapping)


def test_unissued_revision_context_cannot_enable_historical_path():
    owner = object.__new__(NativeReviewInvestigationOwner)
    context = RevisionOnlyContext(owner=SimpleNamespace(), task=None, record=None, version=None,
                                  execution=object(), source_successor=object())
    with pytest.raises(PipelineRepositoryError, match="COMMITTED_REVISION_EXACT_CURRENT_EVIDENCE_REQUIRED"):
        owner._historical_revision_mapping(context)


def test_ordinary_allocation_keeps_current_publication_lookup():
    owner = object.__new__(NativeReviewInvestigationOwner)
    calls = []

    def resolve(version_id, *, current):
        calls.append(current)
        raise NativeTypeEvidencePending("native_content_current_required")

    sibling = SimpleNamespace(published_version_id=uuid4(), public_slot_id=uuid4())
    phase = SimpleNamespace(owner=SimpleNamespace(_versions=lambda task: {"sibling": sibling},
        type_owner=SimpleNamespace(resolve_content=resolve)), task=None, version=SimpleNamespace(public_slot_id=uuid4()))
    parent = SimpleNamespace(target_id="python-kc-binding-v1", allocation=SimpleNamespace(slot="assessment"))
    with pytest.raises(NativeTypeEvidencePending, match="native_content_current_required"):
        owner._select_registered_child_allocation(phase, parent)
    assert calls == [True]
