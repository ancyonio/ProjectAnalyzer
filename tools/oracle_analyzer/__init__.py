"""Deterministic analysis of an Oracle PL/SQL estate held in a repository.

Implements docs/ORACLE_ANALYZER_SPEC.md. The database vocabulary is shared with
`apex_analyzer` rather than duplicated, so a graph from either analyzer answers
the same Cypher.
"""
from .analyzer import OracleAnalyzer
from .constants import SCHEMA_VERSION

__all__ = ['OracleAnalyzer', 'SCHEMA_VERSION']
