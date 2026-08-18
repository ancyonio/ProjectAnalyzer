prompt --application/shared_components/user_interface/lovs/customer_lov
begin
wwv_flow_imp.component_begin (
 p_version_yyyy_mm_dd=>'2023.04.14'
,p_default_application_id=>100
,p_default_owner=>'ORDER_APP'
);
wwv_flow_imp_shared.create_list_of_values(
 p_id=>wwv_flow_imp.id(6101)
,p_lov_name=>'CUSTOMER_LOV'
,p_lov_query=>wwv_flow_string.join(wwv_flow_t_varchar2(
'select c.customer_name as d, c.customer_id as r',
'  from order_app.customers c',
' where c.active_flag = ''Y''',
' order by 1'))
,p_lov_type=>'DYNAMIC'
);
wwv_flow_imp_shared.create_list_of_values(
 p_id=>wwv_flow_imp.id(6102)
,p_lov_name=>'STATUS_LOV'
,p_lov_query=>'select status_name d, status_code r from order_app.order_statuses order by 1'
,p_lov_type=>'DYNAMIC'
);
wwv_flow_imp_shared.create_list_of_values(
 p_id=>wwv_flow_imp.id(6103)
,p_lov_name=>'UNUSED_REGION_LOV'
,p_lov_query=>'select region_name d, region_id r from order_app.regions'
,p_lov_type=>'DYNAMIC'
);
wwv_flow_imp_shared.create_list(
 p_id=>wwv_flow_imp.id(6201)
,p_name=>'Navigation Menu'
,p_list_status=>'PUBLIC'
);
wwv_flow_imp_shared.create_list_item(
 p_id=>wwv_flow_imp.id(6202)
,p_list_id=>wwv_flow_imp.id(6201)
,p_list_item_display_sequence=>10
,p_list_item_link_text=>'Orders'
,p_list_item_link_target=>'f?p=&APP_ID.:20:&SESSION.'
);
wwv_flow_imp_shared.create_list_item(
 p_id=>wwv_flow_imp.id(6203)
,p_list_id=>wwv_flow_imp.id(6201)
,p_list_item_display_sequence=>20
,p_list_item_link_text=>'Home'
,p_list_item_link_target=>'f?p=&APP_ID.:1:&SESSION.'
);
wwv_flow_imp.component_end;
end;
/
