"""
nbr_audit_plugin.py

QGIS plugin entry class: registers the toolbar button / menu item and
docks the NbrAuditDialog panel to the side of the map canvas.
"""

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt


class NbrAuditPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dock = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "icon.png")
        self.action = QAction(QIcon(icon_path), "NBR Audit Tool", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&NBR Audit Tool", self.action)

    def unload(self):
        self.iface.removePluginMenu("&NBR Audit Tool", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock = None

    def run(self):
        from .ui.main_dialog import NbrAuditDialog
        if self.dock is None:
            self.dock = NbrAuditDialog(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()
