"""A registered adapter re-resolves a trusted, reproducible receipt by hash."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field

from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2, RiskEvidenceV2
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model


class VerifiedRiskReceiptV2(StorageContract):
    schema_version: Literal["item_supply_verified_risk_v2"] = "item_supply_verified_risk_v2"
    binding: CandidateBindingV2
    risk: Identifier
    verifier_identity: Identifier
    verifier_version: Identifier
    receipt_hash: Digest
    checks: tuple[Identifier, ...] = Field(min_length=1, max_length=48)
    passed: bool
    reproducible: bool
    isolated: bool = False


class RiskReceiptResolverV2(Protocol):
    def resolve(self, receipt_hash: str) -> VerifiedRiskReceiptV2 | None: ...


@dataclass(frozen=True, slots=True)
class VersionedRiskAdapter:
    risk: str
    version: str
    supported_profile_hashes: tuple[str, ...]
    required_checks: tuple[str, ...]
    resolver: RiskReceiptResolverV2
    requires_isolation: bool = False

    def verifies(self, binding: CandidateBindingV2, evidence: RiskEvidenceV2) -> bool:
        evidence = checked_model(evidence, RiskEvidenceV2)
        if (not evidence.passed or evidence.binding != binding or evidence.risk != self.risk
                or evidence.adapter_version != self.version or evidence.profile_hash != binding.profile_hash
                or binding.profile_hash not in self.supported_profile_hashes):
            return False
        receipt = self.resolver.resolve(evidence.receipt_hash)
        if receipt is None:
            return False
        receipt = checked_model(receipt, VerifiedRiskReceiptV2)
        return (
            receipt.binding == binding and receipt.risk == self.risk
            and receipt.receipt_hash == evidence.receipt_hash and receipt.passed and receipt.reproducible
            and receipt.verifier_identity == evidence.verifier_identity
            and receipt.verifier_version == evidence.verifier_version
            and set(self.required_checks) <= set(receipt.checks)
            and (not self.requires_isolation or receipt.isolated)
        )


# No automatic registration. Main must supply a trusted resolver and a supported
# frozen profile. A model vote or locally limited subprocess is not a receipt.
_CHECKS: dict[str, tuple[tuple[str, ...], bool]] = {
    "sql": (("dialect", "read_only", "single_statement", "bounded_setup", "nulls", "duplicates",
             "empty_set", "ordering", "types", "joins", "equivalent", "known_wrong",
             "scorer_counterexample", "independent_datasets"), True),
    "code_execution": (("reference", "starter_rejected", "equivalent", "known_wrong", "boundary",
                        "time_limit", "memory_limit", "output_limit", "scorer_counterexample"), True),
    "browser_preview": (("real_completion", "event_authority", "scorer_counterexample", "isolation"), True),
    "model_review": (("artifact_identity", "trusted_completion", "rubric", "scorer_counterexample"), True),
    "source_security": (("current_claim", "purpose_permission", "injection", "version", "source_hash",
                         "network_boundary"), False),
    "privacy": (("owner_scope", "no_private_egress", "redaction", "retention"), False),
}


def registered_receipt_adapter(
    risk: str, *, supported_profile_hashes: tuple[str, ...], resolver: RiskReceiptResolverV2,
    version: str = "risk-adapter-v2.1",
) -> VersionedRiskAdapter:
    if risk not in _CHECKS or not supported_profile_hashes:
        raise ValueError("unsupported risk adapter profile")
    checks, isolation = _CHECKS[risk]
    return VersionedRiskAdapter(risk=risk, version=version,
                               supported_profile_hashes=supported_profile_hashes,
                               required_checks=checks, resolver=resolver, requires_isolation=isolation)
