# Rule catalogue

Deterministic rules run by `oracle-analyze rules`. Each produces an `:Issue` node
linked by `HAS_ISSUE` to the object that triggered it, by `AFFECTS` back to that
object, and by `HAS_RECOMMENDATION` to a `:Recommendation`. An agent explains and
prioritises these; it does not re-detect them.

The catalogue lives in `tools/oracle_analyzer/analysis/rules_catalog.py`. Rule ids are
stable — adding a rule takes the next free ordinal, and ids are never reused.

| Rule | Category | Severity | Triggers when | Recommended action |
|---|---|---|---|---|
| `SEC-001` | SECURITY | CRITICAL | A program unit builds SQL at runtime | Replace `EXECUTE IMMEDIATE` with static SQL, or bind every user-supplied value with `USING` rather than concatenating it. |
| `SEC-002` | SECURITY | HIGH | A source file assigns a credential from a literal | Move the secret to a wallet, a vault or an environment-supplied parameter. |
| `CORR-001` | CORRECTNESS | HIGH | A unit swallows every exception with `WHEN OTHERS THEN NULL` | Handle the exceptions you expect and re-raise the rest, so a failure surfaces instead of silently returning success. |
| `CORR-002` | CORRECTNESS | HIGH | A trigger commits | Remove the `COMMIT`; it breaks the calling transaction and can raise ORA-04092. |
| `CORR-003` | CORRECTNESS | HIGH | An `UPDATE` or `DELETE` has no `WHERE` clause | Confirm it is meant to affect every row; if not, add the predicate that bounds it. |
| `PERF-001` | PERFORMANCE | MEDIUM | A query uses `SELECT *` | Name the columns the caller needs; a column added to the table silently changes what this returns. |
| `PERF-002` | PERFORMANCE | MEDIUM | A query carries a hardcoded optimizer hint | Remove the hint and confirm the plan with current statistics; keep it only with a recorded reason. |
| `PERF-003` | PERFORMANCE | HIGH | An unbounded read of a table with ≥100,000 rows | Add a predicate that uses an index, or paginate the result. |
| `DEBT-001` | DEBT | MEDIUM | A package publishes a spec with no body in the tree | Confirm the body is deployed but not in source control, or that the package is genuinely unimplemented. |
| `DEBT-002` | DEBT | LOW | A unit is private to its body and never called | Confirm it is dead and remove it, or note the caller the analysis cannot see. |
| `DEBT-003` | DEBT | HIGH | The dictionary reports the object as `INVALID` | Recompile it and fix what the compilation reports; an invalid object fails at first use. |
| `DEBT-004` | DEBT | LOW | A name is referenced but never defined in the tree | Supply the missing source, or a dictionary extract, before treating the dependency graph as complete. |

## Rules that need a dictionary extract

`PERF-003` reads `numRows`, and `DEBT-003` reads `status`. Both come only from the
data-dictionary extract. Without `--db-meta` they cannot fire, and their absence is
not evidence that the conditions are absent — say so rather than reporting a clean
performance or validity result.

## Two rules that carry more weight than their severity suggests

**`SEC-001` is not only a security finding.** Dynamic SQL is also where dependency
analysis stops: the unit's real reads and writes are unknown to the graph. Every
completeness claim about a unit carrying `hasDynamicSql` is provisional, and a
"dead" object may be reached from exactly there.

**`DEBT-002` must never be acted on alone.** Cross-check the dynamic-SQL list and
`context/unresolved.md` before recommending a deletion. A unit called only through
`EXECUTE IMMEDIATE`, an external job or ORDS looks identical to a dead one here.

## Using them

```bash
oracle-analyze rules --category SECURITY --min-severity HIGH
oracle-analyze rules --rule SEC-001 --json
oracle-analyze rules --fail-on CRITICAL      # exit 2 in CI
```

The severity breakdown printed under a filtered run describes the findings actually
shown, and names how many the filter hid. Severity is fixed by the rule, not by the
finding: judgement about *this* estate belongs in your narrative, not in a rewritten
severity.
