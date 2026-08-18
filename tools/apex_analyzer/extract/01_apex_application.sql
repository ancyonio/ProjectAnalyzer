-- APEX application-level metadata. Read-only.
--   sql> @01_apex_application.sql 100
-- Emits the `application`, `authentication`, `authorization` and
-- `buildOptions` sections of apex_meta.json.

set feedback off
set heading off
set pagesize 0
set linesize 32767
set long 2000000000

define app_id = '&1'

select json_object(
  'application' value (
     select json_arrayagg(json_object('applicationId' value a.application_id,
                                      'name' value a.application_name,
                                      'alias' value a.alias,
                                      'owner' value a.owner,
                                      'version' value a.version,
                                      'authenticationScheme' value a.authentication_scheme,
                                      'compatibilityMode' value a.compatibility_mode,
                                      'friendlyUrls' value a.friendly_url,
                                      'pages' value a.pages,
                                      'lastUpdatedOn' value to_char(a.last_updated_on,
                                                                    'YYYY-MM-DD HH24:MI:SS')
                                      returning clob) returning clob)
       from apex_applications a
      where a.application_id = to_number('&app_id')),

  'authentication' value (
     select json_arrayagg(json_object('name' value s.authentication_scheme_name,
                                      'schemeType' value s.scheme_type,
                                      'isCurrent' value s.is_current
                                      returning clob) returning clob)
       from apex_application_auth s
      where s.application_id = to_number('&app_id')),

  'authorization' value (
     select json_arrayagg(json_object('name' value z.authorization_scheme_name,
                                      'schemeType' value z.scheme_type,
                                      'evaluationPoint' value z.caching,
                                      'errorMessage' value z.error_message
                                      returning clob) returning clob)
       from apex_application_authorization z
      where z.application_id = to_number('&app_id')),

  'buildOptions' value (
     select json_arrayagg(json_object('name' value b.build_option_name,
                                      'status' value b.build_option_status
                                      returning clob) returning clob)
       from apex_application_build_options b
      where b.application_id = to_number('&app_id'))
  returning clob) as apex_application
from dual;
