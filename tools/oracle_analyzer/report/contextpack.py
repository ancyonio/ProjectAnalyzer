"""LLM grounding packs.

Each pack answers one question completely from the graph, so an agent can cite
it instead of re-deriving the answer from source. Every pack states its
coverage, because an agent that does not know what the graph is missing will
present a partial answer as a complete one.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from analyzer_core.model import Graph

from ..analysis.inventory import (complexity_ranking, data_access, dead_code,
                                  entry_points, full_inventory, hotspots,
                                  issues_summary, packages, schemas, summary)


def _table(headers: List[str], rows: List[List[Any]]) -> List[str]:
    if not rows:
        return ['_None._']
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join(['---'] * len(headers)) + '|']
    for row in rows:
        out.append('| ' + ' | '.join('' if v is None else str(v) for v in row) + ' |')
    return out


def _coverage_banner(graph: Graph) -> List[str]:
    coverage = (graph.meta or {}).get('coverage', {})
    resolution = coverage.get('resolutionCoverage', 0)
    lines = [
        '> **Coverage.** '
        f"{coverage.get('objectsModelled', 0)}/{coverage.get('objectsDiscovered', 0)} "
        f'objects modelled ({resolution}%); '
        f"{coverage.get('callsResolved', 0)} of "
        f"{coverage.get('callsResolved', 0) + coverage.get('callsUnresolved', 0)} "
        f'calls resolved; '
        f"{coverage.get('dynamicSqlSites', 0)} dynamic-SQL site(s) where "
        f'dependency analysis stops; '
        f"{coverage.get('parseQuality', 100.0)}% of code nodes parsed cleanly.",
    ]
    quality = coverage.get('parseQuality', 100.0)
    if quality < 90:
        # Stated before the resolution note on purpose: an agent that reads
        # "100% resolved" first will stop reading, and resolution is measured
        # over whatever the parser managed to extract.
        lines.append('>')
        lines.append(
            f'> Parse quality is {quality}%: '
            f"{coverage.get('statementsPartial', 0)} statement(s) parsed only "
            f"partially and {coverage.get('statementsFailed', 0)} failed, so "
            f'the resolution figure above is measured over less code than the '
            f'estate contains. Do not read it as completeness.')
    if coverage.get('ddlUnparsed'):
        lines.append('>')
        lines.append(
            f"> {coverage.get('ddlUnparsed')} DDL statement(s) matched no known "
            f'pattern and produced no node at all; they are absent from every '
            f'count on this page.')
    if resolution < 80:
        lines.append('>')
        lines.append('> Resolution is below 80%: treat this graph as provisional '
                     'and say so in any answer built on it.')
    if not coverage.get('dictionaryAvailable'):
        lines.append('>')
        lines.append('> No data-dictionary extract was supplied, so this is a '
                     'statement about the repository, not the deployed database.')
    return lines + ['']


def estate_facts(graph: Graph) -> str:
    counts = summary(graph)
    out = ['# Estate Facts (verified)', '']
    out += _coverage_banner(graph)
    out += ['## Size', '']
    out += _table(['Metric', 'Count'],
                  [[key, value] for key, value in counts.items()])
    out += ['', '## Schemas', '']
    out += _table(['Schema', 'Tables', 'Views', 'Packages', 'Standalone units',
                   'Triggers'],
                  [[r['name'], r['tables'], r['views'], r['packages'],
                    r['standaloneUnits'], r['triggers']] for r in schemas(graph)])
    return '\n'.join(out) + '\n'


def packages_pack(graph: Graph) -> str:
    out = ['# Packages', '',
           'A spec change breaks every caller; a body change does not. '
           'That is why the two halves are separate nodes.', '']
    out += _table(['Package', 'Owner', 'Spec', 'Body', 'Units', 'LOC', 'Fan-in',
                   'Source'],
                  [[r['name'], r['owner'], 'yes' if r['hasSpec'] else 'no',
                    'yes' if r['hasBody'] else 'no', r['units'], r['loc'],
                    r['fanIn'], r['filePath']] for r in packages(graph)])
    return '\n'.join(out) + '\n'


def entry_points_pack(graph: Graph) -> str:
    out = ['# Entry Points', '',
           'What the outside world can invoke: units a package spec publishes, '
           'standalone procedures and functions, and triggers, which fire '
           'without a caller.', '']
    out += _table(['Name', 'Kind', 'Package / Table', 'Type', 'Source'],
                  [[r['name'], r['kind'], r['package'], r['unitType'],
                    r['filePath']] for r in entry_points(graph)])
    return '\n'.join(out) + '\n'


def complexity_pack(graph: Graph) -> str:
    out = ['# Complexity', '',
           'Score combines length, embedded statements, calls, branching and '
           'looping, with a fixed penalty for dynamic SQL.', '']
    out += _table(['Unit', 'Package', 'Type', 'Tier', 'Score', 'LOC',
                   'Statements', 'Calls', 'Fan-in', 'Source'],
                  [[r['name'], r['package'], r['unitType'], r['tier'],
                    r['complexity'], r['loc'], r['statements'], r['calls'],
                    r['fanIn'], r['filePath']]
                   for r in complexity_ranking(graph)])
    return '\n'.join(out) + '\n'


def data_access_pack(graph: Graph) -> str:
    rows = data_access(graph)
    out = ['# Data Access', '',
           'Which program units read and write which tables, through the SQL '
           'they execute. The specific verb is recorded alongside the '
           '`WRITES_TO` roll-up.', '']
    out += _table(['Unit', 'Package', 'Table', 'Access', 'Source'],
                  [[r['unit'], r['package'], r['table'], r['access'],
                    r['filePath']] for r in rows])
    out += ['', '## Most depended-upon objects', '']
    out += _table(['Object', 'Type', 'Dependents', 'Depends on'],
                  [[r['name'], r['label'], r['fanIn'], r['fanOut']]
                   for r in hotspots(graph)])
    return '\n'.join(out) + '\n'


def findings_pack(graph: Graph) -> str:
    issues = issues_summary(graph)
    out = ['# Findings', '',
           f"{issues['total']} finding(s): "
           f"{', '.join(f'{k}={v}' for k, v in sorted(issues['bySeverity'].items()))}",
           '']
    out += _table(['Severity', 'Rule', 'Target', 'Finding', 'Recommendation',
                   'Source'],
                  [[f['severity'], f['ruleId'], f['target'], f['description'],
                    f['recommendation'],
                    f"{f['filePath']}:{f['lineStart']}" if f['filePath'] else '']
                   for f in issues['findings']])
    return '\n'.join(out) + '\n'


def dead_code_pack(graph: Graph) -> str:
    buckets = dead_code(graph)
    out = ['# Unreferenced Objects', '',
           'Nothing in the analysed tree reaches these. Check the dynamic-SQL '
           'sites before concluding any of them is dead: a call built at '
           'runtime is invisible here by design.', '']
    if not buckets:
        out.append('_Everything is referenced._')
    for label, rows in buckets.items():
        out += [f'## {label}', '']
        out += _table(['Name', 'Owner', 'Source'],
                      [[r['name'], r['owner'], r['filePath']] for r in rows])
        out.append('')
    return '\n'.join(out) + '\n'


def unresolved_pack(graph: Graph) -> str:
    out = ['# Unresolved References', '',
           'Names the analysis saw but could not bind to a definition. These '
           'are the graph\'s known gaps; quote them alongside any completeness '
           'claim.', '']
    rows = [[node.name, node.properties.get('kinds', ''),
             node.properties.get('referenceCount', 0)]
            for node in sorted(graph.by_label('UnresolvedRef'),
                               key=lambda n: n.name)]
    out += _table(['Reference', 'Seen as', 'Referenced by'], rows)
    return '\n'.join(out) + '\n'


def manifest(graph: Graph) -> str:
    out = ['# Context Pack Manifest', '',
           'Generated from `graph.json`. Read the pack rather than recounting '
           'from source.', '']
    out += _table(['Pack', 'Answers'], [
        ['estate-facts.md', 'How big is this estate, and what is in it'],
        ['packages.md', 'Which packages exist, and do they have both halves'],
        ['entry-points.md', 'What can the outside world call'],
        ['complexity.md', 'Which units are hardest to move'],
        ['data-access.md', 'Which units read and write which tables'],
        ['findings.md', 'What the rule catalogue found'],
        ['dead-code.md', 'What nothing references'],
        ['unresolved.md', 'What the graph could not resolve'],
        ['facts.json', 'The whole inventory, machine-readable'],
    ])
    return '\n'.join(out) + '\n'


def generate_all(graph: Graph) -> Dict[str, str]:
    return {
        'MANIFEST.md': manifest(graph),
        'estate-facts.md': estate_facts(graph),
        'packages.md': packages_pack(graph),
        'entry-points.md': entry_points_pack(graph),
        'complexity.md': complexity_pack(graph),
        'data-access.md': data_access_pack(graph),
        'findings.md': findings_pack(graph),
        'dead-code.md': dead_code_pack(graph),
        'unresolved.md': unresolved_pack(graph),
        'facts.json': json.dumps(full_inventory(graph), indent=2, default=str),
    }
