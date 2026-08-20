"""Vocabulary and physical-model configuration for the estate analyzer.

One catalogue, consumed by `graph/schema.py`, which turns it into the Neo4j
export schema, the validation configuration and the impact configuration --
the same arrangement the APEX and Oracle analyzers use.

The vocabulary is the **union** of the three dialects, declared here rather
than imported. The wrapper deliberately imports nothing from `tibco_analyzer`,
`apex_analyzer` or `oracle_analyzer`: it reads their `graph.json` output and
nothing else, which is what keeps the rule in AGENTS.md -- no analyzer imports
another -- true. The cost is that a dialect which adds a label must add it here
too; the benefit is that the validator says so loudly (`AX-VOCAB`) instead of
the wrapper silently importing a shape it does not understand.

See README.md#cross-estate-analysis.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

SCHEMA_VERSION = 'estate-1.0.0'

# ─────────────────────────────────────────────────────────────
# Estates
# ─────────────────────────────────────────────────────────────
# Order matters: it decides which estate wins a property conflict on a node
# two estates both contributed, and it is the order everything is reported in.
ESTATES: Tuple[str, ...] = ('tibco', 'apex', 'oracle')

ESTATE_TITLES: Dict[str, str] = {
    'tibco': 'TIBCO BusinessWorks',
    'apex': 'Oracle APEX',
    'oracle': 'Oracle PL/SQL',
}

DEFAULT_OUTPUT_DIRS: Dict[str, str] = {
    'tibco': 'analysis_output',
    'apex': 'analysis_output_apex',
    'oracle': 'analysis_output_oracle',
}

# Rule-id prefix per estate. `SEC-001` means two different things in APEX and
# Oracle, so an unprefixed merge of the two ledgers is simply wrong.
RULE_PREFIXES: Dict[str, str] = {'tibco': 'TIB.', 'apex': 'APEX.', 'oracle': 'ORA.'}

# ─────────────────────────────────────────────────────────────
# Node identity
# ─────────────────────────────────────────────────────────────
# Id families that are NOT namespaced, because two estates naming the same id
# mean the same object. This is the whole point of the shared
# `analyzer_core.ids` grammar and the only intentional merge in the design.
SHARED_ID_PREFIXES: Tuple[str, ...] = ('db:',)

# Content-addressed families are namespaced on purpose: merging them would
# hide the duplicate-logic finding (XE-004) that compares their digests.
CONTENT_ID_PREFIXES: Tuple[str, ...] = ('sql:', 'plsql:', 'js:')

ESTATE_ID_SEP = ':'

# ─────────────────────────────────────────────────────────────
# Confidence ladder (spec section 4)
# ─────────────────────────────────────────────────────────────
CONFIDENCE: Dict[str, float] = {
    'exact': 1.0,            # same natural key in both graphs
    'declared': 0.9,         # the operator stated it in the estate map
    'qualified-name': 0.8,   # owner.name matched after normalisation
    'name': 0.5,             # a bare name matched exactly one object
}

# Bare-name matches are computed and reported always, but only enter the graph
# when the operator opts in.
DEFAULT_ALLOWED_BASES: Tuple[str, ...] = ('exact', 'declared', 'qualified-name')

# ─────────────────────────────────────────────────────────────
# Labels: the union of the three dialects, plus `Estate`
# ─────────────────────────────────────────────────────────────
TIBCO_LABELS: Set[str] = {
    'Module', 'BWProcess', 'Activity', 'Group', 'ErrorHandler', 'XSD',
    'Element', 'ComplexType', 'Service', 'Operation', 'SharedResource',
    'Adapter', 'System', 'GlobalVariable', 'DataTransformation', 'AESchema',
    'ExternalReference',
}

APEX_LABELS: Set[str] = {
    'ApexWorkspace', 'ApexApplication', 'ApexPage', 'ApexRegion', 'ApexItem',
    'ApexButton', 'ApexProcess', 'ApexValidation', 'ApexBranch',
    'ApexComputation', 'ApexDynamicAction', 'ApexDaAction', 'ApexReportColumn',
    'ApexLov', 'ApexList', 'ApexListEntry', 'ApexNavigation', 'ApexWebSource',
    'ApexWebSourceOperation', 'ApexAutomation', 'ApexPlugin',
    'ApexEmailTemplate', 'ApexAuthorization', 'ApexAuthentication',
    'ApexBuildOption',
}

DB_LABELS: Set[str] = {
    'DbSchema', 'DbTable', 'DbView', 'DbMaterializedView', 'DbPackage',
    'PackageSpec', 'PackageBody', 'DbProgramUnit', 'DbTrigger', 'DbSequence',
    'DbSynonym', 'DbType', 'DbDatabaseLink', 'DbColumn', 'DbConstraint',
    'DbIndex',
}

CODE_LABELS: Set[str] = {'SqlStatement', 'PlsqlBlock', 'JsSnippet', 'BindVariable'}

REPO_LABELS: Set[str] = {'Project', 'Repository', 'Branch', 'Commit',
                         'Developer', 'Directory', 'File'}

SEMANTIC_LABELS: Set[str] = {'BusinessDomain', 'BusinessFunction',
                             'BusinessTransaction', 'TestCase'}

ANALYSIS_LABELS: Set[str] = {'Issue', 'Recommendation', 'Metric', 'CodeMetric',
                             'UnresolvedRef'}

# Carried in `extraLabels`, never as a primary label.
SECONDARY_LABELS: Set[str] = {'DbObject', 'Unresolved', 'Federated'}

FEDERATION_LABELS: Set[str] = {'Estate'}

KNOWN_LABELS: Set[str] = (TIBCO_LABELS | APEX_LABELS | DB_LABELS | CODE_LABELS
                          | REPO_LABELS | SEMANTIC_LABELS | ANALYSIS_LABELS
                          | SECONDARY_LABELS | FEDERATION_LABELS)

# The containers an `Estate` node points at, in preference order.
ESTATE_ROOT_LABELS: Dict[str, Tuple[str, ...]] = {
    'tibco': ('Module',),
    'apex': ('ApexApplication', 'ApexWorkspace', 'Project'),
    'oracle': ('DbSchema', 'Repository', 'Project'),
}

# ─────────────────────────────────────────────────────────────
# Relationships
# ─────────────────────────────────────────────────────────────
TIBCO_RELS: Set[str] = {
    'BELONGS_TO', 'CALLS', 'CALLS_EXTERNAL', 'CONFIGURED_BY', 'CONFIGURES',
    'CONNECTS_TO', 'CONTAINS', 'DEPENDS_ON', 'EXECUTES', 'EXPOSES',
    'HANDLES_ERROR', 'HAS_GROUP', 'IMPORTS_SCHEMA', 'REFERENCES',
    'TRANSITIONS_TO', 'USES_WSDL', 'USES_XSD',
}

APEX_RELS: Set[str] = {
    'CONTAINS_PAGE', 'CONTAINS_REGION', 'CONTAINS_SUBREGION', 'CONTAINS_ITEM',
    'CONTAINS_BUTTON', 'CONTAINS_PROCESS', 'CONTAINS_VALIDATION',
    'CONTAINS_BRANCH', 'CONTAINS_COMPUTATION', 'CONTAINS_DYNAMIC_ACTION',
    'CONTAINS_ACTION', 'CONTAINS_COLUMN', 'EXECUTES_JS', 'TRIGGERS',
    'SUBMITS_TO', 'NAVIGATES_TO', 'USES_LOV', 'VALIDATES', 'SECURED_BY',
    'AUTHENTICATED_BY', 'CONDITIONED_BY', 'SETS_ITEM', 'BINDS_ITEM',
    'CALLS_WEB_SOURCE', 'RUNS', 'SOURCED_FROM', 'REFERENCES_TABLE',
    'IMPLEMENTED_BY', 'PART_OF_DOMAIN',
}

ORACLE_RELS: Set[str] = {
    'CONTAINS_FILE', 'DEFINES', 'OWNS', 'HAS_COLUMN', 'HAS_INDEX',
    'CONSTRAINS', 'HAS_SPEC', 'HAS_BODY', 'HAS_UNIT', 'DEPENDS_ON',
    'RESOLVES_TO', 'USES_SEQUENCE', 'USES_TYPE', 'REFERENCES_DBLINK',
    'FIRES_ON', 'EXECUTES_SQL', 'EXECUTES_PLSQL', 'HAS_METRIC', 'UNRESOLVED',
    'REFERENCES_COLUMN', 'JOINS', 'HAS_TEST',
}

DATA_ACCESS_RELS: Set[str] = {'READS_FROM', 'WRITES_TO', 'INSERTS_INTO',
                              'UPDATES', 'DELETES_FROM'}

ANALYSIS_RELS: Set[str] = {'HAS_ISSUE', 'HAS_RECOMMENDATION', 'AFFECTS'}

GIT_RELS: Set[str] = {'HAS_COMMIT', 'HAS_BRANCH', 'CHANGED', 'AUTHORED_BY'}

# Added by the wrapper and by nothing else.
FEDERATION_RELS: Set[str] = {'CONTAINS_ESTATE', 'CONNECTS_TO_SCHEMA'}

KNOWN_REL_TYPES: Set[str] = (TIBCO_RELS | APEX_RELS | ORACLE_RELS
                             | DATA_ACCESS_RELS | ANALYSIS_RELS | GIT_RELS
                             | FEDERATION_RELS)

REQUIRED_REL_TYPES: Set[str] = {'CONTAINS_ESTATE'}

# The specific verb is emitted alongside the WRITES_TO roll-up, exactly as the
# Oracle analyzer does, so a traversal can use one edge while lineage uses the
# precise one.
WRITE_VERBS: Dict[str, str] = {
    'INSERT': 'INSERTS_INTO',
    'UPDATE': 'UPDATES',
    'DELETE': 'DELETES_FROM',
    'MERGE': 'UPDATES',
    'TRUNCATE': 'DELETES_FROM',
}

READ_VERBS: Tuple[str, ...] = ('SELECT',)

# ─────────────────────────────────────────────────────────────
# Findings
# ─────────────────────────────────────────────────────────────
SEVERITY_ORDER: List[str] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

# APEX spells one concept `TECH_DEBT` and Oracle spells it `DEBT`. Merging the
# ledgers without canonicalising produces two categories for one idea.
CATEGORY_CANON: Dict[str, str] = {
    'TECH_DEBT': 'DEBT',
    'TECHDEBT': 'DEBT',
    'DEBT': 'DEBT',
    'SECURITY': 'SECURITY',
    'PERFORMANCE': 'PERFORMANCE',
    'CORRECTNESS': 'CORRECTNESS',
    'MAINTAINABILITY': 'DEBT',
    'CROSS_ESTATE': 'CROSS_ESTATE',
}

CATEGORIES: Tuple[str, ...] = ('SECURITY', 'PERFORMANCE', 'CORRECTNESS',
                               'DEBT', 'CROSS_ESTATE')

# ─────────────────────────────────────────────────────────────
# Coverage gates (spec section 6)
# ─────────────────────────────────────────────────────────────
MIN_SQL_BIND_COVERAGE = 80.0
MIN_DATASOURCE_COVERAGE = 80.0

# Activity categories that reach a database. Anything here with a static SQL
# statement is expected to bind; anything here without one is a declared blind
# spot, not a silent omission.
JDBC_CATEGORIES: Tuple[str, ...] = ('JDBC_QUERY', 'JDBC_UPDATE',
                                    'JDBC_GENERAL', 'JDBC_STORED_PROC')

# ─────────────────────────────────────────────────────────────
# Impact model
# ─────────────────────────────────────────────────────────────
# Union of the three dialects. Where two dialects weight the same edge type
# differently the stronger weight wins, because a federated traversal should
# not lose reach that a single-estate traversal would have had.
REL_IMPACT_WEIGHTS: Dict[str, float] = {
    # data access -- the spine of every cross-estate answer
    'READS_FROM': 1.0, 'WRITES_TO': 1.0, 'INSERTS_INTO': 1.0,
    'UPDATES': 1.0, 'DELETES_FROM': 1.0, 'REFERENCES_COLUMN': 0.8,
    'JOINS': 0.4, 'HAS_TEST': 0.6,
    # code execution
    'EXECUTES': 0.9, 'EXECUTES_SQL': 0.95, 'EXECUTES_PLSQL': 0.95,
    'EXECUTES_JS': 0.4, 'CALLS': 1.0, 'CALLS_EXTERNAL': 0.6,
    # TIBCO control flow and structure
    'TRANSITIONS_TO': 0.6, 'HANDLES_ERROR': 0.5, 'HAS_GROUP': 0.5,
    'CONTAINS': 0.4, 'REFERENCES': 0.8, 'CONFIGURED_BY': 0.7,
    'CONNECTS_TO': 0.3, 'CONFIGURES': 0.4, 'EXPOSES': 0.9,
    'USES_XSD': 0.7, 'USES_WSDL': 0.7, 'IMPORTS_SCHEMA': 0.6,
    # APEX structure and behaviour
    'CONTAINS_PAGE': 0.9, 'CONTAINS_REGION': 0.9, 'CONTAINS_SUBREGION': 0.9,
    'CONTAINS_ITEM': 0.9, 'CONTAINS_BUTTON': 0.9, 'CONTAINS_PROCESS': 0.9,
    'CONTAINS_VALIDATION': 0.9, 'CONTAINS_BRANCH': 0.9,
    'CONTAINS_COMPUTATION': 0.9, 'CONTAINS_DYNAMIC_ACTION': 0.9,
    'CONTAINS_ACTION': 0.9, 'CONTAINS_COLUMN': 0.8,
    'TRIGGERS': 0.8, 'SUBMITS_TO': 0.6, 'NAVIGATES_TO': 0.5, 'USES_LOV': 0.7,
    'VALIDATES': 0.6, 'SECURED_BY': 0.6, 'AUTHENTICATED_BY': 0.3,
    'CONDITIONED_BY': 0.4, 'SETS_ITEM': 0.6, 'BINDS_ITEM': 0.7,
    'CALLS_WEB_SOURCE': 0.7, 'RUNS': 0.8, 'SOURCED_FROM': 0.9,
    'REFERENCES_TABLE': 0.6, 'IMPLEMENTED_BY': 0.7,
    # database structure
    'HAS_COLUMN': 0.6, 'CONSTRAINS': 0.5, 'HAS_INDEX': 0.3,
    'HAS_SPEC': 0.9, 'HAS_BODY': 0.4, 'DEPENDS_ON': 0.85, 'FIRES_ON': 0.9,
    'RESOLVES_TO': 0.9, 'USES_SEQUENCE': 0.5, 'USES_TYPE': 0.7,
    'REFERENCES_DBLINK': 0.4,
    # federation
    'CONNECTS_TO_SCHEMA': 0.6,
}

# Structure is not a dependency path, and neither is estate membership.
IMPACT_EXCLUDED_RELS: Set[str] = {
    'BELONGS_TO', 'OWNS', 'CONTAINS_FILE', 'DEFINES', 'HAS_UNIT',
    'HAS_BRANCH', 'HAS_COMMIT', 'CHANGED', 'AUTHORED_BY', 'HAS_ISSUE',
    'AFFECTS', 'HAS_RECOMMENDATION', 'HAS_METRIC', 'UNRESOLVED',
    'PART_OF_DOMAIN', 'CONTAINS_ESTATE',
}

MULTIPLIERS: Dict[str, float] = {
    # user-visible surfaces weigh most, in every estate
    'ApexPage': 3.0, 'BWProcess': 2.5, 'Service': 2.2, 'Operation': 2.0,
    'PackageSpec': 2.2, 'DbTable': 2.0, 'DbView': 2.0,
    'DbMaterializedView': 2.0, 'DbPackage': 2.0,
    'DbProgramUnit': 1.5, 'DbTrigger': 1.5, 'ApexProcess': 1.5,
    'ApexRegion': 1.2, 'PackageBody': 1.2, 'Activity': 1.0,
    'SharedResource': 1.0, 'DbType': 1.0, 'ApexLov': 1.0,
    'SqlStatement': 0.8, 'PlsqlBlock': 0.8, 'Adapter': 0.6,
    'DbSynonym': 0.5, 'ApexItem': 0.4, 'ApexButton': 0.4, 'ApexDaAction': 0.4,
    'DbSequence': 0.4, 'DbColumn': 0.3, 'File': 0.2, 'Element': 0.2,
    'Issue': 0.0, 'Recommendation': 0.0, 'CodeMetric': 0.0, 'Metric': 0.0,
    'Estate': 0.0,
}

# ─────────────────────────────────────────────────────────────
# Physical model
# ─────────────────────────────────────────────────────────────
INT_FIELDS: Set[str] = {
    'lineStart', 'lineEnd', 'loc', 'lineCount', 'unitCount', 'columnCount',
    'tableCount', 'bindCount', 'callCount', 'statementCount', 'argumentCount',
    'overload', 'columnId', 'dataLength', 'numRows', 'specLines', 'bodyLines',
    'sourceLine', 'fanIn', 'fanOut', 'commitCount', 'changeCount',
    'dynamicSqlSites', 'position', 'branchCount', 'loopCount', 'joinCount',
    'referenceCount', 'depth', 'order', 'activityCount', 'operationCount',
    'schemaRefCount', 'pageId', 'applicationId', 'nodeCount', 'relCount',
    'estateNodes', 'estateRelationships', 'writerEstates', 'linkCount',
}

# `value` is deliberately absent. It is a metric number on an Oracle
# `CodeMetric` and a configuration string on a TIBCO `GlobalVariable` -- one
# property name, two types, two dialects. A federated schema cannot type it,
# and typing it emits `value:float` for a string column, which fails the Neo4j
# import. The estate fixture carries a string-valued global variable so the
# AX-TYPES check catches anyone who adds it back.
FLOAT_FIELDS: Set[str] = {'complexity', 'complexityScore', 'confidence',
                          'coverage'}

BOOL_FIELDS: Set[str] = {
    'hasSelectStar', 'hasHint', 'hasDbLink', 'hasDynamicSql', 'hasCommit',
    'hasExceptionHandler', 'hasWhenOthersNull', 'isStandalone', 'isPk', 'isFk',
    'nullable', 'isPublic', 'ambiguous', 'inferred', 'isDeterministic',
    'hasNoWhere', 'isPipelined', 'hasPk', 'isDefault', 'isPublished',
    'declaredOnly', 'hasQuery', 'isDynamic', 'partitioned', 'isStarter',
    'merged', 'mapped',
}

COMPOSITE_CONSTRAINTS: List[Tuple[str, List[str]]] = [
    ('DbColumn', ['owner', 'tableName', 'name']),
]

SECONDARY_INDEXES: List[Tuple[str, List[str]]] = [
    ('Estate', ['name']),
    ('DbTable', ['owner']),
    ('DbPackage', ['owner']),
    ('DbProgramUnit', ['owner']),
    ('Activity', ['category']),
    ('Activity', ['estate']),
    ('BWProcess', ['module']),
    ('ApexPage', ['pageId']),
    ('Issue', ['ruleId']),
    ('Issue', ['severity']),
    ('Issue', ['estate']),
    ('File', ['filePath']),
]

FULLTEXT_INDEXES: List[Tuple[str, List[str], List[str]]] = [
    ('estate_code_ft', ['SqlStatement', 'PlsqlBlock'], ['text']),
    ('estate_name_ft', ['DbTable', 'DbView', 'DbPackage', 'DbProgramUnit',
                        'BWProcess', 'Activity', 'ApexPage'], ['name']),
]

# The union of what the three dialects each tolerate. Narrowing it here would
# report an estate's own accepted shape as a federation defect.
ORPHAN_TOLERANT_LABELS: Set[str] = {
    'DbIndex', 'DbConstraint', 'DbSequence', 'DbType', 'DbDatabaseLink',
    'DbSynonym', 'Repository', 'Branch', 'Commit', 'Developer', 'Directory',
    'CodeMetric', 'Metric', 'UnresolvedRef', 'Project', 'System',
    'GlobalVariable', 'DataTransformation', 'AESchema', 'ExternalReference',
    'ApexBuildOption', 'ApexWorkspace', 'ApexEmailTemplate', 'ApexPlugin',
    'ApexAuthentication', 'BusinessDomain',
}

# The namespaced id grammar admits every dialect's ids plus the estate prefix.
ID_PATTERN = re.compile(r'^[A-Za-z0-9_.:#$/@ -]+$')
