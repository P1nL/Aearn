"""Pure partition semantics; live source authority remains the concrete C owner."""
import pytest

from app.services.grounding.autonomous.corpus_usage_partition import document_usages, purpose_facets


def test_mixed_corpus_audits_each_real_grant_without_upgrading_either_purpose():
    main = document_usages(('main_teaching',),('main_teaching',),purpose='assessment_evidence',partitioned=True)
    assessment = document_usages(('assessment_evidence',),('assessment_evidence',),purpose='main_teaching',partitioned=True)
    assert main == ('main_teaching',) and assessment == ('assessment_evidence',)
    coverage = purpose_facets({'tutorial':main,'official':assessment},
                             {'tutorial':{'fundamentals'},'official':{'queries'}})
    assert coverage == {'main_teaching':['fundamentals'],'assessment_evidence':['queries'],'supplementary_explanation':[]}


def test_legacy_single_purpose_and_invalid_usage_partitions_remain_denied():
    with pytest.raises(ValueError):
        document_usages(('main_teaching',),('main_teaching',),purpose='assessment_evidence',partitioned=False)
    for granted,reviewed in (((),('main_teaching',)),(('main_teaching','main_teaching'),('main_teaching',)),
                             (('assessment_evidence',),('main_teaching',)),(('invented',),('invented',))):
        with pytest.raises(ValueError):
            document_usages(granted,reviewed,purpose='main_teaching',partitioned=True)
