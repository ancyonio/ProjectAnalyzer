"""Modernisation sequencing across the three estates.

The ordering is derived, not asserted. It follows one rule: **a component may
not be cut over before the data it shares has an owner.** Everything else falls
out of that.

    Wave 0  Decide  - what must be settled before anything moves: contended
                      tables, unmapped datasources, unresolved references
    Wave 1  Together - components that share a contended table; they cut over
                      as one unit or not at all
    Wave 2  Follow  - components that touch shared data but contend with
                      nobody; they follow the owner of that data
    Wave 3  Free    - components that touch no shared data and can move in any
                      order

A component in wave 3 is not unimportant; it is unblocked, which is exactly
what makes it a good place to start.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from analyzer_core.model import Graph

from .inventory import (ACCESS_RELS, WRITE_RELS, boundary_components,
                        contended_tables, table_access)

MIGRATABLE_LABELS = ('BWProcess', 'ApexPage', 'DbProgramUnit', 'DbPackage',
                     'DbTrigger')


def sequence(graph: Graph) -> Dict[str, Any]:
    contended = {row['nodeId']: row for row in contended_tables(graph)}
    shared = {row['nodeId']: row for row in table_access(graph)
              if row['estateCount'] > 1}

    blockers = _blockers(graph, contended)
    groups = _cutover_groups(graph, contended)
    grouped_ids = {node_id for group in groups for node_id in group['componentIds']}
    follow, free = _remaining(graph, shared, grouped_ids)

    return {
        'waves': [
            {'wave': 0, 'title': 'Decide before anything moves',
             'rationale': 'Each of these leaves a question open that every later '
                          'wave depends on the answer to.',
             'items': blockers},
            {'wave': 1, 'title': 'Cut over together',
             'rationale': 'These components write the same table from different '
                          'estates. Migrating one without the other splits the '
                          'writer set across two runtimes.',
             'items': groups},
            {'wave': 2, 'title': 'Follow the data owner',
             'rationale': 'These touch data another estate also uses, but they '
                          'contend with no other writer, so they follow whoever '
                          'owns that data.',
             'items': follow},
            {'wave': 3, 'title': 'Move independently',
             'rationale': 'No shared data, so no cross-estate ordering '
                          'constraint. Start here.',
             'items': free},
        ],
        'summary': {
            'blockers': len(blockers),
            'cutoverGroups': len(groups),
            'followers': len(follow),
            'independent': len(free),
            'contendedTables': len(contended),
        },
    }


def _blockers(graph: Graph, contended: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Open questions, taken from the findings rather than re-derived."""
    items: List[Dict[str, Any]] = []
    for row in sorted(contended.values(), key=lambda r: r['name']):
        items.append({
            'kind': 'ownership',
            'subject': row['name'],
            'detail': f"written by {', '.join(row['writerEstates'])}; decide "
                      f'which estate owns it before either is cut over',
        })
    for issue in graph.by_label('Issue'):
        rule = str(issue.properties.get('ruleId', ''))
        if rule not in ('XE-002', 'XE-005', 'XE-006'):
            continue
        items.append({
            'kind': {'XE-002': 'unmodelled-dependency',
                     'XE-005': 'unmapped-datasource',
                     'XE-006': 'runtime-sql'}[rule],
            'subject': str(issue.properties.get('targetName', '')),
            'detail': str(issue.properties.get('description', '')),
        })
    items.sort(key=lambda item: (item['kind'], item['subject']))
    return items


def _cutover_groups(graph: Graph, contended: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One group per contended table: the table plus everything writing it."""
    groups: List[Dict[str, Any]] = []
    for table_id, row in sorted(contended.items(), key=lambda kv: kv[1]['name']):
        members: List[Dict[str, Any]] = []
        for rel in graph.incoming(table_id):
            if rel.rel_type not in WRITE_RELS:
                continue
            writer = graph.nodes.get(rel.start_id)
            if writer is None:
                continue
            owner = _migratable_owner(graph, writer)
            if owner is None:
                continue
            members.append({
                'nodeId': owner.node_id, 'name': owner.name,
                'label': owner.label,
                'estate': str(owner.properties.get('estate', '') or ''),
                'access': rel.rel_type,
                'basis': rel.properties.get('basis', 'exact'),
                'confidence': rel.properties.get('confidence', 1.0),
            })
        unique: Dict[str, Dict[str, Any]] = {}
        for member in members:
            unique.setdefault(member['nodeId'], member)
        groups.append({
            'table': row['name'],
            'tableId': table_id,
            'estates': row['writerEstates'],
            'components': sorted(unique.values(),
                                 key=lambda m: (m['estate'], m['name'])),
            'componentIds': sorted(unique),
        })
    return groups


def _migratable_owner(graph: Graph, node):
    """The artefact a team would actually migrate, not the statement node.

    A `SqlStatement` is not a deliverable; the program unit that executes it
    is. Walking up to it keeps the sequence expressed in artefacts a plan can
    name.
    """
    if node.label in MIGRATABLE_LABELS:
        return node
    seen = {node.node_id}
    frontier = [node.node_id]
    for _ in range(4):
        nxt = []
        for current in frontier:
            for rel in graph.incoming(current):
                parent = graph.nodes.get(rel.start_id)
                if parent is None or parent.node_id in seen:
                    continue
                if parent.label in MIGRATABLE_LABELS:
                    return parent
                seen.add(parent.node_id)
                nxt.append(parent.node_id)
        if not nxt:
            break
        frontier = nxt
    return node if node.label != 'SqlStatement' else None


def _remaining(graph: Graph, shared: Dict[str, Any], grouped: set
               ) -> tuple:
    """Split everything not in a cutover group into followers and free movers."""
    touching = defaultdict(set)
    for row in boundary_components(graph):
        touching[row['nodeId']] = set(row['reaches'])

    follow: List[Dict[str, Any]] = []
    free: List[Dict[str, Any]] = []
    shared_names = {row['name'] for row in shared.values()}

    for node in graph.nodes.values():
        if node.label not in MIGRATABLE_LABELS:
            continue
        if node.node_id in grouped:
            continue
        reaches = _reaches(graph, node.node_id)
        row = {
            'nodeId': node.node_id, 'name': node.name, 'label': node.label,
            'estate': str(node.properties.get('estate', '') or ''),
            'module': str(node.properties.get('module', '') or ''),
            'reaches': sorted(reaches),
        }
        if reaches & shared_names:
            row['sharedData'] = sorted(reaches & shared_names)
            follow.append(row)
        else:
            free.append(row)

    follow.sort(key=lambda r: (r['estate'], -len(r['sharedData']), r['name']))
    free.sort(key=lambda r: (r['estate'], r['name']))
    return follow, free


def _reaches(graph: Graph, node_id: str, depth: int = 3) -> set:
    """Database objects a component reaches, directly or through its code."""
    seen = {node_id}
    frontier = [node_id]
    tables = set()
    for _ in range(depth):
        nxt = []
        for current in frontier:
            for rel in graph.outgoing(current):
                target = graph.nodes.get(rel.end_id)
                if target is None or target.node_id in seen:
                    continue
                if rel.rel_type in ACCESS_RELS:
                    tables.add(target.name)
                    continue
                if rel.rel_type in ('EXECUTES', 'EXECUTES_SQL', 'EXECUTES_PLSQL',
                                    'CONTAINS_REGION', 'CONTAINS_PROCESS',
                                    'CONTAINS_ITEM', 'CONTAINS_VALIDATION',
                                    'CONTAINS_COLUMN', 'CONTAINS_BUTTON',
                                    'HAS_UNIT', 'HAS_BODY'):
                    seen.add(target.node_id)
                    nxt.append(target.node_id)
        if not nxt:
            break
        frontier = nxt
    return tables


def render_markdown(result: Dict[str, Any]) -> str:
    out = ['# Modernisation sequence', '',
           'Derived from the federated graph. The rule is that a component may '
           'not be cut over before the data it shares has an owner; the waves '
           'are what follows from that.', '']
    summary = result['summary']
    out += ['| Wave | Items |', '|---|---|',
            f"| 0 Decide | {summary['blockers']} |",
            f"| 1 Together | {summary['cutoverGroups']} group(s) |",
            f"| 2 Follow | {summary['followers']} |",
            f"| 3 Free | {summary['independent']} |", '']

    for wave in result['waves']:
        out += [f"## Wave {wave['wave']} — {wave['title']}", '',
                f"_{wave['rationale']}_", '']
        if not wave['items']:
            out += ['_Nothing in this wave._', '']
            continue
        if wave['wave'] == 0:
            out += ['| Kind | Subject | Detail |', '|---|---|---|']
            for item in wave['items']:
                out.append(f"| {item['kind']} | {item['subject']} | {item['detail']} |")
        elif wave['wave'] == 1:
            for group in wave['items']:
                out += [f"### {group['table']} "
                        f"({', '.join(group['estates'])})", '',
                        '| Component | Label | Estate | Access | Basis |',
                        '|---|---|---|---|---|']
                for member in group['components']:
                    out.append(f"| {member['name']} | {member['label']} | "
                               f"{member['estate']} | {member['access']} | "
                               f"{member['basis']} |")
                out.append('')
        else:
            out += ['| Component | Label | Estate | Shared data |',
                    '|---|---|---|---|']
            for item in wave['items']:
                shared = ', '.join(item.get('sharedData', [])) or '-'
                out.append(f"| {item['name']} | {item['label']} | "
                           f"{item['estate']} | {shared} |")
        out.append('')
    return '\n'.join(out) + '\n'
