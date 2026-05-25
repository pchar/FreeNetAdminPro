"""
FreeNetAdminPro — main application window.

Wires the Qt UI to the async MCP client:
  - pushButton_mcp toggles connection using the URL from lineEdit_mcp
  - icon toggles: green connected / red not_connected
  - all MCP calls logged to textEdit
"""

import sys
import asyncio
import logging
import json
from datetime import datetime

from typing import Optional
from PySide6.QtWidgets import QMainWindow, QApplication, QTableWidgetItem, QProgressDialog
from PySide6.QtCore import QObject, Signal, QThread, Slot, Qt
from PySide6.QtGui import QPixmap, QIcon

from ui_form import Ui_MainWindow
from mcp_handler import MCPClient


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
        self._call("scan_network", {"subnet": "172.30.200.0/24", "resolve_names": True})

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
        result["method_name"] = method_name  # tag so _on_worker_result knows the method
        self.result_signal.emit(result)


# ────────────────────────────────────────────────────────────────────────────
# Main window
# ────────────────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow, Ui_MainWindow):
    """Application main window."""

    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # ── Reconnect UI elements we need ───────────────────────────────
        self.pushButton_mcp.clicked.connect(self._on_mcp_button)
        self.pushButton_mcp.setCheckable(True)
        self.pushButton_mcp.setChecked(False)
        self.pushButton_mcp.setText("Connect")
        self.pushButton_discover.clicked.connect(self._on_discover_button)
        self.pushButton_discover.setEnabled(False)  # disabled until connected

        # Initial icon: not connected
        self._set_status_icon(False)
        self._append_log("[System] FreeNetAdminPro started")
        self._append_log("[System] Click 'connect' on the MCP button to start")

        # ── Worker thread + background worker ───────────────────────────
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[MCPWorker] = None

        self._append_log("[System] Ready")

    def _ensure_thread(self):
        """Create or return the worker thread.
        
        QThread cannot be reused after finish(), so we create a fresh one
        each time the user connects (after a prior disconnect).
        """
        if self._worker_thread is None or not self._worker_thread.isRunning():
            # If thread finished, clean it up and create a new one
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

            # Create worker with this URL (destroy previous if any)
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
                self.pushButton_mcp.setChecked(True)  # re-check if nothing to do
                self.pushButton_mcp.setText("Disconnect")
            self._cleanup_worker()
            # Worker is gone — quit the thread
            if self._worker_thread is not None and self._worker_thread.isRunning():
                self._worker_thread.quit()
                self._worker_thread.wait()

    @Slot(bool, str)
    def _on_worker_status(self, connected: bool, message: str):
        """Handle status updates from the worker thread."""
        self._set_status_icon(connected)
        self.pushButton_mcp.setChecked(connected)
        self.pushButton_mcp.setText("Disconnect" if connected else "Connect")
        self.pushButton_discover.setEnabled(connected)  # enable/disable discover button
        self.statusbar.showMessage(message, 5000)

    @Slot(dict)
    def _on_worker_result(self, result: dict):
        """Handle MCP tool call results and populate UI."""
        # Hide progress bar if visible
        if hasattr(self, "_progress_dialog") and self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog = None

        method_name = result.get("method_name", "")
        self._append_log(f"[UI] Received result: {method_name} -> {list(result.keys()) if isinstance(result, dict) else type(result)}")

        if method_name == "scan_network":
            self._populate_table(result)
            # Re-enable discover button after operation completes
            self.pushButton_discover.setEnabled(True)

    def _on_progress_canceled(self):
        """Handle progress dialog cancel — stop scan and clean up."""
        self._append_log("[UI] Scan canceled by user")
        if self._progress_dialog:
            self._progress_dialog.close()
        self.pushButton_discover.setEnabled(True)

    def _on_discover_button(self):
        """Handle discover button click."""
        if self._worker and self.pushButton_discover.isEnabled():
            # Show progress bar
            self._progress_dialog = QProgressDialog(
                "Scanning network...", "Cancel", 0, 100, self
            )
            self._progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self._progress_dialog.setMinimumDuration(0)  # show immediately
            self._progress_dialog.canceled.connect(self._on_progress_canceled)
            self._progress_dialog.show()
            self.pushButton_discover.setEnabled(False)  # prevent double-click
            self._worker.discover_network()

    def _populate_table(self, result: dict):
        """Populate tableWidgetHost from scan_network result dict."""
        if not isinstance(result, dict):
            self._append_log(f"[UI] ERROR: Expected dict, got {type(result)}")
            self._append_log(f"[UI] Raw result: {result}")
            return

        devices = result.get("devices")
        if devices is None:
            # Try to get from "result" key as fallback
            devices = result.get("result", {}).get("devices", []) if isinstance(result.get("result"), dict) else []
            if not devices:
                self._append_log(f"[UI] No 'devices' key found. Result keys: {list(result.keys())}")
                self._append_log(f"[UI] Full result: {json.dumps(result, indent=2)[:500]}")
                return

        self._append_log(f"[UI] Parsing scan result: {len(devices)} devices")

        # Clear existing rows
        self.tableWidgetHost.setRowCount(0)

        # Prepare icons — reuse from resources
        icon_connected = QPixmap(":/icons/start.svg")   # green (device found)
        icon_disconnected = QPixmap(":/icons/stop.svg")  # red

        for dev in devices:
            row = self.tableWidgetHost.rowCount()
            self.tableWidgetHost.insertRow(row)

            # ── Col 0: Status ──
            # Assume device is up (ARP found it); set green status text
            status_item = QTableWidgetItem("●")
            status_item.setForeground(Qt.GlobalColor.darkGreen)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 0, status_item)

            # ── Col 1: icon ──
            icon_item = QTableWidgetItem()
            icon_item.setIcon(QIcon(icon_connected))
            icon_item.setFlags(icon_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 1, icon_item)

            # ── Col 2: name ──
            name = dev.get("hostname") or dev.get("mac") or "Unknown"
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 2, name_item)

            # ── Col 3: IPv4 Addr ──
            ip = dev.get("ip", "N/A")
            ip_item = QTableWidgetItem(ip)
            ip_item.setFlags(ip_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 3, ip_item)

            # ── Col 4: Ping ──
            ping_item = QTableWidgetItem("N/A")
            ping_item.setForeground(Qt.GlobalColor.gray)
            ping_item.setFlags(ping_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 4, ping_item)

            # ── Col 5: MAC Addr ──
            mac = dev.get("mac", "N/A")
            mac_item = QTableWidgetItem(mac)
            mac_item.setFlags(mac_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 5, mac_item)

            # ── Col 6: NIC Vendor ──
            vendor = dev.get("vendor", "Unknown")
            vendor_item = QTableWidgetItem(vendor)
            vendor_item.setFlags(vendor_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tableWidgetHost.setItem(row, 6, vendor_item)

        total = len(devices)
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

        # 1. Disconnect worker signals first (stop signal routing)
        if self._worker is not None:
            self._append_log("[UI] Disconnecting worker...")
            self._worker.disconnect()
            # Stop any in-flight async operation
            if hasattr(self._worker, 'stop'):
                self._worker.stop()

        # 2. Disconnect UI slots from worker signals
        if self._worker_thread is not None:
            self._worker_thread.quit()
            # Wait with timeout — don't block forever if async ops hang
            if not self._worker_thread.wait(3000):
                self._append_log("[UI] WARNING: Thread did not quit in time, force stopping")

        # 3. Delete worker (now safe — thread is stopped, signals are disconnected)
        self._cleanup_worker()

        # 4. Clean up thread object
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
    app.setStyle("Fusion")  # clean cross-platform look
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
