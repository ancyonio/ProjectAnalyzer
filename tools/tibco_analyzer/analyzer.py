"""The deterministic analyzer.

Walks a TIBCO BusinessWorks project tree and produces a knowledge graph.
Nothing here is heuristic-by-LLM: every node and edge comes from an XML
element that exists on disk. The LLM layer consumes this output; it never
replaces it.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .analysis.rules_catalog import apply_rules
from .constants import (ARTIFACT_FAMILIES, PARSED_ARTIFACT_EXTENSIONS,
                        SCHEMA_VERSION)
from .model import Graph, GraphNode, GraphRel
from .parsers import (
    BwpProcessParserMixin,
    CrossReferenceMixin,
    ProcessParserMixin,
    ResourceParserMixin,
    SchemaParserMixin,
    ServiceParserMixin,
    TransformParserMixin,
)

logger = logging.getLogger('tibco_analyzer')

SCAN_EXCLUDE_DIRS = {'.git', '.svn', 'node_modules', '__pycache__', '.metadata',
                     'target', 'build', '.settings'}


class TibcoAnalyzer(
    ProcessParserMixin,
    BwpProcessParserMixin,
    SchemaParserMixin,
    ServiceParserMixin,
    ResourceParserMixin,
    TransformParserMixin,
    CrossReferenceMixin,
):
    """Parses an entire TIBCO BW project tree into a `Graph`."""

    def __init__(self, tibco_root: str | Path, output_dir: str | Path):
        self.tibco_root = Path(tibco_root).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        if not self.tibco_root.exists():
            raise FileNotFoundError(f"TIBCO source directory not found: {self.tibco_root}")

        # Graph data
        self.nodes: Dict[str, GraphNode] = {}
        self.rels: List[GraphRel] = []

        # ID generators
        self._counters: Dict[str, int] = defaultdict(int)

        # Index maps for cross-referencing
        self._process_by_name: Dict[str, str] = {}
        self._process_by_path: Dict[str, str] = {}
        self._xsd_by_name: Dict[str, str] = {}
        self._xsd_by_path: Dict[str, str] = {}
        self._xsd_by_location: Dict[str, str] = {}
        self._wsdl_by_name: Dict[str, str] = {}
        self._wsdl_by_location: Dict[str, str] = {}
        self._activity_key_to_id: Dict[str, str] = {}
        self._resource_by_path: Dict[str, str] = {}
        self._module_ids: Dict[str, str] = {}
        self._system_ids: Dict[str, str] = {}
        self._gvar_ids: Dict[str, str] = {}
        self._external_ids: Dict[str, str] = {}

        # Deferred cross-references
        self._process_schema_refs: Dict[str, Set[str]] = defaultdict(set)
        self._process_wsdl_refs: Dict[str, Set[str]] = defaultdict(set)
        self._process_resource_refs: Dict[str, Set[str]] = defaultdict(set)

        # Statistics
        self.stats: Dict[str, Any] = defaultdict(int)
        self.file_counts: Counter = Counter()
        self.activity_type_counts: Counter = Counter()
        self.migration_complexity: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # ID / node helpers (used by every parser mixin)
    # ------------------------------------------------------------------
    def _next_id(self, prefix: str) -> str:
        self._counters[prefix] += 1
        return f"{prefix}_{self._counters[prefix]:04d}"

    def _add_node(self, node: GraphNode) -> str:
        self.nodes[node.node_id] = node
        return node.node_id

    def _add_rel(self, start: str, end: str, rtype: str, **props) -> None:
        clean = {k: v for k, v in props.items() if v not in (None, '')}
        self.rels.append(GraphRel(start, end, rtype, clean))

    def _module_of(self, file_path: Path) -> str:
        try:
            rel = file_path.relative_to(self.tibco_root)
            return rel.parts[0] if len(rel.parts) > 1 else 'root'
        except ValueError:
            return 'unknown'

    def _ensure_module(self, name: str) -> str:
        if name in self._module_ids:
            return self._module_ids[name]
        nid = self._next_id('mod')
        self._add_node(GraphNode(nid, 'Module', name, {
            'type': 'TIBCO_MODULE',
            'description': f'TIBCO BW module: {name}',
        }))
        self._module_ids[name] = nid
        return nid

    def _ensure_system(self, tech: str) -> str:
        key = f"{tech}_System"
        if key in self._system_ids:
            return self._system_ids[key]
        nid = self._next_id('sys')
        self._add_node(GraphNode(nid, 'System', key, {
            'technology': tech,
            'type': 'EXTERNAL_SYSTEM',
            'description': f'External {tech} system',
        }))
        self._system_ids[key] = nid
        return nid

    def _ensure_external_reference(self, name: str, target_path: str) -> str:
        """Node for a referenced artefact that is not present in the source tree."""
        key = name or target_path
        if key in self._external_ids:
            return self._external_ids[key]
        nid = self._next_id('ext')
        self._add_node(GraphNode(nid, 'ExternalReference', key, {
            'type': 'UNRESOLVED_PROCESS',
            'targetPath': target_path,
            'note': 'Referenced by a process but not found in the scanned source tree',
        }))
        self._external_ids[key] = nid
        return nid

    def _add_node_prop(self, node_id: str, key: str, value: Any) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].properties[key] = value

    # ------------------------------------------------------------------
    def _scan_files(self) -> None:
        for path in self.tibco_root.rglob('*'):
            if not path.is_file():
                continue
            if any(part in SCAN_EXCLUDE_DIRS for part in path.parts):
                continue
            self.file_counts[path.suffix.lower()] += 1

    # ------------------------------------------------------------------
    def analyze(self) -> Graph:
        """Run the full deterministic parse and return the knowledge graph."""
        logger.info("TIBCO source : %s", self.tibco_root)
        logger.info("Output dir   : %s", self.output_dir)

        logger.info("Scanning file system...")
        self._scan_files()
        total_files = sum(self.file_counts.values())
        logger.info("Found %s files across %s extensions", total_files, len(self.file_counts))

        steps = [
            ("Parsing .process files (BW5)", self._parse_processes),
            ("Parsing .bwp files (BW6/BWCE)", self._parse_bwp_processes),
            ("Parsing .xsd files", self._parse_xsds),
            ("Parsing .wsdl files", self._parse_wsdls),
            ("Parsing shared resources", self._parse_shared_resources),
            ("Parsing global variables", self._parse_global_variables),
            ("Parsing AE schemas", self._parse_aeschemas),
            ("Parsing XSLT transformations", self._parse_xslts),
            ("Building cross-references", self._build_cross_references),
        ]
        for idx, (label, fn) in enumerate(steps, 1):
            logger.info("-- Step %d/%d: %s --", idx, len(steps), label)
            fn()

        # Rules run last: every one of them reads the finished graph, so a rule
        # can never see a half-built estate and report a gap the parser was
        # about to fill.
        issue_count = apply_rules(self)
        logger.info("-- Rules: %d finding(s) --", issue_count)

        meta = {
            'schemaVersion': SCHEMA_VERSION,
            'issueCount': issue_count,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'tibcoRoot': str(self.tibco_root),
            'fileDiscovery': dict(self.file_counts.most_common()),
            'artifactFamilies': self._artifact_families(),
            'activityCategoryCounts': dict(self.activity_type_counts.most_common()),
            'parserStats': dict(self.stats),
            'modules': sorted(self._module_ids),
            'coverage': self._coverage(),
        }
        graph = Graph(self.nodes, self.rels, meta)
        logger.info("Graph built: %s nodes, %s relationships",
                    len(graph.nodes), len(graph.rels))
        return graph

    def _coverage(self) -> Dict[str, Any]:
        """How much of the discovered tree actually reached the graph.

        A small graph can mean a small estate or a partly-parsed one, and an
        analyst cannot tell the two apart from node counts. `artifactCoverage`
        measures supported parser inputs; `estateFileCoverage` measures all
        discovered files, including intentionally unmodelled source/config.
        """
        discovered = sum(self.file_counts.values())
        modelled_paths = {n.properties.get('filePath')
                          for n in self.nodes.values()
                          if n.properties.get('filePath')}
        modelled = len(modelled_paths)

        supported_counts = {
            ext: count for ext, count in self.file_counts.items()
            if ext in PARSED_ARTIFACT_EXTENSIONS
            or ext.endswith(('resource', 'globalinstance'))
        }
        supported = sum(supported_counts.values())

        # `file_counts` keys come from discovery, which lower-cases the
        # extension; node paths keep TIBCO's original spelling
        # (`.jdbcResource`). Compare on a lower-cased key or every BW6 resource
        # looks unmodelled.
        modelled_exts: Counter = Counter()
        for path in modelled_paths:
            suffix = Path(path).suffix.lower()
            if suffix:
                modelled_exts[suffix] += 1
        unmodelled = {ext: count - modelled_exts.get(ext.lower(), 0)
                      for ext, count in self.file_counts.items()
                      if count - modelled_exts.get(ext.lower(), 0) > 0}
        supported_unmodelled = {
            ext: count - modelled_exts.get(ext, 0)
            for ext, count in supported_counts.items()
            if count - modelled_exts.get(ext, 0) > 0
        }
        supported_modelled = supported - sum(supported_unmodelled.values())

        return {
            'filesDiscovered': discovered,
            'filesModelled': modelled,
            'filesSupported': supported,
            'filesSupportedModelled': supported_modelled,
            'artifactCoverage': round(supported_modelled * 100.0 / supported, 1)
                                if supported else 100.0,
            'estateFileCoverage': round(modelled * 100.0 / discovered, 1)
                                  if discovered else 100.0,
            'filesClassified': sum(self._artifact_families().values()),
            'unmodelledExtensions': dict(Counter(unmodelled).most_common(15)),
            'unmodelledSupportedExtensions': dict(
                Counter(supported_unmodelled).most_common(15)),
        }

    def _artifact_families(self) -> Dict[str, int]:
        fams: Counter = Counter()
        families = {ext.lower(): family
                for ext, family in ARTIFACT_FAMILIES.items()}
        for ext, count in self.file_counts.items():
            fam = families.get(ext.lower())
            if fam:
                fams[fam] += count
        return dict(fams.most_common())
