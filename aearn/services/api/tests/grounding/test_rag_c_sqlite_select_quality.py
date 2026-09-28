"""Offline, adversarial checks for the SQLite SELECT quality adapter.

These tests never fetch the page, use a real database, or create a production
review. The illustrative bytes and reference hashes are explicitly fake.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from app.services.grounding.autonomous.contracts import SubjectScope
from app.services.grounding.autonomous.source_review_repository import (
    CompleteCapture,
    QualityVerifier,
    _qualified,
)
from app.services.grounding.autonomous.sqlite_select_quality import (
    MAX_BODY_BYTES,
    SQLITE_SELECT_URL,
    FactCrosscheckReference,
    SQLiteSelectQualityEvidence,
    SQLiteSelectQualityVerifier,
    OperatorQualityJudgment,
    SignedSQLiteSelectOperatorReview,
    SQLiteSelectOperatorReviewPayload,
    TrustedOperatorSQLiteSelectQualityVerifier,
    canonical_operator_review_payload,
)


BODY = b"<html><body>synthetic fixture, not SQLite documentation</body></html>"
DIGEST = hashlib.sha256(BODY).hexdigest()
SCOPE = SubjectScope(subject_id="route.sql", subject_version="1", facets=("queries",))


def capture(**overrides: object) -> CompleteCapture:
    base = CompleteCapture(
        capture_id=UUID("00000000-0000-0000-0000-000000000001"),
        lane="registered",
        body=BODY,
        digest=DIGEST,
        revision=DIGEST,
        scope=SCOPE,
        source_handle="source.sqlite-select",
        final_url=SQLITE_SELECT_URL,
        request_chain=(SQLITE_SELECT_URL,),
        origin="official",
        reading_level="beginner",
        license_id="PublicDomain",  # matches the schema's mixed-case license contract
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def claimed_evidence() -> SQLiteSelectQualityEvidence:
    now = datetime(2026, 9, 25, tzinfo=UTC)
    return SQLiteSelectQualityEvidence(
        capture_id=capture().capture_id,
        source_handle="source.sqlite-select",
        scope=SCOPE,
        final_url=SQLITE_SELECT_URL,
        body_sha256=DIGEST,
        body_bytes=len(BODY),
        revision=DIGEST,
        egress_provenance_receipt_sha256="a" * 64,
        currentness_review_receipt_sha256="b" * 64,
        fact_crosschecks=(
            FactCrosscheckReference(
                claim_id="select.fact",
                page_span_sha256="c" * 64,
                independent_source_revision_sha256="d" * 64,
                reference_family="reference.independent",
                check_receipt_sha256="e" * 64,
            ),
        ),
        known_error_review_receipt_sha256="f" * 64,
        reading_fit_review_receipt_sha256="1" * 64,
        lineage_review_receipt_sha256="2" * 64,
        license_id="PublicDomain",  # matches the schema's mixed-case license contract
        storage_use_grant_receipt_sha256="3" * 64,
        reviewed_at=now,
        retained_until=now + timedelta(days=1),
        reviewer_key_id="reviewer.fake",
        reviewer_signature_hex="4" * 128,
    )


def assert_not_qualified(verifier: QualityVerifier, item: CompleteCapture) -> None:
    result = verifier.verify(item)
    assert result.mode == "offline_protocol_only"
    assert result.covered_facets == ()
    assert result.version_fit == "unknown"
    assert result.reading_fit == "unknown"
    assert result.technical_status == "unknown"
    assert result.known_error == "unknown"
    assert result.conflict_status == "unknown"
    assert len(result.evidence_hash) == 64
    assert not _qualified(result, item.scope)


def test_official_host_full_hash_and_html_do_not_confer_quality() -> None:
    verifier = SQLiteSelectQualityVerifier()
    assert verifier.audit(capture()).code == "EVIDENCE_MISSING"
    assert_not_qualified(verifier, capture())
    assert verifier.verify(capture()) == verifier.verify(capture())


def test_all_self_asserted_receipts_and_signature_still_fail_closed() -> None:
    # A syntactically complete fake bundle cannot validate its own signature,
    # independence, technical truth, current license, or retention authority.
    verifier = SQLiteSelectQualityVerifier(claimed_evidence())
    audit = verifier.audit(capture())
    assert audit.code == "INDEPENDENT_AUTHORITY_MISSING"
    assert "verified_operator_signature" in audit.missing_authorities
    assert "current_license_storage_use_retention_grant" in audit.missing_authorities
    assert_not_qualified(verifier, capture())


@pytest.mark.parametrize(
    "change",
    [
        {"digest": "0" * 64},
        {"revision": "claimed-different-version"},
        {"body": b""},
        {"body": b"x" * (MAX_BODY_BYTES + 1)},
        {"lane": "candidate"},
        {"final_url": "https://www.sqlite.org/copyright.html"},
        {"request_chain": (SQLITE_SELECT_URL, "https://www.sqlite.org/other.html")},
        {
            "scope": SubjectScope(
                subject_id="route.sql", subject_version="1", facets=("schema",)
            )
        },
        {
            "scope": SubjectScope(
                subject_id="route.sql",
                subject_version="1",
                facets=("queries", "schema"),
            )
        },
    ],
)
def test_wrong_bytes_revision_redirect_lane_or_facet_never_qualifies(
    change: dict[str, object],
) -> None:
    item = capture(**change)
    verifier = SQLiteSelectQualityVerifier(claimed_evidence())
    assert verifier.audit(item).code == "CAPTURE_INVALID"
    assert_not_qualified(verifier, item)


@pytest.mark.parametrize(
    "field, value",
    [
        ("body_sha256", "0" * 64),
        ("body_bytes", len(BODY) + 1),
        ("capture_id", UUID("00000000-0000-0000-0000-000000000002")),
        ("license_id", "license.other"),
        ("source_handle", "source.other"),
        (
            "scope",
            SubjectScope(
                subject_id="route.sql", subject_version="2", facets=("queries",)
            ),
        ),
    ],
)
def test_stale_or_cross_bound_evidence_is_rejected(field: str, value: object) -> None:
    evidence = claimed_evidence().model_copy(update={field: value})
    verifier = SQLiteSelectQualityVerifier(evidence)
    assert verifier.audit(capture()).code == "EVIDENCE_MISMATCH"
    assert_not_qualified(verifier, capture())


def test_model_copy_cannot_smuggle_invalid_evidence_into_review() -> None:
    forged = claimed_evidence().model_copy(
        update={"reviewer_signature_hex": "I ran it"}
    )
    verifier = SQLiteSelectQualityVerifier(forged)
    assert verifier.audit(capture()).code == "CAPTURE_INVALID"
    assert_not_qualified(verifier, capture())


def test_evidence_manifest_rejects_schema_facet_and_expired_at_review() -> None:
    evidence = claimed_evidence()
    with pytest.raises(ValidationError):
        SQLiteSelectQualityEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "scope": SubjectScope(
                    subject_id="route.sql", subject_version="1", facets=("schema",)
                ),
            }
        )
    evidence = claimed_evidence()
    with pytest.raises(ValidationError):
        SQLiteSelectQualityEvidence.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "retained_until": evidence.reviewed_at - timedelta(seconds=1),
            }
        )


def test_select_keywords_and_matching_body_digest_are_not_fact_checks() -> None:
    body = b"<html><body>SELECT * FROM t; this is untrusted text</body></html>"
    digest = hashlib.sha256(body).hexdigest()
    item = capture(body=body, digest=digest, revision=digest)
    verifier = SQLiteSelectQualityVerifier()
    assert verifier.audit(item).code == "EVIDENCE_MISSING"
    assert_not_qualified(verifier, item)


# Synthetic keys and fake proof resolver ONLY exist in this offline test file.
# These signatures/receipts are not production authority or actual SQLite review.
SYNTHETIC_PROOF_DIGEST = "5" * 64
SYNTHETIC_REVIEWER_ID = "reviewer.synthetic-test-only"
TEST_NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


class SyntheticTestProvenance:
    """Test double; NOT an implementation of current transport proof checking."""

    def resolve(self, item: CompleteCapture) -> str | None:
        return SYNTHETIC_PROOF_DIGEST if item == capture() else None


def synthetic_review(
    key: Ed25519PrivateKey,
    *,
    payload_changes: dict[str, object] | None = None,
    judgment_changes: dict[str, object] | None = None,
) -> SignedSQLiteSelectOperatorReview:
    judgment = OperatorQualityJudgment(
        version_fit="current",
        reading_fit="suitable",
        technical_status="correct",
        conflict_status="resolved",
        known_error="absent",
        covered_facets=("queries",),
        lineage_family="sqlite.synthetic-test-only",
    )
    if judgment_changes:
        judgment = judgment.model_copy(update=judgment_changes)
    payload = SQLiteSelectOperatorReviewPayload(
        format="aearn.sqlite-select.operator-review.v1",
        capture_id=capture().capture_id,
        lane="registered",
        source_handle=capture().source_handle,
        scope=SCOPE,
        revision=DIGEST,
        body_sha256=DIGEST,
        body_bytes=len(BODY),
        final_url=SQLITE_SELECT_URL,
        request_chain=(SQLITE_SELECT_URL,),
        origin="official",
        reading_level="beginner",
        license_id="PublicDomain",  # matches the schema's mixed-case license contract
        provenance_digest=SYNTHETIC_PROOF_DIGEST,
        judgment=judgment,
        reviewed_at=TEST_NOW - timedelta(hours=1),
        expires_at=TEST_NOW + timedelta(days=1),
    )
    if payload_changes:
        payload = payload.model_copy(update=payload_changes)
    return SignedSQLiteSelectOperatorReview(
        reviewer_key_id=SYNTHETIC_REVIEWER_ID,
        payload=payload,
        signature_hex=key.sign(canonical_operator_review_payload(payload)).hex(),
    )


def synthetic_verifier(
    key: Ed25519PrivateKey,
    review: SignedSQLiteSelectOperatorReview | None,
    *,
    enabled: bool = True,
    provenance: SyntheticTestProvenance | None = None,
    now: datetime = TEST_NOW,
    public_key: bytes | None = None,
) -> TrustedOperatorSQLiteSelectQualityVerifier:
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return TrustedOperatorSQLiteSelectQualityVerifier(
        review=review,
        reviewer_key_id=SYNTHETIC_REVIEWER_ID,
        reviewer_public_key=pub if public_key is None else public_key,
        provenance=provenance,
        enabled=enabled,
        clock=lambda: now,
    )


@pytest.fixture
def synthetic_test_key() -> Ed25519PrivateKey:
    # Ephemeral TEST-ONLY key; no persistence, config, or production receipt.
    return Ed25519PrivateKey.generate()


def test_signed_operator_judgment_is_opt_in_and_does_not_change_offline_adapter(
    synthetic_test_key: Ed25519PrivateKey,
) -> None:
    review = synthetic_review(synthetic_test_key)
    assert_not_qualified(SQLiteSelectQualityVerifier(), capture())
    assert (
        synthetic_verifier(
            synthetic_test_key,
            review,
            provenance=SyntheticTestProvenance(),
            enabled=False,
        )
        .verify(capture())
        .mode
        == "offline_protocol_only"
    )
    verifier = synthetic_verifier(
        synthetic_test_key,
        review,
        provenance=SyntheticTestProvenance(),
    )
    assert verifier.audit(capture()).code == "OPERATOR_REVIEWED"
    finding = verifier.verify(capture())
    assert finding.mode == "production"
    assert finding.covered_facets == ("queries",)
    assert _qualified(finding, capture().scope)


def test_wrong_pinned_key_or_key_id_denies(
    synthetic_test_key: Ed25519PrivateKey,
) -> None:
    review = synthetic_review(synthetic_test_key)
    other = Ed25519PrivateKey.generate()  # synthetic TEST-ONLY wrong key
    assert_not_qualified(
        synthetic_verifier(
            other,
            review,
            provenance=SyntheticTestProvenance(),
        ),
        capture(),
    )
    wrong_id = review.model_copy(update={"reviewer_key_id": "reviewer.other-test-only"})
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            wrong_id,
            provenance=SyntheticTestProvenance(),
        ),
        capture(),
    )


@pytest.mark.parametrize(
    "tamper",
    [
        {"body_bytes": len(BODY) + 1},
        {"provenance_digest": "0" * 64},
        {
            "judgment": OperatorQualityJudgment(
                version_fit="stale",
                reading_fit="suitable",
                technical_status="correct",
                conflict_status="resolved",
                known_error="absent",
                covered_facets=("queries",),
                lineage_family="sqlite.synthetic-test-only",
            )
        },
    ],
)
def test_signed_payload_tamper_denies(
    synthetic_test_key: Ed25519PrivateKey,
    tamper: dict[str, object],
) -> None:
    original = synthetic_review(synthetic_test_key)
    forged = original.model_copy(
        update={
            "payload": original.payload.model_copy(update=tamper),
        }
    )
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            forged,
            provenance=SyntheticTestProvenance(),
        ),
        capture(),
    )


@pytest.mark.parametrize("offset", [timedelta(days=2), -timedelta(hours=2)])
def test_expired_or_future_review_denies(
    synthetic_test_key: Ed25519PrivateKey,
    offset: timedelta,
) -> None:
    review = synthetic_review(synthetic_test_key)
    verifier = synthetic_verifier(
        synthetic_test_key,
        review,
        provenance=SyntheticTestProvenance(),
        now=TEST_NOW + offset,
    )
    assert_not_qualified(verifier, capture())


@pytest.mark.parametrize(
    "payload_change",
    [
        {"capture_id": UUID("00000000-0000-0000-0000-000000000002")},
        {"source_handle": "source.other"},
        {
            "scope": SubjectScope(
                subject_id="route.sql", subject_version="2", facets=("queries",)
            )
        },
        {"body_sha256": "0" * 64},
        {"body_bytes": len(BODY) + 1},
        {"revision": "0" * 64},
        {"origin": "third.party"},
        {"license_id": "license.other"},
    ],
)
def test_even_validly_signed_review_for_other_exact_capture_denies(
    synthetic_test_key: Ed25519PrivateKey,
    payload_change: dict[str, object],
) -> None:
    review = synthetic_review(synthetic_test_key, payload_changes=payload_change)
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            review,
            provenance=SyntheticTestProvenance(),
        ),
        capture(),
    )


@pytest.mark.parametrize(
    "judgment_change",
    [
        {"version_fit": "stale"},
        {"reading_fit": "unsuitable"},
        {"technical_status": "incorrect"},
        {"conflict_status": "unresolved"},
        {"known_error": "present"},
        {"covered_facets": ()},
    ],
)
def test_authenticated_but_unqualified_operator_judgment_denies(
    synthetic_test_key: Ed25519PrivateKey,
    judgment_change: dict[str, object],
) -> None:
    review = synthetic_review(synthetic_test_key, judgment_changes=judgment_change)
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            review,
            provenance=SyntheticTestProvenance(),
        ),
        capture(),
    )


def test_missing_or_mismatched_trusted_provenance_denies(
    synthetic_test_key: Ed25519PrivateKey,
) -> None:
    review = synthetic_review(synthetic_test_key)
    assert_not_qualified(synthetic_verifier(synthetic_test_key, review), capture())

    class NoCurrentProof:
        def resolve(self, item: CompleteCapture) -> str | None:
            return None  # legacy nullable/unverified proof

    class WrongCurrentProof:
        def resolve(self, item: CompleteCapture) -> str | None:
            return "0" * 64

    class BrokenCurrentProof:
        def resolve(self, item: CompleteCapture) -> str | None:
            raise RuntimeError("must not leak transport proof")

    for resolver in (NoCurrentProof(), WrongCurrentProof(), BrokenCurrentProof()):
        verifier = TrustedOperatorSQLiteSelectQualityVerifier(
            review=review,
            reviewer_key_id=SYNTHETIC_REVIEWER_ID,
            reviewer_public_key=synthetic_test_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            ),
            provenance=resolver,
            enabled=True,
            clock=lambda: TEST_NOW,
        )
        assert_not_qualified(verifier, capture())


def test_missing_pinned_key_review_or_malformed_copy_denies(
    synthetic_test_key: Ed25519PrivateKey,
) -> None:
    review = synthetic_review(synthetic_test_key)
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            None,
            provenance=SyntheticTestProvenance(),
        ),
        capture(),
    )
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            review,
            provenance=SyntheticTestProvenance(),
            public_key=b"missing",
        ),
        capture(),
    )
    forged = review.model_copy(
        update={
            "payload": review.payload.model_copy(
                update={"provenance_digest": "not-a-hash"}
            ),
        }
    )
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            forged,
            provenance=SyntheticTestProvenance(),
        ),
        capture(),
    )


def test_claimed_page_keywords_cannot_replace_review_or_current_proof(
    synthetic_test_key: Ed25519PrivateKey,
) -> None:
    body = b"<html><body>SELECT reliable current suitable no errors</body></html>"
    digest = hashlib.sha256(body).hexdigest()
    item = capture(body=body, digest=digest, revision=digest)
    review = synthetic_review(synthetic_test_key)
    assert_not_qualified(
        synthetic_verifier(
            synthetic_test_key,
            review,
            provenance=SyntheticTestProvenance(),
        ),
        item,
    )


def test_formal_eight_mib_quality_gate_accepts_size_but_not_unreviewed_content():
    assert MAX_BODY_BYTES == 8_388_608
    body = b"x" * MAX_BODY_BYTES  # synthetic bytes, not a claim about SQLite
    digest = hashlib.sha256(body).hexdigest()
    complete = capture(body=body, digest=digest, revision=digest)
    assert SQLiteSelectQualityVerifier().audit(complete).code == "EVIDENCE_MISSING"
    assert SQLiteSelectQualityVerifier().audit(
        capture(body=body + b"x", digest=hashlib.sha256(body + b"x").hexdigest(),
                revision=hashlib.sha256(body + b"x").hexdigest())
    ).code == "CAPTURE_INVALID"
    claim = claimed_evidence().model_dump()
    claim["body_bytes"] = MAX_BODY_BYTES
    assert SQLiteSelectQualityEvidence.model_validate(claim).body_bytes == MAX_BODY_BYTES
    claim["body_bytes"] += 1
    with pytest.raises(ValidationError):
        SQLiteSelectQualityEvidence.model_validate(claim)
