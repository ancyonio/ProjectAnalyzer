"""Mermaid sources for the federated graph.

Three diagrams, each answering one question a single-estate diagram cannot:
where the estates meet, which data is contended, and what one change reaches.
Every diagram is a pure function of the graph, so two runs on unchanged input
produce identical files.
"""
from __future__ import annotations

from typing import Dict, List

from analyzer_core.model import Graph

from ..analysis.inventory import (boundary_components, contended_tables,
                                  table_access)

_SAFE = str.maketrans({'"': "'", '\n': ' ', '[': '(', ']': ')',
                       '{': '(', '}': ')'})

ESTATE_STYLE = {
    'tibco': 'fill:#e8f0fe,stroke:#3367d6',
    'apex': 'fill:#e6f4ea,stroke:#188038',
    'oracle': 'fill:#fef7e0,stroke:#b06000',
}


def _id(node_id: str) -> str:
    return 'n' + ''.join(ch if ch.isalnum() else '_' for ch in node_id)


def _label(text: str) -> str:
    return str(text).translate(_SAFE)[:48]


def estate_context(graph: Graph) -> str:
    """The three estates and the database objects that join them."""
    out = ['%% Federated estate context: where the three estates meet.',
           'graph LR']
    meta_estates = (graph.meta or {}).get('estates') or {}
    for estate, info in meta_estates.items():
        out.append(f'  subgraph {estate}["{_label(info.get("title", estate))} '
                   f'({info.get("nodes", 0)} nodes)"]')
        out.append(f'    {estate}_root["{_label(info.get("sourceRoot", "") or estate)}"]')
        out.append('  end')

    shared = [row for row in table_access(graph) if row['estateCount'] > 1]
    if shared:
        out.append('  subgraph shared["Shared data"]')
        for row in shared[:20]:
            out.append(f'    {_id(row["nodeId"])}[("{_label(row["name"])}")]')
        out.append('  end')
    for row in shared[:20]:
        for estate in row['writerEstates']:
            out.append(f'  {estate}_root -->|writes| {_id(row["nodeId"])}')
        for estate in row['readerEstates']:
            if estate not in row['writerEstates']:
                out.append(f'  {estate}_root -.->|reads| {_id(row["nodeId"])}')
    for estate, style in ESTATE_STYLE.items():
        if estate in meta_estates:
            out.append(f'  style {estate}_root {style}')
    return '\n'.join(out) + '\n'


def contended_data(graph: Graph) -> str:
    """Every table more than one estate writes, and who writes it."""
    rows = contended_tables(graph)
    out = ['%% Contended tables: two or more estates writing the same object.',
           'graph TD']
    if not rows:
        out.append('  none["No table is written by more than one estate"]')
        return '\n'.join(out) + '\n'
    for row in rows:
        table = _id(row['nodeId'])
        out.append(f'  {table}[("{_label(row["name"])}")]')
        for rel in graph.incoming(row['nodeId']):
            if rel.rel_type not in ('WRITES_TO', 'INSERTS_INTO', 'UPDATES',
                                    'DELETES_FROM'):
                continue
            writer = graph.nodes.get(rel.start_id)
            if writer is None:
                continue
            estate = str(writer.properties.get('estate', '') or '')
            out.append(f'  {_id(writer.node_id)}["{_label(estate)}: '
                       f'{_label(writer.name)}"]')
            basis = rel.properties.get('basis', 'exact')
            out.append(f'  {_id(writer.node_id)} -->|{rel.rel_type} '
                       f'({basis})| {table}')
    return '\n'.join(out) + '\n'


def cross_estate_flow(graph: Graph) -> str:
    """Components whose data access crosses an estate boundary."""
    rows = boundary_components(graph)
    out = ['%% Cross-estate data flow. Dashed edges are inferred, not extracted.',
           'graph LR']
    if not rows:
        out.append('  none["No component reaches across an estate boundary"]')
        return '\n'.join(out) + '\n'
    seen: set = set()
    for row in rows[:40]:
        node = _id(row['nodeId'])
        if node not in seen:
            out.append(f'  {node}["{_label(row["estate"])}: {_label(row["name"])}"]')
            seen.add(node)
        for rel in graph.outgoing(row['nodeId']):
            if rel.rel_type not in ('READS_FROM', 'WRITES_TO', 'INSERTS_INTO',
                                    'UPDATES', 'DELETES_FROM'):
                continue
            target = graph.nodes.get(rel.end_id)
            if target is None:
                continue
            target_id = _id(target.node_id)
            if target_id not in seen:
                out.append(f'  {target_id}[("{_label(target.name)}")]')
                seen.add(target_id)
            arrow = '-.->' if rel.properties.get('origin') == 'inferred' else '-->'
            confidence = rel.properties.get('confidence')
            label = (f'{rel.rel_type} {confidence}' if confidence is not None
                     else rel.rel_type)
            out.append(f'  {node} {arrow}|{label}| {target_id}')
    return '\n'.join(out) + '\n'


def generate_all(graph: Graph) -> Dict[str, str]:
    return {
        'estate_context.mmd': estate_context(graph),
        'contended_data.mmd': contended_data(graph),
        'cross_estate_flow.mmd': cross_estate_flow(graph),
    }
