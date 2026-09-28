"""Developer-owned Skill manifests, immutable snapshots, and catalog compilation."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agents.harness.capabilities import (
    CapabilityDescriptor,
    EffectDescriptor,
    contains_forbidden_execution_target,
    default_capability_descriptors,
    default_effect_descriptors,
    is_catalog_identifier,
    is_exact_semver,
    is_tutor_contract_identifier,
)


_ALLOWED_RESOURCE_REFS = frozenset({"registry:grounding_sources"})
_SHA256_HEX_LENGTH = 64


class SkillCatalogValidationError(ValueError):
    """The whole catalog is rejected whenever one published bundle is invalid."""


class _FrozenManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SkillContentHash(_FrozenManifestModel):
    file: str = Field(min_length=1, max_length=120)
    sha256: str = Field(min_length=_SHA256_HEX_LENGTH, max_length=_SHA256_HEX_LENGTH)

    @field_validator("file")
    @classmethod
    def _validate_file(cls, value: str) -> str:
        return _bundle_leaf_file(value)

    @field_validator("sha256")
    @classmethod
    def _validate_hash(cls, value: str) -> str:
        normalized = value.lower()
        if len(normalized) != _SHA256_HEX_LENGTH or any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("content hashes must be SHA-256 hex digests")
        return normalized


class SkillManifest(_FrozenManifestModel):
    """Reviewed JSON manifest for one exact-versioned Skill bundle."""

    id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    owner: str = Field(min_length=1, max_length=80)
    kind: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=360)
    instruction_file: str = Field(min_length=1, max_length=120)
    evaluation_suite_file: str = Field(min_length=1, max_length=120)
    content_hashes: tuple[SkillContentHash, ...] = Field(min_length=2, max_length=2)
    resource_refs: tuple[str, ...] = Field(default=(), max_length=8)
    requires_capabilities: tuple[str, ...] = Field(default=(), max_length=8)
    allowed_effect_types: tuple[str, ...] = Field(default=(), max_length=8)
    policy_tags: tuple[str, ...] = Field(default=(), max_length=8)
    input_contract: str = Field(min_length=1, max_length=120)
    output_contract: str = Field(min_length=1, max_length=120)
    deprecated: bool = False
    replacement: str | None = Field(default=None, max_length=240)

    @model_validator(mode="before")
    @classmethod
    def _coerce_hash_mapping(cls, raw: object) -> object:
        if not isinstance(raw, Mapping):
            return raw
        value = dict(raw)
        hashes = value.get("content_hashes")
        if isinstance(hashes, Mapping):
            value["content_hashes"] = [
                {"file": file_name, "sha256": digest}
                for file_name, digest in sorted(hashes.items(), key=lambda item: str(item[0]))
            ]
        return value

    @field_validator("id", "owner", "kind")
    @classmethod
    def _validate_identifier(cls, value: str) -> str:
        if not is_catalog_identifier(value):
            raise ValueError("manifest identifiers must be stable catalog identifiers")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if not is_exact_semver(value):
            raise ValueError("Skill versions must use exact SemVer")
        return value

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, value: str) -> str:
        if contains_forbidden_execution_target(value):
            raise ValueError("Skill summary cannot contain an execution target")
        return " ".join(value.split())

    @field_validator("instruction_file", "evaluation_suite_file")
    @classmethod
    def _validate_bundle_file(cls, value: str) -> str:
        return _bundle_leaf_file(value)

    @field_validator("resource_refs")
    @classmethod
    def _validate_resources(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(values)
        if len(set(normalized)) != len(normalized) or any(
            not value.startswith("registry:") or contains_forbidden_execution_target(value) for value in normalized
        ):
            raise ValueError("resource references must be unique registry references")
        return normalized

    @field_validator("requires_capabilities", "allowed_effect_types", "policy_tags")
    @classmethod
    def _validate_identifier_lists(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(values)
        if len(set(normalized)) != len(normalized) or any(not is_catalog_identifier(value) for value in normalized):
            raise ValueError("manifest identifier lists must be unique stable identifiers")
        return normalized

    @field_validator("input_contract", "output_contract")
    @classmethod
    def _validate_contract(cls, value: str) -> str:
        if not is_tutor_contract_identifier(value):
            raise ValueError("Skill contract versions must be reviewed Tutor contract ids")
        return value

    @field_validator("replacement")
    @classmethod
    def _validate_replacement(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _parse_skill_reference(value)
        return value

    @model_validator(mode="after")
    def _validate_related_fields(self) -> "SkillManifest":
        hashes = tuple(self.content_hashes)
        hash_files = tuple(entry.file for entry in hashes)
        required_files = {self.instruction_file, self.evaluation_suite_file}
        if len(set(hash_files)) != len(hash_files) or set(hash_files) != required_files:
            raise ValueError("content hashes must declare exactly the instruction and evaluation files")
        if self.deprecated is False and self.replacement is not None:
            raise ValueError("only deprecated Skills may declare a replacement")
        return self

    def content_hash_for(self, file_name: str) -> str:
        for entry in self.content_hashes:
            if entry.file == file_name:
                return entry.sha256
        raise KeyError(file_name)


@dataclass(frozen=True)
class CatalogSkillReference:
    skill_id: str
    version: str

    def __post_init__(self) -> None:
        if not is_catalog_identifier(self.skill_id):
            raise ValueError("Skill id must be a stable catalog identifier")
        if not is_exact_semver(self.version):
            raise ValueError("Skill reference requires exact SemVer")

    @property
    def key(self) -> str:
        return f"{self.skill_id}@{self.version}"


@dataclass(frozen=True)
class PublishedSkill:
    manifest: SkillManifest
    instruction: str
    instruction_hash: str
    evaluation_hash: str
    manifest_hash: str

    def __post_init__(self) -> None:
        if not self.instruction.strip():
            raise ValueError("published Skill instructions cannot be empty")
        for value in (self.instruction_hash, self.evaluation_hash, self.manifest_hash):
            if len(value) != _SHA256_HEX_LENGTH or any(character not in "0123456789abcdef" for character in value):
                raise ValueError("published Skill digests must be SHA-256 hex values")

    @property
    def reference(self) -> CatalogSkillReference:
        return CatalogSkillReference(skill_id=self.manifest.id, version=self.manifest.version)


@dataclass(frozen=True)
class SkillCatalogSnapshot:
    """Compiled, ordered data; it contains no executable model-selected function."""

    skills: tuple[PublishedSkill, ...]
    capability_descriptors: tuple[CapabilityDescriptor, ...]
    effect_descriptors: tuple[EffectDescriptor, ...]
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "skills", tuple(self.skills))
        object.__setattr__(self, "capability_descriptors", tuple(self.capability_descriptors))
        object.__setattr__(self, "effect_descriptors", tuple(self.effect_descriptors))
        if not self.skills:
            raise ValueError("Skill catalog cannot be empty")
        skill_keys = tuple(skill.reference.key for skill in self.skills)
        if len(skill_keys) != len(set(skill_keys)):
            raise ValueError("Skill catalog contains duplicate id/version pairs")
        capability_ids = tuple(descriptor.reference for descriptor in self.capability_descriptors)
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("Skill catalog contains duplicate capability id/version pairs")
        effect_types = tuple(descriptor.effect_type for descriptor in self.effect_descriptors)
        if len(effect_types) != len(set(effect_types)):
            raise ValueError("Skill catalog contains duplicate effect types")
        if len(self.digest) != _SHA256_HEX_LENGTH or any(character not in "0123456789abcdef" for character in self.digest):
            raise ValueError("Skill catalog digest must be a SHA-256 hex value")

    def resolve_skill(self, skill_id: str, version: str) -> PublishedSkill | None:
        if not is_exact_semver(version):
            return None
        for skill in self.skills:
            if skill.manifest.id == skill_id and skill.manifest.version == version:
                return skill
        return None

    def capability(self, capability_id: str, version: str | None = None) -> CapabilityDescriptor | None:
        if capability_id == "learning.plan.draft" and version is None:
            version = "1.0.0"
        for descriptor in self.capability_descriptors:
            if descriptor.capability_id == capability_id and (version is None or descriptor.version == version):
                return descriptor
        return None

    def capability_for_skill(self, capability_id: str, reference: CatalogSkillReference) -> CapabilityDescriptor | None:
        version = ("1.1.0" if capability_id == "learning.plan.draft"
                   and reference.key == "tutor.learning-plan-draft@1.1.0" else "1.0.0")
        return self.capability(capability_id, version if capability_id == "learning.plan.draft" else None)

    def effect(self, effect_type: str) -> EffectDescriptor | None:
        for descriptor in self.effect_descriptors:
            if descriptor.effect_type == effect_type:
                return descriptor
        return None


class SkillCatalogCompiler:
    """Compile all reviewed bundles or fail closed without a partial snapshot."""

    def __init__(
        self,
        *,
        capability_descriptors: tuple[CapabilityDescriptor, ...] | None = None,
        effect_descriptors: tuple[EffectDescriptor, ...] | None = None,
        allowed_resource_refs: frozenset[str] = _ALLOWED_RESOURCE_REFS,
    ) -> None:
        self._capability_descriptors = tuple(capability_descriptors or default_capability_descriptors())
        self._effect_descriptors = tuple(effect_descriptors if effect_descriptors is not None else default_effect_descriptors())
        self._allowed_resource_refs = frozenset(allowed_resource_refs)
        _ensure_unique_descriptors(self._capability_descriptors, attribute="reference")
        _ensure_unique_descriptors(self._effect_descriptors, attribute="effect_type")

    def compile(self, source_root: Path) -> SkillCatalogSnapshot:
        source_root = Path(source_root)
        if not source_root.is_dir() or source_root.is_symlink():
            raise SkillCatalogValidationError("Skill source root must be a real directory")
        root = source_root.resolve()

        bundles: list[PublishedSkill] = []
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if child.name == "__init__.py" and child.is_file():
                continue
            if child.name == "__pycache__" and child.is_dir() and not child.is_symlink():
                continue
            if not child.is_dir() or child.is_symlink() or not is_catalog_identifier(child.name):
                raise SkillCatalogValidationError("Skill source root contains an unsafe bundle path")
            version_directories = tuple(sorted(child.iterdir(), key=lambda item: item.name))
            if not version_directories:
                raise SkillCatalogValidationError("Skill id has no published version directory")
            for bundle_directory in version_directories:
                if not bundle_directory.is_dir() or bundle_directory.is_symlink() or not is_exact_semver(bundle_directory.name):
                    raise SkillCatalogValidationError("Skill bundle directory must be an exact SemVer path")
                bundles.append(self._compile_bundle(root=root, bundle_directory=bundle_directory))

        if not bundles:
            raise SkillCatalogValidationError("Skill source root contains no published bundles")
        bundles.sort(key=lambda skill: (skill.manifest.id, skill.manifest.version))
        _ensure_no_duplicate_skill_references(bundles)
        self._validate_replacements(bundles)
        digest = _snapshot_digest(
            skills=tuple(bundles),
            capability_descriptors=self._capability_descriptors,
            effect_descriptors=self._effect_descriptors,
        )
        return SkillCatalogSnapshot(
            skills=tuple(bundles),
            capability_descriptors=self._capability_descriptors,
            effect_descriptors=self._effect_descriptors,
            digest=digest,
        )

    def _compile_bundle(self, *, root: Path, bundle_directory: Path) -> PublishedSkill:
        manifest_path = _bundle_file(root=root, bundle_directory=bundle_directory, file_name="manifest.json")
        try:
            manifest = SkillManifest.model_validate_json(manifest_path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            raise SkillCatalogValidationError(f"invalid Skill manifest in {bundle_directory.name}") from exc
        if manifest.id != bundle_directory.parent.name or manifest.version != bundle_directory.name:
            raise SkillCatalogValidationError("Skill manifest id/version must match its reviewed directory")
        if any(resource_ref not in self._allowed_resource_refs for resource_ref in manifest.resource_refs):
            raise SkillCatalogValidationError("Skill manifest references an untrusted resource")
        if any(self._capability_by_id(capability_id) is None for capability_id in manifest.requires_capabilities):
            raise SkillCatalogValidationError("Skill manifest requires an unknown capability")
        if any(self._effect_by_type(effect_type) is None for effect_type in manifest.allowed_effect_types):
            raise SkillCatalogValidationError("Skill manifest declares an unknown effect type")

        instruction_path = _bundle_file(root=root, bundle_directory=bundle_directory, file_name=manifest.instruction_file)
        evaluation_path = _bundle_file(root=root, bundle_directory=bundle_directory, file_name=manifest.evaluation_suite_file)
        instruction_bytes = _read_nonempty_bytes(instruction_path, label="Skill instruction")
        evaluation_bytes = _read_nonempty_bytes(evaluation_path, label="Skill evaluation suite")
        try:
            instruction = instruction_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SkillCatalogValidationError("Skill instructions must be UTF-8") from exc
        if not instruction.strip():
            raise SkillCatalogValidationError("Skill instructions cannot be blank")
        _validate_evaluation_suite(evaluation_bytes)

        instruction_hash = _sha256(instruction_bytes)
        evaluation_hash = _sha256(evaluation_bytes)
        if instruction_hash != manifest.content_hash_for(manifest.instruction_file):
            raise SkillCatalogValidationError("Skill instruction content hash does not match manifest")
        if evaluation_hash != manifest.content_hash_for(manifest.evaluation_suite_file):
            raise SkillCatalogValidationError("Skill evaluation content hash does not match manifest")
        manifest_hash = _sha256(_canonical_json(manifest.model_dump(mode="json")).encode("utf-8"))
        return PublishedSkill(
            manifest=manifest,
            instruction=instruction,
            instruction_hash=instruction_hash,
            evaluation_hash=evaluation_hash,
            manifest_hash=manifest_hash,
        )

    def _capability_by_id(self, capability_id: str) -> CapabilityDescriptor | None:
        return next(
            (descriptor for descriptor in self._capability_descriptors if descriptor.capability_id == capability_id),
            None,
        )

    def _effect_by_type(self, effect_type: str) -> EffectDescriptor | None:
        return next(
            (descriptor for descriptor in self._effect_descriptors if descriptor.effect_type == effect_type),
            None,
        )

    @staticmethod
    def _validate_replacements(skills: list[PublishedSkill]) -> None:
        published_keys = {skill.reference.key for skill in skills}
        for skill in skills:
            replacement = skill.manifest.replacement
            if replacement is not None and replacement not in published_keys:
                raise SkillCatalogValidationError("deprecated Skill replacement is not published in this catalog")


def published_skill_source_root() -> Path:
    return Path(__file__).resolve().parents[1] / "skills"


def compile_published_skill_catalog(source_root: Path | None = None) -> SkillCatalogSnapshot:
    return SkillCatalogCompiler().compile(source_root or published_skill_source_root())


def _bundle_leaf_file(value: str) -> str:
    candidate = str(value).strip()
    if (
        not candidate
        or candidate in {".", ".."}
        or "/" in candidate
        or "\\" in candidate
        or candidate.startswith(".")
        or ".." in candidate
        or contains_forbidden_execution_target(candidate)
    ):
        raise ValueError("Skill resource files must be safe bundle-relative leaf names")
    return candidate


def _parse_skill_reference(value: str) -> CatalogSkillReference:
    skill_id, separator, version = value.rpartition("@")
    if not separator:
        raise ValueError("Skill replacement must be an exact id@version reference")
    return CatalogSkillReference(skill_id=skill_id, version=version)


def _bundle_file(*, root: Path, bundle_directory: Path, file_name: str) -> Path:
    unresolved_candidate = bundle_directory / _bundle_leaf_file(file_name)
    if unresolved_candidate.is_symlink():
        raise SkillCatalogValidationError("Skill bundle resource is missing or unsafe")
    candidate = unresolved_candidate.resolve()
    try:
        candidate.relative_to(bundle_directory.resolve())
        candidate.relative_to(root)
    except ValueError as exc:
        raise SkillCatalogValidationError("Skill bundle resource escapes the source root") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise SkillCatalogValidationError("Skill bundle resource is missing or unsafe")
    return candidate


def _read_nonempty_bytes(path: Path, *, label: str) -> bytes:
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise SkillCatalogValidationError(f"{label} could not be read") from exc
    if not value.strip():
        raise SkillCatalogValidationError(f"{label} cannot be empty")
    return value


def _validate_evaluation_suite(value: bytes) -> None:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillCatalogValidationError("Skill evaluation suite must be valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping) or not isinstance(decoded.get("cases"), list) or not decoded["cases"]:
        raise SkillCatalogValidationError("Skill evaluation suite must declare at least one case")
    if any(not isinstance(case, Mapping) or not str(case.get("id") or "").strip() for case in decoded["cases"]):
        raise SkillCatalogValidationError("Skill evaluation cases require stable ids")


def _ensure_unique_descriptors(descriptors: tuple[object, ...], *, attribute: str) -> None:
    values = tuple(str(getattr(descriptor, attribute)) for descriptor in descriptors)
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate descriptor {attribute}")


def _ensure_no_duplicate_skill_references(skills: list[PublishedSkill]) -> None:
    references = tuple(skill.reference.key for skill in skills)
    if len(references) != len(set(references)):
        raise SkillCatalogValidationError("duplicate Skill id/version pairs are not allowed")


def _snapshot_digest(
    *,
    skills: tuple[PublishedSkill, ...],
    capability_descriptors: tuple[CapabilityDescriptor, ...],
    effect_descriptors: tuple[EffectDescriptor, ...],
) -> str:
    payload = {
        "skills": [
            {
                "id": skill.manifest.id,
                "version": skill.manifest.version,
                "manifest_hash": skill.manifest_hash,
                "instruction_hash": skill.instruction_hash,
                "evaluation_hash": skill.evaluation_hash,
                "manifest": skill.manifest.model_dump(mode="json"),
            }
            for skill in skills
        ],
        "capabilities": [descriptor.catalog_definition() for descriptor in capability_descriptors],
        "effects": [
            {
                "type": descriptor.effect_type,
                "version": descriptor.version,
                "description": descriptor.description,
                "policy_tags": list(descriptor.policy_tags),
                "implementation_owner": descriptor.implementation_owner,
                "proposal_schema": descriptor.proposal_model.model_json_schema(),
            }
            for descriptor in effect_descriptors
        ],
    }
    return _sha256(_canonical_json(payload).encode("utf-8"))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
