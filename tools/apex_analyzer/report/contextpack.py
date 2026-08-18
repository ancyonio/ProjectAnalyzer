"""LLM grounding packs.

Pre-rendered Markdown an agent can read instead of re-deriving facts — or
instead of reading the export files, which is the failure mode these packs
exist to prevent. One pack per question an agent actually asks.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from analyzer_core.model import Graph, GraphNode
from analyzer_core.utils import md_table, one_line

from ..analysis.inventory import full_inventory
from ..analysis.traverse import WRITE_RELS, descend


class ContextPackBuilder:
    """Writes the grounding packs for one graph."""

    def __init__(self, graph: Graph, output_dir: Path):
        self.graph = graph
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.inventory = full_inventory(graph)

    # ------------------------------------------------------------------
    def build_all(self) -> Dict[str, str]:
        written: Dict[str, str] = {}
        written['application-facts.md'] = self._write('application-facts.md',
                                                      self.application_facts())
        written['pages.md'] = self._write('pages.md', self.pages_pack())
        written['data-access.md'] = self._write('data-access.md', self.data_access_pack())
        written['security.md'] = self._write('security.md', self.security_pack())
        written['findings.md'] = self._write('findings.md', self.findings_pack())
        written['dead-code.md'] = self._write('dead-code.md', self.dead_code_pack())
        written['business-functions.md'] = self._write('business-functions.md',
                                                       self.business_pack())
        written['facts.json'] = self._write_json('facts.json', self.inventory)

        pages_dir = self.output_dir / 'pages'
        pages_dir.mkdir(parents=True, exist_ok=True)
        for page in sorted(self.graph.by_label('ApexPage'),
                           key=lambda p: -float(p.properties.get('complexityScore', 0)
                                                or 0))[:25]:
            name = f"pages/page_{page.properties.get('pageId')}.md"
            written[name] = self._write(name, self.page_pack(page))

        written['MANIFEST.md'] = self._write('MANIFEST.md', self._manifest(written))
        return written

    # ------------------------------------------------------------------
    def _write(self, relative: str, content: str) -> str:
        path = self.output_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return str(path)

    def _write_json(self, relative: str, data: Any) -> str:
        return self._write(relative, json.dumps(data, indent=2, default=str))

    # ------------------------------------------------------------------
    def application_facts(self) -> str:
        summary = self.inventory['summary']
        coverage = self.inventory['coverage']
        return '\n'.join([
            '# Application facts', '',
            'Ground every answer in this file. Do not read the export files to '
            'recount anything listed here.', '',
            md_table(['Fact', 'Value'], [[k, one_line(str(v), 120)]
                                         for k, v in summary.items()]), '',
            '## Coverage — how much of the estate the graph actually resolved', '',
            md_table(['Metric', 'Value'],
                     [[k, one_line(str(v), 120)] for k, v in coverage.items()
                      if k != 'unresolvedNames']), '',
            '## Complexity tiers', '',
            md_table(['Tier', 'Pages'],
                     [[k, v] for k, v in self.inventory['tierDistribution'].items()]),
            '',
            '## Ingestion', '',
            md_table(['Setting', 'Value'],
                     [[k, one_line(str(v), 120)]
                      for k, v in (self.inventory['ingestion'] or {}).items()]), '',
        ])

    def pages_pack(self) -> str:
        return '\n'.join([
            '# Pages', '',
            md_table(['Page', 'Name', 'Group', 'Tier', 'Score', 'Regions', 'Items',
                      'Processes', 'DAs', 'SQL', 'PL/SQL', 'Tables', 'Writes',
                      'Authorization'],
                     [[p['pageId'], p['name'], p['group'], p['tier'],
                       p['complexityScore'], p['regions'], p['items'], p['processes'],
                       p['dynamicActions'], p['sql'], p['plsql'], p['tables'],
                       p['writes'], p['authorization'] or '—']
                      for p in self.inventory['pages']]), '',
            '## Navigation', '',
            md_table(['From', 'Via', 'To'],
                     [[f"{n['fromPage']} {n['fromName']}", n['via'],
                       f"{n['toPage']} {n['toName']}"]
                      for n in self.inventory['navigation']]), '',
        ])

    def data_access_pack(self) -> str:
        return '\n'.join([
            '# Data access', '',
            'Which pages touch which database objects, and how.', '',
            md_table(['Owner', 'Object', 'Type', 'Rows', 'Columns', 'Pages reaching',
                      'Read by', 'Written by'],
                     [[t['owner'], t['name'], t['label'], t['numRows'], t['columns'],
                       t['fanIn'], ', '.join(t['readBy']) or '—',
                       ', '.join(t['writtenBy']) or '—']
                      for t in self.inventory['dataAccess']]), '',
            '## Change hotspots', '',
            md_table(['Type', 'Name', 'Dependents'],
                     [[h['label'], h['name'], h['dependents']]
                      for h in self.inventory['hotspots']]), '',
        ])

    def security_pack(self) -> str:
        security = self.inventory['security']
        return '\n'.join([
            '# Security posture', '',
            md_table(['Metric', 'Value'],
                     [['Pages', security['pages']],
                      ['Secured pages', security['securedPages']],
                      ['Unsecured pages', len(security['unsecuredPages'])],
                      ['Public pages', len(security['publicPages'])],
                      ['Unrestricted access', len(security['unrestrictedAccessPages'])]]),
            '', '## Pages with no authorization scheme', '',
            md_table(['Page', 'Name', 'Tier'],
                     [[p['pageId'], p['name'], p['tier']]
                      for p in security['unsecuredPages']]), '',
            '## Public pages', '',
            md_table(['Page', 'Name'],
                     [[p['pageId'], p['name']] for p in security['publicPages']]), '',
            '## Authorization schemes', '',
            md_table(['Scheme', 'Type', 'Applied to'],
                     [[s['name'], s['type'], s['usedBy']]
                      for s in security['authorizationSchemes']]), '',
        ])

    def findings_pack(self) -> str:
        issues = self.inventory['issues']
        return '\n'.join([
            '# Findings', '',
            f"{issues['total']} finding(s) from the deterministic rule catalogue. "
            'Every one cites the component that triggered it.', '',
            md_table(['Severity', 'Count'],
                     [[k, v] for k, v in issues['bySeverity'].items()]), '',
            md_table(['Severity', 'Rule', 'Page', 'Finding', 'Evidence node'],
                     [[f['severity'], f['ruleId'], f['pageId'],
                       one_line(f['description'], 200), f['evidence']]
                      for f in issues['findings']]), '',
        ])

    def dead_code_pack(self) -> str:
        dead = self.inventory['deadCode']
        return '\n'.join([
            '# Dead code candidates', '',
            'Nothing here is proof: dynamic SQL, external jobs and ORDS endpoints '
            'are outside the graph. Treat each row as a question to confirm.', '',
            '## Pages with no inbound navigation', '',
            md_table(['Page', 'Name'],
                     [[p['pageId'], p['name']] for p in dead['unreachablePages']]), '',
            '## Unused lists of values', '',
            md_table(['Name', 'Type'],
                     [[l['name'], l['type']] for l in dead['unusedLovs']]), '',
            '## Unused authorization schemes', '',
            md_table(['Name'], [[s['name']] for s in dead['unusedAuthorizationSchemes']]),
            '', '## Program units nothing in the application reaches', '',
            md_table(['Owner', 'Package', 'Unit'],
                     [[u['owner'], u['package'], u['name']]
                      for u in dead['programUnitsNotReached']]), '',
            '## Tables no component touches', '',
            md_table(['Owner', 'Table'],
                     [[t['owner'], t['name']] for t in dead['tablesNoComponentTouches']]),
            '',
        ])

    def business_pack(self) -> str:
        return '\n'.join([
            '# Business functions (derived seed)', '',
            'Derived from page groups and write behaviour, with confidence. An agent '
            'may correct these, but must keep the evidence link and set '
            '`origin: llm`.', '',
            md_table(['Domain', 'Function', 'Criticality', 'Confidence',
                      'Implemented by', 'Evidence'],
                     [[b['domain'], b['name'], b['criticality'], b['confidence'],
                       ', '.join(b['implementedBy']), b['description']]
                      for b in self.inventory['businessFunctions']]), '',
        ])

    # ------------------------------------------------------------------
    def page_pack(self, page: GraphNode) -> str:
        graph = self.graph
        reach = descend(graph, page.node_id, max_depth=8)
        components: Dict[str, List[GraphNode]] = {}
        for node_id in reach:
            node = graph.node(node_id)
            if node is None:
                continue
            components.setdefault(node.label, []).append(node)

        out = [f"# Page {page.properties.get('pageId')} — {page.name}", '',
               md_table(['Property', 'Value'],
                        [[k, one_line(str(v), 160)]
                         for k, v in sorted(page.properties.items())
                         if k not in ('extraLabels',)]), '']

        for label in ('ApexRegion', 'ApexItem', 'ApexButton', 'ApexProcess',
                      'ApexValidation', 'ApexBranch', 'ApexDynamicAction',
                      'ApexDaAction'):
            nodes = components.get(label, [])
            if not nodes:
                continue
            out += [f'## {label.replace("Apex", "")}s', '',
                    md_table(['Name', 'Detail'],
                             [[n.name, one_line(_detail(n), 160)] for n in nodes]), '']

        code = components.get('SqlStatement', []) + components.get('PlsqlBlock', [])
        if code:
            out += ['## Code', '']
            for node in code:
                out += [f'### {node.label} `{node.node_id}`', '',
                        md_table(['Property', 'Value'],
                                 [[k, one_line(str(v), 120)]
                                  for k, v in sorted(node.properties.items())
                                  if k not in ('text', 'extraLabels')]), '',
                        '```sql', str(node.properties.get('text', ''))[:2000], '```', '']

        tables = components.get('DbTable', []) + components.get('DbView', [])
        if tables:
            writes = {rel.end_id for node_id in list(reach) + [page.node_id]
                      for rel in graph.outgoing(node_id) if rel.rel_type in WRITE_RELS}
            out += ['## Database objects', '',
                    md_table(['Object', 'Access'],
                             [[f"{t.properties.get('owner', '')}.{t.name}",
                               'write' if t.node_id in writes else 'read']
                              for t in tables]), '']

        issues = [graph.node(rel.end_id) for node_id in list(reach) + [page.node_id]
                  for rel in graph.outgoing(node_id) if rel.rel_type == 'HAS_ISSUE']
        if issues:
            out += ['## Findings', '',
                    md_table(['Severity', 'Rule', 'Finding'],
                             [[i.properties.get('severity'), i.properties.get('ruleId'),
                               one_line(i.properties.get('description', ''), 160)]
                              for i in issues if i is not None]), '']
        return '\n'.join(out)

    def _manifest(self, written: Dict[str, str]) -> str:
        summary = self.inventory['summary']
        return '\n'.join([
            '# Context pack manifest', '',
            f"Application {summary['name']} (id {summary['applicationId']}), "
            f"{summary['pages']} pages, {summary['tables']} tables, "
            f"{summary['issues']} findings.", '',
            md_table(['Pack', 'Answers'],
                     [['application-facts.md', 'size, coverage, tiers, ingestion'],
                      ['pages.md', 'every page with its metrics and the navigation graph'],
                      ['data-access.md', 'which page touches which table, and how'],
                      ['security.md', 'authorization coverage and public surface'],
                      ['findings.md', 'the rule catalogue output'],
                      ['dead-code.md', 'unreachable and unused components'],
                      ['business-functions.md', 'the derived business seed'],
                      ['pages/page_<id>.md', 'one page in full, including its code'],
                      ['facts.json', 'everything above, machine-readable']]), '',
            'Rule: if a fact is in these packs, cite it from here. If it is not, run '
            'the command that would produce it — do not read the export files and '
            'count by hand.', '',
        ])


def _detail(node: GraphNode) -> str:
    for key in ('regionType', 'itemType', 'action', 'processType', 'validationType',
                'branchType', 'eventName', 'actionType', 'sourceType'):
        value = node.properties.get(key)
        if value:
            return f'{key}={value}'
    return ''
