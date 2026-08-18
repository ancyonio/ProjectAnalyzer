"""APEX graph vocabulary and tuning constants.

This module *is* the graph contract: labels, relationship types, impact
weights, resolution confidences, complexity weights, typed properties and the
Neo4j physical model. The validator, the exporter, the impact engine and the
reports all read from here, so there is one definition rather than several
that drift.

Changing a label or a relationship type here changes what the validator will
accept; adding one is a deliberate act, not a side effect.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

SCHEMA_VERSION = 'apex-1.0.0'

# ─────────────────────────────────────────────────────────────
# Node labels (§5)
# ─────────────────────────────────────────────────────────────
APEX_LABELS: Set[str] = {
    'ApexWorkspace', 'ApexApplication', 'ApexPage', 'ApexRegion', 'ApexItem',
    'ApexButton', 'ApexProcess', 'ApexValidation', 'ApexBranch',
    'ApexComputation', 'ApexDynamicAction', 'ApexDaAction', 'ApexReportColumn',
    'ApexLov', 'ApexList', 'ApexListEntry', 'ApexNavigation', 'ApexWebSource',
    'ApexWebSourceOperation', 'ApexAutomation', 'ApexPlugin',
    'ApexEmailTemplate', 'ApexAuthorization', 'ApexAuthentication',
    'ApexBuildOption',
}

CODE_LABELS: Set[str] = {'SqlStatement', 'PlsqlBlock', 'JsSnippet', 'BindVariable'}

DB_LABELS: Set[str] = {
    'DbSchema', 'DbTable', 'DbView', 'DbMaterializedView', 'DbPackage',
    'DbProgramUnit', 'DbTrigger', 'DbSequence', 'DbSynonym', 'DbType',
    'DbDatabaseLink', 'DbColumn', 'DbConstraint', 'DbIndex',
}

REPO_LABELS: Set[str] = {'Project', 'Repository', 'Branch', 'Commit', 'File'}

SEMANTIC_LABELS: Set[str] = {'BusinessDomain', 'BusinessFunction', 'BusinessTransaction'}

ANALYSIS_LABELS: Set[str] = {'Issue', 'Recommendation', 'Metric'}

# `DbObject` and `Unresolved` are secondary labels carried in `extraLabels`.
SECONDARY_LABELS: Set[str] = {'DbObject', 'Unresolved'}

KNOWN_LABELS: Set[str] = (APEX_LABELS | CODE_LABELS | DB_LABELS | REPO_LABELS
                          | SEMANTIC_LABELS | ANALYSIS_LABELS | SECONDARY_LABELS)

# Labels that also carry the generic `:DbObject` traversal label.
DB_OBJECT_LABELS: Set[str] = {
    'DbTable', 'DbView', 'DbMaterializedView', 'DbPackage', 'DbProgramUnit',
    'DbTrigger', 'DbSequence', 'DbSynonym', 'DbType', 'DbDatabaseLink',
}

# ─────────────────────────────────────────────────────────────
# Relationship vocabulary and impact weights (§6)
# ─────────────────────────────────────────────────────────────
REL_IMPACT_WEIGHTS: Dict[str, float] = {
    # structural
    'CONTAINS_PAGE': 0.9, 'CONTAINS_REGION': 0.9, 'CONTAINS_SUBREGION': 0.9,
    'CONTAINS_ITEM': 0.9, 'CONTAINS_BUTTON': 0.9, 'CONTAINS_PROCESS': 0.9,
    'CONTAINS_VALIDATION': 0.9, 'CONTAINS_BRANCH': 0.9,
    'CONTAINS_COMPUTATION': 0.9, 'CONTAINS_DYNAMIC_ACTION': 0.9,
    'CONTAINS_ACTION': 0.9, 'CONTAINS_COLUMN': 0.8, 'HAS_COLUMN': 0.9,
    'HAS_UNIT': 0.9, 'OWNS': 0.2, 'BELONGS_TO': 0.05,
    # behavioural
    'EXECUTES_SQL': 0.85, 'EXECUTES_PLSQL': 0.85, 'EXECUTES_JS': 0.4,
    'TRIGGERS': 0.8, 'SUBMITS_TO': 0.6, 'NAVIGATES_TO': 0.5, 'USES_LOV': 0.7,
    'VALIDATES': 0.6, 'SECURED_BY': 0.6, 'AUTHENTICATED_BY': 0.3,
    'CONDITIONED_BY': 0.4, 'SETS_ITEM': 0.6, 'BINDS_ITEM': 0.7,
    'CALLS_WEB_SOURCE': 0.7, 'RUNS': 0.8,
    # data access
    'READS_FROM': 1.0, 'WRITES_TO': 1.0, 'INSERTS_INTO': 1.0, 'UPDATES': 1.0,
    'DELETES_FROM': 1.0, 'CALLS': 0.9, 'REFERENCES_COLUMN': 0.8,
    'SOURCED_FROM': 0.9, 'USES_SEQUENCE': 0.5, 'RESOLVES_TO': 0.9,
    'DEPENDS_ON': 0.8, 'FIRES_ON': 0.7, 'CONSTRAINS': 0.3,
    'REFERENCES_TABLE': 0.6,
    # repository, semantic, analysis
    'CONTAINS_FILE': 0.1, 'DEFINES': 0.7, 'HAS_BRANCH': 0.05,
    'HAS_COMMIT': 0.05, 'CHANGED': 0.6, 'IMPLEMENTED_BY': 0.7,
    'PART_OF_DOMAIN': 0.2, 'HAS_ISSUE': 0.0, 'AFFECTS': 0.0,
    'HAS_RECOMMENDATION': 0.0,
}

KNOWN_REL_TYPES: Set[str] = set(REL_IMPACT_WEIGHTS)

# Never walked during blast-radius expansion: they would drag in the whole
# application (or every finding) and destroy signal.
IMPACT_EXCLUDED_RELS: Set[str] = {
    'BELONGS_TO', 'OWNS', 'CONTAINS_FILE', 'DEFINES', 'HAS_BRANCH',
    'HAS_COMMIT', 'HAS_ISSUE', 'AFFECTS', 'HAS_RECOMMENDATION',
    'PART_OF_DOMAIN',
    # Package membership is structural, not a dependency path: calling
    # ORDER_PKG.SAVE_ORDER must not make ORDER_PKG.ARCHIVE_ORDERS — and every
    # table it writes — look reachable. Unit-level CALLS edges carry the real
    # dependency, and a package-level CALLS edge is emitted alongside them.
    'HAS_UNIT',
}

# Relationship types that are asserted by APEX/Oracle metadata rather than
# inferred by this analyzer; they carry no confidence property.
EXTRACTED_RELS: Set[str] = {
    'CONTAINS_PAGE', 'CONTAINS_REGION', 'CONTAINS_SUBREGION', 'CONTAINS_ITEM',
    'CONTAINS_BUTTON', 'CONTAINS_PROCESS', 'CONTAINS_VALIDATION',
    'CONTAINS_BRANCH', 'CONTAINS_COMPUTATION', 'CONTAINS_DYNAMIC_ACTION',
    'CONTAINS_ACTION', 'CONTAINS_COLUMN', 'HAS_COLUMN', 'HAS_UNIT', 'OWNS',
    'BELONGS_TO', 'EXECUTES_SQL', 'EXECUTES_PLSQL', 'EXECUTES_JS',
    'SECURED_BY', 'AUTHENTICATED_BY', 'CONDITIONED_BY', 'USES_LOV',
    'VALIDATES', 'RUNS', 'CALLS_WEB_SOURCE', 'RESOLVES_TO', 'DEPENDS_ON',
    'FIRES_ON', 'CONSTRAINS', 'REFERENCES_TABLE', 'CONTAINS_FILE', 'DEFINES',
    'HAS_BRANCH', 'HAS_COMMIT', 'CHANGED', 'HAS_ISSUE', 'AFFECTS',
    'HAS_RECOMMENDATION', 'IMPLEMENTED_BY', 'PART_OF_DOMAIN', 'SUBMITS_TO',
}

MULTIPLIERS: Dict[str, float] = {
    'ApexPage': 3.0, 'ApexRegion': 1.2, 'ApexProcess': 1.5, 'ApexItem': 0.4,
    'ApexButton': 0.4, 'ApexDaAction': 0.4, 'ApexLov': 1.0,
    'SqlStatement': 0.8, 'PlsqlBlock': 0.8, 'DbTable': 2.0, 'DbView': 2.0,
    'DbPackage': 2.0, 'DbProgramUnit': 1.5, 'DbColumn': 0.3, 'File': 0.2,
    'Issue': 0.0, 'Recommendation': 0.0,
}

# ─────────────────────────────────────────────────────────────
# Export API surface (§3)
# ─────────────────────────────────────────────────────────────
# Procedure names are matched without their package prefix, because APEX 21.2
# renamed `wwv_flow_api` to `wwv_flow_imp*` without changing the procedures.
EXPORT_API_PACKAGES = ('wwv_flow_api', 'wwv_flow_imp', 'wwv_flow_imp_page',
                       'wwv_flow_imp_shared', 'wwv_flow_imp_directory')

# Procedures deliberately ignored: presentation-only or install plumbing.
IGNORED_PROCEDURES: Set[str] = {
    'component_begin', 'component_end', 'import_begin', 'import_end',
    'set_security_group_id', 'set_flow_status', 'remove_flow',
    'create_page_plug_template', 'create_template', 'create_theme',
    'create_theme_style', 'create_theme_file', 'create_theme_display_point',
    'create_page_template', 'create_field_template', 'create_menu_template',
    'create_popup_lov_template', 'create_report_layout', 'create_shortcut',
    'create_image', 'create_css', 'create_javascript', 'create_static_file',
    'create_app_static_file', 'create_plugin_file', 'create_upgrade_flow',
    'create_install', 'create_install_script', 'create_install_checks',
    'set_component_ids', 'g_varchar2_table', 'create_worksheet_rpt',
    'create_page_generic_attr', 'create_report_layout_file',
}

# ─────────────────────────────────────────────────────────────
# Component classification
# ─────────────────────────────────────────────────────────────
# Region source types whose `p_plug_source` is SQL.
SQL_REGION_SOURCE_TYPES: Set[str] = {
    'NATIVE_IR', 'NATIVE_IG', 'NATIVE_SQL_REPORT', 'NATIVE_TABFORM',
    'NATIVE_CHART', 'NATIVE_LIST_VIEW', 'NATIVE_CARDS', 'NATIVE_JASPER',
    'NATIVE_CALENDAR', 'NATIVE_TREE', 'NATIVE_MAP_CHART', 'NATIVE_FORM',
    'NATIVE_SQL_QUERY', 'NATIVE_DML_FORM',
}

# Region source types whose `p_plug_source` is PL/SQL producing markup.
PLSQL_REGION_SOURCE_TYPES: Set[str] = {
    'NATIVE_PLSQL', 'NATIVE_DYNAMIC_CONTENT',
}

# Process types whose source is PL/SQL.
PLSQL_PROCESS_TYPES: Set[str] = {
    'NATIVE_PLSQL', 'NATIVE_PLSQL_CODE', 'NATIVE_EXEC_PLSQL',
    'NATIVE_INVOKE_API', 'NATIVE_PLSQL_BODY',
}

# Process types that perform DML declaratively (no code to parse, but they
# still write to a table).
DML_PROCESS_TYPES: Set[str] = {
    'NATIVE_FORM_DML', 'NATIVE_FORM_PAGINATION', 'NATIVE_TABFORM_UPDATE',
    'NATIVE_IG_DML', 'NATIVE_FORM_FETCH', 'NATIVE_FORM_PROCESS',
}

# Validation types whose expression is SQL / PL/SQL rather than a literal.
SQL_VALIDATION_TYPES: Set[str] = {'EXISTS', 'NOT_EXISTS', 'SQL_EXPRESSION', 'SQL_EXP'}
PLSQL_VALIDATION_TYPES: Set[str] = {
    'FUNC_BODY_RETURNING_BOOLEAN', 'FUNC_BODY_RETURNING_ERR_TEXT',
    'PLSQL_EXPRESSION', 'PLSQL_ERROR',
}

# Dynamic action types and which attribute holds their code.
DA_CODE_ATTRIBUTES: Dict[str, Tuple[str, str]] = {
    'NATIVE_EXECUTE_PLSQL_CODE': ('attribute01', 'PLSQL'),
    'NATIVE_JAVASCRIPT_CODE': ('attribute01', 'JS'),
    'NATIVE_SET_VALUE': ('attribute06', 'SQL'),        # SQL statement source
    'NATIVE_DIALOG_CLOSE': ('attribute01', 'NONE'),
}

# Condition types whose expression is code.
SQL_CONDITION_TYPES: Set[str] = {'EXISTS', 'NOT_EXISTS'}
PLSQL_CONDITION_TYPES: Set[str] = {
    'FUNCTION_BODY', 'PLSQL_EXPRESSION', 'FUNC_BODY_RETURNING_BOOLEAN',
    'EXPRESSION',
}

# Authorization scheme types carrying code.
SQL_AUTH_TYPES: Set[str] = {'NATIVE_EXISTS', 'NATIVE_NOT_EXISTS', 'EXISTS', 'NOT_EXISTS'}
PLSQL_AUTH_TYPES: Set[str] = {
    'NATIVE_FUNCTION_BODY', 'FUNCTION_BODY', 'NATIVE_PLSQL_EXPRESSION',
    'PLSQL_EXPRESSION',
}

PAGE_PROTECTION_LEVELS: Dict[str, str] = {
    'U': 'UNRESTRICTED',
    'C': 'ARGUMENTS_MUST_HAVE_CHECKSUM',
    'A': 'ARGUMENTS_MUST_HAVE_CHECKSUM',
    'N': 'NO_ARGUMENTS_ALLOWED',
    'D': 'NO_URL_ACCESS',
    'I': 'NO_URL_ACCESS',
}

ITEM_PROTECTION_LEVELS: Dict[str, str] = {
    'N': 'NONE', 'U': 'UNRESTRICTED', 'C': 'CHECKSUM_USER',
    'S': 'CHECKSUM_SESSION', 'A': 'CHECKSUM_APPLICATION', 'I': 'RESTRICTED',
}

# ─────────────────────────────────────────────────────────────
# SQL / PL/SQL analysis (§10)
# ─────────────────────────────────────────────────────────────
RESOLUTION_CONFIDENCE: Dict[str, float] = {
    'exact': 1.00,
    'schema_default': 0.95,
    'synonym': 0.90,
    'heuristic': 0.70,
    'dynamic': 0.40,
    'unresolved': 0.00,
}

# Names that look like tables in a FROM clause but never are.
SQL_PSEUDO_TABLES: Set[str] = {'DUAL', 'TABLE', 'XMLTABLE', 'JSON_TABLE', 'LATERAL'}

SQL_RESERVED: Set[str] = {
    'SELECT', 'FROM', 'WHERE', 'GROUP', 'ORDER', 'BY', 'HAVING', 'JOIN',
    'INNER', 'LEFT', 'RIGHT', 'FULL', 'OUTER', 'CROSS', 'NATURAL', 'ON',
    'USING', 'UNION', 'ALL', 'MINUS', 'INTERSECT', 'AND', 'OR', 'NOT', 'IN',
    'EXISTS', 'BETWEEN', 'LIKE', 'IS', 'NULL', 'AS', 'WITH', 'CONNECT',
    'START', 'PRIOR', 'DISTINCT', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
    'INTO', 'VALUES', 'SET', 'UPDATE', 'INSERT', 'DELETE', 'MERGE', 'RETURNING',
    'FETCH', 'NEXT', 'ROWS', 'ONLY', 'OFFSET', 'PARTITION', 'OVER', 'ASC',
    'DESC', 'NULLS', 'FIRST', 'LAST', 'FOR', 'LOOP', 'IF', 'BEGIN', 'DECLARE',
}

# Built-in packages: calls to these are not application dependencies.
ORACLE_BUILTIN_PACKAGES: Set[str] = {
    'DBMS_OUTPUT', 'DBMS_SQL', 'DBMS_LOB', 'DBMS_UTILITY', 'DBMS_RANDOM',
    'DBMS_SCHEDULER', 'DBMS_SESSION', 'DBMS_CRYPTO', 'DBMS_METADATA',
    'DBMS_ASSERT', 'DBMS_XMLGEN', 'DBMS_JOB', 'DBMS_STATS', 'DBMS_AQ',
    'UTL_FILE', 'UTL_HTTP', 'UTL_SMTP', 'UTL_RAW', 'UTL_URL', 'UTL_I18N',
    'UTL_ENCODE', 'JSON_OBJECT_T', 'JSON_ARRAY_T', 'JSON_ELEMENT_T',
    'STANDARD', 'SYS', 'HTP', 'HTF', 'OWA_UTIL', 'SDO_GEOM',
}

# APEX runtime packages: recorded as platform calls, not application code.
APEX_RUNTIME_PACKAGES: Set[str] = {
    'APEX_UTIL', 'APEX_APPLICATION', 'APEX_ITEM', 'APEX_ERROR', 'APEX_DEBUG',
    'APEX_JSON', 'APEX_WEB_SERVICE', 'APEX_MAIL', 'APEX_COLLECTION',
    'APEX_ESCAPE', 'APEX_STRING', 'APEX_SESSION', 'APEX_AUTHORIZATION',
    'APEX_CUSTOM_AUTH', 'APEX_LANG', 'APEX_PAGE', 'APEX_APPLICATION_PAGE',
    'APEX_EXEC', 'APEX_ZIP', 'APEX_DATA_PARSER', 'APEX_REGION', 'APEX_IR',
    'WWV_FLOW_API', 'V', 'NV',
}

DEPRECATED_APIS: Set[str] = {
    'APEX_UTIL.STRING_TO_TABLE', 'APEX_UTIL.TABLE_TO_STRING',
    'APEX_UTIL.COUNT_CLICK', 'APEX_UTIL.KEYVAL_NUM', 'APEX_UTIL.KEYVAL_VC2',
    'APEX_PLSQL_JOB.SUBMIT_PROCESS', 'HTMLDB_UTIL.STRING_TO_TABLE',
}

BIND_RE = re.compile(r':([A-Za-z][A-Za-z0-9_$#]*)')
SUBSTITUTION_RE = re.compile(r'&([A-Za-z][A-Za-z0-9_$#]*)\.')
PAGE_ITEM_RE = re.compile(r'^P\d+_', re.IGNORECASE)

# ─────────────────────────────────────────────────────────────
# Complexity model (§11)
# ─────────────────────────────────────────────────────────────
COMPLEXITY_WEIGHTS: Dict[str, float] = {
    'regionCount': 1.0,
    'itemCount': 0.5,
    'processCount': 2.0,
    'dynamicActionCount': 1.5,
    'validationCount': 1.0,
    'branchCount': 1.0,
    'sqlStatementCount': 2.5,
    'plsqlBlockCount': 3.0,
    'tableCount': 2.0,
    'packageCount': 4.0,
    'writeCount': 5.0,
    'unresolvedCount': 3.0,
    'jsWeight': 2.0,
}

COMPLEXITY_TIERS: List[Tuple[float, str]] = [
    (60.0, 'Critical'),
    (35.0, 'High'),
    (15.0, 'Medium'),
    (0.0, 'Low'),
]

# Coverage below this makes the graph provisional (§15, AX-COVERAGE).
MIN_RESOLUTION_COVERAGE = 0.80
MAX_PARSE_FAILURE_RATE = 0.05

# ─────────────────────────────────────────────────────────────
# Neo4j physical model (§14)
# ─────────────────────────────────────────────────────────────
INT_FIELDS: Set[str] = {
    'applicationId', 'pageId', 'regionId', 'displaySequence', 'sequence',
    'executionSequence', 'regionCount', 'itemCount', 'processCount',
    'validationCount', 'branchCount', 'dynamicActionCount', 'pageCount',
    'lineCount', 'tableCount', 'joinCount', 'bindCount', 'callCount',
    'columnCount', 'entryCount', 'argumentCount', 'numRows', 'columnId',
    'dataLength', 'specLines', 'bodyLines', 'unitCount', 'sourceLine',
    'targetPageId', 'writeCount', 'unresolvedCount', 'sqlStatementCount',
    'plsqlBlockCount', 'packageCount', 'fanOut', 'fanIn', 'dependencyDepth',
    'bytes', 'overload',
}

FLOAT_FIELDS: Set[str] = {'complexityScore', 'confidence', 'value', 'couplingIndex'}

BOOL_FIELDS: Set[str] = {
    'isPublic', 'requiresLogin', 'isRequired', 'hasSql', 'hasPlsql',
    'hasSelectStar', 'hasHint', 'hasDbLink', 'isDynamic', 'hasExceptionHandler',
    'hasWhenOthersNull', 'hasCommit', 'hasDynamicSql', 'usesApexServerProcess',
    'isPk', 'isFk', 'nullable', 'partitioned', 'hasPk', 'isUpdatable',
    'isStandalone', 'isParsingSchema', 'isCurrent', 'defaultOnExport',
    'fireOnInit', 'isSortable', 'isStandard', 'isTransactional',
}

COMPOSITE_CONSTRAINTS: List[Tuple[str, List[str]]] = [
    ('ApexPage', ['applicationId', 'pageId']),
    ('DbColumn', ['owner', 'tableName', 'name']),
]

SECONDARY_INDEXES: List[Tuple[str, List[str]]] = [
    ('ApexPage', ['applicationId']),
    ('ApexPage', ['tier']),
    ('ApexRegion', ['regionType']),
    ('ApexItem', ['itemName']),
    ('ApexProcess', ['pointCode']),
    ('DbTable', ['owner']),
    ('DbColumn', ['tableName', 'name']),
    ('SqlStatement', ['sqlHash']),
    ('PlsqlBlock', ['codeHash']),
    ('Issue', ['severity', 'category']),
    ('ApexPage', ['datasetId']),
    ('DbTable', ['datasetId']),
]

FULLTEXT_INDEXES: List[Tuple[str, List[str], List[str]]] = [
    ('apex_code_ft', ['SqlStatement', 'PlsqlBlock', 'JsSnippet'], ['text']),
    ('apex_name_ft', ['ApexPage', 'ApexRegion', 'ApexItem', 'ApexProcess',
                      'DbTable', 'DbView', 'DbPackage', 'DbProgramUnit'], ['name']),
]

ORPHAN_TOLERANT_LABELS: Set[str] = {
    'ApexBuildOption', 'DbIndex', 'DbConstraint', 'BusinessDomain', 'Metric',
    'ApexEmailTemplate', 'ApexPlugin', 'Commit', 'Branch', 'Repository',
    'DbSequence', 'DbType', 'DbDatabaseLink', 'ApexAuthentication',
}

REQUIRED_REL_TYPES: Set[str] = {'CONTAINS_PAGE', 'BELONGS_TO'}

ID_PATTERN = re.compile(r'^[A-Za-z0-9_.:#$/@ -]+$')

# ─────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────
INDEXED_LABELS: Set[str] = {
    'ApexPage', 'ApexRegion', 'ApexItem', 'ApexProcess', 'ApexDynamicAction',
    'ApexValidation', 'ApexLov', 'ApexAuthorization', 'SqlStatement',
    'PlsqlBlock', 'DbTable', 'DbView', 'DbPackage', 'DbProgramUnit', 'DbColumn',
}

SEARCH_SYNONYMS: Dict[str, List[str]] = {
    'page': ['screen', 'form', 'report'],
    'report': ['grid', 'interactive', 'classic', 'ig', 'ir'],
    'form': ['dml', 'insert', 'update', 'entry'],
    'lov': ['list', 'values', 'dropdown', 'select'],
    'auth': ['authorization', 'security', 'privilege', 'role'],
    'login': ['authentication', 'session', 'user'],
    'sql': ['query', 'select', 'statement'],
    'plsql': ['procedure', 'function', 'package', 'block'],
    'table': ['entity', 'relation', 'store'],
    'column': ['field', 'attribute'],
    'delete': ['remove', 'purge'],
    'insert': ['create', 'add', 'new'],
    'update': ['modify', 'edit', 'change'],
    'customer': ['client', 'party', 'account'],
    'order': ['purchase', 'sales'],
    'payment': ['billing', 'settlement', 'charge'],
}
