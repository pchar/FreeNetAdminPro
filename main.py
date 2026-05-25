"""
FreeNetAdminPro — main application window.

Wires the Qt UI to the async MCP client:
  - pushButton_mcp toggles connection using the URL from lineEdit_mcp
  - icon toggles: green connected / red not_connected
  - all MCP calls logged to textEdit
  - scan_network called via worker thread, results streamed back via signals
"""

import sys
import asyncio
import logging
import json
import ipaddress
from datetime import datetime

from typing import Optional
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem
from PySide6.QtCore import QObject, Signal, QThread, Slot, Qt
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtSvg import QSvgRenderer  # ensure SVG renderer plugin is loaded

from ui_form import Ui_MainWindow
from mcp_handler import MCPClient


# ────────────────────────────────────────────────────────────────────────────
# Custom table items with semantic sorting
# ────────────────────────────────────────────────────────────────────────────

class IPTableWidgetItem(QTableWidgetItem):
    """TableWidgetItem that sorts IPv4 addresses numerically, not lexicographically.

    "10.0.0.1" < "192.168.1.1" (correct numeric comparison)
    vs string compare: "10..." < "192..." (wrong — but actually same here)
    Better example: "9.0.0.1" < "10.0.0.1" (numeric) vs "10..." < "9..." (string)
    """

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setData(Qt.UserRole, self._ip_to_num(text))

    @staticmethod
    def _ip_to_num(ip: str) -> int:
        try:
            return int(ipaddress.ip_address(ip))
        except (ValueError, TypeError, ipaddress.AddressValueError):
            return -1  # non-IP addresses sort first (before valid ones)

    def __lt__(self, other):
        # Guard: if other is not an IPTableWidgetItem, fall back to string compare
        if not isinstance(other, IPTableWidgetItem):
            return super().__lt__(other)
        
        self_num = self.data(Qt.UserRole)
        other_num = other.data(Qt.UserRole)
        
        # Handle None values (shouldn't happen, but guard against it)
        if self_num is None or other_num is None:
            return super().__lt__(other)
        
        if self_num != -1 and other_num != -1:
            # Both are valid IPs → numeric comparison
            return self_num < other_num
        if self_num == -1 and other_num == -1:
            # Both are non-IPs → string comparison
            return super().__lt__(other)
        # Valid IPs always sort before non-IPs
        return self_num != -1


class MacTableWidgetItem(QTableWidgetItem):
    """TableWidgetItem that sorts MAC addresses consistently."""

    @staticmethod
    def _mac_to_key(mac: str) -> str:
        try:
            return mac.replace(":", "").replace("-", "").upper()
        except Exception:
            return str(mac)

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setData(Qt.UserRole, self._mac_to_key(text))

    def __lt__(self, other):
        return self.data(Qt.UserRole) < other.data(Qt.UserRole)


# ────────────────────────────────────────────────────────────────────────────
# Device classification — infer device type from vendor + hostname
# ────────────────────────────────────────────────────────────────────────────

# Icon paths mapped to device type keys
DEVICE_ICONS = {
    "apple":     ":/icons/apple.svg",
    "windows":   ":/icons/windows.svg",
    "linux":     ":/icons/linux.svg",
    "android":   ":/icons/mobile.svg",
    "ios":       ":/icons/mobile.svg",
    "server":    ":/icons/server.svg",
    "network":   ":/icons/server.svg",  # router/switch → server icon
    "unknown":   ":/icons/start.svg",   # default device icon
}

# Known manufacturers that imply Linux/server
LINUX_VENDORS = [
    "raspberry pi", "beagleboard", "rockchip", "allwinner", "nvidia",
    "amazon", "google", "arm",
    "microsemi", "altera", "xilinx", "intel corporation", "amd",
    "super micro", "dell", "hpe", "hp inc", "lenovo", "ibm",
    "netapp", "synology", "qnap", "asustor", "buffalo technology",
    "ubiquiti", "cisco", "juniper networks", "arista networks",
    "mikrotik", "fortinet", "palo alto", "checkpoint",
    "citrix", "vmware", "proxmox",
]

# Known manufacturers that imply Apple/IOS/MacOS
APPLE_VENDORS = [
    "apple", "airpod", "airtag",
]

# Known hostname patterns
WINDOWS_PATTERNS = ["win-", "win_", "desktop-", "desktop_"]
SERVER_PATTERNS = ["srv", "server", "nas", "storage", "db-", "db_", "slave"]
IOS_PATTERNS = ["iphone", "ipad", "ipod", "macbook", "imac", "mac mini"]

# IoT/home devices - these often have vendor='Unknown' but identifiable hostnames
IOT_VENDORS = ["bosch", "siemens", "miele", "viessmann", "netatmo", "ezviz", "ring", "nest", "tplink", "kasa", "sonoff"]


def classify_device(vendor: str, hostname: str) -> str:
    """Classify device type and return icon key.
    
    Uses vendor name and hostname to infer device type.
    Returns one of: 'apple', 'windows', 'linux', 'android', 'ios',
                    'server', 'network', 'unknown'
    """
    vendor_lower = (vendor or "").lower()
    host_lower = (hostname or "").lower()

    # Debug: log classification inputs only for unknown matches or first pass
    _classification_count = getattr(classify_device, '_count', 0) + 1
    classify_device._count = _classification_count
    if _classification_count <= 1:
        _debug_log(f"[classify_device] Starting classification ({vendor!r}, {hostname!r})")

    # 1. Check for Apple products (vendor-based, highest priority)
    for kw in APPLE_VENDORS:
        if kw in vendor_lower:
            result = "apple"
            _debug_log(f"[classify_device] ✓ Apple vendor match: '{kw}' in vendor")
            return result

    # 2. Check hostname for Apple devices
    for kw in IOS_PATTERNS:
        if kw in host_lower:
            result = "ios"
            _debug_log(f"[classify_device] ✓ iOS hostname match: '{kw}' in hostname")
            return result

    # 3. Check hostname for Windows devices
    for kw in WINDOWS_PATTERNS:
        if kw in host_lower:
            result = "windows"
            _debug_log(f"[classify_device] ✓ Windows hostname match: '{kw}' in hostname")
            return result

    # 4. Check hostname for Linux servers
    for kw in SERVER_PATTERNS:
        if kw in host_lower:
            result = "server"
            _debug_log(f"[classify_device] ✓ Server hostname match: '{kw}' in hostname")
            return result

    # 5. Check vendor for known Linux/Server hardware
    for kw in LINUX_VENDORS:
        if kw in vendor_lower:
            # Server manufacturers → server icon
            if any(s in vendor_lower for s in ["dell", "hpe", "hp inc", "lenovo", "ibm", "super micro", "raspberry pi"]):
                result = "server"
                _debug_log(f"[classify_device] ✓ Server vendor match: '{kw}' in vendor")
                return result
            # Network equipment
            if any(n in vendor_lower for n in ["cisco", "juniper", "arista", "mikrotik", "ubiquiti", "fortinet"]):
                result = "network"
                _debug_log(f"[classify_device] ✓ Network vendor match: '{kw}' in vendor")
                return result
            # Otherwise regular Linux device
            result = "linux"
            _debug_log(f"[classify_device] ✓ Linux vendor match: '{kw}' in vendor")
            return result

    # 6. IoT/home devices - often have vendor='Unknown' but identifiable hostnames
    iot_patterns = [
        # Smart home brands
        "bosch", "siemens", "miele", "viessmann", "netatmo",
        "ring", "nest", "tplink", "kasa", "sonoff", "tuya",
        "philips hue", "wemo", "ecobee", "honeywell", "ecobee",
        # IoT camera/sensor brands
        "ezviz", "ring", "blink", "arlo", "annke", "reolink",
        # Smart appliances
        "dishwasher", "washing", "fridge", "oven", "oven-",
        # Router/accessory brands
        "gl-mt", "airlock", "airrouter", "nighthawk", "orbi",
        # Generic IoT patterns
        "smart", "iot-", "sensor",
    ]
    for kw in iot_patterns:
        if kw in host_lower:
            result = "server"  # IoT devices share server icon
            _debug_log(f"[classify_device] ✓ IoT hostname match: '{kw}' in hostname")
            return result

    # 7. Linux workstations/servers with vendor='Unknown' - common hostname patterns
    #    Many Linux systems don't report vendor, but hostnames reveal them
    linux_patterns = [
        # Distribution identifiers
        "arch", "gentoo", "fedora", "ubuntu", "debian", "centos", "rhel", "opensuse",
        "kali", "parrot", "raspbian", "pi-hole", "omv", "openmediavault",
        # Common server names
        "master", "slave", "node", "worker", "cluster", "compute",
        # Greek/mythology names (common for Linux workstations)
        "castor", "pollux", "venus", "sun", "eris", "pluto", "ceres", "juno",
        "dione", "tethys", "hebe", "iris", "helene", "calypso", "enceladus",
        "charon", "nereid", "thetis", "triton", "orion", "ursa", "lyra", "cygnus",
        # Lab/scientific naming
        "cicladi", "chiara", "dione", "eris",
        # 3D printers, embedded Linux
        "ultimaker", "prusa", "creality", "rswave", "rsmat", "raspberry",
        # Network interface names in hostname
        "wlan0", "eth0", "enp", "eno",
        # Generic Linux workstation patterns
        "workstation", "dev-", "staging-", "prod-", "jenkins", "gitlab",
    ]
    for kw in linux_patterns:
        if kw in host_lower:
            result = "linux"
            _debug_log(f"[classify_device] ✓ Linux hostname match: '{kw}' in hostname")
            return result

    # 8. Mobile devices often have vendor names like "Apple", "Samsung", etc.
    #    Check mobile vendor patterns (fallback)
    mobile_vendors = ["samsung", "huawei", "xiaomi", "oppo", "vivo", "oneplus", "nokia", "lg electronics"]
    for kw in mobile_vendors:
        if kw in vendor_lower:
            result = "android"
            _debug_log(f"[classify_device] ✓ Android vendor match: '{kw}' in vendor")
            return result

    # 9. Default — assume generic network device
    _debug_log("[classify_device] ⚠ No match — defaulting to 'unknown'")
    return "unknown"


def _debug_log(msg: str):
    """Log a debug message to stdout (will appear in console during dev)."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ────────────────────────────────────────────────────────────────────────────
# Async worker — runs on a dedicated thread so the GUI never freezes
# ────────────────────────────────────────────────────────────────────────────

class MCPWorker(QObject):
    """Background worker that owns the async event loop and MCPClient."""

    # Signals to push results back to the main (GUI) thread
    log_signal = Signal(str)
    status_signal = Signal(bool, str)  # connected, message
    result_signal = Signal(dict)       # parsed MCP tool result (legacy, kept for compatibility)
    device_signal = Signal(int, dict)  # emitted for each device: row index + device dict
    scan_complete_signal = Signal(int)  # emitted when scan finishes: device count
    scan_started_signal = Signal()  # emitted when scan begins

    def __init__(self, base_url: str):
        super().__init__()
        self._base_url = base_url
        self._client: Optional[MCPClient] = None
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Connection ──────────────────────────────────────────────────────

    @Slot()
    def connect(self):
        self._log(f"[MCP] Connecting to {self._base_url} ...")
        result = self._run_sync(self._do_connect())
        if result:
            self._connected = True
            self.status_signal.emit(True, "Connected to MCP server")
            self._log("[MCP] ✓ Connected")
        else:
            self._connected = False
            self.status_signal.emit(False, "Connection failed")
            self._log("[MCP] ✗ Connection failed")

    @Slot()
    def disconnect(self):
        self._log("[MCP] Disconnecting ...")
        if self._client:
            self._run_sync(self._do_disconnect())
        self._connected = False
        self.status_signal.emit(False, "Disconnected")
        self._log("[MCP] ✓ Disconnected")

    # ── MCP tool calls ──────────────────────────────────────────────────

    @Slot()
    def scan_network(self):
        """Scan the configured cluster subnet.

        PyQt5 pattern: emit device_signal(row, dev) per device, then
        scan_complete_signal(count) — keeps the event loop alive so the
        GUI never freezes.
        """
        if not self._client:
            self._log("[MCP] ✗ scan_network — not connected")
            self.status_signal.emit(False, "Not connected — cannot scan")
            return

        self._log("[MCP] → scan_network starting")
        self.status_signal.emit(True, "Scanning network...")
        self.scan_started_signal.emit()

        # Call MCP tool
        result = self._run_sync(self._client._call_tool(
            "scan_network", {"subnet": "", "resolve_names": True}
        ))
        result["method_name"] = "scan_network"

        ok = result.get("success", False)
        if not ok:
            err = result.get("error", "unknown error")
            self._log(f"[MCP] ← scan_network failed: {err}")
            self.status_signal.emit(False, f"Scan failed: {err}")
            self.result_signal.emit(result)  # still emit for legacy handlers
            return

        self._log(f"[MCP] ← scan_network OK — parsing {len(result.get('devices', []))} devices")

        devices = result.get("devices", [])
        total = len(devices)

        # Emit per-device signals (Qt event loop processes each between iterations)
        for row, dev in enumerate(devices):
            self.device_signal.emit(row, dev)

        # Signal completion
        self.scan_complete_signal.emit(total)
        self.status_signal.emit(True, f"Scan complete: {total} devices")
        self._log(f"[MCP] ✓ scan_network complete: {total} devices")

        # Also emit legacy result_signal for backwards compatibility
        self.result_signal.emit(result)

    @Slot()
    def get_scanner_status(self):
        self._call("get_scanner_status", {})

    @Slot()
    def get_network_topology(self):
        self._call("get_network_topology", {})

    @Slot()
    def get_cluster_nodes(self):
        self._call("get_cluster_nodes", {})

    @Slot()
    def discover_services(self):
        self._call("discover_services", {})

    @Slot()
    def get_unknown_devices(self):
        self._call("get_unknown_devices", {})

    @Slot()
    def get_device_info(self, identifier: str):
        self._call("get_device_info", {"identifier": identifier})

    @Slot()
    def get_device_history(self, mac: str):
        self._call("get_device_history", {"mac": mac})

    @Slot()
    def mark_device_known(self, mac: str, label: str, dtype: str = "trusted"):
        self._call("mark_device_known", {"mac": mac, "label": label, "device_type": dtype})

    @Slot()
    def remove_device_known(self, mac: str):
        self._call("remove_device_known", {"mac": mac})

    @Slot()
    def ping_device(self, target: str):
        self._call("ping_device", {"target": target, "count": 3})

    @Slot()
    def resolve_hostname(self, target: str):
        self._call("resolve_device_hostname", {"target": target})

    @Slot()
    def discover_network(self):
        """Scan the cluster subnet (alias for scan_network).

        Delegate to scan_network() so the signal-per-item pattern
        (device_signal / scan_complete_signal / scan_started_signal)
        is followed.  _call() only emits result_signal — that's for
        legacy non-scan tools and does NOT populate the table.
        """
        self._log("[MCP] discover_network → forwarding to scan_network")
        if not self._client:
            self._log("[MCP] ✗ discover_network - no client")
            self.status_signal.emit(False, "No MCP client")
            self.result_signal.emit({
                "success": False, "error": "No MCP client",
                "method_name": "discover_network"
            })
            return
        # Reuse scan_network() which has the full signal-per-item pipeline
        self.scan_network()

    @Slot()
    def scan_device_ports(self, target: str):
        self._call("scan_device_ports", {"target": target, "quick": True})

    # ── Internal helpers ────────────────────────────────────────────────

    def _run_sync(self, coro):
        """Run an async coroutine on this worker's event loop."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop.run_until_complete(coro)

    async def _do_connect(self) -> bool:
        self._client = MCPClient(self._base_url)
        ok = await self._client.connect()
        return ok

    async def _do_disconnect(self):
        if self._client:
            await self._client.disconnect()
            self._client = None

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_signal.emit(f"[{ts}] {msg}")

    def _call(self, method_name: str, params: dict):
        """Helper: log the call, await the result, log the result, re-emit status."""
        if not self._client:
            self._log(f"[MCP] ✗ {method_name} — not connected")
            self.status_signal.emit(False, "Not connected — cannot call tools")
            self.result_signal.emit({
                "success": False, "error": "Not connected",
                "method_name": method_name
            })
            return

        self._log(f"[MCP] → {method_name}({params})")
        result = self._run_sync(self._client._call_tool(method_name, params))

        ok = result.get("success", False)
        if ok:
            self._log(f"[MCP] ← {method_name} OK")
            self.status_signal.emit(True, f"{method_name}: success")
        else:
            err = result.get("error", "unknown error")
            self._log(f"[MCP] ← {method_name} failed: {err}")
            self.status_signal.emit(False, f"{method_name}: {err}")

        # Always emit the parsed result so the main thread can display it
        result["method_name"] = method_name
        self.result_signal.emit(result)


# ────────────────────────────────────────────────────────────────────────────
# Main window
# ────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow, Ui_MainWindow):
    """Application main window."""

    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # ── Wire UI controls ────────────────────────────────────────────
        self.pushButton_mcp.clicked.connect(self._on_mcp_button)
        self.pushButton_mcp.setCheckable(True)
        self.pushButton_mcp.setChecked(False)
        self.pushButton_mcp.setText("Connect")
        self.pushButton_discover.clicked.connect(self._on_discover_button)
        self.pushButton_discover.setEnabled(False)  # disabled until connected

        # ── Enable column sorting ───────────────────────────────────────
        self.tableWidgetHost.setSortingEnabled(False)  # turn off during batch update
        self.tableWidgetHost.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        self.tableWidgetHost.horizontalHeader().setSortIndicatorShown(True)
        self.tableWidgetHost.setSortingEnabled(True)

        # ── Scan-in-progress state ──────────────────────────────────────
        self._is_scanning = False

        # ── PyQt5 signal-per-item scan state ────────────────────────────
        # When the worker emits device_signal(row, dev), the main thread
        # builds the table row-by-row.  _scan_preloaded holds the icon
        # cache keyed by resource path so every device signal can reuse it.
        self._icon_cache: dict[str, QIcon] = {}
        self._scan_rows_ready = 0          # rows inserted so far this scan
        self._scan_total_devices = 0       # total devices from worker
        self._scan_devices_used: set[str] = set()  # icon paths actually used
        self._scan_devices_classified: list[str] = []  # for debug summary

        # ── Worker thread + background worker ───────────────────────────
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[MCPWorker] = None

        self._set_status_icon(False)
        self._append_log("[System] FreeNetAdminPro started")
        self._append_log("[System] Click 'connect' on the MCP button to start")

    def _ensure_thread(self):
        """Create or return the worker thread.

        QThread cannot be reused after finish(), so we create a fresh one
        each time the user connects (after a prior disconnect).
        """
        if self._worker_thread is None or not self._worker_thread.isRunning():
            if self._worker_thread is not None:
                self._worker_thread.quit()
                self._worker_thread.wait()
                self._worker_thread.deleteLater()
            self._worker_thread = QThread()
        return self._worker_thread

    def _on_mcp_button(self):
        """Toggle connect / disconnect when pushButton_mcp is clicked."""
        if self.pushButton_mcp.isChecked():
            # → Connect
            url = self.lineEdit_mcp.text().strip()
            if not url:
                self._append_log("[UI] ✗ MCP URL is empty")
                self.pushButton_mcp.setChecked(False)
                self._set_status_icon(False)
                self.pushButton_mcp.setText("Connect")
                return

            self.pushButton_mcp.setText("Disconnect")
            self._append_log(f"[UI] Connect requested → {url}")

            # Destroy previous worker and create a new one
            self._cleanup_worker()
            thread = self._ensure_thread()
            self._worker = MCPWorker(url)
            self._worker.moveToThread(thread)

            # Wire signals
            self._worker.log_signal.connect(self._append_log)
            self._worker.status_signal.connect(self._on_worker_status)
            self._worker.result_signal.connect(self._on_worker_result)
            self._worker.device_signal.connect(self._on_device_received)
            self._worker.scan_complete_signal.connect(self._on_scan_complete)
            self._worker.scan_started_signal.connect(self._on_scan_started)

            # Start the thread and fire connect
            assert thread is not None
            thread.start()
            self._worker.connect()
        else:
            # → Disconnect
            self.pushButton_mcp.setText("Connect")
            self._append_log("[UI] Disconnect requested")
            if self._worker:
                self._worker.disconnect()
            else:
                self._append_log("[UI] ✗ Not connected")
                self.pushButton_mcp.setChecked(True)
                self.pushButton_mcp.setText("Disconnect")
            self._cleanup_worker()
            if self._worker_thread is not None and self._worker_thread.isRunning():
                self._worker_thread.quit()
                self._worker_thread.wait()

    @Slot(bool, str)
    def _on_worker_status(self, connected: bool, message: str):
        """Handle status updates from the worker thread."""
        self._set_status_icon(connected)
        self.pushButton_mcp.setChecked(connected)
        self.pushButton_mcp.setText("Disconnect" if connected else "Connect")
        self.pushButton_discover.setEnabled(connected)
        self.statusbar.showMessage(message, 5000)

    # ── PyQt5 signal-per-item slots (like the example) ──────────────────
    # The worker emits device_signal(row, dev) per device — each signal
    # goes through Qt's event loop so the GUI stays responsive between
    # row insertions, exactly like the PyQt5 QThread example.

    @Slot()
    def _on_scan_started(self):
        """Handle scan start — disable button, show status, clear old rows."""
        self._is_scanning = True
        self.pushButton_discover.setEnabled(False)
        self.statusbar.showMessage("Scanning network...", 0)
        self._append_log("[UI] Scan started — results will appear as rows")

    @Slot(dict)
    def _on_worker_result(self, result: dict):
        """Legacy handler — kept for non-scan tools (info, ports, etc.)."""
        method_name = result.get("method_name", "")
        self._append_log(f"[UI] Received result: {method_name} -> "
                         f"{list(result.keys()) if isinstance(result, dict) else type(result)}")
        # scan_network is now handled by device_signal / scan_complete_signal

    @Slot(int, dict)
    def _on_device_received(self, row: int, dev: dict):
        """Handle ONE device from the worker — like the PyQt5 some_function.

        Called on the MAIN thread via a queued signal.  The first call
        preloads the icons (outside the table loop), then every call
        inserts exactly one row.  Qt's event loop runs between signals
        so the UI never blocks.
        """
        # ── First call: preload icons & prepare table ─────────────────
        if row == 0 and self._scan_rows_ready == 0:
            self._scan_devices_used.clear()
            self._scan_devices_classified.clear()
            self._scan_rows_ready = 0
            self._scan_total_devices = 0
            self._icon_cache.clear()

            self._append_log("[UI] Preloading icons...")
            for dtype, icon_path in DEVICE_ICONS.items():
                pm = QPixmap(icon_path)
                if pm.isNull():
                    _debug_log(f"[icon] ✗ FAILED to load {icon_path} ({dtype})")
                    self._append_log(f"[UI] ✗ Icon FAILED: {icon_path}")
                else:
                    self._icon_cache[icon_path] = QIcon(pm)
                    _debug_log(f"[icon] ✓ Loaded {icon_path}")
                    self._append_log(f"[UI] ✓ Icon loaded: {icon_path}")

            _debug_log(f"[icon] Preloaded {len(self._icon_cache)} icons")
            self._append_log(f"[UI] Preloaded {len(self._icon_cache)} icons")

            # Clear table & freeze updates
            self.tableWidgetHost.setSortingEnabled(False)
            self.tableWidgetHost.setUpdatesEnabled(False)
            self.tableWidgetHost.setRowCount(0)
            self._append_log(f"[UI] Parsing scan result: ready for devices")

        # ── Debug: print device dict ──────────────────────────────────
        self._append_log(f"[SCAN] Row {row} device dict:")
        self._append_log(f"     {json.dumps(dev, indent=6)}")

        # ── Insert ONE row (main thread, non-blocking) ────────────────
        self.tableWidgetHost.insertRow(row)

        # Col 0: Status ●
        _debug_log("[col 0] Status → ●")
        it = QTableWidgetItem("●")
        it.setForeground(Qt.GlobalColor.darkGreen)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 0, it)
        _debug_log("[col 0] DONE")

        # Col 1: device icon
        vendor = dev.get("vendor", "") or ""
        hostname = dev.get("hostname") or ""
        _debug_log(f"[col 1] vendor='{vendor}', hostname='{hostname}'")
        dtype = classify_device(vendor, hostname)
        icon_path = DEVICE_ICONS.get(dtype, DEVICE_ICONS["unknown"])
        self._scan_devices_used.add(icon_path)
        self._scan_devices_classified.append(dtype)
        _debug_log(f"[col 1] classified → {dtype}, icon={icon_path}")
        it = QTableWidgetItem()
        it.setIcon(self._icon_cache.get(icon_path, self._icon_cache.get(DEVICE_ICONS["unknown"])))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 1, it)
        _debug_log("[col 1] DONE")

        # Col 2: name
        name = dev.get("hostname") or dev.get("mac") or "Unknown"
        _debug_log(f"[col 2] name → '{name}'")
        it = QTableWidgetItem(name)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 2, it)
        _debug_log("[col 2] DONE")

        # Col 3: IPv4
        ip_val = dev.get("ip", "N/A")
        _debug_log(f"[col 3] ip → '{ip_val}'")
        it = IPTableWidgetItem(str(ip_val))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 3, it)
        _debug_log("[col 3] DONE")

        # Col 4: Ping
        _debug_log("[col 4] ping → 'N/A' (placeholder)")
        it = QTableWidgetItem("N/A")
        it.setForeground(Qt.GlobalColor.gray)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 4, it)
        _debug_log("[col 4] DONE")

        # Col 5: MAC
        mac_val = dev.get("mac", "N/A")
        _debug_log(f"[col 5] mac → '{mac_val}' (type={type(mac_val).__name__})")
        it = QTableWidgetItem(str(mac_val))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 5, it)
        _debug_log("[col 5] DONE")

        # Col 6: Vendor
        vendor_val = dev.get("vendor", "Unknown")
        _debug_log(f"[col 6] vendor → '{vendor_val}'")
        it = QTableWidgetItem(str(vendor_val))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 6, it)
        _debug_log("[col 6] DONE")

        _debug_log(f"[row {row}] ████████████████ COMPLETE ████████████████")

        self._scan_rows_ready += 1

    @Slot(int)
    def _on_scan_complete(self, total: int):
        """Handle scan completion — re-enable sorting, unpaint, show summary.

        Called on the main thread after all device_signal emissions.
        """
        self._scan_total_devices = total
        self._append_log(f"[UI] Populated table with {total} devices")
        self.statusbar.showMessage(f"Discovered {total} devices", 5000)

        # Debug summary
        self._append_log(f"[UI] 🔍 Icon cache: {len(self._icon_cache)} loaded")
        self._append_log(f"[UI] 🔍 Icons used by devices: {self._scan_devices_used}")

        unused = set(DEVICE_ICONS.keys()) - set(self._scan_devices_classified)
        if unused:
            self._append_log(f"[UI] ⚠ Icon types never triggered: {unused}")
            self._append_log("[UI]   → Run 'python -m pytest tests/ -v' to verify all icons load")

        # Re-enable sorting and painting
        self.tableWidgetHost.setSortingEnabled(True)
        self.tableWidgetHost.setUpdatesEnabled(True)
        self.tableWidgetHost.repaint()

        # Clear scanning state — re-enable discover button
        self._is_scanning = False
        self.pushButton_discover.setEnabled(True)

    def _on_discover_button(self):
        """Handle discover button click — starts a non-blocking scan."""
        if not self._worker or not self.pushButton_discover.isEnabled():
            return

        # Mark scanning, disable button, show status in statusbar
        self._is_scanning = True
        self.pushButton_discover.setEnabled(False)
        self.statusbar.showMessage("Scanning network...", 0)
        self._append_log("[UI] Scan started — results will appear as rows")
        self._worker.discover_network()

    def _set_status_icon(self, connected: bool):
        """Toggle the MCP status icon label."""
        if connected:
            self.label_mcp_status.setPixmap(QPixmap(":/icons/connected.svg"))
        else:
            self.label_mcp_status.setPixmap(QPixmap(":/icons/not_connected.svg"))

    def _append_log(self, msg: str):
        """Append a line to the debug textEdit."""
        self.textEdit.append(msg)

    def _cleanup_worker(self):
        """Destroy the current worker and reset reference."""
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def closeEvent(self, event):
        """Clean up on exit — stop thread and worker gracefully.

        Order: disconnect signals → disconnect MCP session → delete worker
        → flush deleteLater events → quit thread → wait.

        Critical: deleteLater() posts an event to the worker's thread.
        If we quit the thread before that event fires, Qt may try to
        reparent the still-alive QObject to a different thread during
        QApplication destruction, producing:
            QObject::setParent: Cannot set parent, new parent is in a
            different thread
        The fix is to quit the event loop first, then process pending
        events (including deleteLater), then delete the worker object.
        """
        self._append_log("[UI] Shutting down...")

        if self._worker is not None or self._worker_thread is not None:
            # ── 1. Disconnect all signal connections to prevent
            # │    cross-thread signal delivery after thread quits ─────
            if self._worker is not None:
                self._worker.log_signal.disconnect()
                self._worker.status_signal.disconnect()
                self._worker.result_signal.disconnect()
                self._worker.device_signal.disconnect()
                self._worker.scan_complete_signal.disconnect()
                self._worker.scan_started_signal.disconnect()

            # ── 2. Disconnect the MCP aiohttp session ────────────────
            if self._worker is not None:
                self._append_log("[UI] Disconnecting MCP session...")
                try:
                    self._worker.disconnect()
                except RuntimeError as e:
                    # A scan is mid-flight — event loop is busy.
                    # Force-close the aiohttp session on the worker's own loop.
                    self._append_log(f"[UI] Scan in progress, force-closing: {e}")
                    if self._worker._client and self._worker._client._session:
                        session = self._worker._client._session
                        self._worker._client._session = None
                        self._worker._connected = False
                        # Use the worker's loop, not the main thread's loop
                        loop = self._worker._loop
                        if loop and not loop.is_closed():
                            loop.call_soon_threadsafe(
                                lambda: asyncio.ensure_future(session.close())
                            )

            # ── 3. Schedule worker deletion ──────────────────────────
            worker_to_delete = self._worker
            self._worker = None

            # ── 4. Quit the thread's event loop ─────────────────────
            if self._worker_thread is not None and self._worker_thread.isRunning():
                self._append_log("[UI] Quitting worker thread...")
                self._worker_thread.quit()

                # ── 5. Pump the thread's event loop so deleteLater
                # │    events fire and objects are actually destroyed
                # │    BEFORE we proceed to QApplication teardown. ────
                #    We run a tiny nested event loop on the main thread
                #    that waits for the worker thread to finish.
                #    The worker thread processes its own events (including
                #    deleteLater for worker_to_delete) as it drains.
                if not self._worker_thread.wait(3000):
                    self._append_log("[UI] WARNING: Thread did not quit in time")

                self._worker_thread = None

            # ── 6. Now safe to delete the worker object ────────────
            if worker_to_delete is not None:
                worker_to_delete.deleteLater()

        self._append_log("[UI] Shutdown complete")
        event.accept()


# ────────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
