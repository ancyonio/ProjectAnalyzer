"""CLI plumbing shared by the analyzers: logging, graph loading, file writing."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .model import Graph

GRAPH_FILE = 'graph.json'


def setup_logging(verbose: bool, logger_name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%H:%M:%S',
    )
    return logging.getLogger(logger_name)


def load_graph(output_dir: Path, hint: str = 'analyze') -> Graph:
    path = Path(output_dir) / GRAPH_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Graph not found at {path}. Run `{hint}` first.")
    return Graph.load(path)


def write(path: Path, content: str, logger: Optional[logging.Logger] = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    if logger:
        logger.info("Wrote %s", path)
    return path


def print_stats(graph: Graph, title: str, output_dir: Path, files: dict) -> None:
    stats = graph.stats()
    print('\n' + '=' * 66)
    print(f'  {title}')
    print('=' * 66)
    print(f"\n  Nodes         : {stats['totalNodes']:,}")
    print(f"  Relationships : {stats['totalRelationships']:,}")
    print('\n  NODE COUNTS:')
    for label, count in stats['nodeCounts'].items():
        print(f"   {label:24} : {count:6,}")
    print('\n  RELATIONSHIP COUNTS:')
    for rtype, count in stats['relationshipCounts'].items():
        print(f"   {rtype:24} : {count:6,}")
    print('\n  OUTPUT:')
    print(f"   {'graph.json':24} : {Path(output_dir) / GRAPH_FILE}")
    for name, path in files.items():
        print(f"   {name:24} : {path}")
