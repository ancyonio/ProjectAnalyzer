prompt --application/pages/page_00020
begin
--   Manifest
--     PAGE: 20
--   Manifest End
wwv_flow_imp.component_begin (
 p_version_yyyy_mm_dd=>'2023.04.14'
,p_release=>'23.1.0'
,p_default_application_id=>100
,p_default_owner=>'ORDER_APP'
);
wwv_flow_imp_page.create_page(
 p_id=>20
,p_name=>'Orders'
,p_alias=>'ORDERS'
,p_step_title=>'Orders'
,p_group_name=>'Order Management'
,p_protection_level=>'U'
);
wwv_flow_imp_page.create_page_plug(
 p_id=>wwv_flow_imp.id(2001)
,p_plug_name=>'Orders'
,p_plug_display_sequence=>10
,p_plug_source_type=>'NATIVE_IR'
,p_plug_source=>wwv_flow_string.join(wwv_flow_t_varchar2(
'select o.order_id,',
'       o.customer_id,',
'       o.status_code,',
'       o.order_date,',
'       c.customer_name,',
'       /*+ full(o) */ o.total_amount',
'  from order_app.orders o',
'  join order_app.customers c on c.customer_id = o.customer_id',
'  left join order_app.order_lines l on l.order_id = o.order_id',
'  join order_app.regions r on r.region_id = c.region_id',
'  join order_app.sales_reps s on s.rep_id = o.rep_id',
' where o.status_code = &P20_STATUS.')
)
);
wwv_flow_imp_page.create_worksheet(
 p_id=>wwv_flow_imp.id(2002)
,p_region_id=>wwv_flow_imp.id(2001)
,p_max_row_count=>100000
);
wwv_flow_imp_page.create_worksheet_column(
 p_id=>wwv_flow_imp.id(2003)
,p_region_id=>wwv_flow_imp.id(2001)
,p_db_column_name=>'STATUS_CODE'
,p_display_order=>10
,p_column_identifier=>'C'
,p_column_label=>'Status'
,p_column_type=>'STRING'
,p_report_lov=>'STATUS_LOV'
);
wwv_flow_imp_page.create_worksheet_column(
 p_id=>wwv_flow_imp.id(2004)
,p_region_id=>wwv_flow_imp.id(2001)
,p_db_column_name=>'CUSTOMER_ID'
,p_display_order=>20
,p_column_identifier=>'D'
,p_column_label=>'Customer'
,p_column_type=>'NUMBER'
);
wwv_flow_imp_page.create_page_item(
 p_id=>wwv_flow_imp.id(2101)
,p_name=>'P20_STATUS'
,p_item_sequence=>10
,p_item_plug_id=>wwv_flow_imp.id(2001)
,p_prompt=>'Status'
,p_display_as=>'NATIVE_SELECT_LIST'
,p_named_lov=>'STATUS_LOV'
,p_protection_level=>'N'
);
wwv_flow_imp_page.create_page_button(
 p_id=>wwv_flow_imp.id(2201)
,p_button_sequence=>10
,p_button_plug_id=>wwv_flow_imp.id(2001)
,p_button_name=>'CREATE'
,p_button_action=>'REDIRECT_PAGE'
,p_button_image_alt=>'Create Order'
,p_button_redirect_url=>'f?p=&APP_ID.:10:&SESSION.::&DEBUG.:10::'
);
wwv_flow_imp_page.create_page_process(
 p_id=>wwv_flow_imp.id(2301)
,p_process_sequence=>10
,p_process_point=>'AFTER_SUBMIT'
,p_process_type=>'NATIVE_PLSQL'
,p_process_name=>'Purge cancelled orders'
,p_process_sql_clob=>wwv_flow_string.join(wwv_flow_t_varchar2(
'declare',
'  l_sql varchar2(4000);',
'begin',
'  l_sql := ''delete from order_app.orders where status_code = '''''' || :P20_STATUS || '''''''';',
'  execute immediate l_sql;',
'end;'))
);
wwv_flow_imp.component_end;
end;
/
