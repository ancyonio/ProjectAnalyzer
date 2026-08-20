"""The deterministic Oracle analyzer.

Walks a repository of Oracle source -- packages, standalone units, triggers,
views, DDL -- and produces a knowledge graph. Every node and edge comes from a
statement in a script or a row in a dictionary extract. Where a fact cannot be
established, it is recorded as an unresolved reference and counted against
coverage, never quietly dropped.

Pass order matters:

    1 scan            discover and read the source tree
    2 schema          tables, columns, views, sequences, triggers from DDL
    3 programs        packages, their halves, program units, embedded SQL
    4 dictionary      merge the authoritative extract over the DDL result
    5 cross-reference resolve calls, data access, view and trigger targets
    6 history         Git commits touching analysed files
    7 derive          metrics, rule findings, tests, business seed, coverage
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from analyzer_core.ids import (object_id, project_id, repository_id,
                               schema_id)
from analyzer_core.model import Graph, GraphNode, GraphRel
from analyzer_core.utils import sha1_16

from .analysis.semantics import load_business_map
from .constants import SCHEMA_VERSION
from .parsers import (CrossReferenceMixin, DictionaryMixin, GitMetadataMixin,
                      ProgramParserMixin, SchemaObjectParserMixin,
                      SourceScanMixin)

logger = logging.getLogger('oracle_analyzer')

MAX_CODE_TEXT = 8000


class OracleAnalyzer(
    SourceScanMixin,
    SchemaObjectParserMixin,
    ProgramParserMixin,
    DictionaryMixin,
    CrossReferenceMixin,
    GitMetadataMixin,
):
    """Parses an Oracle source repository into a `Graph`."""

    def __init__(self, source_root, output_dir,
                 default_owner: str = '', db_meta: Optional[Path] = None,
                 business_map: Optional[Path] = None):
        self.source_root = Path(source_root).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.source_root.exists():
            raise FileNotFoundError(f'Source directory not found: {self.source_root}')

        self.default_owner = (default_owner or 'UNKNOWN').upper()
        self.db_meta = Path(db_meta) if db_meta else None
        # Read at construction, not in the derive pass: a bad map should fail
        # before the expensive parse, not after it.
        self.business_map = load_business_map(
            Path(business_map) if business_map else None)

        # graph
        self.nodes: Dict[str, GraphNode] = {}
        self.rels: List[GraphRel] = []
        self._rel_keys: Set[Tuple[str, str, str]] = set()

        # scan results
        self.sources: List[Any] = []
        self.skipped_files: Dict[str, int] = {}
        self.file_counts: Counter = Counter()

        # handed from the schema pass to the program pass
        self.program_objects: List[Tuple[Any, Any]] = []

        # deferred work, resolved in the cross-reference pass
        self.deferred_access: List[Tuple[str, str, str, str, str]] = []
        self.deferred_calls: List[Tuple[str, str, str, str]] = []
        self.deferred_sequences: List[Tuple[str, str, str]] = []
        self.deferred_view_queries: List[Tuple[str, str, str]] = []
        self.deferred_triggers: List[Tuple[str, str, Any]] = []
        self.deferred_synonyms: List[Tuple[str, str]] = []
        self.deferred_indexes: List[Tuple[str, str]] = []
        self.deferred_constraints: List[Tuple[str, Any]] = []
        self.deferred_inline_fks: List[Tuple[str, str, str, str, Any]] = []
        # (statement, owner, column candidates, alias map, table keys)
        self.deferred_columns: List[Tuple[str, str, Tuple,
                                          Dict[str, str], Tuple]] = []
        self.deferred_joins: List[Tuple[str, str, str]] = []
        self.deferred_types: List[Tuple[str, str, str]] = []
        self.late_access: List[Tuple[str, str, str, str, str]] = []
        self.late_calls: List[Tuple[str, str, str, str]] = []

        # resolution state
        self.objects_by_name: Dict[str, List[str]] = {}
        self.units_by_name: Dict[str, List[str]] = {}
        self.synonym_targets: Dict[str, str] = {}
        self.unresolved: Dict[str, Set[str]] = {}
        self.unresolved_sources: Dict[str, Set[str]] = {}
        self.dynamic_sql_sites: List[Tuple[str, str]] = []
        self.dictionary_available = False
        self.dictionary_only: List[str] = []

        self.stats: Counter = Counter()
        self.repository_id = repository_id(self.source_root.name or 'oracle')
        self.project_id = project_id(self.source_root.name)

    # ── graph helpers ─────────────────────────────────────────────────
    def _add_node(self, node: GraphNode) -> GraphNode:
        if node.node_id not in self.nodes:
            self.nodes[node.node_id] = node
        return self.nodes[node.node_id]

    def _add_rel(self, start: str, end: str, rel_type: str, **properties) -> None:
        if not start or not end or start == end:
            return
        key = (start, end, rel_type)
        if key in self._rel_keys:
            return
        self._rel_keys.add(key)
        self.rels.append(GraphRel(start, end, rel_type,
                                  {k: v for k, v in properties.items()
                                   if v not in (None, '')}))

    def _set_property(self, node_id: str, key: str, value: Any) -> None:
        node = self.nodes.get(node_id)
        if node is not None and value is not None:
            node.properties[key] = value

    def _ensure_schema(self, owner: str) -> str:
        owner = (owner or self.default_owner).upper()
        node_id = schema_id(owner)
        if node_id not in self.nodes:
            self._add_node(GraphNode(node_id, 'DbSchema', owner, {
                'owner': owner,
                'isDefault': owner == self.default_owner,
            }))
            self._add_rel(self.project_id, node_id, 'OWNS',
                          purpose='project-schema')
        return node_id

    @staticmethod
    def _truncate(text: str, limit: int = MAX_CODE_TEXT) -> str:
        text = (text or '').strip()
        return text if len(text) <= limit else text[:limit] + '\n-- [truncated]'

    @staticmethod
    def _hash(text: str) -> str:
        return sha1_16(text or '')

    # ── the pipeline ──────────────────────────────────────────────────
    def analyze(self) -> Graph:
        self.project_id = project_id(self.source_root.name)
        self._add_node(GraphNode(self.project_id, 'Project',
                                 self.source_root.name, {
                                     'sourceRoot': str(self.source_root),
                                     'defaultOwner': self.default_owner,
                                 }))
        self._add_node(GraphNode(self.repository_id, 'Repository',
                                 self.source_root.name, {
                                     'path': str(self.source_root),
                                 }))
        self._add_rel(self.project_id, self.repository_id, 'OWNS',
                      purpose='project-repository')

        steps = [
            ('Scanning source tree', self._scan_sources),
            ('Parsing schema objects', self._parse_schema_objects),
            ('Parsing packages and program units', self._parse_programs),
            ('Merging dictionary extract', self._maybe_parse_dictionary),
            ('Cross-referencing', self._cross_reference),
            ('Reading Git history', self._parse_git),
            ('Deriving metrics and findings', self._derive),
        ]
        for index, (label, step) in enumerate(steps, 1):
            logger.info('-- Step %d/%d: %s --', index, len(steps), label)
            step()

        graph = Graph(self.nodes, self.rels, self._meta())
        logger.info('Graph built: %s nodes, %s relationships',
                    len(graph.nodes), len(graph.rels))
        return graph

    def _maybe_parse_dictionary(self) -> int:
        if not self.db_meta:
            logger.info('  no --db-meta supplied; repository-only analysis')
            return 0
        if not self.db_meta.exists():
            logger.warning('  dictionary extract not found at %s', self.db_meta)
            return 0
        return self._parse_dictionary(self.db_meta)

    # ── derived facts ─────────────────────────────────────────────────
    def _derive(self) -> int:
        from .analysis.metrics import attach_metrics
        from .analysis.rules_catalog import apply_rules
        from .analysis.semantics import seed_business_layer
        from .analysis.tests_catalog import attach_tests

        metrics = attach_metrics(self)
        # Tests before rules: a rule that scores coverage needs the test edges
        # to exist, and a rule that fires on an untested entry point cannot
        # tell "no tests" from "tests not read yet".
        tests = attach_tests(self)
        business = seed_business_layer(self, self.business_map)
        findings = apply_rules(self)
        self.stats['metrics'] = metrics
        self.stats['findings'] = findings
        self.stats['business_nodes'] = business
        logger.info('  %d metric node(s), %d test case(s), %d business node(s), '
                    '%d finding(s)', metrics, tests, business, findings)
        return findings

    # ── meta ──────────────────────────────────────────────────────────
    def _coverage(self) -> Dict[str, Any]:
        """The honesty contract: what the graph does and does not know."""
        objects = [n for n in self.nodes.values()
                   if n.label in ('DbTable', 'DbView', 'DbMaterializedView',
                                  'DbPackage', 'DbProgramUnit', 'DbTrigger',
                                  'DbSequence', 'DbSynonym', 'DbType')]
        discovered = len(objects) + len(self.unresolved)
        modelled = len(objects)
        resolved = self.stats.get('calls_resolved', 0)
        unresolved_calls = self.stats.get('calls_unresolved', 0)
        total_calls = resolved + unresolved_calls
        parse = self._parse_quality()

        return {
            'objectsDiscovered': discovered,
            'objectsModelled': modelled,
            'resolutionCoverage': round(modelled * 100.0 / discovered, 1)
            if discovered else 100.0,
            'callsResolved': resolved,
            'callsUnresolved': unresolved_calls,
            'callResolution': round(resolved * 100.0 / total_calls, 1)
            if total_calls else 100.0,
            'dynamicSqlSites': len(self.dynamic_sql_sites),
            'dictionaryAvailable': self.dictionary_available,
            'unresolvedReferences': sorted(self.unresolved)[:50],
            **parse,
        }

    def _parse_quality(self) -> Dict[str, Any]:
        """How much of the code the parser actually understood.

        Resolution coverage answers "did the names bind"; this answers the
        question underneath it, "was the code read correctly in the first
        place". A graph built from mostly `PARTIAL` statements resolves its
        handful of names perfectly and still describes very little, so the two
        figures have to be reported side by side.

        Counted over `SqlStatement` and `PlsqlBlock` only. A `DbProgramUnit`
        carries the status of its own block verbatim, so including units would
        count the same parse twice and flatter the percentage.
        """
        counts: Counter = Counter()
        for node in self.nodes.values():
            if node.label not in ('SqlStatement', 'PlsqlBlock'):
                continue
            counts[str(node.properties.get('parseStatus') or 'UNKNOWN')] += 1

        parsed = counts.get('PARSED', 0)
        partial = counts.get('PARTIAL', 0)
        failed = counts.get('FAILED', 0)
        total = sum(counts.values())
        return {
            'codeNodes': total,
            'statementsParsed': parsed,
            'statementsPartial': partial,
            'statementsFailed': failed,
            'parseQuality': round(parsed * 100.0 / total, 1) if total else 100.0,
            # DDL the splitter produced but no pattern claimed. Nothing is
            # created for these, so they are invisible in a node count.
            'ddlStatements': self.stats.get('ddl_statements', 0),
            'ddlUnparsed': self.stats.get('ddl_unparsed', 0),
        }

    def _meta(self) -> Dict[str, Any]:
        label_counts: Counter = Counter(n.label for n in self.nodes.values())
        return {
            'schemaVersion': SCHEMA_VERSION,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'sourceRoot': str(self.source_root),
            'defaultOwner': self.default_owner,
            'fileDiscovery': dict(self.file_counts.most_common()),
            'filesSkipped': dict(sorted(self.skipped_files.items())),
            'schemas': sorted(n.name for n in self.nodes.values()
                              if n.label == 'DbSchema'),
            'objectCounts': dict(label_counts.most_common()),
            'parserStats': dict(self.stats),
            'coverage': self._coverage(),
        }
