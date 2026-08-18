"""Shared Oracle source analysis: SQL binding, PL/SQL blocks, DDL.

Used by both `apex_analyzer` and `oracle_analyzer`. Nothing here knows which
dialect is calling; anything dialect-specific arrives as an argument.
"""
from .args import ExportCall, iter_calls, mask_literals, parse_value
from .blocks import PlsqlAnalysis, analyse_plsql, normalise_plsql
from .ddl import (DdlColumn, DdlObject, DdlResult, extract_unit_bodies,
                  parse_ddl, split_statements)
from .sqlparse import (SqlAnalysis, TableRef, analyse_sql, normalise_sql,
                       split_object, strip_comments)

__all__ = [
    'ExportCall', 'iter_calls', 'mask_literals', 'parse_value',
    'PlsqlAnalysis', 'analyse_plsql', 'normalise_plsql',
    'DdlColumn', 'DdlObject', 'DdlResult', 'parse_ddl', 'split_statements',
    'extract_unit_bodies',
    'SqlAnalysis', 'TableRef', 'analyse_sql', 'normalise_sql',
    'split_object', 'strip_comments',
]
