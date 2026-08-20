# Oracle graph model

The vocabulary is closed and lives in code: `tools/oracle_analyzer/constants.py` is the
definition, and `analyzer_core/graph/validate.py` fails the build on any label or
relationship type outside it. This guide explains that vocabulary; when the two
disagree, the code is right.

**The database vocabulary is shared with the APEX analyzer on purpose.** `DbTable`,
`READS_FROM`, `HAS_UNIT` and the rest mean the same thing in both graphs, so the same
Cypher answers either. Never introduce a second spelling for a concept that already
has one.

## Layers

| Layer | Labels |
|---|---|
| Repository | `Project`, `Repository`, `Branch`, `Commit`, `Developer`, `Directory`, `File` |
| Schema objects | `DbSchema`, `DbTable`, `DbColumn`, `DbView`, `DbMaterializedView`, `DbIndex`, `DbConstraint`, `DbSequence`, `DbSynonym`, `DbDatabaseLink`, `DbType`, `DbTrigger` |
| Program structure | `DbPackage`, `PackageSpec`, `PackageBody`, `DbProgramUnit`, `PlsqlBlock` |
| Code | `SqlStatement` |
| Analysis | `Issue`, `Recommendation`, `CodeMetric`, `UnresolvedRef` |

## Why a package is three nodes

`DbPackage` is the named unit. `PackageSpec` is the published contract.
`PackageBody` is the implementation. They are separate because they have different
change semantics, and that difference is the point of the graph:

- a change to a **`PackageSpec`** breaks every caller;
- the same change to a **`PackageBody`** is invisible outside the package.

Collapsing them makes the single most useful impact question — *will this change
break callers?* — unanswerable. A unit reachable from outside carries
`isPublished: true`; a private body unit does not.

## The relationships that answer questions

| Question | Path |
|---|---|
| Which units modify this table? | `(:DbProgramUnit)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->(:DbTable)` |
| Exactly how do they touch it? | the same path with `[:INSERTS_INTO\|UPDATES\|DELETES_FROM\|READS_FROM]` |
| What calls this procedure? | `(caller:DbProgramUnit)-[:CALLS*1..]->(:DbProgramUnit)` |
| What does this package publish? | `(:DbPackage)-[:HAS_SPEC]->(:PackageSpec)-[:HAS_UNIT]->(:DbProgramUnit)` |
| What is this view built from? | `(:DbView)-[:DEPENDS_ON]->(:DbTable)` |
| What fires when I write this table? | `(:DbTrigger)-[:FIRES_ON]->(:DbTable)` |
| Where does this synonym point? | `(:DbSynonym)-[:RESOLVES_TO]->(target)` |
| What could the analysis not resolve? | `(src)-[:UNRESOLVED]->(:UnresolvedRef)` |
| What did this release change? | `(:Commit)-[:CHANGED]->(:File)-[:DEFINES]->(object)` |
| What touches this column? | `(:SqlStatement)-[:REFERENCES_COLUMN]->(:DbColumn)` |
| Which tables are queried together? | `(:SqlStatement)-[:JOINS]->(:DbTable)` |
| What depends on this user-defined type? | `(:DbProgramUnit)-[:USES_TYPE]->(:DbType)` |

### Both the verb and the roll-up

Every write emits the specific verb **and** `WRITES_TO`:

```
INSERT INTO ORDERS …   ->  INSERTS_INTO + WRITES_TO
UPDATE ORDERS SET …    ->  UPDATES      + WRITES_TO
DELETE FROM ORDERS …   ->  DELETES_FROM + WRITES_TO
```

So a traversal can use one edge type while lineage uses the precise one.
`WRITES_TO` alone cannot separate an insert from a delete, and that distinction is
what a retention or lineage question turns on — do not answer one with the other.

### HAS_UNIT is structure, not a call path

Package membership is excluded from impact traversal. Calling
`AUDIT_PKG.LOG_ACTION` must not drag in `AUDIT_PKG.PURGE_OLD_LOGS` and everything
that unit touches. Unit-level `CALLS` edges carry the real reachability.

## Identity

Ids are natural keys, not counters, which is what makes two releases comparable by
set arithmetic and a Neo4j re-load idempotent:

```
db:ORDER_APP                                schema
db:ORDER_APP.ORDERS                         table, view, sequence, synonym, type
db:ORDER_APP.ORDERS.ORDER_ID                column
db:ORDER_APP.CUSTOMER_PKG                   package
db:ORDER_APP.CUSTOMER_PKG#spec              package spec
db:ORDER_APP.CUSTOMER_PKG#body              package body
db:ORDER_APP.CUSTOMER_PKG.CREATE_CUSTOMER   packaged procedure or function
db:ORDER_APP.CUSTOMER_PKG.GET_CUSTOMER#2    second overload of the same name
db:ORDER_APP.ARCHIVE_ORDERS                 standalone procedure or function
sql:9f2c1a…                                 SQL statement, content addressed
plsql:3b81cc…                               PL/SQL block, content addressed
file:src/customer/customer_pkg.pkb          source file
unresolved:LEGACY_UTIL.CLEANUP              a name that never resolved
```

**Overloads.** PL/SQL permits overloaded subprograms, so the qualified name is not
unique. The first keeps the unsuffixed id — so a unit does not change id when a
second signature is added later — and subsequent overloads take `#2`, `#3`. Without
a dictionary extract the position is inferred from source order; a `CALLS` edge that
cannot be attributed to one overload targets the unsuffixed id and carries
`ambiguous: true` rather than picking arbitrarily.

## Provenance — read this before quoting an edge

Every node carries `origin`:

| `origin` | Meaning |
|---|---|
| `ddl` | parsed from a script in the repository |
| `dictionary` | from the data-dictionary extract, which is authoritative |
| `inferred` | created because something referenced it, e.g. a database link |

`origin` matters. A graph built from DDL alone is a statement about the
**repository**; one merged with a dictionary extract is a statement about the
**deployed database**. In real estates they disagree — an object dropped in
production but still in source control, a column added by a hotfix that never came
back — and the disagreement is itself a finding. `graph.meta.coverage.dictionaryAvailable`
says which kind of graph you are holding.

## Source locations

Every code node carries `filePath`, `lineStart`, `lineEnd` and `language`, so a
finding can name a range rather than a starting point. Units inside a package
body each get their own range; they do not share the package's. `File` nodes
also carry `lastModified`, which dates the working copy — a checkout rewrites
mtimes, so use `commitCount` from the Git layer for how often something really
changes.

## What is deliberately not modelled

Local variables and constants, individual parameters, cursors and user-defined
exceptions; lines and tokens. Modelling every local declaration inflates node
count by roughly an order of magnitude and buries the structure that matters.

Column-to-column flow is also absent. `REFERENCES_COLUMN` records that a
statement names a column, not that one column populates another — see
[data-lineage.md](data-lineage.md).

Business capabilities and test cases are not modelled either, and not because
they were forgotten: nothing in an Oracle source tree states them, so the only
way to produce them would be to infer them from names. Every node in this graph
comes from a statement in a script or a row in a dictionary extract, and a
guessed node is indistinguishable from a parsed one once it is in the database.
Where a business layer exists it is built by `estate_analyzer`, from evidence
the APEX and TIBCO exports actually carry.
