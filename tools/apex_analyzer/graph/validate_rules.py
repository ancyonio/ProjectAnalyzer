"""APEX-specific validation rules (specification §15).

The generic checks — id grammar, referential integrity, closed vocabulary,
property typing, orphans, provenance — live in `analyzer_core`. These add the
domain rules, of which the most important are the coverage rules: a graph
whose SQL binder resolved less than 80 % of its references is reported as
provisional, because an impact answer computed on it would be quietly wrong.
"""
from __future__ import annotations

from typing import List

from analyzer_core.graph.validate import Finding
from analyzer_core.model import Graph

from ..constants import MAX_PARSE_FAILURE_RATE, MIN_RESOLUTION_COVERAGE


def check_containment(graph: Graph) -> List[Finding]:
    findings: List[Finding] = []
    orphan_pages = [n.node_id for n in graph.by_label('ApexPage')
                    if not any(r.rel_type == 'CONTAINS_PAGE'
                               for r in graph.incoming(n.node_id))]
    if orphan_pages:
        findings.append(Finding('ERROR', 'AX-CONTAIN',
                                f'{len(orphan_pages)} page(s) belong to no application',
                                orphan_pages[:20]))
    orphan_regions = [n.node_id for n in graph.by_label('ApexRegion')
                      if not any(r.rel_type in ('CONTAINS_REGION', 'CONTAINS_SUBREGION')
                                 for r in graph.incoming(n.node_id))]
    if orphan_regions:
        findings.append(Finding('WARNING', 'AX-CONTAIN',
                                f'{len(orphan_regions)} region(s) belong to no page',
                                orphan_regions[:20]))
    orphan_columns = [n.node_id for n in graph.by_label('DbColumn')
                      if not any(r.rel_type == 'HAS_COLUMN'
                                 for r in graph.incoming(n.node_id))]
    if orphan_columns:
        findings.append(Finding('ERROR', 'AX-CONTAIN',
                                f'{len(orphan_columns)} column(s) belong to no table',
                                orphan_columns[:20]))
    return findings


def check_coverage(graph: Graph) -> List[Finding]:
    findings: List[Finding] = []
    coverage = (graph.meta or {}).get('coverage', {})
    if not coverage:
        return findings

    if not coverage.get('dictionaryAvailable'):
        findings.append(Finding(
            'WARNING', 'AX-COVERAGE',
            'No database extract or DDL was available: database objects are '
            'inferred from SQL alone, so impact analysis below the SQL layer is '
            'incomplete',
            ['run apex_analyzer/extract/*.sql and pass --db-meta']))

    ratio = coverage.get('resolutionCoverage')
    if ratio is not None and coverage.get('totalResolutions'):
        if ratio < MIN_RESOLUTION_COVERAGE:
            findings.append(Finding(
                'WARNING', 'AX-COVERAGE',
                f'Resolution coverage is {ratio:.0%} (target '
                f'{MIN_RESOLUTION_COVERAGE:.0%}); the graph is provisional',
                coverage.get('unresolvedNames', [])[:25]))
        else:
            findings.append(Finding('INFO', 'AX-COVERAGE',
                                    f'Resolution coverage {ratio:.0%}'))

    failure_rate = coverage.get('parseFailureRate', 0.0)
    if failure_rate > MAX_PARSE_FAILURE_RATE:
        findings.append(Finding(
            'WARNING', 'AX-COVERAGE',
            f'{failure_rate:.0%} of code nodes failed to parse '
            f'(limit {MAX_PARSE_FAILURE_RATE:.0%})'))
    return findings


def check_unhandled_procedures(graph: Graph) -> List[Finding]:
    unhandled = (graph.meta or {}).get('unhandledProcedures', {})
    if not unhandled:
        return []
    total = sum(unhandled.values())
    return [Finding('WARNING', 'AX-CROSSCHECK',
                    f'{total} export call(s) across {len(unhandled)} procedure(s) were '
                    f'not handled by any parser',
                    [f'{name}: {count}' for name, count in unhandled.items()][:25])]


def check_dependency_agreement(graph: Graph) -> List[Finding]:
    """Parser-inferred `CALLS`/`READS_FROM` against dictionary `DEPENDS_ON`."""
    dictionary = {(r.start_id, r.end_id) for r in graph.rels
                  if r.rel_type == 'DEPENDS_ON' and r.properties.get('origin') != 'inferred'}
    if not dictionary:
        return []
    mismatches = []
    for rel in graph.rels:
        if rel.rel_type != 'CALLS' or rel.properties.get('resolution') in (None, 'exact'):
            continue
        source = graph.node(rel.start_id)
        if source is None or source.label != 'DbProgramUnit':
            continue
        if (rel.start_id, rel.end_id) not in dictionary:
            mismatches.append(f'{rel.start_id} -> {rel.end_id}')
    if mismatches:
        return [Finding('WARNING', 'AX-DEPMISMATCH',
                        f'{len(mismatches)} inferred call edge(s) are not confirmed by '
                        f'ALL_DEPENDENCIES', mismatches[:25])]
    return []


def check_application_present(graph: Graph) -> List[Finding]:
    applications = graph.by_label('ApexApplication')
    if not applications:
        return [Finding('ERROR', 'AX-CONTAIN',
                        'No application node: the export was not recognised')]
    if len(applications) > 1:
        return [Finding('INFO', 'AX-CONTAIN',
                        f'{len(applications)} applications loaded into one graph',
                        [a.node_id for a in applications])]
    return []


APEX_RULES = [
    check_application_present,
    check_containment,
    check_coverage,
    check_unhandled_procedures,
    check_dependency_agreement,
]
