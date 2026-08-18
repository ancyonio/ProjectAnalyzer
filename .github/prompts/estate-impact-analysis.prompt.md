---
mode: agent
description: Assess the blast radius of a change across TIBCO, Oracle APEX and Oracle PL/SQL at once.
---

# End-to-end change impact

Target: `${input:target:e.g. DbTable:ORDERS, DbColumn:STATUS_CODE, BWProcess:OrderIntake, ApexPage:Orders}`

## 1. Resolve the target

`--target` accepts a node id, an exact name, or a `Label:Name` pair. An ambiguous
target lists its candidates — pick one by node id. Do not analyse a phrase like "the
orders table".

Shared database objects keep their natural key, so `DbTable:ORDERS` resolves to the
one node both database estates contributed. Everything else is namespaced by estate:
`tibco:bwp_0003`, `apex:app100:p20`, `oracle:file:packages/audit_pkg.pkb`.

## 2. Run upstream

Upstream is "who depends on this", which is the blast radius:

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate \
  impact --target "${input:target}" --depth 8 --direction upstream \
  --save analysis_output_estate/impact/${input:slug:short-name-for-the-files}
```

Run `--direction downstream` separately if the question is what the target itself
consumes. Never add the two directions' counts together.

## 3. Establish how far the change travels

Before writing anything, answer two questions from the output:

- **How many estates does it cross?** The report's impact-by-estate table is the
  headline. A radius confined to one estate is a team's decision; a radius crossing
  two or three is a programme's.
- **How confident is each crossing?** Run `links` and check the basis of every
  cross-estate edge on a reported path. Anything at `name` (0.5) is a candidate, not a
  fact, and must be confirmed by hand before anyone plans around it.

## 4. Report, in this order

| Section | Content |
|---|---|
| Target | how it resolved, its node id, and which estates contributed it |
| Estates crossed | the impact-by-estate table, and what that implies for ownership |
| Risk band | band, score, and what drives the score |
| Entry points affected | APEX pages, TIBCO processes and exposed services, published Oracle spec units and triggers — with hop counts. This is the headline, not the total artefact count |
| Crossing confidence | every cross-estate edge on a path, with basis and confidence; call out every 0.5 |
| Contract breaks | a `PackageSpec` change breaks every caller; a `PackageBody` change does not. Say which one this is |
| Contention | whether the target is written by more than one estate (finding `XE-001`). If it is, no single team can cut it over |
| What else breaks | remaining impacted artefacts, grouped by estate |
| Test scope | the report's buckets verbatim, with the owning team for each |
| Diagram | the saved `.mmd` blast radius |

## 5. State the confidence

Quote `sqlBindCoverage` and `datasourceCoverage`. If either is below 80 %, or if any
activity in the unbound list reaches this target's schema, the true blast radius is
**larger** than the number you are quoting. Say so in those words.

Quote the weakest upstream estate coverage too. A federated radius over an
80 %-resolved Oracle graph is an 80 %-resolved radius, however many estates it spans.

## 6. Close with what the analysis cannot see

- Service-mediated coupling: a TIBCO process calling an APEX REST endpoint, or an
  APEX web source calling TIBCO, is not joined
- Message and file coupling: JMS, FTP and file hand-offs are never joined across
  estates
- TIBCO stored-procedure calls, and TIBCO dependency below table granularity — a
  column-level target is precise for APEX and Oracle and coarse for TIBCO
- SQL assembled at runtime, and anything reached only from there
- Schemas, modules and applications outside the three analyses
- Grants, privileges, row-level security, execution plans, data volumes, latency

Then recommend go / staged / hold, say which estate must move first and why, and name
the one condition that would change the recommendation.
