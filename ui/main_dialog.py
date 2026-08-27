"""
main_dialog.py

The main plugin UI: a tabbed dialog covering
  1) Import EP (4G / 5G) & create sectors
  2) Styling (graduated / categorized / load saved style - automatic classification)
  3) Import NRNRELATIONSHIP & NRCELLRELATION (multiple files each) and build keys
  4) NBR Audit (search a cell, run audit, produce filtered relation layers)
"""

import os
import traceback

from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QScrollArea,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QCompleter,
    QRadioButton,
    QButtonGroup,
    QSpinBox,
    QFileDialog,
    QMessageBox,
    QGroupBox,
    QFormLayout,
    QListWidget,
)
from qgis.PyQt.QtCore import Qt, QStringListModel
from qgis.core import QgsProject

from ..utils import file_io_utils, sector_utils, style_utils
from .mapping_dialog import FieldMapRow


class NbrAuditDialog(QDockWidget):
    """
    Docks to the side of the QGIS map canvas (like the Layers or Processing
    panels) instead of popping up as a floating dialog, so it stays out of
    the way of the map/site features while you work.
    """

    def __init__(self, iface, parent=None):
        super().__init__("NBR Audit Tool - 4G/5G Sector & Neighbor Relations", parent)
        self.setObjectName("NbrAuditDockWidget")
        self.iface = iface

        # ---- data state ----
        self.ep4g_df = None
        self.ep4g_layer = None
        self.ep4g_key_col = "Key"
        self.ep4g_cellname_col = None

        self.ep5g_df = None
        self.ep5g_layer = None
        self.ep5g_key_col = "Key"
        self.ep5g_cellname_col = None

        self.nrn_df = None       # NRNRELATIONSHIP (LTE-NR), combined from possibly many files
        self.nrc_df = None       # NRCELLRELATION (NR-NR), combined from possibly many files

        # Tracks the audit output layers from the *last* run so a re-run
        # replaces them instead of piling up duplicates (falls back to
        # creating fresh layers if the user deleted the previous ones).
        self._last_audit_layer_ids = {"source": None, "lte_nr": None, "nr_nr": None}

        content = QWidget()
        main_layout = QVBoxLayout(content)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._build_import_tab()
        self._build_styling_tab()
        self._build_relations_tab()
        self._build_audit_tab()

        content.setLayout(main_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.setWidget(scroll)
        self.setMinimumWidth(360)

    # ------------------------------------------------------------------
    # TAB 1: Import EP databases & create sectors
    # ------------------------------------------------------------------
    def _build_import_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.ep4g_group = self._build_ep_group("4G EP Database", is_4g=True)
        self.ep5g_group = self._build_ep_group("5G EP Database", is_4g=False)

        layout.addWidget(self.ep4g_group)
        layout.addWidget(self.ep5g_group)
        layout.addStretch()

        self.tabs.addTab(tab, "1. Import EP && Create Sectors")

    def _build_ep_group(self, title, is_4g):
        group = QGroupBox(title)
        v = QVBoxLayout(group)

        file_row = QHBoxLayout()
        path_edit = QLineEdit()
        path_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse...")
        load_btn = QPushButton("Load Columns")
        file_row.addWidget(QLabel("File:"))
        file_row.addWidget(path_edit, 3)
        file_row.addWidget(browse_btn)
        file_row.addWidget(load_btn)
        v.addLayout(file_row)

        id_form = QFormLayout()
        cellname_combo = QComboBox()
        id_combo = QComboBox()
        cellid_combo = QComboBox()
        lat_combo = QComboBox()
        lon_combo = QComboBox()
        id_form.addRow("CellName column:", cellname_combo)
        id_form.addRow("eNodeB ID (4G) / gNodeB ID (5G) column:", id_combo)
        id_form.addRow("Cell ID column:", cellid_combo)
        id_form.addRow("Latitude column:", lat_combo)
        id_form.addRow("Longitude column:", lon_combo)
        v.addLayout(id_form)

        az_row = FieldMapRow("Azimuth", [], allow_manual=False)
        bw_row = FieldMapRow("Beamwidth", [], allow_manual=True, default_manual="65")
        rad_row = FieldMapRow("Radius (m)", [], allow_manual=True, default_manual="500")
        v.addWidget(az_row)
        v.addWidget(bw_row)
        v.addWidget(rad_row)

        create_btn = QPushButton(f"Create {'4G' if is_4g else '5G'} Sectors")
        status_lbl = QLabel("No layer created yet.")
        status_lbl.setWordWrap(True)
        v.addWidget(create_btn)
        v.addWidget(status_lbl)

        group.path_edit = path_edit
        group.cellname_combo = cellname_combo
        group.id_combo = id_combo
        group.cellid_combo = cellid_combo
        group.lat_combo = lat_combo
        group.lon_combo = lon_combo
        group.az_row = az_row
        group.bw_row = bw_row
        group.rad_row = rad_row
        group.status_lbl = status_lbl
        group.is_4g = is_4g

        browse_btn.clicked.connect(lambda: self._browse_ep_file(group))
        load_btn.clicked.connect(lambda: self._load_ep_columns(group))
        create_btn.clicked.connect(lambda: self._create_sectors(group))

        return group

    def _browse_ep_file(self, group):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select EP database file", "", "Data files (*.csv *.xlsx *.xls *.txt);;All files (*.*)"
        )
        if path:
            group.path_edit.setText(path)

    def _load_ep_columns(self, group):
        path = group.path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "No file", "Please browse to a valid EP file first.")
            return
        try:
            df = file_io_utils.read_table(path)
        except Exception as e:
            QMessageBox.critical(
                self, "Read error",
                f"Could not read file:\n{e}\n\nIf this is a CSV, it may use an unusual delimiter "
                f"or encoding not covered by the automatic fallback."
            )
            return

        if group.is_4g:
            self.ep4g_df = df
        else:
            self.ep5g_df = df

        cols = list(df.columns)
        for combo in (group.cellname_combo, group.id_combo, group.cellid_combo,
                      group.lat_combo, group.lon_combo):
            combo.clear()
            combo.addItems(cols)
        group.az_row.set_columns(cols)
        group.bw_row.set_columns(cols)
        group.rad_row.set_columns(cols)

        self._auto_select(group.lat_combo, cols, ["latitude", "lat"])
        self._auto_select(group.lon_combo, cols, ["longitude", "lon", "long"])
        self._auto_select(group.cellname_combo, cols, ["cellname", "cell name"])
        self._auto_select(group.cellid_combo, cols, ["cellid", "cell id"], exclude=["local"])
        if group.is_4g:
            self._auto_select(group.id_combo, cols, ["enodebid", "enodeb id", "enbid"])
        else:
            self._auto_select(group.id_combo, cols, ["gnodebid", "gnodeb id", "gnbid"])
        self._auto_select(group.az_row.combo, cols, ["azimuth", "az"])

        group.status_lbl.setText(f"Loaded {len(df)} rows, {len(cols)} columns.")

    @staticmethod
    def _auto_select(combo, cols, keywords, exclude=None):
        """
        Best-effort auto-guess of the right column for a semantic field.
        Tries an exact (normalized) match first, then falls back to a
        substring match - but substring matching alone is fooled by columns
        like 'LocalCellId' matching a 'CellId' keyword, so callers can pass
        `exclude` terms (e.g. 'local') to rule those out during the
        substring pass. This is only a convenience default - the user's
        actual drop-down selection always wins, so double-check it.
        """
        exclude = [e.lower() for e in (exclude or [])]
        norm = [(i, c, c.lower().replace("_", "").replace(" ", "")) for i, c in enumerate(cols)]

        # Pass 1: exact normalized match
        for kw in keywords:
            kwn = kw.replace(" ", "").lower()
            for i, c, cl in norm:
                if cl == kwn:
                    combo.setCurrentIndex(i)
                    return

        # Pass 2: substring match, skipping columns containing an excluded term
        for kw in keywords:
            kwn = kw.replace(" ", "").lower()
            for i, c, cl in norm:
                if any(exc in cl for exc in exclude):
                    continue
                if kwn in cl:
                    combo.setCurrentIndex(i)
                    return

    def _create_sectors(self, group):
        df = self.ep4g_df if group.is_4g else self.ep5g_df
        if df is None:
            QMessageBox.warning(self, "No data", "Load the EP file's columns first.")
            return

        id_col = group.id_combo.currentText()
        cellid_col = group.cellid_combo.currentText()
        cellname_col = group.cellname_combo.currentText()
        lat_col = group.lat_combo.currentText()
        lon_col = group.lon_combo.currentText()

        if not all([id_col, cellid_col, cellname_col, lat_col, lon_col]):
            QMessageBox.warning(self, "Missing mapping", "Please map all required columns.")
            return

        az_manual, az_val = group.az_row.value()
        bw_manual, bw_val = group.bw_row.value()
        rad_manual, rad_val = group.rad_row.value()

        if not az_val:
            QMessageBox.warning(self, "Missing value", "Please choose an Azimuth column.")
            return
        if not bw_val or not rad_val:
            QMessageBox.warning(self, "Missing values", "Beamwidth and Radius must be set.")
            return

        try:
            work_df = df.copy()
            work_df["CellName"] = work_df[cellname_col].astype(str)
            key_col = file_io_utils.make_key(work_df, id_col, cellid_col, new_col="Key")

            extra_fields = [cellname_col, id_col, cellid_col, "Key"]
            layer_name = "4G_Sectors" if group.is_4g else "5G_Sectors"

            layer, skipped = sector_utils.build_sector_layer(
                df=work_df,
                layer_name=layer_name,
                lat_col=lat_col,
                lon_col=lon_col,
                azimuth_col=az_val,
                beamwidth_val=bw_val,
                radius_val=rad_val,
                beamwidth_is_column=not bw_manual,
                radius_is_column=not rad_manual,
                extra_fields=extra_fields,
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Sector creation error",
                f"Could not create sectors:\n\n{e}\n\n"
                f"Details:\n{traceback.format_exc(limit=3)}"
            )
            return

        if layer is None or layer.featureCount() == 0:
            QMessageBox.warning(
                self, "No sectors",
                f"No valid sector geometries were created ({skipped} row(s) skipped due to "
                f"missing/invalid Lat, Lon, Azimuth, Beamwidth or Radius values). "
                f"Check your column mapping and that the columns actually contain numbers."
            )
            return

        # keep the enriched dataframe (with CellName/Key columns) as the tracked EP df
        if group.is_4g:
            self.ep4g_df = work_df
        else:
            self.ep5g_df = work_df

        QgsProject.instance().addMapLayer(layer)

        if group.is_4g:
            self.ep4g_layer = layer
            self.ep4g_key_col = key_col
            self.ep4g_cellname_col = "CellName"
        else:
            self.ep5g_layer = layer
            self.ep5g_key_col = key_col
            self.ep5g_cellname_col = "CellName"

        msg = f"Created '{layer_name}' with {layer.featureCount()} sector(s)."
        if skipped:
            msg += f" ({skipped} row(s) skipped due to invalid/missing data.)"
        group.status_lbl.setText(msg)
        self._refresh_layer_combo()
        self._refresh_audit_cell_source()

    # ------------------------------------------------------------------
    # TAB 2: Styling (automatic classification only)
    # ------------------------------------------------------------------
    def _build_styling_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layer_row = QHBoxLayout()
        self.style_layer_combo = QComboBox()
        refresh_btn = QPushButton("Refresh layer list")
        refresh_btn.clicked.connect(self._refresh_layer_combo)
        layer_row.addWidget(QLabel("Target layer:"))
        layer_row.addWidget(self.style_layer_combo, 1)
        layer_row.addWidget(refresh_btn)
        layout.addLayout(layer_row)
        self.style_layer_combo.currentIndexChanged.connect(self._refresh_style_field_combo)

        type_row = QHBoxLayout()
        self.rb_graduated = QRadioButton("Graduated")
        self.rb_categorized = QRadioButton("Categorized")
        self.rb_graduated.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_graduated)
        grp.addButton(self.rb_categorized)
        type_row.addWidget(self.rb_graduated)
        type_row.addWidget(self.rb_categorized)
        type_row.addStretch()
        layout.addLayout(type_row)

        field_row = QHBoxLayout()
        self.style_field_combo = QComboBox()
        field_row.addWidget(QLabel("Field:"))
        field_row.addWidget(self.style_field_combo, 1)
        layout.addLayout(field_row)

        grad_box = QGroupBox("Graduated options")
        grad_form = QFormLayout(grad_box)
        self.grad_classes_spin = QSpinBox()
        self.grad_classes_spin.setRange(2, 20)
        self.grad_classes_spin.setValue(5)
        self.grad_method_combo = QComboBox()
        self.grad_method_combo.addItems(list(style_utils.CLASSIFICATION_METHODS.keys()))
        self.grad_ramp_edit = QLineEdit("Spectral")
        grad_form.addRow("Number of classes:", self.grad_classes_spin)
        grad_form.addRow("Classification method:", self.grad_method_combo)
        grad_form.addRow("Color ramp name:", self.grad_ramp_edit)
        layout.addWidget(grad_box)

        cat_box = QGroupBox("Categorized options")
        cat_form = QFormLayout(cat_box)
        self.cat_ramp_edit = QLineEdit("Set1")
        cat_form.addRow("Color ramp name:", self.cat_ramp_edit)
        layout.addWidget(cat_box)

        apply_btn = QPushButton("Apply Style")
        apply_btn.clicked.connect(self._apply_style)
        layout.addWidget(apply_btn)

        saved_box = QGroupBox("Or load a saved style (.qml) from disk")
        saved_row = QHBoxLayout(saved_box)
        self.qml_path_edit = QLineEdit()
        self.qml_path_edit.setReadOnly(True)
        browse_qml_btn = QPushButton("Browse...")
        apply_qml_btn = QPushButton("Load && Apply Saved Style")
        browse_qml_btn.clicked.connect(self._browse_qml)
        apply_qml_btn.clicked.connect(self._apply_qml)
        saved_row.addWidget(self.qml_path_edit, 1)
        saved_row.addWidget(browse_qml_btn)
        saved_row.addWidget(apply_qml_btn)
        layout.addWidget(saved_box)

        layout.addStretch()
        self.tabs.addTab(tab, "2. Styling")
        self._refresh_layer_combo()

    def _refresh_layer_combo(self):
        self.style_layer_combo.blockSignals(True)
        self.style_layer_combo.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            self.style_layer_combo.addItem(lyr.name(), lyr.id())
        self.style_layer_combo.blockSignals(False)
        self._refresh_style_field_combo()

    def _current_style_layer(self):
        lyr_id = self.style_layer_combo.currentData()
        if not lyr_id:
            return None
        return QgsProject.instance().mapLayer(lyr_id)

    def _refresh_style_field_combo(self):
        self.style_field_combo.clear()
        lyr = self._current_style_layer()
        if lyr is None:
            return
        self.style_field_combo.addItems([f.name() for f in lyr.fields()])

    def _browse_qml(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select saved style", "", "QGIS Style (*.qml)")
        if path:
            self.qml_path_edit.setText(path)

    def _apply_qml(self):
        lyr = self._current_style_layer()
        if lyr is None:
            QMessageBox.warning(self, "No layer", "Select a target layer first.")
            return
        path = self.qml_path_edit.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "No style file", "Browse to a valid .qml file first.")
            return
        ok = style_utils.load_saved_style(lyr, path)
        if ok:
            self.iface.mapCanvas().refresh()
            QMessageBox.information(self, "Style applied", f"Applied saved style to '{lyr.name()}'.")
        else:
            QMessageBox.critical(self, "Failed", "Could not apply the saved style.")

    def _apply_style(self):
        lyr = self._current_style_layer()
        if lyr is None:
            QMessageBox.warning(self, "No layer", "Select a target layer first.")
            return
        field = self.style_field_combo.currentText()
        if not field:
            QMessageBox.warning(self, "No field", "Select a field to style on.")
            return

        try:
            if self.rb_graduated.isChecked():
                style_utils.apply_graduated_style(
                    lyr, field,
                    num_classes=self.grad_classes_spin.value(),
                    method_name=self.grad_method_combo.currentText(),
                    ramp_name=self.grad_ramp_edit.text().strip() or "Spectral",
                )
            else:
                style_utils.apply_categorized_style(
                    lyr, field,
                    ramp_name=self.cat_ramp_edit.text().strip() or "Set1",
                )
        except Exception as e:
            QMessageBox.critical(self, "Styling error", str(e))
            return

        self.iface.mapCanvas().refresh()
        QMessageBox.information(self, "Style applied", f"Style applied to '{lyr.name()}'.")

    # ------------------------------------------------------------------
    # TAB 3: Import relations (multiple files each) & build keys
    # ------------------------------------------------------------------
    def _build_relations_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.nrn_group = self._build_relation_group(
            "NRNRELATIONSHIP file(s) - LTE-NR relations", is_nrn=True
        )
        self.nrc_group = self._build_relation_group(
            "NRCELLRELATION file(s) - NR-NR relations", is_nrn=False
        )
        layout.addWidget(self.nrn_group)
        layout.addWidget(self.nrc_group)
        layout.addStretch()

        self.tabs.addTab(tab, "3. Import Relations && Build Keys")

    def _build_relation_group(self, title, is_nrn):
        group = QGroupBox(title)
        v = QVBoxLayout(group)

        v.addWidget(QLabel(
            "You can select multiple files at once (e.g. when the export is split "
            "across several files) - they will be combined automatically."
        ))

        file_row = QHBoxLayout()
        file_list = QListWidget()
        file_list.setMaximumHeight(80)
        btn_col = QVBoxLayout()
        add_btn = QPushButton("Add file(s)...")
        clear_btn = QPushButton("Clear")
        load_btn = QPushButton("Load Columns")
        btn_col.addWidget(add_btn)
        btn_col.addWidget(clear_btn)
        btn_col.addWidget(load_btn)
        btn_col.addStretch()
        file_row.addWidget(file_list, 3)
        file_row.addLayout(btn_col, 1)
        v.addLayout(file_row)

        form = QFormLayout()
        own_id_combo = None
        own_cellid_combo = None
        nbr_id_combo = None
        nbr_cellid_combo = None
        lte_cellname_combo = None

        if is_nrn:
            # NRNRELATIONSHIP holds one relation per row with two references:
            # an LTE-side CellName, and an NR-side gNodeB ID + Cell ID. Which
            # one is treated as "own" vs "neighbor" depends on whether the
            # audit is run from a 4G or a 5G cell - so both are mapped here,
            # not fixed as own/target.
            lte_cellname_combo = QComboBox()
            own_id_combo = QComboBox()
            own_cellid_combo = QComboBox()
            form.addRow("LTE CellName column (maps to 4G EP):", lte_cellname_combo)
            form.addRow("NR gNodeB ID column (maps to 5G EP):", own_id_combo)
            form.addRow("NR Cell ID column:", own_cellid_combo)
        else:
            # NRCELLRELATION: both sides are NR cells, identified by IDs -
            # matched by key against the 5G EP.
            own_id_combo = QComboBox()
            own_cellid_combo = QComboBox()
            nbr_id_combo = QComboBox()
            nbr_cellid_combo = QComboBox()
            form.addRow("Own/Source gNB ID column:", own_id_combo)
            form.addRow("Own/Source Cell ID column:", own_cellid_combo)
            form.addRow("Neighbor gNB ID column (NR):", nbr_id_combo)
            form.addRow("Neighbor Cell ID column:", nbr_cellid_combo)

        v.addLayout(form)

        build_btn = QPushButton("Build Key && Resolve CellNames from EP")
        status_lbl = QLabel("Not loaded yet.")
        status_lbl.setWordWrap(True)
        v.addWidget(build_btn)
        v.addWidget(status_lbl)

        group.file_list = file_list
        group.own_id_combo = own_id_combo
        group.own_cellid_combo = own_cellid_combo
        group.nbr_id_combo = nbr_id_combo
        group.nbr_cellid_combo = nbr_cellid_combo
        group.lte_cellname_combo = lte_cellname_combo
        group.status_lbl = status_lbl
        group.is_nrn = is_nrn  # True -> LTE-NR file, False -> NR-NR file
        group.file_paths = []

        add_btn.clicked.connect(lambda: self._add_relation_files(group))
        clear_btn.clicked.connect(lambda: self._clear_relation_files(group))
        load_btn.clicked.connect(lambda: self._load_relation_columns(group))
        build_btn.clicked.connect(lambda: self._build_relation_keys(group))

        return group

    def _add_relation_files(self, group):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select relationship file(s) - multiple selection allowed", "",
            "Data files (*.csv *.xlsx *.xls *.txt);;All files (*.*)"
        )
        if paths:
            for p in paths:
                if p not in group.file_paths:
                    group.file_paths.append(p)
                    group.file_list.addItem(p)

    def _clear_relation_files(self, group):
        group.file_paths = []
        group.file_list.clear()

    def _load_relation_columns(self, group):
        if not group.file_paths:
            QMessageBox.warning(self, "No files", "Add at least one file first.")
            return

        df, errors = file_io_utils.read_multiple_tables(group.file_paths)

        if errors:
            details = "\n".join(f"- {os.path.basename(p)}: {msg}" for p, msg in errors)
            QMessageBox.warning(
                self, "Some files failed to load",
                f"{len(errors)} of {len(group.file_paths)} file(s) could not be read and were "
                f"skipped:\n\n{details}"
            )

        if df is None:
            QMessageBox.critical(self, "No data", "None of the selected files could be read.")
            return

        if group.is_nrn:
            self.nrn_df = df
        else:
            self.nrc_df = df

        cols = list(df.columns)
        combos = [group.own_id_combo, group.own_cellid_combo]
        if group.is_nrn:
            combos.append(group.lte_cellname_combo)
        else:
            combos.extend([group.nbr_id_combo, group.nbr_cellid_combo])
        for combo in combos:
            combo.clear()
            combo.addItems(cols)

        self._auto_select(group.own_id_combo, cols, ["gnodebid", "gnbid", "gnodeb id", "gnb id",
                                                       "sourcegnbid", "source gnb id"])
        self._auto_select(group.own_cellid_combo, cols, ["sourcecellid", "source cell id", "cellid"],
                           exclude=["local"])
        if group.is_nrn:
            self._auto_select(group.lte_cellname_combo, cols,
                               ["ltecellname", "lte cell name", "targetcellname",
                                "neighborcellname", "neighbourcellname", "cellname"])
        else:
            self._auto_select(group.nbr_id_combo, cols, ["neighborgnbid", "targetgnbid",
                                                           "neighbourgnbid", "ngnbid"])
            self._auto_select(group.nbr_cellid_combo, cols, ["neighborcellid", "targetcellid",
                                                               "neighbourcellid", "ncellid"],
                               exclude=["local"])

        group.status_lbl.setText(
            f"Loaded {len(df)} row(s) from {len(group.file_paths)} file(s), {len(cols)} column(s)."
        )

    def _build_relation_keys(self, group):
        df = self.nrn_df if group.is_nrn else self.nrc_df
        if df is None:
            QMessageBox.warning(self, "No data", "Load the relation file(s) columns first.")
            return

        own_id_col = group.own_id_combo.currentText()
        own_cellid_col = group.own_cellid_combo.currentText()

        if group.is_nrn:
            lte_cellname_col = group.lte_cellname_combo.currentText()
            if not all([own_id_col, own_cellid_col, lte_cellname_col]):
                QMessageBox.warning(self, "Missing mapping", "Please map the LTE CellName, "
                                                               "NR gNodeB ID, and NR Cell ID columns.")
                return
        else:
            nbr_id_col = group.nbr_id_combo.currentText()
            nbr_cellid_col = group.nbr_cellid_combo.currentText()
            if not all([own_id_col, own_cellid_col, nbr_id_col, nbr_cellid_col]):
                QMessageBox.warning(self, "Missing mapping", "Please map all four ID columns.")
                return

        try:
            work_df = df.copy()
            if group.is_nrn:
                # NR-side reference: gNodeB ID + Cell ID -> 5G-format key
                file_io_utils.make_key(work_df, own_id_col, own_cellid_col, new_col="NRKey")
            else:
                file_io_utils.make_key(work_df, own_id_col, own_cellid_col, new_col="OwnKey")
                file_io_utils.make_key(work_df, nbr_id_col, nbr_cellid_col, new_col="TargetKey")
        except Exception as e:
            QMessageBox.critical(self, "Key build error", f"Could not build keys:\n{e}")
            return

        msgs = []
        low_matches = []  # (label, matched, total) for rates worth flagging

        def _check(label, matched, total):
            if total > 20 and matched / total < 0.5:
                low_matches.append((label, matched, total))

        if group.is_nrn:
            # NR-side reference: resolve against the 5G EP by key (also gives
            # us the NR CellName for display/validation).
            if self.ep5g_df is not None and self.ep5g_key_col in self.ep5g_df.columns:
                work_df, matched, total = file_io_utils.resolve_cellname_by_key(
                    work_df, "NRKey", self.ep5g_df, self.ep5g_key_col,
                    self.ep5g_cellname_col or "CellName", out_col="NRCellName"
                )
                msgs.append(f"NR side (gNodeB ID+Cell ID) resolved for {matched}/{total} row(s) "
                             f"via 5G EP key.")
                _check("NR side (gNodeB ID+Cell ID) vs 5G EP", matched, total)
            else:
                msgs.append("5G EP not created yet - cannot resolve the NR side.")

            # LTE-side reference: given directly as a CellName - text-match
            # it against the 4G EP CellName to get its Key.
            if self.ep4g_df is not None and self.ep4g_cellname_col:
                work_df, matched, total = file_io_utils.resolve_key_by_cellname(
                    work_df, lte_cellname_col, self.ep4g_df, self.ep4g_cellname_col,
                    self.ep4g_key_col, out_col="LTEKey"
                )
                work_df["LTECellName"] = work_df[lte_cellname_col].astype(str)
                msgs.append(f"LTE side (CellName) matched to 4G EP for {matched}/{total} row(s).")
                _check("LTE side (CellName) vs 4G EP", matched, total)
            else:
                msgs.append("4G EP not created yet - cannot resolve the LTE side.")
        else:
            if self.ep5g_df is not None and self.ep5g_key_col in self.ep5g_df.columns:
                work_df, matched, total = file_io_utils.resolve_cellname_by_key(
                    work_df, "OwnKey", self.ep5g_df, self.ep5g_key_col,
                    self.ep5g_cellname_col or "CellName", out_col="OwnCellName"
                )
                msgs.append(f"Own(NR) cell resolved for {matched}/{total} row(s) via 5G EP key.")
                _check("Own/Source (gNB ID+Cell ID) vs 5G EP", matched, total)
                work_df, matched, total = file_io_utils.resolve_cellname_by_key(
                    work_df, "TargetKey", self.ep5g_df, self.ep5g_key_col,
                    self.ep5g_cellname_col or "CellName", out_col="TargetCellName"
                )
                msgs.append(f"Neighbor(NR) cell resolved for {matched}/{total} row(s) via 5G EP key.")
                _check("Neighbor (gNB ID+Cell ID) vs 5G EP", matched, total)
            else:
                msgs.append("5G EP not created yet - cannot resolve own/neighbor cells.")

        if group.is_nrn:
            self.nrn_df = work_df
        else:
            self.nrc_df = work_df

        group.status_lbl.setText(" | ".join(msgs))
        self._refresh_audit_cell_source()

        if low_matches:
            details = "\n".join(
                f"- {label}: only {m}/{t} matched ({100*m/t:.1f}%)" for label, m, t in low_matches
            )
            QMessageBox.warning(
                self, "Low match rate - check your column mapping",
                f"One or more mappings matched fewer than half the rows:\n\n{details}\n\n"
                f"This usually means the wrong column was picked for an ID/Cell ID field - e.g. "
                f"a sequence/local-index column (like 'LocalCellId') instead of the real Cell ID "
                f"column that matches the EP file. Please double-check the drop-downs above and "
                f"re-run 'Build Key & Resolve CellNames from EP'."
            )

    # ------------------------------------------------------------------
    # TAB 4: NBR Audit
    # ------------------------------------------------------------------
    def _build_audit_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Check against:"))
        self.audit_type_combo = QComboBox()
        self.audit_type_combo.addItems(["4G Cell", "5G Cell"])
        self.audit_type_combo.currentIndexChanged.connect(self._refresh_audit_cell_source)
        type_row.addWidget(self.audit_type_combo)
        type_row.addStretch()
        layout.addLayout(type_row)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Cell name:"))
        self.audit_cell_combo = QComboBox()
        self.audit_cell_combo.setEditable(True)
        self.audit_cell_combo.setInsertPolicy(QComboBox.NoInsert)
        self._audit_completer = QCompleter()
        self._audit_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._audit_completer.setFilterMode(Qt.MatchContains)
        self.audit_cell_combo.setCompleter(self._audit_completer)
        search_row.addWidget(self.audit_cell_combo, 1)
        layout.addLayout(search_row)

        run_btn = QPushButton("Run NBR Audit")
        run_btn.clicked.connect(self._run_audit)
        layout.addWidget(run_btn)

        self.audit_status_lbl = QLabel("")
        self.audit_status_lbl.setWordWrap(True)
        layout.addWidget(self.audit_status_lbl)

        layout.addStretch()
        self.tabs.addTab(tab, "4. NBR Audit")

    def _refresh_audit_cell_source(self):
        is_4g = self.audit_type_combo.currentText().startswith("4G")
        df = self.ep4g_df if is_4g else self.ep5g_df
        cellname_col = self.ep4g_cellname_col if is_4g else self.ep5g_cellname_col
        self.audit_cell_combo.clear()
        if df is not None and cellname_col and cellname_col in df.columns:
            names = sorted(set(df[cellname_col].astype(str)))
            self.audit_cell_combo.addItems(names)
            self._audit_completer.setModel(QStringListModel(names))

    def _run_audit(self):
        is_4g = self.audit_type_combo.currentText().startswith("4G")
        cellname = self.audit_cell_combo.currentText().strip()
        if not cellname:
            QMessageBox.warning(self, "No cell", "Type or select a cell name first.")
            return

        try:
            if is_4g:
                self._run_audit_4g(cellname)
            else:
                self._run_audit_5g(cellname)
        except Exception as e:
            QMessageBox.critical(
                self, "Audit error",
                f"Something went wrong running the audit:\n\n{e}\n\n{traceback.format_exc(limit=3)}"
            )
            return

        # Keep the searched cell visibly on top of its relation layers,
        # regardless of the order the layers were (re)created in.
        source_id = self._last_audit_layer_ids.get("source")
        if source_id:
            self._move_layer_to_top(source_id)

    # colors used to highlight audit results: the cell the user searched for
    # vs. the neighbor/relation cells found for it
    SOURCE_COLOR = "#ffe415"    # bright yellow - the searched/own cell
    LTE_NR_COLOR = "#1f77b4"    # blue - LTE-NR relation cells
    NR_NR_COLOR = "#2ca02c"     # green - NR-NR relation cells

    def _move_layer_to_top(self, layer_id):
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer_id)
        if node is None:
            return
        parent = node.parent() or root
        clone = node.clone()
        parent.insertChildNode(0, clone)
        parent.removeChildNode(node)

    def _add_filtered_layer(self, source_layer, keys, out_name, color_hex=None, opacity=0.6,
                             slot=None):
        """
        Create a new memory layer containing only the features of
        source_layer whose 'Key' attribute is in `keys`, styled with a flat
        highlight color.

        `slot` identifies this output's role ("source" / "lte_nr" / "nr_nr").
        Re-running the audit removes whatever layer previously occupied that
        slot first (if it still exists - the user may have deleted it) and
        replaces it, instead of piling up duplicate layers on every search.
        """
        if slot:
            old_id = self._last_audit_layer_ids.get(slot)
            if old_id and QgsProject.instance().mapLayer(old_id) is not None:
                QgsProject.instance().removeMapLayer(old_id)
            self._last_audit_layer_ids[slot] = None

        if source_layer is None:
            return None, 0
        keys = {k for k in keys if k}
        if not keys:
            return None, 0

        clone = source_layer.clone()
        clone.setName(out_name)
        provider = clone.dataProvider()
        key_idx = clone.fields().indexOf("Key")
        ids_to_delete = []
        for f in clone.getFeatures():
            if key_idx < 0 or str(f["Key"]) not in keys:
                ids_to_delete.append(f.id())
        provider.deleteFeatures(ids_to_delete)
        clone.updateExtents()

        if clone.featureCount() == 0:
            return None, 0

        QgsProject.instance().addMapLayer(clone)
        if color_hex:
            style_utils.apply_single_color_style(clone, color_hex, opacity=opacity)
        if slot:
            self._last_audit_layer_ids[slot] = clone.id()
        return clone, clone.featureCount()

    def _highlight_source_cell(self, cellname, source_layer, source_key):
        """Add a single-feature layer for the audited cell itself, in bright
        yellow at full opacity, on top of its relation layers."""
        self._add_filtered_layer(
            source_layer, {source_key}, f"Source Cell - {cellname}",
            color_hex=self.SOURCE_COLOR, opacity=1.0, slot="source"
        )

    def _run_audit_4g(self, cellname):
        if self.ep4g_df is None or self.nrn_df is None or "LTEKey" not in self.nrn_df.columns:
            QMessageBox.warning(
                self, "Missing data",
                "Load 4G EP sectors and build the NRNRELATIONSHIP keys first (Tab 3)."
            )
            return
        match = self.ep4g_df[self.ep4g_df[self.ep4g_cellname_col].astype(str) == cellname]
        if match.empty:
            QMessageBox.warning(self, "Not found", f"Cell '{cellname}' not found in 4G EP.")
            return
        own_key = str(match.iloc[0][self.ep4g_key_col])

        self._highlight_source_cell(cellname, self.ep4g_layer, own_key)

        # Own cell = LTE CellName side (LTEKey); the NR-side reference on the
        # same rows (NRKey) gives the neighbor 5G cells to plot.
        related_rows = self.nrn_df[self.nrn_df["LTEKey"] == own_key]
        relation_keys = set(related_rows["NRKey"].astype(str)) if "NRKey" in related_rows else set()

        layer, count = self._add_filtered_layer(
            self.ep5g_layer, relation_keys, "LTE-NR relations",
            color_hex=self.LTE_NR_COLOR, slot="lte_nr"
        )
        if layer is None:
            self.audit_status_lbl.setText(
                f"{len(related_rows)} relation row(s) matched 4G cell '{cellname}', but no "
                f"corresponding 5G sectors could be plotted (check that 5G sectors were created)."
            )
        else:
            self.audit_status_lbl.setText(
                f"'LTE-NR relations' layer created with {count} sector(s) related to 4G cell '{cellname}'."
            )

    def _run_audit_5g(self, cellname):
        if self.ep5g_df is None:
            QMessageBox.warning(self, "Missing data", "Load 5G EP sectors first.")
            return
        match = self.ep5g_df[self.ep5g_df[self.ep5g_cellname_col].astype(str) == cellname]
        if match.empty:
            QMessageBox.warning(self, "Not found", f"Cell '{cellname}' not found in 5G EP.")
            return
        own_key = str(match.iloc[0][self.ep5g_key_col])

        self._highlight_source_cell(cellname, self.ep5g_layer, own_key)

        msgs = []

        # LTE-NR relations: own cell = NR-side reference (NRKey); the LTE-side
        # reference on the same rows (LTEKey) gives the neighbor 4G cells.
        if self.nrn_df is not None and "NRKey" in self.nrn_df.columns:
            rows = self.nrn_df[self.nrn_df["NRKey"] == own_key]
            relation_keys = set(rows["LTEKey"].astype(str)) if "LTEKey" in rows else set()
            layer, count = self._add_filtered_layer(
                self.ep4g_layer, relation_keys, "LTE-NR relations",
                color_hex=self.LTE_NR_COLOR, slot="lte_nr"
            )
            if layer is None:
                msgs.append(f"No LTE-NR relation cells found for '{cellname}'.")
            else:
                msgs.append(f"'LTE-NR relations' layer created with {count} sector(s).")
        else:
            msgs.append("NRNRELATIONSHIP not loaded/keyed - skipped LTE-NR output.")

        if self.nrc_df is not None and "OwnKey" in self.nrc_df.columns:
            rows = self.nrc_df[self.nrc_df["OwnKey"] == own_key]
            relation_keys = set(rows["TargetKey"].astype(str)) if "TargetKey" in rows else set()
            layer, count = self._add_filtered_layer(
                self.ep5g_layer, relation_keys, "NR-NR relations",
                color_hex=self.NR_NR_COLOR, slot="nr_nr"
            )
            if layer is None:
                msgs.append(f"No NR-NR relation cells found for '{cellname}'.")
            else:
                msgs.append(f"'NR-NR relations' layer created with {count} sector(s).")
        else:
            msgs.append("NRCELLRELATION not loaded/keyed - skipped NR-NR output.")

        self.audit_status_lbl.setText(" | ".join(msgs))
