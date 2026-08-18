"""Traversal helpers shared by the derived-analysis modules."""
from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, List, Optional, Set

from analyzer_core.model import Graph, GraphNode

from ..constants import IMPACT_EXCLUDED_RELS

CONTAINMENT_RELS = {
    'CONTAINS_PAGE', 'CONTAINS_REGION', 'CONTAINS_SUBREGION', 'CONTAINS_ITEM',
    'CONTAINS_BUTTON', 'CONTAINS_PROCESS', 'CONTAINS_VALIDATION',
    'CONTAINS_BRANCH', 'CONTAINS_COMPUTATION', 'CONTAINS_DYNAMIC_ACTION',
    'CONTAINS_ACTION', 'CONTAINS_COLUMN',
}

DEPENDENCY_RELS = CONTAINMENT_RELS | {
    'EXECUTES_SQL', 'EXECUTES_PLSQL', 'EXECUTES_JS', 'READS_FROM', 'WRITES_TO',
    'INSERTS_INTO', 'UPDATES', 'DELETES_FROM', 'CALLS', 'SOURCED_FROM',
    'DEPENDS_ON', 'REFERENCES_COLUMN', 'USES_SEQUENCE', 'USES_LOV',
    'RESOLVES_TO', 'CALLS_WEB_SOURCE', 'RUNS',
}

WRITE_RELS = {'WRITES_TO', 'INSERTS_INTO', 'UPDATES', 'DELETES_FROM'}


def descend(graph: Graph, start: str, rel_types: Optional[Set[str]] = None,
            max_depth: int = 8) -> Dict[str, int]:
    """Node ids reachable from `start` following outgoing edges, with hops."""
    allowed = rel_types if rel_types is not None else DEPENDENCY_RELS
    seen: Dict[str, int] = {start: 0}
    queue = deque([(start, 0)])
    while queue:
        node_id, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for rel in graph.outgoing(node_id):
            if rel.rel_type in IMPACT_EXCLUDED_RELS:
                continue
            if allowed and rel.rel_type not in allowed:
                continue
            if rel.end_id in seen:
                continue
            seen[rel.end_id] = depth + 1
            queue.append((rel.end_id, depth + 1))
    seen.pop(start, None)
    return seen


def ascend(graph: Graph, start: str, rel_types: Optional[Set[str]] = None,
           max_depth: int = 8) -> Dict[str, int]:
    """Node ids that reach `start` following incoming edges, with hops."""
    allowed = rel_types if rel_types is not None else DEPENDENCY_RELS
    seen: Dict[str, int] = {start: 0}
    queue = deque([(start, 0)])
    while queue:
        node_id, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for rel in graph.incoming(node_id):
            if rel.rel_type in IMPACT_EXCLUDED_RELS:
                continue
            if allowed and rel.rel_type not in allowed:
                continue
            if rel.start_id in seen:
                continue
            seen[rel.start_id] = depth + 1
            queue.append((rel.start_id, depth + 1))
    seen.pop(start, None)
    return seen


def nodes_of(graph: Graph, ids: Iterable[str], label: str) -> List[GraphNode]:
    out = []
    for node_id in ids:
        node = graph.node(node_id)
        if node is not None and node.label == label:
            out.append(node)
    return out


def owning_page(graph: Graph, node_id: str) -> Optional[GraphNode]:
    """Walk containment upward to the page a component belongs to."""
    seen = {node_id}
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        for rel in graph.incoming(current):
            if rel.rel_type not in CONTAINMENT_RELS:
                continue
            node = graph.node(rel.start_id)
            if node is None or rel.start_id in seen:
                continue
            if node.label == 'ApexPage':
                return node
            seen.add(rel.start_id)
            queue.append(rel.start_id)
    return None


def pages_reaching(graph: Graph, node_id: str, max_depth: int = 8) -> List[GraphNode]:
    """Every page whose dependency chain reaches this node."""
    return nodes_of(graph, ascend(graph, node_id, max_depth=max_depth), 'ApexPage')


def label_counts(graph: Graph, ids: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for node_id in ids:
        node = graph.node(node_id)
        if node is not None:
            counts[node.label] = counts.get(node.label, 0) + 1
    return counts


def write_targets(graph: Graph, node_ids: Iterable[str]) -> Set[str]:
    """Tables written by any of the given nodes (direct edges only)."""
    targets: Set[str] = set()
    for node_id in node_ids:
        for rel in graph.outgoing(node_id):
            if rel.rel_type in WRITE_RELS:
                targets.add(rel.end_id)
    return targets
