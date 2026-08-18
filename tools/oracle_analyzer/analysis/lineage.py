"""Data lineage.

Walks the data-access edges to answer where a table's contents come from and
where they go. This is the capability that justifies materialising
`SqlStatement` as a node rather than hanging access edges straight off the
program unit: the statement is what carries the verb and the read set.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from analyzer_core.model import Graph, GraphNode

_WRITE_RELS = ('INSERTS_INTO', 'UPDATES', 'DELETES_FROM', 'WRITES_TO')


def _executors(graph: Graph, statement_id: str) -> List[GraphNode]:
    return [graph.nodes[r.start_id] for r in graph.incoming(statement_id)
            if r.rel_type == 'EXECUTES_SQL' and r.start_id in graph.nodes]


def upstream(graph: Graph, table: GraphNode) -> List[Dict[str, Any]]:
    """Statements that write the table, and what each of them reads to do it."""
    rows = []
    for rel in graph.incoming(table.node_id):
        if rel.rel_type not in _WRITE_RELS or rel.rel_type == 'WRITES_TO':
            continue
        statement = graph.nodes.get(rel.start_id)
        if statement is None or statement.label != 'SqlStatement':
            continue
        reads = sorted({graph.nodes[r.end_id].name
                        for r in graph.outgoing(statement.node_id)
                        if r.rel_type == 'READS_FROM' and r.end_id in graph.nodes})
        for unit in _executors(graph, statement.node_id) or [None]:
            rows.append({
                'verb': rel.rel_type,
                'statement': statement.name,
                'unit': unit.name if unit else '(unattributed)',
                'package': unit.properties.get('packageName', '') if unit else '',
                'filePath': unit.properties.get('filePath', '') if unit else '',
                'readsFrom': reads,
            })
    return sorted(rows, key=lambda r: (r['unit'], r['verb']))


def downstream(graph: Graph, table: GraphNode) -> List[Dict[str, Any]]:
    """Everything that reads the table, and what it writes as a result."""
    rows = []
    for rel in graph.incoming(table.node_id):
        if rel.rel_type != 'READS_FROM':
            continue
        statement = graph.nodes.get(rel.start_id)
        if statement is None or statement.label != 'SqlStatement':
            continue
        writes = sorted({graph.nodes[r.end_id].name
                         for r in graph.outgoing(statement.node_id)
                         if r.rel_type == 'WRITES_TO' and r.end_id in graph.nodes})
        for unit in _executors(graph, statement.node_id) or [None]:
            rows.append({
                'statement': statement.name,
                'unit': unit.name if unit else '(unattributed)',
                'package': unit.properties.get('packageName', '') if unit else '',
                'filePath': unit.properties.get('filePath', '') if unit else '',
                'writesTo': writes,
            })
    return sorted(rows, key=lambda r: (r['unit'], r['statement']))


def views_over(graph: Graph, table: GraphNode) -> List[str]:
    return sorted({graph.nodes[r.start_id].name
                   for r in graph.incoming(table.node_id)
                   if r.rel_type == 'DEPENDS_ON' and r.start_id in graph.nodes
                   and graph.nodes[r.start_id].label in ('DbView',
                                                         'DbMaterializedView')})


def triggers_on(graph: Graph, table: GraphNode) -> List[Dict[str, str]]:
    return [{'name': graph.nodes[r.start_id].name,
             'event': graph.nodes[r.start_id].properties.get('triggeringEvent', '')}
            for r in graph.incoming(table.node_id)
            if r.rel_type == 'FIRES_ON' and r.start_id in graph.nodes]


def lineage(graph: Graph, target: GraphNode) -> Dict[str, Any]:
    return {
        'target': target.name,
        'label': target.label,
        'owner': target.properties.get('owner', ''),
        'columns': sorted(graph.nodes[r.end_id].name
                          for r in graph.outgoing(target.node_id)
                          if r.rel_type == 'HAS_COLUMN' and r.end_id in graph.nodes),
        'upstream': upstream(graph, target),
        'downstream': downstream(graph, target),
        'views': views_over(graph, target),
        'triggers': triggers_on(graph, target),
    }


def render_markdown(result: Dict[str, Any]) -> str:
    out = [f"# Data Lineage — {result['label']}: {result['target']}", '']
    if result['columns']:
        out += [f"**Columns:** {', '.join(result['columns'])}", '']

    out += ['## Written by', '']
    if result['upstream']:
        out += ['| Unit | Verb | Reads from | Source |', '|---|---|---|---|']
        for row in result['upstream']:
            reads = ', '.join(row['readsFrom']) or '-'
            unit = f"{row['package']}.{row['unit']}" if row['package'] else row['unit']
            out.append(f"| {unit} | {row['verb']} | {reads} | {row['filePath']} |")
    else:
        out.append('_Nothing in the analysed tree writes this object._')

    out += ['', '## Read by', '']
    if result['downstream']:
        out += ['| Unit | Writes to | Source |', '|---|---|---|']
        for row in result['downstream']:
            writes = ', '.join(row['writesTo']) or '-'
            unit = f"{row['package']}.{row['unit']}" if row['package'] else row['unit']
            out.append(f"| {unit} | {writes} | {row['filePath']} |")
    else:
        out.append('_Nothing in the analysed tree reads this object._')

    if result['views']:
        out += ['', '## Views built on it', '', ', '.join(result['views'])]
    if result['triggers']:
        out += ['', '## Triggers', '']
        out += ['| Trigger | Event |', '|---|---|']
        out += [f"| {t['name']} | {t['event']} |" for t in result['triggers']]
    return '\n'.join(out) + '\n'
