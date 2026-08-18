"""SQL statement analysis.

Extracts, from one SQL statement, the facts the graph needs: which objects it
reads, which it writes and how, which columns and sequences it touches, which
APEX items it binds, and the shape metrics the rules engine scores.

Deliberately liberal on columns and strict on tables. A column candidate that
is not a real column of a table in scope is dropped by
`resolver.Resolver`, so over-collecting here costs nothing and under-collecting
loses lineage. Table references, by contrast, drive impact analysis, so they
are only taken from positions where a table can legally appear.

What this is not: a full Oracle grammar. Where a construct cannot be
understood the statement is marked `PARTIAL` or `FAILED` and that fact is
reported, never hidden.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .constants import (BIND_RE, ORACLE_BUILTIN_PACKAGES, SQL_PSEUDO_TABLES,
                        SQL_RESERVED, SUBSTITUTION_RE)
from .args import mask_literals

READ, INSERT, UPDATE, DELETE = 'READ', 'INSERT', 'UPDATE', 'DELETE'

_OBJECT = r'(?:"[^"]+"|[A-Za-z][A-Za-z0-9_$#]*)'
_QUALIFIED = rf'{_OBJECT}(?:\s*\.\s*{_OBJECT})?(?:@[A-Za-z0-9_$#.]+)?'

_FROM_RE = re.compile(r'\bFROM\b', re.IGNORECASE)
_JOIN_RE = re.compile(rf'\bJOIN\s+({_QUALIFIED})', re.IGNORECASE)
_INSERT_RE = re.compile(rf'\bINSERT\s+INTO\s+({_QUALIFIED})', re.IGNORECASE)
_UPDATE_RE = re.compile(rf'\bUPDATE\s+({_QUALIFIED})', re.IGNORECASE)
_DELETE_RE = re.compile(rf'\bDELETE\s+(?:FROM\s+)?({_QUALIFIED})', re.IGNORECASE)
_MERGE_RE = re.compile(rf'\bMERGE\s+INTO\s+({_QUALIFIED})', re.IGNORECASE)
_USING_RE = re.compile(rf'\bUSING\s+({_QUALIFIED})', re.IGNORECASE)
_WITH_CTE_RE = re.compile(rf'(?:\bWITH\b|,)\s*({_OBJECT})\s+AS\s*\(', re.IGNORECASE)
_SEQ_RE = re.compile(rf'({_QUALIFIED})\s*\.\s*(NEXTVAL|CURRVAL)\b', re.IGNORECASE)
_CALL_RE = re.compile(rf'\b({_OBJECT})\s*\.\s*({_OBJECT})\s*\(', re.IGNORECASE)
_QUALIFIED_COL_RE = re.compile(rf'\b({_OBJECT})\s*\.\s*({_OBJECT})\b(?!\s*[.(])')
_IDENT_RE = re.compile(r'\b([A-Za-z][A-Za-z0-9_$#]*)\b')
_SELECT_STAR_RE = re.compile(r'(?:\bSELECT\s+(?:DISTINCT\s+|ALL\s+)?\*)|(?:\b\w+\.\*)',
                             re.IGNORECASE)
_CLAUSE_END_RE = re.compile(
    r'\b(WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|CONNECT\s+BY|START\s+WITH|UNION|'
    r'MINUS|INTERSECT|MODEL|FETCH|OFFSET|FOR\s+UPDATE|RETURNING|SET|WHEN|USING|'
    r'INNER\s+JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|FULL\s+JOIN|CROSS\s+JOIN|JOIN|ON)\b',
    re.IGNORECASE)
_VERB_RE = re.compile(
    r'^\s*(?:\(\s*)*(WITH|SELECT|INSERT|UPDATE|DELETE|MERGE|BEGIN|DECLARE|'
    r'CREATE|ALTER|DROP|TRUNCATE|GRANT|COMMENT|CALL)\b', re.IGNORECASE)


@dataclass
class TableRef:
    """A table-shaped name found in a position where a table can appear."""
    owner: str
    name: str
    access: str
    alias: str = ''
    db_link: str = ''

    @property
    def key(self) -> Tuple[str, str, str]:
        return (self.owner.upper(), self.name.upper(), self.access)


@dataclass
class SqlAnalysis:
    text: str
    verb: str = ''
    tables: List[TableRef] = field(default_factory=list)
    columns: List[Tuple[str, str]] = field(default_factory=list)   # (alias|'', column)
    sequences: List[Tuple[str, str]] = field(default_factory=list)  # (owner|'', name)
    calls: List[Tuple[str, str]] = field(default_factory=list)      # (package|'', name)
    binds: List[str] = field(default_factory=list)
    substitutions: List[str] = field(default_factory=list)
    alias_map: Dict[str, str] = field(default_factory=dict)
    cte_names: Set[str] = field(default_factory=set)
    has_select_star: bool = False
    has_hint: bool = False
    has_db_link: bool = False
    is_dynamic: bool = False
    join_count: int = 0
    line_count: int = 0
    parse_status: str = 'PARSED'

    @property
    def table_count(self) -> int:
        return len({(t.owner.upper(), t.name.upper()) for t in self.tables})

    @property
    def bind_count(self) -> int:
        return len(set(self.binds) | set(self.substitutions))

    def writes(self) -> List[TableRef]:
        return [t for t in self.tables if t.access != READ]

    def properties(self) -> Dict[str, object]:
        return {
            'verb': self.verb or 'UNKNOWN',
            'lineCount': self.line_count,
            'tableCount': self.table_count,
            'joinCount': self.join_count,
            'bindCount': self.bind_count,
            'hasSelectStar': self.has_select_star,
            'hasHint': self.has_hint,
            'hasDbLink': self.has_db_link,
            'isDynamic': self.is_dynamic,
            'parseStatus': self.parse_status,
        }


def strip_comments(text: str) -> str:
    """Remove `--` and block comments, leaving string literals untouched."""
    out: List[str] = []
    i, n = 0, len(text or '')
    while i < n:
        ch = text[i]
        if ch == '-' and text.startswith('--', i):
            while i < n and text[i] != '\n':
                i += 1
            continue
        if ch == '/' and text.startswith('/*', i):
            end = text.find('*/', i + 2)
            i = n if end == -1 else end + 2
            out.append(' ')
            continue
        if ch == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def normalise_sql(text: str) -> str:
    """Whitespace- and case-normalised form used for the content hash, so two
    components running the same query converge on one `:SqlStatement`."""
    return re.sub(r'\s+', ' ', strip_comments(text or '')).strip().rstrip(';').lower()


def split_object(token: str) -> Tuple[str, str, str]:
    """`ORDER_APP.ORDERS@LINK` -> ('ORDER_APP', 'ORDERS', 'LINK')."""
    token = token.strip()
    db_link = ''
    if '@' in token:
        token, _, db_link = token.partition('@')
    parts = [p.strip().strip('"') for p in token.split('.') if p.strip()]
    if len(parts) >= 2:
        return parts[-2].upper(), parts[-1].upper(), db_link.upper()
    return '', (parts[0].upper() if parts else ''), db_link.upper()


def _clause_span(masked: str, start: int) -> Tuple[int, int]:
    """Span of the FROM clause beginning at `start`, ending at the next
    top-level clause keyword or closing bracket."""
    depth = 0
    i = start
    while i < len(masked):
        ch = masked[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth == 0:
                return start, i
            depth -= 1
        elif depth == 0:
            match = _CLAUSE_END_RE.match(masked, i)
            if match:
                return start, i
        i += 1
    return start, len(masked)


def analyse_sql(text: str, default_access: str = READ) -> SqlAnalysis:
    """Analyse one SQL statement (or an expression containing one)."""
    result = SqlAnalysis(text=text or '')
    if not text or not text.strip():
        result.parse_status = 'FAILED'
        return result

    result.line_count = text.count('\n') + 1
    result.has_hint = '/*+' in text
    masked = mask_literals(text)

    verb_match = _VERB_RE.match(masked)
    result.verb = (verb_match.group(1).upper() if verb_match else '')
    if result.verb == 'WITH':
        result.verb = 'SELECT'
    if result.verb in ('BEGIN', 'DECLARE', 'CALL'):
        result.verb = 'ANONYMOUS'
    if result.verb in ('CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'GRANT', 'COMMENT'):
        result.verb = 'DDL'

    result.cte_names = {m.group(1).strip('"').upper() for m in _WITH_CTE_RE.finditer(masked)}
    result.has_select_star = bool(_SELECT_STAR_RE.search(masked))
    result.join_count = len(_JOIN_RE.findall(masked))

    seen: Set[Tuple[str, str, str]] = set()

    def add_table(token: str, access: str, alias: str = '') -> None:
        owner, name, db_link = split_object(token)
        if not name or name.upper() in SQL_PSEUDO_TABLES or name.upper() in SQL_RESERVED:
            return
        if not owner and name.upper() in result.cte_names:
            return
        ref = TableRef(owner=owner, name=name, access=access, alias=alias.upper(),
                       db_link=db_link)
        if db_link:
            result.has_db_link = True
        if ref.key in seen:
            return
        seen.add(ref.key)
        result.tables.append(ref)
        if alias:
            result.alias_map[alias.upper()] = name.upper()
        result.alias_map.setdefault(name.upper(), name.upper())

    # write positions ---------------------------------------------------
    for match in _INSERT_RE.finditer(masked):
        add_table(match.group(1), INSERT)
    for match in _UPDATE_RE.finditer(masked):
        add_table(match.group(1), UPDATE)
    for match in _MERGE_RE.finditer(masked):
        add_table(match.group(1), UPDATE)
    if result.verb == 'DELETE':
        for match in _DELETE_RE.finditer(masked):
            add_table(match.group(1), DELETE)

    # read positions ----------------------------------------------------
    for match in _JOIN_RE.finditer(masked):
        add_table(match.group(1), READ)
    for match in _USING_RE.finditer(masked):
        token = match.group(1).strip()
        if not token.startswith('('):
            add_table(token, READ)

    for from_match in _FROM_RE.finditer(masked):
        if result.verb == 'DELETE' and from_match.start() < 20:
            continue                     # already captured as the delete target
        start, end = _clause_span(masked, from_match.end())
        clause = masked[start:end]
        items = _split_commas(clause)
        result.join_count += max(0, len([i for i in items if i.strip()]) - 1)
        for item in items:
            item = item.strip()
            if not item or item.startswith('('):
                continue
            tokens = re.split(r'\s+', item)
            table_token = tokens[0]
            alias = ''
            if len(tokens) > 1:
                candidate = tokens[1].upper()
                if candidate == 'AS' and len(tokens) > 2:
                    alias = tokens[2]
                elif candidate not in SQL_RESERVED:
                    alias = tokens[1]
            add_table(table_token, default_access if result.verb == 'DELETE' else READ,
                      alias.strip('"'))

    # sequences, calls, binds ------------------------------------------
    for match in _SEQ_RE.finditer(masked):
        owner, name, _ = split_object(match.group(1))
        result.sequences.append((owner, name))

    table_keys = {(t.owner.upper(), t.name.upper()) for t in result.tables}
    bare_tables = {t.name.upper() for t in result.tables}
    for match in _CALL_RE.finditer(masked):
        package = match.group(1).strip('"').upper()
        name = match.group(2).strip('"').upper()
        if package in result.alias_map or package in SQL_RESERVED:
            continue
        if package in ORACLE_BUILTIN_PACKAGES:
            continue
        if name in ('NEXTVAL', 'CURRVAL'):
            continue
        # `insert into owner.table (col, …)` looks exactly like a call
        if (package, name) in table_keys or name in bare_tables:
            continue
        result.calls.append((package, name))

    result.binds = sorted({m.group(1).upper() for m in BIND_RE.finditer(masked)})
    result.substitutions = sorted({m.group(1).upper()
                                   for m in SUBSTITUTION_RE.finditer(masked)})

    # column candidates -------------------------------------------------
    result.columns = _column_candidates(masked, result)

    if not result.verb:
        result.parse_status = 'FAILED'
    elif result.verb not in ('DDL', 'ANONYMOUS') and not result.tables:
        result.parse_status = 'PARTIAL'
    return result


def _split_commas(clause: str) -> List[str]:
    out, depth, start = [], 0, 0
    for i, ch in enumerate(clause):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            out.append(clause[start:i])
            start = i + 1
    out.append(clause[start:])
    return out


def _column_candidates(masked: str, result: SqlAnalysis) -> List[Tuple[str, str]]:
    """Qualified `alias.column` refs, plus bare identifiers when a single table
    is in scope. The resolver drops anything that is not a real column."""
    candidates: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()

    for match in _QUALIFIED_COL_RE.finditer(masked):
        qualifier = match.group(1).strip('"').upper()
        column = match.group(2).strip('"').upper()
        if qualifier in SQL_RESERVED or column in SQL_RESERVED:
            continue
        if column in ('NEXTVAL', 'CURRVAL'):
            continue
        if (qualifier, column) not in seen:
            seen.add((qualifier, column))
            candidates.append((qualifier, column))

    if len({(t.owner, t.name) for t in result.tables}) == 1:
        for match in _IDENT_RE.finditer(masked):
            word = match.group(1).upper()
            if word in SQL_RESERVED or word in result.alias_map:
                continue
            after = masked[match.end():match.end() + 1]
            before = masked[max(0, match.start() - 1):match.start()]
            if after == '(' or before == '.' or after == '.':
                continue
            if ('', word) not in seen:
                seen.add(('', word))
                candidates.append(('', word))
    return candidates
