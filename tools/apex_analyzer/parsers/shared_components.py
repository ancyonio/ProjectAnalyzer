"""Shared component parsing: lists of values, navigation lists, web sources,
automations, plugins and email templates.

Lists of values are the highest-value item here. A dynamic LOV is a query
that runs once per page — or, when attached to a report column, once per row —
so it belongs in the data-access graph exactly like a region query does.
"""
from __future__ import annotations

from analyzer_core.ids import shared_id

from .plsql_args import ExportCall
from .urls import parse_apex_url


class SharedComponentParserMixin:

    # ── lists of values ───────────────────────────────────────────────
    def handle_create_list_of_values(self, call: ExportCall) -> None:
        name = call.text('lovName') or call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'lov', name)
        query = call.text('lovQuery')
        lov_type = (call.text('lovType') or
                    ('STATIC' if not query else 'DYNAMIC')).upper()
        self._node(node_id, 'ApexLov', name, {
            'lovType': lov_type,
            'queryType': call.text('queryType'),
            'queryTable': call.text('queryTable'),
            'hasSql': bool(query) and query.lstrip().lower().startswith(('select', 'with')),
            'entryCount': 0,
        }, call=call)
        self._register('lov', name.upper(), node_id)
        self._register('lovId', call.number('id'), node_id)

        if query and query.lstrip().lower().startswith(('select', 'with')):
            self._sql_code(node_id, query, 'EXECUTES_SQL', 'list of values')
        elif call.text('queryTable'):
            self._defer('sourcedFrom', node_id=node_id, owner=call.text('queryOwner'),
                        table=call.text('queryTable'))

    def handle_create_static_lov_data(self, call: ExportCall) -> None:
        lov_node = self._lookup('lovId', call.number('lovId'))
        if lov_node:
            self._increment_property(lov_node, 'entryCount')

    # ── navigation lists ──────────────────────────────────────────────
    def handle_create_list(self, call: ExportCall) -> None:
        name = call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'list', name)
        self._node(node_id, 'ApexList', name, {
            'listType': call.text('listStatus') or call.text('listType'),
        }, call=call)
        self._register('list', name.upper(), node_id)
        self._register('listId', call.number('id'), node_id)
        self.current_list_id = call.number('id')

    def handle_create_list_item(self, call: ExportCall) -> None:
        list_node = self._lookup('listId', call.number('listId') or self.current_list_id)
        label = call.text('listItemLinkText') or call.text('name') or 'entry'
        entry_id = call.number('id')
        node_id = shared_id(self.app_id, 'listentry', entry_id or label)
        target = call.text('listItemLinkTarget')
        target_page = parse_apex_url(target)
        self._node(node_id, 'ApexListEntry', label, {
            'target': target,
            'targetPageId': target_page,
            'displaySequence': call.number('listItemDisplaySequence'),
            'condition': call.text('listItemDispCondition'),
            'conditionType': call.text('listItemDispConditionType'),
            'authorizationScheme': call.text('listItemCurrentForPages') and '' or
                                   call.text('securityScheme'),
        }, call=call)
        if list_node:
            self._rel(list_node, node_id, 'CONTAINS_ITEM')
        if target_page is not None:
            self._defer('navigatesTo', node_id=node_id, page=target_page, via='list entry')
        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))

    def handle_create_nav_bar_list_item(self, call: ExportCall) -> None:
        label = call.text('navBarEntryLabel') or call.text('name') or 'nav entry'
        node_id = shared_id(self.app_id, 'nav', call.number('id') or label)
        target = call.text('navBarEntryTarget') or call.text('target')
        target_page = parse_apex_url(target)
        self._node(node_id, 'ApexNavigation', label, {
            'navType': 'NAV_BAR',
            'target': target,
            'targetPageId': target_page,
            'displaySequence': call.number('navBarEntrySequence'),
        }, call=call)
        if target_page is not None:
            self._defer('navigatesTo', node_id=node_id, page=target_page, via='navigation bar')

    # ── REST data sources ─────────────────────────────────────────────
    def handle_create_web_source_module(self, call: ExportCall) -> None:
        name = call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'ws', name)
        self._node(node_id, 'ApexWebSource', name, {
            'staticId': call.text('staticId'),
            'sourceType': call.text('webSourceType'),
            'baseUrl': call.text('urlPathPrefix') or call.text('remoteServerId'),
            'authenticationType': call.text('credentialId') and 'CREDENTIAL' or 'NONE',
        }, call=call)
        self._register('webSource', name.upper(), node_id)
        self._register('webSourceId', call.number('id'), node_id)
        self.current_web_source_id = call.number('id')

    def handle_create_web_source_operation(self, call: ExportCall) -> None:
        parent = self._lookup('webSourceId',
                              call.number('webSrcModuleId') or self.current_web_source_id)
        name = call.text('name') or call.text('databaseOperation') or 'operation'
        node_id = shared_id(self.app_id, 'wsop', call.number('id') or name)
        self._node(node_id, 'ApexWebSourceOperation', name, {
            'httpMethod': call.text('httpMethod'),
            'urlPattern': call.text('urlPattern'),
            'databaseOperation': call.text('databaseOperation'),
        }, call=call)
        if parent:
            self._rel(parent, node_id, 'CONTAINS_ITEM')

    # ── automations, plugins, templates ───────────────────────────────
    def handle_create_automation(self, call: ExportCall) -> None:
        name = call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'automation', name)
        self._node(node_id, 'ApexAutomation', name, {
            'scheduleType': call.text('scheduleType'),
            'actionType': call.text('actionsInitiation'),
            'status': call.text('status'),
            'queryType': call.text('queryType'),
        }, call=call)
        query = call.text('querySqlQuery') or call.text('query')
        if query:
            self._sql_code(node_id, query, 'RUNS', 'automation query')
        self._register('automation', name.upper(), node_id)
        self._register('automationId', call.number('id'), node_id)

    def handle_create_automation_action(self, call: ExportCall) -> None:
        parent = self._lookup('automationId', call.number('automationId'))
        code = call.text('plsqlCode') or call.attribute(1)
        if parent and code:
            self._plsql_code(parent, code, 'RUNS', 'automation action')

    def handle_create_plugin(self, call: ExportCall) -> None:
        name = call.text('name') or call.text('displayName')
        if not name:
            return
        node_id = shared_id(self.app_id, 'plugin', name)
        code = call.text('plsqlCode')
        self._node(node_id, 'ApexPlugin', name, {
            'pluginType': call.text('pluginType'),
            'isStandard': call.flag('standardAttributes') or False,
            'hasPlsql': bool(code),
        }, call=call)
        if code:
            self._plsql_code(node_id, code, 'EXECUTES_PLSQL', 'plugin')

    def handle_create_email_template(self, call: ExportCall) -> None:
        name = call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'email', name)
        self._node(node_id, 'ApexEmailTemplate', name, {
            'staticId': call.text('staticId'),
        }, call=call)
