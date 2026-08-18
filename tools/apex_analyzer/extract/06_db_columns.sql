-- Columns for the schemas in scope. Read-only.
--   sql> @06_db_columns.sql ORDER_APP
-- Emits the `columns` section of db_meta.json.

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000

define schemas = '&1'

select json_object(
  'columns' value (
     select json_arrayagg(json_object('owner' value c.owner,
                                      'tableName' value c.table_name,
                                      'columnName' value c.column_name,
                                      'dataType' value c.data_type,
                                      'dataLength' value c.data_length,
                                      'nullable' value c.nullable,
                                      'columnId' value c.column_id,
                                      'dataDefault' value substr(to_char(c.data_default), 1, 200)
                                      returning clob) returning clob)
       from all_tab_columns c
      where c.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null))
  returning clob) as db_columns
from dual;
