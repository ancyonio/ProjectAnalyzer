"""Small Markdown formatting helpers shared by generated reports."""
from __future__ import annotations

from typing import Any, List


def table_lines(headers: List[str], rows: List[List[Any]]) -> List[str]:
    lines = ['| ' + ' | '.join(headers) + ' |',
             '|' + '|'.join(['---'] * len(headers)) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join('' if cell is None else str(cell) for cell in row) + ' |')
    return lines