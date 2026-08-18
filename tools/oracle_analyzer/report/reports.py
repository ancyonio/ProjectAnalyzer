"""Report scaffolds.

Layer 1 fills the tables from the graph. Layer 2 -- the narrative, the risk
interpretation, the sequencing advice -- is written by an analyst into the
sections marked `<!-- LLM: ... -->`, from the Layer 1 output only. The markers
stay in place so a half-finished report is obvious.
"""
from __future__ import annotations

from typing import Any, Dict, List

from analyzer_core.model import Graph

from ..analysis.inventory import (complexity_ranking, entry_points, hotspots,
                                  issues_summary, packages, schemas, summary)


def _table(headers: List[str], rows: List[List[Any]]) -> List[str]:
    if not rows:
        return ['_None._']
    return (['| ' + ' | '.join(headers) + ' |',
             '|' + '|'.join(['---'] * len(headers)) + '|']
            + ['| ' + ' | '.join('' if v is None else str(v) for v in row) + ' |'
               for row in rows])


def _header(graph: Graph, title: str) -> List[str]:
    meta = graph.meta or {}
    coverage = meta.get('coverage', {})
    return [
        f'# {title}', '',
        f"Source: `{meta.get('sourceRoot', '')}`  ",
        f"Generated: {meta.get('generatedAt', '')}  ",
        f"Resolution coverage: **{coverage.get('resolutionCoverage', 0)}%** "
        f"({coverage.get('objectsModelled', 0)}/"
        f"{coverage.get('objectsDiscovered', 0)} objects)  ",
        f"Dictionary extract: "
        f"{'yes' if coverage.get('dictionaryAvailable') else 'no'}",
        '',
    ]


def step00_inventory(graph: Graph) -> str:
    counts = summary(graph)
    out = _header(graph, 'Step 00 — Oracle Estate Inventory')
    out += ['## What is in the estate', '']
    out += _table(['Metric', 'Count'], [[k, v] for k, v in counts.items()])
    out += ['', '## Schemas', '']
    out += _table(['Schema', 'Tables', 'Views', 'Packages', 'Standalone units',
                   'Triggers'],
                  [[r['name'], r['tables'], r['views'], r['packages'],
                    r['standaloneUnits'], r['triggers']] for r in schemas(graph)])
    out += ['', '## Packages', '']
    out += _table(['Package', 'Spec', 'Body', 'Units', 'LOC'],
                  [[r['name'], 'yes' if r['hasSpec'] else 'no',
                    'yes' if r['hasBody'] else 'no', r['units'], r['loc']]
                   for r in packages(graph)])
    out += ['', '## Entry points', '']
    out += _table(['Name', 'Kind', 'Package / Table', 'Type'],
                  [[r['name'], r['kind'], r['package'], r['unitType']]
                   for r in entry_points(graph)])
    out += ['', '## Interpretation', '',
            '<!-- LLM: characterise the estate from the tables above. Size, '
            'shape, how much of it is reachable from outside, and what the '
            'coverage figure means for confidence. Do not introduce counts '
            'that are not in this document. -->', '']
    return '\n'.join(out) + '\n'


def step01_dependencies(graph: Graph) -> str:
    out = _header(graph, 'Step 01 — Dependencies and Blast Radius')
    out += ['## Most depended-upon objects', '',
            'Change these and the blast radius is widest.', '']
    out += _table(['Object', 'Type', 'Owner', 'Dependents', 'Depends on'],
                  [[r['name'], r['label'], r['owner'], r['fanIn'], r['fanOut']]
                   for r in hotspots(graph)])
    out += ['', '## Most complex units', '']
    out += _table(['Unit', 'Package', 'Tier', 'Score', 'LOC', 'Fan-in'],
                  [[r['name'], r['package'], r['tier'], r['complexity'],
                    r['loc'], r['fanIn']] for r in complexity_ranking(graph, 25)])
    out += ['', '## Where the analysis stops', '']
    unresolved = sorted(graph.by_label('UnresolvedRef'), key=lambda n: n.name)
    out += _table(['Reference', 'Seen as', 'Referenced by'],
                  [[n.name, n.properties.get('kinds', ''),
                    n.properties.get('referenceCount', 0)] for n in unresolved])
    out += ['', '## Interpretation', '',
            '<!-- LLM: name the objects that must be migrated first and why, '
            'using fan-in from the table above. State explicitly what the '
            'unresolved references and any dynamic SQL mean for the '
            'reliability of this ordering. -->', '']
    return '\n'.join(out) + '\n'


def step02_risk(graph: Graph) -> str:
    issues = issues_summary(graph)
    out = _header(graph, 'Step 02 — Risk and Findings')
    out += [f"## {issues['total']} finding(s)", '',
            ', '.join(f'**{k}**: {v}'
                      for k, v in sorted(issues['bySeverity'].items())) or '_None._',
            '']
    out += _table(['Severity', 'Rule', 'Category', 'Target', 'Finding', 'Source'],
                  [[f['severity'], f['ruleId'], f['category'], f['target'],
                    f['description'],
                    f"{f['filePath']}:{f['lineStart']}" if f['filePath'] else '']
                   for f in issues['findings']])
    out += ['', '## Recommendations', '']
    out += _table(['Rule', 'Target', 'Recommendation'],
                  [[f['ruleId'], f['target'], f['recommendation']]
                   for f in issues['findings']])
    out += ['', '## Interpretation', '',
            '<!-- LLM: group the findings above into themes, say which must be '
            'fixed before migration and which can be carried, and sequence the '
            'work. Every claim must trace to a row in this document. -->', '']
    return '\n'.join(out) + '\n'


def generate_all(graph: Graph) -> Dict[str, str]:
    return {
        'Step00_ORACLE_INVENTORY_REPORT.md': step00_inventory(graph),
        'Step01_DEPENDENCY_REPORT.md': step01_dependencies(graph),
        'Step02_RISK_AND_FINDINGS_REPORT.md': step02_risk(graph),
    }
