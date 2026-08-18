-- The published contract. A change here breaks every caller.
CREATE OR REPLACE PACKAGE ORDER_APP.CUSTOMER_PKG AS

  PROCEDURE CREATE_CUSTOMER(p_name VARCHAR2);

  PROCEDURE DELETE_CUSTOMER(p_customer_id NUMBER);

  -- Overloaded on purpose: the fixture must cover overload resolution.
  FUNCTION GET_CUSTOMER(p_customer_id NUMBER) RETURN VARCHAR2;
  FUNCTION GET_CUSTOMER(p_name VARCHAR2) RETURN NUMBER;

END CUSTOMER_PKG;
