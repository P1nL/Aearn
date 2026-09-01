"""Persistence mixin 的共享类型边界。"""
from __future__ import annotations

from typing import Any


class PersistenceMixin:
    """只声明 facade 注入的状态，并为跨职责调用提供动态类型边界。"""

    _conn: Any
    _settings: Any
    _projector: Any
    _failpoint: Any
    _effect_handlers: Any
    _cursor_signing_key: bytes
    _effect_descriptors: Any

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(name)
