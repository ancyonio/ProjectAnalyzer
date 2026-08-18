"""Button parsing.

A button matters to the graph for two reasons: it is what a user presses to
reach a process (`TRIGGERS`, resolved in `crossref` from
`p_process_when_button_id`), and its redirect target is half the page
navigation graph.
"""
from __future__ import annotations

from analyzer_core.ids import component_id

from .plsql_args import ExportCall
from .urls import parse_apex_url


class ButtonParserMixin:

    def handle_create_page_button(self, call: ExportCall) -> None:
        button = call.number('id')
        page = call.number('flowStepId', self.page_id)
        if button is None or page is None:
            return
        name = call.text('buttonName') or f'Button {button}'
        node_id = component_id(self.app_id, page, 'b', button)
        action = call.text('buttonAction')
        redirect = call.text('buttonRedirectUrl')

        self._node(node_id, 'ApexButton', name, {
            'pageId': page,
            'buttonName': name.upper(),
            'label': call.text('buttonImageAlt') or call.text('label'),
            'action': action,
            'target': redirect,
            'requestValue': call.text('request') or name.upper(),
            'position': call.text('buttonPosition'),
            'displaySequence': call.number('buttonSequence'),
            'condition': call.text('buttonCondition'),
            'conditionType': call.text('buttonConditionType'),
            'authorizationScheme': call.text('securityScheme'),
            'databaseAction': call.text('databaseAction'),
            'executesValidations': call.flag('buttonExecuteValidations'),
            'isHot': call.flag('buttonIsHot'),
        }, call=call)

        self._register('button', (page, button), node_id)
        region = call.number('buttonPlugId')
        region_node = self._lookup('region', (page, region)) if region else None
        page_node = self._lookup('page', page)
        if region_node:
            self._rel(region_node, node_id, 'CONTAINS_BUTTON')
        elif page_node:
            self._rel(page_node, node_id, 'CONTAINS_BUTTON')

        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))

        if action.upper() == 'SUBMIT' and page_node:
            self._rel(node_id, page_node, 'SUBMITS_TO')
        target_page = parse_apex_url(redirect)
        if target_page is not None:
            self._defer('navigatesTo', node_id=node_id, page=target_page,
                        via='button redirect')

        self._condition_code(node_id, call.text('buttonConditionType'),
                             call.text('buttonCondition'), 'button condition')
