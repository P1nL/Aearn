"""Explicit operator launcher; never enabled by importing or building the image."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from attestor import load_config


def main() -> int:
    if os.geteuid() != 0 or os.environ.get("RAG_EGRESS_OPERATOR_APPROVED") != "yes":
        raise SystemExit("EGRESS_DEFAULT_OFF")
    config_file = os.environ.get("RAG_EGRESS_CONFIG")
    if not config_file or not Path(config_file).is_absolute():
        raise SystemExit("EGRESS_CONFIG_REQUIRED")
    try:
        config = load_config(Path(config_file))
    except (OSError, ValueError):
        raise SystemExit("EGRESS_CONFIG_DENIED") from None
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise SystemExit("WORKER_COMMAND_REQUIRED")
    directory = Path(config["socket_dir"])
    signer_env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "RAG_EGRESS_OPERATOR_APPROVED": "yes",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    signer = subprocess.Popen(
        [sys.executable, "/opt/rag-egress/attestor.py", "--config", config_file],
        env=signer_env,
    )
    worker = None
    try:
        for _ in range(50):
            if signer.poll() is not None:
                raise RuntimeError("SIGNER_FAILED")
            sock = directory / "attest.sock"
            if (
                sock.exists()
                and stat.S_ISSOCK(sock.lstat().st_mode)
                and (directory / "public.key").is_file()
                and (directory / "policy.sha256").is_file()
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("SIGNER_NOT_READY")
        # The signer alone retains root/NET_ADMIN. No shell or caller-controlled
        # interpolation; setpriv removes every worker capability and privilege gain.
        worker_env = os.environ.copy()
        worker_env.update(
            {
                "RAG_EGRESS_SOCKET_PATH": str(directory / "attest.sock"),
                "RAG_EGRESS_PUBLIC_KEY_PATH": str(directory / "public.key"),
                "RAG_EGRESS_POLICY_PATH": str(directory / "policy.sha256"),
                "RAG_EGRESS_DEPLOYMENT_ID": str(config["deployment_id"]),
                "RAG_EGRESS_TRUSTED_GID": str(config["trusted_gid"]),
            }
        )
        worker = subprocess.Popen(
            [
                "/usr/bin/setpriv",
                "--no-new-privs",
                "--bounding-set=-all",
                "--reuid",
                str(config["worker_uid"]),
                "--regid",
                str(config["worker_gid"]),
                "--groups",
                str(config["trusted_gid"]),
                sys.executable,
                "/opt/rag-egress/worker_entry.py",
                str(directory),
                str(config["trusted_gid"]),
                *command,
            ],
            env=worker_env,
        )
        while worker.poll() is None:
            if signer.poll() is not None:
                worker.terminate()
                raise RuntimeError("SIGNER_LOST")
            time.sleep(0.1)
        return worker.returncode or 0
    except (OSError, RuntimeError):
        print("EGRESS_LAUNCH_DENIED", file=sys.stderr)
        return 1
    finally:
        if worker is not None and worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=2)
            except subprocess.TimeoutExpired:
                worker.kill()
        if signer.poll() is None:
            signer.terminate()
            try:
                signer.wait(timeout=2)
            except subprocess.TimeoutExpired:
                signer.kill()


if __name__ == "__main__":
    raise SystemExit(main())
