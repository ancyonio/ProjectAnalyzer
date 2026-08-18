"""Cross-estate linking: the TIBCO leg of the join.

APEX and Oracle need no matcher -- they already share `analyzer_core.ids`, so
`db:ORDER_APP.ORDERS` is one node the moment both graphs are unioned. TIBCO
shares no ids with either, so its edges to the database estate are *inferred*,
and every one of them carries `origin`, `confidence` and `basis`.

The ladder is deliberately short (spec section 4):

    declared        the operator mapped this JDBC resource to a schema
    qualified-name  owner.name matched, the owner coming from the SQL itself
                    or from the mapped datasource
    name            a bare table name matched exactly one object in one schema

`name` is suppressed unless the operator opts in, and a bare name matching two
schemas is rejected whatever the flag says. Everything rejected is reported:
an unbound activity is a coverage figure, not a silence.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from analyzer_core.ids import db_ident
from analyzer_core.model import Graph, GraphNode

from .constants import (CONFIDENCE, DEFAULT_ALLOWED_BASES, JDBC_CATEGORIES,
                        READ_VERBS, WRITE_VERBS)
from .federate import Federation

logger = logging.getLogger('estate_analyzer')

# Objects a SQL statement can legitimately name.
LINKABLE_LABELS = ('DbTable', 'DbView', 'DbMaterializedView', 'DbSynonym')

JDBC_RESOURCE_TYPES = ('JDBC_CONNECTION',)

_MAX_EVIDENCE = 200


# ──────────────────────────────────────────────────────────────
def _object_index(graph: Graph) -> Tuple[Dict[str, GraphNode], Dict[str, List[GraphNode]]]:
    """Database objects by `OWNER.NAME` and by bare `NAME`."""
    qualified: Dict[str, GraphNode] = {}
    bare: Dict[str, List[GraphNode]] = {}
    for label in LINKABLE_LABELS:
        for node in graph.by_label(label):
            owner = db_ident(node.properties.get('owner', ''))
            name = db_ident(node.name)
            if owner:
                qualified.setdefault(f'{owner}.{name}', node)
            bare.setdefault(name, []).append(node)
    return qualified, bare


def _jdbc_resources(graph: Graph) -> List[GraphNode]:
    return [node for node in graph.by_label('SharedResource')
            if node.properties.get('resourceType') in JDBC_RESOURCE_TYPES]


def _map_datasources(graph: Graph, estate_map: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Resolve every JDBC shared resource against the operator's estate map.

    Matching is on the resource's qualified name, its bare name, or a
    substring of its JDBC url -- in that order, because the first two are
    exact and the third exists only for estates that name resources
    inconsistently.
    """
    entries = list(estate_map.get('datasources') or [])
    resolved: Dict[str, Dict[str, Any]] = {}

    for resource in _jdbc_resources(graph):
        qualified = str(resource.properties.get('qualifiedName', '') or '')
        url = str(resource.properties.get('url', '') or '')
        record: Dict[str, Any] = {
            'nodeId': resource.node_id,
            'name': resource.name,
            'qualifiedName': qualified,
            'url': url,
            'module': str(resource.properties.get('module', '') or ''),
            'schema': '',
            'mapped': False,
            'matchedOn': '',
            'note': '',
        }
        for entry in entries:
            declared = str(entry.get('resource', '') or '')
            contains = str(entry.get('resourceUrlContains', '') or '')
            if declared and declared in (qualified, resource.name):
                record.update(schema=db_ident(entry.get('schema')), mapped=True,
                              matchedOn='resource', note=str(entry.get('note', '') or ''))
                break
            if contains and url and contains in url:
                record.update(schema=db_ident(entry.get('schema')), mapped=True,
                              matchedOn='resourceUrlContains',
                              note=str(entry.get('note', '') or ''))
                break
        resolved[resource.node_id] = record
    return resolved


def _resource_of(graph: Graph, activity: GraphNode) -> Optional[str]:
    """Which JDBC resource an activity runs against.

    BW6 names the resource on the activity; BW5 does not, and the binding is
    only visible as the owning process's REFERENCES edge. Both paths are
    needed, and a process referencing two JDBC resources is deliberately
    treated as unresolved rather than guessed.
    """
    declared = str(activity.properties.get('sharedResources', '') or '')
    if declared:
        for node in _jdbc_resources(graph):
            if declared in (node.properties.get('qualifiedName', ''), node.name):
                return node.node_id

    jdbc_ids = {node.node_id for node in _jdbc_resources(graph)}
    for rel in graph.incoming(activity.node_id):
        if rel.rel_type != 'EXECUTES':
            continue
        candidates = [r.end_id for r in graph.outgoing(rel.start_id)
                      if r.rel_type == 'REFERENCES' and r.end_id in jdbc_ids]
        if len(candidates) == 1:
            return candidates[0]
    return None


def _verb_rels(verb: str) -> List[str]:
    """Edge types for a SQL verb: the precise one, plus the WRITES_TO roll-up."""
    verb = (verb or '').upper()
    if verb in WRITE_VERBS:
        return [WRITE_VERBS[verb], 'WRITES_TO']
    if verb in READ_VERBS:
        return ['READS_FROM']
    return ['READS_FROM'] if verb else []


def _split_tables(raw: str) -> List[str]:
    return [part.strip() for part in str(raw or '').split(',') if part.strip()]


# ──────────────────────────────────────────────────────────────
def link_estates(graph: Graph, federation: Federation, estate_map: Dict[str, Any],
                 allow_name_match: bool = False) -> Dict[str, Any]:
    """Add the cross-estate edges and report everything that did not link."""
    allowed = set(DEFAULT_ALLOWED_BASES) | ({'name'} if allow_name_match else set())
    qualified_index, bare_index = _object_index(graph)
    datasources = _map_datasources(graph, estate_map)

    links: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []
    unbound: List[Dict[str, Any]] = []

    # ── datasource → schema, where the operator declared it ──────────
    for record in datasources.values():
        if not record['mapped']:
            continue
        schema_id = f"db:{record['schema']}"
        if schema_id not in graph.nodes:
            record['mapped'] = False
            record['note'] = (f"declared schema {record['schema']} is not in any "
                              f'database estate')
            continue
        added = federation.add_rel(record['nodeId'], schema_id, 'CONNECTS_TO_SCHEMA', {
            'origin': 'declared', 'basis': 'declared',
            'confidence': CONFIDENCE['declared'],
            'evidence': record['url'] or record['qualifiedName'] or record['name'],
            'purpose': 'datasource-mapping',
        })
        if added:
            links.append({
                'fromId': record['nodeId'], 'fromLabel': 'SharedResource',
                'fromName': record['name'], 'relType': 'CONNECTS_TO_SCHEMA',
                'toId': schema_id, 'toLabel': 'DbSchema', 'toName': record['schema'],
                'basis': 'declared', 'confidence': CONFIDENCE['declared'],
                'evidence': record['url'],
            })

    # ── TIBCO activity → database object ─────────────────────────────
    for activity in graph.by_label('Activity'):
        if activity.properties.get('category') not in JDBC_CATEGORIES:
            continue

        statement = str(activity.properties.get('sqlStatement', '') or '')
        resource_id = _resource_of(graph, activity)
        record = datasources.get(resource_id or '', {})
        mapped_owner = record.get('schema', '') if record.get('mapped') else ''

        if not statement:
            unbound.append({
                'activityId': activity.node_id, 'activity': activity.name,
                'module': str(activity.properties.get('module', '') or ''),
                'reason': 'no-static-sql',
                'detail': 'the activity builds its statement at runtime, so its '
                          'dependencies are invisible to static analysis',
                'resource': record.get('name', ''),
            })
            continue

        tables = _split_tables(activity.properties.get('sqlTables', ''))
        if not tables:
            unbound.append({
                'activityId': activity.node_id, 'activity': activity.name,
                'module': str(activity.properties.get('module', '') or ''),
                'reason': 'no-table-extracted',
                'detail': 'the statement parsed but named no table this analysis '
                          'could extract',
                'resource': record.get('name', ''),
            })
            continue

        verb_rels = _verb_rels(str(activity.properties.get('sqlVerb', '') or ''))
        for raw in tables:
            target, basis, detail = _resolve_table(raw, mapped_owner,
                                                   qualified_index, bare_index)
            if target is None:
                unbound.append({
                    'activityId': activity.node_id, 'activity': activity.name,
                    'module': str(activity.properties.get('module', '') or ''),
                    'table': raw, 'reason': detail,
                    'detail': _unbound_detail(detail, raw, mapped_owner,
                                              record.get('name', '')),
                    'resource': record.get('name', ''),
                })
                continue

            row_base = {
                'fromId': activity.node_id, 'fromLabel': 'Activity',
                'fromName': activity.name, 'toId': target.node_id,
                'toLabel': target.label, 'toName': target.name,
                'basis': basis, 'confidence': CONFIDENCE[basis],
                'evidence': statement[:_MAX_EVIDENCE],
                'module': str(activity.properties.get('module', '') or ''),
                'resource': record.get('name', ''),
            }
            if basis not in allowed:
                for rel_type in verb_rels:
                    suppressed.append(dict(row_base, relType=rel_type,
                                           reason='basis-suppressed'))
                continue
            for rel_type in verb_rels:
                added = federation.add_rel(activity.node_id, target.node_id, rel_type, {
                    'origin': 'inferred', 'basis': basis,
                    'confidence': CONFIDENCE[basis],
                    'evidence': statement[:_MAX_EVIDENCE],
                    'purpose': 'cross-estate-data-access',
                })
                if added:
                    links.append(dict(row_base, relType=rel_type))

    graph.reindex()
    return {
        'links': links,
        'suppressed': suppressed,
        'unbound': unbound,
        'datasources': sorted(datasources.values(), key=lambda r: r['name']),
        'coverage': _coverage(graph, links, unbound, datasources, allow_name_match),
    }


def _resolve_table(raw: str, mapped_owner: str,
                   qualified_index: Dict[str, GraphNode],
                   bare_index: Dict[str, List[GraphNode]]
                   ) -> Tuple[Optional[GraphNode], str, str]:
    """One table name to one database object, or a reason it did not resolve."""
    if '.' in raw:
        owner, _, name = raw.rpartition('.')
        key = f'{db_ident(owner)}.{db_ident(name)}'
        node = qualified_index.get(key)
        return (node, 'qualified-name', '') if node else (None, '', 'no-such-object')

    name = db_ident(raw)
    if mapped_owner:
        node = qualified_index.get(f'{mapped_owner}.{name}')
        return (node, 'qualified-name', '') if node else (None, '', 'no-such-object')

    candidates = bare_index.get(name, [])
    if len(candidates) == 1:
        return candidates[0], 'name', ''
    if len(candidates) > 1:
        return None, '', 'ambiguous-name'
    return None, '', 'no-such-object'


def _unbound_detail(reason: str, raw: str, mapped_owner: str, resource: str) -> str:
    if reason == 'ambiguous-name':
        return (f'"{raw}" matches an object in more than one schema and the '
                f'datasource is unmapped, so the owner cannot be decided')
    if mapped_owner:
        return (f'no object named {mapped_owner}.{db_ident(raw)} exists in any '
                f'database estate')
    return (f'"{raw}" names no object in any database estate, and the datasource '
            f'{resource or "(unknown)"} has no estate-map entry to narrow it')


def _coverage(graph: Graph, links: List[Dict[str, Any]], unbound: List[Dict[str, Any]],
              datasources: Dict[str, Dict[str, Any]], allow_name_match: bool
              ) -> Dict[str, Any]:
    """The wrapper's own gate (spec section 6).

    Activities that carry no static SQL are excluded from the denominator and
    counted separately, exactly as the Oracle analyzer separates
    `dynamicSqlSites` from `resolutionCoverage`. Averaging them in would let a
    blind spot masquerade as a low score rather than as a blind spot.
    """
    jdbc = [node for node in graph.by_label('Activity')
            if node.properties.get('category') in JDBC_CATEGORIES]
    with_sql = [node for node in jdbc if node.properties.get('sqlStatement')]
    bound_ids = {row['fromId'] for row in links if row['fromLabel'] == 'Activity'}
    bound = [node for node in with_sql if node.node_id in bound_ids]
    no_statement = [node for node in jdbc if not node.properties.get('sqlStatement')]

    mapped = [record for record in datasources.values() if record['mapped']]
    by_basis: Dict[str, int] = {}
    for row in links:
        by_basis[row['basis']] = by_basis.get(row['basis'], 0) + 1

    return {
        'jdbcActivities': len(jdbc),
        'jdbcActivitiesWithSql': len(with_sql),
        'jdbcActivitiesBound': len(bound),
        'sqlBindCoverage': round(100.0 * len(bound) / len(with_sql), 1) if with_sql else 0.0,
        'noStaticSqlSites': len(no_statement),
        'datasources': len(datasources),
        'datasourcesMapped': len(mapped),
        'datasourceCoverage': (round(100.0 * len(mapped) / len(datasources), 1)
                               if datasources else 0.0),
        'crossEstateLinks': len(links),
        'crossEstateLinksByBasis': dict(sorted(by_basis.items())),
        'unboundReferences': len(unbound),
        'nameMatchAllowed': allow_name_match,
    }
