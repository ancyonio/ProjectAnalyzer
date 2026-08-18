prompt --application/pages/page_00001
begin
wwv_flow_imp.component_begin (
 p_version_yyyy_mm_dd=>'2023.04.14'
,p_default_application_id=>100
,p_default_owner=>'ORDER_APP'
);
wwv_flow_imp_page.create_page(
 p_id=>1
,p_name=>'Home'
,p_alias=>'HOME'
,p_step_title=>'Home'
,p_group_name=>'Core'
,p_protection_level=>'C'
);
wwv_flow_imp_page.create_page_plug(
 p_id=>wwv_flow_imp.id(3001)
,p_plug_name=>'Open Orders'
,p_plug_display_sequence=>10
,p_plug_source_type=>'NATIVE_SQL_REPORT'
,p_plug_source=>'select * from order_app.order_view where status_code = ''OPEN'''
);
wwv_flow_imp_page.create_page_plug(
 p_id=>wwv_flow_imp.id(3002)
,p_plug_name=>'Welcome'
,p_plug_display_sequence=>20
,p_plug_source_type=>'NATIVE_STATIC'
,p_plug_source=>'<p>Welcome to Order Management.</p>'
);
wwv_flow_imp.component_end;
end;
/
