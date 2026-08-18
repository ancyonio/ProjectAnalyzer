# Dictionary extraction kit

Read-only SQL that produces the JSON the analyzer reads with `--db-meta` and
`--apex-meta`. Without it the analyzer still works — it builds the database
layer from committed DDL — but object resolution is weaker and the validator
says so (`AX-COVERAGE`).

## What it needs

A read-only account that can see the application schema and the APEX
dictionary:

```sql
grant select_catalog_role to analysis_reader;
grant apex_administrator_read_role to analysis_reader;   -- for the APEX_* views
-- or simply run the kit as the workspace parsing schema owner
```

Nothing in this kit writes, locks or creates. Every script is a `select`.

## Running it

With SQLcl (recommended — it can spool JSON directly):

```bash
sql analysis_reader/@//host:1521/service @tools/apex_analyzer/extract/run_all.sql 100 ORDER_APP
```

`run_all.sql` takes two parameters:

1. the APEX application id (e.g. `100`)
2. a comma-free schema name to scope the database extract (e.g. `ORDER_APP`)

It writes two files into the current directory:

| File | Contents | Passed as |
|---|---|---|
| `apex_meta.json` | `APEX_*` dictionary rows for the application | `--apex-meta` |
| `db_meta.json` | objects, columns, dependencies, source, constraints | `--db-meta` |

Then:

```bash
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex analyze \
  --source /path/to/f100 --db-meta db_meta.json --apex-meta apex_meta.json
```

## Running one script at a time

Each numbered script is standalone and prints a JSON array. Use them
individually when a DBA wants to review exactly what is being read, or when
only part of the extract is permitted:

| Script | Yields |
|---|---|
| `01_apex_application.sql` | application, authentication, authorization schemes, build options |
| `02_apex_pages.sql` | pages |
| `03_apex_components.sql` | regions, items, buttons, processes, validations, branches, computations, dynamic actions |
| `04_apex_shared.sql` | lists of values, lists, web sources, automations |
| `05_db_objects.sql` | `ALL_OBJECTS`, procedures, synonyms, sequences, triggers, links |
| `06_db_columns.sql` | `ALL_TAB_COLUMNS` plus row counts |
| `07_db_dependencies.sql` | `ALL_DEPENDENCIES` |
| `08_db_source.sql` | `ALL_SOURCE` for packages, procedures, functions and triggers |
| `09_db_constraints.sql` | constraints, constraint columns, indexes |

## The extraction contract

Each row below is implemented twice — once by a parser in `tools/apex_analyzer/parsers/`
reading the export, once by a query in this kit reading the dictionary. Both must produce
the same component, which is what makes the two sources cross-checkable. When adding
support for a component, add both halves.

| Graph node | Export API procedure | Dictionary view |
|---|---|---|
| `:ApexApplication` | `create_flow` | `APEX_APPLICATIONS` |
| `:ApexPage` | `create_page` | `APEX_APPLICATION_PAGES` |
| `:ApexRegion` | `create_page_plug` | `APEX_APPLICATION_PAGE_REGIONS` |
| `:ApexItem` | `create_page_item` | `APEX_APPLICATION_PAGE_ITEMS` |
| `:ApexButton` | `create_page_button` | `APEX_APPLICATION_PAGE_BUTTONS` |
| `:ApexProcess` (page) | `create_page_process` | `APEX_APPLICATION_PAGE_PROC` |
| `:ApexProcess` (application) | `create_flow_process` | `APEX_APPLICATION_PROCESSES` |
| `:ApexValidation` | `create_page_validation` | `APEX_APPLICATION_PAGE_VAL` |
| `:ApexBranch` | `create_page_branch` | `APEX_APPLICATION_PAGE_BRANCHES` |
| `:ApexComputation` | `create_page_computation`, `create_flow_computation` | `APEX_APPLICATION_PAGE_COMP`, `APEX_APPLICATION_COMPUTATIONS` |
| `:ApexDynamicAction` | `create_page_da_event` | `APEX_APPLICATION_PAGE_DA` |
| `:ApexDaAction` | `create_page_da_action` | `APEX_APPLICATION_PAGE_DA_ACTS` |
| `:ApexLov` | `create_list_of_values` (+ static entries) | `APEX_APPLICATION_LOVS`, `APEX_APPLICATION_LOV_ENTRIES` |
| `:ApexAuthorization` | `create_security_scheme` | `APEX_APPLICATION_AUTHORIZATION` |
| `:ApexAuthentication` | `create_authentication` | `APEX_APPLICATION_AUTH` |
| `:ApexItem` (application level) | `create_flow_item` | `APEX_APPLICATION_ITEMS` |
| `:ApexList` / `:ApexListEntry` | `create_list`, `create_list_item` | `APEX_APPLICATION_LISTS`, `APEX_APPLICATION_LIST_ITEMS` |
| `:ApexNavigation` | `create_nav_bar_list_item` | `APEX_APPLICATION_NAV_BAR` |
| `:ApexBuildOption` | `create_build_option` | `APEX_APPLICATION_BUILD_OPTIONS` |
| `:ApexReportColumn` | `create_report_columns`, `create_worksheet_column`, `create_ig_column` | `APEX_APPLICATION_PAGE_RPT_COLS`, `APEX_APPLICATION_PAGE_IR_COL`, `APEX_APPL_PAGE_IG_COLUMNS` |
| `:ApexWebSource` / `:ApexWebSourceOperation` | `create_web_source_module`, `create_web_source_operation` | `APEX_APPL_WEB_SRC_MODULES`, `APEX_APPL_WEB_SRC_OPERATIONS` |
| `:ApexAutomation` | `create_automation` | `APEX_APPL_AUTOMATIONS` |
| `:ApexPlugin` | `create_plugin` | `APEX_APPL_PLUGINS` |
| `:ApexEmailTemplate` | `create_email_template` | `APEX_APPL_EMAIL_TEMPLATES` |

APEX renamed the import API in 21.2 (`wwv_flow_api.create_page` became
`wwv_flow_imp_page.create_page`). The parser matches on the **procedure name** and treats
the package prefix as informational, so both families work; the dictionary views did not
change.

Database layer, from this kit only: `ALL_OBJECTS`, `ALL_TAB_COLUMNS`, `ALL_DEPENDENCIES`,
`ALL_SOURCE`, `ALL_PROCEDURES`, `ALL_CONSTRAINTS`, `ALL_CONS_COLUMNS`, `ALL_INDEXES`,
`ALL_TRIGGERS`, `ALL_SYNONYMS`, `ALL_MVIEWS`, `ALL_SEQUENCES`, `ALL_DB_LINKS`.

## Expected JSON shape

`db_meta.json` — every section optional; the reader tolerates what is missing:

```json
{
  "schemas": ["ORDER_APP"],
  "objects":      [{"owner": "...", "name": "...", "objectType": "TABLE", "status": "VALID"}],
  "tables":       [{"owner": "...", "tableName": "...", "numRows": 12345, "partitioned": "NO"}],
  "views":        [{"owner": "...", "viewName": "...", "text": "select ..."}],
  "columns":      [{"owner": "...", "tableName": "...", "columnName": "...",
                    "dataType": "NUMBER", "dataLength": 22, "nullable": "N", "columnId": 1}],
  "programUnits": [{"owner": "...", "packageName": "ORDER_PKG", "name": "CREATE_ORDER",
                    "unitKind": "PROCEDURE", "argumentCount": 2, "overload": 0}],
  "dependencies": [{"owner": "...", "name": "...", "type": "PACKAGE BODY",
                    "referencedOwner": "...", "referencedName": "...", "referencedType": "TABLE"}],
  "source":       [{"owner": "...", "name": "ORDER_PKG", "type": "PACKAGE BODY", "text": "..."}],
  "constraints":  [{"owner": "...", "constraintName": "...", "constraintType": "FOREIGN_KEY",
                    "tableName": "...", "refTable": "...", "columns": "ORDER_ID"}],
  "indexes":      [{"owner": "...", "indexName": "...", "tableName": "...",
                    "uniqueness": "UNIQUE", "columns": "ORDER_ID"}],
  "synonyms":     [{"owner": "...", "synonymName": "...", "tableOwner": "...", "tableName": "..."}],
  "sequences":    [{"owner": "...", "sequenceName": "..."}],
  "triggers":     [{"owner": "...", "triggerName": "...", "tableOwner": "...",
                    "tableName": "...", "triggeringEvent": "INSERT OR UPDATE",
                    "status": "ENABLED", "body": "..."}],
  "databaseLinks":[{"owner": "...", "dbLink": "...", "host": "..."}]
}
```

Any producer of this shape works — a DBA-supplied export, a data-governance
tool, or a hand-written query. The analyzer never connects to Oracle itself.
