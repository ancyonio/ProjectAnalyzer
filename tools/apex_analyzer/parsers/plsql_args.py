"""Moved to `analyzer_core.plsql.args`; re-exported so existing
imports and the binder test corpus keep working.
"""
from __future__ import annotations

from analyzer_core.plsql.args import *  # noqa: F401,F403
from analyzer_core.plsql.args import __dict__ as _moved  # noqa: F401

__all__ = [n for n in _moved if not n.startswith("_")]
