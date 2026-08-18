"""APEX export call tokenizer.

An APEX export is a PL/SQL script made of calls to the import API:

    wwv_flow_imp_page.create_page_plug(
     p_id=>wwv_flow_imp.id(1001)
    ,p_flow_step_id=>10
    ,p_plug_name=>'Order Header'
    ,p_plug_source=>'select * from orders where id = :P10_ORDER_ID'
    );

This module turns that text into `ExportCall` objects with parsed arguments.
It has to cope with four things a naive regex gets wrong:

* strings containing parentheses, commas and `=>`;
* doubled quotes (`'it''s'`) and alternative quoting (`q'~ … ~'`);
* long text split into `wwv_flow_string.join(wwv_flow_t_varchar2('a','b'))`;
* `wwv_flow_imp.id(12345)` component references, which are the ids every
  relationship between components is built from.

The approach is a masking scan: string literals and comments are blanked out
(preserving offsets) so that bracket matching, comma splitting and procedure
detection only ever see real code, while values are still read from the
original text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

# `q'<delimiter> … <closing delimiter>'`
_Q_PAIRS = {'[': ']', '(': ')', '{': '}', '<': '>'}

_CALL_RE = re.compile(
    r'\b(?P<pkg>wwv_flow[a-z0-9_]*)\s*\.\s*(?P<proc>[a-z][a-z0-9_]*)\s*\(',
    re.IGNORECASE)

_ID_CALL_RE = re.compile(r'^wwv_flow[a-z0-9_]*\.id\s*\(\s*(-?\d+)\s*\)$', re.IGNORECASE)
_JOIN_RE = re.compile(r'wwv_flow_string\.join\s*\(', re.IGNORECASE)
_UNISTR_RE = re.compile(r'^unistr\s*\((.*)\)$', re.IGNORECASE | re.DOTALL)
_NUMBER_RE = re.compile(r'^-?\d+(\.\d+)?$')
_ARG_SPLIT_RE = re.compile(r'^\s*(p_[a-z0-9_]+)\s*=>\s*(.*)$', re.IGNORECASE | re.DOTALL)


# ──────────────────────────────────────────────────────────────
# Masking scan
# ──────────────────────────────────────────────────────────────
def mask_literals(text: str) -> str:
    """Return `text` with string literals and comments replaced by spaces.

    Offsets are preserved, so any index found in the mask is valid in the
    original text. Newlines are kept so line numbers stay correct.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        # line comment
        if ch == '-' and i + 1 < n and text[i + 1] == '-':
            while i < n and text[i] != '\n':
                out[i] = ' '
                i += 1
            continue
        # block comment
        if ch == '/' and i + 1 < n and text[i + 1] == '*':
            end = text.find('*/', i + 2)
            end = n if end == -1 else end + 2
            for j in range(i, end):
                if text[j] != '\n':
                    out[j] = ' '
            i = end
            continue
        # alternative quoting: q'~ … ~'
        if ch in 'qQ' and i + 2 < n and text[i + 1] == "'":
            delim = text[i + 2]
            closing = _Q_PAIRS.get(delim, delim)
            end = text.find(closing + "'", i + 3)
            end = n if end == -1 else end + 2
            for j in range(i, end):
                if text[j] != '\n':
                    out[j] = ' '
            i = end
            continue
        # ordinary string literal, '' escapes doubled quotes
        if ch == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            for k in range(i, min(j, n)):
                if text[k] != '\n':
                    out[k] = ' '
            i = j
            continue
        i += 1
    return ''.join(out)


def _match_paren(masked: str, open_index: int) -> int:
    """Index just past the `)` that closes the `(` at `open_index`."""
    depth = 0
    for i in range(open_index, len(masked)):
        ch = masked[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    return len(masked)


def split_top_level(text: str, masked: str, separator: str = ',') -> List[Tuple[int, int]]:
    """Spans of `text` separated by `separator` at bracket depth zero."""
    spans: List[Tuple[int, int]] = []
    depth, start = 0, 0
    for i, ch in enumerate(masked):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == separator and depth == 0:
            spans.append((start, i))
            start = i + 1
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


# ──────────────────────────────────────────────────────────────
# Value parsing
# ──────────────────────────────────────────────────────────────
def read_string_literal(text: str, start: int) -> Tuple[str, int]:
    """Read the literal beginning at `start`; returns (value, next index)."""
    n = len(text)
    if text[start] in 'qQ' and start + 2 < n and text[start + 1] == "'":
        delim = text[start + 2]
        closing = _Q_PAIRS.get(delim, delim)
        end = text.find(closing + "'", start + 3)
        if end == -1:
            return text[start + 3:], n
        return text[start + 3:end], end + 2
    if text[start] != "'":
        return '', start
    buf: List[str] = []
    i = start + 1
    while i < n:
        if text[i] == "'":
            if i + 1 < n and text[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            return ''.join(buf), i + 1
        buf.append(text[i])
        i += 1
    return ''.join(buf), n


def parse_value(raw: str) -> Any:
    """Turn one argument's source text into a Python value."""
    value = raw.strip()
    if not value:
        return ''
    lowered = value.lower()
    if lowered == 'null':
        return None
    if lowered in ('true', 'false'):
        return lowered == 'true'
    if _NUMBER_RE.match(value):
        return float(value) if '.' in value else int(value)

    id_call = _ID_CALL_RE.match(value)
    if id_call:
        return int(id_call.group(1))

    unistr = _UNISTR_RE.match(value)
    if unistr:
        return parse_value(unistr.group(1))

    if _JOIN_RE.match(value):
        return _join_varchar2_table(value)

    if value[0] in ("'", 'q', 'Q'):
        parts: List[str] = []
        masked = mask_literals(value)
        i = 0
        while i < len(value):
            ch = value[i]
            if ch == "'" or (ch in 'qQ' and i + 1 < len(value) and value[i + 1] == "'"):
                text_part, i = read_string_literal(value, i)
                parts.append(text_part)
                continue
            # only concatenation operators may sit between literals
            if masked[i:i + 2] == '||':
                i += 2
                continue
            if ch.isspace():
                i += 1
                continue
            break
        if parts:
            return ''.join(parts)
    return value


def _join_varchar2_table(value: str) -> str:
    """`wwv_flow_string.join(wwv_flow_t_varchar2('a','b'))` -> 'ab'."""
    masked = mask_literals(value)
    open_index = masked.find('(')
    if open_index == -1:
        return value
    inner_start = masked.find('(', open_index + 1)
    if inner_start == -1:
        return value
    inner_end = _match_paren(masked, inner_start)
    body = value[inner_start + 1:inner_end - 1]
    body_masked = masked[inner_start + 1:inner_end - 1]
    parts: List[str] = []
    for start, end in split_top_level(body, body_masked):
        piece = parse_value(body[start:end])
        if piece is not None:
            parts.append(str(piece))
    return ''.join(parts)


def normalise_arg_name(name: str) -> str:
    """`p_plug_source` -> `plugSource`, `p_attribute_01` -> `attribute01`."""
    base = name[2:] if name.lower().startswith('p_') else name
    chunks = [c for c in base.lower().split('_') if c]
    if not chunks:
        return base.lower()
    out = chunks[0]
    for chunk in chunks[1:]:
        out += chunk if chunk.isdigit() else chunk.capitalize()
    return out


# ──────────────────────────────────────────────────────────────
@dataclass
class ExportCall:
    """One `wwv_flow_*.<procedure>(...)` call from an export file."""
    package: str
    procedure: str
    args: Dict[str, Any] = field(default_factory=dict)
    line: int = 0
    source_file: str = ''

    def get(self, name: str, default: Any = None) -> Any:
        value = self.args.get(name, default)
        return default if value is None else value

    def text(self, name: str, default: str = '') -> str:
        value = self.args.get(name)
        return default if value in (None, '') else str(value)

    def number(self, name: str, default: Optional[int] = None) -> Optional[int]:
        value = self.args.get(name)
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and _NUMBER_RE.match(value.strip()):
            return int(float(value))
        return default

    def flag(self, name: str, true_values=('Y', 'YES', 'TRUE', 'ON')) -> bool:
        value = self.args.get(name)
        if isinstance(value, bool):
            return value
        return str(value or '').strip().upper() in true_values

    def attribute(self, index: int) -> str:
        return self.text(f'attribute{index:02d}')

    def attributes(self, first: int = 1, last: int = 25) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for i in range(first, last + 1):
            value = self.text(f'attribute{i:02d}')
            if value:
                out[f'attribute{i:02d}'] = value
        return out


def iter_calls(text: str, source_file: str = '') -> Iterator[ExportCall]:
    """Yield every export API call in `text`, in file order."""
    masked = mask_literals(text)
    newline_positions = [i for i, ch in enumerate(text) if ch == '\n']

    def line_of(index: int) -> int:
        low, high = 0, len(newline_positions)
        while low < high:
            mid = (low + high) // 2
            if newline_positions[mid] < index:
                low = mid + 1
            else:
                high = mid
        return low + 1

    cursor = 0
    for match in _CALL_RE.finditer(masked):
        procedure = match.group('proc').lower()
        if procedure == 'id':                       # component id reference
            continue
        if match.start() < cursor:
            continue    # nested helper call inside an argument (join, id, …)
        open_index = match.end() - 1
        close_index = _match_paren(masked, open_index)
        cursor = close_index
        body = text[open_index + 1:close_index - 1]
        body_masked = masked[open_index + 1:close_index - 1]

        args: Dict[str, Any] = {}
        for start, end in split_top_level(body, body_masked):
            piece = body[start:end]
            arg_match = _ARG_SPLIT_RE.match(piece)
            if not arg_match:
                continue
            args[normalise_arg_name(arg_match.group(1))] = parse_value(arg_match.group(2))

        yield ExportCall(package=match.group('pkg').lower(), procedure=procedure,
                         args=args, line=line_of(match.start()),
                         source_file=source_file)
