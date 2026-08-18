---
mode: agent
description: Federate the TIBCO, APEX and Oracle analyses into one graph and write the narrative sections of the cross-estate reports.
---

# Bootstrap a cross-estate analysis

Join three finished analyses, then complete the narrative sections of the reports the
wrapper scaffolds. Do not write a single number the analyzer did not produce, and do
not assert a cross-estate dependency the join did not make.

## 1. Confirm the three estates are analysed

The wrapper reads finished graphs and parses nothing. All three must exist and must
have passed their own gate:

```bash
PYTHONPATH=tools python -m tibco_analyzer  -o analysis_output        validate
PYTHONPATH=tools python -m apex_analyzer   -o analysis_output_apex   validate
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle validate
```

If any reports FAIL, stop. A federated answer built on an untrustworthy input is an
untrustworthy answer with three times the reach.

## 2. Federate

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate all \
  --tibco ${input:tibcoOutput:analysis_output} \
  --apex ${input:apexOutput:analysis_output_apex} \
  --oracle ${input:oracleOutput:analysis_output_oracle} \
  ${input:estateMap: optional --estate-map estate_map.json}
```

Check three numbers in the output before going further:

| Number | If it is zero |
|---|---|
| shared database nodes | the APEX and Oracle analyses cover different schemas. That join needs no heuristic, so zero means they do not overlap — say so rather than reporting one estate as if it were both |
| inferred links added | the TIBCO estate does not reach the analysed database, or no estate map was supplied. Check the datasource table in `links` before concluding the estates are unrelated |
| datasource coverage | no estate map. Everything behind every JDBC resource is missing from the graph |

If `validate` reports FAIL, stop and quote the failing rules. WARN on
`sql-bind-coverage` or `datasource-coverage` is expected on most real estates and is
not a reason to stop — it is a reason to caveat.

## 3. Read, in this order

1. `analysis_output_estate/context/estate-facts.md` — what each estate contributed and
   what the join produced
2. `analysis_output_estate/context/cross-estate-links.md` — every boundary-crossing
   edge with its basis and confidence
3. `analysis_output_estate/context/shared-data.md` — objects more than one estate
   touches, and which are contended
4. `analysis_output_estate/context/boundary-components.md` — artefacts that cannot be
   understood from inside one estate
5. `analysis_output_estate/context/findings.md` — the merged, namespaced ledger
6. `analysis_output_estate/context/sequence.md` — the derived cutover order
7. `analysis_output_estate/context/unresolved.md` — **what the join could not do**

Read 7 before you write anything. It is the list of things that would change your
conclusions if they were resolved.

## 4. Complete the reports

In `analysis_output_estate/reports/`, fill only the sections marked
`<!-- LLM: ... -->`, leaving the marker in place and every generated table untouched:

- **Step00 — Federated Estate Graph.** What this estate is as one system. Which estate
  is the centre of gravity and which is peripheral. What the coverage figures mean for
  confidence in everything that follows. If the TIBCO leg contributed no links, say
  that plainly and give the reason from the datasource table.
- **Step01 — Cross-Estate Dependencies.** Which dependencies a single-estate analysis
  would have missed, and what that would have cost. Name the components, cite the
  confidence, and list which links still need confirming by hand.
- **Step02 — End-to-End Risk and Sequence.** What must be settled before anything
  moves, taken from wave 0. Which components must cut over together and why. What can
  move independently and is therefore the sensible place to start.

## 5. State the caveats

Open your summary with:

- `sqlBindCoverage` and `datasourceCoverage`, and whether either is below 80 %
- the weakest upstream estate's own coverage — the federation is never stronger than
  its weakest input, and an average would hide that
- the count of unmapped datasources, unbound references and runtime-SQL activities

Then name what this analysis structurally cannot join, so nobody reads its silence as
evidence:

- service-mediated coupling — TIBCO calling an APEX REST service, or an APEX web
  source calling TIBCO
- message and file coupling — JMS destinations, FTP and file hand-offs
- TIBCO stored-procedure calls, and TIBCO dependency below table granularity
- anything assembled at runtime

Close with the single change that would most improve the answer. On most estates that
is one more entry in `estate_map.json`.
