"""Oracle language constants shared by every dialect that parses PL/SQL.

Only genuinely Oracle-wide facts live here. Dialect-specific sets -- the APEX
runtime packages, a site's deprecated API list -- are passed into the analysers
as arguments so this module never has to know which analyzer is calling.
"""
from __future__ import annotations

import re
from typing import Set

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

BIND_RE = re.compile(r':([A-Za-z][A-Za-z0-9_$#]*)')
SUBSTITUTION_RE = re.compile(r'&([A-Za-z][A-Za-z0-9_$#]*)\.')
