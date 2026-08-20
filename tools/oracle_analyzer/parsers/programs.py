"""PL/SQL program structure: packages, their two halves, and program units.

The spec and the body are separate nodes because they have different change
semantics, and that difference is the point of the graph: a change to a
`PackageSpec` breaks every caller, while the same change to a `PackageBody` is
invisible outside the package. Collapsing them makes the most useful impact
question unanswerable.

Every unit's source is run through the shared PL/SQL analyser, which yields the
SQL it embeds, the calls it makes and its transaction and error behaviour.
Nothing is bound to a target here -- an object may not have been parsed yet --
so calls and table references are recorded for `crossref` to resolve.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from analyzer_core.ids import object_id, plsql_id, sql_id, unit_id
from analyzer_core.model import GraphNode
from analyzer_core.plsql import (analyse_plsql, extract_unit_bodies,
                                 normalise_plsql, normalise_sql)

from ..constants import COMPLEXITY_WEIGHTS, tier_for

logger = logging.getLogger('oracle_analyzer')

_BRANCH_TOKENS = (' if ', ' elsif ', ' case ')
_LOOP_TOKENS = (' loop ', ' while ', ' for ')

# Positions where a type name can legally appear: a function's return, a
# collection's element type, a cast target, a constructor call, and the type
# half of a parameter or variable declaration.
#
# Deliberately liberal, on the same principle as the SQL column binder: a
# candidate that is not a `DbType` in scope is dropped by `crossref`, so
# over-collecting here costs nothing while under-collecting loses the
# dependency. `%TYPE` and `%ROWTYPE` anchors are excluded by the lookahead --
# those reference a column or a table, not a type.
_TYPE_POSITION_RE = re.compile(
    r'\bRETURN\s+([A-Za-z][\w$#]*(?:\.[\w$#]+)?)'
    r'|\bTABLE\s+OF\s+([A-Za-z][\w$#]*(?:\.[\w$#]+)?)'
    r'|\bREF\s+([A-Za-z][\w$#]*(?:\.[\w$#]+)?)'
    r'|\bAS\s+([A-Za-z][\w$#]*(?:\.[\w$#]+)?)\s*\)'
    r'|\bNEW\s+([A-Za-z][\w$#]*(?:\.[\w$#]+)?)\s*\('
    r'|\b[\w$#]+\s+(?:IN\s+OUT\s+NOCOPY|IN\s+OUT|OUT\s+NOCOPY|IN|OUT)\s+'
    r'([A-Za-z][\w$#]*(?:\.[\w$#]+)?)\s*(?=[;,)]|:=|\bDEFAULT\b)'
    r'|\b[\w$#]+\s+([A-Za-z][\w$#]*(?:\.[\w$#]+)?)\s*(?=[;,)]|:=|\bDEFAULT\b)',
    re.IGNORECASE)

# Scalar and built-in types are not objects in the schema, so they would never
# resolve. Excluding them keeps the deferred queue proportional to the code.
_BUILTIN_TYPES = frozenset({
    'NUMBER', 'VARCHAR2', 'VARCHAR', 'CHAR', 'NCHAR', 'NVARCHAR2', 'DATE',
    'TIMESTAMP', 'CLOB', 'BLOB', 'NCLOB', 'BFILE', 'RAW', 'LONG', 'INTEGER',
    'INT', 'SMALLINT', 'DECIMAL', 'NUMERIC', 'FLOAT', 'REAL', 'DOUBLE',
    'BINARY_INTEGER', 'PLS_INTEGER', 'BINARY_FLOAT', 'BINARY_DOUBLE',
    'BOOLEAN', 'ROWID', 'UROWID', 'INTERVAL', 'XMLTYPE', 'SYS_REFCURSOR',
    'REFCURSOR', 'RECORD', 'CURSOR', 'EXCEPTION', 'CONSTANT', 'DEFAULT',
    'NULL', 'IS', 'AS', 'BEGIN', 'END', 'THEN', 'ELSE', 'LOOP', 'DECLARE',
    'PROCEDURE', 'FUNCTION', 'PRAGMA', 'RETURN', 'SELECT', 'INTO', 'FROM',
    'WHERE', 'VALUES', 'SET', 'AND', 'OR', 'NOT', 'IN', 'OUT', 'NOCOPY',
})


class ProgramParserMixin:
    """Builds packages, package halves and program units."""

    def _parse_programs(self) -> int:
        units = 0
        # Specs first: the contract should exist before the implementation
        # updates it, so the result does not depend on file name order.
        self.program_objects.sort(
            key=lambda pair: (pair[1].kind != 'PACKAGE', bool(pair[1].body),
                              pair[0].rel_path))
        for source, obj in self.program_objects:
            if obj.kind == 'PACKAGE':
                units += self._create_package(source, obj)
            elif obj.kind == 'UNIT':
                units += self._create_standalone_unit(source, obj)

        self.stats['program_units'] = units
        logger.info('  %d program unit(s) across %d package half/halves',
                    units, self.stats.get('package_halves', 0))
        return units

    # ── packages ──────────────────────────────────────────────────────
    def _create_package(self, source, obj) -> int:
        owner = obj.owner or self.default_owner
        is_body = bool(obj.body)
        package_node = object_id(owner, obj.name)
        schema_node = self._ensure_schema(owner)

        if package_node not in self.nodes:
            self._add_node(GraphNode(package_node, 'DbPackage', obj.name, {
                'owner': owner,
                'objectType': 'PACKAGE',
                'origin': 'ddl',
            }))
            self._add_rel(schema_node, package_node, 'OWNS',
                          purpose='schema-ownership')

        half_label = 'PackageBody' if is_body else 'PackageSpec'
        half_node = f'{package_node}#{"body" if is_body else "spec"}'
        source_text = obj.body if is_body else ''

        if half_node in self.nodes:
            return 0
        self.stats['package_halves'] += 1

        half_loc = (source_text or '').count('\n') + 1 if source_text else 0
        self._add_node(GraphNode(half_node, half_label, obj.name, {
            'owner': owner,
            'packageName': obj.name,
            'filePath': source.rel_path,
            'lineStart': obj.source_line,
            'lineEnd': obj.source_line_end or (obj.source_line
                                               + max(0, half_loc - 1)),
            'language': 'PLSQL',
            'loc': half_loc,
            'sourceHash': source.source_hash,
            'origin': 'ddl',
        }))
        self._add_rel(package_node, half_node,
                      'HAS_BODY' if is_body else 'HAS_SPEC',
                      purpose='package-structure')
        self._add_rel(source.node_id, half_node, 'DEFINES',
                      purpose='source-definition')
        source.objects.append(half_node)

        if is_body:
            return self._units_from_body(source, owner, obj.name, half_node,
                                         obj.body, obj.source_line)
        return self._units_from_spec(owner, obj.name, half_node, obj.units)

    # ------------------------------------------------------------------
    def _units_from_spec(self, owner: str, package: str, spec_node: str,
                         declared: List[Tuple[str, str]]) -> int:
        """Declared units in a spec: the published contract, no body to analyse."""
        seen: Counter = Counter()
        created = 0
        for kind, name in declared:
            seen[name] += 1
            overload = seen[name] if seen[name] > 1 else None
            node_id = unit_id(owner, package, name, overload)
            if node_id in self.nodes:
                # `customer_pkg.pkb` sorts before `customer_pkg.pks`, so the
                # body is often parsed first. The spec still has to publish the
                # unit -- skipping here left every implemented public unit
                # looking private, and therefore dead.
                self.nodes[node_id].properties['isPublished'] = True
                self._add_rel(spec_node, node_id, 'HAS_UNIT',
                              purpose='package-membership')
                continue
            self._add_node(GraphNode(node_id, 'DbProgramUnit', name, {
                'owner': owner,
                'packageName': package,
                'unitType': kind,
                'overload': overload or 0,
                'isStandalone': False,
                'declaredOnly': True,
                # The spec is what makes a unit callable from outside. The body
                # pass overwrites `declaredOnly`, so publication is recorded
                # separately or every implemented unit stops being an entry point.
                'isPublished': True,
                'origin': 'ddl',
            }))
            self._add_rel(spec_node, node_id, 'HAS_UNIT',
                          purpose='package-membership')
            created += 1
        return created

    # ------------------------------------------------------------------
    def _units_from_body(self, source, owner: str, package: str, body_node: str,
                         body: str, base_line: int) -> int:
        seen: Counter = Counter()
        created = 0
        for kind, name, unit_source, offset in extract_unit_bodies(body):
            seen[name] += 1
            overload = seen[name] if seen[name] > 1 else None
            node_id = unit_id(owner, package, name, overload)
            # `offset` is the unit's first line within the body. Without it
            # every unit in a package reports the package's own start line,
            # which points a reader at the wrong end of the file.
            self._create_unit(source, node_id, owner, package, kind, name,
                              unit_source, base_line + offset, overload,
                              standalone=False, parent=body_node)
            created += 1
        return created

    # ── standalone procedures and functions ───────────────────────────
    def _create_standalone_unit(self, source, obj) -> int:
        owner = obj.owner or self.default_owner
        kind = obj.units[0][0] if obj.units else 'PROCEDURE'
        node_id = unit_id(owner, None, obj.name)
        if node_id in self.nodes:
            return 0
        schema_node = self._ensure_schema(owner)
        self._create_unit(source, node_id, owner, '', kind, obj.name,
                          obj.body, obj.source_line, None,
                          standalone=True, parent=schema_node)
        return 1

    # ── the shared unit builder ───────────────────────────────────────
    def _create_unit(self, source, node_id: str, owner: str, package: str,
                     kind: str, name: str, unit_source: str, base_line: int,
                     overload: Optional[int], standalone: bool,
                     parent: str) -> None:
        analysis = analyse_plsql(unit_source or '')
        loc = (unit_source or '').count('\n') + 1

        lowered = f' {normalise_plsql(unit_source or "")} '
        branch_count = sum(lowered.count(token) for token in _BRANCH_TOKENS)
        loop_count = sum(lowered.count(token) for token in _LOOP_TOKENS)
        complexity = (
            loc * COMPLEXITY_WEIGHTS['loc']
            + len(analysis.statements) * COMPLEXITY_WEIGHTS['statementCount']
            + analysis.call_count * COMPLEXITY_WEIGHTS['callCount']
            + branch_count * COMPLEXITY_WEIGHTS['branchCount']
            + loop_count * COMPLEXITY_WEIGHTS['loopCount']
            + (COMPLEXITY_WEIGHTS['dynamicSql'] if analysis.has_dynamic_sql else 0.0)
        )

        properties = {
            'owner': owner,
            'packageName': package,
            'unitType': kind,
            'overload': overload or 0,
            'isStandalone': standalone,
            'declaredOnly': False,
            'filePath': source.rel_path,
            'lineStart': base_line,
            'lineEnd': base_line + max(0, loc - 1),
            'language': 'PLSQL',
            'loc': loc,
            'sourceHash': self._hash(unit_source or ''),
            'statementCount': len(analysis.statements),
            'callCount': analysis.call_count,
            'branchCount': branch_count,
            'loopCount': loop_count,
            'complexity': round(complexity, 1),
            'tier': tier_for(complexity),
            'hasExceptionHandler': analysis.has_exception_handler,
            'hasWhenOthersNull': analysis.has_when_others_null,
            'hasCommit': analysis.has_commit,
            'hasDynamicSql': analysis.has_dynamic_sql,
            'parseStatus': analysis.parse_status,
            'origin': 'ddl',
        }

        if node_id in self.nodes:
            # A spec declared it; the body now supplies the implementation.
            self.nodes[node_id].properties.update(properties)
        else:
            self._add_node(GraphNode(node_id, 'DbProgramUnit', name, properties))
        rel = 'HAS_UNIT' if not standalone else 'OWNS'
        self._add_rel(parent, node_id, rel,
                      purpose='package-membership' if not standalone
                      else 'schema-ownership')
        if standalone:
            self._add_rel(source.node_id, node_id, 'DEFINES',
                          purpose='source-definition')
            source.objects.append(node_id)

        self._collect_type_refs(node_id, owner, unit_source or '')
        self._attach_code(node_id, owner, analysis, source, unit_source or '')

    # ── SQL and PL/SQL code nodes ─────────────────────────────────────
    def _attach_code(self, owner_node: str, owner: str, analysis,
                     source, text: str) -> None:
        """Materialise the SQL a unit runs and record what still needs binding."""
        if analysis.has_dynamic_sql:
            self.dynamic_sql_sites.append((owner_node, source.rel_path))

        for statement in analysis.statements:
            normalised = normalise_sql(statement.text)
            if not normalised:
                continue
            statement_node = sql_id(normalised)
            if statement_node not in self.nodes:
                properties = dict(statement.properties())
                properties.update({
                    'text': self._truncate(statement.text),
                    'normalised': self._truncate(normalised, 2000),
                    'hasNoWhere': (statement.verb in ('UPDATE', 'DELETE')
                                   and ' where ' not in f' {normalised} '),
                    'language': 'SQL',
                    'origin': 'ddl',
                })
                self._add_node(GraphNode(statement_node, 'SqlStatement',
                                         f'{statement.verb or "SQL"} '
                                         f'{statement_node.split(":", 1)[1][:8]}',
                                         properties))
            self._add_rel(owner_node, statement_node, 'EXECUTES_SQL',
                          purpose='embedded-sql')

            for table in statement.tables:
                self.deferred_access.append(
                    (statement_node, table.owner or owner, table.name,
                     table.access, table.db_link))
            for seq_owner, seq_name in statement.sequences:
                self.deferred_sequences.append(
                    (owner_node, seq_owner or owner, seq_name))
            self._defer_statement_detail(statement_node, owner, statement)

        for package, name in analysis.calls:
            self.deferred_calls.append((owner_node, owner, package, name))

        if text.strip() and not analysis.statements and analysis.call_count == 0:
            return
        block_node = plsql_id(normalise_plsql(text))
        if block_node not in self.nodes:
            properties = dict(analysis.properties())
            properties['text'] = self._truncate(text)
            properties['language'] = 'PLSQL'
            properties['origin'] = 'ddl'
            self._add_node(GraphNode(block_node, 'PlsqlBlock',
                                     f'PL/SQL {block_node.split(":", 1)[1][:8]}',
                                     properties))
        self._add_rel(owner_node, block_node, 'EXECUTES_PLSQL',
                      purpose='unit-body')

    # ── deferred detail ───────────────────────────────────────────────
    def _defer_statement_detail(self, statement_node: str, owner: str,
                                statement) -> None:
        """Column references and join partners, for `crossref` to bind.

        Columns are recorded per statement rather than per unit because that is
        the granularity at which the reference actually exists: two units
        running the same query converge on one `SqlStatement`, and the columns
        belong to the query, not to either caller.
        """
        if statement.columns:
            # One entry per statement, not per column: the alias map and the
            # table list are properties of the query, and copying them beside
            # every column candidate is the same data many times over.
            self.deferred_columns.append(
                (statement_node, owner, tuple(statement.columns),
                 dict(statement.alias_map),
                 tuple((t.owner, t.name) for t in statement.tables)))

        # A join only exists between two tables, so a single-table statement
        # has none. Recording one anyway would make every read look like a join.
        distinct = {(t.owner, t.name) for t in statement.tables}
        if len(distinct) > 1:
            for table_owner, table_name in sorted(distinct):
                self.deferred_joins.append(
                    (statement_node, table_owner or owner, table_name))

    def _collect_type_refs(self, source_node: str, owner: str,
                           text: str) -> None:
        """Candidate user-defined type names used by a unit or trigger body."""
        if not text:
            return
        seen: Set[str] = set()
        for match in _TYPE_POSITION_RE.finditer(text):
            token = next((group for group in match.groups() if group), '')
            token = token.strip().strip('"').upper()
            if not token or token in seen:
                continue
            bare = token.rsplit('.', 1)[-1]
            if bare in _BUILTIN_TYPES or token in _BUILTIN_TYPES:
                continue
            seen.add(token)
            type_owner, _, type_name = token.rpartition('.')
            self.deferred_types.append(
                (source_node, type_owner or owner, type_name))
