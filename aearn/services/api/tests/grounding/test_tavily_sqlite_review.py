from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from app.services.grounding.autonomous.contracts import SubjectScope
from app.services.grounding.autonomous.source_review_repository import CompleteCapture
from app.services.grounding.autonomous.sqlite_select_automated_review import CLAIMS, SignedAutomatedReview
from app.services.grounding.autonomous.sqlite_select_quality import SQLITE_SELECT_URL
from app.services.grounding.autonomous.tavily_sqlite_review import (
    TavilySQLiteReviewVerifier, canonical_tavily_sqlite_review,
    evaluate_tavily_sqlite, sign_tavily_sqlite_review,
)


def _capture(text: str | None = None) -> CompleteCapture:
    where = CLAIMS['where_true'].replace('boolean expression', '[boolean expression](/lang_expr.html#booleanexpr)')
    body = (text or '# SELECT\n\n'+where+'\n\n'+CLAIMS['limit']+'\n\nUnrelated [link](https://example.org).').encode()
    digest = sha256(body).hexdigest()
    return CompleteCapture(uuid4(), 'registered', body, digest, digest,
        SubjectScope(subject_id='route.sql', subject_version='sqlite-docs-v1', facets=('queries',)),
        'sqlite.select.tavily.unit', SQLITE_SELECT_URL, (SQLITE_SELECT_URL,),
        'official', 'beginner', 'Public-Domain')


def test_provider_markdown_exact_complete_excerpts_are_supported_without_html_wrapping():
    result = evaluate_tavily_sqlite(_capture())
    assert result.code == 'SUPPORTED'
    assert result.claim_ids == ('limit', 'where_true') and result.excerpt_count == 2


@pytest.mark.parametrize('prefix,suffix', [('> ', ''), ('```\n', '\n```'), ('This is false: ', '')])
def test_quoted_code_or_negated_claim_is_not_promoted(prefix, suffix):
    text = prefix+CLAIMS['where_true']+suffix+'\n\n'+CLAIMS['limit']
    assert evaluate_tavily_sqlite(_capture(text)).code == 'QUARANTINED'


def test_signed_provider_review_keeps_domain_provenance_and_exact_returned_bytes():
    class Provenance:
        digest: str | None = 'a'*64
        def provenance_digest(self, capture, *, expected_format=None):
            assert expected_format == 'markdown'
            return self.digest

    capture = _capture()
    provenance = Provenance()
    key = Ed25519PrivateKey.generate()
    now = datetime(2026, 9, 28, tzinfo=UTC)
    review = sign_tavily_sqlite_review(capture, provenance=provenance, private_key=key,
        service_key_id='service.sqlite-select.core.v1', now=now,
        expires_at=now+timedelta(hours=1), enabled=True)
    verifier = TavilySQLiteReviewVerifier(review=review, service_key_id=review.service_key_id,
        service_public_key=key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
        provenance=provenance, enabled=True, clock=lambda: now)
    assert verifier.verify(capture).mode == 'production'
    assert verifier.reviewed_usages(capture) == ('supplementary_explanation',)
    assert all(value.encode() in capture.body for value in verifier.approved_excerpts(capture))
    assert review.payload.representation == 'provider_extracted_markdown'
    with pytest.raises(ValidationError):
        SignedAutomatedReview.model_validate_json(canonical_tavily_sqlite_review(review))
    provenance.digest = None
    assert verifier.verify(capture).mode == 'offline_protocol_only'
