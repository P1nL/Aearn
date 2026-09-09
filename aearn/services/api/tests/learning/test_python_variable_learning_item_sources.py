from __future__ import annotations

from app.services.learning.item_bank.compiler import (
    LearningItemCompiler,
    curated_learning_item_source_root,
)
from app.services.learning.item_bank.contracts import (
    LearningItemKnowledgeCheckContentV1,
    LearningItemModelReviewContentV1,
)
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES


_PYTHON_VARIABLE_SOURCES = {
    "python-variables-rebinding-prediction-v1.json": "66dda8f370aed4c1cb5370ff353c15dceb9252c6276dcf308bd6cec4b35ce206",
    "python-variables-rebinding-remediation-v1.json": "dfc52241bb2524ec544eb681bcabaea39c4d96b4fece0739d5547151bc65f72d",
    "python-variables-rebinding-transfer-v1.json": "2d99fb4bd70864b691df548dd6d803b3b83b99280b1ad042220668d5b44ecaec",
    "python-variables-stale-subtotal-review-v1.json": "bccc8f21952e86a4a1b65754f860e41b8b70e67631c05b62b5577e337afed0f3",
    "python-variables-stale-derived-remediation-v1.json": "6559064923926aac3b253319b0d7ac4e17613599a85f0e7e679eed9d8910af28",
}
_SOURCE_SNAPSHOT_HASH = "e900715b26a7b25339637eb1b83e7dc2ba5fbcabc6843e6a225845f155e40dc5"


def _compiled_sources():  # type: ignore[no-untyped-def]
    root = curated_learning_item_source_root()
    compiler = LearningItemCompiler()
    return {
        name: compiler.compile_file(root, name, require_valid=True)
        for name in _PYTHON_VARIABLE_SOURCES
    }


def test_python_variable_sources_compile_with_stable_immutable_hashes() -> None:
    compiled = _compiled_sources()

    assert {
        name: item.loaded.source.content_hash
        for name, item in compiled.items()
    } == _PYTHON_VARIABLE_SOURCES
    assert all(item.validation.passed for item in compiled.values())
    assert len({item.identity.version.handle for item in compiled.values()}) == len(compiled)


def test_python_variable_knowledge_inventory_has_a_complete_successor_chain() -> None:
    compiled = _compiled_sources()
    sources = {
        item.loaded.source.public.item_key: item.loaded.source
        for item in compiled.values()
        if isinstance(item.loaded.source.public.content, LearningItemKnowledgeCheckContentV1)
    }

    assert set(sources) == {
        "python.variables.rebinding-prediction",
        "python.variables.rebinding-remediation",
        "python.variables.rebinding-transfer",
    }
    original = sources["python.variables.rebinding-prediction"]
    remediation = sources["python.variables.rebinding-remediation"]
    transfer = sources["python.variables.rebinding-transfer"]
    assert original.public.purpose.value == "knowledge_check"
    assert original.public.remediation_item_key == remediation.public.item_key
    assert original.blueprint.remediation_policy is not None
    assert original.blueprint.remediation_policy.successor_item_key == remediation.public.item_key
    assert remediation.public.purpose.value == "remediation"
    assert transfer.public.purpose.value == "transfer_check"
    assert {source.public.difficulty.value for source in sources.values()} == {"D1"}
    assert all(source.blueprint.knowledge_key == "python.variables" for source in sources.values())
    assert all(source.blueprint.required_capabilities == ("python",) for source in sources.values())


def test_python_variable_model_review_has_a_compatible_first_remediation() -> None:
    compiled = _compiled_sources()
    sources = {
        item.loaded.source.public.item_key: item.loaded.source
        for item in compiled.values()
        if isinstance(item.loaded.source.public.content, LearningItemModelReviewContentV1)
    }

    assert set(sources) == {
        "python.variables.stale-subtotal-review",
        "python.variables.stale-derived-remediation",
    }
    original = sources["python.variables.stale-subtotal-review"]
    remediation = sources["python.variables.stale-derived-remediation"]
    assert original.public.purpose.value == "code_review"
    assert original.public.difficulty.value == "D2"
    assert original.public.remediation_item_key == remediation.public.item_key
    assert remediation.public.purpose.value == "remediation"
    assert remediation.public.difficulty.value == "D1"
    assert all(source.blueprint.required_capabilities == ("python",) for source in sources.values())


def test_python_variable_sources_keep_low_risk_review_and_pilot_gates() -> None:
    for item in _compiled_sources().values():
        source = item.loaded.source
        policy = source.blueprint.publication_policy
        assert source.blueprint.language_id == "python"
        assert source.blueprint.knowledge_key == "python.variables"
        assert source.blueprint.required_capabilities == ("python",)
        assert policy.risk_tier.value == "low"
        assert policy.required_review_roles == REQUIRED_REVIEW_ROLES
        assert policy.agent_review_required is True
        assert policy.pilot_required is True
        assert policy.human_approval_required is False
        assert source.blueprint.runtime_profile_id is None
        assert source.blueprint.source_references == source.public.source_references
        reference = source.blueprint.source_references[0]
        assert reference.source_id == "python-tutorial"
        assert reference.source_version == "python-3.14.7"
        assert reference.content_hash == _SOURCE_SNAPSHOT_HASH


_V2_SOURCES = {
    "rebinding-remediation": "865c70e81da10318613d96f8b7ffb22cdc100e01c5a3e36e5eb28fcaed376126",
    "rebinding-transfer": "f3d7bb15a0c41b24d073eb33058b95b510cea27978239817d60a163e77121e6b",
    "stale-subtotal-review": "8d6d7fcf2f3a1e718b9ef7163b65885f18543017558ac1230a75623697496191",
    "stale-derived-remediation": "8d0138fa0a496e1e9047a1e00bd073b61f5a87952a7aca259b8b83fb19685e06",
}
_V1_BYTES = {
    "rebinding-remediation": "f1fb7c567eeff89510f6b2aba8aa13df8860b4e84aa2cb96c1a022a9af99cbc9",
    "rebinding-transfer": "163119864ce6191d7e408348fea11c5258c64892f64cb879afc69a7448d6336c",
    "stale-subtotal-review": "4d9156e60314f0a510f69d6817b895030351cc56c26d77bcd3c5a51f2d292029",
    "stale-derived-remediation": "a7190aa40c95f87725e0c78237b7dcee21e31c190505b350b605ef2b3b83ddaf",
}


def _v2_sources():  # type: ignore[no-untyped-def]
    return {
        name: LearningItemCompiler().compile_file(
            curated_learning_item_source_root(),
            f"python-variables-{name}-v2.json",
            require_valid=True,
        ).loaded.source
        for name in _V2_SOURCES
    }


def test_review_repairs_append_versions_without_rewriting_v1() -> None:
    import hashlib

    compiler = LearningItemCompiler()
    root = curated_learning_item_source_root()
    for name, source in _v2_sources().items():
        previous = compiler.compile_file(root, f"python-variables-{name}-v1.json")
        assert hashlib.sha256((root / previous.loaded.relative_path).read_bytes()).hexdigest() == _V1_BYTES[name]
        assert source.content_hash == _V2_SOURCES[name]
        assert source.public.item_key == previous.loaded.source.public.item_key
        assert source.blueprint.blueprint_key == previous.loaded.source.blueprint.blueprint_key
        assert source.blueprint.version == source.public.version == source.private.version == "v2"
        assert source.content_hash != previous.loaded.source.content_hash
        assert source.blueprint.publication_policy == previous.loaded.source.blueprint.publication_policy
        assert source.blueprint.required_capabilities == ("python",)
        assert source.blueprint.runtime_profile_id is None
        # Rubric/scoring rules are not relaxed to conceal the reported defects.
        assert source.private.content == previous.loaded.source.private.content


def test_v2_knowledge_repairs_supply_trace_and_explicit_response_format() -> None:
    sources = _v2_sources()
    remediation = sources["rebinding-remediation"]
    transfer = sources["rebinding-transfer"]
    assert isinstance(remediation.public.content, LearningItemKnowledgeCheckContentV1)
    assert isinstance(transfer.public.content, LearningItemKnowledgeCheckContentV1)
    assert "| Name | Value after these two lines |" in remediation.public.content.prompt_markdown
    assert "update only its row" in remediation.public.content.prompt_markdown
    assert len(remediation.public.hints) == 2
    assert "Submit only the exact printed integer as plain decimal digits" in transfer.public.content.prompt_markdown
    assert "no quotes, backticks, spaces, decimal point, or explanatory words" in transfer.public.content.prompt_markdown
    original = _compiled_sources()["python-variables-rebinding-prediction-v1.json"].loaded.source
    assert original.public.remediation_item_key == remediation.public.item_key
    assert original.public.difficulty == remediation.public.difficulty == transfer.public.difficulty
    assert remediation.public.purpose.value == "remediation"
    assert transfer.public.purpose.value == "transfer_check"
    assert len({item.public.content.prompt_markdown for item in (original, remediation, transfer)}) == 3


def test_v2_model_reviews_align_public_location_and_remediation_difficulty() -> None:
    sources = _v2_sources()
    for name in ("stale-subtotal-review", "stale-derived-remediation"):
        source = sources[name]
        content = source.public.content
        assert isinstance(content, LearningItemModelReviewContentV1)
        assert f"select line {content.artifact.line_count} alone" in content.prompt.learner_instruction
        assert "not as additional finding locations" in content.prompt.learner_instruction
        assert source.blueprint.difficulty_profile.computed_base == source.public.difficulty
        assert source.public.difficulty.value == "D2"
        assert len(source.public.hints) == 2
    original = sources["stale-subtotal-review"]
    remediation = sources["stale-derived-remediation"]
    assert original.public.remediation_item_key == remediation.public.item_key
    assert remediation.public.content.artifact.line_count < original.public.content.artifact.line_count
