"""Deterministic Mermaid diagram generation.

Every node and edge below comes from the parsed graph. Nothing is invented,
which is exactly the property `Step_1_Architecture_Diagrams.md` demands:
no assumed components, no placeholder services, no fictional patterns.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from ..analysis.inventory import module_dependencies, process_call_edges
from ..model import Graph, GraphNode

MAX_NODES = 60


def _id(text: str) -> str:
    """Mermaid-safe node id."""
    return re.sub(r'[^A-Za-z0-9_]', '_', text)[:60] or 'n'


def _esc(text: str) -> str:
    """Escape label text: angle brackets and quotes break Mermaid parsing."""
    return (str(text).replace('"', "'")
            .replace('<', '(').replace('>', ')')
            .replace('|', '/').replace('\n', ' ')[:70])


# ──────────────────────────────────────────────────────────────
def context_diagram(graph: Graph) -> str:
    """System context: actors -> entry points -> external systems."""
    lines = ['flowchart LR',
             '  %% System context derived from parsed entry points and shared resources',
             '  subgraph External_Consumers["External consumers"]',
             '    CLIENT["Client applications"]',
             '  end',
             '']
    entry_groups: Dict[str, List[GraphNode]] = defaultdict(list)
    for proc in graph.by_label('BWProcess'):
        etype = proc.properties.get('entryType', 'NONE')
        if etype not in (None, '', 'NONE'):
            entry_groups[str(etype)].append(proc)

    lines.append('  subgraph TIBCO["TIBCO BusinessWorks estate"]')
    for etype, procs in sorted(entry_groups.items()):
        lines.append(f'    subgraph EP_{_id(etype)}["{_esc(etype)}"]')
        for proc in procs[:12]:
            lines.append(f'      {_id(proc.node_id)}["{_esc(proc.name)}"]')
        lines.append('    end')
    lines.append('  end')
    lines.append('')

    systems = graph.by_label('System')
    if systems:
        lines.append('  subgraph Externals["External systems"]')
        for sysnode in systems:
            lines.append(f'    {_id(sysnode.node_id)}[("{_esc(sysnode.name)}")]')
        lines.append('  end')
        lines.append('')

    for etype, procs in sorted(entry_groups.items()):
        for proc in procs[:12]:
            lines.append(f'  CLIENT -->|{_esc(etype)}| {_id(proc.node_id)}')

    for res in graph.by_label('SharedResource'):
        users = [graph.node(r.start_id) for r in graph.incoming(res.node_id)
                 if r.rel_type == 'REFERENCES']
        targets = [graph.node(r.end_id) for r in graph.outgoing(res.node_id)
                   if r.rel_type == 'CONNECTS_TO']
        for user in users[:8]:
            for target in targets:
                if user and target:
                    lines.append(f'  {_id(user.node_id)} -->|'
                                 f'{_esc(res.properties.get("technology", "uses"))}| '
                                 f'{_id(target.node_id)}')
    return '\n'.join(lines)


def container_diagram(graph: Graph) -> str:
    """Module-level container view with cross-module call edges."""
    lines = ['flowchart TB',
             '  %% Container view: one box per TIBCO module']
    for mod in sorted(graph.modules()):
        members = [n for n in graph.nodes.values() if n.module == mod]
        procs = [n for n in members if n.label == 'BWProcess']
        schemas = [n for n in members if n.label == 'XSD']
        entries = [p for p in procs
                   if p.properties.get('entryType') not in (None, '', 'NONE')]
        lines.append(f'  subgraph MOD_{_id(mod)}["{_esc(mod)}"]')
        lines.append(f'    {_id(mod)}_stats["{len(procs)} processes<br/>'
                     f'{len(schemas)} schemas<br/>{len(entries)} entry points"]')
        for proc in entries[:8]:
            lines.append(f'    {_id(proc.node_id)}["{_esc(proc.name)}<br/>'
                         f'<small>{_esc(proc.properties.get("entryType", ""))}</small>"]')
        lines.append('  end')
    for dep in module_dependencies(graph):
        lines.append(f'  MOD_{_id(dep["from"])} -->|{dep["calls"]} calls| MOD_{_id(dep["to"])}')
    return '\n'.join(lines)


def component_diagram(graph: Graph, module: Optional[str] = None) -> str:
    """Component view: processes, their schemas and their external touchpoints."""
    procs = [p for p in graph.by_label('BWProcess')
             if module is None or p.module == module]
    procs = sorted(procs, key=lambda p: -float(p.properties.get('complexityScore', 0) or 0))
    procs = procs[:MAX_NODES]
    keep = {p.node_id for p in procs}

    lines = ['flowchart LR',
             f'  %% Component view{" for module " + module if module else ""}']
    lines.append('  subgraph Processes["BW Processes"]')
    for proc in procs:
        entry = proc.properties.get('entryType', 'NONE')
        badge = f'<br/><small>{_esc(entry)}</small>' if entry not in (None, '', 'NONE') else ''
        lines.append(f'    {_id(proc.node_id)}["{_esc(proc.name)}{badge}"]')
    lines.append('  end')

    used_schemas = set()
    for proc in procs:
        for rel in graph.outgoing(proc.node_id):
            if rel.rel_type == 'USES_XSD':
                used_schemas.add(rel.end_id)
    if used_schemas:
        lines.append('  subgraph Schemas["XML Schemas"]')
        for sid in sorted(used_schemas):
            node = graph.node(sid)
            if node:
                lines.append(f'    {_id(sid)}[/"{_esc(node.name)}"/]')
        lines.append('  end')

    for proc in procs:
        for rel in graph.outgoing(proc.node_id):
            if rel.rel_type == 'USES_XSD':
                lines.append(f'  {_id(proc.node_id)} --> {_id(rel.end_id)}')
            elif rel.rel_type == 'REFERENCES':
                other = graph.node(rel.end_id)
                if other:
                    lines.append(f'  {_id(proc.node_id)} -.->|'
                                 f'{_esc(other.properties.get("technology", "resource"))}| '
                                 f'{_id(rel.end_id)}["{_esc(other.name)}"]')
    for src, dst, act in process_call_edges(graph):
        if src in keep and dst in keep:
            lines.append(f'  {_id(src)} ==>|{_esc(act)}| {_id(dst)}')
    return '\n'.join(lines)


def process_flow(graph: Graph, process: GraphNode) -> str:
    """Activity-level flowchart for a single process, from real transitions."""
    activities = [graph.node(r.end_id) for r in graph.outgoing(process.node_id)
                  if r.rel_type == 'EXECUTES']
    activities = [a for a in activities if a]
    activities.sort(key=lambda a: int(a.properties.get('order', 0) or 0))
    act_ids = {a.node_id for a in activities}

    lines = [f'%% Process: {process.name} ({process.file_path})',
             'flowchart TD']
    entry = process.properties.get('entryType', 'NONE')
    if entry not in (None, '', 'NONE'):
        lines.append(f'  START(["{_esc(entry)}"]) --> {_id(activities[0].node_id)}'
                     if activities else f'  START(["{_esc(entry)}"])')
    for act in activities:
        category = str(act.properties.get('category', ''))
        spring = str(act.properties.get('springEquivalent', ''))
        shape_open, shape_close = '[', ']'
        if category in ('CATCH', 'GENERATE_ERROR', 'RETHROW'):
            shape_open, shape_close = '{{', '}}'
        elif category.startswith('JDBC') or category.startswith('JMS'):
            shape_open, shape_close = '[(', ')]'
        lines.append(f'  {_id(act.node_id)}{shape_open}"{_esc(act.name)}<br/>'
                     f'<small>{_esc(spring)}</small>"{shape_close}')

    for rel in graph.rels:
        if rel.rel_type != 'TRANSITIONS_TO':
            continue
        if rel.start_id not in act_ids or rel.end_id not in act_ids:
            continue
        ctype = str(rel.properties.get('conditionType', 'always'))
        cond = str(rel.properties.get('condition', ''))[:40]
        if ctype == 'always':
            lines.append(f'  {_id(rel.start_id)} --> {_id(rel.end_id)}')
        elif ctype == 'error':
            lines.append(f'  {_id(rel.start_id)} -.->|error| {_id(rel.end_id)}')
        else:
            label = _esc(cond or ctype)
            lines.append(f'  {_id(rel.start_id)} -->|{label}| {_id(rel.end_id)}')
    return '\n'.join(lines)


def schema_usage_map(graph: Graph) -> str:
    """Which process uses which schema - the contract-freeze picture."""
    lines = ['flowchart LR', '  %% Schema usage: BWProcess -[USES_XSD]-> XSD']
    edges = [r for r in graph.rels if r.rel_type == 'USES_XSD']
    procs = {r.start_id for r in edges}
    schemas = {r.end_id for r in edges}
    for pid in sorted(procs)[:MAX_NODES]:
        node = graph.node(pid)
        if node:
            lines.append(f'  {_id(pid)}["{_esc(node.name)}"]')
    for sid in sorted(schemas)[:MAX_NODES]:
        node = graph.node(sid)
        if node:
            users = len([r for r in graph.incoming(sid) if r.rel_type == 'USES_XSD'])
            lines.append(f'  {_id(sid)}[/"{_esc(node.name)}<br/>'
                         f'<small>{users} consumer(s)</small>"/]')
    for rel in edges:
        lines.append(f'  {_id(rel.start_id)} --> {_id(rel.end_id)}')
    return '\n'.join(lines)


def er_diagram(graph: Graph, limit: int = 15) -> str:
    """ER-style view of the canonical data model, from XSD complex types."""
    lines = ['erDiagram']
    schemas = sorted(graph.by_label('XSD'),
                     key=lambda x: -int(x.properties.get('elementCount', 0) or 0))[:limit]
    for xsd in schemas:
        entity = _id(xsd.name).upper()
        elements = [graph.node(r.end_id) for r in graph.outgoing(xsd.node_id)
                    if r.rel_type == 'CONTAINS']
        elements = [e for e in elements if e and e.label == 'Element'][:15]
        lines.append(f'  {entity} {{')
        for elem in elements:
            java_type = str(elem.properties.get('javaType', 'Object')).split('.')[-1]
            required = 'PK' if elem.properties.get('required') else ''
            lines.append(f'    {java_type} {_id(elem.name)} {required}'.rstrip())
        lines.append('  }')
    for rel in graph.rels:
        if rel.rel_type != 'IMPORTS_SCHEMA':
            continue
        a, b = graph.node(rel.start_id), graph.node(rel.end_id)
        if a and b and a.label == 'XSD' and b.label == 'XSD':
            lines.append(f'  {_id(a.name).upper()} ||--o{{ {_id(b.name).upper()} : imports')
    return '\n'.join(lines)


def dependency_graph(graph: Graph) -> str:
    """Process-to-process call hierarchy."""
    lines = ['flowchart LR', '  %% Process call hierarchy']
    seen = set()
    for src, dst, act in process_call_edges(graph):
        for nid in (src, dst):
            if nid in seen:
                continue
            seen.add(nid)
            node = graph.node(nid)
            if node:
                lines.append(f'  {_id(nid)}["{_esc(node.name)}"]')
        lines.append(f'  {_id(src)} -->|{_esc(act)}| {_id(dst)}')
    if len(lines) == 2:
        lines.append('  NONE["No inter-process calls detected"]')
    return '\n'.join(lines)


def integration_diagram(graph: Graph) -> str:
    """Outbound integrations grouped by technology."""
    lines = ['flowchart LR', '  %% Adapters and external systems']
    for res in graph.by_label('SharedResource'):
        lines.append(f'  {_id(res.node_id)}["{_esc(res.name)}<br/>'
                     f'<small>{_esc(res.properties.get("springEquivalent", ""))}</small>"]')
        for rel in graph.outgoing(res.node_id):
            if rel.rel_type == 'CONNECTS_TO':
                target = graph.node(rel.end_id)
                if target:
                    lines.append(f'  {_id(res.node_id)} --> {_id(rel.end_id)}'
                                 f'[("{_esc(target.name)}")]')
        for rel in graph.incoming(res.node_id):
            if rel.rel_type == 'REFERENCES':
                user = graph.node(rel.start_id)
                if user:
                    lines.append(f'  {_id(rel.start_id)}["{_esc(user.name)}"] '
                                 f'--> {_id(res.node_id)}')
    if len(lines) == 2:
        lines.append('  NONE["No shared resources detected"]')
    return '\n'.join(lines)


def generate_all(graph: Graph) -> Dict[str, str]:
    """All standard Mermaid diagrams, keyed by relative output path."""
    out: Dict[str, str] = {
        'mermaid/architecture-flows/system-context.mmd': context_diagram(graph),
        'mermaid/component-diagrams/module-containers.mmd': container_diagram(graph),
        'mermaid/component-diagrams/components.mmd': component_diagram(graph),
        'mermaid/architecture-flows/process-dependencies.mmd': dependency_graph(graph),
        'mermaid/data-flow-diagrams/schema-usage-map.mmd': schema_usage_map(graph),
        'mermaid/er-diagrams/canonical-data-model.mmd': er_diagram(graph),
        'mermaid/architecture-flows/integration-surface.mmd': integration_diagram(graph),
    }
    top = sorted(graph.by_label('BWProcess'),
                 key=lambda p: -float(p.properties.get('complexityScore', 0) or 0))[:12]
    for proc in top:
        slug = _id(proc.name).lower()
        out[f'mermaid/architecture-flows/process-{slug}.mmd'] = process_flow(graph, proc)
    return out
