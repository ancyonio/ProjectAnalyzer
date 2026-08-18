"""The deterministic APEX analyzer.

Walks an APEX export (and any DDL or dictionary extract beside it) and
produces a knowledge graph. Nothing here is heuristic-by-LLM: every node and
edge comes from a call in an export file, a row in a dictionary extract, or a
statement in a DDL script. Where a fact cannot be established — a table that
is not in the extract, SQL assembled at runtime — that is recorded as an
unresolved reference with a confidence, never quietly dropped.

Pass order matters:

    1 discover files            what kind of export is this
    2 parse the export          components, containment, code nodes
    3 parse the database        dictionary extract, then DDL scripts
    4 cross-reference and bind  deferred links, then SQL -> database edges
    5 derive                    complexity, metrics, business seeds, rules
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from analyzer_core.ids import (app_id, db_ident, js_id, plsql_id,
                               project_id, sql_id)
from analyzer_core.model import Graph, GraphNode, GraphRel
from analyzer_core.utils import read_text, sha1_16, truncate

from .constants import (DB_OBJECT_LABELS, EXTRACTED_RELS, IGNORED_PROCEDURES,
                        PLSQL_CONDITION_TYPES, SCHEMA_VERSION,
                        SQL_CONDITION_TYPES)
from .parsers import (ApplicationParserMixin, ButtonParserMixin,
                      CrossReferenceMixin, DatabaseMetadataMixin,
                      DynamicActionParserMixin, GitMetadataMixin,
                      ItemParserMixin, PageParserMixin, ProcessParserMixin,
                      RegionParserMixin, SharedComponentParserMixin)
from .parsers.export_scan import KIND_APEX_APP, discover
from .parsers.plsql_args import ExportCall, iter_calls
from .parsers.plsql import analyse_plsql, normalise_plsql
from .parsers.resolver import Resolver
from .parsers.sqlparse import analyse_sql, normalise_sql

logger = logging.getLogger('apex_analyzer')

MAX_CODE_TEXT = 8000


class ApexAnalyzer(
    ApplicationParserMixin,
    PageParserMixin,
    RegionParserMixin,
    ItemParserMixin,
    ButtonParserMixin,
    ProcessParserMixin,
    DynamicActionParserMixin,
    SharedComponentParserMixin,
    DatabaseMetadataMixin,
    CrossReferenceMixin,
    GitMetadataMixin,
):
    """Parses an APEX export tree into a `Graph`."""

    def __init__(self, source: str | Path, output_dir: str | Path,
                 application_id: Optional[int] = None,
                 parsing_schema: str = '',
                 db_meta: Optional[str | Path] = None,
                 apex_meta: Optional[str | Path] = None,
                 git_range: str = '', git_enabled: bool = False):
        self.source_root = Path(source).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_meta_path = Path(db_meta).resolve() if db_meta else None
        self.apex_meta_path = Path(apex_meta).resolve() if apex_meta else None
        self.git_range = git_range
        self.git_enabled = git_enabled or bool(git_range)

        # graph state
        self.nodes: Dict[str, GraphNode] = {}
        self.rels: List[GraphRel] = []
        self._rel_keys: Set[Tuple[str, str, str]] = set()

        # parse state
        self.app_id: Optional[int] = application_id
        self.page_id: Optional[int] = None
        self.parsing_schema = (parsing_schema or '').upper()
        self.application_node: Optional[str] = None
        self.current_file = None
        self.current_region_id: Optional[int] = None
        self.current_list_id: Optional[int] = None
        self.current_web_source_id: Optional[int] = None

        self.registry: Dict[str, Dict[Any, str]] = defaultdict(dict)
        self.deferred: List[Dict[str, Any]] = []
        self.pending_findings: List[Dict[str, str]] = []
        self.sql_analyses: Dict[str, Any] = {}
        self.plsql_analyses: Dict[str, Any] = {}
        self.node_page: Dict[str, Optional[int]] = {}
        self.dictionary_dependencies: Set[Tuple[str, str]] = set()

        self.resolver = Resolver(self.parsing_schema)
        self.stats: Counter = Counter()
        self.unhandled_calls: Counter = Counter()
        self.export_meta: Dict[str, Any] = {}
        self.inventory = None
        self.dataset_id = ''

        self._handlers = self._build_dispatch()

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------
    def _build_dispatch(self) -> Dict[str, Any]:
        handlers: Dict[str, Any] = {}
        for attribute in dir(self):
            if attribute.startswith('handle_'):
                handlers[attribute[len('handle_'):]] = getattr(self, attribute)
        return handlers

    # ------------------------------------------------------------------
    # graph helpers used by every mixin
    # ------------------------------------------------------------------
    def _node(self, node_id: str, label: str, name: str,
              props: Optional[Dict[str, Any]] = None,
              call: Optional[ExportCall] = None,
              extra_labels: Optional[List[str]] = None) -> str:
        payload: Dict[str, Any] = {}
        for key, value in (props or {}).items():
            if value is None or value == '':
                continue
            payload[key] = value
        payload.setdefault('origin', 'export' if call else 'derived')
        if self.dataset_id:
            payload.setdefault('datasetId', self.dataset_id)
        if self.app_id is not None and label.startswith('Apex'):
            payload.setdefault('applicationId', self.app_id)
        if call is not None:
            payload.setdefault('sourceFile', call.source_file)
            payload.setdefault('sourceLine', call.line)
        elif self.current_file is not None and label.startswith(('Apex', 'Db')):
            payload.setdefault('sourceFile', self.current_file.relative)
        if extra_labels:
            payload['extraLabels'] = ';'.join(extra_labels)
        payload.setdefault('schemaVersion', SCHEMA_VERSION)

        existing = self.nodes.get(node_id)
        if existing is not None:
            for key, value in payload.items():
                existing.properties.setdefault(key, value)
            if name and not existing.name:
                existing.name = name
            return node_id

        self.nodes[node_id] = GraphNode(node_id, label, name or node_id, payload)
        self.stats[f'node:{label}'] += 1
        page = payload.get('pageId', self.page_id)
        self.node_page[node_id] = page if isinstance(page, int) else self.page_id
        if label.startswith('Apex') and label != 'ApexApplication' and \
                self.app_id is not None:
            self._rel(node_id, app_id(self.app_id), 'BELONGS_TO')
        if self.current_file is not None and label.startswith('Apex'):
            self._rel(self.current_file.node_id, node_id, 'DEFINES')
        return node_id

    def _set_property(self, node_id: str, key: str, value: Any) -> None:
        node = self.nodes.get(node_id)
        if node is not None and value not in (None, ''):
            node.properties[key] = value

    def _increment_property(self, node_id: str, key: str, delta: int = 1) -> None:
        node = self.nodes.get(node_id)
        if node is not None:
            node.properties[key] = int(node.properties.get(key, 0) or 0) + delta

    def _rel(self, start: str, end: str, rel_type: str, **props: Any) -> None:
        if not start or not end or start == end:
            return
        key = (start, end, rel_type)
        if key in self._rel_keys:
            return
        clean = {k: v for k, v in props.items() if v not in (None, '')}
        if rel_type not in EXTRACTED_RELS and 'origin' not in clean:
            clean['origin'] = 'inferred'
            clean.setdefault('confidence', 1.0)
        self._rel_keys.add(key)
        self.rels.append(GraphRel(start, end, rel_type, clean))
        self.stats[f'rel:{rel_type}'] += 1

    def _register(self, kind: str, key: Any, node_id: str) -> None:
        if key is None:
            return
        self.registry[kind][key] = node_id

    def _lookup(self, kind: str, key: Any) -> Optional[str]:
        if key is None:
            return None
        return self.registry.get(kind, {}).get(key)

    def _defer(self, kind: str, **payload: Any) -> None:
        payload['kind'] = kind
        self.deferred.append(payload)

    def _defer_finding(self, rule_id: str, node_id: str, message: str) -> None:
        self.pending_findings.append({'ruleId': rule_id, 'nodeId': node_id,
                                      'message': message})

    def _ensure_application(self) -> str:
        node_id = app_id(self.app_id)
        if node_id not in self.nodes:
            self._node(node_id, 'ApexApplication', f'Application {self.app_id}',
                       {'applicationId': self.app_id,
                        'parsingSchema': self.parsing_schema,
                        'origin': 'derived'})
            self.application_node = node_id
        return node_id

    # ------------------------------------------------------------------
    # code nodes
    # ------------------------------------------------------------------
    def _sql_code(self, owner_id: str, text: str, rel_type: str = 'EXECUTES_SQL',
                  purpose: str = '') -> Optional[str]:
        if not text or not text.strip():
            return None
        analysis = analyse_sql(text)
        node_id = sql_id(normalise_sql(text))
        properties = analysis.properties()
        properties['sqlHash'] = node_id.split(':', 1)[1]
        properties['text'] = truncate(text.strip(), MAX_CODE_TEXT)
        self._node(node_id, 'SqlStatement',
                   f"{analysis.verb or 'SQL'} {sha1_16(node_id)[:8]}", properties)
        self.sql_analyses.setdefault(node_id, analysis)
        self.node_page.setdefault(node_id, self.page_id)
        self._rel(owner_id, node_id, rel_type, purpose=purpose)
        self.stats['sqlStatements'] += 1
        return node_id

    def _plsql_code(self, owner_id: str, text: str, rel_type: str = 'EXECUTES_PLSQL',
                    purpose: str = '') -> Optional[str]:
        if not text or not text.strip():
            return None
        analysis = analyse_plsql(text)
        node_id = plsql_id(normalise_plsql(text))
        properties = analysis.properties()
        properties['codeHash'] = node_id.split(':', 1)[1]
        properties['text'] = truncate(text.strip(), MAX_CODE_TEXT)
        if analysis.dynamic_sql_concatenates_input:
            properties['dynamicSqlConcatenatesInput'] = True
        if analysis.deprecated_calls:
            properties['deprecatedCalls'] = ', '.join(sorted(set(analysis.deprecated_calls)))
        self._node(node_id, 'PlsqlBlock', f'PL/SQL {sha1_16(node_id)[:8]}', properties)
        self.plsql_analyses.setdefault(node_id, analysis)
        self.node_page.setdefault(node_id, self.page_id)
        self._rel(owner_id, node_id, rel_type, purpose=purpose)
        self.stats['plsqlBlocks'] += 1
        return node_id

    def _js_code(self, owner_id: str, text: str) -> Optional[str]:
        if not text or not text.strip():
            return None
        node_id = js_id(text.strip())
        self._node(node_id, 'JsSnippet', f'JS {sha1_16(node_id)[:8]}', {
            'codeHash': node_id.split(':', 1)[1],
            'lineCount': text.count('\n') + 1,
            'usesApexServerProcess': 'apex.server.process' in text,
            'text': truncate(text.strip(), MAX_CODE_TEXT),
        })
        self._rel(owner_id, node_id, 'EXECUTES_JS')
        self.stats['jsSnippets'] += 1
        return node_id

    def _condition_code(self, owner_id: str, condition_type: str, expression: str,
                        purpose: str) -> None:
        if not expression or not expression.strip():
            return
        kind = (condition_type or '').upper()
        if kind in SQL_CONDITION_TYPES or expression.lstrip().lower().startswith(
                ('select', 'with ')):
            self._sql_code(owner_id, expression, 'EXECUTES_SQL', purpose)
        elif kind in PLSQL_CONDITION_TYPES:
            self._plsql_code(owner_id, expression, 'EXECUTES_PLSQL', purpose)

    # ------------------------------------------------------------------
    # passes
    # ------------------------------------------------------------------
    def analyze(self) -> Graph:
        logger.info("APEX source : %s", self.source_root)
        logger.info("Output dir  : %s", self.output_dir)

        logger.info("-- Step 1/6: discovering export files --")
        self.inventory = discover(self.source_root)
        if self.app_id is None and self.inventory.application_ids:
            self.app_id = self.inventory.application_ids[0]
        self.dataset_id = self._dataset_id()
        logger.info("Mode %s, %s file(s): %s", self.inventory.mode,
                    len(self.inventory.files), self.inventory.counts)
        if self.inventory.mode == 'readable' and not self.inventory.apex_files:
            raise ValueError(
                'This export is a readable (YAML) export only. The readable format '
                'is not parsed yet — re-export with `apex export -applicationid '
                f'{self.app_id or "<id>"} -split`, or point --source at the SQL export.')
        self._register_files()

        logger.info("-- Step 2/6: parsing the application export --")
        self._parse_export_files()

        logger.info("-- Step 3/6: parsing database metadata --")
        # the parsing schema is only known once `component_begin` / `create_flow`
        # has been read, and it is what makes an unqualified name resolve to
        # `schema_default` (0.95) rather than fall through to `heuristic` (0.70)
        self.resolver.parsing_schema = db_ident(self.parsing_schema)
        self._parse_database_metadata()

        logger.info("-- Step 4/6: cross-referencing and binding code --")
        self._build_cross_references()
        if self.git_enabled:
            logger.info("Recording the repository and change layer ...")
            self._parse_git_metadata()

        logger.info("-- Step 5/6: deriving metrics --")
        graph = Graph(self.nodes, self.rels, self._meta())
        from .analysis.complexity import annotate_complexity
        from .analysis.rules_catalog import run_rules
        from .analysis.semantics import seed_business_layer
        annotate_complexity(graph, self.app_id)
        seed_business_layer(graph, self.app_id, self.dataset_id)

        logger.info("-- Step 6/6: running the rule catalogue --")
        issues = run_rules(graph, self.resolver, self.pending_findings, self.dataset_id)
        graph.meta['issueCount'] = issues
        graph.reindex()
        graph.meta.update(self._coverage_meta(graph))
        logger.info("Graph built: %s nodes, %s relationships",
                    len(graph.nodes), len(graph.rels))
        return graph

    # ------------------------------------------------------------------
    def _dataset_id(self) -> str:
        digest = sha1_16(''.join(sorted(f.sha1 for f in (self.inventory.files if
                                                         self.inventory else []))))
        return f'app{self.app_id}@{digest[:12]}' if self.app_id is not None \
            else f'apex@{digest[:12]}'

    def _register_files(self) -> None:
        project_node = project_id(self.source_root.name)
        self._node(project_node, 'Project', self.source_root.name,
                   {'rootPath': str(self.source_root)})
        for export_file in self.inventory.files:
            self._node(export_file.node_id, 'File', export_file.path.name, {
                'path': export_file.relative,
                'ext': export_file.path.suffix.lower(),
                'kind': export_file.kind,
                'bytes': export_file.size,
                'sha1': export_file.sha1,
            })
            self._rel(project_node, export_file.node_id, 'CONTAINS_FILE')

    def _parse_export_files(self) -> None:
        files = self.inventory.apex_files
        # application-level files first, so pages attach to a real application
        files.sort(key=lambda f: (f.kind != KIND_APEX_APP, f.relative))
        for export_file in files:
            self.current_file = export_file
            self.page_id = export_file.page_id if export_file.page_id is not None \
                else None
            text = read_text(export_file.path)
            calls = 0
            for call in iter_calls(text, export_file.relative):
                calls += 1
                handler = self._handlers.get(call.procedure)
                if handler is not None:
                    try:
                        handler(call)
                    except Exception as exc:                  # one bad call must not
                        self.stats['handlerErrors'] += 1      # lose the whole file
                        logger.warning("%s:%s %s failed: %s", export_file.relative,
                                       call.line, call.procedure, exc)
                elif call.procedure not in IGNORED_PROCEDURES:
                    self.unhandled_calls[f'{call.package}.{call.procedure}'] += 1
            self.stats['exportCalls'] += calls
        self.current_file = None
        self.page_id = None
        if self.app_id is not None:
            self._ensure_application()

    # ------------------------------------------------------------------
    def _meta(self) -> Dict[str, Any]:
        return {
            'schemaVersion': SCHEMA_VERSION,
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'apexSource': str(self.source_root),
            'applicationId': self.app_id,
            'parsingSchema': self.parsing_schema,
            'datasetId': self.dataset_id,
            'ingestion': {
                'mode': self.inventory.mode if self.inventory else 'unknown',
                'fileCounts': self.inventory.counts if self.inventory else {},
                'dictionaryExtract': str(self.db_meta_path) if self.db_meta_path else '',
                'apexMetadataExtract': str(self.apex_meta_path)
                                       if self.apex_meta_path else '',
                'readableFilesSeen': self.inventory.readable_files if self.inventory else 0,
            },
            'exportApiFamily': sorted({p.split('.')[0]
                                       for p in self.unhandled_calls} | {'wwv_flow_imp'}),
            'parserStats': dict(sorted(self.stats.items())),
            'unhandledProcedures': dict(self.unhandled_calls.most_common(25)),
            **{k: v for k, v in self.export_meta.items()},
        }

    def _coverage_meta(self, graph: Graph) -> Dict[str, Any]:
        coverage = self.resolver.coverage()
        code_nodes = [n for n in graph.nodes.values()
                      if n.label in ('SqlStatement', 'PlsqlBlock')]
        failed = sum(1 for n in code_nodes if n.properties.get('parseStatus') == 'FAILED')
        partial = sum(1 for n in code_nodes if n.properties.get('parseStatus') == 'PARTIAL')
        coverage.update({
            'codeNodes': len(code_nodes),
            'parseFailed': failed,
            'parsePartial': partial,
            'parseFailureRate': round(failed / len(code_nodes), 4) if code_nodes else 0.0,
            'dictionaryAvailable': self.resolver.has_dictionary,
        })
        return {'coverage': coverage}
