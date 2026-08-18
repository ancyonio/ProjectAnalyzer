---
applyTo: "**/f[0-9]*/**/*.sql,**/*apex*/**/*.sql,**/wwv_flow*.sql"
description: Rules that fire when an Oracle APEX export file is open.
---

# You are looking at an APEX export file

An APEX export is generated PL/SQL: a sequence of `wwv_flow_imp*.create_*` calls (or
`wwv_flow_api.*` before APEX 21.2). It is machine-written, and reading it by hand is
how counts become wrong.

## Do not

- Do not count regions, items, processes or dependencies by reading this file. Run
  `apex-analyze` and read `analysis_output_apex/context/`.
- Do not hand-edit an export file to "fix" a finding. The fix belongs in APEX, and
  the export is regenerated.
- Do not infer what a page does from its file name.

## Do

- Open the file to **confirm** something the graph already pointed at, or to quote an
  exact expression — the `p_plug_source` query, the `p_process_sql_clob` body — that
  the graph stores only as a truncated excerpt.
- Use the `p_id` values: they are the component ids the graph's node ids are built
  from (`app100:p10:r1001` is `p_id=>wwv_flow_imp.id(1001)` on page 10).
- Remember that long text arrives as `wwv_flow_string.join(wwv_flow_t_varchar2(...))`
  and as `q'~ … ~'` literals; what you see split across lines is one value.

## If something is missing from the graph

If a component exists in the file but not in the graph, that is a parser gap, not a
reason to answer from the file. Check `graph.meta.unhandledProcedures`, say what is
missing, and raise it — the fix belongs in `tools/apex_analyzer/parsers/`.
