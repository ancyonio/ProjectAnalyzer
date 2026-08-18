"""Shared resource and global variable parsers.

Shared resources (HTTP/JMS/JDBC connections, identities) become `SharedResource`
nodes wired to external `System` nodes; `.substvar` files become
`GlobalVariable` nodes -- the future `application.yml` of the target service.

Both resource generations are handled. BW5 keeps its detail in child elements
(`<Host>`, `<Port>`, `<driver>`); BW6/BWCE wraps everything in an XMI
`jndi:namedResource` envelope and keeps its detail in attributes on
`jndi:configuration`, `connectionConfig` and `tcpDetails`. Credentials are
never copied into the graph.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Set

from ..constants import (NS, SHARED_RESOURCE_MAP, SHARED_RESOURCE_MAP_BW6,
                         BW6_RESOURCE_TYPE_PREFIXES, ADAPTER_RESOURCE_TYPES)
from ..model import GraphNode
from ..utils import safe_parse_xml, safe_text

logger = logging.getLogger('tibco_analyzer')


class ResourceParserMixin:
    """Parses shared resources and `.substvar` global variables."""

    # Extensions whose files are BW6 resources even when not individually
    # catalogued; the `@type` attribute then supplies the classification.
    _BW6_SUFFIX_HINTS = ('resource', 'globalinstance')

    def _shared_resource_files(self):
        """Every shared-resource file in the tree, both BW5 and BW6 spellings.

        Matching is case-insensitive because TIBCO writes `.jdbcResource` while
        some exports lower-case the extension, and `Path.rglob` is only
        case-insensitive on Windows.
        """
        known = {ext.lower(): ext for ext in SHARED_RESOURCE_MAP}
        found = {}
        for path in self.tibco_root.rglob('*'):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if not suffix:
                continue
            if suffix in known:
                found[path] = known[suffix]
            elif suffix.endswith(self._BW6_SUFFIX_HINTS):
                # An uncatalogued BW6 resource: keep it, classify it from XML.
                found[path] = path.suffix
        return sorted(found.items(), key=lambda kv: str(kv[0]))

    @staticmethod
    def _classify_resource(ext, root):
        """(type, tech, spring) for a resource file, extension first, XML second."""
        mapping = SHARED_RESOURCE_MAP.get(ext)
        if mapping is None:
            mapping = SHARED_RESOURCE_MAP.get(ext.lower())
        if mapping is None and root is not None:
            # BW6 `type="jdbc:JdbcDataSource"` -> prefix `jdbc`.
            type_attr = (root.get('type') or '')
            prefix = type_attr.split(':')[0].strip().lower()
            mapping = BW6_RESOURCE_TYPE_PREFIXES.get(prefix)
        if mapping is None:
            return 'UNKNOWN', 'Unknown', 'Unknown'
        return mapping.get('type', 'UNKNOWN'), mapping.get('tech', 'Unknown'), \
            mapping.get('spring', 'Unknown')

    @staticmethod
    def _is_bw6_resource(root) -> bool:
        return root is not None and root.tag.split('}')[-1] == 'namedResource'

    @staticmethod
    def _bw6_details(root):
        """Host/port/url/driver from a BW6 `jndi:namedResource` envelope.

        Detail lives in attributes, not child elements. Credentials
        (`password`, `username`) are deliberately not extracted.
        """
        host = port_val = url = driver = ''
        for el in root.iter():
            tag = el.tag.split('}')[-1]
            attrib = el.attrib
            if tag == 'connectionConfig':
                driver = attrib.get('jdbcDriver', driver)
                url = attrib.get('dbURL', url)
            elif tag == 'tcpDetails':
                host = attrib.get('host', host)
                port_val = attrib.get('port', port_val)
            elif tag == 'configuration':
                url = attrib.get('providerURL') or attrib.get('namingURL') or url
                port_val = attrib.get('port', port_val)
                host = attrib.get('host', host)
            elif tag == 'sessionConfig':
                url = attrib.get('providerURL', url)
        return host, port_val, url, driver

    @staticmethod
    def _bw5_details(root):
        """Host/port/url/driver from a BW5 resource, which uses child elements."""
        host = port_val = url = driver = ''
        host_el = root.find('.//Host')
        if host_el is not None:
            host = safe_text(host_el)
        port_el = root.find('.//Port')
        if port_el is not None:
            port_val = safe_text(port_el)
        driver_el = root.find('.//driver')
        if driver_el is not None:
            driver = safe_text(driver_el)
        loc_el = root.find('.//location')
        if loc_el is not None:
            url = safe_text(loc_el)
        provider_el = root.find('.//ProviderURL')
        if provider_el is not None:
            url = safe_text(provider_el)
        naming_url = root.find('.//NamingURL')
        if naming_url is not None and not url:
            url = safe_text(naming_url)
        proxy_host = root.find('.//proxyHost')
        if proxy_host is not None:
            host = safe_text(proxy_host)
        proxy_port = root.find('.//proxyPort')
        if proxy_port is not None:
            port_val = safe_text(proxy_port)
        return host, port_val, url, driver

    def _parse_shared_resources(self) -> int:
        count = 0
        bw6_count = 0

        for rf, ext in self._shared_resource_files():
            root = safe_parse_xml(rf)
            module = self._module_of(rf)
            mod_id = self._ensure_module(module)
            res_name = rf.stem

            res_type, tech, spring_eq = self._classify_resource(ext, root)

            is_bw6 = self._is_bw6_resource(root)
            # BW6 resources carry their own fully-qualified name
            # ("Assignment_5.JMSConnectionResource"), which is exactly the
            # string a `.bwp` uses to reference them.
            qualified_name = ''
            if root is not None:
                if is_bw6:
                    bw6_count += 1
                    qualified_name = (root.get('name') or '').strip()
                    host, port_val, url, driver = self._bw6_details(root)
                else:
                    host, port_val, url, driver = self._bw5_details(root)
            else:
                host = port_val = url = driver = ''

            res_id = self._next_id('res')
            rel_path = str(rf.relative_to(self.tibco_root)).replace('\\', '/')

            self._add_node(GraphNode(res_id, 'SharedResource', res_name, {
                'folder': str(rf.parent.relative_to(self.tibco_root)),
                'module': module,
                'resourceType': res_type,
                'technology': tech,
                'springEquivalent': spring_eq,
                'host': host,
                'port': port_val,
                'url': url,
                'driver': driver,
                'filePath': rel_path,
                'qualifiedName': qualified_name,
                'bwVersion': 'BW6' if is_bw6 else 'BW5',
            }))

            # Index by every fragment a process might use to refer to it.
            for part_idx in range(len(Path(rel_path).parts)):
                partial = '/'.join(Path(rel_path).parts[part_idx:])
                self._resource_by_path[partial] = res_id
            self._resource_by_path[res_name + ext] = res_id
            self._resource_by_path[res_name] = res_id
            if qualified_name:
                self._resource_by_path[qualified_name] = res_id
                self._resource_by_path[qualified_name.lower()] = res_id
                # "Assignment_5.JMSConnectionResource" -> also match the tail.
                tail = qualified_name.rsplit('.', 1)[-1]
                if tail:
                    self._resource_by_path.setdefault(tail, res_id)

            # BELONGS_TO
            self._add_rel(res_id, mod_id, 'BELONGS_TO', purpose='module-membership')

            # Create Adapter node for connection-style resources
            if res_type in ADAPTER_RESOURCE_TYPES:
                adp_id = self._next_id('adp')
                self._add_node(GraphNode(adp_id, 'Adapter', f"{res_name}_Adapter", {
                    'type': res_type,
                    'technology': tech,
                    'springEquivalent': spring_eq,
                    'resourceRef': res_id,
                    'module': module,
                }))
                self._add_rel(adp_id, res_id, 'CONFIGURED_BY', purpose='adapter-config')

                sys_id = self._ensure_system(tech)
                self._add_rel(adp_id, sys_id, 'CONNECTS_TO',
                              technology=tech, purpose='system-integration')
                # The documented graph model and the Neo4j cookbook both
                # traverse SharedResource -> System directly, so emit that edge
                # as well rather than forcing every consumer through Adapter.
                self._add_rel(res_id, sys_id, 'CONNECTS_TO',
                              technology=tech, purpose='system-integration')

            count += 1

        self.stats['shared_resources'] = count
        self.stats['shared_resources_bw6'] = bw6_count
        logger.info(f"  Parsed {count} shared resource files "
                    f"({bw6_count} BW6, {count - bw6_count} BW5)")
        return count

    # =================================================================
    # 5. Global Variables Parser (.substvar)
    # =================================================================
    def _parse_global_variables(self) -> int:
        count = 0
        var_count = 0
        for sf in sorted(self.tibco_root.rglob('*.substvar')):
            root = safe_parse_xml(sf)
            if root is None:
                continue

            module = self._module_of(sf)
            mod_id = self._ensure_module(module)
            gv_rel_path = str(sf.relative_to(self.tibco_root)).replace('\\', '/')

            # Try both with and without namespace
            repo_ns = 'http://www.tibco.com/xmlns/repo/types/2002'
            gvars = root.findall(f'.//{{{repo_ns}}}globalVariable')
            if not gvars:
                gvars = root.findall('.//globalVariable')
            if not gvars:
                # Fallback: iterate all descendants for any tag containing 'globalVariable'
                gvars = [el for el in root.iter() if el.tag.endswith('}globalVariable') or el.tag == 'globalVariable']
            logger.debug(f"  substvar {sf.name}: root.tag={root.tag}, gvars={len(gvars)}")
            for gv in gvars:
                name_el = gv.find(f'{{{repo_ns}}}name')
                if name_el is None:
                    name_el = gv.find('name')
                value_el = gv.find(f'{{{repo_ns}}}value')
                if value_el is None:
                    value_el = gv.find('value')
                type_el = gv.find(f'{{{repo_ns}}}type')
                if type_el is None:
                    type_el = gv.find('type')
                deploy_el = gv.find(f'{{{repo_ns}}}deploymentSettable')
                if deploy_el is None:
                    deploy_el = gv.find('deploymentSettable')
                svc_el = gv.find(f'{{{repo_ns}}}serviceSettable')
                if svc_el is None:
                    svc_el = gv.find('serviceSettable')

                vname = safe_text(name_el)
                if not vname:
                    continue

                vvalue = safe_text(value_el)
                vtype = safe_text(type_el, 'String')
                deployable = safe_text(deploy_el, 'false') == 'true'
                service_settable = safe_text(svc_el, 'false') == 'true'

                # Mask sensitive values
                display_value = vvalue
                if any(kw in vname.lower() for kw in ('password', 'secret', 'credential', 'key')):
                    display_value = '***MASKED***'

                gvar_key = f"{module}/{vname}"
                if gvar_key not in self._gvar_ids:
                    gvar_id = self._next_id('gvar')
                    self._add_node(GraphNode(gvar_id, 'GlobalVariable', vname, {
                        'value': display_value,
                        'varType': vtype,
                        'module': module,
                        'deployable': deployable,
                        'serviceSettable': service_settable,
                        'springEquivalent': 'application.yml property',
                        'filePath': gv_rel_path,
                    }))
                    self._gvar_ids[gvar_key] = gvar_id

                    self._add_rel(gvar_id, mod_id, 'CONFIGURES', purpose='module-configuration')
                    var_count += 1

            count += 1

        self.stats['substvar_files'] = count
        self.stats['global_variables'] = var_count
        logger.info(f"  Parsed {count} substvar files ({var_count} unique variables)")
        return var_count

    # =================================================================
    # 6. AE Schema Parser
    # =================================================================
