"""C12 frozen-body and real model contracts; no PG/Artifact acceptance."""
from pathlib import Path
import re
from uuid import uuid4

from pydantic import ValidationError
import pytest

from app.db.schema import SCHEMA_FRAGMENT_NAMES
from app.services.learning.item_bank.contracts import LearningItemPublicV1
from app.services.learning.item_supply.jobs import JobLeaseV1
from tests.learning.test_item_supply_generation import make_request
from tests.learning.test_item_supply_shared_validation import _candidate


SCHEMA = Path(__file__).resolve().parents[2] / 'app/db/schema'
FRAGMENT = '557_learning_item_native_consumer_public_contract.sql'
OLD_JOIN = " JOIN tutor_learning_item_public_contents pub ON pub.version_id=v.id AND pub.public_json->>'visibility'='public'"
NEW_JOIN = """ JOIN tutor_learning_item_public_contents pub ON pub.version_id=v.id
   AND pub.schema_version='learning_item_public_v1'
   AND pub.public_json->>'schema_version'='learning_item_public_v1'
   AND proof.proof_json->'lease'->>'visibility'='public'
   AND proof.proof_json->'lease'->'owner_id'='null'::jsonb
   AND proof.proof_json->'lease'->'owner_epoch'='null'::jsonb"""


def _fragment_parts() -> tuple[str, str, str]:
    sql = (SCHEMA / FRAGMENT).read_text(encoding='utf-8')
    old = sql.split('old_body constant text := $old557$', 1)[1].split('$old557$;', 1)[0]
    new = sql.split('new_body constant text := $new557$', 1)[1].split('$new557$;', 1)[0]
    return old, new, sql.split('$new557$;', 1)[1]


def test_557_full_final549_body_changes_only_the_approved_public_join() -> None:
    source = (SCHEMA / '549_learning_item_current_pack_source_origin_v1.sql').read_text(encoding='utf-8')
    original = re.search(
        r'CREATE OR REPLACE FUNCTION item_supply_internal\.native_consumer_receipt_current\(receipt_id uuid\) RETURNS boolean\n'
        r'LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS \$current549\$'
        r'(.*?)\$current549\$;', source, re.S,
    )
    assert original is not None
    old, new, _ = _fragment_parts()
    assert old == original.group(1)
    assert old.count(OLD_JOIN) == 1 and new.count(NEW_JOIN) == 1
    # Whole-body equality also preserves both modes, source loops, nine fields,
    # source-origin ordering, publication/teaching/postwait and all deadlines.
    assert new == old.replace(OLD_JOIN, NEW_JOIN)
    assert "pub.public_json->>'visibility'" not in new
    assert 'COALESCE' not in NEW_JOIN


def test_557_exact_replay_and_full_nonbody_metadata_guards_precede_replacement() -> None:
    _, _, installer = _fragment_parts()
    replay = installer.index('IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;')
    replacement = installer.index('EXECUTE replace(definition,old_body,new_body);')
    assert installer.count('EXECUTE ') == 1
    assert installer.count("to_regprocedure('item_supply_internal.native_consumer_receipt_current(uuid)')") == 1
    for guard in (
        "actual.proname IS DISTINCT FROM 'native_consumer_receipt_current'",
        "actual.lanname IS DISTINCT FROM 'plpgsql'", "actual.prokind<>'f'",
        'actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof',
        "actual.provolatile<>'v' OR actual.proparallel<>'u'",
        "actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype",
        "actual.proargnames IS DISTINCT FROM ARRAY['receipt_id']",
        'actual.pronargs<>1', 'actual.proargtypes IS DISTINCT FROM',
        'actual.proallargtypes IS NOT NULL', 'actual.proargmodes IS NOT NULL',
        'actual.provariadic<>0', 'actual.pronargdefaults<>0', 'actual.proargdefaults IS NOT NULL',
        'actual.probin IS NOT NULL', 'actual.prosqlbody IS NOT NULL', 'actual.protrftypes IS NOT NULL',
        'actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0',
        "actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']",
        "privilege.grantee=0 AND privilege.privilege_type='EXECUTE'",
    ):
        assert installer.index(guard) < replay
    assert replay < installer.index('IF actual.prosrc IS DISTINCT FROM old_body') < replacement
    assert installer.index("length(definition)-length(replace(definition,old_body,''))<>length(old_body)") < replacement
    assert "WHERE p.oid=actual.oid" in installer[replacement:]
    assert "(to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')" in installer[replacement:]
    assert 'verified.prosrc IS DISTINCT FROM new_body' in installer[replacement:]
    assert not re.search(r'^\s*(?:UPDATE|DELETE|INSERT|COMMIT|GRANT|REVOKE|ALTER|DROP)\b', installer, re.M | re.I)


def test_557_is_registered_once_directly_after_556_without_full_bootstrap() -> None:
    index = SCHEMA_FRAGMENT_NAMES.index('556_learning_item_current_pack_ttl120.sql')
    assert SCHEMA_FRAGMENT_NAMES[index+1] == FRAGMENT
    assert SCHEMA_FRAGMENT_NAMES.count(FRAGMENT) == 1
    assert (SCHEMA / FRAGMENT).is_file()


def test_strict_public_content_serializes_schema_but_forbids_visibility() -> None:
    _, _, source = _candidate('python-kc-binding-v1')
    public = LearningItemPublicV1.model_validate(source.public.model_dump())
    payload = public.model_dump(mode='json')
    assert payload['schema_version'] == 'learning_item_public_v1'
    assert 'visibility' not in payload and 'visibility' not in LearningItemPublicV1.model_fields
    with pytest.raises(ValidationError) as extra:
        LearningItemPublicV1.model_validate({**payload, 'visibility': 'public'})
    assert any(error['loc'] == ('visibility',) and error['type'] == 'extra_forbidden' for error in extra.value.errors())
    with pytest.raises(ValidationError):
        LearningItemPublicV1.model_validate({**payload, 'schema_version': 'wrong_public_schema'})


def _public_lease() -> JobLeaseV1:
    request, _ = make_request()
    deadline = request.profile.parent_deadline_at
    return JobLeaseV1(job_id=uuid4(), visibility='public', lease_owner='offline.public.contract',
        generation=1, state_version=1, expires_at=deadline, parent_deadline=deadline, profile=request.profile)


def test_public_lease_serializes_explicit_json_null_namespace_owners() -> None:
    lease = _public_lease()
    payload = lease.model_dump(mode='json')
    assert payload['visibility'] == 'public'
    assert 'owner_id' in payload and payload['owner_id'] is None
    assert 'owner_epoch' in payload and payload['owner_epoch'] is None
    with pytest.raises(ValidationError, match='lease namespace mismatch'):
        JobLeaseV1.model_validate({**lease.model_dump(), 'visibility': 'private'})
    private = JobLeaseV1.model_validate({**lease.model_dump(), 'visibility': 'private',
        'owner_id': uuid4(), 'owner_epoch': 1})
    assert private.visibility == 'private' and private.owner_id is not None and private.owner_epoch == 1
    # SQL missing-key / JSON-null / string-null semantics are Main's PG checks,
    # not a second Python implementation of the JOIN predicate.


@pytest.mark.parametrize('field,value', (('owner_id', uuid4()), ('owner_epoch', 1)))
def test_public_lease_rejects_non_null_namespace_owner(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match='lease namespace mismatch'):
        JobLeaseV1.model_validate({**_public_lease().model_dump(), field: value})
