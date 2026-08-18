"""Mermaid diagram generation.

Every element is derived from the parsed graph — no assumed components, and
no diagram is drawn for a layer that was not extracted.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from analyzer_core.model import Graph, GraphNode

from ..analysis.traverse import WRITE_RELS, descend

MAX_NODES = 60


def _id(text: str) -> str:
    return 'n' + ''.join(c if c.isalnum() else '_' for c in str(text))


def _esc(text: str) -> str:
    return str(text or '').replace('"', "'").replace('\n', ' ')[:60]


def application_map(graph: Graph) -> str:
    """Application to pages to their data, one level deep."""
    lines = ['flowchart LR', '  %% Generated from graph.json — do not hand-edit']
    applications = graph.by_label('ApexApplication')
    if not applications:
        return '\n'.join(lines + ['  empty["No application parsed"]'])
    application = applications[0]
    lines.append(f'  {_id(application.node_id)}["{_esc(application.name)}<br/>'
                 f'app {application.properties.get("applicationId")}"]:::app')

    pages = sorted(graph.by_label('ApexPage'),
                   key=lambda p: -float(p.properties.get('complexityScore', 0) or 0))
    for page in pages[:MAX_NODES]:
        tier = str(page.properties.get('tier', 'Low')).lower()
        lines.append(f'  {_id(page.node_id)}["{page.properties.get("pageId")}: '
                     f'{_esc(page.name)}<br/>{page.properties.get("tier", "")} '
                     f'({page.properties.get("complexityScore", 0)})"]:::{tier}')
        lines.append(f'  {_id(application.node_id)} --> {_id(page.node_id)}')
    lines += ['',
              '  classDef app fill:#0f172a,stroke:#0f172a,color:#ffffff;',
              '  classDef critical fill:#b91c1c,stroke:#7f1d1d,color:#ffffff;',
              '  classDef high fill:#ea580c,stroke:#9a3412,color:#ffffff;',
              '  classDef medium fill:#facc15,stroke:#a16207,color:#0f172a;',
              '  classDef low fill:#f1f5f9,stroke:#64748b,color:#0f172a;']
    return '\n'.join(lines)


def navigation_map(graph: Graph) -> str:
    """Page navigation graph: how a user moves through the application."""
    lines = ['flowchart TD']
    pages = {p.node_id: p for p in graph.by_label('ApexPage')}
    for page in pages.values():
        lines.append(f'  {_id(page.node_id)}["{page.properties.get("pageId")}: '
                     f'{_esc(page.name)}"]')
    seen = set()
    for rel in graph.rels:
        if rel.rel_type != 'NAVIGATES_TO' or rel.end_id not in pages:
            continue
        source = graph.node(rel.start_id)
        if source is None:
            continue
        origin = source
        if source.label != 'ApexPage':
            from ..analysis.traverse import owning_page
            origin = owning_page(graph, source.node_id) or source
        if origin.node_id not in pages:
            continue
        key = (origin.node_id, rel.end_id, source.label)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f'  {_id(origin.node_id)} -->|{source.label.replace("Apex", "")}| '
                     f'{_id(rel.end_id)}')
    return '\n'.join(lines)


def data_access_map(graph: Graph) -> str:
    """Pages to the tables they read and write."""
    lines = ['flowchart LR']
    tables = {}
    for label in ('DbTable', 'DbView'):
        for table in graph.by_label(label):
            tables[table.node_id] = table

    edges: Dict[str, str] = {}
    for page in graph.by_label('ApexPage'):
        lines.append(f'  {_id(page.node_id)}["{page.properties.get("pageId")}: '
                     f'{_esc(page.name)}"]:::page')
        reach = descend(graph, page.node_id, max_depth=8)
        for node_id in reach:
            for rel in graph.outgoing(node_id):
                if rel.end_id not in tables:
                    continue
                mode = 'writes' if rel.rel_type in WRITE_RELS else 'reads'
                key = f'{page.node_id}->{rel.end_id}'
                if edges.get(key) != 'writes':
                    edges[key] = mode

    for table in tables.values():
        lines.append(f'  {_id(table.node_id)}[("{_esc(table.name)}")]:::table')
    for key, mode in sorted(edges.items()):
        source, target = key.split('->')
        arrow = '==>' if mode == 'writes' else '-->'
        lines.append(f'  {_id(source)} {arrow}|{mode}| {_id(target)}')
    lines += ['',
              '  classDef page fill:#1d4ed8,stroke:#1e3a8a,color:#ffffff;',
              '  classDef table fill:#f1f5f9,stroke:#64748b,color:#0f172a;']
    return '\n'.join(lines)


def dependency_chain(graph: Graph, page: GraphNode) -> str:
    """The full chain for one page: region -> SQL -> table -> package."""
    lines = ['flowchart LR',
             f'  {_id(page.node_id)}["Page {page.properties.get("pageId")}: '
             f'{_esc(page.name)}"]:::page']
    reach = descend(graph, page.node_id, max_depth=7)
    shown = set(list(reach)[:MAX_NODES])
    for node_id in shown:
        node = graph.node(node_id)
        if node is None:
            continue
        unresolved = 'Unresolved' in str(node.properties.get('extraLabels', ''))
        style = {'SqlStatement': 'sql', 'PlsqlBlock': 'plsql', 'DbTable': 'table',
                 'DbView': 'table', 'DbPackage': 'pkg',
                 'DbProgramUnit': 'pkg'}.get(node.label, 'component')
        if unresolved:
            style = 'unresolved'
        shape = ('[("%s")]' if style == 'table' else '["%s"]')
        name = _esc(node.name) + (' (unresolved)' if unresolved else '')
        label = f'{node.label.replace("Apex", "").replace("Db", "")}<br/>{name}'
        lines.append(f'  {_id(node_id)}{shape % label}:::{style}')
    for node_id in list(shown) + [page.node_id]:
        for rel in graph.outgoing(node_id):
            if rel.end_id not in shown:
                continue
            # an inferred edge the analyzer could not pin down is drawn dashed,
            # so a reader never mistakes a guess for an asserted dependency
            resolution = str(rel.properties.get('resolution', ''))
            arrow = '-.->' if resolution in ('dynamic', 'unresolved', 'heuristic') else '-->'
            label = rel.rel_type + (f' ({resolution})' if arrow == '-.->' else '')
            lines.append(f'  {_id(node_id)} {arrow}|{label}| {_id(rel.end_id)}')
    lines += ['',
              '  classDef page fill:#1d4ed8,stroke:#1e3a8a,color:#ffffff;',
              '  classDef sql fill:#0ea5e9,stroke:#0369a1,color:#ffffff;',
              '  classDef plsql fill:#7c3aed,stroke:#4c1d95,color:#ffffff;',
              '  classDef table fill:#f1f5f9,stroke:#64748b,color:#0f172a;',
              '  classDef pkg fill:#16a34a,stroke:#166534,color:#ffffff;',
              '  classDef component fill:#e2e8f0,stroke:#94a3b8,color:#0f172a;',
              '  classDef unresolved fill:#ffffff,stroke:#b91c1c,color:#b91c1c,'
              'stroke-dasharray: 4 3;']
    return '\n'.join(lines)


def entity_relationships(graph: Graph, limit: int = 20) -> str:
    """ER diagram from the foreign key graph."""
    lines = ['erDiagram']
    tables = sorted(graph.by_label('DbTable'),
                    key=lambda t: -int(t.properties.get('fanIn', 0) or 0))[:limit]
    known = {t.node_id for t in tables}
    for table in tables:
        columns = [graph.node(r.end_id) for r in graph.outgoing(table.node_id)
                   if r.rel_type == 'HAS_COLUMN']
        lines.append(f'  {table.name} {{')
        for column in [c for c in columns if c is not None][:12]:
            data_type = str(column.properties.get('dataType', 'unknown')).split('(')[0]
            key = 'PK' if column.properties.get('isPk') else (
                'FK' if column.properties.get('isFk') else '')
            lines.append(f'    {data_type or "unknown"} {column.name} {key}'.rstrip())
        lines.append('  }')
    for constraint in graph.by_label('DbConstraint'):
        if str(constraint.properties.get('constraintType', '')).upper() not in (
                'FOREIGN_KEY', 'R'):
            continue
        child = constraint.properties.get('tableName')
        parents = [graph.node(r.end_id) for r in graph.outgoing(constraint.node_id)
                   if r.rel_type == 'REFERENCES_TABLE']
        for parent in parents:
            if parent is not None and parent.node_id in known and child:
                lines.append(f'  {parent.name} ||--o{{ {child} : "{constraint.name}"')
    return '\n'.join(lines)


def issue_map(graph: Graph) -> str:
    """Findings by severity, and what they attach to."""
    lines = ['flowchart LR']
    issues = graph.by_label('Issue')
    if not issues:
        return '\n'.join(lines + ['  none["No findings"]'])
    by_severity: Dict[str, List] = {}
    for issue in issues:
        by_severity.setdefault(str(issue.properties.get('severity', 'INFO')), []).append(issue)
    for severity, group in by_severity.items():
        lines.append(f'  {_id(severity)}["{severity}<br/>{len(group)} finding(s)"]'
                     f':::{severity.lower()}')
        for issue in group[:15]:
            target = next((graph.node(r.start_id) for r in graph.incoming(issue.node_id)
                           if r.rel_type == 'HAS_ISSUE'), None)
            label = f'{issue.properties.get("ruleId")}<br/>{_esc(target.name if target else "")}'
            lines.append(f'  {_id(issue.node_id)}["{label}"]')
            lines.append(f'  {_id(severity)} --> {_id(issue.node_id)}')
    lines += ['',
              '  classDef critical fill:#b91c1c,stroke:#7f1d1d,color:#ffffff;',
              '  classDef high fill:#ea580c,stroke:#9a3412,color:#ffffff;',
              '  classDef medium fill:#facc15,stroke:#a16207,color:#0f172a;',
              '  classDef low fill:#f1f5f9,stroke:#64748b,color:#0f172a;']
    return '\n'.join(lines)


def generate_all(graph: Graph) -> Dict[str, str]:
    produced = {
        'application_map.mmd': application_map(graph),
        'navigation_map.mmd': navigation_map(graph),
        'data_access_map.mmd': data_access_map(graph),
        'entity_relationships.mmd': entity_relationships(graph),
        'issue_map.mmd': issue_map(graph),
    }
    pages = sorted(graph.by_label('ApexPage'),
                   key=lambda p: -float(p.properties.get('complexityScore', 0) or 0))
    for page in pages[:10]:
        name = f'page_{page.properties.get("pageId")}_dependencies.mmd'
        produced[name] = dependency_chain(graph, page)
    produced['README.md'] = _readme(produced, graph)
    return produced


def _readme(produced: Dict[str, str], graph: Graph) -> str:
    lines = ['# Generated Diagrams', '',
             'Regenerate with `apex-analyze diagrams --format both`. Every element is',
             'derived from the parsed knowledge graph — no assumed components.', '',
             f'Source graph: {len(graph.nodes)} nodes / {len(graph.rels)} relationships.',
             '', '| File | Type |', '|---|---|']
    for name in sorted(produced):
        if name == 'README.md':
            continue
        lines.append(f'| `{name}` | {"Mermaid" if name.endswith(".mmd") else "PlantUML"} |')
    lines += ['', '## Rendering', '',
              '- **Mermaid:** renders natively in GitHub, VS Code, or https://mermaid.live',
              '- **PlantUML:** `plantuml -tsvg <file>.puml`, or the VS Code PlantUML '
              'extension. No remote includes are used, so an offline server works.']
    return '\n'.join(lines) + '\n'
