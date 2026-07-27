"""Constructor-only Docker helper types used in fixed launch options."""

from collections.abc import Mapping


class LogConfig:
    def __init__(self, *, type: str, config: Mapping[str, str]) -> None: ...


class Ulimit:
    def __init__(self, *, name: str, soft: int, hard: int) -> None: ...
