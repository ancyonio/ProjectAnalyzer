"""Graph validation gate.

Implements the validation rules from `Step_0_Neo4j_Analysis.md`:
referential integrity, node-id uniqueness, relationship-type coverage,
BWProcess completeness, orphan detection. Designed to run in CI: a FAIL
means the graph is not trustworthy and no report built on it should ship.
"""
from __future__ import annotations

import csv
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..model import Graph

logger = logging.getLogger('tibco_analyzer')

REQUIRED_REL_TYPES = {'BELONGS_TO', 'EXECUTES', 'CONTAINS'}
EXPECTED_REL_TYPES = {'USES_XSD', 'CALLS', 'TRANSITIONS_TO', 'HANDLES_ERROR',
                      'REFERENCES', 'EXPOSES', 'IMPORTS_SCHEMA'}
# Labels allowed to have no edges at all.
ORPHAN_TOLERANT_LABELS = {'System', 'GlobalVariable', 'DataTransformation',
                          'AESchema', 'ExternalReference'}

SEVERITY_ORDER = {'ERROR': 0, 'WARNING': 1, 'INFO': 2}


@dataclass
class Finding:
    severity: str          # ERROR | WARNING | INFO
    rule: str
    message: str
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {'severity': self.severity, 'rule': self.rule,
                'message': self.message, 'details': self.details[:50]}


class GraphValidator:
    """Validates a `Graph` and, optionally, the exported CSV pair."""

    def __init__(self, graph: Graph, output_dir: Optional[Path] = None):
        self.graph = graph
        self.output_dir = Path(output_dir) if output_dir else None
        self.findings: List[Finding] = []

    # ------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        self.findings = []
        self._check_node_ids()
        self._check_referential_integrity()
        self._check_rel_type_coverage()
        self._check_process_completeness()
        self._check_orphans()
        self._check_schema_wiring()
        self._check_entry_points()
        self._check_unresolved_references()
        self._check_shared_resource_coverage()
        self._check_artifact_coverage()
        if self.output_dir:
            self._check_csv_roundtrip()

        counts = Counter(f.severity for f in self.findings)
        status = 'FAIL' if counts.get('ERROR') else ('WARN' if counts.get('WARNING') else 'PASS')
        return {
            'status': status,
            'errors': counts.get('ERROR', 0),
            'warnings': counts.get('WARNING', 0),
            'info': counts.get('INFO', 0),
            'stats': self.graph.stats(),
            'findings': [f.to_dict() for f in sorted(
                self.findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))],
        }

    # ------------------------------------------------------------------
    def _add(self, severity: str, rule: str, message: str, details: Optional[List[str]] = None) -> None:
        self.findings.append(Finding(severity, rule, message, details or []))

    def _check_node_ids(self) -> None:
        seen = Counter(n.node_id for n in self.graph.nodes.values())
        dupes = [nid for nid, c in seen.items() if c > 1]
        if dupes:
            self._add('ERROR', 'node-id-uniqueness',
                      f'{len(dupes)} duplicate node ids', dupes)
        unnamed = [n.node_id for n in self.graph.nodes.values() if not n.name]
        if unnamed:
            self._add('WARNING', 'node-name-present',
                      f'{len(unnamed)} nodes have an empty name', unnamed)

    def _check_referential_integrity(self) -> None:
        ids = set(self.graph.nodes)
        dangling = [f"{r.start_id}-[{r.rel_type}]->{r.end_id}"
                    for r in self.graph.rels
                    if r.start_id not in ids or r.end_id not in ids]
        if dangling:
            self._add('ERROR', 'referential-integrity',
                      f'{len(dangling)} relationships reference unknown nodes', dangling)
        else:
            self._add('INFO', 'referential-integrity',
                      'All relationship endpoints resolve to existing nodes')

        self_loops = [f"{r.start_id}-[{r.rel_type}]->{r.end_id}"
                      for r in self.graph.rels if r.start_id == r.end_id]
        if self_loops:
            self._add('WARNING', 'no-self-loops',
                      f'{len(self_loops)} self-referencing relationships', self_loops)

    def _check_rel_type_coverage(self) -> None:
        present = {r.rel_type for r in self.graph.rels}
        missing_required = REQUIRED_REL_TYPES - present
        if missing_required:
            self._add('ERROR', 'relationship-coverage',
                      'Required relationship types missing from the graph',
                      sorted(missing_required))
        missing_expected = EXPECTED_REL_TYPES - present
        if missing_expected:
            self._add('WARNING', 'relationship-coverage',
                      'Expected relationship types absent - either the source tree '
                      'does not use them or the parser does not yet model them; '
                      'check artifact-coverage below before concluding the estate '
                      'is simple',
                      sorted(missing_expected))

    # Extensions that hold a shared resource in either BW generation. Used to
    # tell "this estate has no shared resources" apart from "the parser did not
    # recognise this estate's shared resources", which are very different
    # statements to put in front of an analyst.
    _RESOURCE_EXT_HINTS = ('.shared', '.rvtransport', '.httpproxy', '.id')

    def _check_shared_resource_coverage(self) -> None:
        """Resource files on disk but no SharedResource nodes means a parser gap."""
        discovery = (self.graph.meta or {}).get('fileDiscovery') or {}
        if not discovery:
            return
        resource_files = {
            ext: n for ext, n in discovery.items()
            if ext and (ext.lower().endswith('resource')
                        or ext.lower().startswith(self._RESOURCE_EXT_HINTS)
                        or ext.lower().endswith('globalinstance'))
        }
        total_files = sum(resource_files.values())
        parsed = len(self.graph.by_label('SharedResource'))
        if total_files and not parsed:
            self._add('ERROR', 'shared-resource-coverage',
                      f'{total_files} shared-resource files were discovered but none '
                      f'were parsed - the integration surface in this graph is empty '
                      f'and must not be reported as "no external systems"',
                      [f'{ext}: {n}' for ext, n in sorted(resource_files.items())])
        elif total_files:
            self._add('INFO', 'shared-resource-coverage',
                      f'{parsed} shared resource(s) parsed from {total_files} '
                      f'resource file(s)')

    def _check_artifact_coverage(self) -> None:
        """How much of the supported TIBCO input is represented in the graph.

        An analyst reading a context pack cannot otherwise tell whether a small
        graph means a small estate or a partly-parsed one.
        """
        meta = self.graph.meta or {}
        discovery = meta.get('fileDiscovery') or {}
        if not discovery:
            return
        discovered = sum(discovery.values())
        if not discovered:
            return
        coverage = meta.get('coverage') or {}
        modelled = coverage.get('filesModelled', 0)
        supported = coverage.get('filesSupported')
        supported_modelled = coverage.get('filesSupportedModelled')
        if supported is None or supported_modelled is None:
            supported = discovered
            supported_modelled = modelled
        pct = coverage.get('artifactCoverage')
        if pct is None:
            pct = round(supported_modelled * 100.0 / supported, 1)
        estate_pct = coverage.get('estateFileCoverage')
        if estate_pct is None:
            estate_pct = round(modelled * 100.0 / discovered, 1)
        families = meta.get('artifactFamilies') or {}
        classified = sum(families.values())
        detail = [f'{supported_modelled}/{supported} supported artifact files produced graph nodes',
                  f'{modelled}/{discovered} all discovered files produced graph nodes ({estate_pct}%)',
                  f'{classified}/{discovered} files matched a known artifact family']
        if pct < 50:
            self._add('WARNING', 'artifact-coverage',
                      f'Only {pct}% of supported artifact files are represented in the graph - '
                      f'the parser may be missing TIBCO inputs',
                      detail)
        else:
            self._add('INFO', 'artifact-coverage',
                      f'{pct}% of supported artifact files are represented in the graph; '
                      f'all-file estate coverage is {estate_pct}%', detail)

    def _check_process_completeness(self) -> None:
        no_module, no_work = [], []
        for proc in self.graph.by_label('BWProcess'):
            out_types = {r.rel_type for r in self.graph.outgoing(proc.node_id)}
            if 'BELONGS_TO' not in out_types:
                no_module.append(proc.name)
            if not ({'EXECUTES', 'USES_XSD', 'USES_WSDL', 'HAS_GROUP'} & out_types):
                no_work.append(proc.name)
        if no_module:
            self._add('ERROR', 'process-module-membership',
                      f'{len(no_module)} BWProcess nodes have no BELONGS_TO edge', no_module)
        if no_work:
            self._add('WARNING', 'process-has-work',
                      f'{len(no_work)} BWProcess nodes execute no activity and use no schema',
                      no_work)

    def _check_orphans(self) -> None:
        orphans = [f"{n.label}:{n.name}" for n in self.graph.nodes.values()
                   if n.label not in ORPHAN_TOLERANT_LABELS
                   and not self.graph.outgoing(n.node_id)
                   and not self.graph.incoming(n.node_id)]
        if orphans:
            self._add('WARNING', 'no-orphan-nodes',
                      f'{len(orphans)} disconnected nodes (excluding tolerated labels)', orphans)
        else:
            self._add('INFO', 'no-orphan-nodes', 'No disconnected nodes')

    def _check_schema_wiring(self) -> None:
        empty_xsds = [x.name for x in self.graph.by_label('XSD')
                      if not any(r.rel_type == 'CONTAINS' for r in self.graph.outgoing(x.node_id))]
        if empty_xsds:
            self._add('WARNING', 'xsd-contains-elements',
                      f'{len(empty_xsds)} XSD nodes define no elements or types', empty_xsds)

    def _check_entry_points(self) -> None:
        entries = [p for p in self.graph.by_label('BWProcess')
                   if p.properties.get('entryType') not in (None, '', 'NONE')]
        if not entries:
            self._add('WARNING', 'entry-points-detected',
                      'No entry point processes detected - the analysis may be missing starters')
        else:
            self._add('INFO', 'entry-points-detected',
                      f'{len(entries)} entry point processes detected')

    def _check_unresolved_references(self) -> None:
        ext = self.graph.by_label('ExternalReference')
        if ext:
            self._add('WARNING', 'unresolved-references',
                      f'{len(ext)} referenced artefacts were not found in the scanned tree',
                      [f"{n.name} ({n.properties.get('targetPath', '')})" for n in ext])

    def _check_csv_roundtrip(self) -> None:
        nodes_csv = self.output_dir / 'neo4j_nodes.csv'
        rels_csv = self.output_dir / 'neo4j_relationships.csv'
        if not nodes_csv.exists() or not rels_csv.exists():
            self._add('INFO', 'csv-present', 'CSV exports not found - skipping CSV checks')
            return
        with open(nodes_csv, encoding='utf-8') as fh:
            node_ids = {row['nodeId:ID'] for row in csv.DictReader(fh)}
        bad = []
        with open(rels_csv, encoding='utf-8') as fh:
            for row in csv.DictReader(fh):
                if row[':START_ID'] not in node_ids or row[':END_ID'] not in node_ids:
                    bad.append(f"{row[':START_ID']}->{row[':END_ID']}")
        if bad:
            self._add('ERROR', 'csv-referential-integrity',
                      f'{len(bad)} CSV relationships point at unknown node ids', bad)
        else:
            self._add('INFO', 'csv-referential-integrity',
                      f'CSV integrity verified across {len(node_ids)} node ids')


def render_markdown(result: Dict[str, Any]) -> str:
    """Render a validation result as a Markdown report."""
    icon = {'PASS': 'PASS', 'WARN': 'WARN', 'FAIL': 'FAIL'}[result['status']]
    lines = [
        '# Graph Validation Report',
        '',
        f"**Status:** {icon}  ",
        f"**Errors:** {result['errors']} | **Warnings:** {result['warnings']} | "
        f"**Info:** {result['info']}",
        '',
        '## Graph Statistics',
        '',
        '| Metric | Value |',
        '|--------|-------|',
        f"| Total nodes | {result['stats']['totalNodes']} |",
        f"| Total relationships | {result['stats']['totalRelationships']} |",
        '',
        '### Nodes by label',
        '',
        '| Label | Count |',
        '|-------|-------|',
    ]
    for label, count in result['stats']['nodeCounts'].items():
        lines.append(f'| {label} | {count} |')
    lines += ['', '### Relationships by type', '', '| Type | Count |', '|------|-------|']
    for rtype, count in result['stats']['relationshipCounts'].items():
        lines.append(f'| {rtype} | {count} |')

    lines += ['', '## Findings', '']
    if not result['findings']:
        lines.append('No findings.')
    for f in result['findings']:
        lines.append(f"### [{f['severity']}] {f['rule']}")
        lines.append('')
        lines.append(f['message'])
        if f['details']:
            lines.append('')
            for d in f['details'][:25]:
                lines.append(f'- `{d}`')
            if len(f['details']) > 25:
                lines.append(f'- ... and {len(f["details"]) - 25} more')
        lines.append('')
    return '\n'.join(lines)
