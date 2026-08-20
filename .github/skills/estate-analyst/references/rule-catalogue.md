# Cross-estate rule catalogue

Deterministic rules run by `estate-analyze findings`. Every `XE-` rule answers a
question that is **only** answerable once the estates are joined — a condition
visible inside one analyzer belongs to that analyzer's catalogue, not here. Restating
an APEX finding as a federation discovery would inflate the ledger without adding
information.

The catalogue lives in `tools/estate_analyzer/analysis/rules_catalog.py`. All `XE-`
findings carry `category: CROSS_ESTATE` and an `estates` list naming which systems the
finding spans.

| Rule | Severity | Spans | Triggers when | Recommended action |
|---|---|---|---|---|
| `XE-001` | HIGH | any two | One table is written by two or more estates | Decide which estate owns the table before either is migrated. |
| `XE-002` | HIGH | tibco | TIBCO reaches a table no analysed database estate defines | Extend the Oracle analysis to that schema, or correct the estate map. |
| `XE-003` | HIGH | tibco + oracle | A table written from TIBCO is also written by Oracle code that commits | Establish who owns the transaction boundary, or make the integration idempotent for that table. |
| `XE-004` | MEDIUM | any two | The same statement digest is implemented in two estates | Decide which estate owns the behaviour and have the other call it — or record that the duplication is accepted, and why. |
| `XE-005` | MEDIUM | tibco | A JDBC resource has no estate-map entry | Add the resource to the estate map with the schema it serves. |
| `XE-006` | MEDIUM | tibco | A JDBC activity carries no static SQL | Confirm by hand which tables it reaches and record it. |
| `XE-007` | HIGH | tibco + apex | An APEX page reports over a table TIBCO writes behind it | Include the page in the regression scope for any integration change. |

## The three that change a migration plan

**`XE-001` decides cutover order, not just ownership.** Two writers on separate
release trains cannot be cut over independently: the second cutover silently depends
on the first. This is the finding that most often invalidates a sequence someone has
already agreed, so surface it before the plan hardens, not after.

**`XE-003` is a timing bug waiting to be blamed on the wrong system.** The
integration cannot see the database's transaction boundary. An intermediate `COMMIT`
inside the Oracle unit makes partial state visible to TIBCO, so a retry can act on a
half-finished unit of work. The failure depends on timing rather than logic, which is
why it survives testing and appears in production.

**`XE-007` finds defects that will be misattributed.** The page renders state no APEX
code produced. When the row shape or the timing changes, the symptom is an APEX
defect and the cause is in the integration. Naming these pages up front is worth more
than any of the remediation advice attached to them.

## Two rules that measure the join, not the estate

`XE-005` and `XE-006` describe what the federation could **not** do, and they belong
in the coverage paragraph of an answer rather than the findings list.

- `XE-005` — a JDBC url names a database, not a schema, so the mapping cannot be
  inferred. Every table behind an unmapped datasource is dark: absent from lineage,
  absent from every blast radius, and absent without a trace unless this rule is read.
- `XE-006` — runtime SQL at the boundary. Do not read an activity's absence from the
  lineage as evidence that it touches nothing.

Both should be quoted before any negative claim. "No other estate writes this table"
is only true if no unmapped datasource and no runtime-SQL activity could have.

## Reading the merged ledger

`findings` shows the `XE-` rules **and** the three source catalogues, namespaced:

```bash
estate-analyze findings --estate cross              # XE- rules only
estate-analyze findings --rule XE-001
estate-analyze findings --rule APEX.SEC-001         # a source-estate finding
estate-analyze findings --category CROSS_ESTATE
estate-analyze findings --min-severity HIGH --fail-on HIGH
```

The namespace matters. `SEC-001` means a different condition in each of the three
catalogues, so an unqualified rule id in a cross-estate answer is ambiguous at best
and wrong at worst. Always write `TIB.SEC-001`, `APEX.SEC-001` or `ORA.SEC-001` when
the answer spans estates.

## What an `XE-` finding is evidence of

These rules read the federated graph, and most of that graph's cross-estate edges are
**inferred** — TIBCO shares no ids with APEX or Oracle, so its links to the database
carry `origin`, `confidence` and `basis`. A finding drawn through a low-confidence
link inherits that confidence. Before quoting an `XE-` finding as fact, check the link
it rests on in `context/cross-estate-links.md`, and say which it is.
