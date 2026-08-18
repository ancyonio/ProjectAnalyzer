---
applyTo: "**/*.pks,**/*.pkb,**/*.prc,**/*.fnc,**/*.trg,**/*.pls,**/*.plsql,**/*.ddl"
description: Rules that fire when an Oracle PL/SQL source file is open.
---

# You are looking at an Oracle PL/SQL source file

This file is one object in an estate that `tools/oracle_analyzer` has already parsed
into a knowledge graph. Reading it by hand is how counts become wrong.

## Do not

- Do not count procedures, tables, calls or dependencies by reading this file. Run
  `oracle-analyze` and read `analysis_output_oracle/context/`.
- Do not conclude a unit is unused because you cannot see a caller in this file.
  Callers live in other files, and some live in `EXECUTE IMMEDIATE` where no static
  analysis can see them.
- Do not infer what a package does from its file name.
- Do not hand-edit generated output under `analysis_output_oracle/` to match
  something you read here. If the graph is wrong, the fix belongs in
  `tools/oracle_analyzer/parsers/`.

## Do

- Open the file to **confirm** something the graph already pointed at, or to quote an
  exact expression — a `WHERE` clause, an `EXECUTE IMMEDIATE` string — that the graph
  stores only as a truncated excerpt.
- Note which half you are in. A `.pks` is the published contract: a change here breaks
  every caller. A `.pkb` is the implementation: the same change breaks nothing outside
  the package. The graph models them as separate `PackageSpec` and `PackageBody`
  nodes for exactly this reason, and an answer that does not say which one is
  incomplete.
- Watch for **overloads**. Two subprograms with one name are two different objects,
  with node ids `…GET_CUSTOMER` and `…GET_CUSTOMER#2`. Without a dictionary extract
  the position is inferred from source order, so confirm which signature you mean.
- Treat a schema-qualified name as `schema.object`, not `package.procedure`.
  `ORDER_APP.ARCHIVE_ORDERS` is a standalone procedure in a schema.

## When you see dynamic SQL

`EXECUTE IMMEDIATE` on an assembled string, or any `DBMS_SQL` use, is where the
dependency graph stops. The analyzer records this rather than guessing: the unit
carries `hasDynamicSql`, rule `SEC-001` fires, and **no** data-access edge is created.

Two consequences you must carry into any answer:

1. the unit's real reads and writes are unknown to the graph, so a completeness claim
   about it is provisional; and
2. an object that looks dead may be reached from exactly here.

## If something is missing from the graph

If an object exists in this file but not in the graph, that is a parser gap, not a
reason to answer from the file. Check `analysis_output_oracle/context/unresolved.md`
and `graph.meta.coverage`, say what is missing, and raise it — the fix belongs in
`tools/oracle_analyzer/parsers/`, or in `analyzer_core/plsql/` if the SQL binder
itself mis-read the statement.

Note that `analyzer_core/plsql/` is shared with the APEX analyzer, so a change there
must be verified against **both** test suites plus the binder corpus:

```bash
python tests/test_oracle_analyzer.py
python tests/test_apex_analyzer.py
python tests/test_sql_binder.py
```
