# Rule catalogue

Deterministic rules run by `tibco-analyze rules`. Each produces an `:Issue` node
linked by `HAS_ISSUE` to the artefact that triggered it, by `AFFECTS` back to that
artefact, and by `HAS_RECOMMENDATION` to a `:Recommendation`. An agent explains and
prioritises these; it does not re-detect them.

The catalogue lives in `tools/tibco_analyzer/analysis/rules_catalog.py`. Rule ids are
stable — adding a rule takes the next free ordinal, and ids are never reused.

**The same ordinal means something different in each estate.** `SEC-001` is a
credential in a shared resource here, dynamic SQL in Oracle, and something else again
in APEX. The federated ledger namespaces them (`TIB.SEC-001`); an answer that spans
estates must do the same or it will attribute a finding to the wrong system.

| Rule | Category | Severity | Triggers when | Recommended action |
|---|---|---|---|---|
| `SEC-001` | SECURITY | HIGH | A shared resource carries a credential inline | Move it to a module property supplied at deployment, or to the platform credential store. |
| `SEC-002` | SECURITY | HIGH | A secret-named global variable ships with a default value | Leave the default empty and inject per environment, or mark it service-settable. |
| `SEC-003` | SECURITY | MEDIUM | A resource points at `localhost` / `127.0.0.1` / `::1` | Replace the literal host with a module property, so one artefact deploys to every environment. |
| `CORR-001` | CORRECTNESS | HIGH | A process calls out (JDBC, HTTP, SOAP, JMS, FTP, mail, file) but defines no error handler | Catch the faults those activities raise and decide explicitly: retry, compensate, or dead-letter. |
| `CORR-002` | CORRECTNESS | MEDIUM | A process has no starter and nothing calls it | Confirm it is invoked from a module outside this analysis; if not it is dead, and should be removed rather than migrated. |
| `PERF-001` | PERFORMANCE | MEDIUM | A JDBC activity uses `SELECT *` | Name the columns the mapping uses — it documents the data contract and stops a schema change breaking the transformation. |
| `DEBT-001` | TECH_DEBT | LOW | A process is neither called nor exposed within the tree | Confirm it is reachable from outside before migrating it. |
| `DEBT-002` | TECH_DEBT | LOW | A shared resource nothing references | Remove it, or record why it is kept — an unused connection still has to be provisioned at deployment. |
| `DEBT-003` | TECH_DEBT | MEDIUM | An artefact is referenced but was not found in the scanned tree | Supply the missing module, or retire the stale reference. Until then the dependency is missing from every blast radius. |

Note the category token is `TECH_DEBT` here, not `DEBT` as in the Oracle catalogue.
`--category TECH_DEBT` is what the TIBCO CLI accepts.

## Two pairs that are easy to confuse

**`CORR-002` and `DEBT-001` are not the same finding.** `CORR-002` is a process with
**no starter at all** — nothing in any estate can invoke it, so it cannot run.
`DEBT-001` has a starter, so it *does* run; it is simply not part of any flow this
tree shows. The first is broken, the second may be an entry point you cannot see.
Recommending deletion for the second without checking outside the tree is how a live
interface gets decommissioned.

**`SEC-001` records a boolean, never a value.** The parser sets
`hasEmbeddedCredential` and stops; the secret is not copied into the graph, and
TIBCO's `#!` obfuscation is reversible but is never reversed here. An answer can say
a credential is present and where — never what it is.

## What these rules cannot see

Every rule reads only what the parsers established. Three consequences worth stating
in any answer built on them:

- **A process reached only from outside the analysed modules looks dead.** `CORR-002`
  and `DEBT-001` both depend on the tree being complete. Cross-check
  `context/unresolved.md` before recommending removal.
- **`PERF-001` only sees static SQL.** An activity that builds its statement at
  runtime carries no `sqlStatement`, so it cannot trigger this rule — and its absence
  is not evidence the query is well-formed.
- **`DEBT-003` is the honest edge of the analysis.** Each one is a dependency the
  graph knows exists and cannot follow. Treat the count as a confidence signal on
  every completeness claim, not as a backlog item.

## Using them

```bash
tibco-analyze rules --category SECURITY --min-severity HIGH
tibco-analyze rules --rule SEC-001 --json
tibco-analyze rules --module OrderModule
tibco-analyze rules --fail-on HIGH          # exit 2 in CI
```

The severity breakdown printed under a filtered run describes the findings actually
shown, and names how many the filter hid. Severity is fixed by the rule, not by the
finding: judgement about *this* estate belongs in your narrative, not in a rewritten
severity.
