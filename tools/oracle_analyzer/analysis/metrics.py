"""Derived metrics.

Fan-in and fan-out are computed once, here, rather than recomputed by every
consumer, and are attached both as unit properties (cheap to filter on) and as
`CodeMetric` nodes (so a later run can trend them across commits).
"""
from __future__ import annotations

from typing import Dict

from analyzer_core.model import GraphNode

_TRACKED = ('DbProgramUnit', 'DbPackage', 'DbTable', 'DbView')


def _churn_by_path(analyzer) -> Dict[str, int]:
    """How often each source file changed, keyed by path.

    The Git layer counts commits against `File` nodes, which is where the
    evidence is. An object's churn is its file's churn, so the lookup happens
    here rather than every consumer re-deriving it.
    """
    return {path: node.properties.get('commitCount', 0)
            for node in analyzer.nodes.values() if node.label == 'File'
            for path in (node.properties.get('filePath'),) if path}


def _churn_for(analyzer, node, churn: Dict[str, int]) -> int:
    """A node's churn, following package halves when it has no file of its own.

    A package is a logical node spanning two files; its spec and body carry the
    paths. Taking the larger of the two keeps a heavily-edited body from being
    hidden behind a stable spec.
    """
    path = node.properties.get('filePath')
    if path:
        return churn.get(path, 0)
    counts = [churn.get(analyzer.nodes[rel.end_id].properties.get('filePath'), 0)
              for rel in analyzer.rels
              if rel.start_id == node.node_id
              and rel.rel_type in ('HAS_SPEC', 'HAS_BODY')
              and rel.end_id in analyzer.nodes]
    return max(counts, default=0)


def attach_metrics(analyzer) -> int:
    """Attach fan-in/fan-out and a CodeMetric node to every tracked object."""
    incoming: Dict[str, int] = {}
    outgoing: Dict[str, int] = {}
    for rel in analyzer.rels:
        if rel.rel_type in ('CALLS', 'READS_FROM', 'WRITES_TO', 'DEPENDS_ON',
                            'EXECUTES_SQL', 'FIRES_ON'):
            outgoing[rel.start_id] = outgoing.get(rel.start_id, 0) + 1
            incoming[rel.end_id] = incoming.get(rel.end_id, 0) + 1

    churn = _churn_by_path(analyzer)
    created = 0
    for node in list(analyzer.nodes.values()):
        if node.label not in _TRACKED:
            continue
        fan_in = incoming.get(node.node_id, 0)
        fan_out = outgoing.get(node.node_id, 0)
        node.properties['fanIn'] = fan_in
        node.properties['fanOut'] = fan_out
        commit_count = _churn_for(analyzer, node, churn)
        node.properties['commitCount'] = commit_count

        metric_id = f'{node.node_id}#metric'
        analyzer._add_node(GraphNode(metric_id, 'CodeMetric', node.name, {
            'target': node.node_id,
            'targetLabel': node.label,
            'fanIn': fan_in,
            'fanOut': fan_out,
            'loc': node.properties.get('loc', 0),
            'complexity': node.properties.get('complexity', 0.0),
            'commitCount': commit_count,
        }))
        analyzer._add_rel(node.node_id, metric_id, 'HAS_METRIC',
                          purpose='derived-metric')
        created += 1
    return created
