---
mode: agent
description: Run the full Oracle PL/SQL analysis pipeline and write the narrative sections of the generated reports.
---

# Bootstrap an Oracle analysis

Run the whole pipeline, then complete the narrative sections of the reports it
scaffolds. Do not write a single number that the analyzer did not produce.

## 1. Run the pipeline

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle all \
  --source ${input:sourceRoot:path to the Oracle source repository} \
  --schema ${input:schema:default owner for unqualified objects, e.g. ORDER_APP} \
  ${input:dbMeta: optional --db-meta db_meta.json}
```

If `validate` reports FAIL, stop. Report the failing rules and say the graph is not
trustworthy yet.

Sanity-check `--schema` before going further: if the inventory lists schemas you did
not expect, unqualified objects have been scattered and resolution is understated.

## 2. Read, in this order

1. `analysis_output_oracle/context/estate-facts.md` — size, schemas and coverage
2. `analysis_output_oracle/context/packages.md` — every package, spec and body status
3. `analysis_output_oracle/context/entry-points.md` — what the outside world can call
4. `analysis_output_oracle/context/data-access.md` — unit-to-table access and hotspots
5. `analysis_output_oracle/context/complexity.md` — what is hardest to move
6. `analysis_output_oracle/context/findings.md` — rule findings
7. `analysis_output_oracle/context/unresolved.md` — the graph's known gaps

## 3. Complete the reports

In `analysis_output_oracle/reports/`, fill only the sections marked
`<!-- LLM: ... -->`, leaving the marker in place and leaving every generated table
untouched:

- **Step00** — what the estate is, its shape, how much of it is reachable from
  outside, and what the coverage figures mean for confidence in everything that
  follows.
- **Step01** — which objects carry the highest change risk and why, using fan-in from
  the hotspots table. Say which "dead" units are genuinely dead versus reachable by a
  path the analyzer cannot see: dynamic SQL, ORDS, scheduled jobs, another schema.
- **Step02** — remediation themes, their sequence, and what must be fixed before
  migration versus what can be carried.

## 4. State the caveats

Open your summary with both coverage figures — `resolutionCoverage` and
`callResolution` — and with whether a dictionary extract was available.

If it was not, say plainly that the database layer came from committed DDL only, and
name what that leaves out: row counts (so `PERF-003` cannot fire), `INVALID` status
(so `DEBT-003` cannot fire), true `ALL_DEPENDENCIES` edges, and overload positions,
which are inferred from source order instead.

Name every unit carrying `hasDynamicSql`. Those are the points where the dependency
graph stops, and any completeness claim that crosses one is provisional.
