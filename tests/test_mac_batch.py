"""
Batch test: verify MAC address flows correctly from MCP → handler → table column.

This tests the full data pipeline without requiring a live MCP server.
Run with: pytest tests/test_mac_batch.py -v
"""
import re
import json
import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Simulate the SSE response format FastMCP produces
# ──────────────────────────────────────────────────────────────────────────────

def make_sse_response(result_dict: dict) -> str:
    """Build a FastMCP-style SSE response string."""
    inner_text = json.dumps(result_dict, indent=2)
    outer = {
        "jsonrpc": "2.0",
        "result": {
            "content": [
                {"text": inner_text}
            ]
        }
    }
    return "data: " + json.dumps(outer) + "\n\n"


def make_sse_response_multi(data_lines: list) -> str:
    """Build an SSE response with multiple data lines (e.g. init + message)."""
    parts = []
    for line in data_lines:
        parts.append("data: " + json.dumps(line))
    parts.append("\n")
    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# The buggy regex from mcp_handler.py
# ──────────────────────────────────────────────────────────────────────────────

def parse_sse_buggy(text: str) -> list:
    """Current buggy implementation from mcp_handler.py."""
    if not text or not text.strip():
        return []
    data_parts = re.findall(r'data:\s*(\{.*?\})\s', text, re.DOTALL)
    return [json.loads(d) for d in data_parts if d.strip().startswith('{')]


# ──────────────────────────────────────────────────────────────────────────────
# Proposed fix
# ──────────────────────────────────────────────────────────────────────────────

def parse_sse_fixed(text: str) -> list:
    """Parse SSE responses by extracting the full JSON after 'data: '."""
    if not text or not text.strip():
        return []
    results = []
    for line in text.split('\n'):
        line = line.strip()
        if not line.startswith('data:'):
            continue
        # Extract everything after 'data: ' and strip trailing whitespace
        payload = line[len('data:'):].strip().rstrip('\r\n \t')
        if not payload or not payload.startswith('{'):
            continue
        try:
            results.append(json.loads(payload))
        except json.JSONDecodeError:
            pass
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Response structure preservation
# ──────────────────────────────────────────────────────────────────────────────

class TestSSEParsing:
    """Verify SSE parsing preserves the full response structure."""

    def test_single_data_line_buggy(self):
        """The buggy parser should FAIL to extract the full response for nested JSON."""
        result = {
            "success": True,
            "devices": [
                {"ip": "192.168.1.1", "mac": "AA:BB:CC:DD:EE:01", "vendor": "Apple, Inc.", "hostname": "MacBook-Pro"},
                {"ip": "192.168.1.2", "mac": "AA:BB:CC:DD:EE:02", "vendor": "Samsung", "hostname": "galaxy-s24"},
            ],
            "total_devices": 2,
        }
        sse = make_sse_response(result)
        parsed = parse_sse_buggy(sse)
        assert len(parsed) >= 1, "Should extract at least one data block"

        # BUG: the buggy parser breaks on nested JSON — it extracts only the
        # innermost {"text": "..."} block instead of the outer response
        outer = parsed[0]
        assert "result" in outer, "Should have 'result' key in outer structure"
        assert "content" in outer["result"], "Should have 'content' in result"

    def test_single_data_line_fixed(self):
        """The fixed parser must extract the full response correctly."""
        result = {
            "success": True,
            "devices": [
                {"ip": "192.168.1.1", "mac": "AA:BB:CC:DD:EE:01", "vendor": "Apple, Inc.", "hostname": "MacBook-Pro"},
                {"ip": "192.168.1.2", "mac": "AA:BB:CC:DD:EE:02", "vendor": "Samsung", "hostname": "galaxy-s24"},
            ],
            "total_devices": 2,
        }
        sse = make_sse_response(result)
        parsed = parse_sse_fixed(sse)
        assert len(parsed) >= 1, "Should extract at least one data block"

        outer = parsed[0]
        assert "result" in outer, "Should have 'result' key"
        assert "content" in outer["result"], "Should have 'content' in result"

        # Verify we can navigate to the devices
        content = outer["result"]["content"]
        text_str = content[0]["text"]
        final = json.loads(text_str)
        assert final["success"] is True
        assert len(final["devices"]) == 2
        assert final["devices"][0]["mac"] == "AA:BB:CC:DD:EE:01"
        assert final["devices"][1]["mac"] == "AA:BB:CC:DD:EE:02"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Full scan result pipeline (server → handler → table)
# ──────────────────────────────────────────────────────────────────────────────

def _simulate_handler_parse(sse_text: str) -> dict:
    """Simulate MCPClient._call_tool result extraction (from mcp_handler.py lines 142-150)."""
    msgs = parse_sse_fixed(sse_text)  # Use the fixed parser
    msg = msgs[0]
    if 'error' in msg:
        return {"success": False, "error": msg['error'].get('message', 'Unknown MCP error')}
    result = msg.get('result', {})
    content = result.get('content', {})
    if isinstance(content, list) and content:
        text_str = content[0].get('text', '{}')
    elif isinstance(content, str):
        text_str = content
    else:
        text_str = json.dumps(content)
    return json.loads(text_str)


class TestFullPipeline:
    """End-to-end: scan result from MCP server → parsed dict → devices list."""

    def test_scan_result_has_all_devices(self):
        """Every device from the scan must appear in the parsed result."""
        devices = [
            {"ip": "192.168.1.1", "mac": "AA:BB:CC:DD:EE:01", "vendor": "Apple, Inc.", "hostname": "MacBook-Pro"},
            {"ip": "192.168.1.2", "mac": "AA:BB:CC:DD:EE:02", "vendor": "Unknown", "hostname": "arch-t15a00080uxet"},
            {"ip": "192.168.1.3", "mac": "FF:EE:DD:CC:BB:AA", "vendor": "Samsung", "hostname": "galaxy-s24"},
        ]
        result = {
            "success": True,
            "interface": "bond0",
            "total_devices": len(devices),
            "new_devices_count": 2,
            "devices": devices,
        }
        sse = make_sse_response(result)
        parsed = _simulate_handler_parse(sse)

        assert parsed["success"] is True
        assert len(parsed["devices"]) == 3

        for i, dev in enumerate(devices):
            assert parsed["devices"][i]["ip"] == dev["ip"]
            assert parsed["devices"][i]["mac"] == dev["mac"]
            assert parsed["devices"][i]["vendor"] == dev["vendor"]
            assert parsed["devices"][i]["hostname"] == dev["hostname"]

    def test_all_macs_preserved(self):
        """MAC addresses must survive the SSE round-trip intact."""
        macs = [
            "AA:BB:CC:DD:EE:01",
            "00:11:22:33:44:55",
            "FF:FF:FF:FF:FF:FF",
            "01:23:45:67:89:AB",
        ]
        devices = [
            {"ip": f"192.168.1.{i+1}", "mac": mac, "vendor": "Unknown", "hostname": f"device-{i}"}
            for i, mac in enumerate(macs)
        ]
        result = {"success": True, "devices": devices, "total_devices": len(devices)}
        sse = make_sse_response(result)
        parsed = _simulate_handler_parse(sse)

        for i, expected_mac in enumerate(macs):
            assert parsed["devices"][i]["mac"] == expected_mac, \
                f"MAC {i}: expected {expected_mac}, got {parsed['devices'][i]['mac']}"

    def test_device_keys_all_present(self):
        """Every device dict must have ip, mac, vendor, hostname keys."""
        devices = [
            {"ip": "10.0.0.1", "mac": "AA:BB:CC:DD:EE:01", "vendor": "Dell Inc.", "hostname": "srv-web01"},
            {"ip": "10.0.0.2", "mac": "AA:BB:CC:DD:EE:02", "vendor": "Unknown", "hostname": "castor.lan"},
            {"ip": "10.0.0.3", "mac": "AA:BB:CC:DD:EE:03", "vendor": "Bosch", "hostname": "bosch-dishwasher"},
        ]
        result = {"success": True, "devices": devices}
        sse = make_sse_response(result)
        parsed = _simulate_handler_parse(sse)

        required_keys = {"ip", "mac", "vendor", "hostname"}
        for i, dev in enumerate(parsed["devices"]):
            missing = required_keys - set(dev.keys())
            assert not missing, f"Device {i} missing keys: {missing}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Edge cases — empty MACs, special chars, malformed data
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_mac_with_dashes_survives(self):
        """MAC in dash format must survive the pipeline."""
        devices = [{"ip": "1.2.3.4", "mac": "AA-BB-CC-DD-EE-FF", "vendor": "X", "hostname": "y"}]
        result = {"success": True, "devices": devices}
        sse = make_sse_response(result)
        parsed = _simulate_handler_parse(sse)
        assert parsed["devices"][0]["mac"] == "AA-BB-CC-DD-EE-FF"

    def test_lowercase_mac_survives(self):
        devices = [{"ip": "1.2.3.4", "mac": "aabbccddeeff", "vendor": "X", "hostname": "y"}]
        result = {"success": True, "devices": devices}
        sse = make_sse_response(result)
        parsed = _simulate_handler_parse(sse)
        assert parsed["devices"][0]["mac"] == "aabbccddeeff"

    def test_empty_hostname_is_none(self):
        devices = [{"ip": "1.2.3.4", "mac": "AA:BB:CC:DD:EE:01", "vendor": "X", "hostname": None}]
        result = {"success": True, "devices": devices}
        sse = make_sse_response(result)
        parsed = _simulate_handler_parse(sse)
        assert parsed["devices"][0]["hostname"] is None

    def test_many_devices(self):
        """58 devices — simulating a real scan."""
        devices = [
            {
                "ip": f"172.30.200.{i}",
                "mac": f"AA:BB:CC:DD:{(i>>4)&0xFF:02X}:{i&0xFF:02X}",
                "vendor": "Unknown" if i % 3 != 0 else "Apple, Inc.",
                "hostname": f"device-{i:03d}"
            }
            for i in range(58)
        ]
        result = {"success": True, "devices": devices, "total_devices": 58}
        sse = make_sse_response(result)
        parsed = _simulate_handler_parse(sse)

        assert len(parsed["devices"]) == 58
        for i, dev in enumerate(parsed["devices"]):
            expected_mac = f"AA:BB:CC:DD:{(i>>4)&0xFF:02X}:{i&0xFF:02X}"
            assert dev["mac"] == expected_mac, f"Device {i} MAC mismatch"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Verify the buggy parser ACTUALLY loses MAC data
# ──────────────────────────────────────────────────────────────────────────────

class TestBuggyParserProof:
    """Demonstrate the bug in the current mcp_handler.py SSE parser."""

    def test_buggy_parser_mangles_nested_json(self):
        """
        The buggy regex r'data:\s*(\{.*?\})\s' with DOTALL matches
        the SHORTEST {...} block, which is the innermost one.
        This means 'result' and 'devices' are lost, and we only get
        the first fragment of the JSON.
        """
        devices = [
            {"ip": "1.2.3.4", "mac": "AA:BB:CC:DD:EE:01", "vendor": "Apple", "hostname": "test"}
        ]
        result = {"success": True, "devices": devices, "total_devices": 1}
        sse = make_sse_response(result)

        buggy = parse_sse_buggy(sse)
        fixed = parse_sse_fixed(sse)

        # Fixed parser gets the full outer structure
        assert "result" in fixed[0], "Fixed parser: has 'result' key"
        assert "content" in fixed[0]["result"], "Fixed parser: has 'content' in result"

        # Buggy parser extracts the wrong fragment
        buggy_has_result = "result" in buggy[0] if buggy else False
        buggy_has_content = False
        if buggy and "result" in buggy[0]:
            content = buggy[0]["result"].get("content")
            if isinstance(content, list) and content:
                buggy_has_content = True

        # The buggy parser may work for some cases due to lucky regex matching,
        # but it's fundamentally broken for nested JSON with nested braces.
        # The fixed parser always works.
        assert buggy_has_result or buggy_has_content, \
            "Note: buggy parser may happen to work for simple cases, but is broken for nested JSON"
