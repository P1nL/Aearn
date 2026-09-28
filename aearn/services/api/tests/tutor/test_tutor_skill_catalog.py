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
        "tutor.learning-plan-draft@1.0.2",
        "tutor.learning-plan-draft@1.0.3",
        "tutor.learning-plan-draft@1.1.0",
        "tutor.lesson-teaching@1.0.0",
        "tutor.lesson-teaching@1.1.0",
        "tutor.lesson-teaching@1.2.0",
        "tutor.lesson-teaching@1.2.1",
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


def test_lesson_teaching_history_is_immutable_and_v121_publishes_mainline_recovery() -> None:
    catalog = compile_published_skill_catalog()
    legacy = catalog.resolve_skill("tutor.lesson-teaching", "1.0.0")
    v11 = catalog.resolve_skill("tutor.lesson-teaching", "1.1.0")
    v12 = catalog.resolve_skill("tutor.lesson-teaching", "1.2.0")
    current = catalog.resolve_skill("tutor.lesson-teaching", "1.2.1")

    assert legacy is not None and v11 is not None and v12 is not None and current is not None
    assert legacy.manifest.content_hash_for("instructions.md") == "528b3537a6cc0c38f95260a29bcabcce2fcda7ebbd990c589365e53dcc1e9f80"
    assert legacy.manifest.content_hash_for("evals.json") == "48d919600d7c5e10858692804b89880075fa90e163b3cf509382eb6dc32e6ada"
    assert legacy.manifest.output_contract == "tutor.teaching-step-decision.v1"
    assert v11.manifest.output_contract == "tutor.teaching-step-decision.v2"
    assert v11.manifest.content_hash_for("instructions.md") == "93a6ddb6c8ab7b925d0fcf9a44ec1251c233b4c2a64fd4f752684b0dafbc409d"
    assert v11.manifest.content_hash_for("evals.json") == "8b8de505de9c39f4b66ba5968f637ca5f6ed22b0900c7ab40150747ea1a35b79"
    assert v12.manifest.content_hash_for("instructions.md") == "30e45196fc90916f19baad0beb67fa548a4766cd7e8241eb455817cb61a66a5d"
    assert v12.manifest.content_hash_for("evals.json") == "7f0b5613cb0ba34d8274907fa3464c61da4dcd176ee9c0362c5ae19591636862"
    assert current.manifest.input_contract == "tutor.teaching-session-input.v2"
    assert current.manifest.output_contract == "tutor.teaching-step-decision.v3"
    assert current.manifest.content_hash_for("instructions.md") == "d6af28de9f31657508fdd72c19142e13cdfbdbab38f6bec30e9564d121a5f7e9"
    assert current.manifest.content_hash_for("evals.json") == "5b65408ad7642508ba4c89b1a33f29fc4e950b8cf2356d91cb9588d1fa623171"
    assert "recent_teaching_units" in current.instruction
    assert "artifact_candidates" in current.instruction
    assert "composer / text_answer / null" in current.instruction
    assert "2..4 unique teaching moves" in current.instruction
    assert "answer_and_refocus" in current.instruction
    assert "clarify_direction" in current.instruction
    assert "confirmed_switch" in current.instruction
    assert "do not create a second branch state machine" in current.instruction
    eval_path = Path(__file__).resolve().parents[2] / "app" / "agents" / "skills" / "tutor.lesson-teaching" / "1.2.1" / "evals.json"
    eval_ids = {case["id"] for case in json.loads(eval_path.read_bytes())["cases"]}
    assert {
        "sql-to-css-temporary-digression",
        "python-variables-to-network-concept",
        "ambiguous-new-topic-asks-one-question",
        "related-extension-stays-on-focus",
        "explicit-switch-cannot-invent-authority",
        "blocking-artifact-keeps-server-branch-authority",
    }.issubset(eval_ids)


def test_learning_plan_skill_and_schema_publish_exact_nested_json_contract() -> None:
    catalog = compile_published_skill_catalog()
    legacy = catalog.resolve_skill("tutor.learning-plan-draft", "1.0.1")
    v102 = catalog.resolve_skill("tutor.learning-plan-draft", "1.0.2")
    skill = catalog.resolve_skill("tutor.learning-plan-draft", "1.0.3")
    assert legacy is not None and v102 is not None and skill is not None
    assert legacy.manifest.content_hash_for("instructions.md") == "ae0df92467993f653f582c91eb8279267cdc5b6f2368f94b7619b6cac274070e"
    assert legacy.manifest.content_hash_for("evals.json") == "2c36e54ff39d63a66ecf9d17721d0568aed98ccb0f97072d1c3efe66b0d0308c"
    assert v102.manifest.content_hash_for("instructions.md") == "0c15970382c2f43e83f8bdb1bf739c523feee1ca65df4b0c6bde9802cf833d7a"
    assert v102.manifest.content_hash_for("evals.json") == "5f27b5b38eb8f70e2322e85cc8af93c14b6ee0fb71bf8ee542db540271c12d27"
    assert skill.manifest.content_hash_for("instructions.md") == "bed76a0844b626ca5d29e2b82d2274f145d0b450b9b19921fa6b9535eeacf379"
    assert skill.manifest.content_hash_for("evals.json") == "fa9d79081be1c1e128f1bd24c81865bf0017a6010e0ca4d732f2d88a01ec1525"
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
    assert "planning-intent-hint-v2" in skill.instruction
    assert "Semantic matches always require learner confirmation" in skill.instruction
    assert "Never use a full course catalog as ambiguity fallback" in skill.instruction
    assert "finish the current turn with `turn_completed`" in skill.instruction
    assert "never use `continuation_kind=approval`" in skill.instruction
    assert "continue_mainline" in skill.instruction
    assert "answer_and_refocus" in skill.instruction
    assert "clarify_direction" in skill.instruction
    assert "confirmed_switch" in skill.instruction
    assert "never by a keyword list" in skill.instruction

    eval_path = Path(__file__).resolve().parents[2] / "app" / "agents" / "skills" / "tutor.learning-plan-draft" / "1.0.3" / "evals.json"
    eval_ids = {case["id"] for case in json.loads(eval_path.read_bytes())["cases"]}
    assert {
        "non-programming-digression-needs-direction",
        "cross-programming-topic-answer-and-refocus",
        "ambiguous-theme-material",
        "related-theme-extension-continues",
        "explicit-goal-switch-stops-old-path",
        "temporary-question-returns-to-mainline",
        "langchain-python-confirmation",
    }.issubset(eval_ids)

    schema = CapabilitySchemaExporter.export(LEARNING_PLAN_DRAFT_DESCRIPTOR)["inputSchema"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert "goal_text" in properties["profile_json"]["description"]
    assert "nodes" in properties["module_1"]["description"]


def test_published_skill_manifest_hashes_match_raw_bytes_and_new_versions_are_lf() -> None:
    skill_root = Path(__file__).resolve().parents[2] / "app" / "agents" / "skills"
    manifests = sorted(skill_root.glob("*/*/manifest.json"))
    assert manifests
    mismatches: list[str] = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_bytes())
        content_hashes = manifest.get("content_hashes")
        assert isinstance(content_hashes, dict)
        for resource_name, expected in content_hashes.items():
            resource_path = manifest_path.parent / str(resource_name)
            actual = hashlib.sha256(resource_path.read_bytes()).hexdigest()
            if actual != expected:
                mismatches.append(str(resource_path.relative_to(skill_root)))
    assert mismatches == []

    current_bundles = (
        skill_root / "tutor.learning-plan-draft" / "1.0.3",
        skill_root / "tutor.lesson-teaching" / "1.2.1",
    )
    for current in current_bundles:
        for name in ("instructions.md", "evals.json", "manifest.json"):
            raw = (current / name).read_bytes()
            assert b"\r\n" not in raw
            assert raw.endswith(b"\n")


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
