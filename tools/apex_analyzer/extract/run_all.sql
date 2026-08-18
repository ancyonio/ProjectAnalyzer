-- Run the whole extraction kit and spool the JSON the analyzer reads.
--
--   sql analysis_reader/@//host:1521/service @run_all.sql 100 ORDER_APP
--
-- Parameter 1: APEX application id
-- Parameter 2: schema list for the database extract (comma separated, no spaces)
--
-- Writes apex_meta_parts.json and db_meta_parts.json into the current
-- directory. Every script is a plain select; nothing here writes.

set define on
set termout on
define app_id = '&1'
define schemas = '&2'

prompt Extracting APEX metadata for application &app_id ...
spool apex_meta_parts.json
@@01_apex_application.sql &app_id
@@02_apex_pages.sql &app_id
@@03_apex_components.sql &app_id
@@04_apex_shared.sql &app_id
spool off

prompt Extracting database metadata for &schemas ...
spool db_meta_parts.json
@@05_db_objects.sql &schemas
@@06_db_columns.sql &schemas
@@07_db_dependencies.sql &schemas
@@08_db_source.sql &schemas
@@09_db_constraints.sql &schemas
spool off

prompt
prompt Each script emitted one JSON object. Merge the parts into one object per
prompt file before passing them to the analyzer:
prompt
prompt   python tools/apex_analyzer/extract/merge_parts.py db_meta_parts.json db_meta.json
prompt   python tools/apex_analyzer/extract/merge_parts.py apex_meta_parts.json apex_meta.json
prompt
prompt Then:
prompt   python -m apex_analyzer analyze --source <export> --db-meta db_meta.json
