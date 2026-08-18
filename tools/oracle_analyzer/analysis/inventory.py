"""Inventory: the computed facts an analyst would otherwise recount by hand.

Everything here reads the finished graph. Nothing re-parses source, so an
inventory figure and a Cypher query over the same graph always agree.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from analyzer_core.model import Graph

from ..constants import SEVERITY_ORDER

_ACCESS_RELS = ('READS_FROM', 'INSERTS_INTO', 'UPDATES', 'DELETES_FROM')


def summary(graph: Graph) -> Dict[str, Any]:
    counts = Counter(node.label for node in graph.nodes.values())
    return {
        'schemas': counts.get('DbSchema', 0),
        'tables': counts.get('DbTable', 0),
        'columns': counts.get('DbColumn', 0),
        'views': counts.get('DbView', 0) + counts.get('DbMaterializedView', 0),
        'packages': counts.get('DbPackage', 0),
        'packageSpecs': counts.get('PackageSpec', 0),
        'packageBodies': counts.get('PackageBody', 0),
        'programUnits': counts.get('DbProgramUnit', 0),
        'triggers': counts.get('DbTrigger', 0),
        'sequences': counts.get('DbSequence', 0),
        'synonyms': counts.get('DbSynonym', 0),
        'sqlStatements': counts.get('SqlStatement', 0),
        'files': counts.get('File', 0),
        'issues': counts.get('Issue', 0),
        'unresolvedReferences': counts.get('UnresolvedRef', 0),
    }


def schemas(graph: Graph) -> List[Dict[str, Any]]:
    rows = []
    for schema in sorted(graph.by_label('DbSchema'), key=lambda n: n.name):
        owned = Counter()
        for rel in graph.outgoing(schema.node_id):
            if rel.rel_type == 'OWNS' and rel.end_id in graph.nodes:
                owned[graph.nodes[rel.end_id].label] += 1
        rows.append({
            'name': schema.name,
            'isDefault': bool(schema.properties.get('isDefault')),
            'tables': owned.get('DbTable', 0),
            'views': owned.get('DbView', 0),
            'packages': owned.get('DbPackage', 0),
            'standaloneUnits': owned.get('DbProgramUnit', 0),
            'triggers': owned.get('DbTrigger', 0),
        })
    return rows


def packages(graph: Graph) -> List[Dict[str, Any]]:
    rows = []
    for package in sorted(graph.by_label('DbPackage'), key=lambda n: n.name):
        halves, units, loc = {}, 0, 0
        for rel in graph.outgoing(package.node_id):
            half = graph.nodes.get(rel.end_id)
            if half is None or rel.rel_type not in ('HAS_SPEC', 'HAS_BODY'):
                continue
            halves[half.label] = half.properties.get('filePath', '')
            loc += int(half.properties.get('loc', 0) or 0)
            units += sum(1 for r in graph.outgoing(half.node_id)
                         if r.rel_type == 'HAS_UNIT')
        rows.append({
            'name': package.name,
            'owner': package.properties.get('owner', ''),
            'hasSpec': 'PackageSpec' in halves,
            'hasBody': 'PackageBody' in halves,
            'units': units,
            'loc': loc,
            'fanIn': package.properties.get('fanIn', 0),
            'filePath': halves.get('PackageBody') or halves.get('PackageSpec', ''),
        })
    return rows


def complexity_ranking(graph: Graph, limit: int = 40) -> List[Dict[str, Any]]:
    units = [n for n in graph.by_label('DbProgramUnit')
             if not n.properties.get('declaredOnly')]
    units.sort(key=lambda n: (-float(n.properties.get('complexity', 0.0)), n.name))
    return [{
        'name': unit.name,
        'package': unit.properties.get('packageName', ''),
        'owner': unit.properties.get('owner', ''),
        'unitType': unit.properties.get('unitType', ''),
        'complexity': unit.properties.get('complexity', 0.0),
        'tier': unit.properties.get('tier', 'Low'),
        'loc': unit.properties.get('loc', 0),
        'statements': unit.properties.get('statementCount', 0),
        'calls': unit.properties.get('callCount', 0),
        'fanIn': unit.properties.get('fanIn', 0),
        'filePath': unit.properties.get('filePath', ''),
    } for unit in units[:limit]]


def entry_points(graph: Graph) -> List[Dict[str, Any]]:
    """What the outside world can invoke: published units, standalones, triggers."""
    published = set()
    for rel in graph.rels:
        if rel.rel_type != 'HAS_UNIT':
            continue
        parent = graph.nodes.get(rel.start_id)
        if parent is not None and parent.label == 'PackageSpec':
            published.add(rel.end_id)

    rows = []
    for node in graph.by_label('DbProgramUnit'):
        if node.node_id in published or node.properties.get('isStandalone'):
            rows.append({
                'name': node.name,
                'kind': 'STANDALONE' if node.properties.get('isStandalone')
                else 'PUBLISHED',
                'package': node.properties.get('packageName', ''),
                'unitType': node.properties.get('unitType', ''),
                'filePath': node.properties.get('filePath', ''),
            })
    for trigger in graph.by_label('DbTrigger'):
        rows.append({
            'name': trigger.name,
            'kind': 'TRIGGER',
            'package': trigger.properties.get('baseObject', ''),
            'unitType': trigger.properties.get('triggeringEvent', ''),
            'filePath': trigger.properties.get('filePath', ''),
        })
    return sorted(rows, key=lambda r: (r['kind'], r['name']))


def data_access(graph: Graph) -> List[Dict[str, Any]]:
    """Which program units read and write which tables, through their SQL."""
    by_unit: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    statement_owner: Dict[str, List[str]] = defaultdict(list)
    for rel in graph.rels:
        if rel.rel_type == 'EXECUTES_SQL':
            statement_owner[rel.end_id].append(rel.start_id)

    for rel in graph.rels:
        if rel.rel_type not in _ACCESS_RELS:
            continue
        table = graph.nodes.get(rel.end_id)
        if table is None:
            continue
        owners = statement_owner.get(rel.start_id) or [rel.start_id]
        for owner_id in owners:
            owner = graph.nodes.get(owner_id)
            if owner is None or owner.label not in ('DbProgramUnit', 'DbTrigger'):
                continue
            by_unit[owner_id][table.name].add(rel.rel_type)

    rows = []
    for owner_id, tables in by_unit.items():
        owner = graph.nodes[owner_id]
        for table_name, verbs in sorted(tables.items()):
            rows.append({
                'unit': owner.name,
                'package': owner.properties.get('packageName', ''),
                'table': table_name,
                'access': ', '.join(sorted(verbs)),
                'writes': any(v != 'READS_FROM' for v in verbs),
                'filePath': owner.properties.get('filePath', ''),
            })
    return sorted(rows, key=lambda r: (r['unit'], r['table']))


def hotspots(graph: Graph, limit: int = 25) -> List[Dict[str, Any]]:
    """Objects most things depend on: change these and the blast radius is wide."""
    rows = []
    for node in graph.nodes.values():
        if node.label not in ('DbTable', 'DbView', 'DbPackage', 'DbProgramUnit'):
            continue
        fan_in = int(node.properties.get('fanIn', 0) or 0)
        if not fan_in:
            continue
        rows.append({
            'name': node.name,
            'label': node.label,
            'owner': node.properties.get('owner', ''),
            'fanIn': fan_in,
            'fanOut': int(node.properties.get('fanOut', 0) or 0),
        })
    rows.sort(key=lambda r: (-r['fanIn'], r['name']))
    return rows[:limit]


def dead_code(graph: Graph) -> Dict[str, List[Dict[str, str]]]:
    """Objects nothing in the analysed tree reaches."""
    referenced = {r.end_id for r in graph.rels
                  if r.rel_type not in ('OWNS', 'DEFINES', 'CONTAINS_FILE',
                                        'HAS_METRIC', 'HAS_ISSUE', 'AFFECTS',
                                        'HAS_UNIT', 'HAS_SPEC', 'HAS_BODY',
                                        'CHANGED')}
    buckets: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for node in graph.nodes.values():
        if node.label not in ('DbTable', 'DbView', 'DbSequence', 'DbProgramUnit',
                              'DbSynonym'):
            continue
        if node.node_id in referenced:
            continue
        if node.properties.get('declaredOnly'):
            continue
        buckets[node.label].append({
            'name': node.name,
            'owner': node.properties.get('owner', ''),
            'filePath': node.properties.get('filePath', ''),
        })
    return {label: sorted(rows, key=lambda r: r['name'])
            for label, rows in sorted(buckets.items())}


def issues_summary(graph: Graph) -> Dict[str, Any]:
    findings = []
    for issue in graph.by_label('Issue'):
        recommendation = ''
        for rel in graph.outgoing(issue.node_id):
            if rel.rel_type == 'HAS_RECOMMENDATION' and rel.end_id in graph.nodes:
                recommendation = graph.nodes[rel.end_id].properties.get('text', '')
                break
        findings.append({
            'ruleId': issue.properties.get('ruleId', ''),
            'severity': issue.properties.get('severity', 'LOW'),
            'category': issue.properties.get('category', ''),
            'description': issue.properties.get('description', ''),
            'target': issue.properties.get('targetName', ''),
            'targetLabel': issue.properties.get('targetLabel', ''),
            'filePath': issue.properties.get('filePath', ''),
            'lineStart': issue.properties.get('lineStart', 0),
            'recommendation': recommendation,
        })
    findings.sort(key=lambda f: (-SEVERITY_ORDER.index(f['severity'])
                                 if f['severity'] in SEVERITY_ORDER else 0,
                                 f['ruleId'], f['target']))
    return {
        'total': len(findings),
        'bySeverity': dict(Counter(f['severity'] for f in findings)),
        'byCategory': dict(Counter(f['category'] for f in findings)),
        'findings': findings,
    }


def full_inventory(graph: Graph) -> Dict[str, Any]:
    return {
        'summary': summary(graph),
        'coverage': (graph.meta or {}).get('coverage', {}),
        'schemas': schemas(graph),
        'packages': packages(graph),
        'entryPoints': entry_points(graph),
        'complexity': complexity_ranking(graph),
        'dataAccess': data_access(graph),
        'hotspots': hotspots(graph),
        'deadCode': dead_code(graph),
        'issues': issues_summary(graph),
        'stats': graph.stats(),
    }
