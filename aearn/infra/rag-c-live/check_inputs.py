"""Host-side gate for offline Compose inputs. Does not start Docker or make requests."""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import stat

IMAGE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}\Z")
ENV_IMAGES = (
    "RAG_C_CONTROL_BASE",
    "RAG_C_EGRESS_BASE",
    "RAG_C_CONTROL_IMAGE",
    "RAG_C_EGRESS_IMAGE",
)
ENV_IDS = ("RAG_C_WORKER_UID", "RAG_C_WORKER_GID", "RAG_C_BRIDGE_GID")


def check_digest_ref(value: str) -> None:
    if not IMAGE.fullmatch(value):
        raise ValueError("IMAGE_NOT_PINNED")


def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CONFIG_DUPLICATE_FIELD")
        result[key] = value
    return result


def root_config(path: Path) -> dict[str, object]:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or getattr(os, "geteuid", lambda: -1)() != 0
    ):
        raise ValueError("CONFIG_NOT_ROOT_REVIEWED")
    for parent in path.parents:
        if parent == Path("/"):
            break
        info = parent.lstat()
        if (
            info.st_uid != 0
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > 8192
        ):
            raise ValueError("CONFIG_PARENT_DENIED")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (
            info.st_uid != 0
            or not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > 8192
        ):
            raise ValueError("CONFIG_MODE_DENIED")
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            fd = -1
            data = json.load(source, object_pairs_hook=unique)
    finally:
        if fd >= 0:
            os.close(fd)
    if type(data) is not dict or set(data["destinations"]) != {"www.sqlite.org"}:
        raise ValueError("CONFIG_TARGET_DENIED")
    addresses = data["destinations"]["www.sqlite.org"]
    if type(addresses) is not list or not 1 <= len(addresses) <= 16:
        raise ValueError("CONFIG_TARGET_DENIED")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            not isinstance(ip, ipaddress.IPv4Address)
            or not ip.is_global
            or str(ip) != address
        ):
            raise ValueError("CONFIG_TARGET_DENIED")
    return data


def check_inputs(env: dict[str, str]) -> None:
    for name in ENV_IMAGES:
        check_digest_ref(env[name])
    ids = {name: int(env[name]) for name in ENV_IDS}
    if any(value <= 0 or value >= 2**31 for value in ids.values()):
        raise ValueError("ID_DENIED")
    data = root_config(Path(env["RAG_C_EGRESS_CONFIG"]))
    if (
        data["worker_uid"] != ids["RAG_C_WORKER_UID"]
        or data["worker_gid"] != ids["RAG_C_WORKER_GID"]
        or data["trusted_gid"] != ids["RAG_C_BRIDGE_GID"]
    ):
        raise ValueError("ID_MISMATCH")


def main() -> None:
    try:
        check_inputs(os.environ)
    except (OSError, KeyError, TypeError, ValueError):
        raise SystemExit("OFFLINE_INPUTS_DENIED") from None
    print("OFFLINE_INPUTS_READY_NOT_LIVE")


if __name__ == "__main__":
    main()
