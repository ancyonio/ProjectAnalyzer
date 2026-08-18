# Oracle Analyzer — Specification

Status: **Phase 1 implemented** in `tools/oracle_analyzer`, verified by
`tests/test_oracle_analyzer.py` (30 tests) against the fixture in
`tests/fixtures/oracle`. Phase 2 and Phase 3 (§11) remain outstanding, as do the
decisions in §13.

Where the implementation departs from this document, the departure is noted inline
and the code is correct.

This specifies `tools/oracle_analyzer`, a third dialect alongside `tools/tibco_analyzer` and
`tools/apex_analyzer`, for analysing a standalone Oracle PL/SQL estate — packages, procedures,
functions, triggers, views and the schema they sit on — held in a Git repository rather than
inside an APEX application.

---

## 1. The finding that shapes this specification

**Most of the proposed vocabulary already exists.** `apex_analyzer` models the Oracle database
layer today because an APEX application is largely PL/SQL over tables. Of the labels a
comprehensive Oracle model needs, 22 database and code labels are already defined and
exercised by the committed fixture:

`DbSchema` `DbTable` `DbColumn` `DbView` `DbMaterializedView` `DbSequence` `DbSynonym`
`DbIndex` `DbConstraint` `DbTrigger` `DbDatabaseLink` `DbType` `DbPackage` `DbProgramUnit`
`PlsqlBlock` `SqlStatement` `Project` `File` `Issue` `Recommendation` `BusinessDomain`
`BusinessFunction`

`Repository`, `Branch` and `Commit` exist too, bringing the reusable label count to 25.
So do 26 of the relationships, including the semantic data-access verbs
(`READS_FROM`, `WRITES_TO`, `INSERTS_INTO`, `UPDATES`, `DELETES_FROM`), the analysis layer
(`HAS_ISSUE`, `HAS_RECOMMENDATION`, `AFFECTS`) and the Git layer (`HAS_COMMIT`, `CHANGED`).

The consequence for this specification is that the Oracle analyzer is **not a greenfield graph
model**. It is an existing model promoted from supporting cast to main subject. The work is:

| Area | Work |
|---|---|
| Vocabulary | Extend, do not replace. Roughly 12 new labels, 14 new relationships |
| Parsing | New: a repository-first source scanner and a deeper PL/SQL structural parser |
| Reuse | `analyzer_core` engines, the SQL binder, the DDL parser, the rules catalogue shape |

**Do not create a parallel vocabulary.** A `Table` label alongside the existing `DbTable`, or a
`READS` alongside `READS_FROM`, would fracture the graph: cross-analyzer queries would silently
miss half their data, and the shared `analyzer_core` validation and impact engines would need
two configurations that must be kept in step by hand. Every label below either reuses an
existing name exactly or introduces a genuinely new concept.

---

## 2. Architectural constraints

These are inherited and non-negotiable.

1. **`analyzer_core` must not import from any dialect.** Shared engines (graph model, ids,
   Neo4j exporter, validation, blast radius) are configured by a per-dialect `constants.py`
   and `schema.py`, never by conditionals on dialect.
2. **Zero required runtime dependencies.** Parsing, graph construction and export use the
   standard library so the analyzer runs on an air-gapped build agent. `oracledb` stays an
   optional extra used only to pull the dictionary extract.
3. **Deterministic.** The same source tree must produce a byte-identical `graph.json` apart
   from `meta.generatedAt`. This is what makes "diff the graph before and after" a usable
   regression technique.
4. **Natural-key ids, never counters** (§5). This is what makes two releases comparable by set
   arithmetic and a Neo4j re-load idempotent.
5. **Never invent.** Where static analysis cannot resolve a dependency, the graph records the
   gap explicitly rather than guessing or omitting silently (§9).

---

## 3. Node vocabulary

`reuse` — already defined in `apex_analyzer/constants.py`, adopt unchanged.
`extend` — exists, needs additional properties or a new sub-type.
`new` — genuinely new to the estate.

### 3.1 Repository and source

| Label | Status | Purpose |
|---|---|---|
| `Project` | reuse | Analysis root |
| `Repository` | reuse | Git repository |
| `Branch` | reuse | Analysed branch |
| `Commit` | reuse | Commit touching an analysed file |
| `File` | reuse | A `.sql`, `.pks`, `.pkb`, `.prc`, `.fnc`, `.trg` source file |
| `Directory` | new | Folder, for structure-by-convention reporting |
| `Developer` | new | Commit author, for ownership and change-risk analysis |

### 3.2 Schema objects

All reused unchanged. This is the layer `apex_analyzer` already builds from DDL scripts and,
where available, a dictionary extract.

| Label | Status | Notes |
|---|---|---|
| `DbSchema` | reuse | Owner |
| `DbTable` | reuse | |
| `DbColumn` | reuse | |
| `DbView` | reuse | |
| `DbMaterializedView` | reuse | |
| `DbIndex` | reuse | |
| `DbConstraint` | reuse | PK, FK, unique, check |
| `DbSequence` | reuse | |
| `DbSynonym` | reuse | Indirection, resolved via `RESOLVES_TO` |
| `DbDatabaseLink` | reuse | Remote dependency boundary |
| `DbType` | reuse | Object type, collection type |
| `DbTrigger` | reuse | |

### 3.3 PL/SQL program structure

| Label | Status | Purpose |
|---|---|---|
| `DbPackage` | reuse | The package as a named unit |
| `DbProgramUnit` | reuse | A procedure or function. `unitType` distinguishes them |
| `PackageSpec` | new | The published contract |
| `PackageBody` | new | The implementation |
| `PlsqlBlock` | reuse | An anonymous or embedded block |

**Why split spec and body.** They have different change semantics and that difference is the
point of the graph. A change to a `PackageSpec` is a breaking change for every caller; the same
change to a `PackageBody` is invisible outside the package. Collapsing them into one node makes
the single most useful impact question — "will this change break callers?" — unanswerable.
They also live in different files (`.pks` / `.pkb`) and are separately invalid-able in the
data dictionary.

`DbProgramUnit` is retained rather than introducing `Procedure` and `Function` as separate
labels: it is already in the vocabulary, already carries `unitType`, and already appears in the
impact engine's test buckets. Splitting it would be a rename for no analytical gain.

### 3.4 PL/SQL internals

| Label | Status | Phase | Purpose |
|---|---|---|---|
| `Cursor` | new | P2 | Explicit and ref cursors; a named query with its own dependencies |
| `Exception` | new | P2 | User-defined exceptions, for error-path analysis |
| `Parameter` | new | P2 | Formal parameters — the signature, needed for overload resolution |

**Deliberately excluded: `Variable` and `Constant`.** Modelling every local declaration inflates
node count by roughly an order of magnitude and answers no question the estate actually asks. A
package with 40 procedures and 600 locals becomes a graph in which the interesting structure is
invisible. If a specific need appears later — tracing a package-level constant used as a
configuration flag, say — model *that* case as a `Constant` with a documented reason, not the
general one. This follows the stated principle: start at the code-object level and add finer
grain only where it earns its place.

### 3.5 SQL

| Label | Status | Purpose |
|---|---|---|
| `SqlStatement` | reuse | A single SELECT / INSERT / UPDATE / DELETE / MERGE, content-addressed |

`SqlStatement` is already materialised as a node by `apex_analyzer` and is the right level for
this estate. It is what lets a query be attributed to the object that runs it, deduplicated
across copies, and carry its own shape flags (`SELECT *`, hint, no WHERE clause).

### 3.6 Analysis and business layers

| Label | Status | Purpose |
|---|---|---|
| `Issue` | reuse | A rule finding, with `severity`, `ruleId`, `category` |
| `Recommendation` | reuse | The remediation attached to a finding |
| `CodeMetric` | new | Complexity, LOC, fan-in/fan-out, held as a node so it can be trended |
| `BusinessDomain` | reuse | |
| `BusinessFunction` | reuse | |
| `TestCase` | new | P3, only if a test corpus exists to bind to |

The proposal listed `CodeSmell`, `PerformanceIssue`, `SecurityIssue`, `Finding` and
`Optimization` as separate labels. **Use the existing `Issue` + `Recommendation` pair instead**,
with `category` carrying `PERFORMANCE` / `SECURITY` / `CORRECTNESS` / `DEBT` — which is exactly
how the APEX rules catalogue already works (`SEC-001`, `PERF-003`, `CORR-004`, `DEBT-003`).
Five labels for what is one concept with a category property makes every "show me all findings"
query a five-way union, and every new finding type a schema change.

---

## 4. Relationship vocabulary

### 4.1 Structural

| Relationship | From → To | Status |
|---|---|---|
| `CONTAINS_FILE` | Repository / Directory → File | reuse |
| `DEFINES` | File → any database object | reuse |
| `OWNS` | DbSchema → any object | reuse |
| `HAS_COLUMN` | DbTable / DbView → DbColumn | reuse |
| `HAS_INDEX` | DbTable → DbIndex | new |
| `CONSTRAINS` | DbConstraint → DbTable / DbColumn | reuse |
| `HAS_SPEC` | DbPackage → PackageSpec | new |
| `HAS_BODY` | DbPackage → PackageBody | new |
| `HAS_UNIT` | PackageSpec / PackageBody → DbProgramUnit | reuse |
| `HAS_PARAMETER` | DbProgramUnit → Parameter | new (P2) |
| `DECLARES_CURSOR` | DbProgramUnit / PackageBody → Cursor | new (P2) |
| `DECLARES_EXCEPTION` | DbProgramUnit / PackageBody → Exception | new (P2) |

### 4.2 Dependency

| Relationship | From → To | Status |
|---|---|---|
| `CALLS` | DbProgramUnit → DbProgramUnit | reuse |
| `DEPENDS_ON` | DbView → DbTable; DbPackage → DbPackage | reuse |
| `RESOLVES_TO` | DbSynonym → target object | reuse |
| `USES_SEQUENCE` | any code object → DbSequence | reuse |
| `USES_TYPE` | DbProgramUnit → DbType | new |
| `INHERITS` | DbType → DbType | new |
| `REFERENCES_DBLINK` | any object → DbDatabaseLink | new |

### 4.3 Data access

Reused exactly. These already exist and are already finer-grained than the `READS` / `WRITES`
pair originally proposed — `WRITES_TO` alone cannot distinguish an insert from a delete, and
that distinction is what a data-lineage or retention question turns on.

| Relationship | From → To | Status |
|---|---|---|
| `READS_FROM` | SqlStatement / code object → DbTable / DbView | reuse |
| `INSERTS_INTO` | SqlStatement / code object → DbTable | reuse |
| `UPDATES` | SqlStatement / code object → DbTable | reuse |
| `DELETES_FROM` | SqlStatement / code object → DbTable | reuse |
| `WRITES_TO` | SqlStatement / code object → DbTable | reuse — roll-up of the three above |
| `REFERENCES_COLUMN` | SqlStatement → DbColumn | reuse |
| `JOINS_WITH` | SqlStatement → DbTable | new |

`WRITES_TO` is emitted **in addition to** the specific verb, not instead of it, so that
blast-radius traversal can use one edge type while lineage analysis uses the precise one. This
is the existing APEX behaviour and must not diverge.

### 4.4 Runtime and execution

| Relationship | From → To | Status |
|---|---|---|
| `FIRES_ON` | DbTrigger → DbTable | reuse |
| `EXECUTES_SQL` | code object → SqlStatement | reuse |
| `EXECUTES_PLSQL` | code object → PlsqlBlock | reuse |
| `USES_CURSOR` | DbProgramUnit → Cursor | new (P2) |
| `RAISES` | DbProgramUnit → Exception | new (P2) |
| `HANDLES` | DbProgramUnit → Exception | new (P2) |

### 4.5 Analysis and Git

| Relationship | From → To | Status |
|---|---|---|
| `HAS_ISSUE` | any node → Issue | reuse |
| `HAS_RECOMMENDATION` | Issue → Recommendation | reuse |
| `AFFECTS` | Issue → the object it concerns | reuse |
| `HAS_METRIC` | code object → CodeMetric | new |
| `IMPLEMENTED_BY` | BusinessFunction → code object | reuse |
| `PART_OF_DOMAIN` | BusinessFunction → BusinessDomain | reuse |
| `HAS_COMMIT` | Repository → Commit | reuse |
| `CHANGED` | Commit → File | reuse |
| `AUTHORED_BY` | Commit → Developer | new |

---

## 5. Identifier grammar

Ids extend the existing grammar in `analyzer_core/ids.py`. Identifiers are normalised by
`db_ident()`: unquoted, trimmed, upper-cased — except where the source used a quoted
case-sensitive identifier, which is preserved verbatim.

```
db:ORDER_APP                              schema
db:ORDER_APP.ORDERS                       table, view, sequence, synonym, type
db:ORDER_APP.ORDERS.ORDER_ID              column
db:ORDER_APP.CUSTOMER_PKG                 package
db:ORDER_APP.CUSTOMER_PKG#spec            package spec
db:ORDER_APP.CUSTOMER_PKG#body            package body
db:ORDER_APP.CUSTOMER_PKG.CREATE_CUSTOMER packaged procedure or function
db:ORDER_APP.REBUILD_INDEXES              standalone procedure or function
sql:9f2c1a4e…                             content-addressed SQL statement
plsql:3b81cc72…                           content-addressed anonymous block
file:src/customer/customer_pkg.pkb        repository-relative source file
git:8c4f21a…                              commit
```

**Overloading.** PL/SQL permits overloaded subprograms within a package, so the qualified name
is not unique on its own. Disambiguate with the dictionary's overload position, which the
`ALL_PROCEDURES` extract supplies:

```
db:ORDER_APP.CUSTOMER_PKG.GET_CUSTOMER      single, or the first overload
db:ORDER_APP.CUSTOMER_PKG.GET_CUSTOMER#2    second overload
```

**Implementation note.** `analyzer_core.ids.unit_id` already used a `#N` suffix for the
overload position, so the implementation follows that rather than the `@N` this document
first proposed; the two would otherwise be two conventions for one idea. The first overload
keeps the unsuffixed id so an unoverloaded unit and a later-overloaded one do not change id
when a second signature is added.

Where no dictionary extract is available, overloads are resolved by argument arity from source
order and the node records `overloadResolution: 'inferred'`. A `CALLS` edge that cannot be
attributed to a specific overload targets the unsuffixed id and sets `ambiguous: true` rather
than picking one arbitrarily.

---

## 6. Node properties

Every node carries the provenance the analyst needs to open the source:

| Property | Applies to | Notes |
|---|---|---|
| `id` | all | Per §5 |
| `name` | all | Unqualified object name |
| `schema` | database objects | Owner |
| `filePath` | file-backed nodes | Repository-relative, forward slashes |
| `lineStart`, `lineEnd` | code objects | 1-indexed |
| `sourceHash` | code objects | SHA-1 of normalised source, for change detection |
| `status` | dictionary-sourced objects | `VALID` / `INVALID` |
| `origin` | all | `ddl` / `dictionary` / `inferred` |
| `complexity`, `loc` | code objects | |
| `lastModified`, `lastCommit` | file-backed nodes | From Git, when available |

`origin` matters: a graph built from DDL scripts alone is a statement about the repository,
while one merged with a dictionary extract is a statement about the deployed database. They
disagree in real estates, and the disagreement is itself a finding.

**Credentials are never copied into the graph.** Connection strings in deployment scripts must
be masked on the same rule the existing analyzers apply to `password`, `secret`, `credential`
and `key`.

---

## 7. What static analysis cannot resolve

This section is normative, not a caveat. The estate's own core rule is that the tool never
invents, so the boundary must be recorded in the graph rather than papered over.

| Construct | Behaviour |
|---|---|
| `EXECUTE IMMEDIATE` with a literal | Parse the literal, bind normally |
| `EXECUTE IMMEDIATE` with concatenation | Emit `Issue` (`DYN-001`), no dependency edge, set `hasDynamicSql` |
| `DBMS_SQL` | As above |
| Ref cursor opened on a variable | No edge; `Cursor` node records `dynamic: true` |
| Synonym | `RESOLVES_TO` where the target is known; unresolved synonyms are reported |
| Remote object over a DB link | `REFERENCES_DBLINK` only. The remote object is out of scope and must not be fabricated |
| Object referenced but never defined in the tree | Recorded as unresolved; counted against coverage |

### 7.1 The coverage contract

Both existing analyzers publish a coverage figure that must be quoted before any completeness
claim — `meta.coverage.resolutionCoverage` for APEX, `meta.coverage.artifactCoverage` for
TIBCO. The Oracle analyzer publishes the same, and it is the primary honesty mechanism:

```json
"coverage": {
  "objectsDiscovered": 412,
  "objectsModelled": 401,
  "resolutionCoverage": 97.3,
  "callsResolved": 1188,
  "callsUnresolved": 44,
  "dynamicSqlSites": 17,
  "unresolvedReferences": ["ORDER_APP.LEGACY_UTIL.CLEANUP"]
}
```

Below 80% resolution the graph is provisional and every answer derived from it must say so.

---

## 8. Validation gates

Reuses `analyzer_core.graph.validate.GraphValidator` with an Oracle rule set. Beyond the
generic rules (id uniqueness, referential integrity, orphans, CSV round-trip):

| Rule | Severity | Condition |
|---|---|---|
| `package-body-without-spec` | ERROR | A `PackageBody` with no `PackageSpec` |
| `unit-not-in-package` | ERROR | `DbProgramUnit` with no `HAS_UNIT` or `OWNS` edge |
| `table-has-columns` | WARNING | `DbTable` with no `DbColumn` |
| `data-access-coverage` | ERROR | `SqlStatement` nodes exist but no data-access edges — the binder failed, and the lineage graph must not be reported as empty |
| `resolution-coverage` | WARNING | Below 80% |
| `dynamic-sql-declared` | INFO | Count of sites where dependency analysis stops |
| `invalid-objects` | WARNING | Objects the dictionary reports as `INVALID` |

`data-access-coverage` is modelled directly on the `shared-resource-coverage` rule added to the
TIBCO analyzer: it distinguishes "this code touches no tables" from "the binder did not run",
which are indistinguishable from node counts alone and lead to opposite conclusions.

---

## 9. Pipeline and CLI

Matches the two existing analyzers so the operational surface is identical.

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle \
    analyze --source <repo_root> [--db-meta db_meta.json] [--schema ORDER_APP]
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle validate
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle rules --category PERFORMANCE
```

Subcommands: `analyze`, `validate`, `rules`, `impact`, `lineage`, `diagrams`, `context`,
`report`, `queries`, `diff`, `all`.

`lineage` is the one addition to the standard surface: given a table or column, walk the
data-access edges to produce a column-level lineage report. This is the capability that
justifies materialising `SqlStatement`, and it has no equivalent in the other two dialects.

**Parsing order.** DDL and dictionary first so the schema exists, then PL/SQL sources, then
cross-references. The dictionary extract is authoritative and DDL results merge underneath it,
matching `apex_analyzer/parsers/dbmeta.py`.

---

## 10. Test fixture

**A fixture is a delivery requirement, not a follow-up.** The BW6 shared-resource defect found
in this repository was a parser that silently produced zero nodes for an entire artifact class
while validation still reported success. The APEX analyzer, which has a fixture, has no
equivalent defect. The fixture must therefore include, from day one:

- a package with separate `.pks` / `.pkb`, including one overloaded subprogram
- a standalone procedure and a standalone function
- a trigger, a view over two tables, a sequence, a synonym
- a procedure that reads one table and writes another, so all data-access verbs fire
- one `EXECUTE IMMEDIATE` built by concatenation, so the dynamic-SQL boundary is asserted
- a deliberately unresolvable call, so coverage reporting is asserted below 100%
- an obfuscated credential in a deployment script, asserted never to reach the graph

Acceptance: `python tests/test_oracle_analyzer.py` passes, `validate` reports zero errors, and
two consecutive runs produce byte-identical `graph.json` apart from `generatedAt`.

---

## 11. Phasing

**P1 — the dependency graph.** Schema objects, packages with spec/body split, program units,
call graph, data access via the existing SQL binder, Git layer, coverage reporting, validation
gates, fixture. This alone answers "what breaks if I change this table" and "which procedures
modify CUSTOMER", which is the bulk of the analytical value.

**P2 — PL/SQL internals.** Cursors, exceptions, parameters and overload resolution, `USES_TYPE`,
`JOINS_WITH`, column-level lineage.

**P3 — the intelligence layer.** `CodeMetric` trending across commits, `TestCase` binding,
business-capability mapping, and the agent context packs that assemble a graph neighbourhood
plus source plus execution statistics for an LLM.

The ordering is deliberate: P3 is the stated goal, but an agent given a graph with 60%
resolution coverage will produce confident wrong answers. The coverage and validation work in
P1 is what makes the P3 layer trustworthy.

---

## 12. Worked example

```sql
CREATE OR REPLACE PACKAGE BODY CUSTOMER_PKG AS
  PROCEDURE CREATE_CUSTOMER(p_name VARCHAR2) AS
  BEGIN
    INSERT INTO CUSTOMER (CUSTOMER_ID, NAME)
    VALUES (CUSTOMER_SEQ.NEXTVAL, p_name);
  END;

  PROCEDURE DELETE_CUSTOMER(p_customer_id NUMBER) AS
  BEGIN
    DELETE FROM CUSTOMER WHERE CUSTOMER_ID = p_customer_id;
  END;
END CUSTOMER_PKG;
```

Nodes:

| Id | Label |
|---|---|
| `db:ORDER_APP.CUSTOMER_PKG` | `DbPackage` |
| `db:ORDER_APP.CUSTOMER_PKG#body` | `PackageBody` |
| `db:ORDER_APP.CUSTOMER_PKG.CREATE_CUSTOMER` | `DbProgramUnit` |
| `db:ORDER_APP.CUSTOMER_PKG.DELETE_CUSTOMER` | `DbProgramUnit` |
| `db:ORDER_APP.CUSTOMER` | `DbTable` |
| `db:ORDER_APP.CUSTOMER_SEQ` | `DbSequence` |
| `sql:1a7f…`, `sql:c4e9…` | `SqlStatement` |
| `file:src/customer/customer_pkg.pkb` | `File` |

Relationships:

```
CUSTOMER_PKG        -[:HAS_BODY]->        CUSTOMER_PKG#body
CUSTOMER_PKG#body   -[:HAS_UNIT]->        CREATE_CUSTOMER
CUSTOMER_PKG#body   -[:HAS_UNIT]->        DELETE_CUSTOMER
File                -[:DEFINES]->         CUSTOMER_PKG#body
CREATE_CUSTOMER     -[:EXECUTES_SQL]->    sql:1a7f…
sql:1a7f…           -[:INSERTS_INTO]->    CUSTOMER
sql:1a7f…           -[:WRITES_TO]->       CUSTOMER
CREATE_CUSTOMER     -[:USES_SEQUENCE]->   CUSTOMER_SEQ
DELETE_CUSTOMER     -[:EXECUTES_SQL]->    sql:c4e9…
sql:c4e9…           -[:DELETES_FROM]->    CUSTOMER
sql:c4e9…           -[:WRITES_TO]->       CUSTOMER
ORDER_APP           -[:OWNS]->            CUSTOMER_PKG, CUSTOMER, CUSTOMER_SEQ
```

Which procedures modify `CUSTOMER`, at any call depth:

```cypher
MATCH (u:DbProgramUnit)-[:EXECUTES_SQL]->(:SqlStatement)-[:WRITES_TO]->(t:DbTable)
WHERE t.name = 'CUSTOMER'
RETURN DISTINCT u.name, u.filePath, u.lineStart
ORDER BY u.name;
```

Blast radius of a change to `CUSTOMER`, following callers back to entry points:

```cypher
MATCH path = (t:DbTable {name:'CUSTOMER'})
             <-[:READS_FROM|WRITES_TO]-(:SqlStatement)
             <-[:EXECUTES_SQL]-(:DbProgramUnit)
             <-[:CALLS*0..6]-(caller:DbProgramUnit)
RETURN caller.name, length(path) AS depth
ORDER BY depth;
```

---

## 13. Decisions needed before implementation

1. **Is a dictionary extract available?** It changes the achievable resolution materially —
   overload resolution, `INVALID` status and true dependency edges all come from it. If not,
   the analyzer is repository-only and coverage should be expected in the 80s, not the high 90s.
2. **Is there a representative Oracle repository to validate against?** Neither existing
   analyzer's quality is established by its fixture alone. Nothing in this specification should
   be considered proven until it has run against a real estate.
3. **Scope of `JOINS_WITH`.** Full join-graph extraction requires a real SQL grammar; the
   current binder is regex-based and deliberately limited. Either accept partial join coverage
   with explicit reporting, or take a dependency on a parser — which conflicts with constraint
   2 in §2.
4. **Does the business layer have a source?** `BusinessDomain` and `BusinessFunction` are only
   useful if something authoritative maps them. Inferring them from naming conventions produces
   confident nonsense.
