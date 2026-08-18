"""Estate-wide inventory, computed from the federated graph only.

Nothing here recounts what an analyzer already counted. Per-estate totals are
quoted from `graph.meta.estates`; everything else is a fact that exists only
after the join -- which tables two estates share, which components reach across
an estate boundary, and how much of the join is inferred rather than exact.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from analyzer_core.model import Graph, GraphNode

from ..constants import CATEGORIES, ESTATES, SEVERITY_ORDER

WRITE_RELS = ('WRITES_TO', 'INSERTS_INTO', 'UPDATES', 'DELETES_FROM')
READ_RELS = ('READS_FROM',)
ACCESS_RELS = WRITE_RELS + READ_RELS
DB_OBJECT_LABELS = ('DbTable', 'DbView', 'DbMaterializedView')


def _estate_of(node: GraphNode) -> str:
    return str(node.properties.get('estate', '') or '')


def summary(graph: Graph) -> Dict[str, Any]:
    stats = graph.stats()
    counts = stats['nodeCounts']
    estates = (graph.meta or {}).get('estates') or {}
    coverage = (graph.meta or {}).get('coverage') or {}
    return {
        'estates': len(estates),
        'nodes': stats['totalNodes'],
        'relationships': stats['totalRelationships'],
        'tibcoProcesses': counts.get('BWProcess', 0),
        'tibcoActivities': counts.get('Activity', 0),
        'apexPages': counts.get('ApexPage', 0),
        'oracleProgramUnits': counts.get('DbProgramUnit', 0),
        'databaseObjects': sum(counts.get(label, 0) for label in DB_OBJECT_LABELS),
        'sharedDatabaseNodes': coverage.get('mergedDbNodes', 0),
        'sharedDatabaseObjects': sum(
            1 for label in DB_OBJECT_LABELS for node in graph.by_label(label)
            if node.properties.get('merged')),
        'crossEstateLinks': coverage.get('crossEstateLinks', 0),
        'contendedTables': len(contended_tables(graph)),
        'issues': counts.get('Issue', 0),
    }


def estates(graph: Graph) -> List[Dict[str, Any]]:
    """One row per estate, quoting what its own analyzer reported."""
    meta_estates = (graph.meta or {}).get('estates') or {}
    coverage = ((graph.meta or {}).get('coverage') or {}).get('estates') or {}
    rows = []
    for estate in ESTATES:
        if estate not in meta_estates:
            continue
        info = meta_estates[estate]
        own = coverage.get(estate, {})
        rows.append({
            'estate': estate,
            'title': info.get('title', estate),
            'sourceRoot': info.get('sourceRoot', ''),
            'nodes': info.get('nodes', 0),
            'relationships': info.get('relationships', 0),
            'federatedNodes': sum(1 for node in graph.nodes.values()
                                  if _estate_of(node) == estate),
            'coverage': _headline_coverage(own),
        })
    return rows


def _headline_coverage(coverage: Dict[str, Any]) -> str:
    """The one number that estate's own analyzer gates on."""
    for key, label in (('artifactCoverage', 'artifact'),
                       ('resolutionCoverage', 'resolution')):
        if key in coverage and coverage[key] is not None:
            value = coverage[key]
            scaled = value * 100 if 0 < value <= 1 else value
            return f'{label} {round(scaled, 1)}%'
    return 'not reported'


def table_access(graph: Graph) -> List[Dict[str, Any]]:
    """Every database object, and which estates read and write it."""
    rows = []
    for label in DB_OBJECT_LABELS:
        for table in graph.by_label(label):
            readers: Dict[str, List[str]] = defaultdict(list)
            writers: Dict[str, List[str]] = defaultdict(list)
            for rel in graph.incoming(table.node_id):
                source = graph.nodes.get(rel.start_id)
                if source is None:
                    continue
                estate = _estate_of(source)
                if not estate:
                    continue
                if rel.rel_type in WRITE_RELS:
                    writers[estate].append(source.name)
                elif rel.rel_type in READ_RELS:
                    readers[estate].append(source.name)
            if not readers and not writers:
                continue
            estates_touching = sorted(set(readers) | set(writers))
            rows.append({
                'name': table.name,
                'label': label,
                'nodeId': table.node_id,
                'owner': str(table.properties.get('owner', '') or ''),
                'estates': estates_touching,
                'estateCount': len(estates_touching),
                'writerEstates': sorted(writers),
                'readerEstates': sorted(readers),
                'writers': sum(len(v) for v in writers.values()),
                'readers': sum(len(v) for v in readers.values()),
                'shared': bool(table.properties.get('merged')),
            })
    rows.sort(key=lambda r: (-r['estateCount'], -r['writers'] - r['readers'], r['name']))
    return rows


def contended_tables(graph: Graph) -> List[Dict[str, Any]]:
    """Objects more than one estate writes: the hard part of any cutover."""
    return [row for row in table_access(graph) if len(row['writerEstates']) > 1]


def boundary_components(graph: Graph) -> List[Dict[str, Any]]:
    """Components whose data access touches data another estate also uses.

    Two shapes qualify, and both matter: an edge that literally crosses an
    estate boundary, and an edge to an object that more than one estate
    contributed. Either way the component cannot be understood, tested or
    migrated from inside one estate, which is the whole reason the federation
    exists.
    """
    rows = []
    for node in graph.nodes.values():
        estate = _estate_of(node)
        if not estate or node.label in ('Issue', 'Recommendation', 'Estate'):
            continue
        reached = []
        for rel in graph.outgoing(node.node_id):
            if rel.rel_type not in ACCESS_RELS:
                continue
            target = graph.nodes.get(rel.end_id)
            if target is None:
                continue
            others = {e for e in str(target.properties.get('estates', '') or '').split(';') if e}
            others.discard(estate)
            if others or target.properties.get('estate') != estate:
                reached.append({'table': target.name, 'rel': rel.rel_type,
                                'confidence': rel.properties.get('confidence'),
                                'basis': rel.properties.get('basis', 'exact')})
        if not reached:
            continue
        rows.append({
            'nodeId': node.node_id, 'name': node.name, 'label': node.label,
            'estate': estate, 'module': str(node.properties.get('module', '') or ''),
            'reaches': sorted({row['table'] for row in reached}),
            'access': sorted({row['rel'] for row in reached}),
            'minConfidence': min((row['confidence'] for row in reached
                                  if row['confidence'] is not None), default=1.0),
        })
    rows.sort(key=lambda r: (r['estate'], -len(r['reaches']), r['name']))
    return rows


def hotspots(graph: Graph, limit: int = 20) -> List[Dict[str, Any]]:
    """Most depended-upon nodes across the whole estate, not within one."""
    rows = []
    for node in graph.nodes.values():
        if node.label in ('Issue', 'Recommendation', 'Estate'):
            continue
        fan_in = sum(1 for rel in graph.incoming(node.node_id)
                     if rel.rel_type not in ('HAS_ISSUE', 'CONTAINS_ESTATE'))
        if fan_in < 2:
            continue
        estates_touching = {_estate_of(graph.nodes[rel.start_id])
                            for rel in graph.incoming(node.node_id)
                            if rel.start_id in graph.nodes}
        estates_touching.discard('')
        rows.append({'nodeId': node.node_id, 'name': node.name,
                     'label': node.label, 'estate': _estate_of(node),
                     'fanIn': fan_in, 'estateCount': len(estates_touching),
                     'estates': sorted(estates_touching)})
    rows.sort(key=lambda r: (-r['estateCount'], -r['fanIn'], r['name']))
    return rows[:limit]


def issues_summary(graph: Graph) -> Dict[str, Any]:
    findings = []
    for issue in graph.by_label('Issue'):
        recommendation = ''
        for rel in graph.outgoing(issue.node_id):
            if rel.rel_type == 'HAS_RECOMMENDATION' and rel.end_id in graph.nodes:
                recommendation = str(graph.nodes[rel.end_id].properties.get('text', ''))
                break
        findings.append({
            'ruleId': str(issue.properties.get('ruleId', '')),
            'sourceRuleId': str(issue.properties.get('sourceRuleId', '')),
            'severity': str(issue.properties.get('severity', '')),
            'category': str(issue.properties.get('category', '')),
            'estate': str(issue.properties.get('estate', '')),
            'description': str(issue.properties.get('description', '')),
            'targetLabel': str(issue.properties.get('targetLabel', '')),
            'targetName': str(issue.properties.get('targetName', '')),
            'filePath': str(issue.properties.get('filePath', '')),
            'recommendation': recommendation,
            'nodeId': issue.node_id,
        })
    findings.sort(key=lambda f: (-_severity_rank(f['severity']), f['ruleId'],
                                 f['targetName']))

    by_severity: Dict[str, int] = defaultdict(int)
    by_category: Dict[str, int] = defaultdict(int)
    by_estate: Dict[str, int] = defaultdict(int)
    for finding in findings:
        by_severity[finding['severity']] += 1
        by_category[finding['category']] += 1
        by_estate[finding['estate']] += 1
    return {
        'total': len(findings),
        'bySeverity': {s: by_severity[s] for s in reversed(SEVERITY_ORDER)
                       if by_severity.get(s)},
        'byCategory': {c: by_category[c] for c in CATEGORIES if by_category.get(c)},
        'byEstate': dict(sorted(by_estate.items())),
        'findings': findings,
    }


def _severity_rank(severity: str) -> int:
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return -1


def full_inventory(graph: Graph) -> Dict[str, Any]:
    return {
        'summary': summary(graph),
        'estates': estates(graph),
        'coverage': (graph.meta or {}).get('coverage') or {},
        'links': (graph.meta or {}).get('links') or {},
        'tableAccess': table_access(graph),
        'contendedTables': contended_tables(graph),
        'boundaryComponents': boundary_components(graph),
        'hotspots': hotspots(graph),
        'issues': issues_summary(graph),
    }
