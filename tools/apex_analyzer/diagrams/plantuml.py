"""PlantUML diagram generation (C4-style context and component views)."""
from __future__ import annotations

from typing import Dict, List

from analyzer_core.model import Graph, GraphNode

from ..analysis.traverse import WRITE_RELS, descend

HEADER = ['@startuml', 'skinparam shadowing false', 'skinparam defaultFontName Arial',
          'skinparam rectangle {', '  BackgroundColor #F8FAFC', '  BorderColor #64748B',
          '}', '']
FOOTER = ['', '@enduml']


def _alias(text: str) -> str:
    return 'a' + ''.join(c if c.isalnum() else '_' for c in str(text))


def _esc(text: str) -> str:
    return str(text or '').replace('"', "'")[:60]


def context(graph: Graph) -> str:
    """The application, its users and the schemas it touches."""
    lines = list(HEADER) + ['title Application context', '']
    applications = graph.by_label('ApexApplication')
    if not applications:
        return '\n'.join(lines + ['note as N', 'No application parsed', 'end note'] + FOOTER)
    application = applications[0]
    lines += ['actor "End user" as user',
              f'rectangle "{_esc(application.name)}\\napp '
              f'{application.properties.get("applicationId")}" as app #1D4ED8']
    lines.append('user --> app : browser')
    for schema in graph.by_label('DbSchema'):
        tables = sum(1 for t in graph.by_label('DbTable')
                     if t.properties.get('owner') == schema.name)
        lines.append(f'database "{_esc(schema.name)}\\n{tables} table(s)" as '
                     f'{_alias(schema.node_id)}')
        lines.append(f'app --> {_alias(schema.node_id)} : SQL / PL/SQL')
    for source in graph.by_label('ApexWebSource'):
        lines.append(f'cloud "{_esc(source.name)}" as {_alias(source.node_id)}')
        lines.append(f'app --> {_alias(source.node_id)} : REST')
    return '\n'.join(lines + FOOTER)


def components(graph: Graph, limit: int = 25) -> str:
    """Pages as components, grouped by page group, with their data access."""
    lines = list(HEADER) + ['title Pages and data access', '']
    groups: Dict[str, List[GraphNode]] = {}
    for page in graph.by_label('ApexPage'):
        groups.setdefault(str(page.properties.get('pageGroup') or 'Ungrouped'),
                          []).append(page)

    for group, pages in sorted(groups.items()):
        lines.append(f'package "{_esc(group)}" {{')
        for page in sorted(pages, key=lambda p: p.properties.get('pageId') or 0):
            lines.append(f'  component "{page.properties.get("pageId")}: '
                         f'{_esc(page.name)}\\n{page.properties.get("tier", "")}" as '
                         f'{_alias(page.node_id)}')
        lines.append('}')

    tables = {t.node_id: t for t in graph.by_label('DbTable')}
    for table in list(tables.values())[:limit]:
        lines.append(f'database "{_esc(table.name)}" as {_alias(table.node_id)}')

    seen = set()
    for page in graph.by_label('ApexPage'):
        for node_id in descend(graph, page.node_id, max_depth=8):
            for rel in graph.outgoing(node_id):
                if rel.end_id not in tables:
                    continue
                write = rel.rel_type in WRITE_RELS
                key = (page.node_id, rel.end_id, write)
                if key in seen:
                    continue
                seen.add(key)
                arrow = '-[#B91C1C]->' if write else '-->'
                lines.append(f'{_alias(page.node_id)} {arrow} {_alias(rel.end_id)} : '
                             f'{"write" if write else "read"}')
    return '\n'.join(lines + FOOTER)


def sequence(graph: Graph, page: GraphNode) -> str:
    """Submit-time sequence for one page: button, process, PL/SQL, table."""
    lines = list(HEADER) + [f'title Page {page.properties.get("pageId")} — '
                            f'{_esc(page.name)} (submit)', '',
                            'actor User', f'participant "Page" as page',
                            'participant "Process" as proc',
                            'participant "PL/SQL" as code', 'database "Schema" as db', '']
    for rel in graph.outgoing(page.node_id):
        if rel.rel_type != 'CONTAINS_BUTTON':
            continue
        button = graph.node(rel.end_id)
        if button is None:
            continue
        lines.append(f'User -> page : press {_esc(button.name)}')
        for trigger in graph.outgoing(button.node_id):
            if trigger.rel_type != 'TRIGGERS':
                continue
            process = graph.node(trigger.end_id)
            if process is None:
                continue
            lines.append(f'page -> proc : {_esc(process.name)}')
            for run in graph.outgoing(process.node_id):
                if run.rel_type not in ('EXECUTES_PLSQL', 'EXECUTES_SQL'):
                    continue
                block = graph.node(run.end_id)
                if block is None:
                    continue
                lines.append(f'proc -> code : {block.label}')
                for access in graph.outgoing(block.node_id):
                    target = graph.node(access.end_id)
                    if target is None or target.label not in ('DbTable', 'DbView',
                                                              'DbProgramUnit'):
                        continue
                    lines.append(f'code -> db : {access.rel_type} {_esc(target.name)}')
    return '\n'.join(lines + FOOTER)


def generate_all(graph: Graph) -> Dict[str, str]:
    produced = {
        'context.puml': context(graph),
        'components.puml': components(graph),
    }
    pages = sorted(graph.by_label('ApexPage'),
                   key=lambda p: -float(p.properties.get('complexityScore', 0) or 0))
    for page in pages[:5]:
        produced[f'page_{page.properties.get("pageId")}_sequence.puml'] = \
            sequence(graph, page)
    return produced
