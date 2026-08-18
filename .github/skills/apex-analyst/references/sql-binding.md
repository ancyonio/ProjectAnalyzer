# How SQL becomes graph edges — and where it stops

This is the part of the analyzer most likely to be wrong, so it is the part you must
understand before quoting it.

## What is extracted from a statement

| Found in the SQL | Edge produced |
|---|---|
| `FROM`, `JOIN`, subquery, `MERGE … USING` | `READS_FROM` |
| `INSERT INTO` | `INSERTS_INTO` + `WRITES_TO` |
| `UPDATE <t> SET` | `UPDATES` + `WRITES_TO` |
| `DELETE FROM` | `DELETES_FROM` + `WRITES_TO` |
| `<seq>.NEXTVAL` | `USES_SEQUENCE` |
| qualified and in-scope columns | `REFERENCES_COLUMN` |
| `:P10_X`, `&P10_X.` | `BINDS_ITEM` |
| `pkg.proc(...)` | `CALLS` |
| `@dblink` | `hasDbLink`, plus an edge to `:DbDatabaseLink` |

Both the specific and the umbrella write edge are emitted, so
`MATCH (code)-[:WRITES_TO]->(t)` finds every write without a type union.

## Deliberate design choices

- **Common table expressions are resolved locally.** `WITH recent AS (…) SELECT … FROM
  recent` produces one edge to the underlying table, not a phantom `RECENT` table.
- **Columns are collected liberally, then filtered.** Any identifier that could be a
  column is proposed, and the resolver keeps only those that are real columns of a
  table in scope. Over-collecting costs nothing; under-collecting loses lineage.
- **Tables are collected strictly.** A name is only read as a table when it sits where
  a table can legally sit — because table edges drive impact analysis, and a false
  one is worse than a missing one.
- **A qualified name in a DML statement is a table, not a call.** `insert into
  order_app.audit_log (id, note)` looks exactly like `package.procedure(args)`; the
  binder resolves the ambiguity by checking the statement's own table set first.
- **Declarative sources produce `SOURCED_FROM`.** Forms and interactive grids name a
  table with no SQL at all. Ignoring them loses most of the lineage on form pages.

## Where it stops

| Limit | What the graph does | What you must say |
|---|---|---|
| Dynamic SQL (`EXECUTE IMMEDIATE` on an assembled string) | flags `hasDynamicSql`, raises `SEC-001` when input is concatenated, and cannot resolve the target | "the target is assembled at runtime; the dependency is unknown to the graph" |
| Object not in the extract | creates `:DbObject:Unresolved` and raises `CORR-001` | "referenced but not present in the extract" — not "does not exist" |
| No dictionary extract at all | falls back to DDL in the repository; `coverage.dictionaryAvailable` is false | say so before any completeness claim |
| ORDS handlers, external jobs, scheduled batch | outside the model | a "dead" object may be reached from outside APEX |
| Interactive report user customisations | runtime state, not modelled | column-level claims apply to the defined report only |

## Reading coverage

`graph.meta.coverage` reports the whole picture:

```json
{
  "resolutions": {"exact": 25, "schema_default": 5, "unresolved": 2},
  "resolutionCoverage": 0.94,
  "parseFailureRate": 0.0,
  "dictionaryAvailable": true,
  "unresolvedNames": ["ORDER_APP.ORDERS_ARCHIVE"]
}
```

Below 0.80 the validator raises `AX-COVERAGE` and the graph is provisional. Quote the
number when the question is about completeness — "94 % of database references
resolved; the two that did not are listed" is an answer, "the application uses eight
tables" alone is not.
