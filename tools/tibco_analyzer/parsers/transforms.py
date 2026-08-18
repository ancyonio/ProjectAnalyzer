"""XSLT transformation parser: data transformation inventory."""
from __future__ import annotations

import logging
from pathlib import Path

from ..constants import NS
from ..model import GraphNode
from ..utils import safe_parse_xml

logger = logging.getLogger('tibco_analyzer')


class TransformParserMixin:
    """Parses `*.xsl` / `*.xslt` transformations."""

    def _parse_xslts(self) -> int:
        count = 0
        candidates = sorted(set(self.tibco_root.rglob('*.xslt'))
                            | set(self.tibco_root.rglob('*.xsl')))
        for xf in candidates:
            root = safe_parse_xml(xf)
            if root is None:
                continue

            module = self._module_of(xf)
            mod_id = self._ensure_module(module)

            xslt_id = self._next_id('xslt')
            self._add_node(GraphNode(xslt_id, 'DataTransformation', xf.stem, {
                'folder': str(xf.parent.relative_to(self.tibco_root)),
                'module': module,
                'type': 'XSLT',
                'springEquivalent': 'javax.xml.transform / MapStruct',
                'filePath': str(xf.relative_to(self.tibco_root)),
            }))
            self._add_rel(xslt_id, mod_id, 'BELONGS_TO', purpose='module-membership')
            count += 1

        self.stats['xslts'] = count
        if count:
            logger.info(f"  Parsed {count} XSLT files")
        return count

    # =================================================================
    # 8. Cross-Reference Relationship Builder
    # =================================================================
