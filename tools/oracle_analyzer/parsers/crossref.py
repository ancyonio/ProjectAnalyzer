"""Deferred resolution.

Every edge whose target might not have been parsed yet is resolved here, in one
pass over the finished node set. Anything that still does not resolve becomes an
`UnresolvedRef` node rather than being dropped: a missing edge and a
deliberately-recorded gap look identical in a node count, and only one of them
is honest.

Synonyms are followed once, so a procedure that reads a synonym is recorded
against the object the synonym points at as well as the synonym itself.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from analyzer_core.ids import column_id, object_id, unresolved_id, unit_id
from analyzer_core.model import GraphNode
from analyzer_core.plsql import analyse_sql

from ..constants import DB_OBJECT_LABELS, WRITE_VERBS

logger = logging.getLogger('oracle_analyzer')


class CrossReferenceMixin:
    """Second pass: bind everything that needed the whole graph to exist."""

    def _cross_reference(self) -> int:
        edges = 0
        # Everything below resolves by name, so the name indexes have to exist
        # before the first lookup, not after it.
        self._index_objects()
        self._index_units()
        edges += self._resolve_synonyms()
        edges += self._resolve_indexes()
        edges += self._resolve_constraints()
        edges += self._resolve_triggers()
        edges += self._resolve_view_dependencies()
        edges += self._resolve_data_access()
        edges += self._resolve_columns()
        edges += self._resolve_joins()
        edges += self._resolve_sequences()
        edges += self._resolve_types()
        edges += self._resolve_calls()
        self._record_unresolved()
        logger.info('  %d cross-reference edge(s), %d unresolved',
                    edges, len(self.unresolved))
        return edges

    # ── lookup ────────────────────────────────────────────────────────
    def _find_object(self, owner: str, name: str,
                     follow_synonym: bool = True) -> Optional[str]:
        """Resolve owner.name to a node id, following one synonym hop."""
        owner = (owner or self.default_owner).upper()
        name = (name or '').upper().strip('"')
        if not name:
            return None

        node_id = object_id(owner, name)
        if node_id in self.nodes:
            if follow_synonym and self.nodes[node_id].label == 'DbSynonym':
                target = self.synonym_targets.get(node_id)
                if target and target in self.nodes:
                    return target
            return node_id

        # An unqualified name may belong to any analysed schema, and a public
        # synonym has no owner in the reference at all.
        candidate = self.objects_by_name.get(name)
        if candidate and len(candidate) == 1:
            resolved = candidate[0]
            if follow_synonym and self.nodes[resolved].label == 'DbSynonym':
                target = self.synonym_targets.get(resolved)
                if target and target in self.nodes:
                    return target
            return resolved
        return None

    def _index_objects(self) -> None:
        by_name: Dict[str, List[str]] = {}
        for node in self.nodes.values():
            if node.label in DB_OBJECT_LABELS or node.label == 'DbPackage':
                by_name.setdefault(node.name.upper(), []).append(node.node_id)
        self.objects_by_name = by_name

    # ── synonyms ──────────────────────────────────────────────────────
    def _resolve_synonyms(self) -> int:
        edges = 0
        for synonym_node, target in self.deferred_synonyms:
            owner, _, name = target.partition('.')
            if not name:
                owner, name = self.default_owner, owner
            target_node = self._find_object(owner, name, follow_synonym=False)
            if target_node:
                self.synonym_targets[synonym_node] = target_node
                self._add_rel(synonym_node, target_node, 'RESOLVES_TO',
                              purpose='synonym-indirection')
                edges += 1
            else:
                self._note_unresolved(synonym_node, target, 'synonym-target')
        self._index_objects()
        return edges

    # ── indexes and constraints ───────────────────────────────────────
    def _resolve_indexes(self) -> int:
        edges = 0
        for index_node, base in self.deferred_indexes:
            owner, _, name = base.partition('.')
            table_node = self._find_object(owner, name)
            if table_node:
                self._add_rel(table_node, index_node, 'HAS_INDEX',
                              purpose='table-structure')
                edges += 1
            else:
                self._note_unresolved(index_node, base, 'index-base-table')
        return edges

    def _resolve_constraints(self) -> int:
        edges = 0
        for constraint_node, obj in self.deferred_constraints:
            owner, _, name = (obj.base_object or '').partition('.')
            table_node = self._find_object(owner, name)
            if table_node:
                self._add_rel(constraint_node, table_node, 'CONSTRAINS',
                              constraintType=obj.query,
                              purpose='table-constraint')
                edges += 1
                for column in obj.columns:
                    col_node = column_id(
                        self.nodes[table_node].properties.get('owner', owner),
                        self.nodes[table_node].name, column.name)
                    if col_node in self.nodes:
                        self._add_rel(constraint_node, col_node, 'CONSTRAINS',
                                      purpose='column-constraint')
                        edges += 1
                        if obj.query == 'PRIMARY_KEY':
                            self._set_property(col_node, 'isPk', True)
            else:
                self._note_unresolved(constraint_node, obj.base_object,
                                      'constraint-table')

            if obj.target:
                ref_owner, _, ref_name = obj.target.partition('.')
                referenced = self._find_object(ref_owner, ref_name)
                if referenced and table_node:
                    self._add_rel(table_node, referenced, 'DEPENDS_ON',
                                  via='FOREIGN KEY', constraint=obj.name,
                                  purpose='referential-integrity')
                    edges += 1
                elif not referenced:
                    self._note_unresolved(constraint_node, obj.target,
                                          'foreign-key-target')

        for table_node, owner, constraint_name, referenced, columns in \
                self.deferred_inline_fks:
            ref_owner, _, ref_name = (referenced or '').partition('.')
            if not ref_name:
                ref_owner, ref_name = owner, ref_owner
            target = self._find_object(ref_owner, ref_name)
            if target:
                self._add_rel(table_node, target, 'DEPENDS_ON',
                              via='FOREIGN KEY', constraint=constraint_name,
                              purpose='referential-integrity')
                edges += 1
            else:
                self._note_unresolved(table_node, referenced, 'foreign-key-target')
        return edges

    # ── triggers ──────────────────────────────────────────────────────
    def _resolve_triggers(self) -> int:
        edges = 0
        for trigger_node, owner, obj in self.deferred_triggers:
            base_owner, _, base_name = (obj.base_object or '').partition('.')
            table_node = self._find_object(base_owner or owner, base_name)
            if table_node:
                self._add_rel(trigger_node, table_node, 'FIRES_ON',
                              event=obj.triggering_event,
                              purpose='trigger-target')
                edges += 1
            else:
                self._note_unresolved(trigger_node, obj.base_object,
                                      'trigger-base-table')
            if obj.body:
                self._attach_trigger_body(trigger_node, owner, obj.body)
        return edges

    def _attach_trigger_body(self, trigger_node: str, owner: str, body: str) -> None:
        from analyzer_core.plsql import analyse_plsql
        analysis = analyse_plsql(body)
        self._set_property(trigger_node, 'hasDynamicSql', analysis.has_dynamic_sql)
        self._set_property(trigger_node, 'hasCommit', analysis.has_commit)
        for statement in analysis.statements:
            for table in statement.tables:
                self.late_access.append(
                    (trigger_node, table.owner or owner, table.name,
                     table.access, table.db_link))
        for package, name in analysis.calls:
            self.late_calls.append((trigger_node, owner, package, name))
        # A trigger body is PL/SQL like any other, so it reaches types the same
        # way. Resolution runs after this pass, so the queue is still open.
        self._collect_type_refs(trigger_node, owner, body)

    # ── views ─────────────────────────────────────────────────────────
    def _resolve_view_dependencies(self) -> int:
        edges = 0
        for view_node, owner, query in self.deferred_view_queries:
            analysis = analyse_sql(query)
            self._set_property(view_node, 'tableCount', analysis.table_count)
            self._set_property(view_node, 'hasSelectStar', analysis.has_select_star)
            for table in analysis.tables:
                target = self._find_object(table.owner or owner, table.name)
                if target and target != view_node:
                    self._add_rel(view_node, target, 'DEPENDS_ON',
                                  via='VIEW', purpose='view-lineage')
                    edges += 1
                elif not target:
                    self._note_unresolved(view_node,
                                          f'{table.owner or owner}.{table.name}',
                                          'view-source-table')
        return edges

    # ── data access ───────────────────────────────────────────────────
    def _resolve_data_access(self) -> int:
        edges = 0
        pending = list(self.deferred_access) + list(self.late_access)
        seen: set = set()
        for source_node, owner, name, access, db_link in pending:
            if db_link:
                link_node = self._ensure_db_link(db_link)
                key = (source_node, link_node, 'REFERENCES_DBLINK')
                if key not in seen:
                    seen.add(key)
                    self._add_rel(source_node, link_node, 'REFERENCES_DBLINK',
                                  remoteObject=name,
                                  purpose='remote-dependency')
                    edges += 1
                continue

            target = self._find_object(owner, name)
            if not target:
                self._note_unresolved(source_node, f'{owner}.{name}',
                                      'data-access-target')
                continue
            if self.nodes[target].label not in (
                    'DbTable', 'DbView', 'DbMaterializedView', 'DbSynonym'):
                continue

            for rel_type in self._access_rels(access):
                key = (source_node, target, rel_type)
                if key in seen:
                    continue
                seen.add(key)
                self._add_rel(source_node, target, rel_type,
                              purpose='data-access')
                edges += 1
        return edges

    # ── column references ─────────────────────────────────────────────
    def _resolve_columns(self) -> int:
        """Bind a statement's column candidates to real `DbColumn` nodes.

        Strict where the parser is liberal: a candidate that is not a column of
        a table in scope simply produces no edge. That asymmetry is what makes
        over-collection in the SQL parser safe, and it is why an unqualified
        name is only bound when exactly one table could own it -- guessing
        between two would put lineage on the wrong column, which is worse than
        recording none.
        """
        edges = 0
        seen: set = set()
        for statement_node, owner, columns, aliases, tables in \
                self.deferred_columns:
            for qualifier, column in columns:
                if qualifier:
                    candidates = [(owner, aliases.get(qualifier.upper(),
                                                      qualifier))]
                else:
                    candidates = [(table_owner or owner, table_name)
                                  for table_owner, table_name in tables]
                    if len(candidates) != 1:
                        continue
                for table_owner, table_name in candidates:
                    target = self._find_object(table_owner, table_name)
                    if not target or self.nodes[target].label not in (
                            'DbTable', 'DbView', 'DbMaterializedView'):
                        continue
                    node = self.nodes[target]
                    col_node = column_id(
                        node.properties.get('owner', table_owner),
                        node.name, column.upper())
                    if col_node not in self.nodes:
                        continue
                    if (statement_node, col_node) not in seen:
                        seen.add((statement_node, col_node))
                        self._add_rel(statement_node, col_node,
                                      'REFERENCES_COLUMN',
                                      purpose='column-lineage')
                        edges += 1
                    break
        self.stats['column_references'] = edges
        return edges

    # ── joins ─────────────────────────────────────────────────────────
    def _resolve_joins(self) -> int:
        """`JOINS` records that a statement combines a table with others.

        `READS_FROM` already says the statement touches the table; only the
        join edge says it was combined with something else, which is the edge a
        query-shape or index review starts from.
        """
        edges = 0
        seen: set = set()
        for statement_node, owner, name in self.deferred_joins:
            target = self._find_object(owner, name)
            if not target or self.nodes[target].label not in (
                    'DbTable', 'DbView', 'DbMaterializedView'):
                continue
            key = (statement_node, target)
            if key in seen:
                continue
            seen.add(key)
            self._add_rel(statement_node, target, 'JOINS',
                          purpose='query-shape')
            edges += 1
        return edges

    # ── user-defined types ────────────────────────────────────────────
    def _resolve_types(self) -> int:
        """Only a name that is a `DbType` in scope becomes an edge.

        Everything else the type-position scanner offered was a scalar, a
        keyword or a local, and is dropped without comment: an unresolved type
        candidate is a parser artefact, not a missing dependency, so recording
        it as unresolved would inflate the honest count of real gaps.
        """
        edges = 0
        seen: set = set()
        for source_node, owner, name in self.deferred_types:
            target = self._find_object(owner, name)
            if not target or self.nodes[target].label != 'DbType':
                continue
            if target == source_node or (source_node, target) in seen:
                continue
            seen.add((source_node, target))
            self._add_rel(source_node, target, 'USES_TYPE',
                          purpose='type-dependency')
            edges += 1
        self.stats['type_references'] = edges
        return edges

    @staticmethod
    def _access_rels(access: str) -> Tuple[str, ...]:
        """The specific verb plus the WRITES_TO roll-up, per the spec."""
        if access == 'READ':
            return ('READS_FROM',)
        verb = WRITE_VERBS.get(access)
        return (verb, 'WRITES_TO') if verb else ('WRITES_TO',)

    # ── sequences and calls ───────────────────────────────────────────
    def _resolve_sequences(self) -> int:
        edges = 0
        seen: set = set()
        for source_node, owner, name in self.deferred_sequences:
            target = self._find_object(owner, name)
            if target and self.nodes[target].label == 'DbSequence':
                if (source_node, target) in seen:
                    continue
                seen.add((source_node, target))
                self._add_rel(source_node, target, 'USES_SEQUENCE',
                              purpose='sequence-usage')
                edges += 1
        return edges

    def _resolve_calls(self) -> int:
        edges = 0
        seen: set = set()
        pending = list(self.deferred_calls) + list(self.late_calls)
        for source_node, owner, package, name in pending:
            target, ambiguous = self._find_unit(owner, package, name)
            if not target:
                self.stats['calls_unresolved'] += 1
                self._note_unresolved(
                    source_node, f'{package}.{name}' if package else name,
                    'call-target')
                continue
            if target == source_node or (source_node, target) in seen:
                continue
            seen.add((source_node, target))
            self.stats['calls_resolved'] += 1
            self._add_rel(source_node, target, 'CALLS',
                          ambiguous=ambiguous, purpose='call-graph')
            edges += 1
        return edges

    def _find_unit(self, owner: str, package: str,
                   name: str) -> Tuple[Optional[str], bool]:
        """Resolve a call target, reporting overload ambiguity rather than guessing."""
        owner = (owner or self.default_owner).upper()
        package = (package or '').upper()
        name = (name or '').upper()

        if package:
            # `ORDER_APP.ARCHIVE_ORDERS` is schema-qualified, not
            # package-qualified. Without this the unit's own CREATE header
            # reads as a call to a package that does not exist, and the
            # procedure appears to reference itself and fail to resolve.
            if package in self.known_schemas:
                schema_qualified = unit_id(package, None, name)
                if schema_qualified in self.nodes:
                    return schema_qualified, False

            direct = unit_id(owner, package, name)
            if direct in self.nodes:
                return direct, self._is_overloaded(owner, package, name)
            # the package may belong to another analysed schema
            for candidate in self.units_by_name.get(name, []):
                node = self.nodes[candidate]
                if node.properties.get('packageName', '').upper() == package:
                    return candidate, self._is_overloaded(
                        node.properties.get('owner', ''), package, name)
            return None, False

        standalone = unit_id(owner, None, name)
        if standalone in self.nodes:
            return standalone, False
        candidates = self.units_by_name.get(name, [])
        if len(candidates) == 1:
            return candidates[0], False
        if candidates:
            return candidates[0], True
        return None, False

    def _is_overloaded(self, owner: str, package: str, name: str) -> bool:
        return sum(1 for node_id in self.units_by_name.get(name.upper(), [])
                   if self.nodes[node_id].properties.get('packageName',
                                                         '').upper() == package) > 1

    def _index_units(self) -> None:
        self.known_schemas = {node.name.upper()
                              for node in self.nodes.values()
                              if node.label == 'DbSchema'}
        by_name: Dict[str, List[str]] = {}
        for node in self.nodes.values():
            if node.label == 'DbProgramUnit':
                by_name.setdefault(node.name.upper(), []).append(node.node_id)
        self.units_by_name = by_name

    # ── unresolved bookkeeping ────────────────────────────────────────
    def _note_unresolved(self, source_node: str, reference: str, kind: str) -> None:
        reference = (reference or '').strip().upper()
        if not reference or reference.startswith('.'):
            return
        self.unresolved.setdefault(reference, set()).add(kind)
        self.unresolved_sources.setdefault(reference, set()).add(source_node)

    def _record_unresolved(self) -> None:
        for reference, kinds in sorted(self.unresolved.items()):
            node_id = unresolved_id(reference)
            if node_id not in self.nodes:
                self._add_node(GraphNode(node_id, 'UnresolvedRef', reference, {
                    'kinds': ', '.join(sorted(kinds)),
                    'referenceCount': len(self.unresolved_sources.get(reference, ())),
                }))
            for source_node in sorted(self.unresolved_sources.get(reference, ())):
                self._add_rel(source_node, node_id, 'UNRESOLVED',
                              purpose='unresolved-reference')

    def _ensure_db_link(self, name: str) -> str:
        node_id = object_id('PUBLIC', name)
        if node_id not in self.nodes:
            self._add_node(GraphNode(node_id, 'DbDatabaseLink', name.upper(), {
                'owner': 'PUBLIC',
                'objectType': 'DATABASE LINK',
                'origin': 'inferred',
            }))
        return node_id
