---
applyTo: "**/estate_map.json,**/analysis_output_estate/**"
description: Rules that fire when the estate map or a federated output artefact is open.
---

# You are looking at a cross-estate artefact

Two very different kinds of file match this rule, and they need opposite treatment.

## `estate_map.json` — hand-authored, and the most consequential file here

This is the one input to the federation a human writes. Everything else the wrapper
uses is generated.

It exists because **a JDBC url names a database, not an Oracle schema**. Nothing in
`jdbc:oracle:thin:@orders-db.internal:1521/ORDERS` says whether that database serves
`ORDER_APP`, `SALES` or six schemas at once, and the wrapper refuses to guess. So the
mapping is declared:

```json
{
  "datasources": [
    { "resource": "sync.OrderApp_JDBCConnectionResource", "schema": "ORDER_APP",
      "note": "why you believe this" },
    { "resourceUrlContains": "legacy-db.internal", "schema": "ORDER_APP" }
  ]
}
```

| Key | Matches |
|---|---|
| `resource` | the shared resource's `qualifiedName`, else its `name` |
| `resourceUrlContains` | a substring of the resource's JDBC url |
| `schema` | the Oracle owner, as it appears in `db:<OWNER>` |

### Do

- **Take the resource names from the graph, not from the file system.** Run
  `estate-analyze links` and read the datasource table at the bottom: it lists every
  JDBC resource the TIBCO analysis found, its url, and whether it is mapped. An entry
  whose `resource` matches nothing is silently inert.
- **Write the `note`.** Six months from now the mapping is the only record of why
  anyone believed that database was that schema. A mapping without a rationale is a
  guess with better formatting.
- **Verify after editing.** Re-run `federate` and check `datasourceCoverage` moved,
  and that `sqlBindCoverage` moved with it. A mapping that changes neither matched
  nothing.

### Do not

- Do not add a mapping to make a coverage figure look better. A wrong `schema` binds
  TIBCO activities to the wrong tables, and the resulting edges carry confidence 0.8 —
  they will be believed. An unmapped datasource is finding `XE-005` and is honest; a
  wrongly mapped one is a defect that looks like an answer.
- Do not map a resource to a schema no analysed Oracle or APEX estate covers. The
  wrapper drops the mapping and reports the resource as unmapped, which is correct but
  easy to miss.
- Do not use `resourceUrlContains` when `resource` would do. It is there for estates
  that name resources inconsistently, and it will match more than you intend.

## Anything under `analysis_output_estate/` — generated, never hand-edited

`graph.json`, `links.json`, `neo4j_*`, `context/`, `generated_diagrams/`, `reports/`
and both validation reports are reproducible output of `estate-analyze`.

- Do not hand-edit a table, a count, a diagram or a link. If one looks wrong, the fix
  belongs in `tools/estate_analyzer/` — the matcher is in `links.py`, the merge in
  `federate.py`, the rules in `analysis/rules_catalog.py`.
- In the step reports, fill only the sections marked `<!-- LLM: ... -->` and leave the
  marker in place.
- Do not treat this directory as a substitute for the three upstream ones. It contains
  no fact an analyzer did not produce, except the joins themselves.

## Reading `links.json` correctly

This file is the audit trail for the join, and it has four sections that are commonly
confused:

| Section | Meaning |
|---|---|
| `links` | edges added to the graph, each with `basis`, `confidence` and the SQL that evidenced it |
| `suppressed` | matches that were found and deliberately withheld — bare-name guesses, admitted only under `--allow-name-match` |
| `unbound` | references that resolved to nothing, with the reason: `no-such-object`, `ambiguous-name`, `no-static-sql` |
| `datasources` | every JDBC resource and whether the estate map reached it |

`unbound` is the section that matters most when someone is about to say a table has
no integration touching it. Read it before making any negative claim.

## The coverage contract

`graph.meta.coverage` carries `sqlBindCoverage` and `datasourceCoverage`, both gated at
80 %, alongside the three upstream estates' own coverage under `coverage.estates`.

Below either gate the federated graph is provisional, and every answer drawn from it
must say so — the same contract as `resolutionCoverage` in the Oracle and APEX
analyses and `artifactCoverage` in the TIBCO one.

Activities that build SQL at runtime are excluded from the coverage denominator and
counted separately as `noStaticSqlSites`. That is deliberate: a blind spot must be
reported as a blind spot, not averaged into a slightly lower score.

## If a joined edge looks wrong

Check its `basis` first.

- `exact` — the two graphs used the same natural key. If that is wrong, two different
  objects share an id, which is a defect in `analyzer_core.ids`.
- `declared` — the estate map said so. Fix the map.
- `qualified-name` — the owner came from the SQL or the mapped datasource. Check the
  `evidence` field, which holds the statement.
- `name` — a bare-name guess. These are suppressed by default; if one is in the graph,
  someone passed `--allow-name-match`.

After changing the matcher, re-run the federation test — its expected join is written
down in `tests/fixtures/estate/expected_links.json` before the matcher runs, so a
matcher that becomes more eager fails a test rather than quietly inflating coverage:

```bash
python tests/test_estate_analyzer.py
```
