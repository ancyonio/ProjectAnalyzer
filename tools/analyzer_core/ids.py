"""Natural-key node identifiers.

Ids are derived from the identity the source system already gives an object
(application id + page id, owner + object name), never from a counter. That
is what makes two analyses of two releases comparable by set arithmetic, and
what makes a re-load into Neo4j idempotent.

Grammar:

    app100                      application
    app100:p10                  page
    app100:p10:r1001            region
    app100:p10:iP10_ORDER_ID    item
    db:ORDER_APP.ORDERS         database object
    db:ORDER_APP.ORDERS.ORD_ID  column
    sql:9f2c1a…                 content-addressed code node
    project:order_app           analysed project
    repo:order_app              source repository
"""
from __future__ import annotations

import re
from typing import Optional

from .utils import sha1_16

_SAFE = re.compile(r'[^A-Za-z0-9_.:#$/@-]+')


def db_ident(name: Optional[str]) -> str:
    """Normalise an Oracle identifier: unquote, trim, upper-case."""
    if not name:
        return ''
    value = str(name).strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value.upper()


def slug(text: str) -> str:
    """Lower-case, hyphenated token safe for an id segment."""
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', str(text or '').lower())).strip('-')


def clean(segment: str) -> str:
    return _SAFE.sub('_', str(segment or '').strip())


# ── APEX ──────────────────────────────────────────────────────────────────
def app_id(application_id) -> str:
    return f'app{application_id}'


def page_id(application_id, page) -> str:
    return f'{app_id(application_id)}:p{page}'


def component_id(application_id, page, prefix: str, component) -> str:
    """Page-scoped component: region `r`, item `i`, button `b`, process
    `proc`, validation `val`, branch `br`, computation `comp`, dynamic
    action `da`."""
    return f'{page_id(application_id, page)}:{prefix}{clean(component)}'

def da_action_id(application_id, page, da, action) -> str:
    return f'{component_id(application_id, page, "da", da)}:a{clean(action)}'


def report_column_id(application_id, page, region, column) -> str:
    return f'{component_id(application_id, page, "r", region)}:c{clean(db_ident(column))}'


def shared_id(application_id, kind: str, name: str) -> str:
    """Application-scoped shared component: `lov`, `auth`, `authn`, `list`,
    `bo`, `nav`, `ws`, `plugin`, `automation`, `proc`, `item`, `comp`."""
    return f'{app_id(application_id)}:{kind}:{clean(name)}'


# ── code ──────────────────────────────────────────────────────────────────
def sql_id(normalised_sql: str) -> str:
    return f'sql:{sha1_16(normalised_sql)}'


def plsql_id(normalised_code: str) -> str:
    return f'plsql:{sha1_16(normalised_code)}'


def js_id(code: str) -> str:
    return f'js:{sha1_16(code)}'


# ── database ──────────────────────────────────────────────────────────────
def schema_id(owner: str) -> str:
    return f'db:{db_ident(owner)}'


def object_id(owner: str, name: str) -> str:
    return f'db:{db_ident(owner)}.{db_ident(name)}'


def unit_id(owner: str, package: Optional[str], name: str, overload=None) -> str:
    parts = [db_ident(owner)]
    if package:
        parts.append(db_ident(package))
    parts.append(db_ident(name))
    base = f'db:{".".join(parts)}'
    return f'{base}#{overload}' if overload not in (None, '', 0, '0') else base


def column_id(owner: str, table: str, column: str) -> str:
    return f'db:{db_ident(owner)}.{db_ident(table)}.{db_ident(column)}'


def unresolved_id(raw: str) -> str:
    return f'unresolved:{db_ident(raw)}'


# ── repository / analysis ─────────────────────────────────────────────────
def project_id(name: str) -> str:
    """The analysed unit of work. One spelling, so a federated graph can tell
    two projects apart instead of tripping over `proj:` and `project:`."""
    return f'project:{clean(name)}'


def repository_id(name: str) -> str:
    return f'repo:{clean(name)}'


def file_id(relative_path: str) -> str:
    return f'file:{str(relative_path).replace(chr(92), "/")}'


def commit_id(sha: str) -> str:
    return f'commit:{str(sha)[:40]}'


def issue_id(rule_id: str, target_node_id: str) -> str:
    return f'issue:{rule_id}:{target_node_id}'


def recommendation_id(issue_node_id: str, ordinal: int = 1) -> str:
    return f'{issue_node_id}#rec{ordinal}'


def business_function_id(domain: str, name: str) -> str:
    return f'bf:{slug(domain)}:{slug(name)}'


def business_domain_id(name: str) -> str:
    return f'bd:{slug(name)}'
