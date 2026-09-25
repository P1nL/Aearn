"""Fail closed before executing the unprivileged worker command."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def check(directory: Path, gid: int) -> None:
    if os.geteuid() == 0 or gid not in (os.getegid(), *os.getgroups()):
        raise ValueError("WORKER_PRIVILEGE_DENIED")
    status = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        status[key] = value.strip()
    if (
        int(status.get("CapEff", "-1"), 16) != 0
        or int(status.get("CapBnd", "-1"), 16) != 0
        or status.get("NoNewPrivs") != "1"
    ):
        raise ValueError("WORKER_CAPABILITY_DENIED")
    parent = directory
    while parent != Path("/"):
        info = parent.lstat()
        if (
            info.st_uid != 0
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ValueError("SOCKET_PARENT_DENIED")
        parent = parent.parent
    info = directory.lstat()
    if info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o750:
        raise ValueError("SOCKET_DIR_DENIED")
    info = (directory / "attest.sock").lstat()
    if (
        not stat.S_ISSOCK(info.st_mode)
        or info.st_uid != 0
        or info.st_gid != gid
        or stat.S_IMODE(info.st_mode) != 0o660
    ):
        raise ValueError("SOCKET_DENIED")
    for name in ("public.key", "policy.sha256"):
        info = (directory / name).lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise ValueError("ATTESTOR_PIN_DENIED")


def main() -> None:
    try:
        directory = Path(sys.argv[1])
        gid = int(sys.argv[2])
        if not directory.is_absolute() or not sys.argv[3:]:
            raise ValueError("WORKER_COMMAND_REQUIRED")
        check(directory, gid)
        # The application must still explicitly construct LiveEgressAttestor
        # with these root-owned pins. This launcher does not enable fetching.
        os.execvp(sys.argv[3], sys.argv[3:])
    except (OSError, ValueError, IndexError):
        raise SystemExit("WORKER_START_DENIED") from None


if __name__ == "__main__":
    main()
