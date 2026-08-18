# APEX graph model

The vocabulary is closed and lives in code: `tools/apex_analyzer/constants.py` is the
definition, and `tools/apex_analyzer/graph/validate_rules.py` fails the build on any label
or relationship type outside it. This guide explains that vocabulary; when the two
disagree, the code is right.

## Layers

| Layer | Labels |
|---|---|
| Repository | `Project`, `Repository`, `Branch`, `Commit`, `File` |
| Application | `ApexWorkspace`, `ApexApplication`, `ApexBuildOption`, `ApexAuthentication`, `ApexAuthorization` |
| Page components | `ApexPage`, `ApexRegion`, `ApexItem`, `ApexButton`, `ApexProcess`, `ApexValidation`, `ApexBranch`, `ApexComputation`, `ApexDynamicAction`, `ApexDaAction`, `ApexReportColumn` |
| Shared components | `ApexLov`, `ApexList`, `ApexListEntry`, `ApexNavigation`, `ApexWebSource`, `ApexWebSourceOperation`, `ApexAutomation`, `ApexPlugin`, `ApexEmailTemplate` |
| Code | `SqlStatement`, `PlsqlBlock`, `JsSnippet`, `BindVariable` |
| Database | `DbSchema`, `DbTable`, `DbView`, `DbMaterializedView`, `DbPackage`, `DbProgramUnit`, `DbTrigger`, `DbSequence`, `DbSynonym`, `DbType`, `DbDatabaseLink`, `DbColumn`, `DbConstraint`, `DbIndex` |
| Semantic | `BusinessDomain`, `BusinessFunction`, `BusinessTransaction` |
| Analysis | `Issue`, `Recommendation`, `Metric` |

Database objects carry a second label, `:DbObject`, so `MATCH (o:DbObject)` reaches
all of them. A name the analyzer could not resolve becomes `:DbObject:Unresolved`
rather than a dropped edge.

## The relationships that answer questions

| Question | Path |
|---|---|
| What does this page depend on? | `(:ApexPage)-[:CONTAINS_*]->(component)-[:EXECUTES_SQL\|EXECUTES_PLSQL]->(code)-[:READS_FROM\|WRITES_TO\|CALLS]->(:DbObject)` |
| Which pages use this column? | `(:DbColumn)<-[:REFERENCES_COLUMN]-(user)<-[*1..6]-(:ApexPage)` |
| What does this button do? | `(:ApexButton)-[:TRIGGERS]->(:ApexProcess)-[:EXECUTES_PLSQL]->(:PlsqlBlock)` |
| How does a user reach this page? | `()-[:NAVIGATES_TO]->(:ApexPage)` |
| Is this page protected? | `(:ApexPage)-[:SECURED_BY]->(:ApexAuthorization)` |
| What did this release change? | `(:Commit)-[:CHANGED]->(:File)-[:DEFINES]->(component)` |

`SOURCED_FROM` matters as much as `READS_FROM`: a form or interactive grid names its
table declaratively and has no SQL at all, so a SQL-only reading of the application
misses it.

## Identity

Ids are natural keys, not counters, which is what makes two releases comparable:

```
app100                      application
app100:p10                  page 10
app100:p10:r1001            region 1001 on page 10
app100:p10:iP10_ORDER_ID    item P10_ORDER_ID
app100:lov:CUSTOMER_LOV     shared list of values
sql:9f2c1a…                 SQL statement, content addressed
db:ORDER_APP.ORDERS         table
db:ORDER_APP.ORDERS.ORD_ID  column
issue:SEC-002:app100:p20    a finding on page 20
```

## Provenance — read this before quoting an edge

Every node carries `origin`: `export`, `dictionary`, `derived`, `git` or `llm`.
Every *inferred* relationship also carries `confidence` (0–1) and `resolution`:

| `resolution` | Meaning | `confidence` |
|---|---|---|
| `exact` | `OWNER.OBJECT` found in the extract | 1.00 |
| `schema_default` | unqualified, found in the parsing schema | 0.95 |
| `synonym` | resolved through a synonym | 0.90 |
| `heuristic` | unique match in another schema | 0.70 |
| `dynamic` | SQL assembled at runtime | 0.40 |
| `unresolved` | no match — edge points at `:Unresolved` | 0.00 |

An answer that treats a 0.40 edge like a 1.00 edge is wrong even when the graph is
right. Say which it is.

## What is deliberately not modelled

Lines, tokens, variables, individual LOV entries, themes and templates. If a
question only ever reads something as an attribute of its parent, it is a property,
not a node.
