"""Cross-estate validation rules.

The generic engine in `analyzer_core.graph.validate` already checks ids,
referential integrity, vocabulary, typing, orphans and provenance. These are
the checks that depend on what federation *means*.

The important one is `cross-estate-links`. A federated graph with no
cross-estate edges is indistinguishable, in a node count, from a healthy one --
and it is the state a wrapper falls into when the estate map is wrong, when the
TIBCO estate points at a different database, or when a matcher regresses. It
must be loud, because the resulting reports look complete.
"""
from __future__ import annotations

from typing import Any, Dict, List

from analyzer_core.graph.validate import Finding
from analyzer_core.model import Graph

from ..constants import (MIN_DATASOURCE_COVERAGE, MIN_SQL_BIND_COVERAGE,
                         RULE_PREFIXES)

CROSS_ESTATE_RELS = ('READS_FROM', 'WRITES_TO', 'INSERTS_INTO', 'UPDATES',
                     'DELETES_FROM', 'CONNECTS_TO_SCHEMA')


def _coverage(graph: Graph) -> Dict[str, Any]:
    return dict((graph.meta or {}).get('coverage') or {})


def estate_provenance(graph: Graph) -> List[Finding]:
    """Every node must say which estate it came from."""
    missing = [node.node_id for node in graph.nodes.values()
               if not node.properties.get('estate')]
    if missing:
        return [Finding('ERROR', 'estate-provenance',
                        f'{len(missing)} node(s) carry no estate', missing[:25])]
    return [Finding('INFO', 'estate-provenance',
                    f'All {len(graph.nodes)} nodes carry an estate')]


def cross_estate_links(graph: Graph) -> List[Finding]:
    """Edges whose two ends come from different estates."""
    crossing = []
    for rel in graph.rels:
        start = graph.nodes.get(rel.start_id)
        end = graph.nodes.get(rel.end_id)
        if start is None or end is None:
            continue
        if rel.rel_type not in CROSS_ESTATE_RELS:
            continue
        if start.properties.get('estate') != end.properties.get('estate'):
            crossing.append(f'{start.name} -[{rel.rel_type}]-> {end.name}')

    merged = _coverage(graph).get('mergedDbNodes', 0)
    if crossing or merged:
        return [Finding('INFO', 'cross-estate-links',
                        f'{len(crossing)} cross-estate edge(s) and {merged} '
                        f'shared database node(s)', crossing[:25])]
    return [Finding('WARNING', 'cross-estate-links',
                    'The federation produced no cross-estate edges and no '
                    'shared database nodes: this graph is three estates in one '
                    'file, not a federated estate. Check the estate map, and '
                    'check that the TIBCO estate and the database estate '
                    'really are the same system.')]


def sql_bind_coverage(graph: Graph) -> List[Finding]:
    coverage = _coverage(graph)
    value = coverage.get('sqlBindCoverage')
    if value is None:
        return []
    detail = [f"bound: {coverage.get('jdbcActivitiesBound')}"
              f"/{coverage.get('jdbcActivitiesWithSql')} JDBC activities "
              f'carrying static SQL',
              f"no static SQL: {coverage.get('noStaticSqlSites')} activity/ies",
              f"unbound references: {coverage.get('unboundReferences')}"]
    if value < MIN_SQL_BIND_COVERAGE:
        return [Finding('WARNING', 'sql-bind-coverage',
                        f'SQL bind coverage is {value}% - below '
                        f'{MIN_SQL_BIND_COVERAGE}% the cross-estate view is '
                        f'provisional and every answer drawn from it must say '
                        f'so', detail)]
    return [Finding('INFO', 'sql-bind-coverage',
                    f'SQL bind coverage {value}%', detail)]


def datasource_coverage(graph: Graph) -> List[Finding]:
    coverage = _coverage(graph)
    value = coverage.get('datasourceCoverage')
    if value is None:
        return []
    total = coverage.get('datasources', 0)
    mapped = coverage.get('datasourcesMapped', 0)
    if value < MIN_DATASOURCE_COVERAGE:
        return [Finding('WARNING', 'datasource-coverage',
                        f'{mapped}/{total} JDBC datasource(s) are mapped to a '
                        f'schema ({value}%); every table reached through an '
                        f'unmapped datasource is missing from this graph')]
    return [Finding('INFO', 'datasource-coverage',
                    f'{mapped}/{total} JDBC datasource(s) mapped ({value}%)')]


def merged_db_nodes(graph: Graph) -> List[Finding]:
    """The APEX/Oracle join is exact; zero merges means it did not happen."""
    coverage = _coverage(graph)
    estates = set((graph.meta or {}).get('estates') or {})
    merged = coverage.get('mergedDbNodes', 0)
    if not {'apex', 'oracle'} <= estates:
        return []
    if merged:
        return [Finding('INFO', 'merged-db-nodes',
                        f'{merged} database node(s) contributed by both the '
                        f'APEX and Oracle estates')]
    return [Finding('WARNING', 'merged-db-nodes',
                    'The APEX and Oracle estates share no database object ids. '
                    'That join needs no heuristic, so zero means the two '
                    'analyses cover different schemas - say so rather than '
                    'reporting one estate.')]


def property_conflicts(graph: Graph) -> List[Finding]:
    meta = graph.meta or {}
    count = meta.get('propertyConflictCount', 0)
    if not count:
        return []
    unresolved = [c for c in meta.get('propertyConflicts', [])
                  if c.get('resolvedBy') == 'first contributor']
    detail = [f"{c['nodeId']}.{c['property']}: kept {c['kept']!r} from "
              f"{c['keptFrom']}, discarded {c['discarded']!r} from "
              f"{c['discardedFrom']}"
              for c in meta.get('propertyConflicts', [])[:25]]
    if unresolved:
        return [Finding('WARNING', 'property-conflicts',
                        f'{count} property conflict(s) on merged nodes, '
                        f'{len(unresolved)} of them settled only by load order '
                        f'because neither estate supplied a data dictionary',
                        detail)]
    return [Finding('INFO', 'property-conflicts',
                    f'{count} property conflict(s) on merged nodes, all settled '
                    f'by data-dictionary authority', detail)]


def finding_namespacing(graph: Graph) -> List[Finding]:
    """No two estates may contribute the same rule id meaning two things."""
    allowed = tuple(RULE_PREFIXES.values()) + ('XE-',)
    bad = [f"{node.node_id} ({node.properties.get('ruleId')})"
           for node in graph.by_label('Issue')
           if not str(node.properties.get('ruleId', '')).startswith(allowed)]
    if bad:
        return [Finding('ERROR', 'finding-namespacing',
                        f'{len(bad)} finding(s) carry an un-namespaced rule id; '
                        f'SEC-001 means different things in different estates',
                        bad[:25])]
    return []


def inherited_coverage(graph: Graph) -> List[Finding]:
    """Quote the weakest upstream gate, never an average."""
    estates = _coverage(graph).get('estates') or {}
    weak: List[str] = []
    detail: List[str] = []
    for estate, coverage in sorted(estates.items()):
        for key, gate in (('resolutionCoverage', 80.0),
                          ('artifactCoverage', 80.0)):
            value = coverage.get(key)
            if value is None:
                continue
            scaled = value * 100 if 0 < value <= 1 else value
            detail.append(f'{estate}.{key} = {scaled}')
            if scaled < gate:
                weak.append(f'{estate}.{key} = {scaled}% (gate {gate}%)')
    if weak:
        return [Finding('WARNING', 'inherited-coverage',
                        f'{len(weak)} upstream estate(s) are below their own '
                        f'coverage gate; the federated graph cannot be stronger '
                        f'than its weakest input', weak + detail)]
    return [Finding('INFO', 'inherited-coverage',
                    'Every upstream estate is at or above its own coverage gate',
                    detail)]


def suppressed_matches(graph: Graph) -> List[Finding]:
    count = (graph.meta or {}).get('links', {}).get('suppressedCount', 0)
    if not count:
        return []
    return [Finding('INFO', 'suppressed-matches',
                    f'{count} bare-name match(es) were computed and withheld; '
                    f're-run federate with --allow-name-match to admit them, '
                    f'and report them separately if you do')]


ESTATE_RULES = [
    estate_provenance,
    cross_estate_links,
    sql_bind_coverage,
    datasource_coverage,
    merged_db_nodes,
    property_conflicts,
    finding_namespacing,
    inherited_coverage,
    suppressed_matches,
]
