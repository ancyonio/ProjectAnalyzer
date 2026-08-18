"""Data-dictionary extract.

Optional, and authoritative where present. A graph built from DDL scripts is a
statement about the repository; one merged with a dictionary extract is a
statement about the deployed database. They disagree in real estates -- an
object dropped in production but still in source control, a column added by a
hotfix that never made it back -- and the disagreement is itself a finding.

The extract runs after the DDL pass so it can overwrite what DDL inferred and
add what the repository never held. It consumes the same JSON shape as the APEX
analyzer's extract, so `apex_analyzer/extract/*.sql` serves both.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from analyzer_core.ids import column_id, db_ident, object_id, unit_id
from analyzer_core.model import GraphNode

logger = logging.getLogger('oracle_analyzer')

_OBJECT_TYPE_LABEL: Dict[str, str] = {
    'TABLE': 'DbTable',
    'VIEW': 'DbView',
    'MATERIALIZED VIEW': 'DbMaterializedView',
    'SEQUENCE': 'DbSequence',
    'SYNONYM': 'DbSynonym',
    'TRIGGER': 'DbTrigger',
    'TYPE': 'DbType',
    'PACKAGE': 'DbPackage',
    'PACKAGE BODY': 'DbPackage',
    'PROCEDURE': 'DbProgramUnit',
    'FUNCTION': 'DbProgramUnit',
    'INDEX': 'DbIndex',
    'DATABASE LINK': 'DbDatabaseLink',
}


class DictionaryMixin:
    """Merges an Oracle data-dictionary extract over the DDL-derived graph."""

    def _parse_dictionary(self, path: Path) -> int:
        try:
            payload: Dict[str, Any] = json.loads(
                Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            logger.warning('  dictionary extract unreadable (%s); '
                           'continuing from DDL only', exc)
            self.dictionary_available = False
            return 0

        self.dictionary_available = True
        merged = 0
        merged += self._merge_objects(payload.get('objects') or [])
        merged += self._merge_tables(payload.get('tables') or [])
        merged += self._merge_columns(payload.get('columns') or [])
        merged += self._merge_units(payload.get('programUnits') or [])
        merged += self._merge_synonyms(payload.get('synonyms') or [])
        merged += self._merge_dependencies(payload.get('dependencies') or [])

        self.stats['dictionary_rows'] = merged
        logger.info('  %d dictionary row(s) merged', merged)
        return merged

    # ------------------------------------------------------------------
    def _merge_objects(self, rows: List[Dict[str, Any]]) -> int:
        merged = 0
        for row in rows:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('name'))
            object_type = (row.get('objectType') or '').upper()
            label = _OBJECT_TYPE_LABEL.get(object_type)
            if not owner or not name or not label:
                continue

            node_id = object_id(owner, name)
            self._ensure_schema(owner)
            if node_id in self.nodes:
                node = self.nodes[node_id]
                node.properties['status'] = row.get('status', 'VALID')
                node.properties['origin'] = 'dictionary'
            elif label != 'DbProgramUnit':
                self._add_node(GraphNode(node_id, label, name, {
                    'owner': owner,
                    'objectType': object_type,
                    'status': row.get('status', 'VALID'),
                    'origin': 'dictionary',
                }))
                self._add_rel(self._ensure_schema(owner), node_id, 'OWNS',
                              purpose='schema-ownership')
                self.dictionary_only.append(node_id)
            merged += 1
        return merged

    def _merge_tables(self, rows: List[Dict[str, Any]]) -> int:
        merged = 0
        for row in rows:
            node_id = object_id(db_ident(row.get('owner')),
                                db_ident(row.get('tableName')))
            if node_id not in self.nodes:
                continue
            properties = self.nodes[node_id].properties
            if row.get('numRows') is not None:
                properties['numRows'] = row['numRows']
            if row.get('partitioned') is not None:
                properties['partitioned'] = str(row['partitioned']).upper() in ('YES', 'TRUE', '1')
            properties['origin'] = 'dictionary'
            merged += 1
        return merged

    def _merge_columns(self, rows: List[Dict[str, Any]]) -> int:
        merged = 0
        for row in rows:
            owner = db_ident(row.get('owner'))
            table = db_ident(row.get('tableName'))
            column = db_ident(row.get('columnName'))
            table_node = object_id(owner, table)
            if not column or table_node not in self.nodes:
                continue
            node_id = column_id(owner, table, column)
            properties = {
                'owner': owner,
                'tableName': table,
                'dataType': row.get('dataType', ''),
                'dataLength': row.get('dataLength'),
                'nullable': str(row.get('nullable', 'Y')).upper() in ('Y', 'YES', 'TRUE'),
                'columnId': row.get('columnId'),
                'origin': 'dictionary',
            }
            if node_id in self.nodes:
                self.nodes[node_id].properties.update(
                    {k: v for k, v in properties.items() if v is not None})
            else:
                self._add_node(GraphNode(node_id, 'DbColumn', column, properties))
                self._add_rel(table_node, node_id, 'HAS_COLUMN',
                              purpose='table-structure')
            merged += 1
        return merged

    def _merge_units(self, rows: List[Dict[str, Any]]) -> int:
        """Dictionary units carry the overload position source cannot supply."""
        merged = 0
        for row in rows:
            owner = db_ident(row.get('owner'))
            package = db_ident(row.get('packageName'))
            name = db_ident(row.get('name'))
            if not owner or not name:
                continue
            overload = row.get('overload') or None
            node_id = unit_id(owner, package or None, name, overload)
            properties = {
                'owner': owner,
                'packageName': package,
                'unitType': (row.get('unitKind') or 'PROCEDURE').upper(),
                'argumentCount': row.get('argumentCount'),
                'overload': int(overload) if overload else 0,
                'overloadResolution': 'dictionary',
                'origin': 'dictionary',
            }
            if node_id in self.nodes:
                self.nodes[node_id].properties.update(
                    {k: v for k, v in properties.items() if v is not None})
            else:
                self._add_node(GraphNode(node_id, 'DbProgramUnit', name,
                                         {k: v for k, v in properties.items()
                                          if v is not None}))
                parent = object_id(owner, package) + '#spec' if package \
                    else self._ensure_schema(owner)
                if parent in self.nodes:
                    self._add_rel(parent, node_id, 'HAS_UNIT',
                                  purpose='package-membership')
                else:
                    self._add_rel(self._ensure_schema(owner), node_id, 'OWNS',
                                  purpose='schema-ownership')
                self.dictionary_only.append(node_id)
            merged += 1
        return merged

    def _merge_synonyms(self, rows: List[Dict[str, Any]]) -> int:
        merged = 0
        for row in rows:
            owner = db_ident(row.get('owner'))
            name = db_ident(row.get('synonymName'))
            target_owner = db_ident(row.get('tableOwner'))
            target_name = db_ident(row.get('tableName'))
            if not name or not target_name:
                continue
            node_id = object_id(owner, name)
            if node_id not in self.nodes:
                self._add_node(GraphNode(node_id, 'DbSynonym', name, {
                    'owner': owner,
                    'objectType': 'SYNONYM',
                    'target': f'{target_owner}.{target_name}',
                    'isPublic': owner == 'PUBLIC',
                    'origin': 'dictionary',
                }))
                self._add_rel(self._ensure_schema(owner), node_id, 'OWNS',
                              purpose='schema-ownership')
            self.deferred_synonyms.append(
                (node_id, f'{target_owner}.{target_name}'))
            merged += 1
        return merged

    def _merge_dependencies(self, rows: List[Dict[str, Any]]) -> int:
        """True dependency edges, which static parsing can only approximate."""
        merged = 0
        for row in rows:
            source = object_id(db_ident(row.get('owner')), db_ident(row.get('name')))
            target = object_id(db_ident(row.get('referencedOwner')),
                               db_ident(row.get('referencedName')))
            if source in self.nodes and target in self.nodes and source != target:
                self._add_rel(source, target, 'DEPENDS_ON',
                              via='DICTIONARY',
                              referencedType=row.get('referencedType', ''),
                              purpose='declared-dependency')
                merged += 1
        return merged
