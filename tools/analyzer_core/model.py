"""Graph data model.

`Graph` is the deterministic artefact every other command reads. It is
persisted as `graph.json` so that `search`, `impact`, `diagrams`, `context`
and `report` never re-parse the source tree, and so that two runs on the
same input always produce byte-identical downstream output.

Dialect-agnostic: the TIBCO and APEX analyzers both build this structure.
The schema version travels in `meta['schemaVersion']` so each dialect can
version its own vocabulary independently.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

DEFAULT_SCHEMA_VERSION = '1.0.0'


@dataclass
class GraphNode:
    """A node in a knowledge graph."""
    node_id: str
    label: str
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {'id': self.node_id, 'label': self.label, 'name': self.name,
                'properties': self.properties}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'GraphNode':
        return GraphNode(d['id'], d['label'], d.get('name', ''), d.get('properties', {}) or {})

    # convenience accessors -------------------------------------------------
    @property
    def module(self) -> str:
        return str(self.properties.get('module', ''))

    @property
    def file_path(self) -> str:
        return str(self.properties.get('filePath', ''))


@dataclass
class GraphRel:
    """A relationship in a knowledge graph."""
    start_id: str
    end_id: str
    rel_type: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {'start': self.start_id, 'end': self.end_id, 'type': self.rel_type,
                'properties': self.properties}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'GraphRel':
        return GraphRel(d['start'], d['end'], d['type'], d.get('properties', {}) or {})


class Graph:
    """In-memory graph with adjacency indexes for traversal."""

    def __init__(self, nodes: Optional[Dict[str, GraphNode]] = None,
                 rels: Optional[List[GraphRel]] = None,
                 meta: Optional[Dict[str, Any]] = None):
        self.nodes: Dict[str, GraphNode] = nodes or {}
        self.rels: List[GraphRel] = rels or []
        self.meta: Dict[str, Any] = meta or {}
        self._out: Dict[str, List[GraphRel]] = {}
        self._in: Dict[str, List[GraphRel]] = {}
        self._by_label: Dict[str, List[GraphNode]] = {}
        self.reindex()

    # ------------------------------------------------------------------
    def reindex(self) -> None:
        out: Dict[str, List[GraphRel]] = defaultdict(list)
        inn: Dict[str, List[GraphRel]] = defaultdict(list)
        by_label: Dict[str, List[GraphNode]] = defaultdict(list)
        for r in self.rels:
            out[r.start_id].append(r)
            inn[r.end_id].append(r)
        for n in self.nodes.values():
            by_label[n.label].append(n)
        self._out, self._in, self._by_label = dict(out), dict(inn), dict(by_label)

    def outgoing(self, node_id: str) -> List[GraphRel]:
        return self._out.get(node_id, [])

    def incoming(self, node_id: str) -> List[GraphRel]:
        return self._in.get(node_id, [])

    def by_label(self, label: str) -> List[GraphNode]:
        return self._by_label.get(label, [])

    def labels(self) -> List[str]:
        return sorted(self._by_label)

    def node(self, node_id: str) -> Optional[GraphNode]:
        return self.nodes.get(node_id)

    def degree(self, node_id: str) -> int:
        return len(self.outgoing(node_id)) + len(self.incoming(node_id))

    # ------------------------------------------------------------------
    # Properties that identify a node as well as its name does. Kept
    # dialect-agnostic: each analyzer simply sets the ones it uses.
    IDENTITY_PROPERTIES = ('qualifiedName', 'alias', 'pageId', 'staticId',
                           'pageAlias', 'applicationId')

    def resolve(self, ref: str, label: Optional[str] = None) -> List[GraphNode]:
        """Resolve a user-supplied reference to candidate nodes.

        Accepts a node id (`bwp_0001`, `app100:p10`), an exact name, a
        `Label:Name` pair, an identity-bearing property (`ApexPage:20` by
        `pageId`, `ApexPage:HOME` by `alias`, a TIBCO resource by its
        `qualifiedName`), a file path, or a case-insensitive partial name.
        Returns every candidate so the caller can report ambiguity rather
        than guess.
        """
        if not ref:
            return []
        ref = ref.strip()
        if ':' in ref and ref.split(':', 1)[0] in self._by_label:
            label, ref = ref.split(':', 1)

        if ref in self.nodes and (label is None or self.nodes[ref].label == label):
            return [self.nodes[ref]]

        pool: Iterable[GraphNode] = self.by_label(label) if label else self.nodes.values()
        pool = list(pool)

        exact = [n for n in pool if n.name == ref]
        if exact:
            return exact

        # Reports refer to components by whichever identifier reads naturally --
        # "page 20", alias HOME, a fully-qualified resource name -- so accept
        # those too rather than forcing the caller back to the node name.
        lowered = ref.lower()
        by_identity = [n for n in pool
                       if any(str(n.properties.get(key, '')).lower() == lowered
                              for key in self.IDENTITY_PROPERTIES
                              if n.properties.get(key) not in (None, ''))]
        if by_identity:
            return by_identity

        norm = ref.replace('\\', '/').lstrip('./').lower()
        by_path = [n for n in pool if n.file_path and n.file_path.lower() == norm]
        if by_path:
            return by_path

        stem = norm.rsplit('/', 1)[-1]
        stem_no_ext = stem.rsplit('.', 1)[0] if '.' in stem else stem
        ci = [n for n in pool if n.name.lower() in (stem, stem_no_ext)]
        if ci:
            return ci

        path_suffix = [n for n in pool if n.file_path and n.file_path.lower().endswith(norm)]
        if path_suffix:
            return path_suffix

        return [n for n in pool if stem_no_ext and stem_no_ext in n.name.lower()]

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            'schemaVersion': self.meta.get('schemaVersion', DEFAULT_SCHEMA_VERSION),
            'meta': self.meta,
            'nodes': [n.to_dict() for n in self.nodes.values()],
            'relationships': [r.to_dict() for r in self.rels],
        }

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(self.to_dict(), fh, indent=2, default=str)
        return path

    @staticmethod
    def load(path: Path) -> 'Graph':
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Graph not found at {path}. Run the `analyze` command first."
            )
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        nodes = {d['id']: GraphNode.from_dict(d) for d in data.get('nodes', [])}
        rels = [GraphRel.from_dict(d) for d in data.get('relationships', [])]
        return Graph(nodes, rels, data.get('meta', {}))

    # ------------------------------------------------------------------
    def stats(self) -> Dict[str, Any]:
        node_counts: Dict[str, int] = defaultdict(int)
        rel_counts: Dict[str, int] = defaultdict(int)
        for n in self.nodes.values():
            node_counts[n.label] += 1
        for r in self.rels:
            rel_counts[r.rel_type] += 1
        return {
            'totalNodes': len(self.nodes),
            'totalRelationships': len(self.rels),
            'nodeCounts': dict(sorted(node_counts.items(), key=lambda kv: -kv[1])),
            'relationshipCounts': dict(sorted(rel_counts.items(), key=lambda kv: -kv[1])),
        }

    def modules(self) -> Set[str]:
        return {n.module for n in self.nodes.values() if n.module}
