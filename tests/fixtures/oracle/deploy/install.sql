-- Deployment plumbing. Skipped by the scanner, but it carries a credential so
-- the "never copy a secret into the graph" rule has something to be tested on.
CONNECT order_app/hunter2-not-a-real-password@ORCL
DEFINE db_password = 'hunter2-not-a-real-password'
@@../schema/01_tables.sql
