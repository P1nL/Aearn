"""Finite teaching protocol tests, never live C admission or OS acceptance."""
from dataclasses import replace
import hashlib
from html import escape
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.contracts import SubjectScope
from app.services.grounding.autonomous.public_python_teaching_profile import (
    AUTHORS, GROUPS, LICENSE_URL, URL, TeachingReviewDenied, analyze_teaching, teaching_request,
)
from app.services.grounding.autonomous.source_review_repository import CompleteCapture, ReviewDenied, SourceReviewRepository


def capture(*, prefix="", wrapper="", duplicate=False, license_url=LICENSE_URL):
    groups = [escape(p) for p in GROUPS.values()]
    if prefix:
        groups[0] = prefix + "\n" + groups[0]
    if duplicate:
        groups.append(groups[0])
    content = "\n\n".join(groups) + "\n\n# There are no declarations, only assignments.\n"
    pre = '<pre lang="python">'+content+'</pre>'
    if wrapper:
        pre = wrapper + pre + ('</blockquote>' if wrapper.startswith('<blockquote') else '</div>')
    body = ('<html><body>'+pre+'<footer><a rel="license" href="'+license_url+'">CC BY-SA 3.0</a><p>'
            +', '.join(AUTHORS)+'</p></footer></body></html>').encode()
    digest = hashlib.sha256(body).hexdigest()
    return CompleteCapture(uuid4(),'registered',body,digest,digest,
        SubjectScope(subject_id='route.python',subject_version='1.0',facets=('fundamentals',)),
        'source.teaching.test',URL,(URL,),'tutorial','beginner','cc-by-sa-3.0')


def test_only_complete_correct_groups_are_approved_with_unsupported_rest_excluded():
    c = capture()
    spans = analyze_teaching(c)
    assert tuple(s.unit for s in spans) == tuple(GROUPS)
    assert all(hashlib.sha256(c.body[s.start_byte:s.end_byte]).hexdigest()==s.sha256 for s in spans)
    assert all(b'no declarations' not in c.body[s.start_byte:s.end_byte] for s in spans)
    request, expected = teaching_request()
    assert request.runtime_id == 'python-stdout-v1'
    assert expected['cases'][0]['stdout'].endswith('4 5 6\n5 4 6\n')


def test_quote_hidden_conflicting_group_duplicate_and_missing_license_deny():
    for c in (capture(prefix='# This example is incorrect:'),capture(wrapper='<blockquote>'),
              capture(wrapper='<div style="display:none">'),capture(duplicate=True),
              capture(license_url='https://example.invalid/not-a-license')):
        with pytest.raises(TeachingReviewDenied):
            analyze_teaching(c)
    with pytest.raises(TeachingReviewDenied):
        analyze_teaching(replace(capture(),origin='official'))


def test_generic_or_foreign_connection_teaching_port_cannot_upgrade_usage():
    with pytest.raises(ReviewDenied,match='TEACHING_PORT_DENIED'):
        SourceReviewRepository(object(),verifier=SimpleNamespace(),teaching_verifier=SimpleNamespace())
    from app.services.grounding.autonomous.public_python_teaching_review import PublicPythonTeachingVerifier

    foreign = object.__new__(PublicPythonTeachingVerifier)
    foreign.conn = object()
    with pytest.raises(ReviewDenied,match='TEACHING_PORT_DENIED'):
        SourceReviewRepository(object(),verifier=foreign,teaching_verifier=foreign)
