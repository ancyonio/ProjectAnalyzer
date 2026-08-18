-- ALL_SOURCE for packages, procedures, functions and triggers. Read-only.
--   sql> @08_db_source.sql ORDER_APP
-- Emits the `source` section of db_meta.json. The analyzer parses this text
-- for calls and DML, which is what gives package-level lineage when no DDL is
-- committed in the repository.

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000
set longchunksize 2000000

define schemas = '&1'

select json_object(
  'source' value (
     select json_arrayagg(json_object('owner' value owner,
                                      'name' value name,
                                      'type' value type,
                                      'text' value body
                                      returning clob) returning clob)
       from (select s.owner, s.name, s.type,
                    listagg(s.text, '') within group (order by s.line) as body
               from all_source s
              where s.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                                  from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)
                and s.type in ('PACKAGE BODY', 'PROCEDURE', 'FUNCTION', 'TRIGGER',
                               'TYPE BODY')
              group by s.owner, s.name, s.type))
  returning clob) as db_source
from dual;
