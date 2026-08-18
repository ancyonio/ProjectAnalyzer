---
mode: agent
description: Assess the blast radius of changing an Oracle database object or program unit.
---

# Oracle change impact

Target: `${input:target:e.g. DbTable:ORDERS, DbProgramUnit:CREATE_CUSTOMER, DbPackage:CUSTOMER_PKG}`

## 1. Resolve the target

`--target` accepts a node id, an exact name, or a `Label:Name` pair. If the command
reports an ambiguous target it lists the candidates — pick one by node id. Do not
analyse a phrase like "the orders table".

## 2. Run upstream

Upstream is "who depends on this", which is the blast radius:

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle \
  impact --target "${input:target}" --depth 8 --direction upstream \
  --save analysis_output_oracle/impact/${input:slug:short-name-for-the-files}
```

Run `--direction downstream` separately if the question is what the target itself
consumes. Never add the two directions' counts together.

## 3. Report, in this order

| Section | Content |
|---|---|
| Target | how it resolved, with its node id |
| Risk band | band, score, and what drives the score |
| Entry points affected | published spec units, standalone units and triggers, with hop counts — this is the headline, not the total artefact count |
| Contract break? | whether the change touches a `PackageSpec`; if it does, every caller of every unit it publishes is affected |
| What else breaks | the remaining impacted objects by type |
| Test scope | the report's buckets, verbatim |
| Diagram | the saved `.mmd` blast radius |

## 4. State the confidence

Quote `graph.meta.coverage.callResolution` and `resolutionCoverage`. If either is
below 80 %, or if any unit on a reported path carries `hasDynamicSql`, the true blast
radius is **larger** than the number you are quoting. Say so in those words.

## 5. Close with what the analysis cannot see

- SQL assembled at runtime, and anything reached only from there
- ORDS endpoints, scheduled jobs, external batch and other schemas not analysed here
- Grants, row-level security and privileges
- Execution plans, lock contention, data volumes and latency
- When `dictionaryAvailable` is false: anything deployed that is not in the repository

Then recommend go / staged / hold, and name the condition that would change the
recommendation.
