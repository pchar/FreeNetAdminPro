"""
FreeNetAdminPro — main application window.

Wires the Qt UI to the async MCP client:
  - pushButton_mcp toggles connection using the URL from lineEdit_mcp
  - icon toggles: green connected / red not_connected
  - all MCP calls logged to textEdit
  - scan_network called via worker thread, results streamed back via signals

Logging uses logger.py — 3 levels:
  INFO   — high-level phase descriptions
  DEBUG  — deep traces with input/output parameters
  TRACE  — every instruction line-by-line
"""

import sys
import asyncio
import json
import ipaddress
import threading
from typing import Optional
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidgetItem
from PySide6.QtCore import QObject, Signal, QThread, Slot, Qt
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtSvg import QSvgRenderer

from ui_form import Ui_MainWindow
from mcp_handler import MCPClient
from logger import get_logger, set_thread_nick

gui_log = get_logger("GUI")



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


class _classify_logger:
    """Logger instance scoped to classify_device — avoids reimport."""
    inst = None

    @classmethod
    def get(cls):
        if cls.inst is None:
            cls.inst = get_logger("main.classify_device")
        return cls.inst


def classify_device(vendor: str, hostname: str) -> str:
    """Classify device type and return icon key.

    Uses vendor name and hostname to infer device type.
    Returns one of: 'apple', 'windows', 'linux', 'android', 'ios',
                    'server', 'network', 'unknown'
    """
    vendor_lower = (vendor or "").lower()
    host_lower = (hostname or "").lower()
    log = _classify_logger.get()

    # 1. Check for Apple products (vendor-based, highest priority)
    log.trace("classify: checking APPLE_VENDORS …")
    for kw in APPLE_VENDORS:
        if kw in vendor_lower:
            log.debug("Apple vendor match: '%s' in vendor=%r", kw, vendor)
            return "apple"

    # 2. Check hostname for Apple devices
    log.trace("classify: checking IOS_PATTERNS in hostname …")
    for kw in IOS_PATTERNS:
        if kw in host_lower:
            log.debug("iOS hostname match: '%s' in host=%r", kw, hostname)
            return "ios"

    # 3. Check hostname for Windows devices
    log.trace("classify: checking WINDOWS_PATTERNS in hostname …")
    for kw in WINDOWS_PATTERNS:
        if kw in host_lower:
            log.debug("Windows hostname match: '%s' in host=%r", kw, hostname)
            return "windows"

    # 4. Check hostname for Linux servers
    log.trace("classify: checking SERVER_PATTERNS in hostname …")
    for kw in SERVER_PATTERNS:
        if kw in host_lower:
            log.debug("Server hostname match: '%s' in host=%r", kw, hostname)
            return "server"

    # 5. Check vendor for known Linux/Server hardware
    log.trace("classify: checking LINUX_VENDORS in vendor …")
    for kw in LINUX_VENDORS:
        if kw in vendor_lower:
            # Server manufacturers -> server icon
            if any(s in vendor_lower for s in ["dell", "hpe", "hp inc", "lenovo", "ibm", "super micro", "raspberry pi"]):
                log.debug("Server vendor match: '%s' in vendor=%r", kw, vendor)
                return "server"
            # Network equipment
            if any(n in vendor_lower for n in ["cisco", "juniper", "arista", "mikrotik", "ubiquiti", "fortinet"]):
                log.debug("Network vendor match: '%s' in vendor=%r", kw, vendor)
                return "network"
            # Otherwise regular Linux device
            log.debug("Linux vendor match: '%s' in vendor=%r", kw, vendor)
            return "linux"

    # 6. IoT/home devices - often have vendor='Unknown' but identifiable hostnames
    log.trace("classify: checking IOT patterns in hostname …")
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
            log.debug("IoT hostname match: '%s' in host=%r", kw, hostname)
            return "server"  # IoT devices share server icon

    # 7. Linux workstations/servers with vendor='Unknown'
    log.trace("classify: checking LINUX patterns in hostname …")
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
            log.debug("Linux hostname match: '%s' in host=%r", kw, hostname)
            return "linux"

    # 8. Mobile devices
    log.trace("classify: checking MOBILE_VENDORS in vendor …")
    mobile_vendors = ["samsung", "huawei", "xiaomi", "oppo", "vivo", "oneplus", "nokia", "lg electronics"]
    for kw in mobile_vendors:
        if kw in vendor_lower:
            log.debug("Android vendor match: '%s' in vendor=%r", kw, vendor)
            return "android"

    # 9. Default
    log.debug("No match -> defaulting to 'unknown' (vendor=%r, host=%r)", vendor, hostname)
    return "unknown"


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
        self._scan_in_progress = False

        # Per-instance logger with thread nick
        self._log = get_logger("MCPWorker")

    def _get_nick(self) -> str:
        """Return a short identifier for this thread."""
        return str(threading.current_thread().ident)[-4:] if threading.current_thread().ident else "???"

    # ── Connection ──────────────────────────────────────────────────────

    @Slot()
    def connect(self):
        nick = self._get_nick()
        set_thread_nick(f"Worker/{nick}")
        self._log.info("Connecting to %s", self._base_url)
        self._log.trace("connect: creating MCPClient(session=%r)", self._base_url)
        result = self._run_sync(self._do_connect())
        if result:
            self._connected = True
            self.status_signal.emit(True, "Connected to MCP server")
            self._log.info("Connected")
            self._log.trace("connect: _connected=True, status_signal emitted")
        else:
            self._connected = False
            self.status_signal.emit(False, "Connection failed")
            self._log.info("Connection failed")
            self._log.trace("connect: _connected=False, status_signal emitted")

    @Slot()
    def disconnect(self):
        self._log.info("Disconnecting")
        self._log.trace("disconnect: calling _do_disconnect()")
        if self._client:
            self._run_sync(self._do_disconnect())
        self._connected = False
        self.status_signal.emit(False, "Disconnected")
        self._log.info("Disconnected")
        self._log.trace("disconnect: _connected=False, status_signal emitted")

    # ── MCP tool calls ──────────────────────────────────────────────────

    @Slot()
    def scan_network(self):
        """Scan the configured cluster subnet.

        PyQt5 pattern: emit device_signal(row, dev) per device, then
        scan_complete_signal(count) — keeps the event loop alive so the
        GUI never freezes.
        """
        self._log.trace("scan_network: entry")
        if self._scan_in_progress:
            self._log.info("scan_network aborted — scan already in progress")
            self._log.trace("scan_network: _scan_in_progress=True, returning")
            return

        if not self._client:
            self._log.info("scan_network aborted — not connected")
            self._log.trace("scan_network: _client is None")
            self.status_signal.emit(False, "Not connected — cannot scan")
            return

        self._scan_in_progress = True
        self._log.info("scan_network starting")
        self._log.trace("scan_network: _scan_in_progress=True")
        self.status_signal.emit(True, "Scanning network...")
        self.scan_started_signal.emit()

        try:
            # Call MCP tool
            params = {"subnet": "", "resolve_names": True}
            self._log.debug("scan_network: calling _call_tool(tool=scan_network, params=%s)", params)
            self._log.trace("scan_network: _run_sync(_call_tool(...))")
            result = self._run_sync(self._client._call_tool(
                "scan_network", params
            ))
            self._log.debug("scan_network: got result keys=%s", list(result.keys()))
            result["method_name"] = "scan_network"

            ok = result.get("success", False)
            if not ok:
                err = result.get("error", "unknown error")
                self._log.info("scan_network failed: %s", err)
                self._log.trace("scan_network: success=False, emitting result_signal")
                self.status_signal.emit(False, f"Scan failed: {err}")
                self.result_signal.emit(result)
                return

            devices = result.get("devices", [])
            total = len(devices)
            self._log.info("scan_network OK — %d devices", total)
            self._log.debug("scan_network: parsing %d devices", total)
            self._log.trace("scan_network: entering device emit loop")

            # Emit per-device signals (Qt event loop processes each between iterations)
            for row, dev in enumerate(devices):
                self._log.trace("scan_network: device_signal.emit(row=%d, dev=%s)", row, dev.get("ip"))
                self.device_signal.emit(row, dev)

            # Signal completion
            self._log.trace("scan_network: scan_complete_signal.emit(total=%d)", total)
            self.scan_complete_signal.emit(total)
            self.status_signal.emit(True, f"Scan complete: {total} devices")
            self._log.info("scan_network complete: %d devices", total)

            # Also emit legacy result_signal for backwards compatibility
            self._log.trace("scan_network: result_signal.emit(legacy)")
            self.result_signal.emit(result)
        finally:
            # Always reset the guard — even if _run_sync or signal emission raises
            self._log.trace("scan_network: finally — _scan_in_progress=False")
            self._scan_in_progress = False

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
        is followed.
        """
        self._log.info("discover_network -> forwarding to scan_network")
        self._log.trace("discover_network: entry, _client=%s", self._client is not None)
        if not self._client:
            self._log.info("discover_network - no client")
            self.status_signal.emit(False, "No MCP client")
            self._log.trace("discover_network: _client is None, emitting error")
            self.result_signal.emit({
                "success": False, "error": "No MCP client",
                "method_name": "discover_network"
            })
            return
        # Reuse scan_network() which has the full signal-per-item pipeline
        self._log.trace("discover_network: delegating to scan_network()")
        self.scan_network()

    @Slot()
    def scan_device_ports(self, target: str):
        self._call("scan_device_ports", {"target": target, "quick": True})

    # ── Internal helpers ────────────────────────────────────────────────

    def _run_sync(self, coro):
        """Run an async coroutine on this worker's event loop."""
        self._log.trace("_run_sync: loop=%s", "open" if self._loop and not self._loop.is_closed() else "closed")
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._log.trace("_run_sync: created new event loop")
        return self._loop.run_until_complete(coro)

    async def _do_connect(self) -> bool:
        self._log.trace("_do_connect: creating MCPClient(%s)", self._base_url)
        self._client = MCPClient(self._base_url)
        ok = await self._client.connect()
        self._log.debug("_do_connect: connect() returned %s", ok)
        return ok

    async def _do_disconnect(self):
        self._log.trace("_do_disconnect: entry")
        if self._client:
            self._log.trace("_do_disconnect: calling client.disconnect()")
            await self._client.disconnect()
            self._client = None
            self._log.trace("_do_disconnect: client set to None")

    def _call(self, method_name: str, params: dict):
        """Helper: log the call, await the result, log the result, re-emit status."""
        self._log.trace("_call(%s, %s)", method_name, params)
        if not self._client:
            self._log.info("_call(%s) aborted — not connected", method_name)
            self.status_signal.emit(False, "Not connected — cannot call tools")
            self.result_signal.emit({
                "success": False, "error": "Not connected",
                "method_name": method_name
            })
            return

        self._log.info("Calling tool %s", method_name)
        self._log.debug("_call(%s) params=%s", method_name, params)
        self._log.trace("_call: _run_sync(_client._call_tool(...))")
        result = self._run_sync(self._client._call_tool(method_name, params))

        ok = result.get("success", False)
        if ok:
            self._log.info("Tool %s succeeded", method_name)
            self._log.debug("_call(%s): result keys=%s", method_name, list(result.keys()))
            self.status_signal.emit(True, f"{method_name}: success")
        else:
            err = result.get("error", "unknown error")
            self._log.info("Tool %s failed: %s", method_name, err)
            self._log.debug("_call(%s) failed: error=%s", method_name, err)
            self.status_signal.emit(False, f"{method_name}: {err}")

        # Always emit the parsed result so the main thread can display it
        self._log.trace("_call: result_signal.emit(method=%s)", method_name)
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
        gui_log.info("MainWindow.__init__ starting")
        gui_log.trace("__init__: setupUi(self)")

        # ── Wire UI controls ────────────────────────────────────────────
        gui_log.trace("__init__: wiring pushButton_mcp.clicked -> _on_mcp_button")
        self.pushButton_mcp.clicked.connect(self._on_mcp_button)
        self.pushButton_mcp.setCheckable(True)
        self.pushButton_mcp.setChecked(False)
        self.pushButton_mcp.setText("Connect")
        gui_log.trace("__init__: wiring pushButton_discover.clicked -> _on_discover_button")
        self.pushButton_discover.clicked.connect(self._on_discover_button)
        self.pushButton_discover.setEnabled(False)  # disabled until connected

        # ── Enable column sorting ───────────────────────────────────────
        gui_log.trace("__init__: tableWidgetHost sorting disabled during init")
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
        gui_log.info("FreeNetAdminPro started")
        gui_log.debug("__init__: label_mcp_status=not_connected")
        self._append_log("[System] FreeNetAdminPro started")
        gui_log.debug("__init__: user hint logged")
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
        gui_log.trace("_on_mcp_button: isChecked=%s", self.pushButton_mcp.isChecked())
        if self.pushButton_mcp.isChecked():
            # → Connect
            url = self.lineEdit_mcp.text().strip()
            gui_log.debug("_on_mcp_button: lineEdit_mcp.text()=%r", url)
            if not url:
                gui_log.info("Connect failed — MCP URL is empty")
                self._append_log("[UI] ✗ MCP URL is empty")
                self.pushButton_mcp.setChecked(False)
                self._set_status_icon(False)
                self.pushButton_mcp.setText("Connect")
                return

            self.pushButton_mcp.setText("Disconnect")
            gui_log.info("Connect requested → %s", url)
            self._append_log(f"[UI] Connect requested → {url}")

            # Destroy previous worker and create a new one
            gui_log.trace("_on_mcp_button: _cleanup_worker()")
            self._cleanup_worker()
            thread = self._ensure_thread()
            gui_log.trace("_on_mcp_button: creating MCPWorker(%s)", url)
            self._worker = MCPWorker(url)
            self._worker.moveToThread(thread)

            # Wire signals
            gui_log.trace("_on_mcp_button: connecting log_signal -> _append_log")
            self._worker.log_signal.connect(self._append_log)
            gui_log.trace("_on_mcp_button: connecting status_signal -> _on_worker_status")
            self._worker.status_signal.connect(self._on_worker_status)
            gui_log.trace("_on_mcp_button: connecting result_signal -> _on_worker_result")
            self._worker.result_signal.connect(self._on_worker_result)
            gui_log.trace("_on_mcp_button: connecting device_signal -> _on_device_received")
            self._worker.device_signal.connect(self._on_device_received)
            gui_log.trace("_on_mcp_button: connecting scan_complete_signal -> _on_scan_complete")
            self._worker.scan_complete_signal.connect(self._on_scan_complete)
            gui_log.trace("_on_mcp_button: connecting scan_started_signal -> _on_scan_started")
            self._worker.scan_started_signal.connect(self._on_scan_started)

            # Start the thread and fire connect
            gui_log.trace("_on_mcp_button: thread.start()")
            assert thread is not None
            thread.start()
            gui_log.trace("_on_mcp_button: worker.connect()")
            self._worker.connect()
        else:
            # → Disconnect
            gui_log.info("Disconnect requested")
            self.pushButton_mcp.setText("Connect")
            self._append_log("[UI] Disconnect requested")
            if self._worker:
                gui_log.trace("_on_mcp_button: worker.disconnect()")
                self._worker.disconnect()
            else:
                gui_log.info("Disconnect requested — but not connected")
                self._append_log("[UI] ✗ Not connected")
                self.pushButton_mcp.setChecked(True)
                self.pushButton_mcp.setText("Disconnect")
            gui_log.trace("_on_mcp_button: _cleanup_worker()")
            self._cleanup_worker()
            if self._worker_thread is not None and self._worker_thread.isRunning():
                gui_log.trace("_on_mcp_button: worker_thread.quit() + wait()")
                self._worker_thread.quit()
                self._worker_thread.wait()

    @Slot(bool, str)
    def _on_worker_status(self, connected: bool, message: str):
        """Handle status updates from the worker thread."""
        gui_log.trace("_on_worker_status: connected=%s, message=%r", connected, message)
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
        gui_log.info("Scan started")
        gui_log.trace("_on_scan_started: _is_scanning=True, button disabled")
        self._is_scanning = True
        self.pushButton_discover.setEnabled(False)
        self.statusbar.showMessage("Scanning network...", 0)
        self._append_log("[UI] Scan started — results will appear as rows")

    @Slot(dict)
    def _on_worker_result(self, result: dict):
        """Legacy handler — kept for non-scan tools (info, ports, etc.)."""
        method_name = result.get("method_name", "")
        gui_log.debug("Received result: %s, keys=%s", method_name,
                      list(result.keys()) if isinstance(result, dict) else type(result))
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
            gui_log.info("Preloading icons & preparing table")
            self._scan_devices_used.clear()
            self._scan_devices_classified.clear()
            self._scan_rows_ready = 0
            self._scan_total_devices = 0
            self._icon_cache.clear()

            gui_log.debug("Preloading %d icons from DEVICE_ICONS", len(DEVICE_ICONS))
            self._append_log("[UI] Preloading icons...")
            for dtype, icon_path in DEVICE_ICONS.items():
                gui_log.trace("_on_device_received: load icon %s (%s)", icon_path, dtype)
                pm = QPixmap(icon_path)
                if pm.isNull():
                    gui_log.warning("Failed to load icon %s (%s)", icon_path, dtype)
                    self._append_log(f"[UI] ✗ Icon FAILED: {icon_path}")
                else:
                    self._icon_cache[icon_path] = QIcon(pm)
                    gui_log.debug("Icon loaded: %s (%s)", icon_path, dtype)
                    self._append_log(f"[UI] ✓ Icon loaded: {icon_path}")

            gui_log.info("Preloaded %d icons", len(self._icon_cache))
            self._append_log(f"[UI] Preloaded {len(self._icon_cache)} icons")

            # Clear table & freeze updates
            gui_log.trace("_on_device_received: tableWidgetHost.setSortingEnabled(False)")
            self.tableWidgetHost.setSortingEnabled(False)
            gui_log.trace("_on_device_received: tableWidgetHost.setUpdatesEnabled(False)")
            self.tableWidgetHost.setUpdatesEnabled(False)
            gui_log.trace("_on_device_received: tableWidgetHost.setRowCount(0)")
            self.tableWidgetHost.setRowCount(0)
            gui_log.debug("Ready to receive %d devices", self._scan_total_devices)
            self._append_log("[UI] Parsing scan result: ready for devices")

        # ── Insert ONE row (main thread, non-blocking) ────────────────
        gui_log.trace("_on_device_received: insertRow(%d)", row)
        self.tableWidgetHost.insertRow(row)

        # Col 0: Status ●
        gui_log.trace("_on_device_received: col0 — QTableWidgetItem('●')")
        it = QTableWidgetItem("●")
        it.setForeground(Qt.GlobalColor.darkGreen)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 0, it)

        # Col 1: device icon
        vendor = dev.get("vendor", "") or ""
        hostname = dev.get("hostname") or ""
        gui_log.debug("_on_device_received: col1 — vendor=%r, hostname=%r", vendor, hostname)
        dtype = classify_device(vendor, hostname)
        icon_path = DEVICE_ICONS.get(dtype, DEVICE_ICONS["unknown"])
        gui_log.trace("_on_device_received: classified as %s, icon=%s", dtype, icon_path)
        self._scan_devices_used.add(icon_path)
        self._scan_devices_classified.append(dtype)
        it = QTableWidgetItem()
        it.setIcon(self._icon_cache.get(icon_path, self._icon_cache.get(DEVICE_ICONS["unknown"])))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 1, it)

        # Col 2: name
        name = dev.get("hostname") or dev.get("mac") or "Unknown"
        gui_log.debug("_on_device_received: col2 — name=%r", name)
        it = QTableWidgetItem(name)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 2, it)

        # Col 3: IPv4
        ip_val = dev.get("ip", "N/A")
        gui_log.debug("_on_device_received: col3 — ip=%r", ip_val)
        it = IPTableWidgetItem(str(ip_val))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 3, it)

        # Col 4: Ping
        gui_log.trace("_on_device_received: col4 — 'N/A' placeholder")
        it = QTableWidgetItem("N/A")
        it.setForeground(Qt.GlobalColor.gray)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 4, it)

        # Col 5: MAC
        mac_val = dev.get("mac", "N/A")
        gui_log.debug("_on_device_received: col5 — mac=%r (type=%s)", mac_val, type(mac_val).__name__)
        it = QTableWidgetItem(str(mac_val))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 5, it)

        # Col 6: Vendor
        vendor_val = dev.get("vendor", "Unknown")
        gui_log.debug("_on_device_received: col6 — vendor=%r", vendor_val)
        it = QTableWidgetItem(str(vendor_val))
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        self.tableWidgetHost.setItem(row, 6, it)

        gui_log.trace("_on_device_received: row %d COMPLETE", row)
        self._scan_rows_ready += 1

    @Slot(int)
    def _on_scan_complete(self, total: int):
        """Handle scan completion — re-enable sorting, unpaint, show summary.

        Called on the main thread after all device_signal emissions.
        """
        gui_log.info("Scan complete: %d devices", total)
        self._scan_total_devices = total
        self._append_log(f"[UI] Populated table with {total} devices")
        self.statusbar.showMessage(f"Discovered {total} devices", 5000)

        # Debug summary
        gui_log.debug("Icon cache: %d loaded, icons used: %s", len(self._icon_cache), self._scan_devices_used)
        self._append_log(f"[UI] 🔍 Icon cache: {len(self._icon_cache)} loaded")
        self._append_log(f"[UI] 🔍 Icons used by devices: {self._scan_devices_used}")

        unused = set(DEVICE_ICONS.keys()) - set(self._scan_devices_classified)
        if unused:
            gui_log.info("Icon types never triggered: %s", unused)
            self._append_log(f"[UI] ⚠ Icon types never triggered: {unused}")
            self._append_log("[UI]   → Run 'python -m pytest tests/ -v' to verify all icons load")

        # Re-enable sorting and painting
        gui_log.trace("_on_scan_complete: re-enable sorting + updates")
        self.tableWidgetHost.setSortingEnabled(True)
        self.tableWidgetHost.setUpdatesEnabled(True)
        self.tableWidgetHost.repaint()

        # Clear scanning state — re-enable discover button
        gui_log.trace("_on_scan_complete: _is_scanning=False, button enabled")
        self._is_scanning = False
        self.pushButton_discover.setEnabled(True)

    def _on_discover_button(self):
        """Handle discover button click — starts a non-blocking scan."""
        gui_log.trace("_on_discover_button: worker=%s, enabled=%s",
                       self._worker is not None, self.pushButton_discover.isEnabled())
        if not self._worker or not self.pushButton_discover.isEnabled():
            return

        # Mark scanning, disable button, show status in statusbar
        gui_log.info("Discover button clicked — starting scan_network")
        self._is_scanning = True
        self.pushButton_discover.setEnabled(False)
        self.statusbar.showMessage("Scanning network...", 0)
        self._append_log("[UI] Scan started — results will appear as rows")
        self._worker.discover_network()

    def _set_status_icon(self, connected: bool):
        """Toggle the MCP status icon label."""
        gui_log.trace("_set_status_icon: connected=%s -> pixmap=%s", connected,
                      "connected.svg" if connected else "not_connected.svg")
        if connected:
            self.label_mcp_status.setPixmap(QPixmap(":/icons/connected.svg"))
        else:
            self.label_mcp_status.setPixmap(QPixmap(":/icons/not_connected.svg"))

    def _append_log(self, msg: str):
        """Append a line to the debug textEdit."""
        self.textEdit.append(msg)

    def _cleanup_worker(self):
        """Destroy the current worker and reset reference."""
        gui_log.trace("_cleanup_worker: worker=%s", self._worker is not None)
        if self._worker is not None:
            gui_log.debug("_cleanup_worker: deleting worker via deleteLater()")
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
