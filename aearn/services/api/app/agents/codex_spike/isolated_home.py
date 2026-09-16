"""Build a temporary, non-global Codex home for the protocol spike."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.services.llm.llm_urls import normalize_deepseek_base_url

MODEL_ID = "deepseek-flash"
PROVIDER_ID = "aearn_deepseek"
WIRE_API = "responses"
ENV_KEY = "DEEPSEEK_API_KEY"


@dataclass(frozen=True, slots=True)
class IsolatedCodexHome:
    root: Path
    codex_home: Path
    workspace: Path
    config_path: Path
    config_fingerprint: str
    model: str = MODEL_ID
    model_provider: str = PROVIDER_ID
    wire_api: str = WIRE_API
    env_key: str = ENV_KEY
    requires_openai_auth: bool = False


def build_isolated_codex_home(root: Path, *, base_url: str, env_key: str = ENV_KEY) -> IsolatedCodexHome:
    """Create the minimal strict config without copying global Codex state."""
    resolved_root = root.expanduser().resolve()
    global_home = (Path.home() / ".codex").resolve()
    if resolved_root == global_home or global_home in resolved_root.parents:
        raise ValueError("isolated Codex Home must not be inside the user global Codex Home")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if any(character in base_url for character in ("\r", "\n", "\"", "\\")):
        raise ValueError("base_url contains characters that are unsafe for strict TOML")
    normalized_base_url = normalize_deepseek_base_url(base_url)
    if not env_key or not env_key.replace("_", "").isalnum():
        raise ValueError("env_key must be a non-empty environment variable name")

    codex_home = resolved_root / "codex-home"
    workspace = resolved_root / "workspace"
    codex_home.mkdir(parents=True, exist_ok=False)
    workspace.mkdir(parents=True, exist_ok=False)
    config_path = codex_home / "config.toml"
    config_text = (
        f'model = "{MODEL_ID}"\n'
        f'model_provider = "{PROVIDER_ID}"\n'
        'approval_policy = "never"\n'
        'sandbox_mode = "read-only"\n\n'
        f'[model_providers.{PROVIDER_ID}]\n'
        'name = "Aearn DeepSeek"\n'
        f'base_url = "{normalized_base_url}"\n'
        f'env_key = "{env_key}"\n'
        f'wire_api = "{WIRE_API}"\n'
        'requires_openai_auth = false\n'
        'request_max_retries = 0\n'
        'stream_max_retries = 0\n'
        'stream_idle_timeout_ms = 10000\n\n'
        '[analytics]\n'
        'enabled = false\n'
    )
    config_path.write_text(config_text, encoding="utf-8", newline="\n")
    fingerprint = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
    return IsolatedCodexHome(root=resolved_root, codex_home=codex_home, workspace=workspace, config_path=config_path, config_fingerprint=fingerprint, env_key=env_key)
