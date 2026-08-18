"""Graph validation engine (CI gate).

The generic checks live here — id grammar, referential integrity, closed
vocabulary, property typing, orphans, provenance. Dialect-specific rules are
supplied as callables through `ValidationConfig.extra_rules`, so each
analyzer keeps its own domain rules without forking the engine.

Exit contract for callers: `status` is `PASS`, `WARN` or `FAIL`; a `FAIL`
means the graph is not trustworthy and nothing should be built on top of it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from ..model import Graph

logger = logging.getLogger('analyzer_core')

SEVERITY_ORDER = {'ERROR': 0, 'WARNING': 1, 'INFO': 2}


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {'severity': self.severity, 'rule': self.rule,
                'message': self.message, 'details': self.details[:50]}


@dataclass
class ValidationConfig:
    """What "valid" means for one dialect."""
    id_pattern: Optional[re.Pattern] = None
    known_labels: Set[str] = field(default_factory=set)
    known_rel_types: Set[str] = field(default_factory=set)
    required_rel_types: Set[str] = field(default_factory=set)
    orphan_tolerant_labels: Set[str] = field(default_factory=set)
    int_fields: Set[str] = field(default_factory=set)
    float_fields: Set[str] = field(default_factory=set)
    bool_fields: Set[str] = field(default_factory=set)
    # inferred edges must carry a confidence; these types are exempt
    provenance_exempt_rels: Set[str] = field(default_factory=set)
    extra_rules: List[Callable[[Graph], List[Finding]]] = field(default_factory=list)


class GraphValidator:
    """Runs every check and renders a machine- and human-readable verdict."""

    def __init__(self, graph: Graph, config: ValidationConfig,
                 output_dir: Optional[Path] = None):
        self.graph = graph
        self.config = config
        self.output_dir = Path(output_dir) if output_dir else None
        self.findings: List[Finding] = []

    # ------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        self.findings = []
        self._check_ids()
        self._check_referential_integrity()
        self._check_vocabulary()
        self._check_required_rel_types()
        self._check_property_types()
        self._check_orphans()
        self._check_provenance()
        for rule in self.config.extra_rules:
            try:
                self.findings.extend(rule(self.graph) or [])
            except Exception as exc:                       # a broken rule must not
                self.findings.append(Finding(                # hide the other rules
                    'WARNING', 'RULE_ERROR',
                    f'Validation rule {getattr(rule, "__name__", rule)} raised: {exc}'))

        self.findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 3), f.rule))
        errors = sum(1 for f in self.findings if f.severity == 'ERROR')
        warnings = sum(1 for f in self.findings if f.severity == 'WARNING')
        status = 'FAIL' if errors else ('WARN' if warnings else 'PASS')
        stats = self.graph.stats()
        return {
            'status': status,
            'errors': errors,
            'warnings': warnings,
            'totals': {'nodes': stats['totalNodes'],
                       'relationships': stats['totalRelationships']},
            'nodeCounts': stats['nodeCounts'],
            'relationshipCounts': stats['relationshipCounts'],
            'findings': [f.to_dict() for f in self.findings],
        }

    # ------------------------------------------------------------------
    def _add(self, severity: str, rule: str, message: str,
             details: Optional[List[str]] = None) -> None:
        self.findings.append(Finding(severity, rule, message, details or []))

    def _check_ids(self) -> None:
        blank = [nid for nid in self.graph.nodes if not nid]
        if blank:
            self._add('ERROR', 'AX-IDS', f'{len(blank)} node(s) have an empty id')
        mismatched = [n.node_id for n in self.graph.nodes.values()
                      if n.node_id not in self.graph.nodes]
        if mismatched:
            self._add('ERROR', 'AX-IDS',
                      f'{len(mismatched)} node(s) keyed inconsistently', mismatched[:20])
        if self.config.id_pattern is not None:
            bad = [nid for nid in self.graph.nodes if not self.config.id_pattern.match(nid)]
            if bad:
                self._add('ERROR', 'AX-IDS',
                          f'{len(bad)} node id(s) do not match the id grammar', bad[:20])

    def _check_referential_integrity(self) -> None:
        dangling: List[str] = []
        for rel in self.graph.rels:
            if rel.start_id not in self.graph.nodes:
                dangling.append(f'{rel.rel_type}: missing start {rel.start_id}')
            if rel.end_id not in self.graph.nodes:
                dangling.append(f'{rel.rel_type}: missing end {rel.end_id}')
        if dangling:
            self._add('ERROR', 'AX-REFS',
                      f'{len(dangling)} relationship endpoint(s) do not exist',
                      dangling[:25])
        else:
            self._add('INFO', 'AX-REFS',
                      f'All {len(self.graph.rels)} relationship endpoints resolve')

    def _check_vocabulary(self) -> None:
        if self.config.known_labels:
            unknown = sorted({n.label for n in self.graph.nodes.values()
                              if n.label not in self.config.known_labels})
            if unknown:
                self._add('ERROR', 'AX-VOCAB',
                          f'{len(unknown)} label(s) outside the specification', unknown)
        if self.config.known_rel_types:
            unknown_rels = sorted({r.rel_type for r in self.graph.rels
                                   if r.rel_type not in self.config.known_rel_types})
            if unknown_rels:
                self._add('ERROR', 'AX-VOCAB',
                          f'{len(unknown_rels)} relationship type(s) outside the '
                          f'specification', unknown_rels)

    def _check_required_rel_types(self) -> None:
        present = {r.rel_type for r in self.graph.rels}
        missing = sorted(self.config.required_rel_types - present)
        if missing:
            self._add('ERROR', 'AX-CONTAIN',
                      f'{len(missing)} required relationship type(s) absent', missing)

    def _check_property_types(self) -> None:
        bad: List[str] = []
        for node in self.graph.nodes.values():
            for key, value in node.properties.items():
                if key in self.config.int_fields and not isinstance(value, bool) \
                        and not isinstance(value, int):
                    bad.append(f'{node.node_id}.{key} = {value!r} (expected int)')
                elif key in self.config.float_fields and not isinstance(value, (int, float)):
                    bad.append(f'{node.node_id}.{key} = {value!r} (expected float)')
                elif key in self.config.bool_fields and not isinstance(value, bool):
                    bad.append(f'{node.node_id}.{key} = {value!r} (expected bool)')
        if bad:
            self._add('ERROR', 'AX-TYPES',
                      f'{len(bad)} property value(s) have the wrong type', bad[:25])

    def _check_orphans(self) -> None:
        orphans = [n for n in self.graph.nodes.values()
                   if n.label not in self.config.orphan_tolerant_labels
                   and not self.graph.outgoing(n.node_id)
                   and not self.graph.incoming(n.node_id)]
        if orphans:
            self._add('WARNING', 'AX-ORPHAN',
                      f'{len(orphans)} node(s) have no relationships',
                      [f'{n.label}:{n.name} ({n.node_id})' for n in orphans[:25]])

    def _check_provenance(self) -> None:
        missing_conf = [f'{r.rel_type} {r.start_id} -> {r.end_id}'
                        for r in self.graph.rels
                        if r.properties.get('origin') == 'inferred'
                        and 'confidence' not in r.properties
                        and r.rel_type not in self.config.provenance_exempt_rels]
        if missing_conf:
            self._add('ERROR', 'AX-PROV',
                      f'{len(missing_conf)} inferred relationship(s) carry no confidence',
                      missing_conf[:25])
        unevidenced = [n.node_id for n in self.graph.nodes.values()
                       if n.properties.get('origin') == 'llm'
                       and not n.properties.get('evidence')]
        if unevidenced:
            self._add('ERROR', 'AX-PROV',
                      f'{len(unevidenced)} agent-authored node(s) cite no evidence',
                      unevidenced[:25])


# ──────────────────────────────────────────────────────────────
def render_markdown(result: Dict[str, Any], title: str = 'Graph Validation Report') -> str:
    badge = {'PASS': 'PASS', 'WARN': 'WARN (usable, with caveats)',
             'FAIL': 'FAIL (do not build analysis on this graph)'}
    lines = [f'# {title}', '',
             f"**Status:** {badge.get(result['status'], result['status'])}  ",
             f"**Errors:** {result['errors']}  |  **Warnings:** {result['warnings']}", '',
             '## Totals', '',
             '| Metric | Value |', '|---|---|',
             f"| Nodes | {result['totals']['nodes']:,} |",
             f"| Relationships | {result['totals']['relationships']:,} |", '',
             '## Findings', '']
    if not result['findings']:
        lines.append('_No findings._')
    else:
        lines += ['| Severity | Rule | Message |', '|---|---|---|']
        for finding in result['findings']:
            lines.append(f"| {finding['severity']} | {finding['rule']} | "
                         f"{finding['message']} |")
        detailed = [f for f in result['findings'] if f['details']]
        if detailed:
            lines += ['', '### Detail', '']
            for finding in detailed:
                lines += [f"**{finding['rule']} — {finding['message']}**", '']
                lines += [f'- `{d}`' for d in finding['details']]
                lines.append('')
    lines += ['', '## Counts by label', '', '| Label | Count |', '|---|---|']
    for label, count in result['nodeCounts'].items():
        lines.append(f'| {label} | {count:,} |')
    lines += ['', '## Counts by relationship type', '', '| Type | Count |', '|---|---|']
    for rtype, count in result['relationshipCounts'].items():
        lines.append(f'| {rtype} | {count:,} |')
    return '\n'.join(lines) + '\n'
