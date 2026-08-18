"""LLM grounding packs for the federated estate.

Each pack answers one cross-estate question completely, so an agent can cite it
instead of re-deriving the answer from three graphs. Every pack carries the
coverage banner, because an agent that does not know the join is partial will
present a partial answer as a complete one -- and here the partial part is
exactly the part that spans estates.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from analyzer_core.model import Graph

from ..analysis.inventory import (boundary_components, contended_tables,
                                  estates, full_inventory, hotspots,
                                  issues_summary, summary, table_access)
from ..analysis.sequence import sequence
from ..constants import MIN_DATASOURCE_COVERAGE, MIN_SQL_BIND_COVERAGE


def _table(headers: List[str], rows: List[List[Any]]) -> List[str]:
    if not rows:
        return ['_None._']
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join(['---'] * len(headers)) + '|']
    for row in rows:
        out.append('| ' + ' | '.join('' if v is None else str(v) for v in row) + ' |')
    return out


def _coverage_banner(graph: Graph) -> List[str]:
    coverage = (graph.meta or {}).get('coverage') or {}
    lines = [
        '> **Coverage.** '
        f"{coverage.get('mergedDbNodes', 0)} database node(s) joined exactly "
        f'between the APEX and Oracle estates; '
        f"{coverage.get('crossEstateLinks', 0)} inferred cross-estate edge(s) "
        f"({coverage.get('crossEstateLinksByBasis', {})}); "
        f"SQL bind coverage {coverage.get('sqlBindCoverage', 0)}% "
        f"({coverage.get('jdbcActivitiesBound', 0)}/"
        f"{coverage.get('jdbcActivitiesWithSql', 0)} JDBC activities carrying "
        f'static SQL); '
        f"datasource coverage {coverage.get('datasourceCoverage', 0)}% "
        f"({coverage.get('datasourcesMapped', 0)}/"
        f"{coverage.get('datasources', 0)} mapped).",
    ]
    if coverage.get('sqlBindCoverage', 0) < MIN_SQL_BIND_COVERAGE:
        lines += ['>', '> SQL bind coverage is below '
                       f'{MIN_SQL_BIND_COVERAGE}%: treat every cross-estate '
                       'statement as provisional and say so.']
    if coverage.get('datasourceCoverage', 0) < MIN_DATASOURCE_COVERAGE:
        lines += ['>', '> Some JDBC datasources are unmapped. Tables reached '
                       'through them are absent from this graph, so "no '
                       'integration touches this table" cannot be concluded.']
    if coverage.get('noStaticSqlSites'):
        lines += ['>', f"> {coverage['noStaticSqlSites']} JDBC activity/ies "
                       'build SQL at runtime. Their dependencies are invisible '
                       'by design, and that is recorded, not hidden.']
    return lines + ['']


def estate_facts(graph: Graph) -> str:
    counts = summary(graph)
    out = ['# Federated Estate Facts (verified)', '']
    out += _coverage_banner(graph)
    out += ['## Size', '']
    out += _table(['Metric', 'Count'], [[k, v] for k, v in counts.items()])
    out += ['', '## Estates', '']
    out += _table(['Estate', 'Title', 'Nodes', 'Relationships', 'Own coverage',
                   'Source root'],
                  [[r['estate'], r['title'], r['nodes'], r['relationships'],
                    r['coverage'], r['sourceRoot']] for r in estates(graph)])
    out += ['', 'Per-estate totals are quoted from each analyzer, not recounted '
                'here. The federated graph is smaller than their sum, because '
                'database objects both database estates describe are one node.',
            '']
    return '\n'.join(out) + '\n'


def shared_data(graph: Graph) -> str:
    out = ['# Shared data', '',
           'Every database object more than one estate touches, and how. This '
           'is the surface on which a change in one estate becomes a defect in '
           'another.', '']
    out += _coverage_banner(graph)
    rows = [row for row in table_access(graph) if row['estateCount'] > 1]
    out += ['## Touched by more than one estate', '']
    out += _table(['Object', 'Label', 'Written by', 'Read by', 'Writers', 'Readers'],
                  [[r['name'], r['label'], ', '.join(r['writerEstates']) or '-',
                    ', '.join(r['readerEstates']) or '-', r['writers'], r['readers']]
                   for r in rows])
    out += ['', '## Contended: written by more than one estate', '']
    contended = contended_tables(graph)
    out += _table(['Object', 'Written by', 'Read by'],
                  [[r['name'], ', '.join(r['writerEstates']),
                    ', '.join(r['readerEstates']) or '-'] for r in contended])
    if contended:
        out += ['', 'A contended table cannot be cut over by one team alone. '
                    'Decide which estate owns it before either is migrated.', '']
    return '\n'.join(out) + '\n'


def cross_estate_links(graph: Graph) -> str:
    out = ['# Cross-estate links', '',
           'Every edge that crosses an estate boundary, with the basis it rests '
           'on. `exact` needed no heuristic; `name` is a bare-name match and '
           'must be confirmed by hand before it is relied on.', '']
    out += _coverage_banner(graph)

    rows = []
    for rel in graph.rels:
        start = graph.nodes.get(rel.start_id)
        end = graph.nodes.get(rel.end_id)
        if start is None or end is None:
            continue
        if start.properties.get('estate') == end.properties.get('estate'):
            continue
        if rel.rel_type not in ('READS_FROM', 'WRITES_TO', 'INSERTS_INTO',
                                'UPDATES', 'DELETES_FROM', 'CONNECTS_TO_SCHEMA'):
            continue
        rows.append([start.properties.get('estate', ''), start.name, rel.rel_type,
                     end.name, rel.properties.get('basis', 'exact'),
                     rel.properties.get('confidence', 1.0)])
    rows.sort(key=lambda r: (float(r[5]), r[0], r[1]))
    out += ['## Inferred and declared edges', '']
    out += _table(['From estate', 'From', 'Access', 'To', 'Basis', 'Confidence'], rows)

    merged = [node for node in graph.nodes.values() if node.properties.get('merged')]
    out += ['', '## Exact merges (no heuristic)', '',
            f'{len(merged)} database node(s) carried the same natural key in '
            f'more than one estate and became one node.', '']
    out += _table(['Label', 'Name', 'Estates'],
                  sorted([[n.label, n.name, n.properties.get('estates', '')]
                          for n in merged]))
    return '\n'.join(out) + '\n'


def boundary(graph: Graph) -> str:
    out = ['# Components on an estate boundary', '',
           'Artefacts whose data access touches data another estate also uses '
           '- either by crossing an estate boundary outright, or by reaching '
           'an object more than one estate contributed. These cannot be '
           'understood, tested or migrated from inside one estate, which is '
           'the reason this federation exists.', '']
    out += _coverage_banner(graph)
    out += _table(['Estate', 'Label', 'Component', 'Module', 'Reaches',
                   'Access', 'Min confidence'],
                  [[r['estate'], r['label'], r['name'], r['module'],
                    ', '.join(r['reaches']), ', '.join(r['access']),
                    r['minConfidence']] for r in boundary_components(graph)])
    out += ['', '## Most depended-upon across estates', '']
    out += _table(['Label', 'Name', 'Estate', 'Fan-in', 'Estates depending on it'],
                  [[r['label'], r['name'], r['estate'], r['fanIn'],
                    ', '.join(r['estates'])] for r in hotspots(graph)])
    return '\n'.join(out) + '\n'


def findings(graph: Graph) -> str:
    result = issues_summary(graph)
    out = ['# Findings ledger (all estates)', '',
           'Rule ids are namespaced: `APEX.SEC-001` and `ORA.SEC-001` are '
           'different rules that happen to share an ordinal, and `XE-` rules '
           'exist only across estates. Categories are canonical, so APEX '
           '`TECH_DEBT` and Oracle `DEBT` are one category here.', '']
    out += _coverage_banner(graph)
    out += ['## Totals', '']
    out += _table(['Dimension', 'Breakdown'],
                  [['Severity', result['bySeverity']],
                   ['Category', result['byCategory']],
                   ['Estate', result['byEstate']]])
    out += ['', '## Cross-estate findings', '']
    out += _table(['Rule', 'Severity', 'Target', 'Finding', 'Recommendation'],
                  [[f['ruleId'], f['severity'], f['targetName'],
                    f['description'], f['recommendation']]
                   for f in result['findings'] if f['estate'] == 'cross'])
    out += ['', '## Inherited findings', '',
            'Raised by the individual analyzers and reproduced unchanged apart '
            'from the namespaced rule id.', '']
    out += _table(['Rule', 'Estate', 'Severity', 'Target', 'Finding'],
                  [[f['ruleId'], f['estate'], f['severity'], f['targetName'],
                    f['description']]
                   for f in result['findings'] if f['estate'] != 'cross'])
    return '\n'.join(out) + '\n'


def sequence_pack(graph: Graph) -> str:
    out = ['# Modernisation sequence', '']
    out += _coverage_banner(graph)
    body = '\n'.join(sequence_markdown_lines(graph))
    return '\n'.join(out) + '\n' + body


def sequence_markdown_lines(graph: Graph) -> List[str]:
    from ..analysis.sequence import render_markdown
    return render_markdown(sequence(graph)).splitlines()[2:]


def unresolved(graph: Graph) -> str:
    """What the join could not do, stated as plainly as what it could."""
    coverage = (graph.meta or {}).get('coverage') or {}
    out = ['# What this federation could not join', '',
           'Read this before concluding that something is unused, unconnected '
           'or safe to move.', '']
    out += _coverage_banner(graph)
    out += ['## Blind spots', '']
    out += _table(['Kind', 'Count', 'What it means'], [
        ['JDBC activities with no static SQL',
         coverage.get('noStaticSqlSites', 0),
         'They build SQL at runtime. Their tables are unknown, not absent.'],
        ['Unbound table references', coverage.get('unboundReferences', 0),
         'Named a table no database estate models, or the datasource is '
         'unmapped.'],
        ['Unmapped datasources',
         coverage.get('datasources', 0) - coverage.get('datasourcesMapped', 0),
         'A JDBC url names a database, not a schema; nothing behind these is '
         'in the graph.'],
        ['Suppressed bare-name matches',
         (graph.meta or {}).get('links', {}).get('suppressedCount', 0),
         'Computed at confidence 0.5 and withheld. Re-run with '
         '--allow-name-match to admit them.'],
    ])
    out += ['', '## Inherited limits', '',
            'The federated graph cannot be more complete than its inputs. Each '
            'estate reported its own coverage:', '']
    out += _table(['Estate', 'Own coverage'],
                  [[r['estate'], r['coverage']] for r in estates(graph)])
    return '\n'.join(out) + '\n'


def facts_json(graph: Graph) -> str:
    return json.dumps(full_inventory(graph), indent=2, default=str)


def manifest(graph: Graph) -> str:
    counts = summary(graph)
    return '\n'.join([
        '# Federated context pack manifest', '',
        'Generated from `graph.json` in this directory. Every figure is '
        'computed from the federated graph; nothing here was written by hand.',
        '',
        '| Pack | Answers |', '|---|---|',
        '| `estate-facts.md` | How big each estate is and what the join produced |',
        '| `shared-data.md` | Which database objects more than one estate touches |',
        '| `cross-estate-links.md` | Every boundary-crossing edge and its basis |',
        '| `boundary-components.md` | Which artefacts reach across an estate |',
        '| `findings.md` | The merged, namespaced findings ledger |',
        '| `sequence.md` | The derived modernisation order |',
        '| `unresolved.md` | What the join could not do |',
        '| `facts.json` | All of the above, machine readable |',
        '',
        f"Estates: {counts['estates']}  |  Nodes: {counts['nodes']:,}  |  "
        f"Relationships: {counts['relationships']:,}  |  "
        f"Shared database objects: {counts['sharedDatabaseObjects']}  |  "
        f"Cross-estate links: {counts['crossEstateLinks']}",
        '',
    ]) + '\n'


def generate_all(graph: Graph) -> Dict[str, str]:
    return {
        'MANIFEST.md': manifest(graph),
        'estate-facts.md': estate_facts(graph),
        'shared-data.md': shared_data(graph),
        'cross-estate-links.md': cross_estate_links(graph),
        'boundary-components.md': boundary(graph),
        'findings.md': findings(graph),
        'sequence.md': sequence_pack(graph),
        'unresolved.md': unresolved(graph),
        'facts.json': facts_json(graph),
    }
