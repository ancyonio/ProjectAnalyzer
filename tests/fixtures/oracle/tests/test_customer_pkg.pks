-- A utPLSQL suite. The annotations are the only statement of test intent an
-- Oracle repository carries, so TestCase is built from these and nothing else.
CREATE OR REPLACE PACKAGE ORDER_APP.TEST_CUSTOMER_PKG AS

  --%suite(Customer package)
  --%suitepath(order_app.customer)

  --%test(creates a customer row)
  PROCEDURE CREATE_CUSTOMER_OK;

  --%test(deletes a customer row)
  PROCEDURE DELETE_CUSTOMER_OK;

END TEST_CUSTOMER_PKG;
/
