"""
MCP Handler Client for network-scanner-mcp server.

Wraps all MCP tools as callable methods with SSE/HTTP transport support.
Designed for use in FreeNetAdminPro PyQt6 application.

Protocol: FastMCP HTTP transport uses Server-Sent Events (SSE).
  1. POST /mcp with initialize payload → server returns SSE stream + mcp-session-id header
  2. Subsequent calls use the same session ID (handled internally)
  3. SSE responses must be parsed from the text/event-stream format
"""

import json
import asyncio
import re
import aiohttp
from typing import Optional, Dict, Any, List


def _parse_sse(text: str) -> List[Dict[str, Any]]:
    """Parse SSE (Server-Sent Events) response into list of JSON payloads."""
    if not text or not text.strip():
        return []
    data_parts = re.findall(r'data:\s*(\{.*?\})\s', text, re.DOTALL)
    return [json.loads(d) for d in data_parts if d.strip().startswith('{')]


class MCPClient:
    """Async client for network-scanner-mcp HTTP transport.

    Handles SSE protocol with session management automatically.
    Each call re-uses the same aiohttp session for the SSE connection.
    """

    BASE_URL = "http://localhost:8009"

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or self.BASE_URL
        self._session: Optional[aiohttp.ClientSession] = None
        self._session_id: Optional[str] = None
        self.connected = False
        self._initialized = False

    # ─── Lifecycle ──────────────────────────────────────────────────────

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self) -> bool:
        """Establish SSE session with MCP server and perform initialization."""
        if self._session and self._initialized:
            return True
        try:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60)
            )
            assert self._session
            headers = {
                'Accept': 'application/json, text/event-stream',
                'Content-Type': 'application/json',
            }
            init_payload = {
                'jsonrpc': '2.0',
                'method': 'initialize',
                'params': {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {},
                    'clientInfo': {'name': 'freenet-admin', 'version': '1.0'},
                },
                'id': 1,
            }
            async with self._session.post(
                f"{self.base_url}/mcp",
                json=init_payload,
                headers=headers,
            ) as resp:
                self._session_id = resp.headers.get('mcp-session-id')
                self.connected = resp.status == 200
                text = await resp.text()
                msgs = _parse_sse(text)
                if msgs:
                    self._initialized = True
                else:
                    self.connected = False
        except Exception:
            self.connected = False
            self._initialized = False
        return self.connected

    async def disconnect(self):
        """Close session."""
        if self._session:
            await self._session.close()
            self._session = None
            self._session_id = None
            self.connected = False
            self._initialized = False

    # ─── Internal ───────────────────────────────────────────────────────

    async def _call_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send a tool call over the SSE session and parse the response."""
        if not self._session:
            raise RuntimeError("Not connected. Call connect() first.")

        payload = {
            'jsonrpc': '2.0',
            'method': 'tools/call',
            'params': {'name': tool_name, 'arguments': params},
            'id': 9999,
        }
        headers = {
            'Accept': 'application/json, text/event-stream',
            'Content-Type': 'application/json',
        }
        if self._session_id:
            headers['Mcp-Session-Id'] = self._session_id
        try:
            async with self._session.post(
                f"{self.base_url}/mcp",
                json=payload,
                headers=headers,
            ) as resp:
                text = await resp.text()
                msgs = _parse_sse(text)
                if not msgs:
                    return {
                        "success": False,
                        "error": f"Empty response from server (HTTP {resp.status})",
                    }
                msg = msgs[0]
                if 'error' in msg:
                    return {
                        "success": False,
                        "error": msg['error'].get('message', 'Unknown MCP error'),
                        "code": msg['error'].get('code'),
                    }
                result = msg.get('result', {})
                content = result.get('content', {})
                if isinstance(content, list) and content:
                    text_str = content[0].get('text', '{}')
                elif isinstance(content, str):
                    text_str = content
                else:
                    text_str = json.dumps(content)
                return json.loads(text_str)
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─── Device Discovery ───────────────────────────────────────────────

    async def scan_network(
        self,
        subnet: Optional[str] = None,
        resolve_names: bool = True,
    ) -> Dict[str, Any]:
        """Scan local network for connected devices using ARP."""
        return await self._call_tool("scan_network", {
            "subnet": subnet,
            "resolve_names": resolve_names,
        })

    async def detect_new_devices(self) -> Dict[str, Any]:
        """Scan network and return only newly discovered devices."""
        return await self._call_tool("detect_new_devices", {})

    async def get_unknown_devices(self) -> Dict[str, Any]:
        """Get list of all unknown/unverified devices on the network."""
        return await self._call_tool("get_unknown_devices", {})

    # ─── Device Information ─────────────────────────────────────────────

    async def get_device_info(self, identifier: str) -> Dict[str, Any]:
        """Get detailed info about a device by IP or MAC address."""
        return await self._call_tool("get_device_info", {"identifier": identifier})

    async def get_device_history(
        self,
        mac: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get full device history including first/last seen and visit counts."""
        return await self._call_tool("get_device_history", {"mac": mac})

    async def mark_device_known(
        self,
        mac: str,
        label: str,
        device_type: str = "trusted",
    ) -> Dict[str, Any]:
        """Mark a device as known/trusted with a label."""
        return await self._call_tool("mark_device_known", {
            "mac": mac,
            "label": label,
            "device_type": device_type,
        })

    async def remove_device_known(self, mac: str) -> Dict[str, Any]:
        """Remove a device from the known/trusted list."""
        return await self._call_tool("remove_device_known", {"mac": mac})

    # ─── Network Topology ───────────────────────────────────────────────

    async def get_network_topology(self) -> Dict[str, Any]:
        """Get full network topology with categorized devices."""
        return await self._call_tool("get_network_topology", {})

    # ─── Cluster Monitoring ─────────────────────────────────────────────

    async def get_cluster_nodes(self) -> Dict[str, Any]:
        """Get status of known cluster nodes on the network."""
        return await self._call_tool("get_cluster_nodes", {})

    async def check_cluster_health(self) -> Dict[str, Any]:
        """Perform comprehensive health check on all cluster nodes."""
        return await self._call_tool("check_cluster_health", {})

    # ─── Port Scanning ──────────────────────────────────────────────────

    async def scan_device_ports(
        self,
        target: str,
        ports: Optional[str] = None,
        quick: bool = True,
    ) -> Dict[str, Any]:
        """Scan ports on a specific device."""
        return await self._call_tool("scan_device_ports", {
            "target": target,
            "ports": ports,
            "quick": quick,
        })

    async def discover_services(self) -> Dict[str, Any]:
        """Discover services running on all known devices."""
        return await self._call_tool("discover_services", {})

    # ─── Utilities ──────────────────────────────────────────────────────

    async def ping_device(
        self,
        target: str,
        count: int = 3,
    ) -> Dict[str, Any]:
        """Ping a device to check reachability and latency."""
        return await self._call_tool("ping_device", {
            "target": target,
            "count": count,
        })

    async def resolve_hostname(self, target: str) -> Dict[str, Any]:
        """Resolve hostname for a device via reverse DNS."""
        return await self._call_tool("resolve_device_hostname", {
            "target": target,
        })

    async def get_scanner_status(self) -> Dict[str, Any]:
        """Get current status of the network scanner."""
        return await self._call_tool("get_scanner_status", {})

    async def export_for_security_scan(self) -> Dict[str, Any]:
        """Export discovered devices for security scanning integration."""
        return await self._call_tool("export_for_security_scan", {})

    # ─── Compliance & Defense ───────────────────────────────────────────

    async def network_scap_report(
        self,
        target: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate SCAP-compliant scan results (XCCDF, OVAL, CPE)."""
        return await self._call_tool("network_scap_report", {
            "target": target,
        })

    async def network_cis_check(
        self,
        target: str,
        known_services: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run CIS Benchmark assessment against a target device."""
        return await self._call_tool("network_cis_check", {
            "target": target,
            "known_services": known_services,
        })

    async def network_asset_inventory(self) -> Dict[str, Any]:
        """Generate NIST CSF-aligned asset inventory."""
        return await self._call_tool("network_asset_inventory", {})

    async def network_zero_trust_assess(self) -> Dict[str, Any]:
        """Perform Zero Trust Architecture posture assessment."""
        return await self._call_tool("network_zero_trust_assess", {})

    async def network_compliance_map(
        self,
        include_cis: bool = True,
    ) -> Dict[str, Any]:
        """Map scan findings to NIST SP 800-53 Rev. 5 security controls."""
        return await self._call_tool("network_compliance_map", {
            "include_cis": include_cis,
        })

    async def network_vuln_prioritize(
        self,
        vulns_json: str,
    ) -> Dict[str, Any]:
        """Perform defense-grade vulnerability prioritization."""
        return await self._call_tool("network_vuln_prioritize", {
            "vulns_json": vulns_json,
        })

    async def network_generate_poam(self) -> Dict[str, Any]:
        """Generate Plan of Action & Milestones (POA&M) document."""
        return await self._call_tool("network_generate_poam", {})
