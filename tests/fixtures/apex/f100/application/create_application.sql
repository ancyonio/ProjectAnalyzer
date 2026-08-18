prompt --application/create_application
begin
--   Manifest
--     FLOW: 100
--   Manifest End
wwv_flow_imp.component_begin (
 p_version_yyyy_mm_dd=>'2023.04.14'
,p_release=>'23.1.0'
,p_default_workspace_id=>1509884271898235
,p_default_application_id=>100
,p_default_id_offset=>0
,p_default_owner=>'ORDER_APP'
);
wwv_flow_imp.create_flow(
 p_id=>100
,p_owner=>'ORDER_APP'
,p_name=>'Order Management'
,p_alias=>'ORDERMGMT'
,p_page_view_logging=>'YES'
,p_default_page_template=>wwv_flow_imp.id(9200)
,p_flow_version=>'Release 4.2'
,p_flow_theme=>42
,p_authentication=>'PLUGIN'
,p_authentication_id=>wwv_flow_imp.id(7101)
,p_compatibility_mode=>'21.2'
,p_friendly_url=>'Y'
,p_home_link=>'f?p=&APP_ID.:1:&SESSION.'
,p_login_url=>'f?p=&APP_ID.:101:&SESSION.'
,p_checksum_salt=>'A4C2E1'
);
wwv_flow_imp_shared.create_build_option(
 p_id=>wwv_flow_imp.id(7301)
,p_build_option_name=>'FEATURE_BULK_CANCEL'
,p_build_option_status=>'EXCLUDE'
);
wwv_flow_imp_shared.create_authentication(
 p_id=>wwv_flow_imp.id(7101)
,p_name=>'Application Express Accounts'
,p_scheme_type=>'NATIVE_APEX_ACCOUNTS'
,p_is_current=>'Y'
);
wwv_flow_imp_shared.create_security_scheme(
 p_id=>wwv_flow_imp.id(7201)
,p_name=>'Order Clerk'
,p_scheme_type=>'NATIVE_FUNCTION_BODY'
,p_attribute_01=>wwv_flow_string.join(wwv_flow_t_varchar2(
'begin',
'  return order_pkg.is_order_clerk(p_user => :APP_USER);',
'end;'))
,p_error_message=>'You do not have the Order Clerk role.'
,p_caching=>'BY_USER_BY_PAGE_VIEW'
);
wwv_flow_imp_shared.create_security_scheme(
 p_id=>wwv_flow_imp.id(7202)
,p_name=>'Order Approver'
,p_scheme_type=>'NATIVE_EXISTS'
,p_attribute_01=>'select 1 from order_app.app_roles where username = :APP_USER and role_code = ''APPROVER'''
,p_error_message=>'Approver role required.'
);
wwv_flow_imp.create_flow_item(
 p_id=>wwv_flow_imp.id(7401)
,p_name=>'G_CURRENT_CUSTOMER_ID'
,p_protection_level=>'I'
);
wwv_flow_imp.create_flow_process(
 p_id=>wwv_flow_imp.id(7501)
,p_process_sequence=>10
,p_process_point=>'ON_NEW_INSTANCE'
,p_process_type=>'NATIVE_PLSQL'
,p_process_name=>'Initialise session'
,p_process_sql_clob=>wwv_flow_string.join(wwv_flow_t_varchar2(
'begin',
'  :G_CURRENT_CUSTOMER_ID := order_pkg.default_customer(p_user => :APP_USER);',
'end;'))
);
wwv_flow_imp.component_end;
end;
/
