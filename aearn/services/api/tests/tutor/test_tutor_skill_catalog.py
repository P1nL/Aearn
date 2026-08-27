from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from app.agents.harness.capabilities import (
    CapabilitySchemaExporter,
    GROUNDING_RETRIEVE_DESCRIPTOR,
    LEARNING_PLAN_DRAFT_DESCRIPTOR,
)
from app.agents.harness.skill_catalog import (
    SkillCatalogCompiler,
    SkillCatalogSnapshot,
    SkillCatalogValidationError,
    compile_published_skill_catalog,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_bundle(
    root: Path,
    *,
    skill_id: str = "tutor.example",
    version: str = "1.0.0",
    mutate: Callable[[dict[str, object]], None] | None = None,
) -> Path:
    bundle = root / skill_id / version
    bundle.mkdir(parents=True)
    instructions = "Use only approved, bounded evidence.\n"
    evals = json.dumps({"cases": [{"id": "case-1", "expected": "bounded"}]}, sort_keys=True) + "\n"
    (bundle / "instructions.md").write_bytes(instructions.encode("utf-8"))
    (bundle / "evals.json").write_bytes(evals.encode("utf-8"))
    manifest: dict[str, object] = {
        "id": skill_id,
        "version": version,
        "owner": "aearn-core",
        "kind": "tutoring",
        "summary": "Use an approved bounded fact.",
        "instruction_file": "instructions.md",
        "evaluation_suite_file": "evals.json",
        "content_hashes": {
            "instructions.md": _sha256(instructions),
            "evals.json": _sha256(evals),
        },
        "resource_refs": ["registry:grounding_sources"],
        "requires_capabilities": ["grounding.retrieve"],
        "allowed_effect_types": [],
        "policy_tags": ["registry-grounding"],
        "input_contract": "tutor.skill-input.v1",
        "output_contract": "tutor.skill-decision.v1",
        "deprecated": False,
    }
    if mutate is not None:
        mutate(manifest)
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return bundle


def test_published_catalog_is_exact_versioned_immutable_and_deterministic() -> None:
    first = compile_published_skill_catalog()
    second = compile_published_skill_catalog()

    assert first == second
    assert first.digest == second.digest
    assert tuple(skill.reference.key for skill in first.skills) == (
        "tutor.learner-state@1.0.0",
        "tutor.learning-plan-draft@1.0.0",
        "tutor.learning-plan-draft@1.0.1",
        "tutor.lesson-teaching@1.0.0",
        "tutor.lesson-teaching@1.1.0",
        "tutor.registry-grounding@1.0.0",
        "tutor.runner-execution@1.0.0",
    )
    assert tuple(descriptor.effect_type for descriptor in first.effect_descriptors) == (
        "runner.execute",
        "tutor.plan.activate",
        "tutor.plan.rollback",
        "tutor.memory.record",
        "tutor.activity.record",
    )
    assert first.resolve_skill("tutor.registry-grounding", "1.0.0") is not None
    assert first.resolve_skill("tutor.registry-grounding", "current") is None
    assert isinstance(first.skills, tuple)
    with pytest.raises((AttributeError, TypeError)):
        first.skills += ()  # type: ignore[misc]


def test_lesson_teaching_v1_is_immutable_and_v11_publishes_the_v2_contract() -> None:
    catalog = compile_published_skill_catalog()
    legacy = catalog.resolve_skill("tutor.lesson-teaching", "1.0.0")
    current = catalog.resolve_skill("tutor.lesson-teaching", "1.1.0")

    assert legacy is not None and current is not None
    assert legacy.manifest.content_hash_for("instructions.md") == "528b3537a6cc0c38f95260a29bcabcce2fcda7ebbd990c589365e53dcc1e9f80"
    assert legacy.manifest.content_hash_for("evals.json") == "48d919600d7c5e10858692804b89880075fa90e163b3cf509382eb6dc32e6ada"
    assert legacy.manifest.output_contract == "tutor.teaching-step-decision.v1"
    assert current.manifest.output_contract == "tutor.teaching-step-decision.v2"
    assert current.manifest.content_hash_for("instructions.md") == "93a6ddb6c8ab7b925d0fcf9a44ec1251c233b4c2a64fd4f752684b0dafbc409d"
    assert current.manifest.content_hash_for("evals.json") == "8b8de505de9c39f4b66ba5968f637ca5f6ed22b0900c7ab40150747ea1a35b79"
    assert "recent_teaching_units" in current.instruction
    assert "learner_response_mode=composer" in current.instruction
    assert "2..4 unique `teaching_moves`" in current.instruction


def test_learning_plan_skill_and_schema_publish_exact_nested_json_contract() -> None:
    catalog = compile_published_skill_catalog()
    skill = catalog.resolve_skill("tutor.learning-plan-draft", "1.0.1")
    assert skill is not None
    for required in (
        "goal_text",
        "target_level",
        "teaching_preferences",
        "pace_summary",
        "module_key",
        "nodes",
        "prerequisite_keys",
        "required_capabilities",
    ):
        assert required in skill.instruction
    assert "Do not use aliases such as `goal`" in skill.instruction
    assert "finish the current turn with `turn_completed`" in skill.instruction
    assert "never use `continuation_kind=approval`" in skill.instruction

    schema = CapabilitySchemaExporter.export(LEARNING_PLAN_DRAFT_DESCRIPTOR)["inputSchema"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert "goal_text" in properties["profile_json"]["description"]
    assert "nodes" in properties["module_1"]["description"]


def test_catalog_exports_mcp_compatible_grounding_schema() -> None:
    schema = CapabilitySchemaExporter.export(GROUNDING_RETRIEVE_DESCRIPTOR)

    assert schema["name"] == "grounding.retrieve"
    assert "inputSchema" in schema
    input_schema = schema["inputSchema"]
    assert isinstance(input_schema, dict)
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["properties"]) == {"language_id_or_alias", "query_text", "topic_tags", "top_k"}


def test_catalog_ignores_python_cache_directories_without_treating_them_as_bundles(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    (tmp_path / "__pycache__").mkdir()

    catalog = SkillCatalogCompiler().compile(tmp_path)

    assert tuple(skill.reference.key for skill in catalog.skills) == ("tutor.example@1.0.0",)


def test_catalog_rejects_symlinked_roots_and_resources(tmp_path: Path) -> None:
    target_root = tmp_path / "target-root"
    _write_bundle(target_root)
    root_link = tmp_path / "root-link"
    try:
        root_link.symlink_to(target_root, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not available in this test environment")

    with pytest.raises(SkillCatalogValidationError):
        SkillCatalogCompiler().compile(root_link)

    resource_root = tmp_path / "resource-root"
    bundle = _write_bundle(resource_root)
    instruction_path = bundle / "instructions.md"
    source_path = bundle / "instruction-source.md"
    source_path.write_bytes(instruction_path.read_bytes())
    instruction_path.unlink()
    instruction_path.symlink_to(source_path)

    with pytest.raises(SkillCatalogValidationError):
        SkillCatalogCompiler().compile(resource_root)


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("unversioned", lambda manifest: manifest.__setitem__("version", "current")),
        ("unknown-capability", lambda manifest: manifest.__setitem__("requires_capabilities", ["unknown.capability"])),
        ("unknown-effect", lambda manifest: manifest.__setitem__("allowed_effect_types", ["note.write"])),
        ("untrusted-resource", lambda manifest: manifest.__setitem__("resource_refs", ["registry:open_web"])),
        ("path-traversal", lambda manifest: manifest.__setitem__("instruction_file", "../instructions.md")),
        ("unsafe-summary", lambda manifest: manifest.__setitem__("summary", "Fetch https://untrusted.example/document")),
    ],
)
def test_catalog_rejects_invalid_manifest_contracts(
    tmp_path: Path,
    label: str,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    _write_bundle(tmp_path, mutate=mutate)

    with pytest.raises(SkillCatalogValidationError):
        SkillCatalogCompiler().compile(tmp_path)

    del label


def test_catalog_rejects_missing_resources_hash_mismatch_and_duplicate_snapshot_entries(tmp_path: Path) -> None:
    bundle = _write_bundle(tmp_path)
    (bundle / "evals.json").unlink()

    with pytest.raises(SkillCatalogValidationError):
        SkillCatalogCompiler().compile(tmp_path)

    complete_root = tmp_path / "complete"
    _write_bundle(complete_root)
    manifest_path = complete_root / "tutor.example" / "1.0.0" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["content_hashes"]["instructions.md"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SkillCatalogValidationError):
        SkillCatalogCompiler().compile(complete_root)

    catalog = compile_published_skill_catalog()
    with pytest.raises(ValueError):
        SkillCatalogSnapshot(
            skills=(catalog.skills[0], catalog.skills[0]),
            capability_descriptors=catalog.capability_descriptors,
            effect_descriptors=catalog.effect_descriptors,
            digest=catalog.digest,
        )
