---
mode: agent
description: Trace where an Oracle table's data comes from and where it goes, from the deterministic graph.
---

# Oracle data lineage

Target: `${input:target:e.g. DbTable:ORDERS}`

## 1. Run the trace

```bash
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle \
  lineage --target "${input:target}" \
  --save analysis_output_oracle/lineage/${input:slug:short-name-for-the-file}
```

Add `--json` when you need to trace further than one hop and want to join the results
yourself.

## 2. Read all four sections

| Section | Question it answers |
|---|---|
| Written by | where the data comes from — and, in the "Reads from" column, what each write reads to produce it |
| Read by | who is affected by the data, and what they write as a result |
| Views | the second surface consumers may actually be reading |
| Triggers | code that runs on a write which the calling unit never mentions |

The "Reads from" column is what makes this lineage rather than an access list. Report
it; a write with no stated source is an incomplete answer.

## 3. Extend by one hop where it matters

The command reports one hop in each direction by design. For a chain, run `lineage`
again on each source or target table, or use the `table-lineage` query in
`analysis_output_oracle/ANALYSIS_QUERIES.md`. A multi-hop claim is yours to make
explicit, not the tool's to imply.

## 4. Use the specific verb

`WRITES_TO` is a roll-up. Answer a provenance question with `INSERTS_INTO`, a
retention question with `DELETES_FROM`, and a mutation question with `UPDATES`. Say
which one you used — the roll-up hides exactly the distinction these questions turn
on.

## 5. State the limits

- **Column references are per-statement, not column-to-column.** `REFERENCES_COLUMN`
  says a statement names a column; it does not say which column feeds which. Answer
  "what touches this column", never "this column populates that one".
- **Dynamic SQL is a hole in the lineage, not an absence of it.** Check the
  dynamic-SQL sites before saying "nothing else writes this table". The honest form is
  "nothing else that the analyzer can resolve".
- **A synonym hides the real target.** Lineage follows one synonym hop, so a unit that
  reads `CUST` appears against `CUSTOMERS`. Say which name the source used when it
  matters to a code change.
- **External writers are invisible.** ETL, ORDS, scheduled jobs and other schemas do
  not appear unless they were analysed into the same graph.
