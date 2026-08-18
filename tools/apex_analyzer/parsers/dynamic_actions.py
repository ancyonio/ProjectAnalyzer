"""Dynamic action parsing.

A dynamic action is an event (`create_page_da_event`) plus an ordered list of
actions (`create_page_da_action`). The code lives in the action's numbered
attributes, and which attribute holds it depends on the action type — see
`constants.DA_CODE_ATTRIBUTES`. Getting this wrong loses a large share of an
application's PL/SQL, because modern APEX applications put a lot of logic
here rather than in page processes.
"""
from __future__ import annotations

from analyzer_core.ids import component_id, da_action_id

from ..constants import DA_CODE_ATTRIBUTES
from .plsql_args import ExportCall


class DynamicActionParserMixin:

    def handle_create_page_da_event(self, call: ExportCall) -> None:
        event = call.number('id')
        page = call.number('flowStepId', self.page_id)
        if event is None or page is None:
            return
        node_id = component_id(self.app_id, page, 'da', event)
        self._node(node_id, 'ApexDynamicAction', call.text('name') or f'DA {event}', {
            'pageId': page,
            'eventName': call.text('bindEventType') or call.text('triggeringEventType'),
            'selectionType': call.text('triggeringElementType'),
            'selectionValue': call.text('triggeringElement'),
            'bindType': call.text('bindType'),
            'sequence': call.number('eventSequence'),
            'condition': call.text('displayWhenCondition'),
            'conditionType': call.text('displayWhenType'),
            'fireOnInit': call.flag('triggeringConditionType') or
                          call.flag('fireOnPageLoad'),
        }, call=call)
        page_node = self._lookup('page', page)
        if page_node:
            self._rel(page_node, node_id, 'CONTAINS_DYNAMIC_ACTION')
        self._register('da', (page, event), node_id)

        element_type = call.text('triggeringElementType').upper()
        element = call.text('triggeringElement')
        if element_type == 'ITEM' and element:
            for item in [part.strip().upper() for part in element.split(',') if part.strip()]:
                self._defer('daTriggerItem', node_id=node_id, page=page, item=item)
        button = call.number('triggeringButtonId')
        if button:
            self._defer('daTriggerButton', node_id=node_id, page=page, button=button)
        region = call.number('triggeringRegionId')
        if region:
            self._defer('daTriggerRegion', node_id=node_id, page=page, region=region)

        self._condition_code(node_id, call.text('displayWhenType'),
                             call.text('displayWhenCondition'), 'dynamic action condition')
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))

    # ------------------------------------------------------------------
    def handle_create_page_da_action(self, call: ExportCall) -> None:
        action = call.number('id')
        event = call.number('eventId')
        page = self.page_id
        if action is None or event is None or page is None:
            return
        node_id = da_action_id(self.app_id, page, event, action)
        action_type = call.text('action').upper()

        code_attribute, code_kind = DA_CODE_ATTRIBUTES.get(action_type, ('', ''))
        code = call.text(code_attribute) if code_attribute else ''

        self._node(node_id, 'ApexDaAction', call.text('name') or action_type or
                   f'Action {action}', {
            'pageId': page,
            'actionType': action_type,
            'sequence': call.number('actionSequence'),
            'eventResult': call.text('eventResult'),
            'affectedElements': call.text('affectedElements'),
            'affectedElementsType': call.text('affectedElementsType'),
            'hasPlsql': bool(code) and code_kind == 'PLSQL',
            'hasJavaScript': bool(code) and code_kind == 'JS',
            'itemsToSubmit': call.text('attribute02'),
            'itemsToReturn': call.text('attribute03'),
        }, call=call)

        da_node = self._lookup('da', (page, event))
        if da_node:
            self._rel(da_node, node_id, 'CONTAINS_ACTION')

        if code:
            if code_kind == 'PLSQL':
                self._plsql_code(node_id, code, 'EXECUTES_PLSQL', 'dynamic action')
            elif code_kind == 'JS':
                self._js_code(node_id, code)
            elif code_kind == 'SQL':
                self._sql_code(node_id, code, 'EXECUTES_SQL', 'dynamic action')

        # NATIVE_SET_VALUE carries its source in one of several attributes
        if action_type == 'NATIVE_SET_VALUE':
            set_type = call.text('attribute01').upper()
            expression = (call.text('attribute06') or call.text('attribute07')
                          or call.text('attribute08') or call.text('attribute09'))
            if expression:
                if set_type in ('SQL_STATEMENT', 'SQL'):
                    self._sql_code(node_id, expression, 'EXECUTES_SQL', 'set value')
                elif set_type in ('PLSQL_EXPRESSION', 'FUNCTION_BODY', 'PLSQL'):
                    self._plsql_code(node_id, expression, 'EXECUTES_PLSQL', 'set value')
            for item in _split_items(call.text('affectedElements')):
                self._defer('setsItem', node_id=node_id, item=item, page=page)

        for item in _split_items(call.text('attribute02')):
            self._defer('daSubmitsItem', node_id=node_id, page=page, item=item)
        for item in _split_items(call.text('attribute03')):
            self._defer('setsItem', node_id=node_id, item=item, page=page)

        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))


def _split_items(value: str):
    if not value:
        return []
    return [part.strip().upper().lstrip('#').rstrip('#')
            for part in str(value).replace(';', ',').split(',') if part.strip()]
