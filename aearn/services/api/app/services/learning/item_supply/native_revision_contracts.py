"""Explicit server-owned author feedback sidecar; original V2 DTOs stay unchanged."""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.persistent_pack_revision_contracts import PersistentRegisteredFamilyRevisionV1
from app.services.learning.item_supply.review_contracts_v2 import ReviewDiagnosticReferenceV1
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

if TYPE_CHECKING:
    from app.services.learning.item_supply.native_review_investigation_contracts import NativeDisputeAnalysisV1


class NativeRevisionProblemV1(StorageContract):
    dispute_key: Digest
    analysis: str = Field(min_length=1, max_length=1600, repr=False)
    verification_question: str = Field(min_length=1, max_length=1200, repr=False)
    proposed_revision: str | None = Field(default=None, min_length=1, max_length=1600, repr=False)
    references: tuple[ReviewDiagnosticReferenceV1, ...] = Field(min_length=1, max_length=6)

    @classmethod
    def from_analysis(cls, analysis: NativeDisputeAnalysisV1) -> NativeRevisionProblemV1:
        return cls(dispute_key=analysis.dispute_key, analysis=analysis.analysis,
            verification_question=analysis.verification_question, proposed_revision=analysis.proposed_revision,
            references=analysis.references)


class NativeRevisionContextV1(StorageContract):
    schema_version: Literal["native_revision_author_context_v1", "native_revision_author_context_v2", "native_revision_author_context_v3"] = "native_revision_author_context_v1"
    purpose: Literal["bounded_content_revision_not_admission"] = "bounded_content_revision_not_admission"
    parent_artifact_id: UUID
    parent_artifact_hash: Digest
    parent_source_hash: Digest
    parent_content_hash: Digest
    parent_review_hash: Digest
    investigation_receipt_id: UUID
    investigation_receipt_hash: Digest
    investigation_report_hash: Digest
    child_candidate_id: UUID
    child_item_key: Identifier
    child_version: Identifier
    scope_hash: Digest
    policy_hash: Digest
    target_definition_hash: Digest
    parent_source: LearningItemSourceV1 = Field(repr=False)
    problems: tuple[NativeRevisionProblemV1, ...] = Field(min_length=1, max_length=144, repr=False)
    publication_enabled: Literal[False] = False
    blockers_discharged: Literal[False] = False
    persistent_family_revision: PersistentRegisteredFamilyRevisionV1 | None = Field(default=None,repr=False)

    @model_serializer(mode="wrap")
    def preserve_v1_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str,Any]:
        payload=handler(self)
        if self.schema_version=="native_revision_author_context_v1":
            payload.pop("persistent_family_revision",None)
        return payload

    @model_validator(mode="after")
    def exact_parent(self) -> NativeRevisionContextV1:
        source = checked_model(self.parent_source, LearningItemSourceV1)
        if ((source.source_hash, source.content_hash) != (self.parent_source_hash, self.parent_content_hash)
                or len({p.dispute_key for p in self.problems}) != len(self.problems)):
            raise ValueError("revision original source/problems mismatch")
        family=self.persistent_family_revision
        if self.schema_version=="native_revision_author_context_v1":
            if family is not None:
                raise ValueError("v1 cannot contain registered-family permission DATA")
        else:
            if family is None:
                raise ValueError("v2 exact registered-family DATA required")
            spec=family.child_specification
            baseline = source.blueprint
            if self.schema_version == "native_revision_author_context_v3":
                # DATA shape only, not a source grant. The original owner/SQL must
                # validate the stored bridge; check_request binds factory citations.
                baseline = baseline.model_copy(update={"source_references": spec.public_template.source_references})
            if (spec.target_definition_hash!=self.target_definition_hash
                    or spec.coverage_blueprint.scope.scope_hash!=self.scope_hash
                    or spec.blueprint.model_dump(mode="json",exclude={"blueprint_key","version"})
                        !=baseline.model_dump(mode="json",exclude={"blueprint_key","version"})
                    or family.finding_key not in {p.dispute_key for p in self.problems}):
                raise ValueError("v2 same public objective/risk/capabilities and actual finding required")
        return self

    @property
    def context_hash(self) -> str:
        return canonical_hash(checked_model(self, NativeRevisionContextV1).model_dump(mode="json"))

    def check_request(self, request: GenerationRequestV2) -> None:
        context = checked_model(self, NativeRevisionContextV1)
        request = checked_model(request, GenerationRequestV2)
        if (request.candidate_id != context.child_candidate_id or request.item_key != context.child_item_key
                or request.version != context.child_version or request.scope_hash != context.scope_hash
                or request.materials == () or request.demand_binding is not None):
            raise ValueError("revision child request/context mismatch")
        if context.schema_version=="native_revision_author_context_v1":
            if request.blueprint!=context.parent_source.blueprint:
                raise ValueError("revision child request/context mismatch")
        else:
            family=context.persistent_family_revision
            if family is None:
                raise ValueError("v2 registered-family DATA required")
            spec=family.child_specification
            if (request.blueprint!=spec.blueprint or request.public_template!=spec.public_template
                    or (spec.public_template.item_key,spec.public_template.version)!=(request.item_key,request.version)):
                raise ValueError("v2 exact original-factory child request required")
            if context.schema_version == "native_revision_author_context_v3":
                from app.services.learning.item_supply.finite_candidate_factory import check_finite_public_request
                check_finite_public_request(request)

    @property
    def provider_payload(self) -> dict[str, object]:
        context = checked_model(self, NativeRevisionContextV1)
        # Source/grading are public-origin shared-confidential author material.
        # No learner-private payload, peer verdict, blind answer or ledger.
        return {"supplemental_context_version": "supplemental-generation-context-v1",
            "context_hash": context.context_hash, "context": context.model_dump(mode="json")}


class NativeRevisionAuthorInputBindingV1(StorageContract):
    schema_version: Literal["native_revision_author_input_binding_v1"] = "native_revision_author_input_binding_v1"
    request_hash: Digest
    context_hash: Digest
    envelope_hash: Digest
    messages_hash: Digest
    output_schema_hash: Digest
    input_bytes: int = Field(ge=1, le=16_777_216)


class NativeRevisionAuthorTrace:
    """Ephemeral observed ORIGINAL generation envelope, not publication authority.

    Only generate_candidate records this; it cannot be restored from JSON to
    satisfy NativeRevisionOwner's original SharedGeneration producer check.
    """
    def __init__(self, context: NativeRevisionContextV1) -> None:
        self.context = checked_model(context, NativeRevisionContextV1)
        self.binding: NativeRevisionAuthorInputBindingV1 | None = None

    def record(self, request: GenerationRequestV2, context: NativeRevisionContextV1, *,
               messages: tuple[dict[str, str], ...], output_schema: Mapping[str, object], input_bytes: int) -> None:
        self.context.check_request(request)
        if self.binding is not None or context != self.context or input_bytes > request.limits.max_input_bytes:
            raise ValueError("revision actual envelope unavailable")
        self.binding = NativeRevisionAuthorInputBindingV1(request_hash=canonical_hash(request.model_dump(mode="json")),
            context_hash=context.context_hash, messages_hash=canonical_hash(messages),
            output_schema_hash=canonical_hash(output_schema),
            envelope_hash=canonical_hash({"messages": messages, "output_schema": output_schema}), input_bytes=input_bytes)
