"""Blast-radius / change-impact engine (dialect-agnostic).

Answers: *if this artefact changes, what else breaks?*

Traversal is a weighted best-first search over the knowledge graph.

  upstream   - follow incoming edges: who depends on the target (default;
               this is the blast radius of a change).
  downstream - follow outgoing edges: what the target depends on.
  both       - union of the two.

Each hop multiplies a decay factor by the relationship weight, so a table
read directly by a page scores higher than one reached through six hops.
Weights, label multipliers and the definition of an "entry point" arrive
through `ImpactConfig`, because those are the only parts that differ between
a TIBCO estate and an APEX one.
"""
from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..model import Graph, GraphNode

DEFAULT_DEPTH = 6
DEFAULT_DECAY = 0.75

RISK_BANDS = [
    (60.0, 'CRITICAL'),
    (30.0, 'HIGH'),
    (12.0, 'MEDIUM'),
    (0.0, 'LOW'),
]


def band(score: float) -> str:
    for threshold, label in RISK_BANDS:
        if score > threshold:
            return label
    return 'LOW'


@dataclass
class ImpactConfig:
    """Dialect knobs for the traversal and the score."""
    weights: Dict[str, float] = field(default_factory=dict)
    default_weight: float = 0.5
    excluded_rels: Set[str] = field(default_factory=set)
    label_multipliers: Dict[str, float] = field(default_factory=dict)
    entry_predicate: Optional[Callable[[GraphNode], bool]] = None
    entry_bonus: float = 6.0
    # (heading, predicate) pairs rendered as the "required test scope" block
    test_buckets: List[Tuple[str, Callable[[Dict[str, Any]], bool]]] = field(default_factory=list)

    def weight_of(self, rel_type: str) -> float:
        return self.weights.get(rel_type, self.default_weight)

    def is_entry(self, node: GraphNode) -> bool:
        return bool(self.entry_predicate and self.entry_predicate(node))


class ImpactAnalyzer:
    """Computes the blast radius of a change to one or more nodes."""

    def __init__(self, graph: Graph, config: ImpactConfig, decay: float = DEFAULT_DECAY):
        self.graph = graph
        self.config = config
        self.decay = decay

    # ------------------------------------------------------------------
    def analyze(self, targets: List[GraphNode], depth: int = DEFAULT_DEPTH,
                direction: str = 'upstream',
                include_rels: Optional[Set[str]] = None,
                exclude_rels: Optional[Set[str]] = None) -> Dict[str, Any]:
        exclude = set(exclude_rels or set()) | set(self.config.excluded_rels)
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
                'hops': info['hops'],
                'weight': round(info['weight'], 4),
                'via': info['path'],
                'isEntry': self.config.is_entry(node),
                'pageId': node.properties.get('pageId', ''),
                'owner': node.properties.get('owner', ''),
                'tier': node.properties.get('tier', ''),
                'filePath': node.properties.get('sourceFile', node.file_path),
                'parent': info.get('parent'),
                'parentRel': info.get('parentRel', ''),
            })
        impacted.sort(key=lambda r: (-r['weight'], r['hops'], r['label'], r['name']))

        by_label: Dict[str, int] = defaultdict(int)
        for row in impacted:
            by_label[row['label']] += 1
        entry_points = [r for r in impacted if r['isEntry']]
        risk = self._risk_score(impacted, entry_points)

        return {
            'targets': [{'nodeId': t.node_id, 'label': t.label, 'name': t.name,
                         'filePath': t.properties.get('sourceFile', t.file_path)}
                        for t in targets],
            'parameters': {'depth': depth, 'direction': direction, 'decay': self.decay,
                           'includeRels': sorted(include_rels) if include_rels else 'ALL',
                           'excludeRels': sorted(exclude)},
            'summary': {
                'impactedNodes': len(impacted),
                'impactedByLabel': dict(sorted(by_label.items(), key=lambda kv: -kv[1])),
                'affectedEntryPoints': len(entry_points),
                'riskScore': risk,
                'riskBand': band(risk),
            },
            'entryPoints': entry_points,
            'impacted': impacted,
            'testScope': self._test_scope(impacted, entry_points),
            'cypher': self._equivalent_cypher(targets, depth, direction, exclude),
        }

    # ------------------------------------------------------------------
    def _traverse(self, targets: List[GraphNode], depth: int, direction: str,
                  include_rels: Optional[Set[str]], exclude_rels: Set[str]
                  ) -> Dict[str, Dict[str, Any]]:
        """Best-first search keeping, per node, the strongest path found."""
        best: Dict[str, Dict[str, Any]] = {}
        heap: List[Tuple[float, int, str, List[str]]] = []
        for target in targets:
            best[target.node_id] = {'weight': 1.0, 'hops': 0, 'path': [],
                                    'parent': None, 'parentRel': ''}
            heapq.heappush(heap, (-1.0, 0, target.node_id, []))

        while heap:
            neg_weight, hops, node_id, path = heapq.heappop(heap)
            weight = -neg_weight
            if hops >= depth:
                continue
            current = best.get(node_id)
            if current and weight < current['weight'] - 1e-9:
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
                new_weight = weight * self.config.weight_of(rel.rel_type) * self.decay
                if new_weight < 0.01:
                    continue
                prior = best.get(neighbour)
                if prior and prior['weight'] >= new_weight - 1e-9:
                    continue
                step = (f"<-[{rel.rel_type}]-" if arrow == 'IN'
                        else f"-[{rel.rel_type}]->")
                new_path = path + [step]
                best[neighbour] = {'weight': new_weight, 'hops': hops + 1,
                                   'path': new_path, 'parent': node_id,
                                   'parentRel': rel.rel_type}
                heapq.heappush(heap, (-new_weight, hops + 1, neighbour, new_path))
        return best

    # ------------------------------------------------------------------
    def _risk_score(self, impacted: List[Dict[str, Any]],
                    entry_points: List[Dict[str, Any]]) -> float:
        """Weighted count of impacted artefacts, entry points weighted heaviest.

        Deterministic and comparable across runs; not calibrated to any
        absolute scale — use the band, and compare targets against each other.
        """
        score = sum(row['weight'] * self.config.label_multipliers.get(row['label'], 1.0)
                    for row in impacted)
        score += self.config.entry_bonus * len(entry_points)
        return round(score, 2)

    def _test_scope(self, impacted: List[Dict[str, Any]],
                    entry_points: List[Dict[str, Any]]) -> Dict[str, Any]:
        buckets: Dict[str, List[str]] = {}
        for heading, predicate in self.config.test_buckets:
            buckets[heading] = sorted({row['name'] for row in impacted if predicate(row)})
        buckets['User-visible surfaces'] = sorted({e['name'] for e in entry_points})
        recommendation = (
            'Re-test every listed user-visible surface end to end before releasing '
            'this change.' if entry_points else
            'No user-visible surface is reached; scope regression to the listed '
            'components.')
        return {'buckets': buckets, 'recommendation': recommendation}

    def _equivalent_cypher(self, targets: List[GraphNode], depth: int,
                           direction: str, exclude: Set[str]) -> str:
        ids = ', '.join(f"'{t.node_id}'" for t in targets)
        arrow_l, arrow_r = ('<-', '-') if direction == 'upstream' else ('-', '->')
        if direction == 'both':
            arrow_l, arrow_r = '-', '-'
        skipped = ', '.join(f"'{r}'" for r in sorted(exclude)) or "''"
        return (
            f"MATCH (t) WHERE t.nodeId IN [{ids}]\n"
            f"MATCH path = (t){arrow_l}[r*1..{depth}]{arrow_r}(affected)\n"
            f"WHERE none(rel IN r WHERE type(rel) IN [{skipped}])\n"
            f"RETURN DISTINCT labels(affected)[0] AS Type, affected.name AS Name,\n"
            f"       min(length(path)) AS Hops\n"
            f"ORDER BY Hops, Type, Name;"
        )


# ──────────────────────────────────────────────────────────────
# Rendering
# ──────────────────────────────────────────────────────────────
def render_markdown(result: Dict[str, Any], max_rows: int = 60,
                    title: str = 'Change Impact / Blast Radius Report') -> str:
    targets = ', '.join(f"`{t['label']}:{t['name']}`" for t in result['targets'])
    summary = result['summary']
    lines = [
        f'# {title}', '',
        f"**Target(s):** {targets}  ",
        f"**Direction:** {result['parameters']['direction']} "
        f"(depth {result['parameters']['depth']})  ",
        f"**Risk band:** {summary['riskBand']} (score {summary['riskScore']})", '',
        '## Summary', '',
        '| Metric | Value |', '|---|---|',
        f"| Impacted artefacts | {summary['impactedNodes']} |",
        f"| Affected user-visible surfaces | {summary['affectedEntryPoints']} |", '',
        '### Impacted by type', '', '| Type | Count |', '|---|---|',
    ]
    for label, count in summary['impactedByLabel'].items():
        lines.append(f'| {label} | {count} |')

    lines += ['', '## Affected user-visible surfaces', '']
    if result['entryPoints']:
        lines += ['| Surface | Type | Hops |', '|---|---|---|']
        for entry in result['entryPoints']:
            lines.append(f"| {entry['name']} | {entry['label']} | {entry['hops']} |")
    else:
        lines.append('_None — the change does not reach a user-visible surface._')

    lines += ['', '## Impacted artefacts (strongest coupling first)', '',
              '| # | Type | Name | Hops | Weight | Path |',
              '|---|---|---|---|---|---|']
    for i, row in enumerate(result['impacted'][:max_rows], 1):
        via = ' '.join(row['via'][-3:]) or 'direct'
        lines.append(f"| {i} | {row['label']} | {row['name']} | {row['hops']} | "
                     f"{row['weight']} | `{via}` |")
    if len(result['impacted']) > max_rows:
        lines.append(f"| … | | _{len(result['impacted']) - max_rows} more_ | | | |")

    scope = result['testScope']
    lines += ['', '## Required test scope', '']
    for heading, names in scope['buckets'].items():
        shown = ', '.join(names[:25]) or 'none'
        more = f' (+{len(names) - 25} more)' if len(names) > 25 else ''
        lines.append(f'- **{heading}:** {shown}{more}')
    lines += ['', f"> {scope['recommendation']}", '',
              '## Equivalent Cypher', '', '```cypher', result['cypher'], '```', '']
    return '\n'.join(lines)


def render_mermaid(result: Dict[str, Any], max_nodes: int = 40) -> str:
    """Mermaid flowchart of the blast radius."""
    def nid(node_id: str) -> str:
        return 'n' + ''.join(c if c.isalnum() else '_' for c in node_id)

    lines = ['flowchart LR']
    for target in result['targets']:
        lines.append(f'  {nid(target["nodeId"])}["CHANGE: {target["label"]}'
                     f'<br/>{target["name"]}"]:::target')

    shown = result['impacted'][:max_nodes]
    known = {t['nodeId'] for t in result['targets']} | {r['nodeId'] for r in shown}
    for row in shown:
        cls = 'entry' if row['isEntry'] else 'impacted'
        lines.append(f'  {nid(row["nodeId"])}["{row["label"]}<br/>{row["name"]}"]:::{cls}')
    lines.append('')
    for row in shown:
        parent = row.get('parent')
        if parent and parent in known:
            lines.append(f'  {nid(row["nodeId"])} -->|{row.get("parentRel", "")}| '
                         f'{nid(parent)}')
    lines += ['',
              '  classDef target fill:#b91c1c,stroke:#7f1d1d,color:#ffffff,stroke-width:2px;',
              '  classDef entry fill:#1d4ed8,stroke:#1e3a8a,color:#ffffff;',
              '  classDef impacted fill:#f1f5f9,stroke:#64748b,color:#0f172a;']
    return '\n'.join(lines)
