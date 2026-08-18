---
mode: agent
description: Run the full APEX analysis pipeline and write the narrative sections of the generated reports.
---

# Bootstrap an APEX analysis

Run the whole pipeline, then complete the narrative sections of the reports it
scaffolds. Do not write a single number that the analyzer did not produce.

## 1. Run the pipeline

```bash
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex all \
  --source ${input:exportRoot:path to the APEX export (split export directory or f100.sql)} \
  ${input:dbMeta: optional --db-meta db_meta.json}
```

If `validate` reports FAIL, stop. Report the failing rules and say the graph is not
trustworthy yet.

## 2. Read, in this order

1. `analysis_output_apex/context/application-facts.md` — size and coverage
2. `analysis_output_apex/context/pages.md` — every page with its metrics
3. `analysis_output_apex/context/data-access.md` — page-to-table access
4. `analysis_output_apex/context/security.md` — authorization posture
5. `analysis_output_apex/context/findings.md` — rule findings

## 3. Complete the reports

In `analysis_output_apex/reports/`, fill only the sections marked
`<!-- LLM: ... -->`, leaving the marker in place and leaving every generated table
untouched:

- **Step00** — what the application is, what drives complexity on the top pages, and
  what that means for change risk.
- **Step01** — which tables and packages carry the highest change risk, and which
  "dead" components are genuinely dead versus reachable by a path the analyzer
  cannot see (dynamic SQL, ORDS, scheduled jobs).
- **Step02** — remediation themes, their sequence, and what must be fixed before the
  next release. Correct the derived business-function seed, keeping its evidence.

## 4. State the caveats

Open your summary with the coverage figure and the ingestion mode. If no database
extract was available, say that the database layer came from committed DDL only and
name what that leaves out (row counts, synonyms, `ALL_DEPENDENCIES` confirmation).
