-- APEX pages. Read-only.
--   sql> @02_apex_pages.sql 100
-- Emits the `pages` section of apex_meta.json, used to cross-check the export
-- parse (validation rule AX-CROSSCHECK).

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000

define app_id = '&1'

select json_object(
  'pages' value (
     select json_arrayagg(json_object('pageId' value p.page_id,
                                      'name' value p.page_name,
                                      'alias' value p.page_alias,
                                      'title' value p.page_title,
                                      'pageMode' value p.page_mode,
                                      'pageGroup' value p.page_group,
                                      'authorizationScheme' value p.authorization_scheme,
                                      'pageAccessProtection' value p.page_access_protection,
                                      'requiresLogin' value p.page_requires_authentication,
                                      'lastUpdatedOn' value to_char(p.last_updated_on,
                                                                    'YYYY-MM-DD HH24:MI:SS')
                                      returning clob) returning clob)
       from apex_application_pages p
      where p.application_id = to_number('&app_id'))
  returning clob) as apex_pages
from dual;
