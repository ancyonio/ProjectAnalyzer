-- Takes and declares ORDER_LINE_T, so the type dependency is real rather
-- than inferred from a name that happens to match.
CREATE OR REPLACE FUNCTION ORDER_APP.LINE_SUBTOTAL(
  p_line IN ORDER_LINE_T
) RETURN NUMBER AS
  v_line ORDER_LINE_T;
BEGIN
  v_line := p_line;
  RETURN v_line.QUANTITY * v_line.UNIT_PRICE;
END;
/
