"""Federation: three finished graphs in, one federated graph out.

This module reads `graph.json` from each estate's output directory and nothing
else. It never parses source, never re-derives a fact an analyzer already
computed, and never writes into an estate's output directory.

The one decision that matters is node identity. Every imported id is prefixed
with its estate (`tibco:act_0007`, `apex:app100:p20`) except the `db:` family,
which is left alone so the APEX and Oracle views of one table become one node.
That merge is the entire reason the three analyzers share
`analyzer_core.ids`; see docs/ESTATE_ANALYZER_SPEC.md section 2.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from analyzer_core.model import Graph, GraphNode, GraphRel

from .constants import (CATEGORY_CANON, ESTATE_ID_SEP, ESTATE_ROOT_LABELS,
                        ESTATE_TITLES, ESTATES, RULE_PREFIXES, SCHEMA_VERSION,
                        SHARED_ID_PREFIXES)

logger = logging.getLogger('estate_analyzer')

GRAPH_FILE = 'graph.json'

# Properties that describe an estate's *view* of a shared object rather than
# the object itself: each estate measured its own graph and its own files, so
# both values are correct and merging them into one would be a fiction.
PER_ESTATE_PROPERTIES: Tuple[str, ...] = (
    'origin', 'fanIn', 'fanOut', 'filePath', 'sourceFile', 'lineStart',
    'lineEnd', 'confidence', 'datasetId',
)

_MERGE_RESERVED = frozenset(
    {'estate', 'estates', 'sourceNodeId', 'extraLabels', 'merged'})


# ──────────────────────────────────────────────────────────────
@dataclass
class EstateSource:
    """One analysed estate, as its analyzer left it."""
    estate: str
    output_dir: Path
    graph: Graph

    @property
    def source_root(self) -> str:
        meta = self.graph.meta or {}
        for key in ('tibcoRoot', 'sourceRoot', 'apexSource', 'source'):
            if meta.get(key):
                return str(meta[key])
        return ''

    @property
    def coverage(self) -> Dict[str, Any]:
        return dict((self.graph.meta or {}).get('coverage') or {})


def load_sources(paths: Dict[str, Path]) -> List[EstateSource]:
    """Load the estates the caller named, in the canonical estate order.

    A missing directory is a usage error, not something to work around: a
    federation quietly built from two estates would answer three-estate
    questions with a two-estate graph.
    """
    sources: List[EstateSource] = []
    for estate in ESTATES:
        directory = paths.get(estate)
        if directory is None:
            continue
        path = Path(directory) / GRAPH_FILE
        if not path.exists():
            raise FileNotFoundError(
                f"No {GRAPH_FILE} for the {estate} estate at {path}. Run that "
                f"analyzer's `analyze` command first, or drop --{estate}.")
        sources.append(EstateSource(estate, Path(directory), Graph.load(path)))
    if not sources:
        raise ValueError('Name at least one estate: --tibco, --apex or --oracle.')
    return sources


# ──────────────────────────────────────────────────────────────
def is_shared_id(node_id: str) -> bool:
    """True when two estates using this id mean the same object."""
    return any(node_id.startswith(prefix) for prefix in SHARED_ID_PREFIXES)


def federated_id(estate: str, node_id: str) -> str:
    return node_id if is_shared_id(node_id) else f'{estate}{ESTATE_ID_SEP}{node_id}'


# ──────────────────────────────────────────────────────────────
@dataclass
class Federation:
    """Builds the federated graph and records what it had to reconcile.

    `authority` ranks the estates for property arbitration on a merged node.
    An estate that supplied a data-dictionary extract outranks one that only
    parsed DDL, because the dictionary describes the deployed database and the
    DDL describes a repository. Without that rule the winner would be whichever
    estate happened to be loaded first, which is not a reason.
    """
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    rels: List[GraphRel] = field(default_factory=list)
    contributors: Dict[str, List[str]] = field(default_factory=dict)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    authority: Dict[str, int] = field(default_factory=dict)
    _owners: Dict[str, Dict[str, str]] = field(default_factory=dict)
    _rel_keys: set = field(default_factory=set)

    # ------------------------------------------------------------------
    def add_node(self, node: GraphNode, estate: str) -> str:
        """Import one node, merging it when the id is shared."""
        new_id = federated_id(estate, node.node_id)
        existing = self.nodes.get(new_id)
        if existing is None:
            properties = dict(node.properties)
            properties['estate'] = estate
            properties['sourceNodeId'] = node.node_id
            for key in PER_ESTATE_PROPERTIES:
                if key in properties:
                    properties[f'{key}ByEstate'] = f'{estate}={properties[key]}'
            self.nodes[new_id] = GraphNode(new_id, node.label, node.name, properties)
            self.contributors[new_id] = [estate]
            self._owners[new_id] = {key: estate for key in properties}
            return new_id

        self.contributors[new_id].append(estate)
        existing.properties['estates'] = ';'.join(self.contributors[new_id])
        existing.properties['merged'] = True
        existing.properties['extraLabels'] = _with_extra_label(
            existing.properties.get('extraLabels', ''), 'Federated')
        owners = self._owners.setdefault(new_id, {})
        rank = self.authority.get(estate, 0)

        for key, value in node.properties.items():
            if key in _MERGE_RESERVED:
                continue
            # Locally-scoped facts: each estate measured its own graph, so the
            # two values are both right and neither is the answer. Keep the
            # breakdown instead of manufacturing a conflict.
            if key in PER_ESTATE_PROPERTIES:
                existing.properties[f'{key}ByEstate'] = _append_by_estate(
                    existing.properties.get(f'{key}ByEstate', ''), estate, value)
                continue
            if key not in existing.properties or existing.properties[key] in (None, ''):
                existing.properties[key] = value
                owners[key] = estate
                continue
            if existing.properties[key] == value:
                continue
            incumbent = owners.get(key, self.contributors[new_id][0])
            if rank > self.authority.get(incumbent, 0):
                kept, kept_from, discarded, discarded_from = (
                    value, estate, existing.properties[key], incumbent)
                existing.properties[key] = value
                owners[key] = estate
            else:
                kept, kept_from, discarded, discarded_from = (
                    existing.properties[key], incumbent, value, estate)
            self.conflicts.append({
                'nodeId': new_id, 'property': key, 'kept': kept,
                'keptFrom': kept_from, 'discarded': discarded,
                'discardedFrom': discarded_from,
                'resolvedBy': ('data-dictionary authority'
                               if self.authority.get(kept_from, 0)
                               > self.authority.get(discarded_from, 0)
                               else 'first contributor'),
            })

        if existing.label != node.label:
            self.conflicts.append({
                'nodeId': new_id, 'property': 'label',
                'kept': existing.label, 'keptFrom': self.contributors[new_id][0],
                'discarded': node.label, 'discardedFrom': estate,
                'resolvedBy': 'first contributor',
            })
        return new_id

    def add_rel(self, start_id: str, end_id: str, rel_type: str,
                properties: Optional[Dict[str, Any]] = None) -> bool:
        """Add an edge, ignoring an exact duplicate.

        Two estates that both describe `ORDERS HAS_COLUMN ORDER_ID` are saying
        one thing, and counting it twice would inflate every fan-in figure
        built on the federated graph.
        """
        if start_id not in self.nodes or end_id not in self.nodes:
            return False
        key = (start_id, end_id, rel_type)
        if key in self._rel_keys:
            return False
        self._rel_keys.add(key)
        self.rels.append(GraphRel(start_id, end_id, rel_type, dict(properties or {})))
        return True

    def has_rel(self, start_id: str, end_id: str, rel_type: str) -> bool:
        return (start_id, end_id, rel_type) in self._rel_keys

    def merged_ids(self) -> List[str]:
        return sorted(nid for nid, who in self.contributors.items() if len(who) > 1)


def _append_by_estate(current: str, estate: str, value: Any) -> str:
    parts = [part for part in str(current or '').split(';') if part]
    entry = f'{estate}={value}'
    if entry not in parts:
        parts.append(entry)
    return ';'.join(parts)


def _with_extra_label(current: str, label: str) -> str:
    labels = [part.strip() for part in str(current or '').split(';') if part.strip()]
    if label not in labels:
        labels.append(label)
    return ';'.join(labels)


# ──────────────────────────────────────────────────────────────
def _namespace_finding(node: GraphNode, estate: str) -> None:
    """Prefix a rule id and canonicalise its category, in place.

    `SEC-001` is SQL injection in APEX and unresolvable dynamic SQL in Oracle.
    The original spelling is kept so a finding can be traced back to the
    analyzer that raised it.
    """
    prefix = RULE_PREFIXES.get(estate, '')
    rule_id = str(node.properties.get('ruleId', '') or '')
    if rule_id and not rule_id.startswith(prefix):
        node.properties['sourceRuleId'] = rule_id
        node.properties['ruleId'] = f'{prefix}{rule_id}'
        if node.name == rule_id:
            node.name = f'{prefix}{rule_id}'
        elif node.name.startswith(f'{rule_id} '):
            node.name = f'{prefix}{node.name}'
    category = str(node.properties.get('category', '') or '')
    if category:
        canonical = CATEGORY_CANON.get(category.upper(), category.upper())
        if canonical != category:
            node.properties['sourceCategory'] = category
            node.properties['category'] = canonical


def _estate_node(source: EstateSource) -> GraphNode:
    stats = source.graph.stats()
    return GraphNode(f'estate:{source.estate}', 'Estate', source.estate, {
        'title': ESTATE_TITLES.get(source.estate, source.estate),
        'outputDir': str(source.output_dir).replace('\\', '/'),
        'sourceRoot': source.source_root.replace('\\', '/'),
        'schemaVersion': (source.graph.meta or {}).get('schemaVersion', ''),
        'generatedAt': (source.graph.meta or {}).get('generatedAt', ''),
        'estateNodes': stats['totalNodes'],
        'estateRelationships': stats['totalRelationships'],
        'estate': source.estate,
    })


def _root_ids(source: EstateSource, federation: Federation) -> List[str]:
    """The estate's top-level containers, for the CONTAINS_ESTATE edges."""
    ids: List[str] = []
    for label in ESTATE_ROOT_LABELS.get(source.estate, ()):
        for node in source.graph.by_label(label):
            new_id = federated_id(source.estate, node.node_id)
            if new_id in federation.nodes:
                ids.append(new_id)
        if ids:
            break
    return ids


# ──────────────────────────────────────────────────────────────
def federate(sources: List[EstateSource]) -> Tuple[Graph, Federation]:
    """Union the estates into one graph. Cross-estate links come later.

    Returns the graph and the `Federation` that built it, because the link
    stage needs the builder's duplicate suppression and the reporting stage
    needs its conflict list.
    """
    federation = Federation(authority={
        source.estate: 1 if source.coverage.get('dictionaryAvailable') else 0
        for source in sources
    })

    for source in sources:
        for node in source.graph.nodes.values():
            new_id = federation.add_node(node, source.estate)
            if source.graph.nodes[node.node_id].label in ('Issue', 'Recommendation'):
                _namespace_finding(federation.nodes[new_id], source.estate)

    for source in sources:
        for rel in source.graph.rels:
            properties = dict(rel.properties)
            properties.setdefault('estate', source.estate)
            federation.add_rel(federated_id(source.estate, rel.start_id),
                               federated_id(source.estate, rel.end_id),
                               rel.rel_type, properties)

    for source in sources:
        estate_node = _estate_node(source)
        federation.nodes[estate_node.node_id] = estate_node
        federation.contributors[estate_node.node_id] = [source.estate]
        for root_id in _root_ids(source, federation):
            federation.add_rel(estate_node.node_id, root_id, 'CONTAINS_ESTATE',
                               {'estate': source.estate, 'purpose': 'estate-membership'})

    graph = Graph(federation.nodes, federation.rels, _meta(sources, federation))
    return graph, federation


def _meta(sources: List[EstateSource], federation: Federation) -> Dict[str, Any]:
    merged = federation.merged_ids()
    return {
        'schemaVersion': SCHEMA_VERSION,
        'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'estates': {
            source.estate: {
                'title': ESTATE_TITLES.get(source.estate, source.estate),
                'outputDir': str(source.output_dir).replace('\\', '/'),
                'sourceRoot': source.source_root.replace('\\', '/'),
                'schemaVersion': (source.graph.meta or {}).get('schemaVersion', ''),
                'nodes': source.graph.stats()['totalNodes'],
                'relationships': source.graph.stats()['totalRelationships'],
            }
            for source in sources
        },
        'propertyConflicts': federation.conflicts[:200],
        'propertyConflictCount': len(federation.conflicts),
        'coverage': {
            'estates': {source.estate: source.coverage for source in sources},
            'mergedDbNodes': len(merged),
            'mergedDbNodeIds': merged[:100],
        },
    }


def load_estate_map(path: Optional[Path]) -> Dict[str, Any]:
    """The operator-declared datasource mapping (spec section 5).

    A JDBC URL names a database, not an Oracle schema. Without this file the
    wrapper reports every JDBC resource as unmapped rather than guessing.
    """
    if path is None:
        return {'datasources': []}
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'Estate map not found at {path}')
    with open(path, encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get('datasources', []), list):
        raise ValueError(f'{path} must be an object with a "datasources" array')
    return data
