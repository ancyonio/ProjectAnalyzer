---
mode: agent
description: Review the APEX application's security posture from the deterministic rule findings.
---

# APEX security review

## 1. Collect the findings

```bash
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex rules \
  --category SECURITY --json
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex rules \
  --category CORRECTNESS --min-severity HIGH
```

Then read `analysis_output_apex/context/security.md` for the authorization posture as
a whole, not only where a rule fired.

## 2. Rank

Order by severity, then by whether the affected page writes to the database, then by
how many tables it reaches. `SEC-001` (injection through concatenated dynamic SQL) is
always first and is never a style comment.

## 3. For each finding, report

| Field | From |
|---|---|
| What is wrong | the rule's `description` |
| Where | page id, component name, `sourceFile` |
| Why it matters here | the tables and data the component actually reaches |
| Fix | the linked `:Recommendation`, made specific to this component |

## 4. Cover what rules cannot

State these explicitly, from `context/security.md` rather than from a rule:

- pages with no authorization scheme that only read (lower risk, still a gap);
- authorization schemes defined but applied nowhere;
- items holding key values with no session state protection;
- public pages, and whether being public is intentional.

## 5. Caveats

Say plainly that this review covers what is statically visible in the export and the
schema extract. It does not cover runtime authorization decisions, ORDS endpoints,
database privileges, or anything reached through dynamic SQL — and name any
`resolution: dynamic` component that makes a finding uncertain.
