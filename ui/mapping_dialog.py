"""
mapping_dialog.py

A reusable widget row: for each "semantic field" (e.g. Azimuth, Beamwidth,
Radius, Latitude...) the user can either pick a source column from a
drop-down (populated from the loaded file's columns) OR flip a checkbox to
type a manual/fixed value instead. Used for EP imports and for relationship
file field mapping.
"""

from qgis.PyQt.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QCheckBox,
    QLineEdit,
)


class FieldMapRow(QWidget):
    """One row: Label | [Column dropdown] | [x] Manual | [manual value box]"""

    def __init__(self, label, columns, allow_manual=True, default_manual="", parent=None):
        super().__init__(parent)
        self.allow_manual = allow_manual

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(label)
        self.label.setMinimumWidth(110)
        layout.addWidget(self.label)

        self.combo = QComboBox()
        self.combo.addItems(columns)
        layout.addWidget(self.combo, 2)

        if allow_manual:
            self.manual_check = QCheckBox("Manual value")
            layout.addWidget(self.manual_check)

            self.manual_edit = QLineEdit()
            self.manual_edit.setText(default_manual)
            self.manual_edit.setEnabled(False)
            layout.addWidget(self.manual_edit, 1)

            self.manual_check.toggled.connect(self._toggle_manual)
        else:
            self.manual_check = None
            self.manual_edit = None

        self.setLayout(layout)

    def _toggle_manual(self, checked):
        self.combo.setEnabled(not checked)
        self.manual_edit.setEnabled(checked)

    def set_columns(self, columns):
        current = self.combo.currentText()
        self.combo.clear()
        self.combo.addItems(columns)
        idx = self.combo.findText(current)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

    def is_manual(self):
        return bool(self.manual_check and self.manual_check.isChecked())

    def value(self):
        """Returns (is_manual: bool, value: str) -- value is either the chosen
        column name, or the manual text entered."""
        if self.is_manual():
            return True, self.manual_edit.text().strip()
        return False, self.combo.currentText()
