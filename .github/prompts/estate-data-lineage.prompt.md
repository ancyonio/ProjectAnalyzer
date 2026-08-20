---
mode: agent
description: Trace where a table's data comes from and goes to across the TIBCO, APEX and Oracle estates, without overstating what the join can prove.
---

# Cross-estate data lineage

Single-estate lineage is answered by that estate's analyzer. Come here only when the
answer has to cross a boundary — "who else writes this table", "what feeds this page
that APEX did not produce", "what breaks everywhere if this column changes".

## 1. Establish the join first

Lineage that crosses estates rests on the join, so read it before reading the
lineage:

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate links
```

Then `context/cross-estate-links.md`. APEX and Oracle share `analyzer_core.ids`, so a
table they both touch is **one node with nothing inferred**. Every TIBCO edge into the
database is inferred and carries `basis` and `confidence` — `exact` 1.0, `declared`
0.9, `qualified-name` 0.8, `name` 0.5 (off unless `--allow-name-match`).

## 2. Trace it

```bash
PYTHONPATH=tools python -m estate_analyzer -o analysis_output_estate impact \
  --target "DbTable:ORDERS" --direction upstream
```

and `context/shared-data.md` for everything more than one estate touches.

For a specific chain, the `tibco-to-table` and `end-to-end-path` queries in
`references/cypher-cookbook.md` give the two directions that matter: what an
integration writes, and what a user surface reads behind it.

## 3. Report each leg with its basis

Never flatten the two halves of the join into one confidence. One row per leg:

| Leg | Estate | Verb | Basis | Confidence |
|---|---|---|---|---|
| `ORDER_PKG.CANCEL_ORDER` | oracle | `UPDATES` | exact — shared id | 1.0 |
| `CustomerSync.WriteOrderLines` | tibco | `INSERTS_INTO` | qualified-name, via mapped datasource | 0.8 |

Use the **specific verb**, not the `WRITES_TO` roll-up. A retention question needs
`DELETES_FROM`; a provenance question needs `INSERTS_INTO`. Say which one you used.

## 4. State what the lineage cannot show

Column-to-column flow is not modelled anywhere in this toolkit. `REFERENCES_COLUMN`
says a statement *names* a column, not that one column populates another. Answer
"what touches this column", never "this column populates that one".

Then check all four gaps before any negative claim — this is the step that makes a
cross-estate lineage answer trustworthy:

1. **`XE-005` unmapped datasources** — a JDBC url names a database, not a schema, so
   the mapping cannot be inferred. Every table behind an unmapped resource is dark:
   absent from this lineage and from every blast radius.
2. **`XE-006` runtime SQL at the boundary** — an activity with no static SQL appears
   in no lineage. Its absence is not evidence it touches nothing.
3. **Oracle dynamic SQL** — `SEC-001`; the unit's real reads and writes are unknown.
4. **`context/unresolved.md`** — dependencies the graph knows exist and cannot follow.

"Nothing else writes this table" is only true if no unmapped datasource and no
runtime-SQL activity could have. The honest form is **"nothing this analysis can
resolve writes it, and here is what it could not resolve."**

## 5. Findings that change the reading

| Rule | What it means for lineage |
|---|---|
| `XE-001` | More than one estate writes it. The lineage has two owners and two release trains. |
| `XE-003` | A TIBCO-written table is also written by Oracle code that commits. Partial state is visible to the integration; the failure mode depends on timing, not logic. |
| `XE-004` | The same statement digest in two estates — one behaviour, two owners, and it will drift. |
| `XE-007` | An APEX page reports over a table TIBCO writes. The page shows state no APEX code produced. |

## 6. Write it up

Lead with the table and its writers, then readers, then the gaps. State coverage next
to the conclusion, not in a footnote — see
[analysis-trust](../skills/analysis-trust/SKILL.md):

> `ORDER_LINES` is written by two estates: `ORDER_PKG.CANCEL_ORDER` (oracle, `UPDATES`,
> exact — both database estates name the same object) and `CustomerSync.WriteOrderLines`
> (tibco, `INSERTS_INTO`, qualified-name at 0.8, via the mapped
> `sync.OrderApp_JDBCConnectionResource`). Two APEX pages read it, so `XE-007` applies
> to both. SQL bind coverage is 60% and one datasource is unmapped, so there may be
> further writers this cannot see; mapping that resource in the estate map would close
> the gap.

Style: British-neutral professional English, no emoji, no hype, tables over prose when
carrying more than three facts, uncertainty stated plainly with the command that would
remove it.
