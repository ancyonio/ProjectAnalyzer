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
  "objectsDiscovered": 26,
  "objectsModelled": 25,
  "resolutionCoverage": 96.2,
  "callsResolved": 4,
  "callsUnresolved": 1,
  "callResolution": 80.0,
  "dynamicSqlSites": 1,
  "dictionaryAvailable": false,
  "unresolvedReferences": ["LEGACY_UTIL.CLEANUP"],
  "codeNodes": 19,
  "statementsParsed": 19,
  "statementsPartial": 0,
  "statementsFailed": 0,
  "parseQuality": 100.0,
  "ddlStatements": 22,
  "ddlUnparsed": 0
}
```

Three figures, answering three different questions — in this order, because
each one is measured over whatever the one before it produced:

- **`parseQuality`** — how much of the code the parser actually read.
  `PARSED` / `PARTIAL` / `FAILED` over `SqlStatement` and `PlsqlBlock`. This is
  the figure to read **first**, because the two below are measured over the code
  that parsed, not over the code that exists. Below 90 % the validator raises
  `parse-quality`.
- **`resolutionCoverage`** — how much of what the parser extracted became a
  modelled object. Low means names were referenced that the tree never defined.
- **`callResolution`** — how much of the call graph bound to a target. Low means
  the call graph, and therefore every blast radius drawn from it, is incomplete.

`ddlUnparsed` sits beside them and is not a percentage of anything: those are
statements that matched no pattern and created **nothing**, so they leave no
trace in any node count. A file of unsupported DDL and an empty file look
identical without it.

Below 80 % on either resolution figure the validator raises
`resolution-coverage` and the graph is provisional.

### Why the order matters

A graph can report **100 % resolution and 100 % call resolution** while having
read a third of its code: every name the parser managed to extract bound
perfectly, and the rest was never seen. That is the most flattering possible
summary of the least useful graph, and it is exactly what `parseQuality`
exists to contradict. The context-pack banner states it before the resolution
line for the same reason.

Quote the numbers when the question is about completeness — "96 % of objects
resolved from 100 % of the code, and the one that did not is listed" is an
answer; "the estate uses five tables" alone is not.
