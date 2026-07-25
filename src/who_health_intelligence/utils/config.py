"""
Compatibility wrapper for centralized project configuration.

The canonical configuration lives in ``src/config.py``. This module preserves
existing imports from ``who_health_intelligence.utils.config`` while preventing
configuration values from being scattered across the codebase.
"""

from __future__ import annotations

from importlib import import_module

try:
    _config = import_module("src.config")
except ModuleNotFoundError:
    _config = import_module("config")

__all__ = list(getattr(_config, "__all__", []))
for _name in __all__:
    globals()[_name] = getattr(_config, _name)

del _config, _name, import_module
