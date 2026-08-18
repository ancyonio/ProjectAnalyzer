---
mode: agent
description: Review an Oracle PL/SQL estate's security and correctness posture from the deterministic rule findings.
---

# Oracle PL/SQL security review

## 1. Collect the findings

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle rules \
  --category SECURITY --json
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle rules \
  --category CORRECTNESS --min-severity HIGH
```

Then read `analysis_output_oracle/context/findings.md` for the whole set, and
`context/unresolved.md` for the gaps, not only where a rule fired.

## 2. Rank

Order by severity, then by whether the affected unit writes to the database, then by
how many tables it reaches (`context/data-access.md`).

`SEC-001` is always first and is never a style comment. It carries two distinct
problems at once:

1. **an injection surface** — a value concatenated into the statement is not bound; and
2. **a hole in the dependency graph** — the unit's real reads and writes are unknown,
   so every completeness claim that crosses it is provisional.

Report both. A review that treats it only as an injection risk understates it.

## 3. For each finding, report

| Field | From |
|---|---|
| What is wrong | the rule's `description` |
| Where | node id, `filePath`, `lineStart` |
| Why it matters here | the tables and data the unit actually reaches |
| Fix | the linked `:Recommendation`, made specific to this unit |

## 4. Cover what rules cannot

State these explicitly, from the context packs rather than from a rule:

- units that commit inside a call chain other units depend on (transaction control
  taken away from the caller);
- `WHEN OTHERS` handlers that log but do not re-raise — `CORR-001` catches only the
  `THEN NULL` form;
- writes to tables with no constraint coverage in the graph;
- objects reachable through a public synonym, which widens the surface beyond what
  the schema list suggests;
- database links, which move part of the dependency outside this database entirely.

## 5. Caveats

Say plainly that this review covers what is **statically visible in the analysed
source**. It does not cover:

- grants, roles, privileges or row-level security — none of which are modelled;
- runtime authorisation decisions;
- ORDS endpoints, scheduled jobs or external batch;
- anything reached through dynamic SQL — name every unit carrying `hasDynamicSql`.

If no dictionary extract was supplied, add that `DEBT-003` (invalid objects) and
`PERF-003` (large-table reads) could not fire at all, so a clean result on those two
is an absence of evidence, not evidence of absence.
