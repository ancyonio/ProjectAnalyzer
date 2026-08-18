"""Region parsing, including report / interactive report / interactive grid
columns.

Two source shapes matter and both are handled:

* SQL regions — `p_plug_source` is a query, which becomes a `:SqlStatement`;
* declarative regions — `p_query_type => 'TABLE'` names a table directly,
  which becomes `SOURCED_FROM` with no SQL involved. Forms and interactive
  grids are usually of this shape, and a SQL-only parser misses them entirely.
"""
from __future__ import annotations

from analyzer_core.ids import component_id, report_column_id

from ..constants import (PLSQL_CONDITION_TYPES, PLSQL_REGION_SOURCE_TYPES,
                         SQL_CONDITION_TYPES, SQL_REGION_SOURCE_TYPES)
from .plsql_args import ExportCall


class RegionParserMixin:

    def handle_create_page_plug(self, call: ExportCall) -> None:
        region = call.number('id')
        page = call.number('flowStepId', self.page_id)
        if region is None or page is None:
            return
        node_id = component_id(self.app_id, page, 'r', region)
        source_type = call.text('plugSourceType') or call.text('sourceType')
        source = call.text('plugSource') or call.text('source')
        query_type = call.text('queryType').upper()
        table = call.text('queryTable')
        name = call.text('plugName') or call.text('name') or f'Region {region}'

        self._node(node_id, 'ApexRegion', name, {
            'pageId': page,
            'regionId': region,
            'regionType': _region_type(source_type),
            'sourceType': source_type,
            'staticId': call.text('plugStaticId'),
            'displaySequence': call.number('plugDisplaySequence'),
            'displayPoint': call.text('plugDisplayPoint'),
            'parentRegionId': call.number('parentPlugId'),
            'serverSideCondition': call.text('plugDisplayWhenCondition'),
            'conditionType': call.text('plugDisplayConditionType'),
            'authorizationScheme': call.text('plugRequiredRole'),
            'queryType': query_type,
            'queryTable': table,
            'queryWhere': call.text('queryWhere'),
            'noDataFoundMessage': call.text('plugQueryNoDataFound'),
            'hasSql': bool(source) and _is_sql(source_type, source),
        }, call=call)

        page_node = self._lookup('page', page)
        if page_node:
            self._rel(page_node, node_id, 'CONTAINS_REGION')
        parent = call.number('parentPlugId')
        if parent:
            self._defer('subRegion', node_id=node_id, page=page, parent=parent)

        self._register('region', (page, region), node_id)
        self._defer('securedBy', node_id=node_id, scheme=call.text('plugRequiredRole'))
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))

        if source:
            if _is_sql(source_type, source):
                self._sql_code(node_id, source, 'EXECUTES_SQL', 'region source')
            elif source_type.upper() in PLSQL_REGION_SOURCE_TYPES:
                self._plsql_code(node_id, source, 'EXECUTES_PLSQL', 'region source')

        if query_type in ('TABLE', 'TABLE_NAME') and table:
            self._defer('sourcedFrom', node_id=node_id, owner=call.text('queryOwner'),
                        table=table)

        self._condition_code(node_id, call.text('plugDisplayConditionType'),
                             call.text('plugDisplayWhenCondition'), 'region condition')

    # ------------------------------------------------------------------
    def handle_create_report_columns(self, call: ExportCall) -> None:
        self._report_column(call, call.text('columnAlias'), call.text('columnHeading'),
                            call.text('displayAs'), call.number('columnDisplaySequence'))

    def handle_create_worksheet_column(self, call: ExportCall) -> None:
        self._report_column(call, call.text('dbColumnName') or call.text('columnIdentifier'),
                            call.text('columnLabel'), call.text('columnType'),
                            call.number('displayOrder'),
                            lov=call.text('reportLov') or call.text('namedLov'))

    def handle_create_region_column(self, call: ExportCall) -> None:
        """Interactive grid column."""
        self._report_column(call, call.text('name'), call.text('heading'),
                            call.text('itemType') or call.text('displayAs'),
                            call.number('displaySequence'),
                            lov=call.text('lovId') or call.text('namedLov'),
                            source_column=call.text('source'),
                            data_type=call.text('dataType'))

    def _report_column(self, call: ExportCall, alias: str, heading: str,
                       display_as: str, sequence, lov: str = '',
                       source_column: str = '', data_type: str = '') -> None:
        if not alias:
            return
        region = call.number('regionId') or call.number('plugId') or self.current_region_id
        page = self.page_id
        if region is None or page is None:
            return
        node_id = report_column_id(self.app_id, page, region, alias)
        self._node(node_id, 'ApexReportColumn', alias, {
            'pageId': page,
            'columnAlias': alias.upper(),
            'heading': heading,
            'displayType': display_as,
            'displaySequence': sequence,
            'dataType': data_type,
            'sourceColumn': (source_column or alias).upper(),
            'isSortable': call.flag('isSortableAscending') or call.flag('sortable'),
            'lovName': lov,
        }, call=call)
        region_node = self._lookup('region', (page, region))
        if region_node:
            self._rel(region_node, node_id, 'CONTAINS_COLUMN')
        if lov:
            self._defer('usesLov', node_id=node_id, lov=lov)
        self._defer('columnSource', node_id=node_id, page=page, region=region,
                    column=(source_column or alias).upper())

    # `create_worksheet` / `create_interactive_grid` only carry region-level
    # display attributes; the region node already exists, so they are recorded
    # as attributes rather than nodes.
    def handle_create_worksheet(self, call: ExportCall) -> None:
        self._region_attributes(call, 'INTERACTIVE_REPORT')

    def handle_create_interactive_grid(self, call: ExportCall) -> None:
        self._region_attributes(call, 'INTERACTIVE_GRID')

    def _region_attributes(self, call: ExportCall, region_type: str) -> None:
        region = call.number('regionId') or call.number('plugId')
        if region is None or self.page_id is None:
            return
        self.current_region_id = region
        node_id = self._lookup('region', (self.page_id, region))
        if not node_id:
            return
        self._set_property(node_id, 'regionType', region_type)
        max_rows = call.number('maxRowCount')
        if max_rows:
            self._set_property(node_id, 'maxRowCount', max_rows)


def _region_type(source_type: str) -> str:
    mapping = {
        'NATIVE_IR': 'INTERACTIVE_REPORT',
        'NATIVE_IG': 'INTERACTIVE_GRID',
        'NATIVE_SQL_REPORT': 'CLASSIC_REPORT',
        'NATIVE_FORM': 'FORM',
        'NATIVE_DML_FORM': 'FORM',
        'NATIVE_TABFORM': 'TABULAR_FORM',
        'NATIVE_STATIC': 'STATIC_CONTENT',
        'NATIVE_PLSQL': 'PLSQL_DYNAMIC_CONTENT',
        'NATIVE_DYNAMIC_CONTENT': 'PLSQL_DYNAMIC_CONTENT',
        'NATIVE_CHART': 'CHART',
        'NATIVE_CARDS': 'CARDS',
        'NATIVE_TREE': 'TREE',
        'NATIVE_CALENDAR': 'CALENDAR',
        'NATIVE_LIST': 'LIST',
        'NATIVE_BREADCRUMB': 'BREADCRUMB',
        'NATIVE_URL': 'URL',
    }
    key = (source_type or '').upper()
    if key in mapping:
        return mapping[key]
    if key.startswith('PLUGIN_'):
        return 'PLUGIN'
    return key or 'UNKNOWN'


def _is_sql(source_type: str, source: str) -> bool:
    key = (source_type or '').upper()
    if key in SQL_REGION_SOURCE_TYPES:
        return True
    if key in PLSQL_REGION_SOURCE_TYPES:
        return False
    head = (source or '').lstrip().lower()
    return head.startswith(('select', 'with '))
