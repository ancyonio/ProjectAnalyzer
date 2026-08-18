"""Cypher cookbook.

The same questions the local engine answers in-memory, expressed as Cypher
for teams who load the graph into Neo4j. Emitted as a `.cypher` file so it is
copy-pasteable into Neo4j Browser, and surfaced by the `queries` CLI command.
"""
from __future__ import annotations

from typing import Dict, List

CYPHER_COOKBOOK: List[Dict[str, str]] = [
    {
        'id': 'node-counts',
        'title': 'Node counts by label (verification)',
        'purpose': 'Confirm the import populated every expected label.',
        'cypher': 'MATCH (n)\nRETURN labels(n)[0] AS NodeType, count(n) AS Count\nORDER BY Count DESC;',
    },
    {
        'id': 'rel-counts',
        'title': 'Relationship counts by type (verification)',
        'purpose': 'Confirm every semantic edge type is present.',
        'cypher': 'MATCH ()-[r]->()\nRETURN type(r) AS RelationshipType, count(r) AS Count\nORDER BY Count DESC;',
    },
    {
        'id': 'entry-points',
        'title': 'Entry point catalog',
        'purpose': 'Every externally reachable surface: HTTP, SOAP, JMS, file, timer.',
        'cypher': "MATCH (p:BWProcess)\nWHERE p.entryType IS NOT NULL AND p.entryType <> 'NONE'\nRETURN p.name AS Process, p.entryType AS EntryType, p.endpoint AS Endpoint,\n       p.module AS Module, p.complexityScore AS Complexity\nORDER BY p.entryType, p.complexityScore DESC;",
    },
    {
        'id': 'complexity-ranking',
        'title': 'Migration complexity ranking',
        'purpose': 'Order the migration backlog by measured complexity.',
        'cypher': 'MATCH (p:BWProcess)\nOPTIONAL MATCH (p)-[:EXECUTES]->(a:Activity)\nOPTIONAL MATCH (p)-[:USES_XSD]->(x:XSD)\nOPTIONAL MATCH (p)-[:HANDLES_ERROR]->(e:ErrorHandler)\nRETURN p.name AS Process, p.tier AS Tier, p.complexityScore AS Score,\n       count(DISTINCT a) AS Activities, count(DISTINCT x) AS Schemas,\n       count(DISTINCT e) AS ErrorHandlers\nORDER BY Score DESC;',
    },
    {
        'id': 'schema-blast-radius',
        'title': 'Blast radius of a schema change',
        'purpose': 'Which processes break if this XSD changes.',
        'cypher': "MATCH (x:XSD {name: $schemaName})<-[:USES_XSD|IMPORTS_SCHEMA*1..3]-(dependent)\nRETURN DISTINCT labels(dependent)[0] AS Type, dependent.name AS Name,\n       dependent.module AS Module, dependent.entryType AS EntryType\nORDER BY Type, Name;",
    },
    {
        'id': 'field-blast-radius',
        'title': 'Field-level blast radius',
        'purpose': 'Which processes touch a specific element.',
        'cypher': 'MATCH (e:Element {name: $fieldName})<-[:CONTAINS]-(x:XSD)<-[:USES_XSD]-(p:BWProcess)\nRETURN DISTINCT p.name AS Process, p.module AS Module, x.name AS Schema,\n       e.javaType AS JavaType, e.required AS Required;',
    },
    {
        'id': 'reachable-entry-points',
        'title': 'Entry points affected by a process change',
        'purpose': 'Walk callers upward to the externally reachable surfaces.',
        'cypher': "MATCH (target:BWProcess {name: $processName})\nMATCH path = (entry:BWProcess)-[:EXECUTES|CALLS*1..8]->(target)\nWHERE entry.entryType IS NOT NULL AND entry.entryType <> 'NONE'\nRETURN DISTINCT entry.name AS EntryPoint, entry.entryType AS Type,\n       entry.endpoint AS Endpoint, length(path) AS Hops\nORDER BY Hops;",
    },
    {
        'id': 'circular-dependencies',
        'title': 'Circular process dependencies (migration blockers)',
        'purpose': 'Cycles must be broken before incremental migration.',
        'cypher': 'MATCH path = (p:BWProcess)-[:EXECUTES|CALLS*2..10]->(p)\nRETURN DISTINCT [n IN nodes(path) WHERE n:BWProcess | n.name] AS Cycle\nLIMIT 50;',
    },
    {
        'id': 'orphan-schemas',
        'title': 'Orphan schemas (dead code)',
        'purpose': 'XSDs no process references - candidates to drop from scope.',
        'cypher': 'MATCH (x:XSD)\nWHERE NOT ()-[:USES_XSD|IMPORTS_SCHEMA]->(x)\nRETURN x.name AS OrphanSchema, x.folder AS Location, x.namespace AS Namespace\nORDER BY x.name;',
    },
    {
        'id': 'unreachable-processes',
        'title': 'Unreachable processes (dead code)',
        'purpose': 'No caller and no entry point - nothing can invoke them.',
        'cypher': "MATCH (p:BWProcess)\nWHERE NOT ()-[:CALLS]->(p)\n  AND (p.entryType IS NULL OR p.entryType = 'NONE')\nRETURN p.name AS DeadProcess, p.module AS Module, p.folder AS Location\nORDER BY p.module;",
    },
    {
        'id': 'shared-hotspots',
        'title': 'Most-reused artefacts (change hotspots)',
        'purpose': 'High in-degree = high blast radius. Migrate these carefully.',
        'cypher': 'MATCH (n)<-[r]-()\nWHERE n:XSD OR n:BWProcess OR n:SharedResource OR n:GlobalVariable\nRETURN labels(n)[0] AS Type, n.name AS Name, count(r) AS Dependents\nORDER BY Dependents DESC\nLIMIT 25;',
    },
    {
        'id': 'external-systems',
        'title': 'External system touchpoints',
        'purpose': 'Every outbound integration that needs a Spring client.',
        'cypher': 'MATCH (r:SharedResource)-[:CONNECTS_TO]->(s:System)\nOPTIONAL MATCH (p:BWProcess)-[:REFERENCES]->(r)\nRETURN s.name AS System, s.technology AS Technology, r.name AS Resource,\n       collect(DISTINCT p.name) AS UsedByProcesses;',
    },
    {
        'id': 'error-coverage',
        'title': 'Processes without error handling',
        'purpose': 'Fault-handling gaps to close during migration.',
        'cypher': 'MATCH (p:BWProcess)\nWHERE NOT (p)-[:HANDLES_ERROR]->() AND p.activityCount > 3\nRETURN p.name AS Process, p.module AS Module, p.activityCount AS Activities,\n       p.tier AS Tier\nORDER BY p.activityCount DESC;',
    },
    {
        'id': 'global-variable-usage',
        'title': 'Global variable usage (future application.yml)',
        'purpose': 'Configuration surface to externalise.',
        'cypher': 'MATCH (g:GlobalVariable)\nOPTIONAL MATCH (p:BWProcess)-[:CONFIGURED_BY]->(g)\nRETURN g.name AS Variable, g.value AS DefaultValue, g.module AS Module,\n       count(p) AS UsedBy\nORDER BY UsedBy DESC, g.name;',
    },
    {
        'id': 'activity-mix',
        'title': 'Activity mix by Spring target',
        'purpose': 'Sizing: how much of each Spring construct the migration needs.',
        'cypher': 'MATCH (a:Activity)\nRETURN a.category AS Category, a.springEquivalent AS SpringTarget, count(*) AS Count\nORDER BY Count DESC;',
    },
]


def render_cookbook() -> str:
    """Render the cookbook as a runnable, commented Cypher file."""
    out = [
        '// ================================================================',
        '// TIBCO Knowledge Graph - Analysis Query Cookbook',
        '// Parameterised queries use $params; set them in Neo4j Browser with',
        '//   :param schemaName => "Order.xsd"',
        '// ================================================================',
        '',
    ]
    for q in CYPHER_COOKBOOK:
        out += [f"// ---------------------------------------------------------------",
                f"// {q['title']}",
                f"// {q['purpose']}",
                f"// id: {q['id']}",
                '', q['cypher'], '']
    return '\n'.join(out)


def render_markdown() -> str:
    out = ['# Cypher Query Cookbook', '',
           'Run these in Neo4j Browser after importing `neo4j_import.cypher` '
           'or the CSV pair.', '']
    for q in CYPHER_COOKBOOK:
        out += [f"## {q['title']}", '', f"_{q['purpose']}_", '', '```cypher', q['cypher'], '```', '']
    return '\n'.join(out)
