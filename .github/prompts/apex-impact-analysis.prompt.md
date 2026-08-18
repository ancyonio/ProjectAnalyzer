---
mode: agent
description: Work out the blast radius of changing an APEX component, a table, a view or a package procedure.
---

# APEX impact analysis

Target: `${input:target:e.g. DbTable:ORDERS, DbProgramUnit:CREATE_ORDER, ApexPage:Order Details}`

## 1. Compute it — do not reason it out by hand

```bash
PYTHONPATH=tools python -m apex_analyzer -o analysis_output_apex impact \
  --target "${input:target}" --direction upstream --depth 8 \
  --save analysis_output_apex/impact/${input:slug:short-name-for-the-file}
```

If the target is ambiguous the command lists the candidates; re-run with the node id
or `--label`.

## 2. Report

1. **Answer first:** how many pages are affected and which, by name and page id.
2. **The chain:** for the two or three most affected pages, the actual path
   (`page → region → SQL → table`) from the report's `via` column.
3. **Risk band and score,** quoted from the report, with the note that the score is
   comparative rather than absolute.
4. **Test scope:** the buckets the report produced, unedited in substance.
5. **Confidence:** if any edge on the path has `resolution: dynamic` or `unresolved`,
   say so — the true blast radius may be larger than the graph knows.

## 3. Do not

- Do not open the export files to "check" the answer; open one only to quote a line
  the graph already pointed at.
- Do not describe reach as "widely used" when the report gives you a number.
- Do not omit the unresolved caveat because it weakens the answer. It is the answer.
