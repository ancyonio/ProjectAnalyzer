"""Report scaffolds.

Every table here is computed from the graph. Sections marked
`<!-- LLM: ... -->` are the only places narrative belongs, and an agent must
write them from these tables rather than from the export files.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from analyzer_core.model import Graph
from analyzer_core.utils import md_table, one_line

LLM_MARK = ('<!-- LLM: {instruction} -->\n'
            '_This section is for the analysis agent to complete from the tables '
            'above and the context packs. Do not invent counts._\n')


def _header(title: str, step: str, graph: Graph, summary: Dict[str, Any]) -> str:
    meta = graph.meta or {}
    coverage = meta.get('coverage', {})
    resolution = coverage.get('resolutionCoverage')
    return '\n'.join([
        f'# {step} — {title}',
        '',
        f"**Application:** {summary['name']} (id {summary['applicationId']}, "
        f"schema {summary['parsingSchema'] or 'unknown'})  ",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  ",
        f"**Graph:** {summary['totalNodes']} nodes / "
        f"{summary['totalRelationships']} relationships  ",
        f"**Ingestion:** {summary['ingestionMode']}; database extract "
        f"{'available' if summary['dictionaryAvailable'] else 'NOT available'}; "
        f"resolution coverage "
        f"{f'{resolution:.0%}' if resolution is not None else 'n/a'}",
        '',
        '> Every number below is computed from `graph.json`. Regenerate with '
        '`apex-analyze report`.',
        '',
    ])


def step00_graph_analysis(graph: Graph, inventory: Dict[str, Any]) -> str:
    summary = inventory['summary']
    stats = graph.stats()
    out = [_header('Knowledge graph and inventory', 'Step00', graph, summary)]

    out += ['## 1. Inventory', '',
            md_table(['Artefact', 'Count'],
                     [['Pages', summary['pages']], ['Regions', summary['regions']],
                      ['Items', summary['items']], ['Buttons', summary['buttons']],
                      ['Processes', summary['processes']],
                      ['Dynamic actions', summary['dynamicActions']],
                      ['Validations', summary['validations']],
                      ['Branches', summary['branches']],
                      ['Lists of values', summary['lovs']],
                      ['Authorization schemes', summary['authorizationSchemes']],
                      ['SQL statements', summary['sqlStatements']],
                      ['PL/SQL blocks', summary['plsqlBlocks']],
                      ['Tables', summary['tables']], ['Views', summary['views']],
                      ['Packages', summary['packages']],
                      ['Program units', summary['programUnits']],
                      ['Columns', summary['columns']],
                      ['Findings', summary['issues']]]), '']

    out += ['## 2. Graph composition', '',
            md_table(['Label', 'Nodes'],
                     [[k, v] for k, v in stats['nodeCounts'].items()]), '',
            md_table(['Relationship', 'Count'],
                     [[k, v] for k, v in stats['relationshipCounts'].items()]), '']

    out += ['## 3. Page complexity', '',
            md_table(['Page', 'Name', 'Tier', 'Score', 'Regions', 'Processes',
                      'SQL', 'PL/SQL', 'Tables', 'Writes'],
                     [[p['pageId'], p['name'], p['tier'], p['complexityScore'],
                       p['regions'], p['processes'], p['sql'], p['plsql'],
                       p['tables'], p['writes']]
                      for p in inventory['pages'][:40]]), '',
            LLM_MARK.format(instruction='Explain what drives complexity on the top '
                                        'pages and what that implies for change risk.'),
            '']

    out += ['## 4. Coverage and trust', '',
            md_table(['Metric', 'Value'],
                     [[k, one_line(str(v), 120)]
                      for k, v in (inventory['coverage'] or {}).items()
                      if k != 'unresolvedNames']), '']
    unresolved = (inventory['coverage'] or {}).get('unresolvedNames', [])
    if unresolved:
        out += ['Unresolved database references: ' +
                ', '.join(f'`{name}`' for name in unresolved[:25]), '']
    unhandled = inventory.get('unhandledProcedures') or {}
    if unhandled:
        out += ['Export procedures no parser handled:', '',
                md_table(['Procedure', 'Calls'],
                         [[k, v] for k, v in unhandled.items()]), '']
    return '\n'.join(out)


def step01_dependencies(graph: Graph, inventory: Dict[str, Any]) -> str:
    summary = inventory['summary']
    out = [_header('Dependencies and data access', 'Step01', graph, summary)]

    out += ['## 1. Data access by table', '',
            md_table(['Owner', 'Object', 'Type', 'Columns', 'Pages reaching',
                      'Read by', 'Written by'],
                     [[t['owner'], t['name'], t['label'], t['columns'], t['fanIn'],
                       ', '.join(t['readBy'][:6]) or '—',
                       ', '.join(t['writtenBy'][:6]) or '—']
                      for t in inventory['dataAccess'][:40]]), '',
            LLM_MARK.format(instruction='Identify the tables whose change risk is '
                                        'highest and say why.'), '']

    out += ['## 2. Change hotspots', '',
            md_table(['Type', 'Name', 'Dependents', 'Pages reaching'],
                     [[h['label'], h['name'], h['dependents'], h['pagesReaching']]
                      for h in inventory['hotspots']]), '']

    out += ['## 3. Navigation', '',
            md_table(['From page', 'Via', 'To page'],
                     [[f"{n['fromPage']} {n['fromName']}", n['via'],
                       f"{n['toPage']} {n['toName']}"]
                      for n in inventory['navigation'][:40]]), '']

    dead = inventory['deadCode']
    out += ['## 4. Dead code candidates', '',
            '### Pages with no inbound navigation', '',
            md_table(['Page', 'Name'],
                     [[p['pageId'], p['name']] for p in dead['unreachablePages']]), '',
            '### Unused lists of values', '',
            md_table(['Name', 'Type'],
                     [[l['name'], l['type']] for l in dead['unusedLovs']]), '',
            '### Program units nothing in the application reaches', '',
            md_table(['Owner', 'Package', 'Unit'],
                     [[u['owner'], u['package'], u['name']]
                      for u in dead['programUnitsNotReached'][:40]]), '',
            '### Tables no component touches', '',
            md_table(['Owner', 'Table'],
                     [[t['owner'], t['name']] for t in dead['tablesNoComponentTouches']]),
            '',
            LLM_MARK.format(instruction='Say which of these are genuinely dead and '
                                        'which are reached by a path the analyzer '
                                        'cannot see (dynamic SQL, external jobs).'),
            '']
    return '\n'.join(out)


def step02_risk_and_findings(graph: Graph, inventory: Dict[str, Any]) -> str:
    summary = inventory['summary']
    issues = inventory['issues']
    security = inventory['security']
    out = [_header('Risk, security and findings', 'Step02', graph, summary)]

    out += ['## 1. Findings by severity', '',
            md_table(['Severity', 'Count'],
                     [[k, v] for k, v in issues['bySeverity'].items()]), '',
            md_table(['Category', 'Count'],
                     [[k, v] for k, v in issues['byCategory'].items()]), '']

    out += ['## 2. All findings', '',
            md_table(['Severity', 'Rule', 'Page', 'Finding', 'Source'],
                     [[f['severity'], f['ruleId'], f['pageId'],
                       one_line(f['description'], 160), f['sourceFile']]
                      for f in issues['findings']]), '',
            LLM_MARK.format(instruction='Group these findings into remediation themes, '
                                        'sequence them, and state which must be fixed '
                                        'before the next release.'), '']

    out += ['## 3. Security posture', '',
            md_table(['Metric', 'Value'],
                     [['Pages', security['pages']],
                      ['Pages with an authorization scheme', security['securedPages']],
                      ['Pages without one', len(security['unsecuredPages'])],
                      ['Public pages', len(security['publicPages'])],
                      ['Unrestricted page access',
                       len(security['unrestrictedAccessPages'])]]), '',
            '### Pages with no authorization scheme', '',
            md_table(['Page', 'Name', 'Tier'],
                     [[p['pageId'], p['name'], p['tier']]
                      for p in security['unsecuredPages']]), '',
            '### Authorization schemes', '',
            md_table(['Scheme', 'Type', 'Used by'],
                     [[s['name'], s['type'], s['usedBy']]
                      for s in security['authorizationSchemes']]), '']

    out += ['## 4. Business function seed', '',
            md_table(['Domain', 'Function', 'Criticality', 'Implemented by', 'Origin'],
                     [[b['domain'], b['name'], b['criticality'],
                       ', '.join(b['implementedBy']), b['origin']]
                      for b in inventory['businessFunctions']]), '',
            LLM_MARK.format(instruction='Name the real business functions, correct the '
                                        'derived seed, and keep the evidence links.'),
            '']
    return '\n'.join(out)


REPORTS = {
    'Step00_APEX_GRAPH_REPORT.md': step00_graph_analysis,
    'Step01_DEPENDENCY_REPORT.md': step01_dependencies,
    'Step02_RISK_AND_FINDINGS_REPORT.md': step02_risk_and_findings,
}


def generate_reports(graph: Graph, output_dir: Path,
                     inventory: Dict[str, Any]) -> List[str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for name, builder in REPORTS.items():
        (output_dir / name).write_text(builder(graph, inventory), encoding='utf-8')
        written.append(name)
    return written
