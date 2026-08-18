"""APEX URL parsing.

Branch targets, button redirects and list entries all carry a target as
either a classic `f?p=` URL, a friendly URL, or a bare page number. All three
forms have to resolve to a page id or the navigation graph has holes.

    f?p=&APP_ID.:20:&SESSION.::&DEBUG.:RP:P20_ID:&P10_ID.   -> 20
    f?p=100:30:&SESSION.                                     -> 30
    &APP_ID.:15                                              -> 15
    20                                                       -> 20
"""
from __future__ import annotations

import re
from typing import List, Optional

_FP_RE = re.compile(r'f\?p=([^"\'\s]+)', re.IGNORECASE)
_NUMBER_RE = re.compile(r'^\d+$')
_ITEM_LIST_RE = re.compile(r'[A-Za-z][A-Za-z0-9_$#]*')


def parse_apex_url(url: str) -> Optional[int]:
    """Page id a target URL points at, or None when it is external/unknown."""
    if not url:
        return None
    text = str(url).strip()
    match = _FP_RE.search(text)
    if match:
        parts = match.group(1).split(':')
        if len(parts) >= 2 and _NUMBER_RE.match(parts[1].strip()):
            return int(parts[1].strip())
        return None
    if ':' in text and 'APP_ID' in text.upper():
        parts = text.split(':')
        if len(parts) >= 2 and _NUMBER_RE.match(parts[1].strip()):
            return int(parts[1].strip())
        return None
    if _NUMBER_RE.match(text):
        return int(text)
    return None


def parse_url_items(url: str) -> List[str]:
    """Item names a `f?p=` URL sets (the `itemNames` position)."""
    if not url:
        return []
    match = _FP_RE.search(str(url))
    if not match:
        return []
    parts = match.group(1).split(':')
    if len(parts) < 7:
        return []
    return [name.upper() for name in _ITEM_LIST_RE.findall(parts[6])]
