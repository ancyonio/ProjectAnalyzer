"""Database layer construction.

Two sources, merged, dictionary first:

1. `db_meta.json` — produced by `apex_analyzer/extract/*.sql`. Authoritative:
   real objects, real columns, real `ALL_DEPENDENCIES` edges, real source.
2. DDL committed in the repository — parsed by `ddl.py`. Used when there is no
   extract, and merged underneath one when there is, so a table that exists in
   the repo but not (yet) in the target schema is still visible.

Everything registered here also goes into the `Resolver`, which is what lets
the SQL binder turn `orders` in a region query into
`db:ORDER_APP.ORDERS` with a stated confidence.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from analyzer_core.ids import column_id, db_ident, object_id, schema_id, unit_id
from analyzer_core.utils import read_text

from .ddl import DdlObject, extract_unit_bodies, parse_ddl

logger = logging.getLogger('apex_analyzer')

KIND_LABEL = {
    'TABLE': 'DbTable',
    'VIEW': 'DbView',
    'MVIEW': 'DbMaterializedView',
    'MATERIALIZED VIEW': 'DbMaterializedView',
    'PACKAGE': 'DbPackage',
    'PACKAGE BODY': 'DbPackage',
    'UNIT': 'DbProgramUnit',
    'PROCEDURE': 'DbProgramUnit',
    'FUNCTION': 'DbProgramUnit',
    'TRIGGER': 'DbTrigger',
    'SEQUENCE': 'DbSequence',
    'SYNONYM': 'DbSynonym',
    'TYPE': 'DbType',
    'DATABASE LINK': 'DbDatabaseLink',
    'INDEX': 'DbIndex',
    'CONSTRAINT': 'DbConstraint',
}


def load_json(path: Optional[Path]) -> Dict[str, Any]:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'Metadata extract not found: {path}')
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f'{path} is not valid JSON: {exc}') from exc


class DatabaseMetadataMixin:
    """Builds `:DbObject` nodes from a dictionary extract and/or DDL scripts."""

    # ------------------------------------------------------------------
    def _parse_database_metadata(self) -> None:
        payload = load_json(self.db_meta_path) if self.db_meta_path else {}
        if payload:
            self._load_dictionary(payload)
        self._load_ddl_files()

    # ── dictionary extract ────────────────────────────────────────────
    def _load_dictionary(self, payload: Dict[str, Any]) -> None:
        self.stats['dbMetaSections'] = len([k for k, v in payload.items() if v])
        schemas = payload.get('schemas') or []
        for owner in schemas:
            self._db_schema(owner)

        for row in payload.get('objects', []) or []:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('name') or row.get('objectName'))
            object_type = str(row.get('objectType') or row.get('type') or '').upper()
            label = KIND_LABEL.get(object_type)
            if not label or not name:
                continue
            self._db_object(owner, name, label, {
                'status': row.get('status', ''),
                'objectType': object_type,
            })

        for row in payload.get('tables', []) or []:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('tableName') or row.get('name'))
            if not name:
                continue
            node_id = self._db_object(owner, name, 'DbTable', {
                'numRows': _int(row.get('numRows')),
                'partitioned': str(row.get('partitioned', '')).upper() == 'YES',
            })
            self.stats['dbTables'] += 1

        for row in payload.get('views', []) or []:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('viewName') or row.get('name'))
            if not name:
                continue
            self._db_object(owner, name, 'DbView', {'isUpdatable': False})
            text = row.get('text') or row.get('query') or ''
            if text:
                self._defer('viewQuery', owner=owner, name=name, query=text)

        for row in payload.get('columns', []) or []:
            self._db_column(
                db_ident(row.get('owner')),
                db_ident(row.get('tableName') or row.get('table')),
                db_ident(row.get('columnName') or row.get('name')),
                {
                    'dataType': row.get('dataType', ''),
                    'dataLength': _int(row.get('dataLength')),
                    'nullable': str(row.get('nullable', 'Y')).upper() in ('Y', 'YES', 'TRUE'),
                    'columnId': _int(row.get('columnId')),
                })

        for row in payload.get('programUnits', []) or []:
            owner = db_ident(row.get('owner'))
            package = db_ident(row.get('packageName') or row.get('objectName'))
            name = db_ident(row.get('name') or row.get('procedureName'))
            if not name:
                continue
            self._db_program_unit(owner, package or None, name, {
                'unitKind': str(row.get('unitKind') or row.get('type') or 'PROCEDURE').upper(),
                'argumentCount': _int(row.get('argumentCount')),
                'overload': _int(row.get('overload')),
                'isStandalone': not bool(package),
            })

        for row in payload.get('synonyms', []) or []:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('synonymName') or row.get('name'))
            target_owner = db_ident(row.get('tableOwner') or row.get('targetOwner'))
            target_name = db_ident(row.get('tableName') or row.get('targetName'))
            if not name:
                continue
            node_id = self._db_object(owner, name, 'DbSynonym', {
                'targetOwner': target_owner, 'targetName': target_name,
                'dbLink': row.get('dbLink', '') or '',
            })
            self.resolver.register_synonym(owner, name, target_owner, target_name)
            if target_name:
                self._defer('synonymTarget', node_id=node_id, owner=target_owner,
                            name=target_name)

        for row in payload.get('sequences', []) or []:
            self._db_object(db_ident(row.get('owner')),
                            db_ident(row.get('sequenceName') or row.get('name')),
                            'DbSequence', {})

        for row in payload.get('triggers', []) or []:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('triggerName') or row.get('name'))
            if not name:
                continue
            node_id = self._db_object(owner, name, 'DbTrigger', {
                'triggeringEvent': row.get('triggeringEvent', ''),
                'status': row.get('status', ''),
                'baseObject': f"{db_ident(row.get('tableOwner'))}."
                              f"{db_ident(row.get('tableName'))}",
            })
            if row.get('tableName'):
                self._defer('triggerTable', node_id=node_id,
                            owner=db_ident(row.get('tableOwner')),
                            table=db_ident(row.get('tableName')))
            body = row.get('body') or row.get('triggerBody') or ''
            if body:
                self._plsql_code(node_id, body, 'EXECUTES_PLSQL', 'trigger body')

        for row in payload.get('constraints', []) or []:
            self._db_constraint(row)

        for row in payload.get('indexes', []) or []:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('indexName') or row.get('name'))
            if not name:
                continue
            self._db_object(owner, name, 'DbIndex', {
                'tableName': db_ident(row.get('tableName')),
                'uniqueness': row.get('uniqueness', ''),
                'columns': row.get('columns', ''),
            })

        for row in payload.get('dependencies', []) or []:
            self._defer('dictionaryDependency', row=row)

        for row in payload.get('source', []) or []:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('name'))
            text = row.get('text') or ''
            if not name or not text:
                continue
            self._defer('unitSource', owner=owner, name=name,
                        type=str(row.get('type', '')).upper(), text=text)

        for row in payload.get('databaseLinks', []) or []:
            self._db_object(db_ident(row.get('owner')),
                            db_ident(row.get('dbLink') or row.get('name')),
                            'DbDatabaseLink', {'host': row.get('host', '')})

    # ── DDL scripts ───────────────────────────────────────────────────
    def _load_ddl_files(self) -> None:
        for export_file in self.inventory.db_files:
            text = read_text(export_file.path)
            result = parse_ddl(text, default_owner=self.parsing_schema,
                               source_file=export_file.relative)
            self.stats['ddlStatements'] += result.statements_seen
            for obj in result.objects:
                self._from_ddl(obj, export_file)

    def _from_ddl(self, obj: DdlObject, export_file) -> None:
        owner = db_ident(obj.owner or self.parsing_schema)
        name = db_ident(obj.name)
        if not name:
            return
        file_node = export_file.node_id
        source = {'sourceFile': export_file.relative, 'sourceLine': obj.source_line}

        if obj.kind == 'TABLE':
            node_id = self._db_object(owner, name, 'DbTable', {
                'columnCount': len(obj.columns),
                'hasPk': any(c.is_pk for c in obj.columns), **source})
            self._rel(file_node, node_id, 'DEFINES')
            for column in obj.columns:
                self._db_column(owner, name, column.name, {
                    'dataType': column.data_type, 'nullable': column.nullable,
                    'isPk': column.is_pk, 'isFk': column.is_fk,
                    'columnId': column.position})
            for constraint_name, reference, columns in obj.foreign_keys:
                self._db_fk(owner, name, constraint_name, reference, columns, source)

        elif obj.kind in ('VIEW', 'MVIEW'):
            label = 'DbView' if obj.kind == 'VIEW' else 'DbMaterializedView'
            node_id = self._db_object(owner, name, label, source)
            self._rel(file_node, node_id, 'DEFINES')
            if obj.query:
                self._defer('viewQuery', owner=owner, name=name, query=obj.query)

        elif obj.kind == 'PACKAGE':
            node_id = self._db_object(owner, name, 'DbPackage', {
                'unitCount': len(obj.units),
                'bodyLines': obj.body.count('\n') + 1 if obj.body else 0, **source})
            self._rel(file_node, node_id, 'DEFINES')
            for kind, unit_name in obj.units:
                unit_node = self._db_program_unit(owner, name, unit_name, {
                    'unitKind': kind, 'isStandalone': False, **source})
                self._rel(file_node, unit_node, 'DEFINES')
            if obj.body:
                for kind, unit_name, body in extract_unit_bodies(obj.body):
                    unit_node = self._db_program_unit(owner, name, unit_name,
                                                      {'unitKind': kind,
                                                       'isStandalone': False, **source})
                    self._plsql_code(unit_node, body, 'EXECUTES_PLSQL',
                                     f'{name}.{unit_name} body')

        elif obj.kind == 'UNIT':
            kind = obj.units[0][0] if obj.units else 'PROCEDURE'
            node_id = self._db_program_unit(owner, None, name,
                                            {'unitKind': kind, 'isStandalone': True, **source})
            self._rel(file_node, node_id, 'DEFINES')
            if obj.body:
                self._plsql_code(node_id, obj.body, 'EXECUTES_PLSQL', f'{name} body')

        elif obj.kind == 'TRIGGER':
            node_id = self._db_object(owner, name, 'DbTrigger', {
                'triggeringEvent': obj.triggering_event,
                'baseObject': obj.base_object, **source})
            self._rel(file_node, node_id, 'DEFINES')
            if obj.base_object:
                base_owner, _, base_name = obj.base_object.partition('.')
                self._defer('triggerTable', node_id=node_id, owner=base_owner,
                            table=base_name)
            if obj.body:
                self._plsql_code(node_id, obj.body, 'EXECUTES_PLSQL', 'trigger body')

        elif obj.kind == 'SEQUENCE':
            self._rel(file_node, self._db_object(owner, name, 'DbSequence', source), 'DEFINES')

        elif obj.kind == 'SYNONYM':
            target_owner, _, target_name = (obj.target or '').partition('.')
            node_id = self._db_object(owner, name, 'DbSynonym', {
                'targetOwner': target_owner, 'targetName': target_name, **source})
            self.resolver.register_synonym(owner, name, target_owner, target_name)
            if target_name:
                self._defer('synonymTarget', node_id=node_id, owner=target_owner,
                            name=target_name)

        elif obj.kind == 'INDEX':
            base_owner, _, base_name = (obj.base_object or '').partition('.')
            self._db_object(owner, name, 'DbIndex', {
                'tableName': base_name, 'uniqueness': obj.query,
                'columns': ','.join(c.name for c in obj.columns), **source})

        elif obj.kind == 'CONSTRAINT':
            base_owner, _, base_name = (obj.base_object or '').partition('.')
            if obj.query == 'FOREIGN_KEY' and obj.target:
                self._db_fk(base_owner or owner, base_name, name, obj.target,
                            ','.join(c.name for c in obj.columns), source)
            else:
                self._db_constraint({'owner': owner, 'constraintName': name,
                                     'constraintType': obj.query,
                                     'tableName': base_name, **source})

    # ── node builders ─────────────────────────────────────────────────
    def _db_schema(self, owner: str) -> str:
        owner = db_ident(owner)
        node_id = schema_id(owner)
        self._node(node_id, 'DbSchema', owner, {
            'owner': owner,
            'isParsingSchema': owner == db_ident(self.parsing_schema),
        })
        return node_id

    def _db_object(self, owner: str, name: str, label: str,
                   props: Optional[Dict[str, Any]] = None) -> str:
        owner, name = db_ident(owner or self.parsing_schema), db_ident(name)
        node_id = object_id(owner, name)
        payload = {'owner': owner, 'objectName': name}
        payload.update(props or {})
        self._node(node_id, label, name, payload, extra_labels=['DbObject'])
        self.resolver.register_object(owner, name, label)
        if owner:
            self._rel(self._db_schema(owner), node_id, 'OWNS')
        return node_id

    def _db_column(self, owner: str, table: str, column: str,
                   props: Optional[Dict[str, Any]] = None) -> Optional[str]:
        owner, table, column = db_ident(owner or self.parsing_schema), db_ident(table), \
            db_ident(column)
        if not table or not column:
            return None
        table_node = object_id(owner, table)
        if table_node not in self.nodes:
            self._db_object(owner, table, 'DbTable', {})
        node_id = column_id(owner, table, column)
        payload = {'owner': owner, 'tableName': table}
        payload.update(props or {})
        self._node(node_id, 'DbColumn', column, payload)
        self._rel(table_node, node_id, 'HAS_COLUMN')
        self.resolver.register_column(owner, table, column)
        return node_id

    def _db_program_unit(self, owner: str, package: Optional[str], name: str,
                         props: Optional[Dict[str, Any]] = None) -> str:
        owner, name = db_ident(owner or self.parsing_schema), db_ident(name)
        package = db_ident(package) if package else None
        node_id = unit_id(owner, package, name, (props or {}).get('overload'))
        payload = {'owner': owner, 'packageName': package or '', 'unitKind': 'PROCEDURE'}
        payload.update(props or {})
        display = f'{package}.{name}' if package else name
        self._node(node_id, 'DbProgramUnit', display, payload, extra_labels=['DbObject'])
        self.resolver.register_unit(owner, package, name)
        if package:
            package_node = object_id(owner, package)
            if package_node not in self.nodes:
                self._db_object(owner, package, 'DbPackage', {})
            self._rel(package_node, node_id, 'HAS_UNIT')
        else:
            self.resolver.register_object(owner, name, 'DbProgramUnit')
            self._rel(self._db_schema(owner), node_id, 'OWNS')
        return node_id

    def _db_constraint(self, row: Dict[str, Any]) -> None:
        owner = db_ident(row.get('owner'))
        name = db_ident(row.get('constraintName') or row.get('name'))
        table = db_ident(row.get('tableName'))
        if not name:
            return
        node_id = object_id(owner, name)
        self._node(node_id, 'DbConstraint', name, {
            'owner': owner, 'constraintType': row.get('constraintType', ''),
            'tableName': table, 'refTable': db_ident(row.get('refTable', '')),
            'columns': row.get('columns', ''),
            'sourceFile': row.get('sourceFile', ''),
        })
        if table:
            table_node = object_id(owner, table)
            if table_node in self.nodes:
                self._rel(node_id, table_node, 'CONSTRAINS')
        reference = db_ident(row.get('refTable', ''))
        if reference:
            self._defer('constraintReference', node_id=node_id,
                        owner=db_ident(row.get('refOwner') or owner), table=reference)

    def _db_fk(self, owner: str, table: str, constraint: str, reference: str,
               columns: str, source: Dict[str, Any]) -> None:
        ref_owner, _, ref_name = reference.partition('.')
        self._db_constraint({'owner': owner, 'constraintName': constraint,
                             'constraintType': 'FOREIGN_KEY', 'tableName': table,
                             'refTable': ref_name, 'refOwner': ref_owner,
                             'columns': columns, **source})


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
