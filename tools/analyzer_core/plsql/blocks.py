"""PL/SQL block analysis.

A page process, a dynamic action, a validation or a package body is analysed
for the things that matter to the graph:

* the SQL statements it embeds (each analysed by `sqlparse`, so a process that
  updates ORDERS produces the same `WRITES_TO` edge a region query would);
* the procedures and functions it calls;
* transaction and error-handling behaviour (`COMMIT`, `WHEN OTHERS THEN NULL`),
  which the rules engine scores;
* dynamic SQL, which is where dependency analysis legitimately runs out of
  road — flagged rather than guessed at.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import chain
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from .constants import (BIND_RE, ORACLE_BUILTIN_PACKAGES, SQL_RESERVED,
                        SUBSTITUTION_RE)
from .args import mask_literals
from .sqlparse import SqlAnalysis, analyse_sql, strip_comments

_STATEMENT_START_RE = re.compile(
    r'\b(SELECT|INSERT|UPDATE|DELETE|MERGE)\b', re.IGNORECASE)
_CALL_RE = re.compile(
    r'\b("?[A-Za-z][A-Za-z0-9_$#]*"?)\s*\.\s*("?[A-Za-z][A-Za-z0-9_$#]*"?)\s*\(')
# `PKG.PROC;` is a call with no arguments, but it is a *statement*. Matching
# that shape anywhere reads `RETURN v_rec.AMOUNT;` as a call to a package named
# V_REC: an attribute of an object type is not a call, and counting it as one
# leaves an unresolvable reference that never existed.
_PARAMLESS_CALL_RE = re.compile(
    r'(?:^|;|\bBEGIN\b|\bTHEN\b|\bELSE\b|\bLOOP\b)\s*'
    r'("?[A-Za-z][A-Za-z0-9_$#]*"?)\s*\.\s*("?[A-Za-z][A-Za-z0-9_$#]*"?)\s*;',
    re.IGNORECASE | re.MULTILINE)
_BARE_CALL_RE = re.compile(r'(?:^|[\s;])([A-Za-z][A-Za-z0-9_$#]*)\s*\(', re.MULTILINE)
_DYNAMIC_RE = re.compile(r'\b(EXECUTE\s+IMMEDIATE|DBMS_SQL\.|OPEN\s+\w+\s+FOR\s+\w)',
                         re.IGNORECASE)
_COMMIT_RE = re.compile(r'\bCOMMIT\b|\bROLLBACK\b', re.IGNORECASE)
_EXCEPTION_RE = re.compile(r'\bEXCEPTION\b', re.IGNORECASE)
_WHEN_OTHERS_NULL_RE = re.compile(
    r'\bWHEN\s+OTHERS\s+THEN\s+NULL\s*;', re.IGNORECASE)
_CONCAT_BIND_RE = re.compile(
    r"\|\|\s*[:&]?[A-Za-z][A-Za-z0-9_$#]*|[:&][A-Za-z][A-Za-z0-9_$#]*\s*\|\|")


@dataclass
class PlsqlAnalysis:
    text: str
    statements: List[SqlAnalysis] = field(default_factory=list)
    calls: List[Tuple[str, str]] = field(default_factory=list)     # (package|'', name)
    binds: List[str] = field(default_factory=list)
    substitutions: List[str] = field(default_factory=list)
    deprecated_calls: List[str] = field(default_factory=list)
    apex_api_calls: List[str] = field(default_factory=list)
    line_count: int = 0
    has_exception_handler: bool = False
    has_when_others_null: bool = False
    has_commit: bool = False
    has_dynamic_sql: bool = False
    dynamic_sql_concatenates_input: bool = False
    parse_status: str = 'PARSED'

    @property
    def call_count(self) -> int:
        return len(set(self.calls))

    def tables(self):
        for statement in self.statements:
            for table in statement.tables:
                yield table

    def properties(self) -> Dict[str, object]:
        return {
            'lineCount': self.line_count,
            'callCount': self.call_count,
            'bindCount': len(set(self.binds) | set(self.substitutions)),
            'hasExceptionHandler': self.has_exception_handler,
            'hasWhenOthersNull': self.has_when_others_null,
            'hasCommit': self.has_commit,
            'hasDynamicSql': self.has_dynamic_sql,
            'parseStatus': self.parse_status,
        }


def normalise_plsql(text: str) -> str:
    return re.sub(r'\s+', ' ', strip_comments(text or '')).strip().lower()


def _split_statements(text: str, masked: str) -> List[Tuple[int, int]]:
    """Statement spans, split on `;` at bracket depth zero."""
    spans: List[Tuple[int, int]] = []
    depth, start = 0, 0
    for i, ch in enumerate(masked):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth = max(0, depth - 1)
        elif ch == ';' and depth == 0:
            spans.append((start, i))
            start = i + 1
    if start < len(text):
        spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def analyse_plsql(text: str,
                  runtime_packages: FrozenSet[str] = frozenset(),
                  deprecated_apis: FrozenSet[str] = frozenset()) -> PlsqlAnalysis:
    """Analyse an anonymous block, a function body or a package body.

    `runtime_packages` are platform packages whose calls are recorded as
    platform usage rather than application dependencies (APEX_UTIL and friends
    for APEX; usually empty for a plain Oracle estate). `deprecated_apis` are
    fully-qualified names the caller wants flagged. Both are arguments rather
    than imports so this module stays dialect-agnostic.
    """
    result = PlsqlAnalysis(text=text or '')
    if not text or not text.strip():
        result.parse_status = 'FAILED'
        return result

    result.line_count = text.count('\n') + 1
    masked = mask_literals(text)

    result.has_exception_handler = bool(_EXCEPTION_RE.search(masked))
    result.has_when_others_null = bool(_WHEN_OTHERS_NULL_RE.search(masked))
    result.has_commit = bool(_COMMIT_RE.search(masked))
    result.has_dynamic_sql = bool(_DYNAMIC_RE.search(masked))
    if result.has_dynamic_sql:
        # concatenating a page item into dynamic SQL is the injection pattern
        result.dynamic_sql_concatenates_input = bool(_CONCAT_BIND_RE.search(text))

    for start, end in _split_statements(text, masked):
        fragment = text[start:end]
        fragment_masked = masked[start:end]
        if not _STATEMENT_START_RE.search(fragment_masked):
            continue
        offset = _STATEMENT_START_RE.search(fragment_masked).start()
        statement = analyse_sql(fragment[offset:])
        if statement.tables or statement.verb:
            result.statements.append(statement)

    # A qualified name in a DML statement is a table, not a call:
    # `insert into order_app.audit_log (...)` must not become CALLS.
    table_names = {(t.owner.upper(), t.name.upper()) for t in result.tables()}
    bare_tables = {name for _, name in table_names}

    seen_calls: Set[Tuple[str, str]] = set()
    for match in chain(_CALL_RE.finditer(masked),
                       _PARAMLESS_CALL_RE.finditer(masked)):
        package = match.group(1).strip('"').upper()
        name = match.group(2).strip('"').upper()
        if package in SQL_RESERVED or name in SQL_RESERVED:
            continue
        if (package, name) in table_names or name in bare_tables:
            continue
        if name in ('NEXTVAL', 'CURRVAL', 'COUNT', 'FIRST', 'LAST', 'NEXT', 'PRIOR',
                    'EXISTS', 'DELETE', 'EXTEND', 'TRIM'):
            continue
        qualified = f'{package}.{name}'
        if qualified in deprecated_apis:
            result.deprecated_calls.append(qualified)
        if package in runtime_packages:
            result.apex_api_calls.append(qualified)
            continue
        if package in ORACLE_BUILTIN_PACKAGES:
            continue
        if (package, name) not in seen_calls:
            seen_calls.add((package, name))
            result.calls.append((package, name))

    result.binds = sorted({m.group(1).upper() for m in BIND_RE.finditer(masked)})
    result.substitutions = sorted({m.group(1).upper()
                                   for m in SUBSTITUTION_RE.finditer(masked)})

    if not result.statements and not result.calls and not masked.strip():
        result.parse_status = 'FAILED'
    elif result.has_dynamic_sql and not result.statements:
        result.parse_status = 'PARTIAL'
    return result


def analyse_condition(expression: str, condition_type: str,
                      sql_types: Set[str], plsql_types: Set[str]
                      ) -> Tuple[Optional[SqlAnalysis], Optional[PlsqlAnalysis]]:
    """Conditions carry code too: `EXISTS (SELECT …)` is a real query and a real
    dependency. Returns whichever analysis applies."""
    if not expression or not expression.strip():
        return None, None
    kind = (condition_type or '').upper()
    if kind in sql_types:
        return analyse_sql(expression), None
    if kind in plsql_types:
        return None, analyse_plsql(expression)
    return None, None
