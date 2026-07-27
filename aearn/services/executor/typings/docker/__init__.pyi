"""Narrow type surface used by the isolated Docker client boundary."""

from typing import Any


class DockerClient:
    images: Any
    containers: Any

    def ping(self) -> Any: ...


def from_env() -> DockerClient: ...
