"""Schema objects from DDL.

Turns the `DdlObject` records the shared DDL parser produces into the schema
layer of the graph: tables and their columns, views, materialized views,
sequences, synonyms, indexes, constraints and triggers.

Views and triggers carry code, but their dependency edges are not resolved
here -- an object referenced before its `create` statement has been read would
resolve to nothing. Everything that needs a target is deferred to `crossref`.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from analyzer_core.ids import column_id, object_id
from analyzer_core.model import GraphNode
from analyzer_core.plsql import parse_ddl

logger = logging.getLogger('oracle_analyzer')

# DDL kind -> graph label for the objects handled directly here.
_KIND_LABEL: Dict[str, str] = {
    'TABLE': 'DbTable',
    'VIEW': 'DbView',
    'MVIEW': 'DbMaterializedView',
    'SEQUENCE': 'DbSequence',
    'SYNONYM': 'DbSynonym',
    'INDEX': 'DbIndex',
    'CONSTRAINT': 'DbConstraint',
    'TRIGGER': 'DbTrigger',
    'TYPE': 'DbType',
}


class SchemaObjectParserMixin:
    """Builds the schema layer from DDL scripts."""

    def _parse_schema_objects(self) -> int:
        created = 0
        for source in self.sources:
            result = parse_ddl(source.text, default_owner=self.default_owner,
                               source_file=source.rel_path)
            self.stats['ddl_statements'] += result.statements_seen
            self.stats['ddl_unparsed'] += result.unparsed

            for obj in result.objects:
                # Packages and standalone units are program structure, handled
                # by the program parser, which needs their bodies.
                if obj.kind in ('PACKAGE', 'UNIT'):
                    self.program_objects.append((source, obj))
                    continue
                if self._create_object(source, obj):
                    created += 1

        self.stats['schema_objects'] = created
        logger.info('  %d schema object(s) from DDL', created)
        return created

    # ------------------------------------------------------------------
    def _create_object(self, source, obj) -> bool:
        label = _KIND_LABEL.get(obj.kind)
        if label is None:
            return False

        owner = obj.owner or self.default_owner
        node_id = object_id(owner, obj.name)
        schema_node = self._ensure_schema(owner)

        properties = {
            'owner': owner,
            'objectType': obj.kind,
            'filePath': source.rel_path,
            'lineStart': obj.source_line,
            'origin': 'ddl',
        }

        if obj.kind in ('VIEW', 'MVIEW'):
            properties['query'] = self._truncate(obj.query)
            properties['hasQuery'] = bool(obj.query)
        if obj.kind == 'SYNONYM':
            properties['target'] = obj.target
            properties['isPublic'] = owner == 'PUBLIC'
        if obj.kind == 'INDEX':
            properties['baseObject'] = obj.base_object
            properties['uniqueness'] = obj.query or 'NONUNIQUE'
            properties['columns'] = ', '.join(c.name for c in obj.columns)
        if obj.kind == 'CONSTRAINT':
            properties['baseObject'] = obj.base_object
            properties['constraintType'] = obj.query
            properties['columns'] = ', '.join(c.name for c in obj.columns)
            properties['referencedObject'] = obj.target
        if obj.kind == 'TRIGGER':
            properties['baseObject'] = obj.base_object
            properties['triggeringEvent'] = obj.triggering_event
            properties['loc'] = (obj.body or '').count('\n') + 1

        # A table can be created by DDL and then altered; keep the first
        # definition but let a later one add columns.
        if node_id in self.nodes:
            existing = self.nodes[node_id]
            if obj.kind == 'TABLE':
                self._add_columns(owner, obj, node_id)
            return existing.label == label and False

        self._add_node(GraphNode(node_id, label, obj.name, properties))
        self._add_rel(schema_node, node_id, 'OWNS', purpose='schema-ownership')
        self._add_rel(source.node_id, node_id, 'DEFINES', purpose='source-definition')
        source.objects.append(node_id)

        if obj.kind == 'TABLE':
            self._add_columns(owner, obj, node_id)
        if obj.kind in ('VIEW', 'MVIEW') and obj.query:
            self.deferred_view_queries.append((node_id, owner, obj.query))
        if obj.kind == 'TRIGGER':
            self.deferred_triggers.append((node_id, owner, obj))
        if obj.kind == 'SYNONYM' and obj.target:
            self.deferred_synonyms.append((node_id, obj.target))
        if obj.kind == 'INDEX' and obj.base_object:
            self.deferred_indexes.append((node_id, obj.base_object))
        if obj.kind == 'CONSTRAINT':
            self.deferred_constraints.append((node_id, obj))
        return True

    # ------------------------------------------------------------------
    def _add_columns(self, owner: str, obj, table_node_id: str) -> None:
        for column in obj.columns:
            col_id = column_id(owner, obj.name, column.name)
            if col_id in self.nodes:
                continue
            self._add_node(GraphNode(col_id, 'DbColumn', column.name, {
                'owner': owner,
                'tableName': obj.name,
                'dataType': column.data_type,
                'nullable': column.nullable,
                'isPk': column.is_pk,
                'isFk': column.is_fk,
                'position': column.position,
                'origin': 'ddl',
            }))
            self._add_rel(table_node_id, col_id, 'HAS_COLUMN',
                          purpose='table-structure')

        if obj.columns:
            self._set_property(table_node_id, 'columnCount', len(obj.columns))
            self._set_property(table_node_id, 'hasPk',
                               any(c.is_pk for c in obj.columns))

        for constraint_name, referenced, columns in obj.foreign_keys:
            self.deferred_inline_fks.append(
                (table_node_id, owner, constraint_name, referenced, columns))
