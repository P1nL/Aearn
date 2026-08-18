"""Strict, isolated configuration for the Codex runtime sidecar."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import DEEPSEEK_V4_FLASH_MODEL, Settings
from app.services.llm.llm_urls import normalize_deepseek_base_url

CODEX_MODEL_PROVIDER = "aearn_deepseek"
CODEX_WIRE_API = "responses"
CODEX_ENV_KEY = "DEEPSEEK_API_KEY"
_VERSION_PATTERN = re.compile(r"^codex-cli\s+(?P<version>\S+)$")


@dataclass(frozen=True, slots=True)
class CodexExecutableProbe:
    status: str
    executable_path: str | None
    version: str | None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class CodexRuntimeConfig:
    enabled: bool
    executable_path: Path | None
    home_root: Path
    model: str
    model_provider: str
    base_url: str | None
    env_key: str
    allowed_versions: frozenset[str]
    startup_timeout_s: float
    request_timeout_s: float
    turn_timeout_s: float
    shutdown_timeout_s: float
    notification_queue_size: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "CodexRuntimeConfig":
        configured_path = settings.codex_runtime_binary_path
        executable = resolve_codex_executable(configured_path)
        home = settings.codex_runtime_home_path
        allowed = frozenset(item.strip() for item in settings.codex_runtime_allowed_versions.split(",") if item.strip())
        return cls(
            enabled=settings.codex_runtime_enabled,
            executable_path=executable,
            home_root=home,
            model=str(settings.deepseek_model or DEEPSEEK_V4_FLASH_MODEL),
            model_provider=CODEX_MODEL_PROVIDER,
            base_url=settings.deepseek_base_url,
            env_key=CODEX_ENV_KEY,
            allowed_versions=allowed,
            startup_timeout_s=settings.codex_runtime_startup_timeout_seconds,
            request_timeout_s=settings.codex_runtime_request_timeout_seconds,
            turn_timeout_s=settings.codex_runtime_turn_timeout_seconds,
            shutdown_timeout_s=settings.codex_runtime_shutdown_timeout_seconds,
            notification_queue_size=settings.codex_runtime_notification_queue_size,
        )


@dataclass(frozen=True, slots=True)
class CodexRuntimeHome:
    root: Path
    codex_home: Path
    workspace: Path
    config_path: Path
    config_fingerprint: str


def resolve_codex_executable(explicit: str | Path | None = None) -> Path | None:
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        return candidate.resolve() if candidate.is_file() else None
    names = ("codex.exe", "codex.cmd", "codex") if os.name == "nt" else ("codex",)
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).resolve()
    return None


def probe_codex_executable(explicit: str | Path | None = None) -> CodexExecutableProbe:
    executable = resolve_codex_executable(explicit)
    if executable is None:
        return CodexExecutableProbe("missing", None, None, "codex_missing")
    try:
        completed = subprocess.run([str(executable), "--version"], capture_output=True, check=False, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return CodexExecutableProbe("error", str(executable), None, "version_probe_failed")
    match = _VERSION_PATTERN.fullmatch(completed.stdout.strip())
    if completed.returncode != 0 or match is None:
        return CodexExecutableProbe("incompatible", str(executable), None, "version_format_incompatible")
    return CodexExecutableProbe("ready", str(executable), match.group("version"))


def ensure_codex_runtime_home(config: CodexRuntimeConfig, *, allow_existing: bool = True) -> CodexRuntimeHome:
    root = config.home_root.expanduser().resolve()
    global_home = (Path.home() / ".codex").resolve()
    if root == global_home or global_home in root.parents:
        raise ValueError("Codex runtime home must not be inside the user global Codex Home")
    if config.model != DEEPSEEK_V4_FLASH_MODEL:
        raise ValueError("Codex runtime requires exact deepseek-v4-flash")
    if config.model_provider != CODEX_MODEL_PROVIDER:
        raise ValueError("Codex runtime provider is invalid")
    if not config.base_url:
        raise ValueError("Codex runtime DeepSeek base URL is required")
    if any(character in config.base_url for character in ("\r", "\n", '"', "\\")):
        raise ValueError("Codex runtime base URL is unsafe for strict TOML")
    codex_home = root / "codex-home"
    workspace = root / "workspace"
    if not allow_existing and root.exists():
        raise FileExistsError(root)
    codex_home.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    normalized = normalize_deepseek_base_url(config.base_url)
    text = (
        f'model = "{config.model}"\n'
        f'model_provider = "{config.model_provider}"\n'
        'approval_policy = "never"\n'
        'sandbox_mode = "read-only"\n\n'
        f'[model_providers.{config.model_provider}]\n'
        'name = "Aearn DeepSeek"\n'
        f'base_url = "{normalized}"\n'
        f'env_key = "{config.env_key}"\n'
        f'wire_api = "{CODEX_WIRE_API}"\n'
        'requires_openai_auth = false\n'
        'request_max_retries = 0\n'
        'stream_max_retries = 0\n'
        'stream_idle_timeout_ms = 300000\n\n'
        '[analytics]\n'
        'enabled = false\n'
    )
    path = codex_home / "config.toml"
    temporary = codex_home / "config.toml.tmp"
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)
    return CodexRuntimeHome(root, codex_home, workspace, path, hashlib.sha256(text.encode()).hexdigest())
