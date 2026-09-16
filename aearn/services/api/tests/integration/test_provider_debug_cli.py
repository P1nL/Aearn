from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from app.core import config
from app.core.config import Settings
from app.services.llm import provider_debug_cli as cli
from app.services.llm.provider_diagnostics import ProviderDiagnosticMetadata


_KEY = b"0123456789abcdef" * 2
_BODY = 'fake rejected response: {"private_text": "never show by default"}'
_RUN_ID = "00000000-0000-4000-8000-000000000001"
_OTHER_RUN_ID = "00000000-0000-4000-8000-000000000002"
_ARTIFACT_ID = "a" * 32
_SUFFIX = ".aearn-provider-debug"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    # Do not consult host environment defaults or any real provider credentials.
    monkeypatch.setattr(config, "_env_str", lambda _name, default: default)
    monkeypatch.setattr(config, "_env_optional", lambda _name: None)
    directory = tmp_path / "artifacts"
    directory.mkdir()
    settings = Settings(
        llm_type="disabled",
        tutor_provider_debug_capture_mode="rejected",
        tutor_provider_debug_capture_key=SecretStr(
            base64.b64encode(_KEY).decode("ascii")
        ),
        tutor_provider_debug_capture_directory=str(directory),
        tutor_provider_debug_capture_max_bytes=4096,
        tutor_provider_debug_capture_retention_hours=24,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    return settings


def _write_artifact(
    settings: Settings,
    *,
    artifact_id: str = _ARTIFACT_ID,
    run_id: str = _RUN_ID,
    legacy: bool = False,
    second: int = 0,
) -> Path:
    metadata = ProviderDiagnosticMetadata(
        run_id=run_id,
        attempt_index=1,
        provider_type="fake",
        protocol="responses",
        model="test-model",
        diagnostic_code="decision_schema_invalid",
        contract_hash="fake-contract-hash",
    ).as_dict(
        artifact_id=artifact_id,
        created_at=datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC),
    )
    metadata.update(captured_bytes=len(_BODY.encode()), truncated=False)
    # Exercise legacy files independently of the current writer's schema defaults.
    metadata.pop("input_revision", None)
    metadata.pop("decision_iteration", None)
    if not legacy:
        metadata.update(input_revision=7, decision_iteration=2)
    metadata["unexpected_body"] = _BODY
    nonce = bytes.fromhex(artifact_id)[:12]
    aad = json.dumps(
        metadata, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    ciphertext = AESGCM(_KEY).encrypt(nonce, _BODY.encode(), aad)
    envelope = {
        "metadata": metadata,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "unexpected_body": _BODY,
    }
    attempt = "1" if legacy else "r7-d2-a1"
    path = (
        settings.tutor_provider_debug_capture_path
        / f"1767225600000-{run_id}-{attempt}-{artifact_id}{_SUFFIX}"
    )
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


@pytest.mark.parametrize("legacy", [False, True])
def test_list_filter_and_show_only_decrypt_with_body(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    legacy: bool,
) -> None:
    first = _write_artifact(settings, legacy=legacy)
    second = _write_artifact(
        settings, artifact_id="b" * 32, run_id=_OTHER_RUN_ID, second=1
    )
    before = {path.name: path.read_bytes() for path in (first, second)}
    calls: list[Settings] = []
    original_factory = cli.ProviderDiagnosticStore.from_settings

    def factory(value: Settings, *, read_only: bool = False):
        calls.append(value)
        assert read_only
        return original_factory(value, read_only=read_only)

    monkeypatch.setattr(cli.ProviderDiagnosticStore, "from_settings", factory)
    for arguments, expected_ids in (
        (["list"], ["b" * 32, _ARTIFACT_ID]),
        (["list", "--limit", "1"], ["b" * 32]),
        (["list", "--run-id", _RUN_ID], [_ARTIFACT_ID]),
        (["list", "--run-id", "00000000-0000-4000-8000-000000000003"], []),
    ):
        assert cli.main(arguments) == 0
        captured = capsys.readouterr()
        assert [row["artifact_id"] for row in json.loads(captured.out)] == expected_ids
        assert not captured.err
        assert _BODY not in captured.out
        assert "unexpected_body" not in captured.out
        assert "ciphertext" not in captured.out
        assert str(settings.tutor_provider_debug_capture_path) not in captured.out

    assert cli.main(["show", _ARTIFACT_ID]) == 0
    captured = capsys.readouterr()
    metadata = json.loads(captured.out)
    assert "body" not in metadata and "unexpected_body" not in metadata
    assert metadata["attempt_index"] == 1
    assert metadata.get("input_revision") == (None if legacy else 7)
    assert metadata.get("decision_iteration") == (None if legacy else 2)
    assert calls == []

    assert cli.main(["show", _ARTIFACT_ID, "--body"]) == 0
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out)["body"] == _BODY
    assert len(calls) == 1
    assert {path.name: path.read_bytes() for path in first.parent.iterdir()} == before


@pytest.mark.parametrize(
    "unsafe",
    [
        "arguments",
        "symlink-inside",
        "symlink-outside",
        "directory-symlink",
        "resolved-outside",
        "duplicate",
        "mismatched-id",
    ],
)
def test_invalid_ids_and_unsafe_paths_are_rejected(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unsafe: str,
) -> None:
    path = _write_artifact(settings)
    if unsafe == "arguments":
        arguments = [
            ["show", value, "--body"]
            for value in (
                "../private",
                "A" * 32,
                "a" * 31,
                "a" * 33,
                "g" * 32,
                str(path),
            )
        ]
        arguments += [
            ["list", "--limit", value] for value in ("0", "-1", "101", "private")
        ]
        arguments += [["list", "--run-id", str(path)]]
        for argv in arguments:
            with pytest.raises(SystemExit) as error:
                cli.main(argv)
            assert error.value.code == 2
            captured = capsys.readouterr()
            assert captured.out == ""
            assert (
                captured.err
                == "provider-debug: invalid arguments; use --help for usage.\n"
            )
        return

    if unsafe.startswith("symlink"):
        target = (
            path.with_suffix(".encrypted")
            if unsafe == "symlink-inside"
            else tmp_path / "outside.encrypted"
        )
        path.rename(target)
        try:
            path.symlink_to(target)
        except OSError:
            # Windows without symlink privilege: exercise the same filesystem probe.
            path.write_bytes(target.read_bytes())
            original = Path.is_symlink
            monkeypatch.setattr(
                Path, "is_symlink", lambda self: self == path or original(self)
            )
    elif unsafe == "directory-symlink":
        original = Path.is_symlink
        monkeypatch.setattr(
            Path, "is_symlink", lambda self: self == path.parent or original(self)
        )
    elif unsafe == "resolved-outside":
        outside = tmp_path / f"outside-{_ARTIFACT_ID}{_SUFFIX}"
        outside.write_bytes(path.read_bytes())
        original_resolve = Path.resolve
        monkeypatch.setattr(
            Path,
            "resolve",
            lambda self, **kwargs: (
                outside if self == path else original_resolve(self, **kwargs)
            ),
        )
    elif unsafe == "duplicate":
        (path.parent / f"duplicate-{_ARTIFACT_ID}{_SUFFIX}").write_bytes(
            path.read_bytes()
        )
    elif unsafe == "mismatched-id":
        path.rename(path.parent / f"mismatch-{'b' * 32}{_SUFFIX}")

    def no_store(_settings: Settings):
        pytest.fail("Unsafe artifacts must be rejected before initializing the store")

    monkeypatch.setattr(cli.ProviderDiagnosticStore, "from_settings", no_store)
    selected_id = "b" * 32 if unsafe == "mismatched-id" else _ARTIFACT_ID
    for argv in (["list", "--limit", "1"], ["show", selected_id, "--body"]):
        assert cli.main(argv) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "provider-debug:" in captured.err
        assert _BODY not in captured.err and str(tmp_path) not in captured.err
        assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "failure",
    [
        "disabled",
        "missing-directory",
        "missing-artifact",
        "settings-error",
        "bad-json",
        "bad-metadata",
        "wrong-key",
    ],
)
def test_errors_are_safe_and_do_not_create_diagnostic_files(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    path = _write_artifact(settings)
    args = ["show", _ARTIFACT_ID, "--body"]
    if failure == "disabled":
        settings.tutor_provider_debug_capture_mode = "off"
        settings.tutor_provider_debug_capture_directory = str(tmp_path / "missing")
    elif failure == "missing-directory":
        settings.tutor_provider_debug_capture_directory = str(tmp_path / "missing")
    elif failure == "missing-artifact":
        args = ["show", "b" * 32, "--body"]
    elif failure == "settings-error":

        def broken_settings():
            raise ValueError(f"{_BODY}: {tmp_path}: {_KEY!r}")

        monkeypatch.setattr(cli, "get_settings", broken_settings)
    elif failure == "bad-json":
        path.write_text(_BODY, encoding="utf-8")
    elif failure == "bad-metadata":
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["metadata"]["model"] = {"body": _BODY}
        path.write_text(json.dumps(envelope), encoding="utf-8")
    elif failure == "wrong-key":
        settings.tutor_provider_debug_capture_key = SecretStr(
            base64.b64encode(b"z" * 32).decode("ascii")
        )
    before = {
        item.relative_to(tmp_path): item.read_bytes()
        for item in tmp_path.rglob("*")
        if item.is_file()
    }
    assert cli.main(args) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "provider-debug:" in captured.err
    for secret in (
        _BODY,
        _KEY.decode(),
        base64.b64encode(_KEY).decode(),
        str(tmp_path),
        "Traceback",
    ):
        assert secret not in captured.err
    assert not (tmp_path / "missing").exists()
    assert {
        item.relative_to(tmp_path): item.read_bytes()
        for item in tmp_path.rglob("*")
        if item.is_file()
    } == before
