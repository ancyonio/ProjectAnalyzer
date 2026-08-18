"""PL/SQL block analysis for APEX.

The analyser itself moved to `analyzer_core.plsql.blocks` so `oracle_analyzer`
can use it too. This module binds the APEX-specific sets -- the runtime
packages whose calls are platform usage rather than application dependencies,
and the deprecated APIs the rule catalogue reports -- so every APEX caller gets
them without passing them explicitly.
"""
from __future__ import annotations

from typing import FrozenSet, Optional

from analyzer_core.plsql.blocks import PlsqlAnalysis, normalise_plsql
from analyzer_core.plsql.blocks import analyse_plsql as _analyse_plsql

from ..constants import APEX_RUNTIME_PACKAGES, DEPRECATED_APIS

__all__ = ['PlsqlAnalysis', 'analyse_plsql', 'normalise_plsql']


def analyse_plsql(text: str,
                  runtime_packages: Optional[FrozenSet[str]] = None,
                  deprecated_apis: Optional[FrozenSet[str]] = None
                  ) -> PlsqlAnalysis:
    """Analyse a PL/SQL block with the APEX platform sets applied."""
    return _analyse_plsql(
        text,
        runtime_packages=(frozenset(APEX_RUNTIME_PACKAGES)
                          if runtime_packages is None else runtime_packages),
        deprecated_apis=(frozenset(DEPRECATED_APIS)
                         if deprecated_apis is None else deprecated_apis),
    )
