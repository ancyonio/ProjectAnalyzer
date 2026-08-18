"""Page parsing.

`create_page` also establishes the page context every component call that
follows inherits, which is what makes a split export (one file per page) and
a single-file export parse identically.
"""
from __future__ import annotations

from analyzer_core.ids import app_id, page_id

from ..constants import PAGE_PROTECTION_LEVELS
from .plsql_args import ExportCall


class PageParserMixin:

    def handle_create_page(self, call: ExportCall) -> None:
        page = call.number('id')
        if page is None:
            return
        if self.app_id is None:
            self.app_id = call.number('flowId')
        self.page_id = page

        protection = call.text('protectionLevel')
        authorization = call.text('requiredRole') or call.text('authorizationScheme')
        node_id = page_id(self.app_id, page)
        name = (call.text('name') or call.text('stepTitle') or f'Page {page}')

        self._node(node_id, 'ApexPage', name, {
            'pageId': page,
            'alias': call.text('alias'),
            'title': call.text('stepTitle'),
            'pageMode': call.text('pageMode') or ('MODAL' if call.text('dialog') else 'NORMAL'),
            'pageTemplate': call.text('stepTemplate') or call.text('pageTemplate'),
            'pageGroup': call.text('groupName') or call.text('pageGroupId'),
            'pageAccessProtection': PAGE_PROTECTION_LEVELS.get(
                protection.upper(), protection.upper() or 'UNKNOWN'),
            'isPublic': (protection.upper() in ('U', '')) and not authorization,
            'requiresLogin': call.text('pageRequiresAuthentication', 'Y').upper() != 'N',
            'authorizationScheme': authorization,
            'helpText': 'set' if call.text('helpText') else '',
            'lastUpdatedOn': call.text('lastUpdYyyymmddhh24miss'),
        }, call=call)

        self._register('page', page, node_id)
        if self.application_node:
            self._rel(self.application_node, node_id, 'CONTAINS_PAGE')
        elif self.app_id is not None:
            # a split export of a single page: keep the application implicit
            # but present, so containment is never dangling
            self._ensure_application()
            self._rel(app_id(self.app_id), node_id, 'CONTAINS_PAGE')

        self._defer('securedBy', node_id=node_id, scheme=authorization)
        self._defer('buildOption', node_id=node_id,
                    build_option=call.text('buildOption'))

        inline_js = call.text('javascriptCode') or call.text('javascriptCodeOnload')
        if inline_js:
            self._js_code(node_id, inline_js)
