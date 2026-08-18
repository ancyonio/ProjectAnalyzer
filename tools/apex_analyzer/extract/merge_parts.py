#!/usr/bin/env python3
"""Merge the spooled extraction parts into one JSON object.

Each script in this kit emits one JSON object; SQLcl spools them one after
another. This joins them into the single object the analyzer expects.

    python merge_parts.py db_meta_parts.json db_meta.json
    python merge_parts.py apex_meta_parts.json apex_meta.json

Standard library only, so it runs wherever the extract was taken.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator


def iter_objects(text: str) -> Iterator[Dict[str, Any]]:
    """Yield every top-level JSON object in a spool file."""
    decoder = json.JSONDecoder()
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index] not in '{[':
            index += 1
        if index >= length:
            return
        try:
            value, end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(value, dict):
            yield value
        index = end


def merge(source: Path, target: Path) -> int:
    text = source.read_text(encoding='utf-8', errors='replace')
    merged: Dict[str, Any] = {}
    sections = 0
    for payload in iter_objects(text):
        for key, value in payload.items():
            if value is None:
                continue
            if key in merged and isinstance(merged[key], list) and isinstance(value, list):
                merged[key].extend(value)
            else:
                merged[key] = value
            sections += 1
    target.write_text(json.dumps(merged, indent=2), encoding='utf-8')
    print(f'{target}: {sections} section(s), '
          f'{sum(len(v) for v in merged.values() if isinstance(v, list))} row(s)')
    return 0 if merged else 1


def main(argv=None) -> int:
    argv = list(argv or sys.argv[1:])
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 1
    source, target = Path(argv[0]), Path(argv[1])
    if not source.is_file():
        print(f'ERROR: {source} not found', file=sys.stderr)
        return 1
    return merge(source, target)


if __name__ == '__main__':
    sys.exit(main())
