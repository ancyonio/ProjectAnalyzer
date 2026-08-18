"""Mermaid diagram sources.

Every diagram is generated from the graph, so a diagram and a count in a report
can never disagree. Nodes are capped per diagram: a 400-package estate renders
as an unreadable hairball, and an unreadable diagram is worse than none.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List

from analyzer_core.model import Graph

MAX_NODES = 60


def _safe(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]', '_', str(text or 'n'))[:60]


def _label(text: str) -> str:
    return str(text or '').replace('"', "'")[:48]


def schema_overview(graph: Graph) -> str:
    """Schemas and what they own."""
    out = ['graph TD', '  %% Schema ownership']
    for schema in sorted(graph.by_label('DbSchema'), key=lambda n: n.name):
        sid = _safe(schema.node_id)
        out.append(f'  {sid}["{_label(schema.name)}"]:::schema')
        owned = defaultdict(int)
        for rel in graph.outgoing(schema.node_id):
            node = graph.nodes.get(rel.end_id)
            if rel.rel_type == 'OWNS' and node is not None:
                owned[node.label] += 1
        for label, count in sorted(owned.items()):
            bucket = f'{sid}_{_safe(label)}'
            out.append(f'  {bucket}["{label}<br/>{count}"]:::bucket')
            out.append(f'  {sid} --> {bucket}')
    out.append('  classDef schema fill:#0A6B6B,stroke:#06504F,color:#fff')
    out.append('  classDef bucket fill:#EFF4F6,stroke:#B9C8D1,color:#101C25')
    return '\n'.join(out) + '\n'


def package_structure(graph: Graph) -> str:
    """Packages, their halves and the units each half holds."""
    out = ['graph LR', '  %% Package spec/body structure']
    for package in sorted(graph.by_label('DbPackage'), key=lambda n: n.name)[:20]:
        pid = _safe(package.node_id)
        out.append(f'  {pid}["{_label(package.name)}"]:::pkg')
        for rel in graph.outgoing(package.node_id):
            half = graph.nodes.get(rel.end_id)
            if half is None or rel.rel_type not in ('HAS_SPEC', 'HAS_BODY'):
                continue
            hid = _safe(half.node_id)
            kind = 'spec' if half.label == 'PackageSpec' else 'body'
            out.append(f'  {hid}["{kind}"]:::{kind}')
            out.append(f'  {pid} -->|{rel.rel_type}| {hid}')
            units = [graph.nodes[r.end_id] for r in graph.outgoing(half.node_id)
                     if r.rel_type == 'HAS_UNIT' and r.end_id in graph.nodes]
            for unit in units[:8]:
                uid = _safe(unit.node_id)
                out.append(f'  {uid}("{_label(unit.name)}"):::unit')
                out.append(f'  {hid} --> {uid}')
    out.append('  classDef pkg fill:#0A6B6B,stroke:#06504F,color:#fff')
    out.append('  classDef spec fill:#DFEFEE,stroke:#0A6B6B,color:#06504F')
    out.append('  classDef body fill:#F6EBD7,stroke:#8A5806,color:#8A5806')
    out.append('  classDef unit fill:#FFF,stroke:#B9C8D1,color:#101C25')
    return '\n'.join(out) + '\n'


def data_access_map(graph: Graph) -> str:
    """Which units read and which write which tables."""
    out = ['graph LR', '  %% Data access: solid = write, dotted = read']
    statement_owner: Dict[str, List[str]] = defaultdict(list)
    for rel in graph.rels:
        if rel.rel_type == 'EXECUTES_SQL':
            statement_owner[rel.end_id].append(rel.start_id)

    seen = set()
    drawn = 0
    for rel in graph.rels:
        if rel.rel_type not in ('READS_FROM', 'WRITES_TO') or drawn >= MAX_NODES:
            continue
        table = graph.nodes.get(rel.end_id)
        if table is None:
            continue
        for owner_id in statement_owner.get(rel.start_id, []):
            owner = graph.nodes.get(owner_id)
            if owner is None or owner.label not in ('DbProgramUnit', 'DbTrigger'):
                continue
            key = (owner_id, rel.end_id, rel.rel_type)
            if key in seen:
                continue
            seen.add(key)
            drawn += 1
            uid, tid = _safe(owner_id), _safe(rel.end_id)
            out.append(f'  {uid}("{_label(owner.name)}"):::unit')
            out.append(f'  {tid}[("{_label(table.name)}")]:::table')
            arrow = '-->' if rel.rel_type == 'WRITES_TO' else '-.->'
            out.append(f'  {uid} {arrow}|{rel.rel_type}| {tid}')
    if drawn == 0:
        out.append('  none["No data-access edges in this graph"]')
    out.append('  classDef unit fill:#FFF,stroke:#0A6B6B,color:#101C25')
    out.append('  classDef table fill:#EFF4F6,stroke:#B9C8D1,color:#101C25')
    return '\n'.join(out) + '\n'


def call_graph(graph: Graph) -> str:
    out = ['graph LR', '  %% Unit call graph']
    edges = [r for r in graph.rels if r.rel_type == 'CALLS'][:MAX_NODES]
    for rel in edges:
        caller, callee = graph.nodes.get(rel.start_id), graph.nodes.get(rel.end_id)
        if caller is None or callee is None:
            continue
        out.append(f'  {_safe(rel.start_id)}("{_label(caller.name)}")')
        out.append(f'  {_safe(rel.end_id)}("{_label(callee.name)}")')
        out.append(f'  {_safe(rel.start_id)} --> {_safe(rel.end_id)}')
    if not edges:
        out.append('  none["No CALLS edges in this graph"]')
    return '\n'.join(out) + '\n'


def trigger_map(graph: Graph) -> str:
    out = ['graph LR', '  %% Triggers: control flow a caller never mentions']
    drawn = 0
    for rel in graph.rels:
        if rel.rel_type != 'FIRES_ON':
            continue
        trigger, table = graph.nodes.get(rel.start_id), graph.nodes.get(rel.end_id)
        if trigger is None or table is None:
            continue
        drawn += 1
        out.append(f'  {_safe(rel.start_id)}{{{{"{_label(trigger.name)}"}}}}')
        out.append(f'  {_safe(rel.end_id)}[("{_label(table.name)}")]')
        event = _label(trigger.properties.get("triggeringEvent", "")) or "FIRES_ON"
        out.append(f'  {_safe(rel.start_id)} -->|{event}| {_safe(rel.end_id)}')
    if not drawn:
        out.append('  none["No triggers in this graph"]')
    return '\n'.join(out) + '\n'


def generate_all(graph: Graph) -> Dict[str, str]:
    return {
        'schema_overview.mmd': schema_overview(graph),
        'package_structure.mmd': package_structure(graph),
        'data_access_map.mmd': data_access_map(graph),
        'call_graph.mmd': call_graph(graph),
        'trigger_map.mmd': trigger_map(graph),
    }
