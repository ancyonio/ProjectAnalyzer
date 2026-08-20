"""DDL script parsing.

Most APEX repositories commit their schema alongside the application export:
`create table`, `create or replace package body`, view and trigger scripts.
Parsing those gives the database layer — tables, columns, program units,
foreign keys — without needing a live database connection, which matters
because the dictionary extract usually needs an approval the analysis does
not want to wait for.

Where a dictionary extract *is* available it wins: it is authoritative, and
these results are merged underneath it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .args import mask_literals
from .sqlparse import split_object, strip_comments

_CREATE_TABLE_RE = re.compile(
    r'\bcreate\s+(?:global\s+temporary\s+)?table\s+([\w$#."]+)\s*\(', re.IGNORECASE)
_CREATE_VIEW_RE = re.compile(
    r'\bcreate\s+(?:or\s+replace\s+)?(?:(?:force|no\s*force)\s+)?'
    r'(materialized\s+)?view\s+([\w$#."]+)(?:\s*\([^)]*\))?\s+as\b', re.IGNORECASE)
_CREATE_PACKAGE_RE = re.compile(
    r'\bcreate\s+(?:or\s+replace\s+)?(?:editionable\s+)?package\s+(body\s+)?([\w$#."]+)',
    re.IGNORECASE)
_CREATE_UNIT_RE = re.compile(
    r'\bcreate\s+(?:or\s+replace\s+)?(?:editionable\s+)?(procedure|function)\s+([\w$#."]+)',
    re.IGNORECASE)
# `create type` was previously unparsed, so a `DbType` node could only ever
# arrive from a dictionary extract and a repository-only analysis had nothing
# for `USES_TYPE` to bind to.
_CREATE_TYPE_RE = re.compile(
    r'\bcreate\s+(?:or\s+replace\s+)?(?:editionable\s+)?type\s+(body\s+)?'
    r'([\w$#."]+)', re.IGNORECASE)
_TYPE_CATEGORY_RE = re.compile(
    r'\bas\s+(object|table\s+of|varray\s*\([^)]*\)\s*of|record)\b',
    re.IGNORECASE)
_CREATE_TRIGGER_RE = re.compile(
    r'\bcreate\s+(?:or\s+replace\s+)?trigger\s+([\w$#."]+)(.*?)\bon\s+([\w$#."]+)',
    re.IGNORECASE | re.DOTALL)
_CREATE_SEQUENCE_RE = re.compile(r'\bcreate\s+sequence\s+([\w$#."]+)', re.IGNORECASE)
_CREATE_SYNONYM_RE = re.compile(
    r'\bcreate\s+(?:or\s+replace\s+)?(public\s+)?synonym\s+([\w$#."]+)\s+for\s+([\w$#."@]+)',
    re.IGNORECASE)
_CREATE_INDEX_RE = re.compile(
    r'\bcreate\s+(unique\s+)?index\s+([\w$#."]+)\s+on\s+([\w$#."]+)\s*\(([^)]*)\)',
    re.IGNORECASE)
_ALTER_ADD_CONSTRAINT_RE = re.compile(
    r'\balter\s+table\s+([\w$#."]+)\s+add\s+(?:constraint\s+([\w$#."]+)\s+)?'
    r'(primary\s+key|unique|foreign\s+key)\s*\(([^)]*)\)'
    r'(?:\s*references\s+([\w$#."]+)\s*\(([^)]*)\))?', re.IGNORECASE)
_UNIT_IN_BODY_RE = re.compile(
    r'\b(procedure|function)\s+("?[\w$#]+"?)\s*(\(|\bis\b|\bas\b|\breturn\b)',
    re.IGNORECASE)
# A spec may declare a parameterless unit as `PROCEDURE PURGE_OLD_LOGS;`,
# which the body pattern above deliberately does not match: inside a body
# that form is a forward declaration, and treating it as a unit would split
# the body at the wrong place. Specs get their own, looser pattern.
_UNIT_DECL_RE = re.compile(
    r'\b(procedure|function)\s+("?[\w$#]+"?)\s*(\(|\bis\b|\bas\b|\breturn\b|;)',
    re.IGNORECASE)
_COLUMN_RE = re.compile(
    r'^\s*("?[A-Za-z][\w$#]*"?)\s+([A-Za-z][\w ]*(?:\([^)]*\))?)', re.IGNORECASE)
_INLINE_FK_RE = re.compile(r'\breferences\s+([\w$#."]+)\s*\(([^)]*)\)', re.IGNORECASE)
_CONSTRAINT_LINE_RE = re.compile(
    r'^\s*(?:constraint\s+("?[\w$#]+"?)\s+)?(primary\s+key|unique|foreign\s+key|check)\b',
    re.IGNORECASE)


@dataclass
class DdlColumn:
    name: str
    data_type: str
    nullable: bool = True
    is_pk: bool = False
    is_fk: bool = False
    position: int = 0


@dataclass
class DdlObject:
    owner: str
    name: str
    kind: str                      # TABLE | VIEW | MVIEW | PACKAGE | UNIT | TRIGGER …
    columns: List[DdlColumn] = field(default_factory=list)
    units: List[Tuple[str, str]] = field(default_factory=list)   # (kind, name)
    query: str = ''
    body: str = ''
    base_object: str = ''
    target: str = ''
    triggering_event: str = ''
    source_file: str = ''
    source_line: int = 0
    # The last line of the statement that produced this object. Without it a
    # finding can say where an object starts but not how far it reaches, which
    # is the difference between "look here" and "read this file".
    source_line_end: int = 0
    foreign_keys: List[Tuple[str, str, str]] = field(default_factory=list)
    # (constraint name, referenced object, columns)


@dataclass
class DdlResult:
    objects: List[DdlObject] = field(default_factory=list)
    statements_seen: int = 0
    unparsed: int = 0


def split_statements(text: str) -> List[Tuple[int, str]]:
    """Split a DDL script into statements, keeping PL/SQL bodies whole.

    Returns (line number, statement) pairs.
    """
    cleaned = strip_comments(text or '')
    chunks: List[Tuple[int, str]] = []
    line = 1
    buffer: List[str] = []
    buffer_line = 1
    in_plsql = False
    depth = 0

    # Decisions are made on the comment-stripped text, but the statement kept
    # is the original: an optimizer hint lives in a `/*+ ... */` comment, and
    # stripping it before the statement is stored loses the one thing a
    # performance rule needs to see. `strip_comments` preserves line count, so
    # the two views stay aligned; if they ever do not, fall back to the
    # stripped text rather than mis-pairing lines.
    cleaned_lines = cleaned.splitlines(keepends=True)
    original_lines = (text or '').splitlines(keepends=True)
    if len(cleaned_lines) != len(original_lines):
        original_lines = cleaned_lines

    for raw_line, original_line in zip(cleaned_lines, original_lines):
        stripped = raw_line.strip()
        if not buffer and not stripped:
            # a blank line between statements must not start one, or the
            # `create or replace package` on the next line is never seen as
            # PL/SQL and the body gets split at its first semicolon
            line += 1
            continue
        if not buffer:
            buffer_line = line
            head = stripped.lower()
            in_plsql = bool(re.match(
                r'create\s+(or\s+replace\s+)?(editionable\s+)?'
                r'(package|procedure|function|trigger|type)\b', head)) or \
                head.startswith(('declare', 'begin'))
            depth = 0
        if stripped == '/':
            if buffer:
                chunks.append((buffer_line, ''.join(buffer)))
                buffer = []
            line += 1
            continue
        buffer.append(original_line)
        if not in_plsql:
            masked = mask_literals(raw_line)
            depth += masked.count('(') - masked.count(')')
            if ';' in masked and depth <= 0:
                statement = ''.join(buffer)
                chunks.append((buffer_line, statement))
                buffer = []
        line += 1

    if buffer and ''.join(buffer).strip():
        chunks.append((buffer_line, ''.join(buffer)))
    return [(number, statement) for number, statement in chunks if statement.strip()]


def parse_ddl(text: str, default_owner: str = '', source_file: str = '') -> DdlResult:
    """Parse a DDL script into database objects."""
    result = DdlResult()
    for line_number, statement in split_statements(text):
        result.statements_seen += 1
        obj = _parse_statement(statement, default_owner)
        if obj is None:
            result.unparsed += 1
            continue
        line_end = line_number + statement.count('\n')
        for parsed in (obj if isinstance(obj, list) else [obj]):
            parsed.source_file = source_file
            parsed.source_line = line_number
            parsed.source_line_end = line_end
            result.objects.append(parsed)
    return result


def _parse_statement(statement: str, default_owner: str):
    masked = mask_literals(statement)

    match = _CREATE_TABLE_RE.search(masked)
    if match:
        return _parse_table(statement, masked, match, default_owner)

    match = _CREATE_VIEW_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(2))
        return DdlObject(owner or default_owner, name,
                         'MVIEW' if match.group(1) else 'VIEW',
                         query=statement[match.end():].strip().rstrip(';/ \n'))

    match = _CREATE_PACKAGE_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(2))
        is_body = bool(match.group(1))
        # Declaration order is kept and duplicates are NOT removed: two
        # entries with the same name are overloads, and collapsing them makes
        # every overload after the first invisible to the caller.
        pattern = _UNIT_IN_BODY_RE if is_body else _UNIT_DECL_RE
        units = [(kind.upper(), unit.strip('"').upper())
                 for kind, unit, _ in pattern.findall(masked[match.end():])]
        return DdlObject(owner or default_owner, name, 'PACKAGE',
                         units=units,
                         body=statement if is_body else '')

    match = _CREATE_UNIT_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(2))
        return DdlObject(owner or default_owner, name, 'UNIT',
                         units=[(match.group(1).upper(), name)], body=statement)

    match = _CREATE_TYPE_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(2))
        category = _TYPE_CATEGORY_RE.search(masked[match.end():])
        obj = DdlObject(owner or default_owner, name, 'TYPE',
                        body=statement if match.group(1) else '')
        # The spec declares the shape; the body implements its methods. Both
        # are the same type, so they converge on one node rather than two.
        obj.query = (re.sub(r'\s+', ' ', category.group(1)).upper()
                     if category else ('BODY' if match.group(1) else ''))
        return obj

    match = _CREATE_TRIGGER_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(1))
        base_owner, base_name, _ = split_object(match.group(3))
        event = ' '.join(re.findall(r'\b(before|after|instead\s+of|insert|update|delete)\b',
                                    match.group(2), re.IGNORECASE)).upper()
        return DdlObject(owner or default_owner, name, 'TRIGGER',
                         base_object=f'{base_owner or default_owner}.{base_name}',
                         triggering_event=event, body=statement)

    match = _CREATE_SEQUENCE_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(1))
        return DdlObject(owner or default_owner, name, 'SEQUENCE')

    match = _CREATE_SYNONYM_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(2))
        target_owner, target_name, _ = split_object(match.group(3))
        return DdlObject('PUBLIC' if match.group(1) else (owner or default_owner), name,
                         'SYNONYM', target=f'{target_owner or default_owner}.{target_name}')

    match = _CREATE_INDEX_RE.search(masked)
    if match:
        owner, name, _ = split_object(match.group(2))
        base_owner, base_name, _ = split_object(match.group(3))
        obj = DdlObject(owner or default_owner, name, 'INDEX',
                        base_object=f'{base_owner or default_owner}.{base_name}')
        obj.query = 'UNIQUE' if match.group(1) else 'NONUNIQUE'
        obj.columns = [DdlColumn(c.strip().strip('"').upper(), '')
                       for c in match.group(4).split(',') if c.strip()]
        return obj

    match = _ALTER_ADD_CONSTRAINT_RE.search(masked)
    if match:
        table_owner, table_name, _ = split_object(match.group(1))
        constraint = (match.group(2) or f'{table_name}_{match.group(3)}').strip('"').upper()
        kind = re.sub(r'\s+', '_', match.group(3).upper())
        obj = DdlObject(table_owner or default_owner, constraint, 'CONSTRAINT',
                        base_object=f'{table_owner or default_owner}.{table_name}')
        obj.query = kind
        obj.columns = [DdlColumn(c.strip().strip('"').upper(), '')
                       for c in match.group(4).split(',') if c.strip()]
        if match.group(5):
            ref_owner, ref_name, _ = split_object(match.group(5))
            obj.target = f'{ref_owner or default_owner}.{ref_name}'
        return obj
    return None


def _parse_table(statement: str, masked: str, match, default_owner: str) -> DdlObject:
    owner, name, _ = split_object(match.group(1))
    table = DdlObject(owner or default_owner, name, 'TABLE')

    start = match.end()
    depth, end = 1, len(statement)
    for i in range(start, len(masked)):
        if masked[i] == '(':
            depth += 1
        elif masked[i] == ')':
            depth -= 1
            if depth == 0:
                end = i
                break
    body = statement[start:end]
    body_masked = masked[start:end]

    position = 0
    for span_start, span_end in _split_top_level(body_masked):
        item = body[span_start:span_end].strip()
        if not item:
            continue
        constraint = _CONSTRAINT_LINE_RE.match(item)
        if constraint:
            kind = re.sub(r'\s+', '_', constraint.group(2).upper())
            columns = re.search(r'\(([^)]*)\)', item)
            names = [c.strip().strip('"').upper()
                     for c in (columns.group(1).split(',') if columns else [])]
            if kind == 'PRIMARY_KEY':
                for column in table.columns:
                    if column.name in names:
                        column.is_pk = True
            elif kind == 'FOREIGN_KEY':
                reference = _INLINE_FK_RE.search(item)
                if reference:
                    ref_owner, ref_name, _ = split_object(reference.group(1))
                    table.foreign_keys.append((
                        (constraint.group(1) or f'{name}_FK').strip('"').upper(),
                        f'{ref_owner or table.owner}.{ref_name}', ','.join(names)))
                for column in table.columns:
                    if column.name in names:
                        column.is_fk = True
            continue

        column_match = _COLUMN_RE.match(item)
        if not column_match:
            continue
        position += 1
        column = DdlColumn(column_match.group(1).strip('"').upper(),
                           re.sub(r'\s+', ' ', column_match.group(2).strip()).upper(),
                           position=position)
        upper_item = item.upper()
        column.nullable = 'NOT NULL' not in upper_item
        column.is_pk = 'PRIMARY KEY' in upper_item
        reference = _INLINE_FK_RE.search(item)
        if reference:
            column.is_fk = True
            ref_owner, ref_name, _ = split_object(reference.group(1))
            table.foreign_keys.append((f'{name}_{column.name}_FK',
                                       f'{ref_owner or table.owner}.{ref_name}',
                                       column.name))
        table.columns.append(column)
    return table


def _split_top_level(masked: str) -> List[Tuple[int, int]]:
    spans, depth, start = [], 0, 0
    for i, ch in enumerate(masked):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            spans.append((start, i))
            start = i + 1
    spans.append((start, len(masked)))
    return spans


def extract_unit_bodies(body: str) -> List[Tuple[str, str, str, int]]:
    """Split a package body into (kind, name, source, line offset) tuples.

    The offset is the unit's first line counted from the start of the body, so
    a caller that knows where the body begins can give every unit its own line
    range instead of stamping all of them with the package's.
    """
    body = body or ''
    masked = mask_literals(body)
    matches = list(_UNIT_IN_BODY_RE.finditer(masked))
    out: List[Tuple[str, str, str, int]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((match.group(1).upper(), match.group(2).strip('"').upper(),
                    body[match.start():end], body.count('\n', 0, match.start())))
    return out
