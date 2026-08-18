"""Blast-radius / change-impact engine.

Answers: *if this artefact changes, what else breaks?*

Traversal is a weighted BFS over the knowledge graph. Direction matters:

  upstream   – follow incoming edges: who depends on the target (default;
               this is the blast radius of a change).
  downstream – follow outgoing edges: what the target depends on (useful for
               "what do I need in scope to migrate this").
  both       – union of the two.

Each hop multiplies a decay factor by the relationship weight, so a schema
consumed directly scores higher than one reached through five hops. The
result also names the *entry points* reached, because those are the surfaces
a regression becomes visible on.
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ..constants import IMPACT_EXCLUDED_RELS, REL_IMPACT_WEIGHTS
from ..model import Graph, GraphNode

DEFAULT_DEPTH = 4
DEFAULT_DECAY = 0.75

RISK_BANDS = [
    (60.0, 'CRITICAL'),
    (30.0, 'HIGH'),
    (12.0, 'MEDIUM'),
    (0.0, 'LOW'),
]


def _band(score: float) -> str:
    for threshold, label in RISK_BANDS:
        if score > threshold:
            return label
    return 'LOW'


class ImpactAnalyzer:
    """Computes the blast radius of a change to one or more nodes."""

    def __init__(self, graph: Graph, decay: float = DEFAULT_DECAY):
        self.graph = graph
        self.decay = decay

    # ------------------------------------------------------------------
    def analyze(self, targets: List[GraphNode], depth: int = DEFAULT_DEPTH,
                direction: str = 'upstream',
                include_rels: Optional[Set[str]] = None,
                exclude_rels: Optional[Set[str]] = None) -> Dict[str, Any]:
        exclude = set(exclude_rels or set()) | set(IMPACT_EXCLUDED_RELS)
        reached = self._traverse(targets, depth, direction, include_rels, exclude)

        target_ids = {t.node_id for t in targets}
        impacted: List[Dict[str, Any]] = []
        for node_id, info in reached.items():
            if node_id in target_ids:
                continue
            node = self.graph.node(node_id)
            if node is None:
                continue
            impacted.append({
                'nodeId': node_id,
                'label': node.label,
                'name': node.name,
                'module': node.module,
                'hops': info['hops'],
                'weight': round(info['weight'], 4),
                'via': info['path'],
                'entryType': node.properties.get('entryType', ''),
                'filePath': node.file_path,
                'tier': node.properties.get('tier', ''),
                'parent': info.get('parent'),
                'parentRel': info.get('parentRel', ''),
            })
        impacted.sort(key=lambda r: (-r['weight'], r['hops'], r['label'], r['name']))

        by_label: Dict[str, int] = defaultdict(int)
        for row in impacted:
            by_label[row['label']] += 1

        affected_entry_points = [r for r in impacted
                                 if r['label'] == 'BWProcess'
                                 and r['entryType'] not in (None, '', 'NONE')]
        affected_modules = sorted({r['module'] for r in impacted if r['module']})

        risk_score = self._risk_score(impacted, affected_entry_points)
        return {
            'targets': [{'nodeId': t.node_id, 'label': t.label, 'name': t.name,
                         'module': t.module, 'filePath': t.file_path} for t in targets],
            'parameters': {'depth': depth, 'direction': direction,
                           'decay': self.decay,
                           'includeRels': sorted(include_rels) if include_rels else 'ALL',
                           'excludeRels': sorted(exclude)},
            'summary': {
                'impactedNodes': len(impacted),
                'impactedByLabel': dict(sorted(by_label.items(), key=lambda kv: -kv[1])),
                'affectedEntryPoints': len(affected_entry_points),
                'affectedModules': affected_modules,
                'riskScore': risk_score,
                'riskBand': _band(risk_score),
            },
            'entryPoints': affected_entry_points,
            'impacted': impacted,
            'testScope': self._test_scope(impacted, affected_entry_points),
            'cypher': self._equivalent_cypher(targets, depth, direction),
        }

    # ------------------------------------------------------------------
    def _traverse(self, targets: List[GraphNode], depth: int, direction: str,
                  include_rels: Optional[Set[str]], exclude_rels: Set[str]
                  ) -> Dict[str, Dict[str, Any]]:
        """Best-first search keeping, per node, the strongest path found."""
        best: Dict[str, Dict[str, Any]] = {}
        heap: List[Tuple[float, int, str, List[str]]] = []
        counter = 0
        for t in targets:
            best[t.node_id] = {'weight': 1.0, 'hops': 0, 'path': [], 'parent': None,
                               'parentRel': ''}
            heapq.heappush(heap, (-1.0, 0, t.node_id, []))

        while heap:
            neg_weight, hops, node_id, path = heapq.heappop(heap)
            weight = -neg_weight
            if hops >= depth:
                continue
            current = best.get(node_id)
            if current and (weight < current['weight'] - 1e-9):
                continue

            edges = []
            if direction in ('upstream', 'both'):
                edges += [(r, r.start_id, 'IN') for r in self.graph.incoming(node_id)]
            if direction in ('downstream', 'both'):
                edges += [(r, r.end_id, 'OUT') for r in self.graph.outgoing(node_id)]

            for rel, neighbour, arrow in edges:
                if rel.rel_type in exclude_rels:
                    continue
                if include_rels and rel.rel_type not in include_rels:
                    continue
                if neighbour == node_id:
                    continue
                edge_weight = REL_IMPACT_WEIGHTS.get(rel.rel_type, 0.5)
                new_weight = weight * edge_weight * self.decay
                if new_weight < 0.01:
                    continue
                prior = best.get(neighbour)
                if prior and prior['weight'] >= new_weight - 1e-9:
                    continue
                step = f"{'<-' if arrow == 'IN' else '-'}[{rel.rel_type}]{'-' if arrow == 'IN' else '->'}"
                new_path = path + [step]
                best[neighbour] = {'weight': new_weight, 'hops': hops + 1,
                                   'path': new_path, 'parent': node_id,
                                   'parentRel': rel.rel_type}
                counter += 1
                heapq.heappush(heap, (-new_weight, hops + 1, neighbour, new_path))
        return best

    # ------------------------------------------------------------------
    def _risk_score(self, impacted: List[Dict[str, Any]],
                    entry_points: List[Dict[str, Any]]) -> float:
        """Weighted count of impacted artefacts, entry points weighted heaviest.

        Deterministic and comparable across runs; not calibrated to any
        absolute scale - use the band, and compare targets against each other.
        """
        label_multiplier = {
            'BWProcess': 3.0, 'Service': 3.0, 'XSD': 2.0, 'Element': 0.5,
            'Activity': 0.6, 'SharedResource': 1.5, 'GlobalVariable': 1.0,
            'Module': 1.0, 'ErrorHandler': 0.4, 'DataTransformation': 1.0,
        }
        score = sum(row['weight'] * label_multiplier.get(row['label'], 1.0)
                    for row in impacted)
        score += 6.0 * len(entry_points)
        return round(score, 2)

    def _test_scope(self, impacted: List[Dict[str, Any]],
                    entry_points: List[Dict[str, Any]]) -> Dict[str, Any]:
        """What must be re-tested for this change to be safe."""
        processes = [r['name'] for r in impacted if r['label'] == 'BWProcess']
        schemas = [r['name'] for r in impacted if r['label'] == 'XSD']
        services = [r['name'] for r in impacted if r['label'] == 'Service']
        return {
            'contractTests': sorted({e['name'] for e in entry_points}),
            'processRegression': sorted(set(processes)),
            'schemaMarshallingTests': sorted(set(schemas)),
            'serviceContractTests': sorted(set(services)),
            'recommendation': (
                'Re-run parity tests for every listed entry point with recorded '
                'production payloads before and after the change.'
                if entry_points else
                'No externally reachable entry point is affected; scope regression '
                'to the listed processes and schemas.'
            ),
        }

    def _equivalent_cypher(self, targets: List[GraphNode], depth: int,
                           direction: str) -> str:
        names = ', '.join(f"'{t.name}'" for t in targets)
        arrow_l, arrow_r = ('<-', '-') if direction == 'upstream' else ('-', '->')
        if direction == 'both':
            arrow_l, arrow_r = '-', '-'
        return (
            f"MATCH (t) WHERE t.name IN [{names}]\n"
            f"MATCH path = (t){arrow_l}[r*1..{depth}]{arrow_r}(affected)\n"
            f"WHERE none(rel IN r WHERE type(rel) = 'BELONGS_TO')\n"
            f"RETURN DISTINCT labels(affected)[0] AS Type, affected.name AS Name,\n"
            f"       affected.module AS Module, affected.entryType AS EntryType,\n"
            f"       min(length(path)) AS Hops\n"
            f"ORDER BY Hops, Type, Name;"
        )


# ──────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────
def render_markdown(result: Dict[str, Any], max_rows: int = 60) -> str:
    tgt = ', '.join(f"`{t['label']}:{t['name']}`" for t in result['targets'])
    s = result['summary']
    lines = [
        '# Change Impact / Blast Radius Report',
        '',
        f"**Target(s):** {tgt}  ",
        f"**Direction:** {result['parameters']['direction']} "
        f"(depth {result['parameters']['depth']})  ",
        f"**Risk band:** {s['riskBand']} (score {s['riskScore']})",
        '',
        '## Summary',
        '',
        '| Metric | Value |',
        '|--------|-------|',
        f"| Impacted artefacts | {s['impactedNodes']} |",
        f"| Affected entry points | {s['affectedEntryPoints']} |",
        f"| Affected modules | {', '.join(s['affectedModules']) or 'none'} |",
        '',
        '### Impacted by type',
        '',
        '| Type | Count |',
        '|------|-------|',
    ]
    for label, count in s['impactedByLabel'].items():
        lines.append(f'| {label} | {count} |')

    lines += ['', '## Affected entry points (externally visible regressions)', '']
    if result['entryPoints']:
        lines += ['| Entry point | Type | Module | Hops |', '|---|---|---|---|']
        for e in result['entryPoints']:
            lines.append(f"| {e['name']} | {e['entryType']} | {e['module']} | {e['hops']} |")
    else:
        lines.append('_None - the change does not reach an externally reachable surface._')

    lines += ['', '## Impacted artefacts (strongest coupling first)', '',
              '| # | Type | Name | Module | Hops | Weight | Path |',
              '|---|------|------|--------|------|--------|------|']
    for i, row in enumerate(result['impacted'][:max_rows], 1):
        via = ' '.join(row['via'][-3:]) or 'direct'
        lines.append(f"| {i} | {row['label']} | {row['name']} | {row['module']} | "
                     f"{row['hops']} | {row['weight']} | `{via}` |")
    if len(result['impacted']) > max_rows:
        lines.append(f"| … | | _{len(result['impacted']) - max_rows} more_ | | | | |")

    ts = result['testScope']
    lines += ['', '## Required test scope', '',
              f"- **Contract / parity tests:** {', '.join(ts['contractTests']) or 'none'}",
              f"- **Process regression:** {', '.join(ts['processRegression'][:25]) or 'none'}",
              f"- **Schema marshalling tests:** {', '.join(ts['schemaMarshallingTests'][:25]) or 'none'}",
              f"- **Service contract tests:** {', '.join(ts['serviceContractTests'][:25]) or 'none'}",
              '', f"> {ts['recommendation']}",
              '', '## Equivalent Cypher', '', '```cypher', result['cypher'], '```', '']
    return '\n'.join(lines)


def render_mermaid(result: Dict[str, Any], max_nodes: int = 40) -> str:
    """Mermaid flowchart of the blast radius."""
    def nid(node_id: str) -> str:
        return node_id.replace('-', '_')

    lines = ['flowchart LR']
    for t in result['targets']:
        lines.append(f'  {nid(t["nodeId"])}["CHANGE: {t["label"]}<br/>{t["name"]}"]:::target')

    shown = result['impacted'][:max_nodes]
    ids = {t['nodeId'] for t in result['targets']} | {r['nodeId'] for r in shown}
    for row in shown:
        cls = 'entry' if row['entryType'] not in (None, '', 'NONE') else 'impacted'
        label = f'{row["label"]}<br/>{row["name"]}'
        lines.append(f'  {nid(row["nodeId"])}["{label}"]:::{cls}')

    lines.append('')
    for row in shown:
        parent = row.get('parent')
        if parent and parent in ids:
            lines.append(f'  {nid(row["nodeId"])} -->|{row.get("parentRel", "")}| {nid(parent)}')

    lines += [
        '',
        '  classDef target fill:#b91c1c,stroke:#7f1d1d,color:#ffffff,stroke-width:2px;',
        '  classDef entry fill:#1d4ed8,stroke:#1e3a8a,color:#ffffff;',
        '  classDef impacted fill:#f1f5f9,stroke:#64748b,color:#0f172a;',
    ]
    return '\n'.join(lines)
