"""Cross-referencing and code binding.

Component parsing is a single forward pass, so anything that points at a
component defined later (a process fired by a button, an item using a shared
LOV, a branch targeting a page) is deferred and resolved here.

This module also runs the binder: every `:SqlStatement` and `:PlsqlBlock`
collected during parsing is walked against the resolver, producing the
`READS_FROM` / `WRITES_TO` / `CALLS` / `REFERENCES_COLUMN` / `BINDS_ITEM`
edges that make the graph worth querying. Each of those edges carries the
resolution and confidence the resolver reported — never a bare assertion.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from analyzer_core.ids import column_id, db_ident, object_id, page_id, unresolved_id
from analyzer_core.utils import one_line

from ..constants import DB_OBJECT_LABELS
from .sqlparse import DELETE, INSERT, READ, UPDATE, analyse_sql

logger = logging.getLogger('apex_analyzer')

ACCESS_RELS = {
    READ: ['READS_FROM'],
    INSERT: ['INSERTS_INTO', 'WRITES_TO'],
    UPDATE: ['UPDATES', 'WRITES_TO'],
    DELETE: ['DELETES_FROM', 'WRITES_TO'],
}


class CrossReferenceMixin:
    """Second pass: resolve deferred references, then bind code to the database."""

    # ------------------------------------------------------------------
    def _build_cross_references(self) -> None:
        handlers = {
            'securedBy': self._xref_secured_by,
            'buildOption': self._xref_build_option,
            'usesLov': self._xref_uses_lov,
            'navigatesTo': self._xref_navigates_to,
            'triggeredByButton': self._xref_triggered_by_button,
            'validatesItemId': self._xref_validates_item_id,
            'validatesItem': self._xref_validates_item,
            'setsItem': self._xref_sets_item,
            'daSubmitsItem': self._xref_da_submits_item,
            'daTriggerItem': self._xref_da_trigger_item,
            'daTriggerButton': self._xref_da_trigger_button,
            'daTriggerRegion': self._xref_da_trigger_region,
            'subRegion': self._xref_sub_region,
            'sourcedFrom': self._xref_sourced_from,
            'itemColumn': self._xref_item_column,
            'columnSource': self._xref_column_source,
            'processDml': self._xref_process_dml,
            'processDmlRegion': self._xref_process_dml_region,
            'viewQuery': self._xref_view_query,
            'synonymTarget': self._xref_synonym_target,
            'triggerTable': self._xref_trigger_table,
            'constraintReference': self._xref_constraint_reference,
            'dictionaryDependency': self._xref_dictionary_dependency,
            'unitSource': self._xref_unit_source,
        }
        for deferred in self.deferred:
            handler = handlers.get(deferred['kind'])
            if handler:
                handler(deferred)
        self._bind_code()

    # ── APEX cross-references ─────────────────────────────────────────
    def _xref_secured_by(self, ref: Dict[str, Any]) -> None:
        scheme = (ref.get('scheme') or '').strip()
        if not scheme:
            return
        target = self._lookup('authorization', scheme) or \
            self._lookup('authorizationId', _as_int(scheme))
        if target:
            self._rel(ref['node_id'], target, 'SECURED_BY')
            # the export stores the scheme as a component id; show the name
            scheme_node = self.nodes.get(target)
            if scheme_node is not None:
                self._set_property(ref['node_id'], 'authorizationScheme',
                                   scheme_node.name)
        else:
            self.stats['unresolvedAuthorizationSchemes'] += 1

    def _xref_build_option(self, ref: Dict[str, Any]) -> None:
        option = (ref.get('build_option') or '').strip()
        if not option:
            return
        target = self._lookup('buildOption', option) or \
            self._lookup('buildOptionId', _as_int(option))
        if target:
            self._rel(ref['node_id'], target, 'CONDITIONED_BY')

    def _xref_uses_lov(self, ref: Dict[str, Any]) -> None:
        lov = (ref.get('lov') or '').strip()
        if not lov:
            return
        target = self._lookup('lov', lov.upper()) or self._lookup('lovId', _as_int(lov))
        if target:
            self._rel(ref['node_id'], target, 'USES_LOV')

    def _xref_navigates_to(self, ref: Dict[str, Any]) -> None:
        target = self._lookup('page', ref.get('page'))
        if target:
            self._rel(ref['node_id'], target, 'NAVIGATES_TO', via=ref.get('via', ''))
        else:
            self.stats['navigationToMissingPage'] += 1
            self._defer_finding('CORR-005', ref['node_id'],
                                f"targets page {ref.get('page')}, which does not exist")

    def _xref_triggered_by_button(self, ref: Dict[str, Any]) -> None:
        button = self._lookup('button', (ref['page'], ref['button']))
        if button:
            self._rel(button, ref['node_id'], 'TRIGGERS',
                      origin='inferred', confidence=0.95,
                      resolution='exact', evidenceSnippet='p_process_when_button_id')

    def _xref_validates_item_id(self, ref: Dict[str, Any]) -> None:
        item = self._lookup('itemId', ref.get('item_id'))
        if item:
            self._rel(ref['node_id'], item, 'VALIDATES')

    def _xref_validates_item(self, ref: Dict[str, Any]) -> None:
        item = self._lookup('item', (ref['page'], ref['item']))
        if item:
            self._rel(ref['node_id'], item, 'VALIDATES')

    def _xref_sets_item(self, ref: Dict[str, Any]) -> None:
        item = self._resolve_item(ref.get('page'), ref.get('item'))
        if item:
            self._rel(ref['node_id'], item, 'SETS_ITEM',
                      origin='inferred', confidence=0.9, resolution='exact')

    def _xref_da_submits_item(self, ref: Dict[str, Any]) -> None:
        item = self._resolve_item(ref.get('page'), ref.get('item'))
        if item:
            self._rel(ref['node_id'], item, 'BINDS_ITEM',
                      origin='inferred', confidence=0.9, resolution='exact',
                      evidenceSnippet='items to submit')

    def _xref_da_trigger_item(self, ref: Dict[str, Any]) -> None:
        item = self._resolve_item(ref.get('page'), ref.get('item'))
        if item:
            self._rel(ref['node_id'], item, 'BINDS_ITEM',
                      origin='inferred', confidence=0.85, resolution='exact',
                      evidenceSnippet='triggering element')

    def _xref_da_trigger_button(self, ref: Dict[str, Any]) -> None:
        button = self._lookup('button', (ref['page'], ref['button']))
        if button:
            self._rel(button, ref['node_id'], 'TRIGGERS',
                      origin='inferred', confidence=0.95, resolution='exact',
                      evidenceSnippet='dynamic action triggering button')

    def _xref_da_trigger_region(self, ref: Dict[str, Any]) -> None:
        region = self._lookup('region', (ref['page'], ref['region']))
        if region:
            self._rel(region, ref['node_id'], 'CONTAINS_DYNAMIC_ACTION')

    def _xref_sub_region(self, ref: Dict[str, Any]) -> None:
        parent = self._lookup('region', (ref['page'], ref['parent']))
        if parent:
            self._rel(parent, ref['node_id'], 'CONTAINS_SUBREGION')

    # ── declarative data sources ──────────────────────────────────────
    def _xref_sourced_from(self, ref: Dict[str, Any]) -> None:
        resolution = self.resolver.resolve_object(ref.get('owner', ''), ref['table'])
        target = self._ensure_db_node(resolution)
        self._rel(ref['node_id'], target, 'SOURCED_FROM',
                  origin='inferred', confidence=resolution.confidence,
                  resolution=resolution.resolution,
                  evidenceSnippet=f"query table {ref['table']}")

    def _xref_item_column(self, ref: Dict[str, Any]) -> None:
        """An item sourced from a database column, via its region's table."""
        table = self._region_table(ref.get('page'), ref.get('region'))
        if not table:
            return
        owner, table_name = table
        column_node = self.resolver.resolve_column(owner, table_name, ref['column'])
        if column_node and column_node in self.nodes:
            self._rel(ref['node_id'], column_node, 'REFERENCES_COLUMN',
                      origin='inferred', confidence=0.95, resolution='exact',
                      evidenceSnippet=f"item source {ref['column']}")
        else:
            self.stats['itemColumnUnresolved'] += 1
            if self.resolver.columns_of(owner, table_name):
                self._defer_finding(
                    'CORR-002', ref['node_id'],
                    f"is sourced from {table_name}.{ref['column']}, which is not a "
                    f'column of that table')

    def _xref_column_source(self, ref: Dict[str, Any]) -> None:
        table = self._region_table(ref.get('page'), ref.get('region'))
        if not table:
            return
        owner, table_name = table
        column_node = self.resolver.resolve_column(owner, table_name, ref['column'])
        if column_node and column_node in self.nodes:
            self._rel(ref['node_id'], column_node, 'REFERENCES_COLUMN',
                      origin='inferred', confidence=0.9, resolution='exact',
                      evidenceSnippet='report column source')

    def _xref_process_dml(self, ref: Dict[str, Any]) -> None:
        resolution = self.resolver.resolve_object(ref.get('owner', ''), ref['table'])
        target = self._ensure_db_node(resolution)
        for rel_type in ('WRITES_TO', 'INSERTS_INTO', 'UPDATES'):
            self._rel(ref['node_id'], target, rel_type,
                      origin='inferred', confidence=min(resolution.confidence, 0.8),
                      resolution=resolution.resolution,
                      evidenceSnippet=f"declarative DML ({ref.get('process_type', '')})")

    def _xref_process_dml_region(self, ref: Dict[str, Any]) -> None:
        table = self._region_table(ref.get('page'), ref.get('region'))
        if not table:
            return
        owner, table_name = table
        resolution = self.resolver.resolve_object(owner, table_name)
        target = self._ensure_db_node(resolution)
        for rel_type in ('WRITES_TO', 'INSERTS_INTO', 'UPDATES'):
            self._rel(ref['node_id'], target, rel_type,
                      origin='inferred', confidence=min(resolution.confidence, 0.75),
                      resolution=resolution.resolution,
                      evidenceSnippet='declarative DML on the region source table')

    # ── database cross-references ─────────────────────────────────────
    def _xref_view_query(self, ref: Dict[str, Any]) -> None:
        view_node = object_id(ref['owner'], ref['name'])
        if view_node not in self.nodes:
            return
        analysis = analyse_sql(ref['query'])
        for table in analysis.tables:
            resolution = self.resolver.resolve_object(table.owner, table.name)
            if resolution.name == db_ident(ref['name']) and resolution.owner == \
                    db_ident(ref['owner']):
                continue
            target = self._ensure_db_node(resolution)
            self._rel(view_node, target, 'DEPENDS_ON',
                      origin='inferred', confidence=resolution.confidence,
                      resolution=resolution.resolution,
                      evidenceSnippet='view query')
            self._rel(view_node, target, 'READS_FROM',
                      origin='inferred', confidence=resolution.confidence,
                      resolution=resolution.resolution)

    def _xref_synonym_target(self, ref: Dict[str, Any]) -> None:
        resolution = self.resolver.resolve_object(ref['owner'], ref['name'])
        if resolution.resolved:
            self._rel(ref['node_id'], self._ensure_db_node(resolution), 'RESOLVES_TO')

    def _xref_trigger_table(self, ref: Dict[str, Any]) -> None:
        resolution = self.resolver.resolve_object(ref.get('owner', ''), ref['table'])
        self._rel(ref['node_id'], self._ensure_db_node(resolution), 'FIRES_ON',
                  origin='inferred', confidence=resolution.confidence,
                  resolution=resolution.resolution)

    def _xref_constraint_reference(self, ref: Dict[str, Any]) -> None:
        resolution = self.resolver.resolve_object(ref.get('owner', ''), ref['table'])
        if resolution.resolved:
            self._rel(ref['node_id'], self._ensure_db_node(resolution), 'REFERENCES_TABLE')

    def _xref_dictionary_dependency(self, ref: Dict[str, Any]) -> None:
        row = ref['row']
        source = object_id(db_ident(row.get('owner')), db_ident(row.get('name')))
        target_owner = db_ident(row.get('referencedOwner'))
        target_name = db_ident(row.get('referencedName'))
        if source not in self.nodes or not target_name:
            return
        target = object_id(target_owner, target_name)
        if target not in self.nodes:
            return
        self._rel(source, target, 'DEPENDS_ON',
                  referencedType=str(row.get('referencedType', '')).upper())
        self.dictionary_dependencies.add((source, target))

    def _xref_unit_source(self, ref: Dict[str, Any]) -> None:
        """Package/procedure source from `ALL_SOURCE`: analyse it like DDL."""
        owner, name = ref['owner'], ref['name']
        node_id = object_id(owner, name)
        if node_id not in self.nodes:
            return
        if str(ref.get('type', '')).upper() in ('PACKAGE BODY', 'PACKAGE'):
            from .ddl import extract_unit_bodies
            for kind, unit_name, body in extract_unit_bodies(ref['text']):
                unit_node = self._db_program_unit(owner, name, unit_name,
                                                  {'unitKind': kind, 'isStandalone': False})
                self._plsql_code(unit_node, body, 'EXECUTES_PLSQL',
                                 f'{name}.{unit_name} body')
        else:
            self._plsql_code(node_id, ref['text'], 'EXECUTES_PLSQL', f'{name} body')

    # ── the binder ────────────────────────────────────────────────────
    def _bind_code(self) -> None:
        """Turn every parsed statement into data-access edges."""
        for node_id, analysis in list(self.sql_analyses.items()):
            self._bind_sql(node_id, analysis)
        for node_id, analysis in list(self.plsql_analyses.items()):
            for statement in analysis.statements:
                self._bind_sql(node_id, statement, nested=True)
            self._bind_calls(node_id, analysis.calls)
            self._bind_items(node_id, analysis.binds + analysis.substitutions)
            if analysis.apex_api_calls:
                self._set_property(node_id, 'apexApiCalls',
                                   ', '.join(sorted(set(analysis.apex_api_calls))[:10]))

    def _bind_sql(self, node_id: str, analysis, nested: bool = False) -> None:
        table_nodes: Dict[str, Tuple[str, str]] = {}
        for table in analysis.tables:
            resolution = self.resolver.resolve_object(table.owner, table.name)
            target = self._ensure_db_node(resolution)
            table_nodes[table.name.upper()] = (target, resolution.owner or
                                               db_ident(self.parsing_schema))
            if table.alias:
                table_nodes[table.alias.upper()] = table_nodes[table.name.upper()]
            for rel_type in ACCESS_RELS.get(table.access, ['READS_FROM']):
                self._rel(node_id, target, rel_type,
                          origin='inferred', confidence=resolution.confidence,
                          resolution=resolution.resolution,
                          evidenceSnippet=one_line(analysis.text, 160))
            if not resolution.resolved:
                self._defer_finding('CORR-001', node_id,
                                    f'references {table.name}, which is not in the '
                                    f'database extract')

        self._bind_columns(node_id, analysis, table_nodes)
        self._bind_calls(node_id, analysis.calls)
        self._bind_items(node_id, analysis.binds + analysis.substitutions)

        for owner, sequence in analysis.sequences:
            resolution = self.resolver.resolve_object(owner, sequence)
            self._rel(node_id, self._ensure_db_node(resolution), 'USES_SEQUENCE',
                      origin='inferred', confidence=resolution.confidence,
                      resolution=resolution.resolution)

    def _bind_columns(self, node_id: str, analysis,
                      table_nodes: Dict[str, Tuple[str, str]]) -> None:
        if not self.resolver.columns:
            return
        for qualifier, column in analysis.columns:
            candidates: List[Tuple[str, str]] = []
            if qualifier:
                table_name = analysis.alias_map.get(qualifier, qualifier)
                owner = table_nodes.get(table_name.upper(), (None, ''))[1]
                candidates.append((owner, table_name))
            else:
                for table in analysis.tables:
                    owner = table_nodes.get(table.name.upper(), (None, ''))[1]
                    candidates.append((owner, table.name))
            for owner, table_name in candidates:
                resolved = self.resolver.resolve_column(owner or self.parsing_schema,
                                                        table_name, column)
                if resolved and resolved in self.nodes:
                    self._rel(node_id, resolved, 'REFERENCES_COLUMN',
                              origin='inferred', confidence=0.85,
                              resolution='exact')
                    break

    def _bind_calls(self, node_id: str, calls) -> None:
        for package, name in calls:
            resolution = self.resolver.resolve_unit(package, name)
            if resolution.resolved:
                target = resolution.node_id
                if target not in self.nodes:
                    owner = resolution.owner or db_ident(self.parsing_schema)
                    target = self._db_program_unit(owner, package or None, name,
                                                   {'unitKind': 'PROCEDURE'})
                self._rel(node_id, target, 'CALLS',
                          origin='inferred', confidence=resolution.confidence,
                          resolution=resolution.resolution)
                package_node = object_id(resolution.owner or self.parsing_schema, package)
                if package and package_node in self.nodes:
                    self._rel(node_id, package_node, 'CALLS',
                              origin='inferred', confidence=resolution.confidence,
                              resolution=resolution.resolution)
            else:
                target = self._ensure_db_node(resolution)
                self._rel(node_id, target, 'CALLS',
                          origin='inferred', confidence=0.0, resolution='unresolved')
                self._defer_finding('CORR-001', node_id,
                                    f'calls {package}.{name}, which is not in the '
                                    f'database extract')

    def _bind_items(self, node_id: str, names) -> None:
        page = self.node_page.get(node_id)
        for name in sorted(set(names)):
            item = self._resolve_item(page, name)
            if item:
                self._rel(node_id, item, 'BINDS_ITEM',
                          origin='inferred', confidence=0.9, resolution='exact',
                          evidenceSnippet=f':{name}')

    # ── helpers ───────────────────────────────────────────────────────
    def _resolve_item(self, page: Optional[int], name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        name = str(name).upper()
        if page is not None:
            hit = self._lookup('item', (page, name))
            if hit:
                return hit
        hit = self._lookup('appItem', name)
        if hit:
            return hit
        # a page item bound from another page (a very common APEX pattern)
        for (item_page, item_name), node in self.registry.get('item', {}).items():
            if item_name == name:
                return node
        return None

    def _region_table(self, page: Optional[int], region: Optional[int]
                      ) -> Optional[Tuple[str, str]]:
        """The table a region is sourced from, declaratively or via its query."""
        if page is None or region is None:
            return None
        region_node = self._lookup('region', (page, region))
        if not region_node:
            return None
        node = self.nodes.get(region_node)
        if node and node.properties.get('queryTable'):
            return (node.properties.get('queryOwner') or self.parsing_schema,
                    str(node.properties['queryTable']).upper())
        for rel in self.rels:
            if rel.start_id != region_node:
                continue
            if rel.rel_type in ('SOURCED_FROM', 'EXECUTES_SQL'):
                if rel.rel_type == 'SOURCED_FROM':
                    target = self.nodes.get(rel.end_id)
                    if target:
                        return (target.properties.get('owner', ''), target.name.upper())
                analysis = self.sql_analyses.get(rel.end_id)
                if analysis and analysis.tables:
                    table = analysis.tables[0]
                    return (table.owner or self.parsing_schema, table.name.upper())
        return None

    def _ensure_db_node(self, resolution) -> str:
        """Materialise the node a resolution points at, including misses."""
        if resolution.node_id in self.nodes:
            return resolution.node_id
        if resolution.resolved:
            label = resolution.label if resolution.label in DB_OBJECT_LABELS else 'DbTable'
            return self._db_object(resolution.owner, resolution.name, label,
                                   {'origin': 'inferred'})
        node_id = unresolved_id(resolution.name)
        self._node(node_id, 'DbObject', resolution.name, {
            'rawName': resolution.name,
            'reason': 'not present in the database extract',
        }, extra_labels=['Unresolved'])
        self.stats['unresolvedObjects'] += 1
        return node_id


def _as_int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
