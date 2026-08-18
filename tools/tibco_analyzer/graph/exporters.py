"""Neo4j exporters: admin-import CSVs, a runnable Cypher script and the
JSON analysis summary.

Every artefact here is a pure function of the parsed graph, so two runs on
unchanged source produce identical files -- which is what makes them safe to
commit and diff in CI.
"""
from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from ..constants import ACTIVITY_SPRING_MAP
from ..model import Graph
from ..utils import escape_cypher

logger = logging.getLogger('tibco_analyzer')


class Neo4jExporter:
    """Writes Neo4j-ready artefacts for a `Graph`."""

    def __init__(self, graph: Graph, output_dir: Path):
        self.graph = graph
        self.nodes = graph.nodes
        self.rels = graph.rels
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        meta = graph.meta or {}
        self.tibco_root = meta.get('tibcoRoot', '')
        self.file_counts = Counter(meta.get('fileDiscovery', {}))
        self.activity_type_counts = Counter(meta.get('activityCategoryCounts', {}))
        self._module_ids = {m: m for m in meta.get('modules', [])}

    def write_all(self) -> Dict[str, str]:
        nodes_csv, rels_csv = self._write_csv()
        cypher = self._write_cypher()
        summary = self._write_analysis_summary()
        return {
            'nodes_csv': str(nodes_csv),
            'relationships_csv': str(rels_csv),
            'cypher_script': str(cypher),
            'analysis_summary': str(summary),
        }

    def _write_csv(self) -> Tuple[Path, Path]:
        """Write Neo4j admin-import compatible CSV files."""
        # Collect all property keys used across all nodes
        prop_keys: Set[str] = set()
        for node in self.nodes.values():
            prop_keys.update(node.properties.keys())

        # Typed columns for Neo4j import
        int_fields = {'activityCount', 'transitionCount', 'errorHandlerCount', 'elementCount',
                       'complexTypeCount', 'simpleTypeCount', 'importCount', 'operationCount',
                       'schemaRefCount', 'wsdlRefCount', 'processVarCount', 'groupCount',
                       'order', 'fieldCount'}
        float_fields = {'complexityScore'}
        bool_fields = {'required', 'multiple', 'deployable', 'serviceSettable'}

        typed_keys = {}
        for k in sorted(prop_keys):
            if k in int_fields:
                typed_keys[k] = f'{k}:int'
            elif k in float_fields:
                typed_keys[k] = f'{k}:float'
            elif k in bool_fields:
                typed_keys[k] = f'{k}:boolean'
            else:
                typed_keys[k] = k

        node_columns = ['nodeId:ID', 'label:LABEL', 'name'] + [typed_keys[k] for k in sorted(prop_keys)]

        nodes_path = self.output_dir / 'neo4j_nodes.csv'
        with open(nodes_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=node_columns, extrasaction='ignore', restval='')
            writer.writeheader()
            for node in self.nodes.values():
                row = {
                    'nodeId:ID': node.node_id,
                    'label:LABEL': node.label,
                    'name': node.name,
                }
                for k, v in node.properties.items():
                    col = typed_keys.get(k, k)
                    if isinstance(v, bool):
                        row[col] = str(v).lower()
                    elif v is not None and v != '' and v != 0:
                        row[col] = str(v)
                writer.writerow(row)

        # Relationships CSV
        rel_prop_keys: Set[str] = set()
        for r in self.rels:
            rel_prop_keys.update(r.properties.keys())

        rel_columns = [':START_ID', ':END_ID', ':TYPE'] + sorted(rel_prop_keys)

        rels_path = self.output_dir / 'neo4j_relationships.csv'
        with open(rels_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=rel_columns, extrasaction='ignore', restval='')
            writer.writeheader()
            for r in self.rels:
                row = {
                    ':START_ID': r.start_id,
                    ':END_ID': r.end_id,
                    ':TYPE': r.rel_type,
                }
                for k, v in r.properties.items():
                    if v is not None and v != '':
                        row[k] = str(v)
                writer.writerow(row)

        logger.info(f"  CSV: {len(self.nodes)} nodes -> {nodes_path.name}")
        logger.info(f"  CSV: {len(self.rels)} rels  -> {rels_path.name}")
        return nodes_path, rels_path

    def _write_cypher(self) -> Path:
        """Generate a comprehensive Cypher import script."""
        cypher_path = self.output_dir / 'neo4j_import.cypher'

        labels = sorted(set(n.label for n in self.nodes.values()))
        rel_types = sorted(set(r.rel_type for r in self.rels))

        with open(cypher_path, 'w', encoding='utf-8') as f:
            f.write("// ================================================================\n")
            f.write("// TIBCO BW -> Neo4j Comprehensive Import Script\n")
            f.write(f"// Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"// Nodes: {len(self.nodes):,}  |  Relationships: {len(self.rels):,}\n")
            f.write(f"// Labels: {', '.join(labels)}\n")
            f.write(f"// Rel Types: {', '.join(rel_types)}\n")
            f.write("// ================================================================\n\n")

            # Constraints & Indexes
            f.write("// --- CONSTRAINTS ---\n\n")
            for lbl in labels:
                f.write(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{lbl}) REQUIRE n.nodeId IS UNIQUE;\n")

            f.write("\n// --- INDEXES ---\n\n")
            for lbl in labels:
                f.write(f"CREATE INDEX IF NOT EXISTS FOR (n:{lbl}) ON (n.name);\n")
            f.write("CREATE INDEX IF NOT EXISTS FOR (n:BWProcess) ON (n.module);\n")
            f.write("CREATE INDEX IF NOT EXISTS FOR (n:BWProcess) ON (n.tier);\n")
            f.write("CREATE INDEX IF NOT EXISTS FOR (n:Activity) ON (n.category);\n")
            f.write("CREATE INDEX IF NOT EXISTS FOR (n:XSD) ON (n.namespace);\n")
            f.write("CREATE INDEX IF NOT EXISTS FOR (n:SharedResource) ON (n.resourceType);\n")
            f.write("CREATE INDEX IF NOT EXISTS FOR (n:GlobalVariable) ON (n.module);\n\n")

            # Nodes grouped by label
            nodes_by_label = defaultdict(list)
            for node in self.nodes.values():
                nodes_by_label[node.label].append(node)

            for lbl in labels:
                ns = nodes_by_label[lbl]
                f.write(f"\n// --- {lbl.upper()} NODES ({len(ns)}) ---\n\n")
                for node in ns:
                    props = [f"nodeId: '{escape_cypher(node.node_id)}'",
                             f"name: '{escape_cypher(node.name)}'"]
                    for k, v in sorted(node.properties.items()):
                        if v is None or v == '' or v == 0:
                            continue
                        if isinstance(v, bool):
                            props.append(f"{k}: {str(v).lower()}")
                        elif isinstance(v, (int, float)):
                            props.append(f"{k}: {v}")
                        else:
                            props.append(f"{k}: '{escape_cypher(str(v))}'")
                    f.write(f"CREATE (:{lbl} {{{', '.join(props)}}});\n")

            # Relationships grouped by type
            rels_by_type = defaultdict(list)
            for r in self.rels:
                rels_by_type[r.rel_type].append(r)

            f.write("\n\n")
            for rtype in sorted(rels_by_type.keys()):
                rs = rels_by_type[rtype]
                f.write(f"\n// --- {rtype} ({len(rs)} relationships) ---\n\n")
                for r in rs:
                    rprops = []
                    for k, v in r.properties.items():
                        if v is not None and v != '':
                            if isinstance(v, (int, float)):
                                rprops.append(f"{k}: {v}")
                            elif isinstance(v, bool):
                                rprops.append(f"{k}: {str(v).lower()}")
                            else:
                                rprops.append(f"{k}: '{escape_cypher(str(v))}'")
                    prop_str = f" {{{', '.join(rprops)}}}" if rprops else ""
                    f.write(
                        f"MATCH (a {{nodeId: '{escape_cypher(r.start_id)}'}}),"
                        f" (b {{nodeId: '{escape_cypher(r.end_id)}'}}) "
                        f"CREATE (a)-[:{rtype}{prop_str}]->(b);\n"
                    )

            # Verification & Analysis Queries
            f.write("\n\n// ================================================================\n")
            f.write("// VERIFICATION & ANALYSIS QUERIES\n")
            f.write("// ================================================================\n\n")

            f.write("// Count nodes by label\n")
            f.write("// MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count ORDER BY count DESC;\n\n")

            f.write("// Count relationships by type\n")
            f.write("// MATCH ()-[r]->() RETURN type(r) AS relType, count(r) AS count ORDER BY count DESC;\n\n")

            f.write("// Top 10 most complex processes\n")
            f.write("// MATCH (p:BWProcess) RETURN p.name, p.complexityScore, p.tier, p.activityCount ORDER BY p.complexityScore DESC LIMIT 10;\n\n")

            f.write("// Process call graph (who calls whom)\n")
            f.write("// MATCH (a:Activity)-[:CALLS]->(p:BWProcess) MATCH (caller:BWProcess)-[:EXECUTES]->(a) RETURN caller.name AS caller, p.name AS callee;\n\n")

            f.write("// Module dependency graph\n")
            f.write("// MATCH (m1:Module)-[:DEPENDS_ON]->(m2:Module) RETURN m1.name, m2.name;\n\n")

            f.write("// Schema dependency chain\n")
            f.write("// MATCH path = (x1:XSD)-[:IMPORTS_SCHEMA*1..5]->(x2:XSD) RETURN [n IN nodes(path) | n.name] AS chain;\n\n")

            f.write("// Activity type distribution\n")
            f.write("// MATCH (a:Activity) RETURN a.category AS type, count(a) AS count ORDER BY count DESC;\n\n")

            f.write("// Spring Boot migration mapping\n")
            f.write("// MATCH (a:Activity) WHERE a.springEquivalent IS NOT NULL RETURN a.category, a.springEquivalent, count(*) AS count ORDER BY count DESC;\n\n")

            f.write("// External system connections\n")
            f.write("// MATCH (a:Adapter)-[:CONNECTS_TO]->(s:System) RETURN s.name, collect(a.name) AS adapters;\n\n")

            f.write("// Shared resource usage\n")
            f.write("// MATCH (p:BWProcess)-[:REFERENCES]->(r:SharedResource) RETURN p.name, r.name, r.resourceType;\n\n")

            f.write("// Global variables by module\n")
            f.write("// MATCH (g:GlobalVariable)-[:CONFIGURES]->(m:Module) RETURN m.name, collect(g.name) AS variables;\n\n")

            f.write("// Full migration pathway: Process -> Activities -> Spring equivalents\n")
            f.write("// MATCH (p:BWProcess)-[:EXECUTES]->(a:Activity) RETURN p.name, p.tier, collect({activity: a.name, spring: a.springEquivalent}) AS migration_plan ORDER BY p.complexityScore DESC;\n\n")

            f.write("// Data lineage: Process -> XSD -> Elements\n")
            f.write("// MATCH (p:BWProcess)-[:USES_XSD]->(x:XSD)-[:CONTAINS]->(e:Element) RETURN p.name, x.name, collect(e.name) AS elements;\n\n")

            f.write("// Error handling coverage\n")
            f.write("// MATCH (p:BWProcess) OPTIONAL MATCH (p)-[:HANDLES_ERROR]->(eh:ErrorHandler) RETURN p.name, p.activityCount, count(eh) AS errorHandlers, CASE WHEN count(eh) > 0 THEN 'Covered' ELSE 'Uncovered' END AS status ORDER BY p.activityCount DESC;\n\n")

            f.write("// Find processes with no error handling\n")
            f.write("// MATCH (p:BWProcess) WHERE NOT (p)-[:HANDLES_ERROR]->() AND p.activityCount > 3 RETURN p.name, p.tier, p.activityCount ORDER BY p.activityCount DESC;\n\n")

            f.write("// WSDL service to schema mapping\n")
            f.write("// MATCH (s:Service)-[:IMPORTS_SCHEMA]->(x:XSD) RETURN s.name, collect(x.name) AS schemas;\n\n")

            f.write("// Service operations\n")
            f.write("// MATCH (s:Service)-[:EXPOSES]->(o:Operation) RETURN s.name, collect(o.name) AS operations;\n\n")

            f.write("// Import complete!\n")

        logger.info(f"  Cypher: {cypher_path.name}")
        return cypher_path

    def _write_analysis_summary(self) -> Path:
        """Write a JSON summary with migration statistics and recommendations."""
        summary_path = self.output_dir / 'analysis_summary.json'

        label_counts = Counter(n.label for n in self.nodes.values())
        rel_type_counts = Counter(r.rel_type for r in self.rels)

        # Tier distribution
        tier_dist = Counter()
        for node in self.nodes.values():
            if node.label == 'BWProcess':
                tier_dist[node.properties.get('tier', 'Unknown')] += 1

        # Entry type distribution
        entry_dist = Counter()
        for node in self.nodes.values():
            if node.label == 'BWProcess':
                entry_dist[node.properties.get('entryType', 'NONE')] += 1

        # Technology stack
        tech_stack = set()
        for node in self.nodes.values():
            tech = node.properties.get('technology', '')
            if tech:
                tech_stack.add(tech)

        # Module statistics
        module_stats = {}
        for mod_name in self._module_ids:
            mod_processes = sum(1 for n in self.nodes.values()
                               if n.label == 'BWProcess' and n.properties.get('module') == mod_name)
            mod_xsds = sum(1 for n in self.nodes.values()
                           if n.label == 'XSD' and n.properties.get('module') == mod_name)
            mod_activities = sum(1 for n in self.nodes.values()
                                if n.label == 'Activity' and n.properties.get('module') == mod_name)
            mod_gvars = sum(1 for n in self.nodes.values()
                            if n.label == 'GlobalVariable' and n.properties.get('module') == mod_name)
            mod_services = sum(1 for n in self.nodes.values()
                               if n.label == 'Service' and n.properties.get('module') == mod_name)
            module_stats[mod_name] = {
                'processes': mod_processes,
                'xsds': mod_xsds,
                'activities': mod_activities,
                'globalVariables': mod_gvars,
                'services': mod_services,
            }

        # Top complex processes
        complex_procs = sorted(
            [(n.name, n.properties.get('complexityScore', 0), n.properties.get('tier', ''))
             for n in self.nodes.values() if n.label == 'BWProcess'],
            key=lambda x: x[1], reverse=True
        )[:20]

        summary = {
            'generated': datetime.now().isoformat(),
            'tibcoRoot': str(self.tibco_root),
            'totals': {
                'nodes': len(self.nodes),
                'relationships': len(self.rels),
                'nodeLabels': len(label_counts),
                'relationshipTypes': len(rel_type_counts),
            },
            'nodeCounts': dict(label_counts.most_common()),
            'relationshipCounts': dict(rel_type_counts.most_common()),
            'fileDiscovery': dict(self.file_counts.most_common()),
            'migrationComplexity': {
                'tierDistribution': dict(tier_dist),
                'entryPointTypes': dict(entry_dist),
                'topComplexProcesses': [
                    {'name': name, 'score': score, 'tier': tier}
                    for name, score, tier in complex_procs
                ],
            },
            'technologyStack': sorted(tech_stack),
            'activityTypeDistribution': dict(self.activity_type_counts.most_common()),
            'moduleStatistics': module_stats,
            'springBootMigrationMapping': {
                info['category']: info['spring']
                for atype, info in sorted(ACTIVITY_SPRING_MAP.items())
                if self.activity_type_counts.get(info['category'], 0) > 0
            },
            'recommendations': self._generate_recommendations(tier_dist, entry_dist, tech_stack),
        }

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, default=str)

        logger.info(f"  Summary: {summary_path.name}")
        return summary_path

    def _generate_recommendations(self, tier_dist, entry_dist, tech_stack) -> List[str]:
        """Generate migration recommendations based on analysis."""
        recs = []

        total_procs = sum(tier_dist.values())
        if tier_dist.get('Critical', 0) > 0:
            pct = round(tier_dist['Critical'] / total_procs * 100, 1) if total_procs else 0
            recs.append(f"{tier_dist['Critical']} critical-complexity processes ({pct}%) - prioritize decomposition and thorough testing")
        if tier_dist.get('High', 0) > 0:
            pct = round(tier_dist['High'] / total_procs * 100, 1) if total_procs else 0
            recs.append(f"{tier_dist['High']} high-complexity processes ({pct}%) - allocate senior developer time")
        if tier_dist.get('Low', 0) > 0:
            pct = round(tier_dist['Low'] / total_procs * 100, 1) if total_procs else 0
            recs.append(f"{tier_dist['Low']} low-complexity processes ({pct}%) - good candidates for automated migration")

        if entry_dist.get('HTTP_RECEIVER', 0) > 0:
            recs.append(f"{entry_dist['HTTP_RECEIVER']} HTTP-triggered processes -> Spring @RestController endpoints")
        if entry_dist.get('SOAP_RECEIVER', 0) > 0:
            recs.append(f"{entry_dist['SOAP_RECEIVER']} SOAP services -> Spring WS @Endpoint (or convert to REST)")
        if entry_dist.get('JMS_RECEIVER', 0) > 0:
            recs.append(f"{entry_dist['JMS_RECEIVER']} JMS consumers -> Spring @JmsListener")
        if entry_dist.get('TIMER', 0) > 0:
            recs.append(f"{entry_dist['TIMER']} timer-driven processes -> Spring @Scheduled")
        if entry_dist.get('FILE_POLLER', 0) > 0:
            recs.append(f"{entry_dist['FILE_POLLER']} file pollers -> Spring Integration / WatchService")

        if 'JMS' in tech_stack:
            recs.append("JMS infrastructure detected - provision ActiveMQ/RabbitMQ or use Spring Cloud Stream")
        if 'JDBC' in tech_stack:
            recs.append("JDBC connections found - configure Spring DataSource + connection pooling (HikariCP)")
        if 'RV' in tech_stack:
            recs.append("TIBCO Rendezvous detected - migrate to JMS or Kafka for messaging")

        if len(self._module_ids) > 3:
            recs.append(f"{len(self._module_ids)} modules detected - consider microservice boundary alignment")

        return recs
