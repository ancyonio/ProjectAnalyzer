prompt --application/pages/page_00010
begin
--   Manifest
--     PAGE: 10
--   Manifest End
wwv_flow_imp.component_begin (
 p_version_yyyy_mm_dd=>'2023.04.14'
,p_release=>'23.1.0'
,p_default_workspace_id=>1509884271898235
,p_default_application_id=>100
,p_default_id_offset=>0
,p_default_owner=>'ORDER_APP'
);
wwv_flow_imp_page.create_page(
 p_id=>10
,p_name=>'Order Details'
,p_alias=>'ORDER-DETAILS'
,p_step_title=>'Order Details'
,p_group_name=>'Order Management'
,p_protection_level=>'C'
,p_required_role=>wwv_flow_imp.id(7201)
,p_page_component_map=>'18'
);
wwv_flow_imp_page.create_page_plug(
 p_id=>wwv_flow_imp.id(1001)
,p_plug_name=>'Order Header'
,p_region_template_options=>'#DEFAULT#'
,p_plug_display_sequence=>10
,p_plug_source_type=>'NATIVE_FORM'
,p_query_type=>'TABLE'
,p_query_table=>'ORDERS'
,p_query_owner=>'ORDER_APP'
,p_query_where=>'order_id = :P10_ORDER_ID'
);
wwv_flow_imp_page.create_page_plug(
 p_id=>wwv_flow_imp.id(1002)
,p_plug_name=>'Order Lines'
,p_plug_display_sequence=>20
,p_plug_source_type=>'NATIVE_IG'
,p_plug_source=>wwv_flow_string.join(wwv_flow_t_varchar2(
'select l.line_id,',
'       l.order_id,',
'       l.product_code,',
'       l.quantity,',
'       l.unit_price,',
'       l.quantity * l.unit_price as line_total',
'  from order_app.order_lines l',
' where l.order_id = :P10_ORDER_ID',
' order by l.line_id')
)
,p_plug_query_no_data_found=>'This order has no lines.'
);
wwv_flow_imp_page.create_page_plug(
 p_id=>wwv_flow_imp.id(1003)
,p_plug_name=>'Customer Summary'
,p_plug_display_sequence=>30
,p_plug_source_type=>'NATIVE_SQL_REPORT'
,p_plug_source=>'select * from order_view where customer_id = :P10_CUSTOMER_ID'
,p_plug_display_when_condition=>'select 1 from dual where :P10_CUSTOMER_ID is not null'
,p_plug_display_condition_type=>'EXISTS'
);
wwv_flow_imp_page.create_page_item(
 p_id=>wwv_flow_imp.id(1101)
,p_name=>'P10_ORDER_ID'
,p_item_sequence=>10
,p_item_plug_id=>wwv_flow_imp.id(1001)
,p_prompt=>'Order Id'
,p_source=>'ORDER_ID'
,p_source_type=>'DB_COLUMN'
,p_display_as=>'NATIVE_HIDDEN'
,p_protection_level=>'N'
,p_is_required=>'Y'
);
wwv_flow_imp_page.create_page_item(
 p_id=>wwv_flow_imp.id(1102)
,p_name=>'P10_CUSTOMER_ID'
,p_item_sequence=>20
,p_item_plug_id=>wwv_flow_imp.id(1001)
,p_prompt=>'Customer'
,p_source=>'CUSTOMER_ID'
,p_source_type=>'DB_COLUMN'
,p_display_as=>'NATIVE_SELECT_LIST'
,p_named_lov=>'CUSTOMER_LOV'
,p_protection_level=>'C'
,p_is_required=>'Y'
);
wwv_flow_imp_page.create_page_item(
 p_id=>wwv_flow_imp.id(1103)
,p_name=>'P10_ORDER_STATUS'
,p_item_sequence=>30
,p_item_plug_id=>wwv_flow_imp.id(1001)
,p_prompt=>'Status'
,p_source=>'STATUS_CODE'
,p_source_type=>'DB_COLUMN'
,p_display_as=>'NATIVE_SELECT_LIST'
,p_named_lov=>'STATUS_LOV'
,p_protection_level=>'C'
);
wwv_flow_imp_page.create_page_item(
 p_id=>wwv_flow_imp.id(1104)
,p_name=>'P10_ORDER_TOTAL'
,p_item_sequence=>40
,p_item_plug_id=>wwv_flow_imp.id(1001)
,p_prompt=>'Order Total'
,p_display_as=>'NATIVE_DISPLAY_ONLY'
,p_item_default_type=>'SQL_QUERY'
,p_item_default=>'select sum(quantity * unit_price) from order_app.order_lines where order_id = :P10_ORDER_ID'
,p_protection_level=>'C'
);
wwv_flow_imp_page.create_page_button(
 p_id=>wwv_flow_imp.id(1201)
,p_button_sequence=>10
,p_button_plug_id=>wwv_flow_imp.id(1001)
,p_button_name=>'SAVE'
,p_button_action=>'SUBMIT'
,p_button_image_alt=>'Apply Changes'
,p_button_is_hot=>'Y'
,p_database_action=>'UPDATE'
);
wwv_flow_imp_page.create_page_button(
 p_id=>wwv_flow_imp.id(1202)
,p_button_sequence=>20
,p_button_plug_id=>wwv_flow_imp.id(1001)
,p_button_name=>'CANCEL_ORDER'
,p_button_action=>'SUBMIT'
,p_button_image_alt=>'Cancel Order'
,p_security_scheme=>wwv_flow_imp.id(7202)
);
wwv_flow_imp_page.create_page_button(
 p_id=>wwv_flow_imp.id(1203)
,p_button_sequence=>30
,p_button_plug_id=>wwv_flow_imp.id(1001)
,p_button_name=>'BACK'
,p_button_action=>'REDIRECT_PAGE'
,p_button_image_alt=>'Back to Orders'
,p_button_redirect_url=>'f?p=&APP_ID.:20:&SESSION.::&DEBUG.:::'
);
wwv_flow_imp_page.create_page_validation(
 p_id=>wwv_flow_imp.id(1301)
,p_validation_name=>'Customer must exist'
,p_validation_sequence=>10
,p_validation=>'select 1 from order_app.customers where customer_id = :P10_CUSTOMER_ID'
,p_validation_type=>'EXISTS'
,p_error_message=>'Customer does not exist.'
,p_associated_item=>wwv_flow_imp.id(1102)
,p_when_button_pressed=>wwv_flow_imp.id(1201)
);
wwv_flow_imp_page.create_page_process(
 p_id=>wwv_flow_imp.id(1401)
,p_process_sequence=>10
,p_process_point=>'AFTER_SUBMIT'
,p_process_type=>'NATIVE_PLSQL'
,p_process_name=>'Save Order'
,p_process_sql_clob=>wwv_flow_string.join(wwv_flow_t_varchar2(
'begin',
'  order_pkg.save_order(',
'    p_order_id    => :P10_ORDER_ID,',
'    p_customer_id => :P10_CUSTOMER_ID,',
'    p_status_code => :P10_ORDER_STATUS);',
'  commit;',
'exception',
'  when others then null;',
'end;'))
,p_process_when_button_id=>wwv_flow_imp.id(1201)
,p_process_success_message=>'Order saved.'
);
wwv_flow_imp_page.create_page_process(
 p_id=>wwv_flow_imp.id(1402)
,p_process_sequence=>20
,p_process_point=>'AFTER_SUBMIT'
,p_process_type=>'NATIVE_PLSQL'
,p_process_name=>'Cancel Order'
,p_process_sql_clob=>wwv_flow_string.join(wwv_flow_t_varchar2(
'begin',
'  update order_app.orders',
'     set status_code = ''CANCELLED'',',
'         cancelled_on = sysdate',
'   where order_id = :P10_ORDER_ID;',
'  delete from order_app.order_lines where order_id = :P10_ORDER_ID;',
'end;'))
,p_process_when_button_id=>wwv_flow_imp.id(1202)
,p_security_scheme=>wwv_flow_imp.id(7202)
,p_build_option=>wwv_flow_imp.id(7301)
);
wwv_flow_imp_page.create_page_branch(
 p_id=>wwv_flow_imp.id(1501)
,p_branch_name=>'Back to Orders'
,p_branch_action=>'f?p=&APP_ID.:20:&SESSION.::&DEBUG.:::'
,p_branch_point=>'AFTER_PROCESSING'
,p_branch_type=>'REDIRECT_URL'
,p_branch_sequence=>10
);
wwv_flow_imp_page.create_page_da_event(
 p_id=>wwv_flow_imp.id(1601)
,p_name=>'Recalculate total'
,p_event_sequence=>10
,p_triggering_element_type=>'ITEM'
,p_triggering_element=>'P10_CUSTOMER_ID'
,p_bind_type=>'bind'
,p_bind_event_type=>'change'
);
wwv_flow_imp_page.create_page_da_action(
 p_id=>wwv_flow_imp.id(1602)
,p_event_id=>wwv_flow_imp.id(1601)
,p_event_result=>'TRUE'
,p_action_sequence=>10
,p_action=>'NATIVE_EXECUTE_PLSQL_CODE'
,p_attribute_01=>wwv_flow_string.join(wwv_flow_t_varchar2(
'begin',
'  :P10_ORDER_TOTAL := order_pkg.order_total(p_order_id => :P10_ORDER_ID);',
'end;'))
,p_attribute_02=>'P10_ORDER_ID,P10_CUSTOMER_ID'
,p_attribute_03=>'P10_ORDER_TOTAL'
);
wwv_flow_imp_page.create_page_da_action(
 p_id=>wwv_flow_imp.id(1603)
,p_event_id=>wwv_flow_imp.id(1601)
,p_event_result=>'TRUE'
,p_action_sequence=>20
,p_action=>'NATIVE_JAVASCRIPT_CODE'
,p_attribute_01=>wwv_flow_string.join(wwv_flow_t_varchar2(
'apex.message.showPageSuccess("Total refreshed");'))
);
wwv_flow_imp.component_end;
end;
/
