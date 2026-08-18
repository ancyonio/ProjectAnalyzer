---
mode: agent
description: Complete Step02 — write business flow documentation, the risk register and success criteria from the per-process context packs.
tools: ['codebase', 'terminal']
---

# Step 02 — discover and baseline

Fill the three narrative slots in
`${input:outputDir:analysis_output}/reports/Step02_DISCOVER_AND_BASELINE_REPORT.md`:
Section 8 "Business Flow Documentation", Section 9 "Risk Register", Section 10
"Success Criteria".

## Preconditions

```bash
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} validate
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} context
PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} report
```

Stop on a FAIL validation and report the failing rules.

## Procedure

1. **List the entry points you must document.** They are in Section 2 of the report and in
   `context/entry-points.md`. Every entry point gets a subsection in Section 8 — no more, no
   fewer.

   ```bash
   ls -1 ${input:outputDir:analysis_output}/context/processes/
   ```

2. **Open the context pack for each entry-point process before writing about it.**

   ```bash
   cat ${input:outputDir:analysis_output}/context/processes/<ProcessName>.md
   ```

   Each pack contains: the process header (module, entry type, tier, complexity, file path),
   activities in execution order with their type and Spring target, the control flow
   (transitions, including error transitions), the schemas used and the shared resources.
   If a called process has its own pack, open that too before describing what happens inside it.

   Only the top processes by complexity get a pack. If an entry point has none, get its facts
   from the report's own tables plus:

   ```bash
   PYTHONPATH=tools python -m tibco_analyzer -o ${input:outputDir:analysis_output} \
     search "<ProcessName>" --label BWProcess --top 3
   ```

   and say in the subsection that no context pack exists for it.

3. **Write Section 8, Business Flow Documentation.** One subsection per entry point:

   ```
   ### <ProcessName> — <entryType> (<module>)

   **Trigger:** <entry type and endpoint, or "endpoint not captured in the source">
   **Contract in / out:** <schemas from the pack>
   **Happy path:** numbered steps, one per activity in execution order, naming the activity
     and its type; note each called process and each external system touched.
   **Branching:** each conditional transition and its condition as parsed; if the condition
     expression is not captured, say so.
   **Fault paths:** each error transition and error handler; if the pack lists none, write
     "no error transition parsed — failure behaviour is undefined in the source".
   **Spring Boot target:** the targets already mapped in the pack and in Section 2.
   ```

   Describe the flow in TIBCO terms, not in terms of what you assume the business does. A
   business meaning that is not in an artefact name, an endpoint or a schema element does not
   go in.

4. **Write Section 9, Risk Register.** One table, sourced from the tables already in the report
   and in `context/complexity.md`:

   | # | Risk | Source evidence | Likelihood | Impact | Mitigation | Owner |
   |---|---|---|---|---|---|---|

   Populate it from, at minimum:

   - change hotspots (`context/complexity.md`) — high-fan-in artefacts;
   - circular dependencies — each cycle is one risk row, since it blocks incremental cutover;
   - error-handling gaps (Section 6) — each listed process;
   - integration surface (Section 3) — each adapter category with no direct Spring equivalent;
   - contract freeze (Section 4) — schemas with several consumers;
   - dead code (Section 7) — the risk of migrating out-of-scope artefacts.

   Rules: "Source evidence" cites the report section and the measured value. Likelihood and
   impact are High/Medium/Low and must be justified by that evidence. Owner is a role
   ("Integration lead", "Data owner"), never a person's name.

5. **Write Section 10, Success Criteria.** Measurable parity criteria, one block per entry
   point in Section 2:

   | Criterion | Target | How it is verified |
   |---|---|---|

   Cover, per entry point: contract preservation (the exact namespaces and root elements from
   Section 4 — unchanged), functional parity per branch documented in Section 8, error-response
   parity for each fault path, and test coverage of the activities listed in the context pack.

   Latency, throughput and error-rate budgets have **no measured baseline in this analysis**.
   Include them as rows with the target marked `TBD — requires production baseline`, and state
   plainly that the analyzer cannot supply them.

6. **Self-check** against `.github/copilot-instructions.md` §9. Confirm every process, activity,
   schema and system named in your three sections appears in a context pack or a generated
   table.

## Acceptance criteria

- Section 8 has exactly one subsection per entry point listed in Section 2.
- No process is described whose context pack (or search result) you did not open.
- Every risk row cites a section and a value from this report.
- Success criteria distinguish what is verifiable from the analysis from what needs a
  production baseline.
- Only the three `<!-- LLM: … -->` slots changed; the markers remain in place.

## Do not

- Do not read raw `.process` XML to embellish a flow description.
- Do not assign numeric latency or throughput targets — no baseline exists.
- Do not invent business semantics, SLAs, regulatory drivers or stakeholders.
- Do not edit Sections 1-7 or 11, which are generated.
- Do not merge or skip entry points because they look similar.
