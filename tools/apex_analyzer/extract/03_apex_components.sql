-- APEX page components. Read-only.
--   sql> @03_apex_components.sql 100
-- Emits `regions`, `items`, `buttons`, `processes`, `validations`, `branches`
-- and `dynamicActions` for the cross-check against the export parse.

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000

define app_id = '&1'

select json_object(
  'regions' value (
     select json_arrayagg(json_object('pageId' value r.page_id,
                                      'regionId' value r.region_id,
                                      'name' value r.region_name,
                                      'sourceType' value r.source_type,
                                      'regionType' value r.region_type,
                                      'query' value r.region_source
                                      returning clob) returning clob)
       from apex_application_page_regions r
      where r.application_id = to_number('&app_id')),

  'items' value (
     select json_arrayagg(json_object('pageId' value i.page_id,
                                      'name' value i.item_name,
                                      'itemType' value i.display_as,
                                      'sourceType' value i.item_source_type,
                                      'source' value i.item_source,
                                      'protection' value i.item_protection_level
                                      returning clob) returning clob)
       from apex_application_page_items i
      where i.application_id = to_number('&app_id')),

  'buttons' value (
     select json_arrayagg(json_object('pageId' value b.page_id,
                                      'name' value b.button_name,
                                      'action' value b.button_action,
                                      'target' value b.button_redirect_url
                                      returning clob) returning clob)
       from apex_application_page_buttons b
      where b.application_id = to_number('&app_id')),

  'processes' value (
     select json_arrayagg(json_object('pageId' value p.page_id,
                                      'name' value p.process_name,
                                      'processType' value p.process_type,
                                      'pointCode' value p.process_point,
                                      'source' value p.process_source
                                      returning clob) returning clob)
       from apex_application_page_proc p
      where p.application_id = to_number('&app_id')),

  'validations' value (
     select json_arrayagg(json_object('pageId' value v.page_id,
                                      'name' value v.validation_name,
                                      'validationType' value v.validation_type,
                                      'expression' value v.validation_expression1
                                      returning clob) returning clob)
       from apex_application_page_val v
      where v.application_id = to_number('&app_id')),

  'branches' value (
     select json_arrayagg(json_object('pageId' value b.page_id,
                                      'name' value b.branch_name,
                                      'branchType' value b.branch_type,
                                      'target' value b.branch_action
                                      returning clob) returning clob)
       from apex_application_page_branches b
      where b.application_id = to_number('&app_id')),

  'dynamicActions' value (
     select json_arrayagg(json_object('pageId' value d.page_id,
                                      'name' value d.dynamic_action_name,
                                      'event' value d.event_name,
                                      'selectionType' value d.selection_type
                                      returning clob) returning clob)
       from apex_application_page_da d
      where d.application_id = to_number('&app_id'))
  returning clob) as apex_components
from dual;
