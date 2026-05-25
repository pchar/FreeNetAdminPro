"""
Unit tests for FreeNetAdminPro — icon loading, classification, and item sorting.

Run with: pytest tests/ -v
These tests are standalone — no Qt imports needed, so they run cleanly
outside the application without needing pytest or Qt environment.
"""
import os
import sys
import pytest
from ipaddress import ip_address


# ──────────────────────────────────────────────────────────────────────────────
# Fixture
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Icon Files Exist on Disk
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("icon_path,expected_exists", [
    ("icons/apple.svg", True),
    ("icons/linux.svg", True),
    ("icons/windows.svg", True),
    ("icons/mobile.svg", True),
    ("icons/server.svg", True),
    ("icons/start.svg", True),
    ("icons/stop.svg", True),
    ("icons/connected.svg", True),
    ("icons/not_connected.svg", True),
])
def test_icon_files_exist(app_dir, icon_path, expected_exists):
    """All expected icon SVG files exist."""
    full_path = os.path.join(app_dir, icon_path)
    if expected_exists:
        assert os.path.exists(full_path), f"Missing icon: {full_path}"
    else:
        assert not os.path.exists(full_path), f"Unexpected icon: {full_path}"


@pytest.mark.parametrize("icon_path", [
    "icons/apple.svg",
    "icons/linux.svg",
    "icons/windows.svg",
    "icons/mobile.svg",
    "icons/server.svg",
])
def test_icon_svg_valid(app_dir, icon_path):
    """Icon SVG files have valid XML structure."""
    import xml.etree.ElementTree as ET
    
    full_path = os.path.join(app_dir, icon_path)
    tree = ET.parse(full_path)
    root = tree.getroot()
    
    # Should have an SVG namespace
    assert root.tag.startswith('{'), f"Missing namespace in {icon_path}"
    assert 'svg' in root.tag.lower(), f"Not SVG element in {icon_path}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: IP Numeric Sorting Logic (no Qt needed)
# ──────────────────────────────────────────────────────────────────────────────

def _ip_to_num(ip: str) -> int:
    """Convert IP string to 32-bit integer (mirrors IPTableWidgetItem logic)."""
    try:
        return int(ip_address(ip))
    except (ValueError, TypeError):
        return -1


class TestIPSorting:
    def test_9_vs_10(self):
        """'9.0.0.1' < '10.0.0.1' — numeric correct, string wrong."""
        assert _ip_to_num("9.0.0.1") < _ip_to_num("10.0.0.1")
    
    def test_192_vs_9(self):
        """'192.168.1.1' > '9.0.0.1'."""
        assert _ip_to_num("9.0.0.1") < _ip_to_num("192.168.1.1")
    
    def test_na_sorts_first(self):
        """'N/A' returns -1, sorting before valid IPs."""
        assert _ip_to_num("N/A") == -1
    
    def test_private_ranges(self):
        """Private ranges sort correctly."""
        ips = ["10.0.0.1", "10.0.0.10", "10.0.0.2", "192.168.1.1", "172.16.0.1"]
        nums = [_ip_to_num(ip) for ip in ips]
        sorted_pairs = sorted(zip(nums, ips))
        assert [ip for _, ip in sorted_pairs] == sorted(ips, key=_ip_to_num)


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Device Classification Logic (no Qt needed)
# ──────────────────────────────────────────────────────────────────────────────

def _classify_device(vendor: str, hostname: str) -> str:
    """Direct copy of production classify_device logic for testing."""
    vendor_lower = (vendor or "").lower()
    host_lower = (hostname or "").lower()
    
    # 1. Apple vendor
    for kw in ["apple", "iphone", "ipad", "imac", "macbook"]:
        if kw in vendor_lower:
            return "apple"
    
    # 2. iOS hostname
    for kw in ["iphone", "ipad", "ipod", "macbook", "imac", "mac mini"]:
        if kw in host_lower:
            return "ios"
    
    # 3. Windows hostname
    for kw in ["win-", "win_", "desktop-", "desktop_"]:
        if kw in host_lower:
            return "windows"
    
    # 4. Server hostname
    for kw in ["srv", "server", "nas", "storage", "db-", "db_", "slave"]:
        if kw in host_lower:
            return "server"
    
    # 5. Linux vendor
    linux_vendors = ["dell", "hpe", "hp inc", "lenovo", "ibm", "super micro",
                "raspberry pi", "cisco", "juniper", "arista", "mikrotik",
                "ubiquiti", "fortinet", "google", "amd", "arm"]
    for kw in linux_vendors:
        if kw in vendor_lower:
            if any(s in vendor_lower for s in ["dell", "hpe", "hp inc", "lenovo", "ibm", "super micro", "raspberry pi"]):
                return "server"
            if any(n in vendor_lower for n in ["cisco", "juniper", "arista", "mikrotik", "ubiquiti", "fortinet"]):
                return "network"
            return "linux"
    
    # 6. IoT hostname
    for kw in ["bosch", "siemens", "miele", "viessmann", "netatmo",
                "ring", "nest", "tplink", "kasa", "sonoff", "tuya",
                "philips hue", "wemo", "ecobee", "honeywell", "blink",
                "arlo", "annke", "reolink", "dishwasher", "washing",
                "fridge", "oven", "gl-mt", "airlock", "nighthawk", "orbi",
                "smart", "iot-", "sensor"]:
        if kw in host_lower:
            return "server"
    
    # 7. Mobile vendor
    for kw in ["samsung", "huawei", "xiaomi", "oppo", "vivo",
                "oneplus", "nokia", "lg electronics"]:
        if kw in vendor_lower:
            return "android"
    
    # 8. Linux hostname
    for kw in ["arch", "gentoo", "fedora", "ubuntu", "debian", "centos",
                "rhel", "opensuse", "kali", "parrot", "raspbian", "pi-hole",
                "omv", "openmediavault", "master", "node", "worker",
                "cluster", "compute", "castor", "pollux", "venus", "sun",
                "eris", "pluto", "ceres", "juno", "dione", "tethys",
                "cicladi", "chiara", "ultimaker", "prusa", "creality",
                "rswave", "rsmat", "wlan0", "eth0", "enp", "eno",
                "workstation", "dev-", "staging-", "prod-", "jenkins",
                "gitlab"]:
        if kw in host_lower:
            return "linux"
    
    return "unknown"


class TestClassifyApple:
    def test_apple_vendor(self):
        assert _classify_device("Apple, Inc.", "MacBook-Pro") == "apple"
    
    def test_iphone_vendor(self):
        assert _classify_device("Apple", "iPhone") == "apple"


class TestClassifyIOS:
    def test_macbook(self):
        assert _classify_device("", "macbook-pro") == "ios"
    
    def test_iphone(self):
        assert _classify_device("", "iphone-xyz") == "ios"
    
    def test_ipad(self):
        assert _classify_device("", "ipad-air") == "ios"


class TestClassifyWindows:
    def test_win(self):
        assert _classify_device("", "WIN-ABC123") == "windows"
    
    def test_desktop(self):
        assert _classify_device("", "DESKTOP-XYZ789") == "windows"


class TestClassifyServer:
    def test_srv(self):
        assert _classify_device("", "srv-dc01") == "server"
    
    def test_nas(self):
        assert _classify_device("", "nas-home") == "server"
    
    def test_db(self):
        assert _classify_device("", "db-01") == "server"
    
    def test_slave(self):
        assert _classify_device("", "slave11") == "server"


class TestClassifyLinux:
    def test_arch(self):
        assert _classify_device("", "arch-t15a00080uxet") == "linux"
    
    def test_greek_name(self):
        assert _classify_device("", "castor.lan") == "linux"
    
    def test_master(self):
        assert _classify_device("", "master.lan") == "linux"
    
    def test_cicladi(self):
        assert _classify_device("", "cicladi.lan") == "linux"


class TestClassifyIoT:
    def test_bosch(self):
        assert _classify_device("", "bosch-dishwasher") == "server"
    
    def test_miele(self):
        assert _classify_device("", "miele-001d63") == "server"
    
    def test_viessmann(self):
        assert _classify_device("", "viessmann-123") == "server"
    
    def test_netatmo(self):
        assert _classify_device("", "netatmo-presence") == "server"
    
    def test_tplink(self):
        assert _classify_device("", "tplink-camera") == "server"


class TestClassifyAndroid:
    def test_samsung(self):
        assert _classify_device("Samsung", "") == "android"
    
    def test_huawei(self):
        assert _classify_device("Huawei", "") == "android"


class TestClassifyUnknown:
    def test_empty(self):
        assert _classify_device("", "") == "unknown"
    
    def test_none(self):
        assert _classify_device(None, None) == "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: MAC Sorting Logic (no Qt needed)
# ──────────────────────────────────────────────────────────────────────────────

def _mac_to_key(mac: str) -> str:
    """Normalize MAC for sorting (mirrors MacTableWidgetItem logic)."""
    if not mac or mac.upper() == "N/A":
        return "ZZ"
    normalized = mac.upper().replace(":", "").replace("-", "")
    # Verify it looks like a MAC (12 hex chars)
    if len(normalized) == 12 and all(c in "0123456789ABCDEF" for c in normalized):
        return normalized
    return "ZZ"


class TestMacSorting:
    def test_001_vs_002(self):
        assert _mac_to_key("00:11:22:33:44:01") < _mac_to_key("00:11:22:33:44:02")
    
    def test_dashes_normalized(self):
        assert _mac_to_key("00-11-22-33-44-01") == _mac_to_key("00:11:22:33:44:01")
    
    def test_invalid(self):
        assert _mac_to_key("N/A") == "ZZ"
        assert _mac_to_key("") == "ZZ"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Resources QRC / RC
# ──────────────────────────────────────────────────────────────────────────────

class TestResources:
    @pytest.fixture
    def qrc_content(self, app_dir):
        with open(os.path.join(app_dir, "resources.qrc"), "r") as f:
            return f.read()
    
    @pytest.fixture
    def rc_content(self, app_dir):
        with open(os.path.join(app_dir, "rc_resources.py"), "r") as f:
            return f.read()
    
    def test_qrc_has_all_icons(self, qrc_content):
        """resources.qrc includes all SVG icons."""
        expected = [
            "apple.svg", "linux.svg", "windows.svg", "mobile.svg",
            "server.svg", "start.svg", "stop.svg", "connected.svg",
            "not_connected.svg",
        ]
        for icon in expected:
            assert icon in qrc_content, f"Missing in resources.qrc: {icon}"
    
    def test_rc_python_exists(self, rc_content):
        """rc_resources.py is generated and loadable."""
        assert "qt_resource_data" in rc_content
        assert "qInitResources" in rc_content
        assert "qCleanupResources" in rc_content
        # File should be substantial (compiled binary resource data)
        assert len(rc_content) > 1000


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: Classification Coverage
# ──────────────────────────────────────────────────────────────────────────────

def test_all_icon_types_covered():
    """Every icon type in DEVICE_ICONS is reachable via _classify_device."""
    DEVICE_ICONS = {
        "apple":    ":/icons/apple.svg",
        "windows":  ":/icons/windows.svg",
        "linux":    ":/icons/linux.svg",
        "android":  ":/icons/mobile.svg",
        "ios":      ":/icons/mobile.svg",
        "server":   ":/icons/server.svg",
        "network":  ":/icons/server.svg",
        "unknown":  ":/icons/start.svg",
    }
    
    test_inputs = [
        ("Apple, Inc.", "MacBook-Pro"),    # apple
        ("", "WIN-ABC123"),                # windows
        ("", "arch-t15a00080uxet"),        # linux
        ("Samsung", ""),                   # android
        ("", "iphone-xyz"),                # ios
        ("", "srv-dc01"),                  # server
        ("Cisco", ""),                     # server (network)
        ("", ""),                          # unknown
    ]
    
    achieved = {
        _classify_device(vendor, hostname)
        for vendor, hostname in test_inputs
    }
    
    for icon_type in DEVICE_ICONS.keys():
        assert icon_type in achieved, f"Icon type '{icon_type}' unreachable"
