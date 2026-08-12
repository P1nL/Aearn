"""Encrypted, local-only capture for bounded provider response diagnostics."""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from app.core.config import Settings


_PROVIDER_DEBUG_FORMAT_VERSION = "aearn_provider_debug_v1"
_PROVIDER_DEBUG_SUFFIX = ".aearn-provider-debug"


@dataclass(frozen=True)
class ProviderDiagnosticMetadata:
    run_id: str
    attempt_index: int
    provider_type: str
    protocol: str
    model: str
    diagnostic_code: str
    contract_hash: str

    def as_dict(self, *, artifact_id: str, created_at: datetime) -> dict[str, object]:
        return {
            "format_version": _PROVIDER_DEBUG_FORMAT_VERSION,
            "artifact_id": _safe_metadata_token(artifact_id),
            "created_at": created_at.astimezone(UTC).isoformat(),
            "run_id": _safe_metadata_token(self.run_id),
            "attempt_index": self.attempt_index,
            "provider_type": _safe_metadata_token(self.provider_type),
            "protocol": _safe_metadata_token(self.protocol),
            "model": _safe_metadata_token(self.model),
            "diagnostic_code": _safe_metadata_token(self.diagnostic_code),
            "contract_hash": _safe_metadata_token(self.contract_hash),
        }


@dataclass(frozen=True)
class ProviderDiagnosticArtifact:
    artifact_id: str
    path: Path
    captured_bytes: int
    truncated: bool


class ProviderBodyCapture:
    """Bounded in-memory body that is encrypted only after a rejected attempt."""

    def __init__(self, *, store: "ProviderDiagnosticStore", max_bytes: int) -> None:
        self._store = store
        self._max_bytes = max_bytes
        self._buffer = bytearray()
        self._truncated = False
        self._closed = False

    @property
    def has_content(self) -> bool:
        return bool(self._buffer)

    @property
    def remaining_capacity(self) -> int:
        if self._closed:
            return 0
        return max(self._max_bytes - len(self._buffer), 0)

    def append(self, value: bytes) -> None:
        if self._closed or not value:
            return
        remaining = self._max_bytes - len(self._buffer)
        if remaining <= 0:
            self._truncated = True
            return
        self._buffer.extend(value[:remaining])
        if len(value) > remaining:
            self._truncated = True

    def append_mapping(self, value: object) -> None:
        if self._buffer or self._closed:
            return
        try:
            serialized = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return
        self.append(serialized)

    def commit(
        self,
        metadata: ProviderDiagnosticMetadata,
    ) -> ProviderDiagnosticArtifact | None:
        if self._closed or not self._buffer:
            self.discard()
            return None
        try:
            return self._store.write(
                plaintext=bytes(self._buffer),
                metadata=metadata,
                truncated=self._truncated,
            )
        finally:
            self.discard()

    def discard(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._buffer.clear()
        self._closed = True


class ProviderDiagnosticStore:
    """AES-GCM artifact store with random nonces, bounded retention, and no API route."""

    def __init__(
        self,
        *,
        directory: Path,
        key: bytes,
        max_bytes: int,
        retention_hours: int,
    ) -> None:
        if len(key) != 32:
            raise ValueError("provider diagnostic key must decode to exactly 32 bytes")
        self._directory = directory.expanduser().resolve()
        self._aesgcm = AESGCM(key)
        self._max_bytes = max_bytes
        self._retention = timedelta(hours=retention_hours)
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            self._directory.chmod(0o700)
        self._prune_expired(now=datetime.now(UTC))

    @classmethod
    def from_settings(cls, settings: "Settings") -> "ProviderDiagnosticStore | None":
        if settings.tutor_provider_debug_capture_mode == "off":
            return None
        secret = settings.tutor_provider_debug_capture_key
        if secret is None:
            raise ValueError("provider diagnostic capture requires an encryption key")
        try:
            key = base64.b64decode(secret.get_secret_value(), validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("provider diagnostic key must be valid base64") from exc
        return cls(
            directory=settings.tutor_provider_debug_capture_path,
            key=key,
            max_bytes=settings.tutor_provider_debug_capture_max_bytes,
            retention_hours=settings.tutor_provider_debug_capture_retention_hours,
        )

    def begin_capture(self) -> ProviderBodyCapture:
        return ProviderBodyCapture(store=self, max_bytes=self._max_bytes)

    def write(
        self,
        *,
        plaintext: bytes,
        metadata: ProviderDiagnosticMetadata,
        truncated: bool,
    ) -> ProviderDiagnosticArtifact:
        now = datetime.now(UTC)
        self._prune_expired(now=now)
        artifact_id = secrets.token_hex(16)
        safe_metadata = metadata.as_dict(artifact_id=artifact_id, created_at=now)
        safe_metadata["truncated"] = truncated
        safe_metadata["captured_bytes"] = len(plaintext)
        associated_data = _canonical_json_bytes(safe_metadata)
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, associated_data)
        envelope = {
            "metadata": safe_metadata,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        filename = (
            f"{int(now.timestamp() * 1000)}-"
            f"{_safe_filename_token(metadata.run_id)}-"
            f"{metadata.attempt_index}-{artifact_id}{_PROVIDER_DEBUG_SUFFIX}"
        )
        target = self._directory / filename
        temporary = self._directory / f".{filename}.{secrets.token_hex(8)}.tmp"
        encoded = _canonical_json_bytes(envelope)
        with temporary.open("xb") as handle:
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if os.name != "nt":
            target.chmod(0o600)
        return ProviderDiagnosticArtifact(
            artifact_id=artifact_id,
            path=target,
            captured_bytes=len(plaintext),
            truncated=truncated,
        )

    def decrypt_artifact(self, path: Path) -> bytes:
        """Internal operator/test helper; no learner-facing route calls this."""

        resolved = path.expanduser().resolve()
        if (
            resolved.parent != self._directory
            or resolved.suffix != _PROVIDER_DEBUG_SUFFIX
        ):
            raise ValueError(
                "provider diagnostic artifact is outside the configured store"
            )
        envelope = json.loads(resolved.read_text(encoding="utf-8"))
        metadata = envelope["metadata"]
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        return self._aesgcm.decrypt(nonce, ciphertext, _canonical_json_bytes(metadata))

    def _prune_expired(self, *, now: datetime) -> None:
        cutoff = now - self._retention
        for candidate in self._directory.glob(f"*{_PROVIDER_DEBUG_SUFFIX}"):
            try:
                modified = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)
            except OSError:
                continue
            if modified >= cutoff:
                continue
            try:
                candidate.unlink()
            except OSError:
                continue


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _safe_metadata_token(value: str) -> str:
    stripped = str(value).strip()
    safe = "".join(
        character
        for character in stripped
        if character.isalnum() or character in "._:-"
    )
    if not safe:
        return "unknown"
    return safe[:160]


def _safe_filename_token(value: str) -> str:
    safe = _safe_metadata_token(value).replace(":", "-")
    return safe[:64]
