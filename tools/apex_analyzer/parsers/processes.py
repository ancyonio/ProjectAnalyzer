"""Page process, computation, validation and branch parsing.

These four are grouped because they share the same shape: a component that
carries code, a condition, an optional authorization scheme, and a link back
to the button that fires it.
"""
from __future__ import annotations

from analyzer_core.ids import component_id

from ..constants import (DML_PROCESS_TYPES, PLSQL_PROCESS_TYPES,
                         PLSQL_VALIDATION_TYPES, SQL_VALIDATION_TYPES)
from .plsql_args import ExportCall
from .urls import parse_apex_url, parse_url_items


class ProcessParserMixin:

    # ------------------------------------------------------------------
    def handle_create_page_process(self, call: ExportCall) -> None:
        process = call.number('id')
        page = call.number('flowStepId', self.page_id)
        if process is None or page is None:
            return
        node_id = component_id(self.app_id, page, 'proc', process)
        name = call.text('processName') or f'Process {process}'
        process_type = call.text('processType')
        code = call.text('processSqlClob') or call.text('process')

        self._node(node_id, 'ApexProcess', name, {
            'pageId': page,
            'scope': 'PAGE',
            'processType': process_type,
            'pointCode': call.text('processPointCode') or call.text('processPoint'),
            'executionSequence': call.number('processSequence'),
            'condition': call.text('processWhen'),
            'conditionType': call.text('processWhenType'),
            'authorizationScheme': call.text('securityScheme'),
            'errorMessage': call.text('processErrorMessage'),
            'successMessage': call.text('processSuccessMessage'),
            'hasPlsql': bool(code),
            'targetTable': call.text('attribute01') if
                           process_type.upper() in DML_PROCESS_TYPES else '',
        }, call=call)

        self._register('process', (page, process), node_id)
        page_node = self._lookup('page', page)
        if page_node:
            self._rel(page_node, node_id, 'CONTAINS_PROCESS')

        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))
        button = call.number('processWhenButtonId')
        if button:
            self._defer('triggeredByButton', node_id=node_id, page=page, button=button)

        if code:
            if process_type.upper() in PLSQL_PROCESS_TYPES or not process_type:
                self._plsql_code(node_id, code, 'EXECUTES_PLSQL', 'page process')
            elif code.lstrip().lower().startswith(('select', 'with ', 'insert', 'update',
                                                   'delete', 'merge')):
                self._sql_code(node_id, code, 'EXECUTES_SQL', 'page process')
            else:
                self._plsql_code(node_id, code, 'EXECUTES_PLSQL', 'page process')

        # declarative DML: the process writes to a table without any code
        if process_type.upper() in DML_PROCESS_TYPES:
            table = call.text('attribute01') or call.text('processTable')
            if table:
                self._defer('processDml', node_id=node_id, table=table,
                            owner=call.text('attribute02'), process_type=process_type)
            else:
                self._defer('processDmlRegion', node_id=node_id, page=page,
                            region=call.number('processRegionId') or
                            call.number('regionId'), process_type=process_type)

        self._condition_code(node_id, call.text('processWhenType'),
                             call.text('processWhen'), 'process condition')

    # ------------------------------------------------------------------
    def handle_create_page_computation(self, call: ExportCall) -> None:
        computation = call.number('id')
        page = call.number('flowStepId', self.page_id)
        if computation is None or page is None:
            return
        item = call.text('computationItem')
        node_id = component_id(self.app_id, page, 'comp', computation)
        computation_type = call.text('computationType').upper()

        self._node(node_id, 'ApexComputation', item or f'Computation {computation}', {
            'pageId': page,
            'scope': 'PAGE',
            'itemName': item.upper(),
            'computationType': computation_type,
            'pointCode': call.text('computationPoint'),
            'sequence': call.number('computationSequence'),
            'condition': call.text('computationWhen'),
        }, call=call)
        page_node = self._lookup('page', page)
        if page_node:
            self._rel(page_node, node_id, 'CONTAINS_COMPUTATION')

        expression = call.text('computation')
        if expression:
            if computation_type in ('QUERY', 'SQL_QUERY', 'QUERY_COLON'):
                self._sql_code(node_id, expression, 'EXECUTES_SQL', 'computation')
            elif computation_type in ('FUNCTION_BODY', 'PLSQL_EXPRESSION',
                                      'PLSQL_FUNCTION_BODY'):
                self._plsql_code(node_id, expression, 'EXECUTES_PLSQL', 'computation')
        if item:
            self._defer('setsItem', node_id=node_id, item=item.upper(), page=page)

    # ------------------------------------------------------------------
    def handle_create_page_validation(self, call: ExportCall) -> None:
        validation = call.number('id')
        page = call.number('flowStepId', self.page_id)
        if validation is None or page is None:
            return
        node_id = component_id(self.app_id, page, 'val', validation)
        validation_type = call.text('validationType').upper()
        expression = call.text('validation') or call.text('validationExpression1')

        self._node(node_id, 'ApexValidation', call.text('validationName')
                   or f'Validation {validation}', {
            'pageId': page,
            'validationType': validation_type,
            'sequence': call.number('validationSequence'),
            'errorMessage': call.text('errorMessage'),
            'condition': call.text('validationCondition'),
            'conditionType': call.text('validationConditionType'),
            'authorizationScheme': call.text('securityScheme'),
            'errorDisplayLocation': call.text('errorDisplayLocation'),
        }, call=call)
        page_node = self._lookup('page', page)
        if page_node:
            self._rel(page_node, node_id, 'CONTAINS_VALIDATION')
        self._register('validation', (page, validation), node_id)

        associated = call.number('associatedItem')
        if associated:
            self._defer('validatesItemId', node_id=node_id, page=page, item_id=associated)
        associated_name = call.text('associatedItemName')
        if associated_name:
            self._defer('validatesItem', node_id=node_id, page=page,
                        item=associated_name.upper())

        if expression:
            if validation_type in SQL_VALIDATION_TYPES:
                self._sql_code(node_id, expression, 'EXECUTES_SQL', 'validation')
            elif validation_type in PLSQL_VALIDATION_TYPES:
                self._plsql_code(node_id, expression, 'EXECUTES_PLSQL', 'validation')

        button = call.number('whenButtonPressed')
        if button:
            self._defer('triggeredByButton', node_id=node_id, page=page, button=button)
        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))
        self._defer('buildOption', node_id=node_id, build_option=call.text('buildOption'))

    # ------------------------------------------------------------------
    def handle_create_page_branch(self, call: ExportCall) -> None:
        branch = call.number('id')
        page = call.number('flowStepId', self.page_id)
        if branch is None or page is None:
            return
        node_id = component_id(self.app_id, page, 'br', branch)
        action = call.text('branchAction')
        target = parse_apex_url(action)
        if target is None:
            target = call.number('branchTargetPage')

        self._node(node_id, 'ApexBranch', call.text('branchName') or f'Branch {branch}', {
            'pageId': page,
            'branchType': call.text('branchType'),
            'pointCode': call.text('branchPoint'),
            'sequence': call.number('branchSequence'),
            'condition': call.text('branchCondition'),
            'conditionType': call.text('branchConditionType'),
            'targetPageId': target,
            'target': action,
        }, call=call)
        page_node = self._lookup('page', page)
        if page_node:
            self._rel(page_node, node_id, 'CONTAINS_BRANCH')

        if target is not None:
            self._defer('navigatesTo', node_id=node_id, page=target, via='branch')
        for item in parse_url_items(action):
            self._defer('setsItem', node_id=node_id, item=item, page=target)
        button = call.number('branchWhenButtonId')
        if button:
            self._defer('triggeredByButton', node_id=node_id, page=page, button=button)
        self._condition_code(node_id, call.text('branchConditionType'),
                             call.text('branchCondition'), 'branch condition')
