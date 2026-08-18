-- Order Management schema
create table order_app.customers (
  customer_id    number(12)      not null,
  customer_name  varchar2(200)   not null,
  region_id      number(6),
  active_flag    varchar2(1)     default 'Y' not null,
  created_on     date            default sysdate,
  constraint customers_pk primary key (customer_id)
);

create table order_app.orders (
  order_id       number(12)      not null,
  customer_id    number(12)      not null references order_app.customers (customer_id),
  rep_id         number(6),
  status_code    varchar2(20)    not null,
  order_date     date            default sysdate not null,
  total_amount   number(14,2),
  cancelled_on   date,
  constraint orders_pk primary key (order_id)
);

create table order_app.order_lines (
  line_id        number(12)      not null,
  order_id       number(12)      not null,
  product_code   varchar2(30)    not null,
  quantity       number(10)      not null,
  unit_price     number(12,2)    not null,
  constraint order_lines_pk primary key (line_id),
  constraint order_lines_order_fk foreign key (order_id) references order_app.orders (order_id)
);

create table order_app.order_statuses (
  status_code    varchar2(20)    not null,
  status_name    varchar2(60)    not null,
  constraint order_statuses_pk primary key (status_code)
);

create table order_app.regions (
  region_id      number(6)       not null,
  region_name    varchar2(100)   not null,
  constraint regions_pk primary key (region_id)
);

create table order_app.sales_reps (
  rep_id         number(6)       not null,
  rep_name       varchar2(100)   not null,
  constraint sales_reps_pk primary key (rep_id)
);

create table order_app.app_roles (
  username       varchar2(100)   not null,
  role_code      varchar2(30)    not null
);

create table order_app.audit_log (
  audit_id       number(12)      not null,
  table_name     varchar2(30),
  changed_on     date default sysdate
);

create sequence order_app.order_seq;

create index order_app.orders_customer_ix on order_app.orders (customer_id);
