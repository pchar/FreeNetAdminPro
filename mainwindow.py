# This Python file uses the following encoding: utf-8
import sys
from pathlib import Path

from PySide6.QtGui import QAction, QIcon, QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import QApplication, QMainWindow

# Important:
# You need to run the following command to generate the ui_form.py file
#     pyside6-uic form.ui -o ui_form.py, or
#     pyside2-uic form.ui -o ui_form.py
from ui_form import Ui_MainWindow
import resources_rc  # noqa: F401 -- registers the Qt resource

ICONS_DIR = Path(__file__).parent / "icons"


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # Icon setup — show play icon, scan not running
        self._scanning = False
        self._start_icon = QIcon(str(ICONS_DIR / "start.svg"))
        self._stop_icon = QIcon(str(ICONS_DIR / "stop.svg"))

        self.ui.actionStart.setCheckable(False)
        self.ui.actionStart.setIcon(self._start_icon)
        self.ui.actionStart.setToolTip("Start Scanning")

        self.ui.actionStart.triggered.connect(self._on_triggered)

        # CIDR subnet validator: accepts e.g. 172.30.200.0/24
        cidr_re = QRegularExpression(
            r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\."
            r"(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\/"
            r"(3[0-2]|[12]?\d)$"
        )
        self.ui.cluster.setValidator(
            QRegularExpressionValidator(cidr_re, self.ui.cluster)
        )

    def _on_triggered(self):
        if not self._scanning:
            self._scanning = True
            self.ui.actionStart.setIcon(self._stop_icon)
            self.ui.actionStart.setToolTip("Stop Scanning")
            self._start_scanning()
        else:
            self._scanning = False
            self.ui.actionStart.setIcon(self._start_icon)
            self.ui.actionStart.setToolTip("Start Scanning")
            self._stop_scanning()

    def _start_scanning(self):
        self.ui.textEdit.append("[*] Scanning started...")

    def _stop_scanning(self):
        self.ui.textEdit.append("[!] Scanning stopped.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = MainWindow()
    widget.show()
    sys.exit(app.exec())
