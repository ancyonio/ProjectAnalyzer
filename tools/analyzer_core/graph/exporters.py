"""Neo4j delivery: admin-import CSVs, a runnable Cypher script and the
index/constraint sidecar the push script consumes.

Dialect-agnostic. Everything that differs between technologies — which
properties are typed, which indexes matter, which full-text indexes to build
— arrives as a `Neo4jSchema`, so one exporter serves every analyzer.

Multi-label nodes: a node keeps one primary `label`, and any additional
labels live in the reserved `extraLabels` property (semicolon separated).
The exporter emits `Primary;Extra` in the `label:LABEL` column, which
`neo4j-admin import` and `scripts/push_to_neo4j.py` both understand, and
`(:Primary:Extra { … })` in the Cypher script.

Every artefact is a pure function of the graph, so two runs on unchanged
input produce identical files — which is what makes them safe to commit and
diff in CI.
"""
from __future__ import annotations

import csv
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from ..model import Graph, GraphNode
from ..utils import escape_cypher

logger = logging.getLogger('analyzer_core')

EXTRA_LABELS_KEY = 'extraLabels'


@dataclass
class Neo4jSchema:
    """Physical-model description for one dialect."""
    title: str = 'Knowledge Graph'
    int_fields: Set[str] = field(default_factory=set)
    float_fields: Set[str] = field(default_factory=set)
    bool_fields: Set[str] = field(default_factory=set)
    # (label, [property, …]) — composite key constraints beyond nodeId
    composite_constraints: List[Tuple[str, List[str]]] = field(default_factory=list)
    # (label, [property, …]) — secondary indexes
    indexes: List[Tuple[str, List[str]]] = field(default_factory=list)
    # (index name, [label, …], [property, …])
    fulltext: List[Tuple[str, List[str], List[str]]] = field(default_factory=list)

    def column_type(self, key: str) -> str:
        if key in self.int_fields:
            return 'int'
        if key in self.float_fields:
            return 'float'
        if key in self.bool_fields:
            return 'boolean'
        return ''


def node_labels(node: GraphNode) -> List[str]:
    """Primary label first, then any `extraLabels`, de-duplicated."""
    labels = [node.label]
    extra = node.properties.get(EXTRA_LABELS_KEY, '')
    if extra:
        for lbl in str(extra).split(';'):
            lbl = lbl.strip()
            if lbl and lbl not in labels:
                labels.append(lbl)
    return labels


class Neo4jExporter:
    """Writes Neo4j-ready artefacts for a `Graph`."""

    def __init__(self, graph: Graph, output_dir: Path, schema: Neo4jSchema):
        self.graph = graph
        self.nodes = graph.nodes
        self.rels = graph.rels
        self.schema = schema
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def write_all(self) -> Dict[str, str]:
        nodes_csv, rels_csv = self._write_csv()
        cypher = self._write_cypher()
        indexes = self._write_index_sidecar()
        return {
            'nodes_csv': str(nodes_csv),
            'relationships_csv': str(rels_csv),
            'cypher_script': str(cypher),
            'index_sidecar': str(indexes),
        }

    # ------------------------------------------------------------------
    def all_labels(self) -> List[str]:
        labels: Set[str] = set()
        for node in self.nodes.values():
            labels.update(node_labels(node))
        return sorted(labels)

    def _write_csv(self) -> Tuple[Path, Path]:
        prop_keys: Set[str] = set()
        for node in self.nodes.values():
            prop_keys.update(k for k in node.properties if k != EXTRA_LABELS_KEY)

        typed_keys: Dict[str, str] = {}
        for key in sorted(prop_keys):
            kind = self.schema.column_type(key)
            typed_keys[key] = f'{key}:{kind}' if kind else key

        columns = ['nodeId:ID', 'label:LABEL', 'name'] + [typed_keys[k] for k in sorted(prop_keys)]
        nodes_path = self.output_dir / 'neo4j_nodes.csv'
        with open(nodes_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction='ignore', restval='')
            writer.writeheader()
            for node in self.nodes.values():
                row = {'nodeId:ID': node.node_id,
                       'label:LABEL': ';'.join(node_labels(node)),
                       'name': node.name}
                for key, value in node.properties.items():
                    if key == EXTRA_LABELS_KEY or value is None or value == '':
                        continue
                    col = typed_keys.get(key, key)
                    row[col] = str(value).lower() if isinstance(value, bool) else str(value)
                writer.writerow(row)

        rel_prop_keys: Set[str] = set()
        for rel in self.rels:
            rel_prop_keys.update(rel.properties.keys())
        rel_columns = [':START_ID', ':END_ID', ':TYPE'] + [
            f'{k}:float' if k in self.schema.float_fields else
            (f'{k}:int' if k in self.schema.int_fields else k)
            for k in sorted(rel_prop_keys)]

        rels_path = self.output_dir / 'neo4j_relationships.csv'
        with open(rels_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=rel_columns, extrasaction='ignore', restval='')
            writer.writeheader()
            for rel in self.rels:
                row = {':START_ID': rel.start_id, ':END_ID': rel.end_id, ':TYPE': rel.rel_type}
                for key, value in rel.properties.items():
                    if value is None or value == '':
                        continue
                    col = (f'{key}:float' if key in self.schema.float_fields else
                           f'{key}:int' if key in self.schema.int_fields else key)
                    row[col] = str(value).lower() if isinstance(value, bool) else str(value)
                writer.writerow(row)

        logger.info("  CSV: %s nodes -> %s", len(self.nodes), nodes_path.name)
        logger.info("  CSV: %s rels  -> %s", len(self.rels), rels_path.name)
        return nodes_path, rels_path

    # ------------------------------------------------------------------
    def _schema_statements(self) -> List[str]:
        present = set(self.all_labels())
        out = ['// --- CONSTRAINTS ---']
        for label in sorted(present):
            out.append(f'CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) '
                       f'REQUIRE n.nodeId IS UNIQUE;')
        for label, props in self.schema.composite_constraints:
            if label in present:
                keys = ', '.join(f'n.`{p}`' for p in props)
                out.append(f'CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) '
                           f'REQUIRE ({keys}) IS UNIQUE;')
        out.append('')
        out.append('// --- INDEXES ---')
        for label in sorted(present):
            out.append(f'CREATE INDEX IF NOT EXISTS FOR (n:`{label}`) ON (n.name);')
        for label, props in self.schema.indexes:
            if label in present:
                keys = ', '.join(f'n.`{p}`' for p in props)
                out.append(f'CREATE INDEX IF NOT EXISTS FOR (n:`{label}`) ON ({keys});')
        for name, labels, props in self.schema.fulltext:
            usable = [lbl for lbl in labels if lbl in present]
            if not usable:
                continue
            label_expr = '|'.join(f'`{lbl}`' for lbl in usable)
            prop_expr = ', '.join(f'n.`{p}`' for p in props)
            out.append(f'CREATE FULLTEXT INDEX {name} IF NOT EXISTS '
                       f'FOR (n:{label_expr}) ON EACH [{prop_expr}];')
        return out

    def _write_index_sidecar(self) -> Path:
        """Machine-readable constraints/indexes for `scripts/push_to_neo4j.py`."""
        present = set(self.all_labels())
        payload = {
            'schemaVersion': self.graph.meta.get('schemaVersion', ''),
            'title': self.schema.title,
            'labels': sorted(present),
            'relationshipTypes': sorted({r.rel_type for r in self.rels}),
            'uniqueConstraints': [{'label': lbl, 'properties': ['nodeId']}
                                  for lbl in sorted(present)],
            'compositeConstraints': [{'label': lbl, 'properties': props}
                                     for lbl, props in self.schema.composite_constraints
                                     if lbl in present],
            'indexes': ([{'label': lbl, 'properties': ['name']} for lbl in sorted(present)] +
                        [{'label': lbl, 'properties': props}
                         for lbl, props in self.schema.indexes if lbl in present]),
            'fulltextIndexes': [{'name': name,
                                 'labels': [l for l in labels if l in present],
                                 'properties': props}
                                for name, labels, props in self.schema.fulltext
                                if any(l in present for l in labels)],
        }
        path = self.output_dir / 'neo4j_indexes.json'
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        logger.info("  Sidecar: %s", path.name)
        return path

    # ------------------------------------------------------------------
    def _write_cypher(self) -> Path:
        cypher_path = self.output_dir / 'neo4j_import.cypher'
        rel_types = sorted({r.rel_type for r in self.rels})
        labels = self.all_labels()

        nodes_by_label: Dict[str, List[GraphNode]] = defaultdict(list)
        for node in self.nodes.values():
            nodes_by_label[node.label].append(node)
        rels_by_type: Dict[str, List] = defaultdict(list)
        for rel in self.rels:
            rels_by_type[rel.rel_type].append(rel)

        with open(cypher_path, 'w', encoding='utf-8') as fh:
            fh.write('// ================================================================\n')
            fh.write(f'// {self.schema.title} -> Neo4j import script\n')
            fh.write(f'// Nodes: {len(self.nodes):,}  |  Relationships: {len(self.rels):,}\n')
            fh.write(f'// Labels: {", ".join(labels)}\n')
            fh.write(f'// Rel types: {", ".join(rel_types)}\n')
            fh.write('// Deterministic: regenerated identically from the same graph.json\n')
            fh.write('// ================================================================\n\n')
            fh.write('\n'.join(self._schema_statements()))
            fh.write('\n\n')

            for label in sorted(nodes_by_label):
                group = nodes_by_label[label]
                fh.write(f'\n// --- {label} ({len(group)}) ---\n\n')
                for node in group:
                    fh.write(f'CREATE (:{":".join(node_labels(node))} '
                             f'{{{self._props(node)}}});\n')

            fh.write('\n\n')
            for rtype in sorted(rels_by_type):
                group = rels_by_type[rtype]
                fh.write(f'\n// --- {rtype} ({len(group)}) ---\n\n')
                for rel in group:
                    props = _prop_literals(rel.properties)
                    suffix = f' {{{props}}}' if props else ''
                    fh.write(f"MATCH (a {{nodeId: '{escape_cypher(rel.start_id)}'}}), "
                             f"(b {{nodeId: '{escape_cypher(rel.end_id)}'}}) "
                             f'CREATE (a)-[:{rtype}{suffix}]->(b);\n')
            fh.write('\n// Import complete.\n')

        logger.info("  Cypher: %s", cypher_path.name)
        return cypher_path

    def _props(self, node: GraphNode) -> str:
        pairs = [f"nodeId: '{escape_cypher(node.node_id)}'",
                 f"name: '{escape_cypher(node.name)}'"]
        payload = {k: v for k, v in node.properties.items() if k != EXTRA_LABELS_KEY}
        rendered = _prop_literals(payload)
        if rendered:
            pairs.append(rendered)
        return ', '.join(pairs)


def _prop_literals(properties: Dict[str, Any]) -> str:
    out: List[str] = []
    for key, value in sorted(properties.items()):
        if value is None or value == '':
            continue
        if isinstance(value, bool):
            out.append(f'{key}: {str(value).lower()}')
        elif isinstance(value, (int, float)):
            out.append(f'{key}: {value}')
        else:
            out.append(f"{key}: '{escape_cypher(str(value))}'")
    return ', '.join(out)
