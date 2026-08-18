"""Deterministic PlantUML diagram generation.

Portability rules enforced here (from `Step_1_Architecture_Diagrams.md`):
no `!theme`, no remote `!include`, no orphan `note top :` — so every file
renders on an offline PlantUML server. C4-style views are expressed with
plain packages and stereotypes rather than the C4-PlantUML macro library,
which would require a network include.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Optional

from ..analysis.inventory import module_dependencies, process_call_edges
from ..model import Graph, GraphNode

HEADER = ['@startuml', 'skinparam shadowing false',
          'skinparam defaultFontName "Segoe UI"',
          'skinparam componentStyle rectangle',
          'skinparam wrapWidth 220', '']
FOOTER = ['', '@enduml']


def _alias(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]', '_', str(text))[:60] or 'n'


def _esc(text: str) -> str:
    """Escape label text: angle brackets collide with PlantUML stereotypes."""
    return (str(text).replace('"', "'")
            .replace('<', '(').replace('>', ')')
            .replace('\n', ' ')[:70])


def c4_context(graph: Graph) -> str:
    lines = list(HEADER) + ['title System Context - TIBCO BusinessWorks estate', '',
                            'actor "Client application" as CLIENT']
    entry_groups: Dict[str, List[GraphNode]] = defaultdict(list)
    for proc in graph.by_label('BWProcess'):
        etype = str(proc.properties.get('entryType', 'NONE'))
        if etype not in ('', 'NONE'):
            entry_groups[etype].append(proc)

    lines.append('rectangle "TIBCO BW estate" <<system>> {')
    for etype, procs in sorted(entry_groups.items()):
        lines.append(f'  package "{_esc(etype)}" {{')
        for proc in procs[:12]:
            lines.append(f'    component "{_esc(proc.name)}" as {_alias(proc.node_id)}')
        lines.append('  }')
    lines.append('}')

    for sysnode in graph.by_label('System'):
        lines.append(f'database "{_esc(sysnode.name)}" as {_alias(sysnode.node_id)} <<external>>')

    for etype, procs in sorted(entry_groups.items()):
        for proc in procs[:12]:
            lines.append(f'CLIENT --> {_alias(proc.node_id)} : {_esc(etype)}')

    for res in graph.by_label('SharedResource'):
        users = [graph.node(r.start_id) for r in graph.incoming(res.node_id)
                 if r.rel_type == 'REFERENCES']
        targets = [graph.node(r.end_id) for r in graph.outgoing(res.node_id)
                   if r.rel_type == 'CONNECTS_TO']
        tech = _esc(res.properties.get('technology', 'uses'))
        for user in users[:8]:
            for target in targets:
                if user and target:
                    lines.append(f'{_alias(user.node_id)} --> '
                                 f'{_alias(target.node_id)} : {tech}')
    return '\n'.join(lines + FOOTER)


def c4_container(graph: Graph) -> str:
    lines = list(HEADER) + ['title Container View - TIBCO modules', '']
    for mod in sorted(graph.modules()):
        members = [n for n in graph.nodes.values() if n.module == mod]
        procs = [n for n in members if n.label == 'BWProcess']
        schemas = [n for n in members if n.label == 'XSD']
        entries = [p for p in procs
                   if p.properties.get('entryType') not in (None, '', 'NONE')]
        lines.append(f'package "{_esc(mod)}" as {_alias(mod)} {{')
        lines.append(f'  component "{len(procs)} processes / {len(schemas)} schemas / '
                     f'{len(entries)} entry points" as {_alias(mod)}_stats')
        for proc in entries[:8]:
            lines.append(f'  component "{_esc(proc.name)}\\n<<{_esc(proc.properties.get("entryType", ""))}>>" '
                         f'as {_alias(proc.node_id)}')
        lines.append('}')
    for dep in module_dependencies(graph):
        lines.append(f'{_alias(dep["from"])} --> {_alias(dep["to"])} : {dep["calls"]} calls')
    return '\n'.join(lines + FOOTER)


def c4_component(graph: Graph, module: Optional[str] = None) -> str:
    procs = [p for p in graph.by_label('BWProcess')
             if module is None or p.module == module]
    procs = sorted(procs, key=lambda p: -float(p.properties.get('complexityScore', 0) or 0))[:40]
    keep = {p.node_id for p in procs}

    title = f'Component View{" - " + module if module else ""}'
    lines = list(HEADER) + [f'title {title}', '', 'package "Processes" {']
    for proc in procs:
        entry = str(proc.properties.get('entryType', 'NONE'))
        stereo = f'\\n<<{_esc(entry)}>>' if entry not in ('', 'NONE') else ''
        lines.append(f'  component "{_esc(proc.name)}{stereo}" as {_alias(proc.node_id)}')
    lines.append('}')

    schemas = {r.end_id for p in procs for r in graph.outgoing(p.node_id)
               if r.rel_type == 'USES_XSD'}
    if schemas:
        lines.append('package "Schemas" {')
        for sid in sorted(schemas):
            node = graph.node(sid)
            if node:
                lines.append(f'  artifact "{_esc(node.name)}" as {_alias(sid)}')
        lines.append('}')

    for proc in procs:
        for rel in graph.outgoing(proc.node_id):
            if rel.rel_type == 'USES_XSD':
                lines.append(f'{_alias(proc.node_id)} ..> {_alias(rel.end_id)} : uses')
    for src, dst, act in process_call_edges(graph):
        if src in keep and dst in keep:
            lines.append(f'{_alias(src)} --> {_alias(dst)} : {_esc(act)}')
    return '\n'.join(lines + FOOTER)


def deployment_diagram(graph: Graph) -> str:
    lines = list(HEADER) + ['title Deployment / Integration Topology', '',
                            'node "TIBCO BW Runtime" as BWRT {']
    for mod in sorted(graph.modules()):
        lines.append(f'  artifact "{_esc(mod)}" as {_alias(mod)}')
    lines.append('}')
    for sysnode in graph.by_label('System'):
        tech = _esc(sysnode.properties.get('technology', ''))
        lines.append(f'node "{_esc(sysnode.name)}" as {_alias(sysnode.node_id)} <<{tech}>>')
        lines.append(f'BWRT --> {_alias(sysnode.node_id)} : {tech}')
    return '\n'.join(lines + FOOTER)


def sequence_diagram(graph: Graph, process: GraphNode) -> str:
    """Sequence view of one process, ordered by activity execution order."""
    activities = [graph.node(r.end_id) for r in graph.outgoing(process.node_id)
                  if r.rel_type == 'EXECUTES']
    activities = sorted([a for a in activities if a],
                        key=lambda a: int(a.properties.get('order', 0) or 0))

    lines = list(HEADER) + [f'title {_esc(process.name)} - runtime sequence', '',
                            'actor Client', f'participant "{_esc(process.name)}" as PROC']
    partners: Dict[str, str] = {}
    for act in activities:
        category = str(act.properties.get('category', ''))
        if category.startswith('JDBC'):
            partners.setdefault('DB', 'database "Database" as DB')
        elif category.startswith('JMS') or category.startswith('RV'):
            partners.setdefault('MQ', 'queue "Message broker" as MQ')
        elif category in ('HTTP_REQUEST', 'SOAP_CALL'):
            partners.setdefault('EXT', 'participant "External service" as EXT')
        elif category.startswith('FILE') or category.startswith('FTP'):
            partners.setdefault('FS', 'participant "File system" as FS')
    lines += list(partners.values()) + ['']

    entry = str(process.properties.get('entryType', 'NONE'))
    lines.append(f'Client -> PROC : {_esc(entry if entry != "NONE" else "invoke")}')
    lines.append('activate PROC')
    for act in activities:
        category = str(act.properties.get('category', ''))
        spring = _esc(act.properties.get('springEquivalent', ''))
        if category.startswith('JDBC'):
            lines.append(f'PROC -> DB : {_esc(act.name)}')
            lines.append(f'DB --> PROC : result')
        elif category.startswith('JMS') or category.startswith('RV'):
            lines.append(f'PROC -> MQ : {_esc(act.name)}')
        elif category in ('HTTP_REQUEST', 'SOAP_CALL'):
            lines.append(f'PROC -> EXT : {_esc(act.name)}')
            lines.append(f'EXT --> PROC : response')
        elif category.startswith('FILE') or category.startswith('FTP'):
            lines.append(f'PROC -> FS : {_esc(act.name)}')
        elif category in ('CATCH', 'GENERATE_ERROR', 'RETHROW'):
            lines.append(f'note right of PROC : fault path - {_esc(act.name)} ({spring})')
        else:
            lines.append(f'PROC -> PROC : {_esc(act.name)}')
    lines.append('PROC --> Client : response')
    lines.append('deactivate PROC')
    return '\n'.join(lines + FOOTER)


def generate_all(graph: Graph) -> Dict[str, str]:
    out = {
        'plantuml/c4-models/context.puml': c4_context(graph),
        'plantuml/c4-models/container.puml': c4_container(graph),
        'plantuml/c4-models/component.puml': c4_component(graph),
        'plantuml/deployment-diagrams/topology.puml': deployment_diagram(graph),
    }
    top = sorted(graph.by_label('BWProcess'),
                 key=lambda p: -float(p.properties.get('complexityScore', 0) or 0))[:8]
    for proc in top:
        slug = _alias(proc.name).lower()
        out[f'plantuml/sequence-diagrams/sequence-{slug}.puml'] = sequence_diagram(graph, proc)
    return out
