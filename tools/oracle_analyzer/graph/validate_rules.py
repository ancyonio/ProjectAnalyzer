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
# Below this the parser is losing code, not just failing to bind names. Set
# higher than the resolution gate on purpose: an unresolved name is often a
# genuinely absent object, whereas a statement the parser could not read is
# always the parser's problem.
MIN_PARSE_QUALITY = 90.0


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


def business_seed_is_grounded(graph: Graph) -> List[Finding]:
    """Every seeded business node must say where it came from.

    A `BusinessFunction` with no `evidence` and no `IMPLEMENTED_BY` edge is
    indistinguishable from one an agent invented, and once it is in Neo4j
    nobody can tell the difference. That is the one thing this layer must not
    allow.
    """
    ungrounded = []
    for node in graph.by_label('BusinessFunction'):
        implemented = any(r.rel_type == 'IMPLEMENTED_BY'
                          for r in graph.outgoing(node.node_id))
        if not implemented or not node.properties.get('evidence'):
            ungrounded.append(node.name)
    if ungrounded:
        return [Finding('ERROR', 'business-seed-grounded',
                        f'{len(ungrounded)} business function(s) have no '
                        f'evidence or nothing implementing them',
                        sorted(ungrounded))]
    functions = len(graph.by_label('BusinessFunction'))
    if functions:
        declared = sum(1 for n in graph.by_label('BusinessFunction')
                       if n.properties.get('origin') == 'declared')
        return [Finding('INFO', 'business-seed-grounded',
                        f'{functions} business function(s), {declared} declared '
                        f'and {functions - declared} derived')]
    return []


def test_coverage(graph: Graph) -> List[Finding]:
    """Entry points with no test, reported as scope rather than as a defect."""
    cases = graph.by_label('TestCase')
    if not cases:
        return []
    untested = []
    for node in graph.by_label('DbProgramUnit'):
        if not (node.properties.get('isPublished')
                or node.properties.get('isStandalone')):
            continue
        if node.properties.get('declaredOnly'):
            continue
        if any(r.rel_type == 'HAS_TEST' for r in graph.outgoing(node.node_id)):
            continue
        if str(node.properties.get('packageName') or '') in {
                c.properties.get('suite') for c in cases}:
            continue                      # the suite does not test itself
        untested.append(node.name)
    if untested:
        return [Finding('INFO', 'test-coverage',
                        f'{len(cases)} test case(s); {len(untested)} entry '
                        f'point(s) have none', sorted(untested))]
    return [Finding('INFO', 'test-coverage',
                    f'{len(cases)} test case(s) cover every entry point')]


def parse_quality(graph: Graph) -> List[Finding]:
    """Did the parser understand the code, not just bind the names it found?

    `resolution-coverage` measures whether references resolved. This measures
    the step before it. The two fail independently and the difference matters:
    a graph that reads 40% of its statements can still resolve every name it
    managed to extract and report full coverage, which is the most flattering
    possible summary of the least useful graph.
    """
    coverage = (graph.meta or {}).get('coverage') or {}
    total = coverage.get('codeNodes')
    if not total:
        return []

    value = coverage.get('parseQuality', 100.0)
    partial = coverage.get('statementsPartial', 0)
    failed = coverage.get('statementsFailed', 0)
    unparsed = coverage.get('ddlUnparsed', 0)
    detail = [f"parsed: {coverage.get('statementsParsed')}/{total}",
              f'partial: {partial}', f'failed: {failed}',
              f"unparsed DDL: {unparsed}/{coverage.get('ddlStatements', 0)}"]

    if value < MIN_PARSE_QUALITY:
        return [Finding('WARNING', 'parse-quality',
                        f'Parse quality is {value}% - below '
                        f'{MIN_PARSE_QUALITY}% the graph describes less of the '
                        f'code than its resolution figure suggests', detail)]
    if failed:
        return [Finding('WARNING', 'parse-quality',
                        f'{failed} code node(s) failed to parse; their '
                        f'dependencies are absent from the graph', detail)]
    return [Finding('INFO', 'parse-quality',
                    f'Parse quality {value}%', detail)]


def unparsed_ddl(graph: Graph) -> List[Finding]:
    """DDL the splitter produced but no pattern claimed.

    These create nothing, so they leave no trace in a node count. A file of
    unsupported DDL and a file of nothing look identical without this.
    """
    coverage = (graph.meta or {}).get('coverage') or {}
    unparsed = coverage.get('ddlUnparsed', 0)
    if not unparsed:
        return []
    total = coverage.get('ddlStatements', 0)
    severity = 'WARNING' if total and unparsed * 100.0 / total > 10 else 'INFO'
    return [Finding(severity, 'unparsed-ddl',
                    f'{unparsed} of {total} DDL statement(s) matched no known '
                    f'pattern and produced no node')]


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
    parse_quality,
    unparsed_ddl,
    business_seed_is_grounded,
    test_coverage,
    package_body_without_spec,
    unit_not_in_package,
    data_access_coverage,
    table_has_columns,
    resolution_coverage,
    invalid_objects,
    dynamic_sql_declared,
]
