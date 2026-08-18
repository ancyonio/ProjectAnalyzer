-- Standalone procedure: an entry point with no package.
-- Also the fixture's dynamic-SQL site, built by concatenation on purpose so
-- the resolution boundary in spec section 7 is asserted rather than assumed.
CREATE OR REPLACE PROCEDURE ORDER_APP.ARCHIVE_ORDERS(p_before DATE, p_table VARCHAR2) AS
  l_sql VARCHAR2(4000);
BEGIN
  INSERT INTO ORDER_APP.ORDERS_ARCHIVE (ORDER_ID, ARCHIVED_ON)
  SELECT ORDER_ID, SYSDATE FROM ORDER_APP.ORDERS WHERE CREATED_ON < p_before;

  l_sql := 'DELETE FROM ' || p_table || ' WHERE CREATED_ON < :1';
  EXECUTE IMMEDIATE l_sql USING p_before;

  -- A call to something that is not in the analysed tree: coverage must
  -- report below 100% because of it.
  LEGACY_UTIL.CLEANUP(p_before);
END;
