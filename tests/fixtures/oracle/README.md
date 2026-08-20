# Oracle analyzer fixture

A small but complete Oracle estate, carrying deliberately seeded conditions so
the analyzer's boundaries are asserted rather than assumed:

- a package with separate `.pks` / `.pkb` and an **overloaded** function
- a standalone procedure and a standalone function
- a trigger, a view over two tables, a sequence, a synonym, an index, two FKs
- reads and writes across several tables, so every data-access verb fires
- an `EXECUTE IMMEDIATE` built by concatenation (the dynamic-SQL boundary)
- a call to `LEGACY_UTIL.CLEANUP`, which is **not** in the tree, so resolution
  coverage is asserted below 100%
- a private body unit nothing calls, so dead-code detection has a target
- a `create type` and a function that declares it, so `USES_TYPE` has a target
  and object-attribute access is asserted not to read as a call
- a two-table `INSERT ... SELECT`, so `JOINS` fires and a single-table read
  is asserted not to
- a credential in `deploy/install.sql`, asserted never to reach the graph
- a utPLSQL suite under `tests/`, so `TestCase` and `HAS_TEST` are built from
  real annotations and the suite is asserted not to test itself
- published units that write (business functions) alongside a private helper
  and a read-only lookup that must **not** become one
