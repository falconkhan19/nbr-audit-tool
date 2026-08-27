"""
NBR Audit Tool
QGIS plugin entry point.
"""


def classFactory(iface):
    from .nbr_audit_plugin import NbrAuditPlugin
    return NbrAuditPlugin(iface)
