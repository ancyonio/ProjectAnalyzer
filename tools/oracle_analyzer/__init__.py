"""Deterministic analysis of an Oracle PL/SQL estate held in a repository.

The graph vocabulary is defined in `constants.py` and documented for agents in
`.github/skills/oracle-analyst/references/graph-model.md`. The database half of
it is shared with `apex_analyzer` rather than duplicated, so a graph from either
analyzer answers the same Cypher.
"""
from .analyzer import OracleAnalyzer
from .constants import SCHEMA_VERSION

__all__ = ['OracleAnalyzer', 'SCHEMA_VERSION']
