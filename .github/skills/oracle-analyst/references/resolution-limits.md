# How Oracle source becomes graph edges — and where it stops

This is the part of the analyzer most likely to be wrong, so it is the part you must
understand before quoting it. The binder is shared with the APEX analyzer and lives
in `analyzer_core/plsql/`.

## What is extracted

| Found in the source | Edge produced |
|---|---|
| `FROM`, `JOIN`, subquery, `MERGE … USING` | `READS_FROM` |
| `INSERT INTO` | `INSERTS_INTO` + `WRITES_TO` |
| `UPDATE <t> SET` | `UPDATES` + `WRITES_TO` |
| `DELETE FROM` | `DELETES_FROM` + `WRITES_TO` |
| `<seq>.NEXTVAL` | `USES_SEQUENCE` |
| `pkg.proc(...)` | `CALLS` |
| `@dblink` | `REFERENCES_DBLINK`, and no edge to the remote object |
| `CREATE VIEW … AS SELECT` | `DEPENDS_ON` per base table |
| `CREATE TRIGGER … ON <t>` | `FIRES_ON` |
| `CREATE SYNONYM … FOR <t>` | `RESOLVES_TO` |
| `ALTER TABLE … FOREIGN KEY` | `CONSTRAINS` + `DEPENDS_ON` |

`INSERT INTO archive SELECT … FROM orders` produces **both** sides — a write to the
target and a read of the source. Recording only the write loses half the lineage.

## Deliberate design choices

- **Both the specific verb and the roll-up are emitted.** So a traversal can use
  `WRITES_TO` while lineage uses `INSERTS_INTO`. They are not alternatives.
- **A schema-qualified name is not a package-qualified name.**
  `ORDER_APP.ARCHIVE_ORDERS` is `schema.procedure`; read as `package.procedure` it
  makes a standalone unit's own `CREATE` header look like a call to itself.
- **A qualified name in a DML statement is a table, not a call.**
  `insert into order_app.audit_log (…)` looks exactly like `package.procedure(args)`;
  the binder resolves the ambiguity by checking the statement's own table set first.
- **Synonyms are followed one hop.** A unit that reads a synonym is recorded against
  the object the synonym points at, so lineage does not stop at the indirection.
- **Specs are parsed before bodies**, regardless of file order — `.pkb` sorts before
  `.pks` — so publication does not depend on file names.
- **Comments are stripped for parsing but not for storage.** An optimizer hint lives
  in a `/*+ … */` comment; discarding it before the statement is stored would lose
  the one thing `PERF-002` needs to see.

## Where it stops

| Limit | What the graph does | What you must say |
|---|---|---|
| `EXECUTE IMMEDIATE` on an assembled string | flags `hasDynamicSql`, raises `SEC-001`, produces **no** dependency edge | "the target is assembled at runtime; the dependency is unknown to the graph" |
| `DBMS_SQL` | as above | as above |
| Object referenced but never defined in the tree | creates `:UnresolvedRef` and raises `DEBT-004` | "referenced but not present in the analysed tree" — not "does not exist" |
| Remote object over a database link | `REFERENCES_DBLINK` only | the remote object is out of scope and is not fabricated |
| No dictionary extract | falls back to repository DDL; `coverage.dictionaryAvailable` is false | this is a statement about the repository, not the deployed database |
| Overload that cannot be attributed | edge targets the unsuffixed id with `ambiguous: true` | say which overload is uncertain |
| ORDS endpoints, scheduled jobs, external batch | outside the model | a "dead" object may be reached from outside the database |
| Row-level security, privileges, execution plans | not modelled | the graph models structure, not behaviour |

## Reading coverage

`graph.meta.coverage` reports the whole picture:

```json
{
  "objectsDiscovered": 21,
  "objectsModelled": 20,
  "resolutionCoverage": 95.2,
  "callsResolved": 2,
  "callsUnresolved": 1,
  "callResolution": 66.7,
  "dynamicSqlSites": 1,
  "dictionaryAvailable": false,
  "unresolvedReferences": ["LEGACY_UTIL.CLEANUP"]
}
```

Two figures, and they answer different questions:

- **`resolutionCoverage`** — how much of what the analysis saw became a modelled
  object. Low means names were referenced that the tree never defined.
- **`callResolution`** — how much of the call graph bound to a target. Low means the
  call graph, and therefore every blast radius drawn from it, is incomplete.

Below 80 % on either, the validator raises `resolution-coverage` and the graph is
provisional. Quote the number when the question is about completeness — "95 % of
objects resolved; the one that did not is listed" is an answer, "the estate uses five
tables" alone is not.
