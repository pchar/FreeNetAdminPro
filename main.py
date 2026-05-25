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
        self_num = self.data(Qt.UserRole)
        other_num = other.data(Qt.UserRole)
        if self_num != -1 and other_num != -1:
            # Both are valid IPs → numeric comparison
            return self_num < other_num
        if self_num == -1 and other_num == -1:
            # Both are non-IPs (e.g. "N/A") → string comparison
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
# Async worker — runs on a dedicated thread so the GUI never freezes
# ────────────────────────────────────────────────────────────────────────────

class MCPWorker(QObject):
    """Background worker that owns the async event loop and MCPClient."""

    # Signals to push results back to the main (GUI) thread
    log_signal = Signal(str)
    status_signal = Signal(bool, str)  # connected, message
    result_signal = Signal(dict)       # parsed MCP tool result

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
        """Scan the configured cluster subnet."""
        self._call("scan_network", {"subnet": "", "resolve_names": True})

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
        """Scan the cluster subnet (alias for scan_network)."""
        self._call("scan_network", {
            "subnet": "",
            "resolve_names": True
        })

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

    @Slot(dict)
    def _on_worker_result(self, result: dict):
        """Handle MCP tool call results and populate UI.

        This runs on the main thread (queued signal). Table population
        is fast for typical datasets (<500 rows) so we do it here.
        """
        method_name = result.get("method_name", "")
        self._append_log(f"[UI] Received result: {method_name} -> "
                         f"{list(result.keys()) if isinstance(result, dict) else type(result)}")

        if method_name == "scan_network":
            # Clear scanning flag and re-enable the discover button
            self._is_scanning = False
            self.pushButton_discover.setEnabled(True)
            self._populate_table(result)

    def _on_discover_button(self):
        """Handle discover button click — starts a non-blocking scan."""
        if not self._worker or not self.pushButton_discover.isEnabled():
            return

        # Mark scanning, disable button, show status in statusbar
        self._is_scanning = True
        self.pushButton_discover.setEnabled(False)
        self.statusbar.showMessage("Scanning network...", 0)
        self._append_log("[UI] Scan started — results will appear when complete")
        self._worker.discover_network()

    def _populate_table(self, result: dict):
        """Populate tableWidgetHost from scan_network result dict.

        Optimization: disable widget updates during batch insert to avoid
        repainting for every row, then re-enable for a single paint.
        """
        if not isinstance(result, dict):
            self._append_log(f"[UI] ERROR: Expected dict, got {type(result)}")
            self._append_log(f"[UI] Raw result: {result}")
            self.statusbar.showMessage("Scan failed — invalid response", 5000)
            return

        devices = result.get("devices")
        if devices is None:
            devices = result.get("result", {}).get("devices", []) if isinstance(result.get("result"), dict) else []
            if not devices:
                self._append_log(f"[UI] No 'devices' key found. Result keys: {list(result.keys())}")
                self._append_log(f"[UI] Full result: {json.dumps(result, indent=2)[:500]}")
                self.statusbar.showMessage("Scan found no devices", 5000)
                return

        total = len(devices)
        self._append_log(f"[UI] Parsing scan result: {total} devices")

        # Disable sorting during batch insert — prevents re-sort after every row
        self.tableWidgetHost.setSortingEnabled(False)
        # Batch update: freeze painting, insert all rows, then paint once
        self.tableWidgetHost.setUpdatesEnabled(False)
        self.tableWidgetHost.setRowCount(0)

        # Preload icons once (avoid repeated QPixmap construction)
        icon_up = QIcon(QPixmap(":/icons/start.svg"))

        for dev in devices:
            row = self.tableWidgetHost.rowCount()
            self.tableWidgetHost.insertRow(row)

            # ── Col 0: Status ──
            item = QTableWidgetItem("●")
            item.setForeground(Qt.GlobalColor.darkGreen)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 0, item)

            # ── Col 1: icon ──
            item = QTableWidgetItem()
            item.setIcon(icon_up)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 1, item)

            # ── Col 2: name ──
            name = dev.get("hostname") or dev.get("mac") or "Unknown"
            item = QTableWidgetItem(name)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 2, item)

            # ── Col 3: IPv4 — semantic numeric sort ──
            item = IPTableWidgetItem(str(dev.get("ip", "N/A")))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 3, item)

            # ── Col 4: Ping ──
            item = QTableWidgetItem("N/A")
            item.setForeground(Qt.GlobalColor.gray)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 4, item)

            # ── Col 5: MAC ──
            item = QTableWidgetItem(str(dev.get("mac", "N/A")))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 5, item)

            # ── Col 6: Vendor ──
            item = QTableWidgetItem(str(dev.get("vendor", "Unknown")))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 6, item)

        # Re-enable sorting and painting — table is ready for user interaction
        self.tableWidgetHost.setSortingEnabled(True)
        self.tableWidgetHost.setUpdatesEnabled(True)
        self.tableWidgetHost.repaint()

        self._append_log(f"[UI] Populated table with {total} devices")
        self.statusbar.showMessage(f"Discovered {total} devices", 5000)

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
        """Clean up on exit — stop thread and worker gracefully."""
        self._append_log("[UI] Shutting down...")

        # 1. Disconnect worker signals first
        if self._worker is not None:
            self._append_log("[UI] Disconnecting worker...")
            self._worker.disconnect()

        # 2. Quit the thread and wait (3s timeout)
        if self._worker_thread is not None:
            self._worker_thread.quit()
            if not self._worker_thread.wait(3000):
                self._append_log("[UI] WARNING: Thread did not quit in time")

        # 3. Delete worker (thread is stopped)
        self._cleanup_worker()

        # 4. Delete thread
        if self._worker_thread is not None:
            self._worker_thread.deleteLater()
            self._worker_thread = None

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
