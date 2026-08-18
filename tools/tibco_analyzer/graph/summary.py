"""The TIBCO migration summary.

`analysis_summary.json` is the one export that is not a pure Neo4j artefact:
it is the migration-facing read of the graph -- tier distribution, entry-point
mix, technology stack, per-module size and the Spring targets each activity
category maps to. It lived inside the old exporter fork; it moved here
unchanged when the CSV and Cypher export moved to `analyzer_core.graph`.

Like every other artefact, it is a pure function of the graph, so two runs on
unchanged source produce identical output.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List

from ..constants import ACTIVITY_SPRING_MAP
from ..model import Graph

logger = logging.getLogger('tibco_analyzer')


def write_analysis_summary(graph: Graph, output_dir: Path) -> Path:
    """Write a JSON summary with migration statistics and recommendations."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / 'analysis_summary.json'

    meta = graph.meta or {}
    nodes, rels = graph.nodes, graph.rels
    tibco_root = meta.get('tibcoRoot', '')
    file_counts = Counter(meta.get('fileDiscovery', {}))
    activity_type_counts = Counter(meta.get('activityCategoryCounts', {}))
    modules = list(meta.get('modules', []))

    label_counts = Counter(n.label for n in nodes.values())
    rel_type_counts = Counter(r.rel_type for r in rels)

    # Tier distribution
    tier_dist = Counter()
    for node in nodes.values():
        if node.label == 'BWProcess':
            tier_dist[node.properties.get('tier', 'Unknown')] += 1

    # Entry type distribution
    entry_dist = Counter()
    for node in nodes.values():
        if node.label == 'BWProcess':
            entry_dist[node.properties.get('entryType', 'NONE')] += 1

    # Technology stack
    tech_stack = set()
    for node in nodes.values():
        tech = node.properties.get('technology', '')
        if tech:
            tech_stack.add(tech)

    # Module statistics
    module_stats = {}
    for mod_name in modules:
        mod_processes = sum(1 for n in nodes.values()
                           if n.label == 'BWProcess' and n.properties.get('module') == mod_name)
        mod_xsds = sum(1 for n in nodes.values()
                       if n.label == 'XSD' and n.properties.get('module') == mod_name)
        mod_activities = sum(1 for n in nodes.values()
                            if n.label == 'Activity' and n.properties.get('module') == mod_name)
        mod_gvars = sum(1 for n in nodes.values()
                        if n.label == 'GlobalVariable' and n.properties.get('module') == mod_name)
        mod_services = sum(1 for n in nodes.values()
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
         for n in nodes.values() if n.label == 'BWProcess'],
        key=lambda x: x[1], reverse=True
    )[:20]

    summary = {
        'generated': datetime.now().isoformat(),
        'tibcoRoot': str(tibco_root),
        'totals': {
            'nodes': len(nodes),
            'relationships': len(rels),
            'nodeLabels': len(label_counts),
            'relationshipTypes': len(rel_type_counts),
        },
        'nodeCounts': dict(label_counts.most_common()),
        'relationshipCounts': dict(rel_type_counts.most_common()),
        'fileDiscovery': dict(file_counts.most_common()),
        'migrationComplexity': {
            'tierDistribution': dict(tier_dist),
            'entryPointTypes': dict(entry_dist),
            'topComplexProcesses': [
                {'name': name, 'score': score, 'tier': tier}
                for name, score, tier in complex_procs
            ],
        },
        'technologyStack': sorted(tech_stack),
        'activityTypeDistribution': dict(activity_type_counts.most_common()),
        'moduleStatistics': module_stats,
        'springBootMigrationMapping': {
            info['category']: info['spring']
            for atype, info in sorted(ACTIVITY_SPRING_MAP.items())
            if activity_type_counts.get(info['category'], 0) > 0
        },
        'recommendations': _recommendations(tier_dist, entry_dist, tech_stack, modules),
    }

    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"  Summary: {summary_path.name}")
    return summary_path


def _recommendations(tier_dist, entry_dist, tech_stack, modules) -> List[str]:
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

    if len(modules) > 3:
        recs.append(f"{len(modules)} modules detected - consider microservice boundary alignment")

    return recs
