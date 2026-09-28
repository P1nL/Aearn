"""Synthetic timestamps, real signature/oracle: long C fetch is not stale dial authority."""
import hashlib
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.grounding.autonomous.registered_source_bridge_host import _canonical
from app.services.grounding.autonomous.registered_source_provenance import (
    PostgresCurrentCaptureProvenanceResolver,
)
from app.services.grounding.autonomous.sqlite_select_automated_review import (
    CLAIMS, SQLiteSelectAutomatedReviewVerifier, sign_service_review,
)
from tests.grounding.test_rag_c_registered_source_provenance import IMAGE, fixture


@pytest.mark.parametrize("fetch_seconds", [61, 299, 300])
def test_long_full_report_settlement_historical_provenance_and_automated_review(fetch_seconds):
    conn, verifier, capture, proof = fixture()
    body = ("<html><body>" + "".join("<p>" + text + "</p>" for text in CLAIMS.values())
            + "</body></html>").encode()
    digest = hashlib.sha256(body).hexdigest()
    settled = conn.attempt["settled_at"]
    reported = int(settled.timestamp() * 1000) - 500
    pre_dial = reported - fetch_seconds * 1000
    proof["egress"]["receipt"]["expires_unix"] = pre_dial // 1000 + 3
    private = Ed25519PrivateKey.from_private_bytes(b"\x07" * 32)
    proof["egress"]["signature"] = private.sign(_canonical(proof["egress"]["receipt"])).hex()
    proof["worker_fetch_report"].update(pre_dial_unix_ms=pre_dial, reported_unix_ms=reported,
        body_sha256=digest, body_bytes=len(body), wire_bytes=len(body))
    conn.attempt.update(dispatched_at=settled-timedelta(seconds=fetch_seconds+2),
                        response_sha256=digest, response_bytes=len(body))
    conn.row.update(captured_body=body, captured_bytes=len(body), fetched_sha256=digest,
                    transport_proof=_canonical(proof),
                    transport_proof_sha256=hashlib.sha256(_canonical(proof)).hexdigest())
    capture = replace(capture, body=body, digest=digest, revision=digest)
    report = proof["worker_fetch_report"]
    wire_scope = SimpleNamespace(policy_id=report["policy_id"], generation=report["generation"],
        source_handle=capture.source_handle, subject_id=capture.scope.subject_id,
        subject_version=capture.scope.subject_version, facets=capture.scope.facets,
        url=report["url"], host=report["host"], path="/lang_select.html", root_id=report["root_id"],
        dispatch_id=report["dispatch_id"], max_bytes=1048576)
    assert verifier.verify(wire_scope, proof, now=settled) is not None
    # The 60-second bound remains on report delivery, not elapsed fetch duration.
    assert verifier.verify(wire_scope, proof, now=settled+timedelta(seconds=61)) is None
    resolver = PostgresCurrentCaptureProvenanceResolver(conn, verifier=verifier,
                                                       worker_image_sha256=IMAGE)
    assert resolver.resolve(capture) == conn.row["transport_proof_sha256"]
    key = Ed25519PrivateKey.from_private_bytes(b"\x08" * 32)
    now = conn.now
    review = sign_service_review(capture, provenance=resolver, private_key=key,
        service_key_id="fixture.long-c-review", now=now, expires_at=now+timedelta(minutes=10), enabled=True)
    automated = SQLiteSelectAutomatedReviewVerifier(review=review,
        service_key_id="fixture.long-c-review",
        service_public_key=key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        provenance=resolver, enabled=True, clock=lambda: now)
    assert automated.reviewed_usages(capture) == ("supplementary_explanation",)
    assert automated.approved_excerpts(capture) == tuple(CLAIMS.values())
    # An actually expired pre-dial grant is still rejected, even with a valid signature.
    proof["egress"]["receipt"]["expires_unix"] = pre_dial // 1000
    proof["egress"]["signature"] = private.sign(_canonical(proof["egress"]["receipt"])).hex()
    assert verifier.verify(wire_scope, proof, now=settled) is None
