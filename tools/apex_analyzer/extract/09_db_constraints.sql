-- Constraints and indexes for the schemas in scope. Read-only.
--   sql> @09_db_constraints.sql ORDER_APP
-- Emits the `constraints` and `indexes` sections of db_meta.json. The foreign
-- key rows become the REFERENCES_TABLE edges the entity-relationship diagram
-- is drawn from.

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000

define schemas = '&1'

select json_object(
  'constraints' value (
     select json_arrayagg(json_object('owner' value c.owner,
                                      'constraintName' value c.constraint_name,
                                      'constraintType' value
                                        case c.constraint_type
                                          when 'P' then 'PRIMARY_KEY'
                                          when 'R' then 'FOREIGN_KEY'
                                          when 'U' then 'UNIQUE'
                                          when 'C' then 'CHECK'
                                          else c.constraint_type end,
                                      'tableName' value c.table_name,
                                      'refOwner' value r.owner,
                                      'refTable' value r.table_name,
                                      'columns' value (
                                          select listagg(cc.column_name, ',')
                                                   within group (order by cc.position)
                                            from all_cons_columns cc
                                           where cc.owner = c.owner
                                             and cc.constraint_name = c.constraint_name)
                                      returning clob) returning clob)
       from all_constraints c
       left join all_constraints r
              on r.owner = c.r_owner
             and r.constraint_name = c.r_constraint_name
      where c.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null)),

  'indexes' value (
     select json_arrayagg(json_object('owner' value i.owner,
                                      'indexName' value i.index_name,
                                      'tableName' value i.table_name,
                                      'uniqueness' value i.uniqueness,
                                      'columns' value (
                                          select listagg(ic.column_name, ',')
                                                   within group (order by ic.column_position)
                                            from all_ind_columns ic
                                           where ic.index_owner = i.owner
                                             and ic.index_name = i.index_name)
                                      returning clob) returning clob)
       from all_indexes i
      where i.owner in (select upper(trim(regexp_substr('&schemas', '[^,]+', 1, level)))
                          from dual connect by regexp_substr('&schemas', '[^,]+', 1, level) is not null))
  returning clob) as db_constraints
from dual;
