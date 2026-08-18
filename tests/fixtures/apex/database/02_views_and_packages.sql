create or replace view order_app.order_view as
select o.order_id,
       o.customer_id,
       c.customer_name,
       o.status_code,
       o.order_date,
       o.total_amount
  from order_app.orders o
  join order_app.customers c on c.customer_id = o.customer_id;
/

create or replace package order_app.order_pkg as
  procedure save_order(p_order_id in number, p_customer_id in number,
                       p_status_code in varchar2);
  procedure create_order(p_customer_id in number, p_order_id out number);
  procedure cancel_order(p_order_id in number);
  function  order_total(p_order_id in number) return number;
  function  is_order_clerk(p_user in varchar2) return boolean;
  function  default_customer(p_user in varchar2) return number;
  procedure archive_orders(p_before in date);
end order_pkg;
/

create or replace package body order_app.order_pkg as

  procedure save_order(p_order_id in number, p_customer_id in number,
                       p_status_code in varchar2) is
  begin
    update order_app.orders
       set customer_id = p_customer_id,
           status_code = p_status_code
     where order_id = p_order_id;
  end save_order;

  procedure create_order(p_customer_id in number, p_order_id out number) is
  begin
    p_order_id := order_app.order_seq.nextval;
    insert into order_app.orders (order_id, customer_id, status_code, order_date)
    values (p_order_id, p_customer_id, 'OPEN', sysdate);
    audit_pkg.record_change(p_table => 'ORDERS');
  end create_order;

  procedure cancel_order(p_order_id in number) is
  begin
    update order_app.orders set status_code = 'CANCELLED' where order_id = p_order_id;
    delete from order_app.order_lines where order_id = p_order_id;
  end cancel_order;

  function order_total(p_order_id in number) return number is
    l_total number;
  begin
    select sum(quantity * unit_price) into l_total
      from order_app.order_lines
     where order_id = p_order_id;
    return l_total;
  end order_total;

  function is_order_clerk(p_user in varchar2) return boolean is
    l_count number;
  begin
    select count(*) into l_count
      from order_app.app_roles
     where username = p_user and role_code = 'CLERK';
    return l_count > 0;
  end is_order_clerk;

  function default_customer(p_user in varchar2) return number is
    l_customer_id number;
  begin
    select min(customer_id) into l_customer_id from order_app.customers;
    return l_customer_id;
  end default_customer;

  procedure archive_orders(p_before in date) is
  begin
    insert into order_app.orders_archive
    select * from order_app.orders where order_date < p_before;
  end archive_orders;

end order_pkg;
/

create or replace package body order_app.audit_pkg as
  procedure record_change(p_table in varchar2) is
  begin
    insert into order_app.audit_log (audit_id, table_name)
    values (order_app.order_seq.nextval, p_table);
  end record_change;
end audit_pkg;
/

create or replace trigger order_app.orders_biu
before insert or update on order_app.orders
for each row
begin
  if :new.order_id is null then
    :new.order_id := order_app.order_seq.nextval;
  end if;
end;
/
