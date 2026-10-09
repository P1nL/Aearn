"""Default-off C control composition; never launches Docker, worker or HTTP."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from typing import Any
from uuid import UUID

import psycopg
from cryptography.hazmat.primitives import serialization
from app.services.grounding.autonomous.registered_source_bridge_host import (
    SignedDispatchProofVerifier, make_host_callbacks,
    owned_b1d_scope_allowed, owned_course_scope_allowed, transport_database_allowed,
)
from app.services.grounding.autonomous.registered_source_policy import RegisteredSourceScope
from app.services.grounding.autonomous.registered_source_repository import PostgresRegisteredSourceRepository
from protocol import BridgeDenied, Scope
from server import CaptureRecord, Decision, GrantServer

HASH = re.compile(r"[0-9a-f]{64}\Z")
DB = re.compile(r"aearn_rag260_c_[a-zA-Z0-9_]+\Z")
CONFIG = {"approved", "database_name", "dsn_secret_path", "directory", "arm_path",
          "scope", "b_attestor", "worker_uid", "worker_gid", "trusted_gid",
          "worker_image_sha256", "deployment_id"}
CONFIG_ASSESSMENT = CONFIG | {"owned_b1d_assessment"}
CONFIG_COURSE = CONFIG | {"owned_b1d_course_sources"}
PIN = {"public_key_hex", "public_key_sha256", "deployment_id", "policy_sha256",
       "namespace_inode", "allowed_ips"}
ARM = {"public_key_sha256", "deployment_id", "scope", "request_hash",
       "operation_key", "expires_unix", "b_attestor", "worker_image_sha256"}
ARM_SUPPLEMENTAL = ARM | {"supplemental_authorization_id"}


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("DUPLICATE_FIELD")
        value[key] = item
    return value


def _absolute(value: object) -> Path:
    if type(value) is not str or not value or ".." in Path(value).parts:
        raise ValueError("INVALID_PATH")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("INVALID_PATH")
    return path


def _root_file(path: Path, *, limit: int = 8192) -> tuple[bytes, os.stat_result]:
    """Root-owned, private, no symlink and no writable ancestor on Linux."""
    if os.name != "posix" or os.geteuid() != 0 or not path.is_absolute():
        raise ValueError("ROOT_FILE_DENIED")
    for parent in path.parents:
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise ValueError("ROOT_FILE_DENIED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o077 or not 0 < info.st_size <= limit):
            raise ValueError("ROOT_FILE_DENIED")
        body = os.read(fd, limit + 1)
        if len(body) != info.st_size:
            raise ValueError("ROOT_FILE_DENIED")
        return body, info
    finally:
        os.close(fd)


def _root_json(path: Path) -> tuple[dict[str, Any], os.stat_result]:
    raw, info = _root_file(path)
    value = json.loads(raw, object_pairs_hook=_unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(value) is not dict:
        raise ValueError("CONFIG_DENIED")
    return value, info


def _digest(value: object) -> bool:
    return type(value) is str and HASH.fullmatch(value) is not None


def _canonical_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


class ControlRuntime:
    """One in-memory dispatch owner: process restart loses both permits."""

    def __init__(self, config: dict[str, Any], dsn: str) -> None:
        if (type(config) is not dict or set(config) not in (CONFIG, CONFIG_ASSESSMENT, CONFIG_COURSE)
                or config["approved"] is not True or type(config.get("owned_b1d_assessment", False)) is not bool
                or type(config.get("owned_b1d_course_sources", False)) is not bool):
            raise ValueError("CONFIG_DENIED")
        owned_assessment = config.get("owned_b1d_assessment", False)
        owned_course = config.get("owned_b1d_course_sources", False)
        if (not transport_database_allowed(config["database_name"], owned_b1d_assessment=owned_assessment,
                                           owned_b1d_course_sources=owned_course)
                or psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") != config["database_name"]):
            raise ValueError("DATABASE_DENIED")
        self.directory = _absolute(config["directory"])
        self.arm_path = _absolute(config["arm_path"])
        if (self.arm_path == self.directory or self.directory in self.arm_path.parents
                or _absolute(config["dsn_secret_path"]) == self.arm_path):
            raise ValueError("ARM_PATH_DENIED")
        pin = config["b_attestor"]
        if (type(pin) is not dict or set(pin) != PIN
                or type(pin["public_key_hex"]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", pin["public_key_hex"]) is None
                or not _digest(pin["public_key_sha256"])
                or hashlib.sha256(bytes.fromhex(pin["public_key_hex"])).hexdigest()
                   != pin["public_key_sha256"]
                or type(pin["allowed_ips"]) is not list
                or any(type(ip) is not str for ip in pin["allowed_ips"])
                or len(set(pin["allowed_ips"])) != len(pin["allowed_ips"])):
            raise ValueError("ATTESTOR_CONFIG_DENIED")
        if not _digest(config["worker_image_sha256"]):
            raise ValueError("IMAGE_DENIED")
        self.scope = Scope.from_wire(config["scope"])
        if ((owned_assessment and not owned_b1d_scope_allowed(self._domain_scope()))
                or (owned_course and not owned_course_scope_allowed(self._domain_scope()))
                or (not owned_assessment and not owned_course and (self.scope.url != "https://www.sqlite.org/lang_select.html"
                    or self.scope.subject_id != "route.sql" or self.scope.facets != ("queries",)))):
            raise ValueError("SCOPE_DENIED")
        self._pin = pin
        self._image = config["worker_image_sha256"]
        self._owner = PostgresRegisteredSourceRepository(dsn)
        verifier = SignedDispatchProofVerifier(
            public_key=bytes.fromhex(pin["public_key_hex"]),
            deployment_id=pin["deployment_id"], policy_sha256=pin["policy_sha256"],
            namespace_inode=pin["namespace_inode"], allowed_ips=frozenset(pin["allowed_ips"]),
        )
        callbacks = make_host_callbacks(
            dsn=dsn, verifier=verifier, decision_type=Decision,
            capture_record_type=CaptureRecord, worker_uid=config["worker_uid"],
            worker_gid=config["worker_gid"], dispatch_owner=self._owner,
            worker_image_sha256=self._image,
            owned_b1d_assessment=owned_assessment,
            owned_b1d_course_sources=owned_course,
        )
        self._lock = threading.Lock()
        self._attempted = False

        def resolver(scope: Scope, now: object) -> object | None:
            if type(scope) is not Scope or scope != self.scope:
                return None
            with self._lock:
                if not self._attempted:
                    try:
                        arm = self._approved_arm()
                    except (OSError, ValueError, TypeError, KeyError):
                        return None
                    # One DB attempt only. Commit is inside take_dispatch, before
                    # callbacks.resolver can return a grant to the worker.
                    self._attempted = True
                    try:
                        dispatch_args: dict[str, Any] = {}
                        if "supplemental_authorization_id" in arm:
                            dispatch_args["supplemental_authorization_id"] = UUID(
                                arm["supplemental_authorization_id"]
                            )
                        self._owner.take_dispatch(
                            self._domain_scope(), operation_key=arm["operation_key"],
                            request_hash=arm["request_hash"], now=now, **dispatch_args,
                        )
                    except ValueError:
                        return None
                return callbacks.resolver(scope, now)

        self.server = GrantServer(
            resolver=resolver, deployment_id=config["deployment_id"],
            worker_uid=config["worker_uid"], worker_gid=config["worker_gid"],
            trusted_gid=config["trusted_gid"], proof_verifier=callbacks.proof_verifier,
            capture_store=callbacks.capture_store,
        )

    def _domain_scope(self) -> RegisteredSourceScope:
        return RegisteredSourceScope(**{**vars(self.scope), "dispatch_id": UUID(self.scope.dispatch_id)})

    def _approved_arm(self) -> dict[str, Any]:
        key_path = self.directory / "public.key"
        key_info = key_path.lstat()
        if (not stat.S_ISREG(key_info.st_mode) or key_info.st_uid != 0
                or stat.S_IMODE(key_info.st_mode) != 0o644):
            raise ValueError("ARM_DENIED")
        key = key_path.read_bytes()
        expected = self.server.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        if key != expected:
            raise ValueError("ARM_DENIED")
        arm, info = _root_json(self.arm_path)
        if (set(arm) not in (ARM, ARM_SUPPLEMENTAL)
                or ("supplemental_authorization_id" in arm
                    and not _canonical_uuid(arm["supplemental_authorization_id"]))
                or info.st_ctime_ns <= key_info.st_ctime_ns
                or arm["public_key_sha256"] != hashlib.sha256(expected).hexdigest()
                or arm["deployment_id"] != self.server.deployment_id
                or arm["scope"] != self.scope.wire() or arm["b_attestor"] != self._pin
                or arm["worker_image_sha256"] != self._image
                or not _digest(arm["request_hash"])
                or type(arm["operation_key"]) is not str
                or re.fullmatch(r"[A-Za-z0-9._:-]{8,160}", arm["operation_key"]) is None
                or type(arm["expires_unix"]) is not int
                or not time.time() < arm["expires_unix"] <= time.time() + 300):
            raise ValueError("ARM_DENIED")
        return arm

    def serve(self, *, approved: bool = False) -> None:
        """Publish C ephemeral key/socket; does not dispatch at startup."""
        self.server.serve(self.directory, approved=approved)


def build_runtime(config_path: Path, *, approved: bool = False) -> ControlRuntime:
    """Explicit approved root config and secret are required; no DB I/O here."""
    if not approved:
        raise BridgeDenied("DEFAULT_OFF")
    try:
        config, _ = _root_json(config_path)
        if (set(config) not in (CONFIG, CONFIG_ASSESSMENT, CONFIG_COURSE) or config["approved"] is not True
                or type(config.get("owned_b1d_assessment", False)) is not bool
                or type(config.get("owned_b1d_course_sources", False)) is not bool):
            raise ValueError("CONFIG_DENIED")
        secret, _ = _root_file(_absolute(config["dsn_secret_path"]), limit=4096)
        dsn = secret.decode("utf-8").strip()
        if not dsn or "\n" in dsn or "\r" in dsn:
            raise ValueError("DATABASE_DENIED")
        return ControlRuntime(config, dsn)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, psycopg.Error):
        raise BridgeDenied("CONFIG_DENIED") from None


def main() -> None:
    import sys
    if sys.argv[1:] != ["--serve"]:
        raise SystemExit("CONTROL_DEFAULT_OFF")
    try:
        instance = build_runtime(Path("/etc/rag-c-control/config.json"), approved=True)
        instance.serve(approved=True)
    except (Exception, KeyboardInterrupt):
        raise SystemExit("CONTROL_RUNTIME_DENIED") from None


if __name__ == "__main__":
    main()
