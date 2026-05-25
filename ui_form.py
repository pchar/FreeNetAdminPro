# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'form.ui'
##
## Created by: Qt User Interface Compiler version 6.10.3
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QAction, QBrush, QColor, QConicalGradient,
    QCursor, QFont, QFontDatabase, QGradient,
    QIcon, QImage, QKeySequence, QLinearGradient,
    QPainter, QPalette, QPixmap, QRadialGradient,
    QTransform)
from PySide6.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QPushButton,
    QSizePolicy, QSpacerItem, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QToolBar, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)
import rc_resources

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(1086, 845)
        self.actionStart = QAction(MainWindow)
        self.actionStart.setObjectName(u"actionStart")
        self.actionStart.setCheckable(True)
        self.actionStart.setChecked(True)
        self.actionStart.setEnabled(True)
        icon = QIcon()
        icon.addFile(u":/icons/start.svg", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        icon.addFile(u":/icons/stop.svg", QSize(), QIcon.Mode.Normal, QIcon.State.On)
        self.actionStart.setIcon(icon)
        self.actionStart.setMenuRole(QAction.MenuRole.NoRole)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.gridLayout = QGridLayout(self.centralwidget)
        self.gridLayout.setObjectName(u"gridLayout")
        self.horizontalLayout_4 = QHBoxLayout()
        self.horizontalLayout_4.setObjectName(u"horizontalLayout_4")
        self.label_cluster = QLabel(self.centralwidget)
        self.label_cluster.setObjectName(u"label_cluster")

        self.horizontalLayout_4.addWidget(self.label_cluster)

        self.cluster = QLineEdit(self.centralwidget)
        self.cluster.setObjectName(u"cluster")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.cluster.sizePolicy().hasHeightForWidth())
        self.cluster.setSizePolicy(sizePolicy)
        self.cluster.setProperty(u"fixedWidth", 190)

        self.horizontalLayout_4.addWidget(self.cluster)

        self.ApplypushButton = QPushButton(self.centralwidget)
        self.ApplypushButton.setObjectName(u"ApplypushButton")

        self.horizontalLayout_4.addWidget(self.ApplypushButton)

        self.pushButton_discover = QPushButton(self.centralwidget)
        self.pushButton_discover.setObjectName(u"pushButton_discover")

        self.horizontalLayout_4.addWidget(self.pushButton_discover)

        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout_4.addItem(self.horizontalSpacer)

        self.label_mcp = QLabel(self.centralwidget)
        self.label_mcp.setObjectName(u"label_mcp")

        self.horizontalLayout_4.addWidget(self.label_mcp)

        self.label_mcp_status = QLabel(self.centralwidget)
        self.label_mcp_status.setObjectName(u"label_mcp_status")
        self.label_mcp_status.setMinimumSize(QSize(24, 24))
        self.label_mcp_status.setPixmap(QPixmap(u":/icons/not_connected.svg"))
        self.label_mcp_status.setScaledContents(True)

        self.horizontalLayout_4.addWidget(self.label_mcp_status)

        self.lineEdit_mcp = QLineEdit(self.centralwidget)
        self.lineEdit_mcp.setObjectName(u"lineEdit_mcp")
        sizePolicy.setHeightForWidth(self.lineEdit_mcp.sizePolicy().hasHeightForWidth())
        self.lineEdit_mcp.setSizePolicy(sizePolicy)
        self.lineEdit_mcp.setMinimumSize(QSize(160, 0))

        self.horizontalLayout_4.addWidget(self.lineEdit_mcp)

        self.pushButton_mcp = QPushButton(self.centralwidget)
        self.pushButton_mcp.setObjectName(u"pushButton_mcp")
        self.pushButton_mcp.setCheckable(True)

        self.horizontalLayout_4.addWidget(self.pushButton_mcp)

        self.horizontalLayout_4.setStretch(4, 1)

        self.gridLayout.addLayout(self.horizontalLayout_4, 0, 0, 1, 1)

        self.textEdit = QTextEdit(self.centralwidget)
        self.textEdit.setObjectName(u"textEdit")
        self.textEdit.setReadOnly(True)

        self.gridLayout.addWidget(self.textEdit, 2, 0, 1, 1)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.labelClusters = QLabel(self.centralwidget)
        self.labelClusters.setObjectName(u"labelClusters")

        self.verticalLayout_2.addWidget(self.labelClusters)

        self.tableWidgetHost = QTableWidget(self.centralwidget)
        if (self.tableWidgetHost.columnCount() < 7):
            self.tableWidgetHost.setColumnCount(7)
        __qtablewidgetitem = QTableWidgetItem()
        self.tableWidgetHost.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.tableWidgetHost.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.tableWidgetHost.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.tableWidgetHost.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.tableWidgetHost.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.tableWidgetHost.setHorizontalHeaderItem(5, __qtablewidgetitem5)
        __qtablewidgetitem6 = QTableWidgetItem()
        self.tableWidgetHost.setHorizontalHeaderItem(6, __qtablewidgetitem6)
        self.tableWidgetHost.setObjectName(u"tableWidgetHost")

        self.verticalLayout_2.addWidget(self.tableWidgetHost)


        self.horizontalLayout.addLayout(self.verticalLayout_2)


        self.gridLayout.addLayout(self.horizontalLayout, 1, 0, 1, 1)

        self.verticalLayout = QVBoxLayout()
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.verticalLayout.addItem(self.verticalSpacer)

        self.treeWidgetDevice = QTreeWidget(self.centralwidget)
        __qtreewidgetitem = QTreeWidgetItem(self.treeWidgetDevice)
        QTreeWidgetItem(__qtreewidgetitem)
        QTreeWidgetItem(__qtreewidgetitem)
        QTreeWidgetItem(__qtreewidgetitem)
        __qtreewidgetitem1 = QTreeWidgetItem(__qtreewidgetitem)
        QTreeWidgetItem(__qtreewidgetitem1)
        self.treeWidgetDevice.setObjectName(u"treeWidgetDevice")

        self.verticalLayout.addWidget(self.treeWidgetDevice)

        self.verticalLayout.setStretch(0, 4)
        self.verticalLayout.setStretch(1, 56)

        self.gridLayout.addLayout(self.verticalLayout, 1, 1, 1, 1)

        self.verticalLayout_3 = QVBoxLayout()
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")

        self.gridLayout.addLayout(self.verticalLayout_3, 2, 1, 1, 1)

        self.gridLayout.setColumnStretch(0, 5)
        self.gridLayout.setColumnStretch(1, 1)
        MainWindow.setCentralWidget(self.centralwidget)
        self.statusbar = QStatusBar(MainWindow)
        self.statusbar.setObjectName(u"statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.toolBar = QToolBar(MainWindow)
        self.toolBar.setObjectName(u"toolBar")
        MainWindow.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolBar)

        self.toolBar.addAction(self.actionStart)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.actionStart.setText(QCoreApplication.translate("MainWindow", u"Start Stop", None))
        self.actionStart.setIconText(QCoreApplication.translate("MainWindow", u"Start Stop", None))
#if QT_CONFIG(tooltip)
        self.actionStart.setToolTip(QCoreApplication.translate("MainWindow", u"Start/Stop Scanning", None))
#endif // QT_CONFIG(tooltip)
        self.label_cluster.setText(QCoreApplication.translate("MainWindow", u"cluster", None))
        self.cluster.setText(QCoreApplication.translate("MainWindow", u"172.30.200.0/24", None))
        self.cluster.setPlaceholderText(QCoreApplication.translate("MainWindow", u"e.g. 172.30.200.0/24", None))
        self.ApplypushButton.setText(QCoreApplication.translate("MainWindow", u"Apply", None))
        self.pushButton_discover.setText(QCoreApplication.translate("MainWindow", u"discover", None))
        self.label_mcp.setText(QCoreApplication.translate("MainWindow", u"MCP", None))
        self.label_mcp_status.setText("")
        self.lineEdit_mcp.setText(QCoreApplication.translate("MainWindow", u"http://localhost:8009", None))
        self.pushButton_mcp.setText(QCoreApplication.translate("MainWindow", u"connect", None))
        self.labelClusters.setText(QCoreApplication.translate("MainWindow", u"Clusters", None))
        ___qtablewidgetitem = self.tableWidgetHost.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("MainWindow", u"Status", None))
        ___qtablewidgetitem1 = self.tableWidgetHost.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("MainWindow", u"icon", None))
        ___qtablewidgetitem2 = self.tableWidgetHost.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("MainWindow", u"name", None))
        ___qtablewidgetitem3 = self.tableWidgetHost.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("MainWindow", u"IPv4 Addr", None))
        ___qtablewidgetitem4 = self.tableWidgetHost.horizontalHeaderItem(4)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("MainWindow", u"Ping", None))
        ___qtablewidgetitem5 = self.tableWidgetHost.horizontalHeaderItem(5)
        ___qtablewidgetitem5.setText(QCoreApplication.translate("MainWindow", u"MAC Addr", None))
        ___qtablewidgetitem6 = self.tableWidgetHost.horizontalHeaderItem(6)
        ___qtablewidgetitem6.setText(QCoreApplication.translate("MainWindow", u"NIC Vendor", None))
        ___qtreewidgetitem = self.treeWidgetDevice.headerItem()
        ___qtreewidgetitem.setText(0, QCoreApplication.translate("MainWindow", u"device", None))

        __sortingEnabled = self.treeWidgetDevice.isSortingEnabled()
        self.treeWidgetDevice.setSortingEnabled(False)
        ___qtreewidgetitem1 = self.treeWidgetDevice.topLevelItem(0)
        ___qtreewidgetitem1.setText(0, QCoreApplication.translate("MainWindow", u"fdsfs", None))
        ___qtreewidgetitem2 = ___qtreewidgetitem1.child(0)
        ___qtreewidgetitem2.setText(0, QCoreApplication.translate("MainWindow", u"New Subitem", None))
        ___qtreewidgetitem3 = ___qtreewidgetitem1.child(1)
        ___qtreewidgetitem3.setText(0, QCoreApplication.translate("MainWindow", u"New Item", None))
        ___qtreewidgetitem4 = ___qtreewidgetitem1.child(2)
        ___qtreewidgetitem4.setText(0, QCoreApplication.translate("MainWindow", u"New Item", None))
        ___qtreewidgetitem5 = ___qtreewidgetitem1.child(3)
        ___qtreewidgetitem5.setText(0, QCoreApplication.translate("MainWindow", u"New Item", None))
        ___qtreewidgetitem6 = ___qtreewidgetitem5.child(0)
        ___qtreewidgetitem6.setText(0, QCoreApplication.translate("MainWindow", u"New Subitem", None))
        self.treeWidgetDevice.setSortingEnabled(__sortingEnabled)

        self.toolBar.setWindowTitle(QCoreApplication.translate("MainWindow", u"toolBar", None))
    # retranslateUi

