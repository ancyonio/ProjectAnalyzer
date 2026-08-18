"""Oracle-specific validation rules (spec §8).

These are the checks the generic engine cannot make because they depend on what
the vocabulary means. The important one is `data-access-coverage`: SQL nodes
with no data-access edges means the binder did not run, which is
indistinguishable from "this code touches no tables" in a node count and leads
to the opposite conclusion. The TIBCO analyzer learned the same lesson from a
parser that silently produced nothing for a whole artifact class.
"""
from __future__ import annotations

from typing import List

from analyzer_core.graph.validate import Finding
from analyzer_core.model import Graph

MIN_RESOLUTION = 80.0


def package_body_without_spec(graph: Graph) -> List[Finding]:
    """A body with no spec publishes nothing and cannot be called from outside."""
    orphaned = []
    for package in graph.by_label('DbPackage'):
        halves = {graph.nodes[r.end_id].label
                  for r in graph.outgoing(package.node_id)
                  if r.rel_type in ('HAS_SPEC', 'HAS_BODY')
                  and r.end_id in graph.nodes}
        if 'PackageBody' in halves and 'PackageSpec' not in halves:
            orphaned.append(package.name)
    if orphaned:
        return [Finding('ERROR', 'package-body-without-spec',
                        f'{len(orphaned)} package body/bodies have no spec',
                        sorted(orphaned))]
    return []


def unit_not_in_package(graph: Graph) -> List[Finding]:
    """Every program unit belongs to a package half or directly to a schema."""
    loose = []
    for unit in graph.by_label('DbProgramUnit'):
        parents = {r.rel_type for r in graph.incoming(unit.node_id)}
        if not parents & {'HAS_UNIT', 'OWNS'}:
            loose.append(unit.name)
    if loose:
        return [Finding('ERROR', 'unit-not-in-package',
                        f'{len(loose)} program unit(s) have no owning package '
                        f'or schema', sorted(loose))]
    return []


def data_access_coverage(graph: Graph) -> List[Finding]:
    """SQL nodes but no data-access edges means the binder failed."""
    statements = graph.by_label('SqlStatement')
    if not statements:
        return []
    access = sum(1 for r in graph.rels
                 if r.rel_type in ('READS_FROM', 'WRITES_TO', 'INSERTS_INTO',
                                   'UPDATES', 'DELETES_FROM'))
    if access:
        return [Finding('INFO', 'data-access-coverage',
                        f'{access} data-access edge(s) from '
                        f'{len(statements)} SQL statement(s)')]
    return [Finding('ERROR', 'data-access-coverage',
                    f'{len(statements)} SQL statement(s) produced no '
                    f'data-access edges - the lineage graph is empty because '
                    f'the binder did not resolve, not because this code '
                    f'touches no tables')]


def table_has_columns(graph: Graph) -> List[Finding]:
    bare = [t.name for t in graph.by_label('DbTable')
            if not any(r.rel_type == 'HAS_COLUMN'
                       for r in graph.outgoing(t.node_id))]
    if bare:
        return [Finding('WARNING', 'table-has-columns',
                        f'{len(bare)} table(s) have no columns - column-level '
                        f'lineage is unavailable for them', sorted(bare))]
    return []


def resolution_coverage(graph: Graph) -> List[Finding]:
    coverage = (graph.meta or {}).get('coverage') or {}
    value = coverage.get('resolutionCoverage')
    if value is None:
        return []
    detail = [f"objects modelled: {coverage.get('objectsModelled')}"
              f"/{coverage.get('objectsDiscovered')}",
              f"calls resolved: {coverage.get('callsResolved')}"
              f"/{coverage.get('callsResolved', 0) + coverage.get('callsUnresolved', 0)}"]
    if value < MIN_RESOLUTION:
        return [Finding('WARNING', 'resolution-coverage',
                        f'Resolution coverage is {value}% - below {MIN_RESOLUTION}% '
                        f'the graph is provisional and every answer drawn from '
                        f'it must say so', detail)]
    return [Finding('INFO', 'resolution-coverage',
                    f'Resolution coverage {value}%', detail)]


def invalid_objects(graph: Graph) -> List[Finding]:
    invalid = [n.name for n in graph.nodes.values()
               if str(n.properties.get('status', '')).upper() == 'INVALID']
    if invalid:
        return [Finding('WARNING', 'invalid-objects',
                        f'{len(invalid)} object(s) are INVALID in the database',
                        sorted(invalid))]
    return []


def dynamic_sql_declared(graph: Graph) -> List[Finding]:
    sites = (graph.meta or {}).get('coverage', {}).get('dynamicSqlSites', 0)
    if sites:
        return [Finding('INFO', 'dynamic-sql-declared',
                        f'{sites} site(s) build SQL at runtime; dependency '
                        f'analysis stops there by design')]
    return []


ORACLE_RULES = [
    package_body_without_spec,
    unit_not_in_package,
    data_access_coverage,
    table_has_columns,
    resolution_coverage,
    invalid_objects,
    dynamic_sql_declared,
]
