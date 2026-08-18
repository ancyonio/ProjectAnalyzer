-- Database objects for the schemas in scope.
-- Read-only. Parameter 1: comma-separated schema list, upper case.
--
--   sql> @05_db_objects.sql ORDER_APP
--
-- Emits a JSON object with the `objects`, `tables`, `views`, `programUnits`,
-- `synonyms`, `sequences`, `triggers` and `databaseLinks` sections of
-- db_meta.json.

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000
set longchunksize 2000000

define schemas = '&1'

select json_object(
  'schemas' value (
     select json_arrayagg(column_value returning clob)
       from table(sys.odcivarchar2list(upper('&schemas')))),

  'objects' value (
     select json_arrayagg(json_object('owner' value owner,
                                      'name' value object_name,
                                      'objectType' value object_type,
                                      'status' value status
                                      returning clob) returning clob)
       from all_objects
      where owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                        from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)
        and object_type in ('TABLE','VIEW','MATERIALIZED VIEW','PACKAGE','PACKAGE BODY',
                            'PROCEDURE','FUNCTION','TRIGGER','SEQUENCE','SYNONYM','TYPE')),

  'tables' value (
     select json_arrayagg(json_object('owner' value t.owner,
                                      'tableName' value t.table_name,
                                      'numRows' value t.num_rows,
                                      'partitioned' value t.partitioned
                                      returning clob) returning clob)
       from all_tables t
      where t.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)),

  'views' value (
     select json_arrayagg(json_object('owner' value v.owner,
                                      'viewName' value v.view_name,
                                      'text' value to_clob(v.text)
                                      returning clob) returning clob)
       from all_views v
      where v.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)),

  'programUnits' value (
     select json_arrayagg(json_object('owner' value p.owner,
                                      'packageName' value p.object_name,
                                      'name' value p.procedure_name,
                                      'unitKind' value nvl(p.object_type, 'PROCEDURE'),
                                      'overload' value p.overload
                                      returning clob) returning clob)
       from all_procedures p
      where p.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)
        and p.procedure_name is not null),

  'synonyms' value (
     select json_arrayagg(json_object('owner' value s.owner,
                                      'synonymName' value s.synonym_name,
                                      'tableOwner' value s.table_owner,
                                      'tableName' value s.table_name,
                                      'dbLink' value s.db_link
                                      returning clob) returning clob)
       from all_synonyms s
      where s.owner in ('PUBLIC') or
            s.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)),

  'sequences' value (
     select json_arrayagg(json_object('owner' value q.sequence_owner,
                                      'sequenceName' value q.sequence_name
                                      returning clob) returning clob)
       from all_sequences q
      where q.sequence_owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                                   from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)),

  'triggers' value (
     select json_arrayagg(json_object('owner' value g.owner,
                                      'triggerName' value g.trigger_name,
                                      'tableOwner' value g.table_owner,
                                      'tableName' value g.table_name,
                                      'triggeringEvent' value g.triggering_event,
                                      'status' value g.status,
                                      'body' value g.trigger_body
                                      returning clob) returning clob)
       from all_triggers g
      where g.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)),

  'databaseLinks' value (
     select json_arrayagg(json_object('owner' value l.owner,
                                      'dbLink' value l.db_link,
                                      'host' value l.host
                                      returning clob) returning clob)
       from all_db_links l)

  returning clob) as db_objects
from dual;
