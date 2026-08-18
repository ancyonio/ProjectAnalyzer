-- APEX shared components. Read-only.
--   sql> @04_apex_shared.sql 100
-- Emits `lovs`, `lists`, `webSources` and `automations`.

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000

define app_id = '&1'

select json_object(
  'lovs' value (
     select json_arrayagg(json_object('name' value l.list_of_values_name,
                                      'lovType' value l.lov_type,
                                      'query' value l.list_of_values_query,
                                      'entryCount' value (
                                          select count(*)
                                            from apex_application_lov_entries e
                                           where e.application_id = l.application_id
                                             and e.list_of_values_id = l.list_of_values_id)
                                      returning clob) returning clob)
       from apex_application_lovs l
      where l.application_id = to_number('&app_id')),

  'lists' value (
     select json_arrayagg(json_object('name' value t.list_name,
                                      'entryCount' value t.list_entry_count
                                      returning clob) returning clob)
       from apex_application_lists t
      where t.application_id = to_number('&app_id')),

  'webSources' value (
     select json_arrayagg(json_object('name' value w.name,
                                      'sourceType' value w.web_source_type,
                                      'baseUrl' value w.url_endpoint
                                      returning clob) returning clob)
       from apex_appl_web_src_modules w
      where w.application_id = to_number('&app_id')),

  'automations' value (
     select json_arrayagg(json_object('name' value a.name,
                                      'scheduleType' value a.schedule_type,
                                      'status' value a.status
                                      returning clob) returning clob)
       from apex_appl_automations a
      where a.application_id = to_number('&app_id'))
  returning clob) as apex_shared
from dual;
