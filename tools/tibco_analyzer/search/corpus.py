"""Search corpus builder.

Turns the knowledge graph plus the raw TIBCO source into one searchable
document per artefact. The document text deliberately mixes *structure*
(names, types, namespaces, Spring targets) with *behaviour* (XPath
conditions, SQL, log messages, JMS destinations, endpoint URIs), because
"where is credit scoring implemented?" is usually answered by the latter.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..model import Graph, GraphNode
from ..utils import element_text_blob, localname, safe_parse_xml, split_identifier

logger = logging.getLogger('tibco_analyzer')

# Labels worth indexing as standalone search hits.
INDEXED_LABELS = {
    'BWProcess', 'Activity', 'XSD', 'Element', 'ComplexType', 'Service',
    'Operation', 'SharedResource', 'GlobalVariable', 'DataTransformation',
    'AESchema', 'System', 'ErrorHandler', 'Module',
}

MAX_TEXT = 6000

# Behavioural detail the parsers lift out of activity configuration. Rolling
# these up onto the owning process is what lets "which process writes to
# ORDERS?" or "who publishes to ORDER.EVENTS.QUEUE?" hit the process itself
# and not just the individual activity.
BEHAVIOUR_KEYS = ('sqlStatement', 'sqlTables', 'sqlVerb', 'jmsDestination',
                  'endpointUri', 'httpMethod', 'storedProcedure', 'fileTarget',
                  'mailTo', 'javaClass', 'logMessage')


class Document:
    __slots__ = ('doc_id', 'node_id', 'label', 'name', 'module', 'file_path',
                 'text', 'snippet', 'properties')

    def __init__(self, doc_id: str, node_id: str, label: str, name: str,
                 module: str, file_path: str, text: str, snippet: str,
                 properties: Dict[str, Any]):
        self.doc_id = doc_id
        self.node_id = node_id
        self.label = label
        self.name = name
        self.module = module
        self.file_path = file_path
        self.text = text
        self.snippet = snippet
        self.properties = properties

    def to_dict(self) -> Dict[str, Any]:
        return {'docId': self.doc_id, 'nodeId': self.node_id, 'label': self.label,
                'name': self.name, 'module': self.module, 'filePath': self.file_path,
                'text': self.text, 'snippet': self.snippet, 'properties': self.properties}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'Document':
        return Document(d['docId'], d['nodeId'], d['label'], d['name'], d['module'],
                        d['filePath'], d['text'], d.get('snippet', ''),
                        d.get('properties', {}))


class CorpusBuilder:
    """Builds `Document`s from a `Graph` and (optionally) the source tree."""

    def __init__(self, graph: Graph, tibco_root: Optional[Path] = None):
        self.graph = graph
        self.tibco_root = Path(tibco_root) if tibco_root else None
        self._file_text_cache: Dict[str, str] = {}

    # ------------------------------------------------------------------
    def build(self) -> List[Document]:
        docs: List[Document] = []
        activities_by_proc: Dict[str, List[GraphNode]] = defaultdict(list)
        for act in self.graph.by_label('Activity'):
            proc_id = str(act.properties.get('processRef', ''))
            if proc_id:
                activities_by_proc[proc_id].append(act)

        for node in self.graph.nodes.values():
            if node.label not in INDEXED_LABELS:
                continue
            if node.label == 'BWProcess':
                docs.append(self._process_doc(node, activities_by_proc.get(node.node_id, [])))
            elif node.label == 'XSD':
                docs.append(self._schema_doc(node))
            elif node.label == 'Service':
                docs.append(self._service_doc(node))
            else:
                docs.append(self._generic_doc(node))
        logger.info("Corpus: %s documents", len(docs))
        return docs

    # ------------------------------------------------------------------
    def _source_text(self, file_path: str, limit: int = MAX_TEXT) -> str:
        if not self.tibco_root or not file_path:
            return ''
        if file_path in self._file_text_cache:
            return self._file_text_cache[file_path]
        full = self.tibco_root / file_path
        text = ''
        root = safe_parse_xml(full) if full.exists() else None
        if root is not None:
            text = element_text_blob(root, limit)
        self._file_text_cache[file_path] = text
        return text

    def _props_text(self, node: GraphNode, keys: List[str]) -> str:
        return ' '.join(str(node.properties.get(k, '')) for k in keys if node.properties.get(k))

    # ------------------------------------------------------------------
    def _process_doc(self, node: GraphNode, activities: List[GraphNode]) -> Document:
        act_names = [a.name for a in activities]
        act_categories = sorted({str(a.properties.get('category', '')) for a in activities})
        spring = sorted({str(a.properties.get('springEquivalent', '')) for a in activities})
        schemas = [self.graph.nodes[r.end_id].name
                   for r in self.graph.outgoing(node.node_id)
                   if r.rel_type == 'USES_XSD' and r.end_id in self.graph.nodes]
        conditions = [str(r.properties.get('condition', ''))
                      for r in self.graph.rels
                      if r.rel_type == 'TRANSITIONS_TO' and r.properties.get('condition')
                      and r.start_id in {a.node_id for a in activities}]
        behaviour = []
        for a in activities:
            for key in BEHAVIOUR_KEYS:
                value = a.properties.get(key)
                if value:
                    behaviour.append(str(value))

        parts = [
            node.name,
            node.module,
            self._props_text(node, ['entryType', 'endpoint', 'targetNamespace',
                                    'tier', 'folder', 'bwVersion']),
            ' '.join(act_names),
            ' '.join(act_categories),
            ' '.join(spring),
            ' '.join(schemas),
            ' '.join(behaviour)[:2000],
            ' '.join(conditions)[:1500],
            self._source_text(node.file_path),
        ]
        text = ' '.join(p for p in parts if p)
        snippet = (f"{node.properties.get('entryType', 'internal')} process, "
                   f"{len(activities)} activities, tier "
                   f"{node.properties.get('tier', '?')} "
                   f"({node.properties.get('complexityScore', 0)})")
        return Document(f"doc_{node.node_id}", node.node_id, node.label, node.name,
                        node.module, node.file_path, text[:MAX_TEXT], snippet,
                        dict(node.properties))

    def _schema_doc(self, node: GraphNode) -> Document:
        elements = [self.graph.nodes[r.end_id]
                    for r in self.graph.outgoing(node.node_id)
                    if r.rel_type == 'CONTAINS' and r.end_id in self.graph.nodes]
        elem_text = ' '.join(f"{e.name} {e.properties.get('xsdType', '')} "
                             f"{e.properties.get('javaType', '')}" for e in elements)
        users = [self.graph.nodes[r.start_id].name
                 for r in self.graph.incoming(node.node_id)
                 if r.rel_type in ('USES_XSD', 'IMPORTS_SCHEMA') and r.start_id in self.graph.nodes]
        text = ' '.join([node.name, node.module,
                         self._props_text(node, ['namespace', 'rootElements', 'folder']),
                         elem_text, ' '.join(users)])
        snippet = (f"{node.properties.get('elementCount', 0)} elements, "
                   f"namespace {node.properties.get('namespace', 'n/a')}, "
                   f"used by {len(users)} artefact(s)")
        return Document(f"doc_{node.node_id}", node.node_id, node.label, node.name,
                        node.module, node.file_path, text[:MAX_TEXT], snippet,
                        dict(node.properties))

    def _service_doc(self, node: GraphNode) -> Document:
        ops = [self.graph.nodes[r.end_id].name
               for r in self.graph.outgoing(node.node_id)
               if r.rel_type == 'EXPOSES' and r.end_id in self.graph.nodes]
        text = ' '.join([node.name, node.module, ' '.join(ops),
                         self._props_text(node, ['namespace', 'endpointUrl', 'bindingStyle',
                                                 'springEquivalent', 'type', 'folder']),
                         self._source_text(node.file_path, 2500)])
        snippet = (f"{node.properties.get('type', 'service')} with "
                   f"{node.properties.get('operationCount', len(ops))} operation(s)"
                   + (f": {', '.join(ops[:6])}" if ops else ''))
        return Document(f"doc_{node.node_id}", node.node_id, node.label, node.name,
                        node.module, node.file_path, text[:MAX_TEXT], snippet,
                        dict(node.properties))

    def _generic_doc(self, node: GraphNode) -> Document:
        prop_text = ' '.join(f"{k} {v}" for k, v in node.properties.items()
                             if isinstance(v, (str, int, float, bool)) and str(v))
        owner = ''
        if node.label == 'Activity':
            proc = self.graph.node(str(node.properties.get('processRef', '')))
            owner = proc.name if proc else ''
        elif node.label == 'Element':
            xsd = self.graph.node(str(node.properties.get('schemaRef', '')))
            owner = xsd.name if xsd else ''
        text = ' '.join([node.name, node.module, owner, prop_text])
        snippet_bits = {
            'Activity': f"{node.properties.get('category', '')} -> "
                        f"{node.properties.get('springEquivalent', '')} (in {owner})",
            'Element': f"{node.properties.get('xsdType', '')} -> "
                       f"{node.properties.get('javaType', '')} (in {owner})",
            'GlobalVariable': f"value: {str(node.properties.get('value', ''))[:60]}",
            'SharedResource': f"{node.properties.get('resourceType', '')} -> "
                              f"{node.properties.get('springEquivalent', '')}",
        }
        snippet = snippet_bits.get(node.label, node.label)
        return Document(f"doc_{node.node_id}", node.node_id, node.label, node.name,
                        node.module, node.file_path, text[:MAX_TEXT], snippet,
                        dict(node.properties))
