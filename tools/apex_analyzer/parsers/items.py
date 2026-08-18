"""Page item parsing.

Items are where the graph gets its column-level lineage on form pages: an
item whose source type is `DB_COLUMN` names the column directly, so
`page -> item -> column` works even though no SQL exists anywhere on the page.
"""
from __future__ import annotations

from analyzer_core.ids import component_id

from ..constants import ITEM_PROTECTION_LEVELS
from .plsql_args import ExportCall


class ItemParserMixin:

    def handle_create_page_item(self, call: ExportCall) -> None:
        name = call.text('name')
        page = call.number('flowStepId', self.page_id)
        if not name or page is None:
            return
        node_id = component_id(self.app_id, page, 'i', name.upper())
        region = call.number('itemPlugId')
        source_type = call.text('sourceType')
        source = call.text('source')
        protection = call.text('protectionLevel')

        self._node(node_id, 'ApexItem', name, {
            'pageId': page,
            'itemName': name.upper(),
            'scope': 'PAGE',
            'label': call.text('prompt'),
            'itemType': call.text('displayAs'),
            'sourceType': source_type,
            'sourceValue': source,
            'defaultType': call.text('itemDefaultType'),
            'defaultValue': call.text('itemDefault'),
            'displaySequence': call.number('itemSequence'),
            'isRequired': call.flag('isRequired') or call.flag('itemRequired'),
            'sessionStateProtection': ITEM_PROTECTION_LEVELS.get(
                protection.upper(), protection.upper()),
            'lovName': call.text('namedLov') or call.text('lov'),
            'readOnlyCondition': call.text('readOnlyWhen'),
            'authorizationScheme': call.text('securityScheme'),
            'dataType': call.text('dataType'),
        }, call=call)

        self._register('item', (page, name.upper()), node_id)
        self._register('itemId', call.number('id'), node_id)
        region_node = self._lookup('region', (page, region)) if region else None
        page_node = self._lookup('page', page)
        if region_node:
            self._rel(region_node, node_id, 'CONTAINS_ITEM')
        elif page_node:
            self._rel(page_node, node_id, 'CONTAINS_ITEM')

        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))

        lov = call.text('namedLov') or call.text('lov')
        if lov:
            self._defer('usesLov', node_id=node_id, lov=lov)
        lov_query = call.text('lovDefinition') or (
            call.text('lov') if (call.text('lov') or '').lstrip().lower().startswith('select')
            else '')
        if lov_query:
            self._sql_code(node_id, lov_query, 'EXECUTES_SQL', 'inline LOV')

        # column lineage: an item sourced from a database column
        if source and source_type.upper() in ('DB_COLUMN', 'DATABASE_COLUMN', ''):
            self._defer('itemColumn', node_id=node_id, page=page, region=region,
                        column=source.upper())

        default_type = call.text('itemDefaultType').upper()
        default_value = call.text('itemDefault')
        if default_value:
            if default_type in ('SQL_QUERY', 'QUERY'):
                self._sql_code(node_id, default_value, 'EXECUTES_SQL', 'item default')
            elif default_type in ('PLSQL_EXPRESSION', 'PLSQL_FUNCTION_BODY',
                                  'FUNCTION_BODY'):
                self._plsql_code(node_id, default_value, 'EXECUTES_PLSQL', 'item default')

        self._condition_code(node_id, call.text('displayWhenType'),
                             call.text('displayWhen'), 'item condition')
