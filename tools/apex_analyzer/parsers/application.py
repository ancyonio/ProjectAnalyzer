"""Application-level components: the flow itself, build options,
authentication, authorization schemes, application items, processes and
computations.

Handlers are named `handle_<export procedure>`; the analyzer builds its
dispatch table by reflection, so adding support for a new export procedure is
one method and nothing else.
"""
from __future__ import annotations

from analyzer_core.ids import app_id, shared_id

from ..constants import (PLSQL_AUTH_TYPES, PLSQL_CONDITION_TYPES,
                         SQL_AUTH_TYPES, SQL_CONDITION_TYPES)
from .plsql_args import ExportCall


class ApplicationParserMixin:
    """Parses `create_flow` and the application-scoped shared components."""

    # ------------------------------------------------------------------
    def handle_component_begin(self, call: ExportCall) -> None:
        """`component_begin` carries the defaults every later call inherits."""
        application = call.number('defaultApplicationId')
        if application is not None:
            self.app_id = application
        owner = call.text('defaultOwner')
        if owner and not self.parsing_schema:
            self.parsing_schema = owner.upper()
        version = call.text('versionYyyyMmDd')
        if version:
            self.export_meta.setdefault('exportVersion', version)
        release = call.text('release')
        if release:
            self.export_meta.setdefault('apexVersion', release)
        workspace = call.number('defaultWorkspaceId')
        if workspace:
            self.export_meta.setdefault('workspaceId', workspace)

    # ------------------------------------------------------------------
    def handle_create_flow(self, call: ExportCall) -> None:
        application = call.number('id') or self.app_id
        if application is None:
            return
        self.app_id = application
        owner = call.text('owner') or self.parsing_schema
        if owner:
            self.parsing_schema = owner.upper()

        node_id = app_id(application)
        self._node(node_id, 'ApexApplication', call.text('name', f'Application {application}'),
                   {
                       'applicationId': application,
                       'alias': call.text('alias'),
                       'parsingSchema': self.parsing_schema,
                       'apexVersion': call.text('flowVersion') or
                                      self.export_meta.get('apexVersion', ''),
                       'compatibilityMode': call.text('compatibilityMode'),
                       'friendlyUrls': call.text('friendlyUrl') or call.text('friendlyUrls'),
                       'authenticationScheme': call.text('authentication'),
                       'homeLink': call.text('homeLink'),
                       'loginUrl': call.text('loginUrl'),
                       'logoutUrl': call.text('logoutUrl'),
                       'themeId': call.number('flowTheme') or call.number('themeId'),
                       'checksumSalt': 'set' if call.text('checksumSalt') else '',
                   }, call=call)
        self.application_node = node_id

        workspace = self.export_meta.get('workspaceId')
        if workspace:
            workspace_node = f'ws:{workspace}'
            self._node(workspace_node, 'ApexWorkspace', str(workspace),
                       {'workspaceId': workspace, 'parsingSchema': self.parsing_schema},
                       call=call)
            self._rel(node_id, workspace_node, 'BELONGS_TO')

    # ------------------------------------------------------------------
    def handle_create_build_option(self, call: ExportCall) -> None:
        name = call.text('buildOptionName') or call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'bo', name)
        self._node(node_id, 'ApexBuildOption', name, {
            'status': call.text('buildOptionStatus', 'INCLUDE'),
            'defaultOnExport': call.flag('onUpgradeKeepStatus'),
        }, call=call)
        self._register('buildOption', name, node_id)
        self._register('buildOptionId', call.number('id'), node_id)

    def handle_create_authentication(self, call: ExportCall) -> None:
        name = call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'authn', name)
        self._node(node_id, 'ApexAuthentication', name, {
            'schemeType': call.text('schemeType'),
            'isCurrent': call.flag('isCurrent', ('Y', 'YES', 'TRUE')),
        }, call=call)
        if self.application_node:
            self._rel(self.application_node, node_id, 'AUTHENTICATED_BY')
        code = call.attribute(1)
        if code and 'begin' in code.lower():
            self._plsql_code(node_id, code, 'EXECUTES_PLSQL', 'authentication')

    def handle_create_security_scheme(self, call: ExportCall) -> None:
        """Authorization scheme (the export calls it a security scheme)."""
        name = call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'auth', name)
        scheme_type = call.text('schemeType')
        code = call.attribute(1) or call.text('attribute01')
        self._node(node_id, 'ApexAuthorization', name, {
            'schemeType': scheme_type,
            'evaluationPoint': call.text('caching'),
            'errorMessage': call.text('errorMessage'),
            'hasSql': bool(code) and scheme_type.upper() in SQL_AUTH_TYPES,
            'hasPlsql': bool(code) and scheme_type.upper() in PLSQL_AUTH_TYPES,
        }, call=call)
        self._register('authorization', name, node_id)
        self._register('authorizationId', call.number('id'), node_id)
        if code:
            if scheme_type.upper() in SQL_AUTH_TYPES:
                self._sql_code(node_id, code, 'EXECUTES_SQL', 'authorization')
            elif scheme_type.upper() in PLSQL_AUTH_TYPES:
                self._plsql_code(node_id, code, 'EXECUTES_PLSQL', 'authorization')

    # ------------------------------------------------------------------
    def handle_create_flow_item(self, call: ExportCall) -> None:
        """Application item — session state that survives between pages."""
        name = call.text('name')
        if not name:
            return
        node_id = shared_id(self.app_id, 'item', name)
        self._node(node_id, 'ApexItem', name, {
            'itemName': name.upper(),
            'scope': 'APPLICATION',
            'itemType': 'APPLICATION_ITEM',
            'sessionStateProtection': call.text('protectionLevel'),
        }, call=call)
        self._register('appItem', name.upper(), node_id)
        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))

    def handle_create_flow_process(self, call: ExportCall) -> None:
        name = call.text('processName') or call.text('name')
        process_id = call.number('id')
        if not name:
            return
        node_id = shared_id(self.app_id, 'proc', process_id or name)
        code = call.text('processSqlClob') or call.text('process')
        self._node(node_id, 'ApexProcess', name, {
            'scope': 'APPLICATION',
            'processType': call.text('processType'),
            'pointCode': call.text('processPointCode') or call.text('processPoint'),
            'executionSequence': call.number('processSequence'),
            'condition': call.text('processWhen'),
            'conditionType': call.text('processWhenType'),
            'hasPlsql': bool(code),
        }, call=call)
        self._register('process', process_id, node_id)
        if code:
            self._plsql_code(node_id, code, 'EXECUTES_PLSQL', 'application process')
        self._defer('securedBy', node_id=node_id, scheme=call.text('securityScheme'))
        self._defer('buildOption', node_id=node_id,
                    build_option=call.text('processBuildOption') or call.text('buildOption'))

    def handle_create_flow_computation(self, call: ExportCall) -> None:
        item = call.text('computationItem') or call.text('name')
        computation_id = call.number('id')
        node_id = shared_id(self.app_id, 'comp', computation_id or item)
        self._node(node_id, 'ApexComputation', item or f'computation {computation_id}', {
            'scope': 'APPLICATION',
            'itemName': item.upper(),
            'computationType': call.text('computationType'),
            'pointCode': call.text('computationPoint'),
            'sequence': call.number('computationSequence'),
        }, call=call)
        expression = call.text('computation')
        computation_type = call.text('computationType').upper()
        if expression:
            if computation_type in ('QUERY', 'SQL_QUERY', 'QUERY_COLON'):
                self._sql_code(node_id, expression, 'EXECUTES_SQL', 'computation')
            elif computation_type in ('FUNCTION_BODY', 'PLSQL_EXPRESSION',
                                      'PLSQL_FUNCTION_BODY'):
                self._plsql_code(node_id, expression, 'EXECUTES_PLSQL', 'computation')
        if item:
            self._defer('setsItem', node_id=node_id, item=item.upper(), page=None)
