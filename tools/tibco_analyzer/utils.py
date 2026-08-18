"""Low-level helpers shared by every parser and exporter."""
from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from .constants import XSD_JAVA_TYPE_MAP, COMPLEXITY_TIERS

logger = logging.getLogger('tibco_analyzer')

# ─────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────
def safe_text(elem, default: str = "") -> str:
    """Safely extract text from an XML element."""
    if elem is not None and elem.text:
        return elem.text.strip()
    return default


def escape_cypher(value: str) -> str:
    """Escape a string for safe Cypher literal embedding."""
    if not value:
        return ""
    return (str(value)
            .replace('\\', '\\\\')
            .replace("'", "\\'")
            .replace('\n', '\\n')
            .replace('\r', '\\r'))


def xsd_type_to_java(xsd_type: str) -> str:
    """Convert an XSD type name to its Java equivalent."""
    if not xsd_type:
        return 'Object'
    local = xsd_type.split(':')[-1] if ':' in xsd_type else xsd_type
    return XSD_JAVA_TYPE_MAP.get(local, 'Object')


def safe_parse_xml(file_path: Path) -> Optional[ET.Element]:
    """Parse an XML file with Windows long-path support."""
    try:
        fp = str(file_path)
        if os.name == 'nt' and not fp.startswith('\\\\?\\'):
            fp = '\\\\?\\' + fp
        tree = ET.parse(fp)
        return tree.getroot()
    except (ET.ParseError, FileNotFoundError, OSError, UnicodeDecodeError) as exc:
        logger.debug(f"XML parse skipped: {file_path.name} - {type(exc).__name__}")
        return None

def tier_for(score: float) -> str:
    """Map a numeric complexity score onto a migration tier."""
    for threshold, tier in COMPLEXITY_TIERS:
        if score > threshold:
            return tier
    return 'Low'


def localname(tag: str) -> str:
    """Strip the namespace from an ElementTree tag."""
    return tag.split('}')[-1] if '}' in tag else tag


def rel_path(path: Path, root: Path) -> str:
    """Return a POSIX-style path relative to the project root."""
    try:
        return str(path.relative_to(root)).replace('\\', '/')
    except ValueError:
        return str(path).replace('\\', '/')


_SPLIT_RE = re.compile(r'[^A-Za-z0-9]+')
_CAMEL_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')


def split_identifier(text: str) -> list:
    """Split an identifier into lowercase word tokens.

    'CreditScoreLookup_v2' -> ['credit', 'score', 'lookup', 'v2']
    Deterministic: no stemming, no model, same input always same output.
    """
    if not text:
        return []
    out = []
    for chunk in _SPLIT_RE.split(str(text)):
        if not chunk:
            continue
        for piece in _CAMEL_RE.split(chunk):
            if piece:
                out.append(piece.lower())
    return out


def element_text_blob(elem, limit: int = 4000) -> str:
    """Flatten an XML element's text and attribute values into one string."""
    parts = []
    for node in elem.iter():
        if node.text and node.text.strip():
            parts.append(node.text.strip())
        for value in node.attrib.values():
            if value and len(value) < 400:
                parts.append(value)
        if sum(len(p) for p in parts) > limit:
            break
    return ' '.join(parts)[:limit]


def read_text(path: Path, limit: int = 200_000) -> str:
    """Read a file defensively (encoding-tolerant, size-capped)."""
    try:
        return path.read_text(encoding='utf-8', errors='replace')[:limit]
    except OSError:
        return ''


# ─────────────────────────────────────────────────────────────
# Activity payload extraction
#
# The *behaviour* of an activity lives in its config: the SQL it runs, the
# queue it publishes to, the URI it exposes. BW5 and BW6 nest these under
# different elements, but the leaf tag names are largely shared, so the
# extractor matches on local name and ignores namespaces entirely.
# ─────────────────────────────────────────────────────────────

# property name -> lower-cased local tag names that carry it
ACTIVITY_DETAIL_TAGS = {
    'sqlStatement':    ('statement', 'sqlstatement', 'sql', 'query'),
    'jmsDestination':  ('permitteddest', 'destination', 'destinationname',
                        'queuename', 'topicname', 'jmsdestination'),
    'httpMethod':      ('method', 'httpmethod'),
    'endpointUri':     ('uri', 'requesturi', 'url', 'endpointuri', 'resourcepath'),
    'fileTarget':      ('filename', 'filepath', 'sourcefilename', 'targetfilename'),
    'logMessage':      ('message', 'logmessage'),
    'storedProcedure': ('procedurename', 'spname', 'procedure'),
    'mailTo':          ('to', 'sendto'),
    'javaClass':       ('classname', 'javaclass'),
}

_DETAIL_LOOKUP = {tag: prop
                  for prop, tags in ACTIVITY_DETAIL_TAGS.items()
                  for tag in tags}

_MAX_DETAIL = 400

# Table names in SQL: FROM x, JOIN x, INTO x, UPDATE x. Deliberately simple —
# it reports what the statement names, and is not a SQL parser.
_SQL_TABLE_RE = re.compile(
    r'\b(?:from|join|into|update)\s+([A-Za-z_][A-Za-z0-9_$#]*(?:\.[A-Za-z_][A-Za-z0-9_$#]*)*)',
    re.IGNORECASE)

_SQL_VERB_RE = re.compile(
    r'^\s*(select|insert|update|delete|merge|call|exec|execute|truncate)\b',
    re.IGNORECASE)


def sql_tables(statement: str) -> list:
    """Table names referenced by a SQL statement, sorted and de-duplicated."""
    if not statement:
        return []
    found = {m.group(1) for m in _SQL_TABLE_RE.finditer(statement)}
    # `from` also precedes sub-selects and aliases; drop obvious keywords.
    noise = {'select', 'where', 'set', 'values', 'dual'}
    return sorted(t for t in found if t.lower() not in noise)


def sql_verb(statement: str) -> str:
    """The leading verb of a SQL statement, upper-cased ('' when unknown)."""
    if not statement:
        return ''
    m = _SQL_VERB_RE.match(statement)
    return m.group(1).upper() if m else ''


def activity_details(element) -> dict:
    """Pull behavioural detail out of an activity's config subtree.

    Returns only the keys that were actually found, so callers can merge the
    result straight into node properties without emitting empty fields.
    Scans descendants by local name, so it works for BW5 `<config>` and BW6
    `bwext:BWActivity` configuration alike.
    """
    if element is None:
        return {}
    out = {}
    for node in element.iter():
        prop = _DETAIL_LOOKUP.get(localname(node.tag).lower())
        if not prop or prop in out:
            continue
        value = (node.text or '').strip()
        if not value:
            continue
        out[prop] = value[:_MAX_DETAIL]

    # Attribute-carried values: BW6 puts several of these on attributes.
    for node in element.iter():
        for attr, value in node.attrib.items():
            prop = _DETAIL_LOOKUP.get(localname(attr).lower())
            if prop and prop not in out and value.strip():
                out[prop] = value.strip()[:_MAX_DETAIL]

    if out.get('sqlStatement'):
        tables = sql_tables(out['sqlStatement'])
        if tables:
            out['sqlTables'] = ', '.join(tables)
        verb = sql_verb(out['sqlStatement'])
        if verb:
            out['sqlVerb'] = verb
    return out
