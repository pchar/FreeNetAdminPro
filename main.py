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
from datetime import datetime

from PySide6.QtWidgets import QMainWindow, QApplication
from PySide6.QtCore import QObject, Signal, QThread, Slot
from PySide6.QtGui import QPixmap

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

    def __init__(self, base_url: str):
        super().__init__()
        self._base_url = base_url
        self._client: MCPClient | None = None
        self._connected = False
        self._loop: asyncio.AbstractEventLoop | None = None

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

        # Initial icon: not connected
        self._set_status_icon(False)
        self._append_log("[System] FreeNetAdminPro started")
        self._append_log("[System] Click 'connect' on the MCP button to start")

        # ── Worker thread + background worker ───────────────────────────
        self._worker_thread = QThread()
        self._worker = None  # created lazily on first connect

        self._worker_thread.start()

        self._append_log("[System] Ready")

    def _on_mcp_button(self):
        """Toggle connect / disconnect when pushButton_mcp is clicked."""
        if self.pushButton_mcp.isChecked():
            # → Connect
            url = self.lineEdit_mcp.text().strip()
            if not url:
                self._append_log("[UI] ✗ MCP URL is empty")
                self.pushButton_mcp.setChecked(False)
                self._set_status_icon(False)
                return

            self._append_log(f"[UI] Connect requested → {url}")

            # Create worker with this URL (destroy previous if any)
            self._cleanup_worker()
            self._worker = MCPWorker(url)
            self._worker.setParent(self._worker_thread)
            self._worker.moveToThread(self._worker_thread)

            # Wire signals
            self._worker.log_signal.connect(self._append_log)
            self._worker.status_signal.connect(self._on_worker_status)

            # Fire connect on the worker
            self._worker.connect()
        else:
            # → Disconnect
            self._append_log("[UI] Disconnect requested")
            if self._worker:
                self._worker.disconnect()
            else:
                self._append_log("[UI] ✗ Not connected")
                self.pushButton_mcp.setChecked(True)  # re-check if nothing to do
            self._cleanup_worker()

    @Slot(bool, str)
    def _on_worker_status(self, connected: bool, message: str):
        """Handle status updates from the worker thread."""
        self._set_status_icon(connected)
        self.statusbar.showMessage(message, 5000)

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
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    def closeEvent(self, event):
        """Clean up on exit."""
        self._cleanup_worker()
        self._worker_thread.quit()
        self._worker_thread.wait()
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
