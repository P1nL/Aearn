"""Original ItemBank PRIVATE native publication/current reader; producer expiry is history."""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_bank.native_publication_contracts import build_native_practice_material
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.native_type_fingerprints import semantic_payload
from app.services.learning.item_supply.private_enhancement_contracts import PrivateNativePending, PrivateNativePublicationV1, PrivateNativeQualityV1, PrivateResolvedContent
from app.services.learning.item_supply.private_native_admission_facts import PrivateNativeAdmissionFactsOwner
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import lock_private_namespace, server_clock
from app.services.learning.item_supply.type_evidence import ContentIdentityV2
from app.services.learning.practice.repository import PostgresExerciseGateRepository

PUBLICATIONS = 'tutor_item_supply_private_native_publications'
QUALITY = 'tutor_item_supply_private_native_quality_evidence'


def private_content_identity(quality: PrivateNativeQualityV1) -> ContentIdentityV2:
    inputs = prepare_finite_candidate_validation(quality.source, spec=quality.spec, materials=quality.request.materials)
    fixture = inputs.static_facts.instance_hash if inputs.static_facts else None if inputs.probe_plan is None else inputs.probe_plan.server_fixture_hash
    if fixture is None:
        raise PrivateNativePending('private_native_actual_fixture_required')
    semantic = semantic_payload(quality.source, quality.spec)
    return ContentIdentityV2(item_handle='lip:v2:' + str(quality.version_id), version_id=quality.version_id,
        content_hash=quality.source.content_hash, actual_public_task_hash=quality.source.public.public_hash,
        actual_fixture_hash=fixture, decision_signature=canonical_hash({'domain': 'decision', 'semantics': semantic}),
        answer_leakage_signature=canonical_hash({'domain': 'contextual-solution', 'semantics': semantic}),
        author_id=uuid5(NAMESPACE_URL, 'aearn:item-author:' + quality.bundle.author_identity))


class PrivateNativePublicationOwner:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 facts_owner: PrivateNativeAdmissionFactsOwner, enabled: bool = False) -> None:
        if type(facts_owner) is not PrivateNativeAdmissionFactsOwner or facts_owner.conn is not conn or facts_owner.settings is not settings:
            raise PrivateNativePending('private_publication_concrete_facts_required')
        self.conn, self.settings, self.facts_owner, self.enabled = conn, settings, facts_owner, enabled
        self._published: dict[UUID, PrivateNativePublicationV1] = {}

    def publish_internal(self, quality: PrivateNativeQualityV1) -> PrivateNativePublicationV1:
        if not self.enabled:
            raise PrivateNativePending('private_publication_disabled')
        quality = self.facts_owner.verify(quality)
        # Sources FIRST, then bank/private version. Repeat after every lock wait.
        for material_ref, expected in zip(quality.request.materials, quality.source_receipts, strict=True):
            self.facts_owner.source_authority.assert_current(material_ref, expected)
        row = self.conn.execute('SELECT * FROM tutor_item_supply_private_versions WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s FOR UPDATE',
            (quality.version_id, quality.ref.user_id, quality.ref.epoch, quality.ref.scope_id)).fetchone()
        if (row is None or row['public_json'] != quality.source.public.model_dump(mode='json')
                or row['private_json'] != quality.source.private.model_dump(mode='json')
                or row['id'] != quality.version_id):
            raise PrivateNativePending('private_publication_actual_version_required')
        quality = self.facts_owner.verify(quality)
        material = build_native_practice_material(quality.source, spec=quality.spec, materials=quality.request.materials)
        # The original Exercise authority writer is reused, never a fake exercise handle.
        exercise_id = UUID(PostgresExerciseGateRepository(self.conn).ensure_exercise_authority(material.exercise, material.rubric, now=quality.checked_at))
        mid = uuid5(NAMESPACE_URL, 'aearn:private-native-material:' + str(quality.receipt_id))
        material_hash = canonical_hash({'version_id': str(quality.version_id), 'exercise_version_id': str(exercise_id),
            'content_hash': quality.source.content_hash, 'exercise_content_hash': material.exercise.content_hash,
            'rubric_hash': material.rubric.rubric_hash, 'runner': dict(material.runner_payload)})
        stamp = server_clock(self.conn, datetime.now(UTC))
        publication = PrivateNativePublicationV1(publication_id=uuid4(), quality_id=quality.receipt_id,
            ref=quality.ref, version_id=quality.version_id, item_handle='lip:v2:' + str(row['id']), source_hash=quality.source.source_hash,
            content_hash=quality.source.content_hash, materialization_id=mid, exercise_version_id=exercise_id,
            exercise_content_hash=material.exercise.content_hash, rubric_hash=material.rubric.rubric_hash,
            materialization_hash=material_hash, quality_hash=quality.receipt_hash, runner_material=dict(material.runner_payload),
            checked_at=stamp, producer_valid_until=quality.valid_until)
        self.conn.execute('INSERT INTO ' + PUBLICATIONS + ' (id,user_id,epoch,scope_id,pack_task_id,slot_id,root_id,version_id,quality_id,state,state_version,payload_json,exercise_version_id,content_json) '
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'published',1,%s,%s,%s)",
            (publication.publication_id, quality.ref.user_id, quality.ref.epoch, quality.ref.scope_id, quality.ref.pack_task_id,
             quality.ref.slot_id, quality.ref.root_id, quality.version_id, quality.receipt_id,
             Jsonb(publication.model_dump(mode='json')), exercise_id,
             Jsonb(private_content_identity(quality).model_dump(mode='json'))))
        self.facts_owner.verify(quality)
        self._published[publication.publication_id] = publication
        return publication


class PrivateNativePublicationQuery:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, user_id: UUID, expected_epoch: int,
                 source_authority: RagSourceAuthority, enabled: bool = False) -> None:
        if type(source_authority) is not RagSourceAuthority or source_authority.connection is not conn:
            raise PrivateNativePending('private_query_same_source_owner_required')
        self.conn, self.settings, self.user_id, self.epoch = conn, settings, user_id, expected_epoch
        self.source_authority, self.enabled = source_authority, enabled

    def _guard(self) -> datetime:
        if (not self.enabled or not self.settings.learning_item_supply_enabled or not self.settings.learning_item_v2_admission_enabled
                or self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS):
            raise PrivateNativePending('private_query_current_transaction_required')
        lock_private_namespace(self.conn, self.user_id, self.epoch)
        isolation = self.conn.execute('SHOW transaction_isolation').fetchone()
        if isolation is None or isolation['transaction_isolation'] != 'read committed':
            raise PrivateNativePending('private_query_read_committed_required')
        return server_clock(self.conn, datetime.now(UTC))

    def resolve_content(self, version_id: UUID, *, current: bool = True) -> PrivateResolvedContent:
        self._guard()
        row = self.conn.execute('SELECT p.payload_json,p.payload_hash,p.content_json,q.payload_json AS quality_json,q.payload_hash AS quality_hash, '
            'p.xmin::text::bigint=(txid_current() %% 4294967296) AS own,q.xmin::text::bigint=(txid_current() %% 4294967296) AS quality_own '
            'FROM ' + PUBLICATIONS + ' p JOIN ' + QUALITY + " q ON q.id=p.quality_id AND q.user_id=p.user_id AND q.epoch=p.epoch WHERE p.version_id=%s AND p.user_id=%s AND p.epoch=%s AND p.state='published' ORDER BY p.state_version LIMIT 1",
            (version_id, self.user_id, self.epoch)).fetchone()
        if row is None or row['own'] or row['quality_own']:
            raise PrivateNativePending('private_query_committed_publication_required')
        publication = PrivateNativePublicationV1.model_validate_json(json.dumps(row['payload_json']))
        quality = PrivateNativeQualityV1.model_validate_json(json.dumps(row['quality_json']))
        if (publication.publication_hash != row['payload_hash'] or quality.receipt_hash != row['quality_hash']
                or publication.quality_hash != quality.receipt_hash or publication.quality_id != quality.receipt_id
                or publication.ref != quality.ref or quality.version_id != publication.version_id
                or not quality.checked_at <= publication.checked_at < quality.valid_until):
            raise PrivateNativePending('private_query_quality_history_required')
        material = build_native_practice_material(quality.source, spec=quality.spec, materials=quality.request.materials)
        if (publication.source_hash != quality.source.source_hash or publication.content_hash != quality.source.content_hash
                or material.exercise.content_hash != publication.exercise_content_hash or material.rubric.rubric_hash != publication.rubric_hash
                or dict(material.runner_payload) != publication.runner_material):
            raise PrivateNativePending('private_query_materialization_identity_required')
        identity = private_content_identity(quality)
        if row['content_json'] != identity.model_dump(mode='json'):
            raise PrivateNativePending('private_query_actual_semantic_fingerprints_required')
        result = PrivateResolvedContent(publication, quality, identity)
        if not current:
            return result  # Historical DATA for actual exposure, never a current capability.
        for material_ref, expected in zip(quality.request.materials, quality.source_receipts, strict=True):
            self.source_authority.assert_current(material_ref, expected)
        locked = self.conn.execute('SELECT id FROM tutor_item_supply_private_versions WHERE id=%s AND user_id=%s AND epoch=%s FOR SHARE',
            (version_id, self.user_id, self.epoch)).fetchone()
        latest = self.conn.execute('SELECT id,state FROM ' + PUBLICATIONS + ' WHERE version_id=%s AND user_id=%s AND epoch=%s ORDER BY state_version DESC LIMIT 1',
            (version_id, self.user_id, self.epoch)).fetchone()
        if locked is None or latest is None or latest['state'] != 'published' or UUID(str(latest['id'])) != publication.publication_id:
            raise PrivateNativePending('private_query_retired_or_quarantined')
        receipt_hashes = []
        deadline = self._guard() + timedelta(seconds=30)
        for material_ref, expected in zip(quality.request.materials, quality.source_receipts, strict=True):
            received = self.source_authority.assert_current(material_ref, expected)
            receipt_hashes.append(canonical_hash(received.model_dump(mode='json')))
            reviews = self.source_authority._current.governance.source_reviews
            coordinate = material_ref.binding.evidence[0].binding
            review = None if reviews is None else reviews.resolve(coordinate.source_handle, coordinate.document_handle)
            if review is None or review.grant is None:
                raise PrivateNativePending('private_query_source_current_required')
            deadline = min(deadline, review.grant.retained_until)
        now = self._guard()
        if now >= deadline:
            raise PrivateNativePending('private_query_current_expired')
        # KC uses genuinely recomputed static semantics, not OS availability fiction.
        inputs = prepare_finite_candidate_validation(quality.source, spec=quality.spec, materials=quality.request.materials)
        if inputs.static_facts is None:
            raise PrivateNativePending('private_query_current_execution_owner_required')
        return replace(result, observed_at=now, valid_until=deadline, source_set_hash=canonical_hash(receipt_hashes))
