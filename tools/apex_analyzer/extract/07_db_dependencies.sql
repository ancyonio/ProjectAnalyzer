-- ALL_DEPENDENCIES for the schemas in scope. Read-only.
--   sql> @07_db_dependencies.sql ORDER_APP
-- Emits the `dependencies` section of db_meta.json. This is the authoritative
-- object-to-object edge set: the analyzer's own parsed CALLS / READS_FROM
-- edges are cross-checked against it (validation rule AX-DEPMISMATCH).

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000

define schemas = '&1'

select json_object(
  'dependencies' value (
     select json_arrayagg(json_object('owner' value d.owner,
                                      'name' value d.name,
                                      'type' value d.type,
                                      'referencedOwner' value d.referenced_owner,
                                      'referencedName' value d.referenced_name,
                                      'referencedType' value d.referenced_type
                                      returning clob) returning clob)
       from all_dependencies d
      where d.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)
        and d.referenced_owner not in ('SYS', 'PUBLIC'))
  returning clob) as db_dependencies
from dual;
