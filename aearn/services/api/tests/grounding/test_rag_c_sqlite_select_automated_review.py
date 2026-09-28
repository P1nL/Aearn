"""No provider/network/real DB: bounded service review and adversarial counterexamples."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.grounding.autonomous.contracts import SubjectScope
from app.services.grounding.autonomous.source_review_repository import CompleteCapture
from app.services.grounding.autonomous.sqlite_select_automated_review import (
    CLAIMS, WHERE_PARAGRAPH, AutomatedReviewDenied, SQLiteSelectAutomatedReviewVerifier,
    canonical_signed_review, evaluate, sign_service_review,
)

NOW = datetime(2026, 9, 25, 15, 0, tzinfo=UTC)
URL = "https://www.sqlite.org/lang_select.html"


class Provenance:
    def __init__(self) -> None:
        self.current = "a" * 64
        self.calls = 0

    def resolve(self, capture: CompleteCapture) -> str | None:
        self.calls += 1
        return self.current


def capture(*sentences: str) -> CompleteCapture:
    body = ("<!doctype html><html><head><title>SELECT</title></head><body>"
            + "".join("<p>" + sentence + "</p>" for sentence in sentences)
            + "</body></html>").encode()
    digest = hashlib.sha256(body).hexdigest()
    return CompleteCapture(uuid4(), "registered", body, digest, digest,
                           SubjectScope(subject_id="route.sql", subject_version="v1", facets=("queries",)),
                           "source.sqlite", URL, (URL,), "official", "beginner", "public-domain")


def signed(c: CompleteCapture):  # type: ignore[no-untyped-def]
    key = Ed25519PrivateKey.generate()  # isolated test-only key, never a production trust anchor
    provenance = Provenance()
    review = sign_service_review(c, provenance=provenance, private_key=key,
                                 service_key_id="review.service.test", now=NOW,
                                 expires_at=NOW + timedelta(hours=1), enabled=True)
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    verifier = SQLiteSelectAutomatedReviewVerifier(
        review=review, service_key_id="review.service.test", service_public_key=public,
        provenance=provenance, enabled=True, clock=lambda: NOW + timedelta(minutes=1))
    return review, verifier, provenance, public


def test_exact_excerpt_service_receipt_and_bounded_oracle() -> None:
    c = capture(*CLAIMS.values())
    probe = evaluate(c)
    assert probe.code == "SUPPORTED"
    assert set(probe.claim_ids) == set(CLAIMS)
    assert probe.excerpt_count == 2
    review, verifier, provenance, _ = signed(c)
    assert review.payload.reviewer_kind == "automated_service"
    assert review.payload.quality_scope == "approved_excerpts_only"
    assert review.payload.profile == "sqlite-select-exact-excerpts-v1"
    assert verifier.verify(c).mode == "production"
    assert verifier.verify(c).covered_facets == ("queries",)
    assert verifier.reviewed_usages(c) == ("supplementary_explanation",)
    excerpts = verifier.approved_excerpts(c)
    assert excerpts == tuple(CLAIMS.values())
    assert all(x.encode() in c.body for x in excerpts)
    assert len(canonical_signed_review(review)) > 64
    assert provenance.calls >= 3


def test_default_off_and_signer_without_external_provenance_denied() -> None:
    c = capture(WHERE_PARAGRAPH, CLAIMS["limit"])
    key = Ed25519PrivateKey.generate()
    p = Provenance()
    with pytest.raises(AutomatedReviewDenied, match="SIGNER_DISABLED"):
        sign_service_review(c, provenance=p, private_key=key, service_key_id="service.test",
                            now=NOW, expires_at=NOW + timedelta(hours=1))
    assert p.calls == 0
    p.current = None  # type: ignore[assignment]
    with pytest.raises(AutomatedReviewDenied, match="PROVENANCE_UNVERIFIED"):
        sign_service_review(c, provenance=p, private_key=key, service_key_id="service.test",
                            now=NOW, expires_at=NOW + timedelta(hours=1), enabled=True)
    assert SQLiteSelectAutomatedReviewVerifier().verify(c).mode == "offline_protocol_only"
    assert SQLiteSelectAutomatedReviewVerifier().approved_excerpts(c) == ()


@pytest.mark.parametrize("poison", [
    "LIMIT SELECT DISTINCT WHERE", "This is false: " + CLAIMS["limit"],
    "WARNING: " + CLAIMS["limit"],
    CLAIMS["where_true"].replace("true", "false"),
    CLAIMS["limit"].replace("upper bound", "no upper bound"),
    "<script>" + CLAIMS["limit"] + "</script>",
    "<svg><text>" + CLAIMS["limit"] + "</text></svg>",
    "<blockquote>" + CLAIMS["limit"] + "</blockquote>",
])
def test_keywords_negation_warning_and_hidden_markup_do_not_qualify(poison: str) -> None:
    assert evaluate(capture(poison)).code == "QUARANTINED"


def test_malformed_html_and_unknown_profile_quarantine() -> None:
    original = capture(WHERE_PARAGRAPH, CLAIMS["limit"])
    for text in (b"<p>broken", b"</wrong>", b"<script>unfinished", b"<p title=\"unterminated", b"not html", b"\xff"):
        body = original.body + text
        c = replace(original, body=body, digest=hashlib.sha256(body).hexdigest(),
                    revision=hashlib.sha256(body).hexdigest())
        assert evaluate(c).code == "QUARANTINED"
    assert evaluate(capture("Other dialect SELECT trivia.")).code == "QUARANTINED"


def test_signature_body_span_identity_provenance_and_time_rechecked() -> None:
    c = capture(WHERE_PARAGRAPH, CLAIMS["limit"])
    review, verifier, provenance, public = signed(c)
    assert verifier.verify(c).mode == "production"
    modified = c.body.replace(b"upper bound", b"no upper bound")
    wrong = replace(c, body=modified, digest=hashlib.sha256(modified).hexdigest(),
                    revision=hashlib.sha256(modified).hexdigest())
    assert verifier.verify(wrong).mode == "offline_protocol_only"
    assert verifier.approved_excerpts(wrong) == ()
    assert verifier.verify(replace(c, capture_id=uuid4())).mode == "offline_protocol_only"
    forged = review.model_copy(update={"signature_hex": "0" * 128})
    bad = SQLiteSelectAutomatedReviewVerifier(
        review=forged, service_key_id="review.service.test", service_public_key=public,
        provenance=provenance, enabled=True, clock=lambda: NOW + timedelta(minutes=1))
    assert bad.verify(c).mode == "offline_protocol_only"
    provenance.current = "b" * 64
    assert verifier.verify(c).mode == "offline_protocol_only"
    provenance.current = "a" * 64
    expired = SQLiteSelectAutomatedReviewVerifier(
        review=review, service_key_id="review.service.test", service_public_key=public,
        provenance=provenance, enabled=True, clock=lambda: NOW + timedelta(hours=1))
    assert expired.reviewed_usages(c) == ()
    wrong_key = SQLiteSelectAutomatedReviewVerifier(
        review=review, service_key_id="review.service.other", service_public_key=public,
        provenance=provenance, enabled=True, clock=lambda: NOW)
    assert wrong_key.verify(c).mode == "offline_protocol_only"


def test_profile_receipt_cannot_add_usage_or_alter_excerpt() -> None:
    c = capture(WHERE_PARAGRAPH, CLAIMS["limit"])
    review, _, provenance, public = signed(c)
    tampered_payload = review.payload.model_copy(update={"usages": ("main_teaching",)})
    forged = review.model_copy(update={"payload": tampered_payload})
    verifier = SQLiteSelectAutomatedReviewVerifier(
        review=forged, service_key_id="review.service.test", service_public_key=public,
        provenance=provenance, enabled=True, clock=lambda: NOW)
    assert verifier.verify(c).mode == "offline_protocol_only"
    altered = review.payload.excerpts[0].model_copy(update={"start_byte": 0})
    forged = review.model_copy(update={"payload": review.payload.model_copy(update={"excerpts": (altered,)})})
    verifier = SQLiteSelectAutomatedReviewVerifier(
        review=forged, service_key_id="review.service.test", service_public_key=public,
        provenance=provenance, enabled=True, clock=lambda: NOW)
    assert verifier.approved_excerpts(c) == ()


def test_utf8_offsets_and_exact_inline_markup_bytes() -> None:
    c = capture("é — " + CLAIMS["limit"])
    assert evaluate(c).code == "QUARANTINED"  # paragraph prefix poisons an assertion
    body = ("<!doctype html><html><body><p>Non-ASCII é is not reviewed.</p><p>"
            + WHERE_PARAGRAPH + "</p><p>" + CLAIMS["limit"] + "</p></body></html>").encode()
    digest = hashlib.sha256(body).hexdigest()
    c = replace(c, body=body, digest=digest, revision=digest)
    assert evaluate(c).claim_ids == ("limit", "where_true")
    _, verifier, _, _ = signed(c)
    assert verifier.approved_excerpts(c) == (WHERE_PARAGRAPH, CLAIMS["limit"])


def test_unrelated_html_optional_closes_do_not_validate_unsupported_unit() -> None:
    body = ("<!doctype html><html><body><div><p>" + WHERE_PARAGRAPH +
            "<h2>Other heading</h2><p>" + CLAIMS["limit"] +
            "</p><p>The LIMIT clause is not a general dialect certificate.").encode()
    c = capture(WHERE_PARAGRAPH, CLAIMS["limit"])
    digest = hashlib.sha256(body).hexdigest()
    c = replace(c, body=body, digest=digest, revision=digest)
    # Missing optional document/block ends and a separate unsupported paragraph
    # cannot expand the exact supported first unit.
    assert evaluate(c).claim_ids == ("limit", "where_true")
    _, verifier, _, _ = signed(c)
    assert len(verifier.approved_excerpts(c)) == 2


def test_explicit_conflicting_context_quarantines_even_with_other_valid_unit() -> None:
    c = capture(WHERE_PARAGRAPH, CLAIMS["limit"], "This is false: " + CLAIMS["limit"])
    assert evaluate(c).code == "QUARANTINED"
    c = capture(WHERE_PARAGRAPH, "<blockquote><p>" + CLAIMS["limit"] + "</p></blockquote>")
    assert evaluate(c).code == "QUARANTINED"


def test_exact_three_sentence_where_unit_without_subspan_extraction() -> None:
    c = capture(WHERE_PARAGRAPH, CLAIMS["limit"])
    assert evaluate(c).claim_ids == ("limit", "where_true")
    _, verifier, _, _ = signed(c)
    assert verifier.approved_excerpts(c) == (WHERE_PARAGRAPH, CLAIMS["limit"])
    assert verifier.reviewed_usages(c) == ("supplementary_explanation",)
    # A single inserted negation, caveat or fourth sentence poisons that unit.
    altered = capture(WHERE_PARAGRAPH.replace("true", "not true"), CLAIMS["limit"])
    assert evaluate(altered).code == "QUARANTINED"
    altered = capture(WHERE_PARAGRAPH + " This statement is false.", CLAIMS["limit"])
    assert evaluate(altered).code == "QUARANTINED"


def test_profile_requires_exactly_two_distinct_reviewed_units() -> None:
    assert evaluate(capture(CLAIMS["limit"])).code == "QUARANTINED"
    assert evaluate(capture(WHERE_PARAGRAPH)).code == "QUARANTINED"
    assert evaluate(capture(WHERE_PARAGRAPH, CLAIMS["limit"], CLAIMS["limit"])).code == "QUARANTINED"
    assert evaluate(capture(WHERE_PARAGRAPH, CLAIMS["limit"], "Other SQL topic.")).excerpt_count == 2
