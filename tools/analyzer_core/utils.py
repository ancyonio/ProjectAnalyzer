"""Small, dialect-agnostic helpers shared by every analyzer."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, List, Optional

_SPLIT_RE = re.compile(r'[^A-Za-z0-9]+')
_CAMEL_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def escape_cypher(value: str) -> str:
    """Escape a value for a single-quoted Cypher string literal."""
    if value is None:
        return ''
    return (str(value)
            .replace('\\', '\\\\')
            .replace("'", "\\'")
            .replace('\n', '\\n')
            .replace('\r', '')
            .replace('\t', ' '))


def sha1_16(text: str) -> str:
    """Stable 16-hex-char digest, used for content-addressed node ids."""
    return hashlib.sha1(text.encode('utf-8', 'replace')).hexdigest()[:16]


def sha1_full(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def rel_path(path: Path, root: Path) -> str:
    """Repo-relative, forward-slashed path. Falls back to the absolute path."""
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace('\\', '/')
    except (ValueError, OSError):
        return str(path).replace('\\', '/')


def read_text(path: Path, limit: int = 2_000_000) -> str:
    """Read a text file defensively: unknown encodings must not stop a parse."""
    try:
        data = Path(path).read_bytes()[:limit]
    except OSError:
        return ''
    for encoding in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode('utf-8', 'replace')


def tier_for(score: float, tiers: Iterable) -> str:
    """Map a numeric score onto a named tier using `(threshold, name)` pairs
    ordered from highest threshold down."""
    for threshold, name in tiers:
        if score >= threshold:
            return name
    return 'Low'


def split_identifier(text: str) -> List[str]:
    """`ORDER_PKG.createOrder` -> ['order', 'pkg', 'create', 'order']."""
    if not text:
        return []
    parts: List[str] = []
    for chunk in _SPLIT_RE.split(text):
        if not chunk:
            continue
        parts.extend(p.lower() for p in _CAMEL_RE.split(chunk) if p)
    return parts


def truncate(text: str, limit: int, suffix: str = ' …') -> str:
    if text is None:
        return ''
    text = str(text)
    return text if len(text) <= limit else text[:limit].rstrip() + suffix


def one_line(text: str, limit: int = 200) -> str:
    """Collapse to a single line for table cells and evidence snippets."""
    if not text:
        return ''
    return truncate(re.sub(r'\s+', ' ', str(text)).strip(), limit)


def md_table(headers: List[str], rows: List[List[Any]]) -> str:
    """Render a GitHub-flavoured Markdown table (empty rows produce a note)."""
    if not rows:
        return '_none_'
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        cells = ['' if c is None else str(c).replace('|', '\\|').replace('\n', ' ')
                 for c in row]
        out.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(out)


def pct(part: float, total: float, digits: int = 1) -> float:
    return round(part / total * 100, digits) if total else 0.0


def coalesce(*values: Optional[Any]) -> Any:
    for value in values:
        if value not in (None, ''):
            return value
    return ''
