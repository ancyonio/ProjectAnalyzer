# Data lineage

`oracle-analyze lineage --target "DbTable:ORDERS"` answers where a table's contents
come from and where they go. It has no equivalent in the TIBCO or APEX analyzers, and
it is the capability that justifies materialising `SqlStatement` as a node: the
statement is what carries the verb and the read set, not the program unit.

## The shape of the answer

```
                READS_FROM              INSERTS_INTO / UPDATES / DELETES_FROM
  source tables ──────────> SqlStatement ──────────────────────> target table
                                 ^
                                 │ EXECUTES_SQL
                            DbProgramUnit
```

| Section | Question it answers | Path |
|---|---|---|
| **Written by** | where the data comes from | `(:SqlStatement)-[:INSERTS_INTO\|UPDATES\|DELETES_FROM]->(target)` plus that statement's `READS_FROM` |
| **Read by** | who is affected by the data | `(:SqlStatement)-[:READS_FROM]->(target)` plus that statement's `WRITES_TO` |
| **Views** | derived exposure | `(:DbView)-[:DEPENDS_ON]->(target)` |
| **Triggers** | control flow the caller never mentions | `(:DbTrigger)-[:FIRES_ON]->(target)` |

The "Reads from" column on a write row is what makes this lineage rather than an
access list: it is the provenance of the values being written.

## Reading it honestly

1. **Triggers are the easy thing to miss.** A write to a table may run code the
   calling unit never names. Always report the triggers section; if it is empty, say
   the table has no triggers rather than saying nothing.

2. **A view is a second surface.** Consumers may read the view, not the table. A
   column dropped from the table breaks both, and only one of them is in the query
   you were shown.

3. **A synonym hides the real target.** Lineage follows one synonym hop, so a unit
   that reads `CUST` appears against `CUSTOMERS`. Say which name the source actually
   used when it matters to a code change.

4. **Dynamic SQL is a hole in the lineage, not an absence of lineage.** Check
   `context/unresolved.md` and the dynamic-SQL list before saying "nothing else
   writes this table". The honest form is "nothing else that the analyzer can
   resolve".

5. **`WRITES_TO` is not enough on its own.** A retention question needs
   `DELETES_FROM`; a provenance question needs `INSERTS_INTO`. Use the specific verb
   and say which one you used.

6. **Column-level lineage is per-statement, not column-to-column.**
   `REFERENCES_COLUMN` binds a `SqlStatement` to every `DbColumn` it names, so
   "which statements touch `CUSTOMERS.NAME`" is answerable and so is the set of
   columns a unit reaches through its statements. What is *not* modelled is flow
   between two columns — that `SOURCE.AMOUNT` populates `TARGET.TOTAL`. A
   statement that reads four columns and writes one records five references, not
   the mapping between them. Say which of the two you are answering.

   The binder is strict: a candidate that is not a column of a table in scope
   produces no edge, and an unqualified name is bound only when exactly one table
   could own it. Absence of a `REFERENCES_COLUMN` edge therefore means "not
   resolvable", not "not referenced".

## Commands

```bash
# the report, as Markdown
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle \
  lineage --target "DbTable:ORDERS"

# machine-readable, for a wider trace
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle \
  lineage --target "DbTable:ORDERS" --json

# save it beside the analysis
PYTHONPATH=tools python -m oracle_analyzer -o analysis_output_oracle \
  lineage --target "DbTable:ORDERS" --save analysis_output_oracle/lineage/orders.md
```

For a chain across several tables, run `lineage` on each end and join the results
yourself, or use the `table-lineage` query in the Cypher cookbook — the command
reports one hop in each direction by design, so a multi-hop claim is yours to make
explicit rather than the tool's to imply.
