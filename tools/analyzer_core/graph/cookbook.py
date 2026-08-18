"""Cypher cookbook rendering.

A cookbook is a list of `{id, title, purpose, cypher}` dicts owned by the
dialect. This module only renders it — as a runnable `.cypher` file for
Neo4j Browser, and as Markdown for the reports and skills.
"""
from __future__ import annotations

from typing import Dict, List

Entry = Dict[str, str]


def render_cookbook(entries: List[Entry], title: str,
                    param_hint: str = ':param objectName => "ORDERS"') -> str:
    out = [
        '// ================================================================',
        f'// {title} - Analysis Query Cookbook',
        '// Parameterised queries use $params; set them in Neo4j Browser with',
        f'//   {param_hint}',
        '// ================================================================',
        '',
    ]
    for entry in entries:
        out += ['// ---------------------------------------------------------------',
                f"// {entry['title']}",
                f"// {entry['purpose']}",
                f"// id: {entry['id']}",
                '', entry['cypher'], '']
    return '\n'.join(out)


def render_markdown(entries: List[Entry], title: str, intro: str = '') -> str:
    out = [f'# {title} — Cypher Query Cookbook', '']
    if intro:
        out += [intro, '']
    out += ['| id | Question |', '|---|---|']
    for entry in entries:
        out.append(f"| `{entry['id']}` | {entry['title']} |")
    out.append('')
    for entry in entries:
        out += [f"## {entry['title']}", '', f"_{entry['purpose']}_", '',
                '```cypher', entry['cypher'], '```', '']
    return '\n'.join(out)
