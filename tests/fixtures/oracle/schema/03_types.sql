-- A user-defined object type. Exercises `create type` parsing and gives
-- USES_TYPE a target, which a repository-only analysis previously never had.
CREATE OR REPLACE TYPE ORDER_APP.ORDER_LINE_T AS OBJECT (
  PRODUCT_CODE  VARCHAR2(30),
  QUANTITY      NUMBER,
  UNIT_PRICE    NUMBER(12,2)
);
/
