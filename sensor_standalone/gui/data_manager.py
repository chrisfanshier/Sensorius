"""Data Manager — cruises, cores, sensor files, and winch files."""
from __future__ import annotations

import os

from pyqtgraph.Qt import QtWidgets, QtCore

from ..formats import SENSOR_LOCATIONS, SENSOR_BRANDS
from ..persistence.project import ProjectStore
from .winch_dialog import WinchImportDialog


def _dt_edit(initial=None) -> QtWidgets.QDateTimeEdit:
    edit = QtWidgets.QDateTimeEdit()
    edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    edit.setCalendarPopup(True)
    edit.setTimeSpec(QtCore.Qt.UTC)
    if initial:
        edit.setDateTime(QtCore.QDateTime.fromString(str(initial)[:19], "yyyy-MM-dd HH:mm:ss"))
    else:
        edit.setDateTime(QtCore.QDateTime.currentDateTimeUtc())
    return edit


def _dt_value(edit: QtWidgets.QDateTimeEdit) -> str:
    return edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")


def _optional_float(text: str):
    text = (text or "").strip()
    if not text:
        return None
    return float(text)


class CruiseDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, cruise=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Cruise" if cruise else "New Cruise")
        form = QtWidgets.QFormLayout(self)
        self.name_edit = QtWidgets.QLineEdit(cruise["cruise_name"] if cruise else "")
        self.vessel_edit = QtWidgets.QLineEdit((cruise and cruise.get("vessel_name")) or "")
        self.notes_edit = QtWidgets.QLineEdit((cruise and cruise.get("notes")) or "")
        form.addRow("Cruise name*:", self.name_edit)
        form.addRow("Vessel:", self.vessel_edit)
        form.addRow("Notes:", self.notes_edit)
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _validate(self):
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Please enter a cruise name.")
            return
        self.accept()

    def values(self):
        return (
            self.name_edit.text().strip(),
            self.vessel_edit.text().strip() or None,
            self.notes_edit.text().strip() or None,
        )


class CoreDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, core=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Core" if core else "New Core")
        form = QtWidgets.QFormLayout(self)

        self.name_edit = QtWidgets.QLineEdit(core["core_name"] if core else "")
        self.type_edit = QtWidgets.QLineEdit((core and core.get("core_type")) or "Jumbo Piston Core")
        self.length_edit = QtWidgets.QLineEdit("" if not core or core.get("core_length") is None else str(core["core_length"]))
        self.scope_edit = QtWidgets.QLineEdit("" if not core or core.get("scope") is None else str(core["scope"]))
        self.start_edit = _dt_edit(core and core.get("start_datetime"))
        self.end_edit = _dt_edit(core and core.get("end_datetime"))
        self.trigger_line_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_line_length") is None else str(core["trigger_line_length"])
        )
        self.trigger_core_len_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_core_length") is None else str(core["trigger_core_length"])
        )
        self.trigger_pen_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_core_penetration") is None else str(core["trigger_core_penetration"])
        )
        self.trigger_recovery_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("trigger_core_recovery") is None else str(core["trigger_core_recovery"])
        )
        self.piston_recovery_edit = QtWidgets.QLineEdit(
            "" if not core or core.get("piston_core_recovery") is None else str(core["piston_core_recovery"])
        )
        self.pig_edit = QtWidgets.QLineEdit((core and core.get("pig_weights")) or "")
        self.wire_edit = QtWidgets.QLineEdit((core and core.get("wire_type")) or "")
        self.notes_edit = QtWidgets.QLineEdit((core and core.get("notes")) or "")

        form.addRow("Core name*:", self.name_edit)
        form.addRow("Core type:", self.type_edit)
        form.addRow("Core length (ft):", self.length_edit)
        form.addRow("Scope (ft):", self.scope_edit)
        form.addRow("Deploy start (UTC):", self.start_edit)
        form.addRow("Deploy end (UTC):", self.end_edit)
        form.addRow("Trigger line length (ft):", self.trigger_line_edit)
        form.addRow("Trigger core length (ft):", self.trigger_core_len_edit)
        form.addRow("Trigger core penetration (m):", self.trigger_pen_edit)
        form.addRow("Trigger core recovery:", self.trigger_recovery_edit)
        form.addRow("Piston core recovery:", self.piston_recovery_edit)
        form.addRow("Pig weights:", self.pig_edit)
        form.addRow("Wire type:", self.wire_edit)
        form.addRow("Notes:", self.notes_edit)

        hint = QtWidgets.QLabel(
            "Deployment start/end are used to match winch files.\n"
            "Missing fields won't block analysis — modes degrade gracefully."
        )
        hint.setStyleSheet("color: gray; font-size: 10px;")
        form.addRow(hint)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _validate(self):
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Missing Name", "Please enter a core name.")
            return
        self.accept()

    def values(self) -> dict:
        return {
            "core_name": self.name_edit.text().strip(),
            "core_type": self.type_edit.text().strip() or None,
            "core_length": _optional_float(self.length_edit.text()),
            "scope": _optional_float(self.scope_edit.text()),
            "start_datetime": _dt_value(self.start_edit),
            "end_datetime": _dt_value(self.end_edit),
            "trigger_line_length": _optional_float(self.trigger_line_edit.text()),
            "trigger_core_length": _optional_float(self.trigger_core_len_edit.text()),
            "trigger_core_penetration": _optional_float(self.trigger_pen_edit.text()),
            "trigger_core_recovery": _optional_float(self.trigger_recovery_edit.text()),
            "piston_core_recovery": _optional_float(self.piston_recovery_edit.text()),
            "pig_weights": self.pig_edit.text().strip() or None,
            "wire_type": self.wire_edit.text().strip() or None,
            "notes": self.notes_edit.text().strip() or None,
        }


class SensorFileDialog(QtWidgets.QDialog):
    """Register one or more sensor files with location and brand (parser driver)."""

    def __init__(self, file_names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Register Sensor Files")
        self.location: str | None = None
        self.sensor_type: str | None = None
        self.remarks: str = ""

        form = QtWidgets.QFormLayout(self)
        files_label = QtWidgets.QLabel(
            "\n".join(file_names) if len(file_names) <= 3
            else f"{file_names[0]}\n… and {len(file_names) - 1} more"
        )
        files_label.setWordWrap(True)
        form.addRow("Files:", files_label)

        self.location_combo = QtWidgets.QComboBox()
        self.location_combo.addItems(SENSOR_LOCATIONS + ["Other…"])
        form.addRow("Sensor location*:", self.location_combo)

        self.other_location_edit = QtWidgets.QLineEdit()
        self.other_location_edit.setPlaceholderText("Custom location name")
        self.other_location_edit.setVisible(False)
        self.location_combo.currentTextChanged.connect(self._on_location_changed)
        form.addRow("", self.other_location_edit)

        self.brand_combo = QtWidgets.QComboBox()
        self.brand_combo.addItems(SENSOR_BRANDS)
        form.addRow("Sensor brand*:", self.brand_combo)

        hint = QtWidgets.QLabel(
            "Brand selects the parser (RBR .rsk vs Star-Oddi .dat/.acc/.txt).\n"
            "Location becomes the column prefix and drives auto-detection in\n"
            "Calculate mode (Weight Stand, Release Device, Trigger Core/Weight)."
        )
        hint.setStyleSheet("color: gray; font-size: 10px;")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.remarks_edit = QtWidgets.QLineEdit()
        self.remarks_edit.setPlaceholderText("Optional remarks")
        form.addRow("Remarks:", self.remarks_edit)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        btns.accepted.connect(self._validate)
        btns.rejected.connect(self.reject)
        form.addRow(btns)

    def _on_location_changed(self, text: str):
        self.other_location_edit.setVisible(text == "Other…")

    def _validate(self):
        loc = self.location_combo.currentText()
        if loc == "Other…":
            loc = self.other_location_edit.text().strip()
        if not loc:
            QtWidgets.QMessageBox.warning(
                self, "Missing Location",
                "Choose a sensor location (Weight Stand, Release Device, "
                "Trigger Core/Weight, or enter a custom location)."
            )
            return
        self.location = loc
        self.sensor_type = self.brand_combo.currentText()
        self.remarks = self.remarks_edit.text().strip()
        self.accept()


class DataManagerPage(QtWidgets.QWidget):
    dataChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store: ProjectStore | None = None
        self._cruises: list[dict] = []
        self._cores: list[dict] = []
        self._build_ui()

    def set_store(self, store: ProjectStore | None):
        self.store = store
        self._set_enabled(store is not None)
        self.refresh(keep_selection=False)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        cruise_row = QtWidgets.QHBoxLayout()
        cruise_row.addWidget(QtWidgets.QLabel("Cruise:"))
        self.cruise_combo = QtWidgets.QComboBox()
        self.cruise_combo.currentIndexChanged.connect(self._on_cruise_changed)
        cruise_row.addWidget(self.cruise_combo, stretch=1)
        self.add_cruise_btn = QtWidgets.QPushButton("New Cruise")
        self.add_cruise_btn.clicked.connect(self._add_cruise)
        self.edit_cruise_btn = QtWidgets.QPushButton("Edit")
        self.edit_cruise_btn.clicked.connect(self._edit_cruise)
        self.del_cruise_btn = QtWidgets.QPushButton("Delete")
        self.del_cruise_btn.clicked.connect(self._delete_cruise)
        cruise_row.addWidget(self.add_cruise_btn)
        cruise_row.addWidget(self.edit_cruise_btn)
        cruise_row.addWidget(self.del_cruise_btn)
        layout.addLayout(cruise_row)

        core_row = QtWidgets.QHBoxLayout()
        core_row.addWidget(QtWidgets.QLabel("Core:"))
        self.core_combo = QtWidgets.QComboBox()
        self.core_combo.currentIndexChanged.connect(self._on_core_changed)
        core_row.addWidget(self.core_combo, stretch=1)
        self.add_core_btn = QtWidgets.QPushButton("New Core")
        self.add_core_btn.clicked.connect(self._add_core)
        self.edit_core_btn = QtWidgets.QPushButton("Edit")
        self.edit_core_btn.clicked.connect(self._edit_core)
        self.del_core_btn = QtWidgets.QPushButton("Delete")
        self.del_core_btn.clicked.connect(self._delete_core)
        core_row.addWidget(self.add_core_btn)
        core_row.addWidget(self.edit_core_btn)
        core_row.addWidget(self.del_core_btn)
        layout.addLayout(core_row)

        tabs = QtWidgets.QTabWidget()
        self.sensor_table = QtWidgets.QTableWidget(0, 4)
        self.sensor_table.setHorizontalHeaderLabels(
            ["File", "Location", "Type", "Remarks"]
        )
        self.sensor_table.horizontalHeader().setStretchLastSection(True)
        sensor_btns = QtWidgets.QHBoxLayout()
        add_sensor = QtWidgets.QPushButton("Add Sensor File(s)…")
        add_sensor.clicked.connect(self._add_sensor_files)
        del_sensor = QtWidgets.QPushButton("Remove Selected")
        del_sensor.clicked.connect(self._delete_sensor_file)
        sensor_btns.addWidget(add_sensor)
        sensor_btns.addWidget(del_sensor)
        sensor_btns.addStretch()
        sensor_page = QtWidgets.QWidget()
        sp_layout = QtWidgets.QVBoxLayout(sensor_page)
        sp_layout.addWidget(self.sensor_table)
        sp_layout.addLayout(sensor_btns)
        tabs.addTab(sensor_page, "Sensor Files")

        self.winch_table = QtWidgets.QTableWidget(0, 4)
        self.winch_table.setHorizontalHeaderLabels(
            ["File", "Start", "End", "Notes"]
        )
        self.winch_table.horizontalHeader().setStretchLastSection(True)
        winch_btns = QtWidgets.QHBoxLayout()
        add_winch = QtWidgets.QPushButton("Add Winch File…")
        add_winch.clicked.connect(self._add_winch_file)
        del_winch = QtWidgets.QPushButton("Remove Selected")
        del_winch.clicked.connect(self._delete_winch_file)
        winch_btns.addWidget(add_winch)
        winch_btns.addWidget(del_winch)
        winch_btns.addStretch()
        winch_page = QtWidgets.QWidget()
        wp_layout = QtWidgets.QVBoxLayout(winch_page)
        wp_layout.addWidget(self.winch_table)
        wp_layout.addLayout(winch_btns)
        tabs.addTab(winch_page, "Winch Files (per cruise)")

        layout.addWidget(tabs)
        self._set_enabled(False)

    def _set_enabled(self, on: bool):
        for w in (
            self.cruise_combo, self.add_cruise_btn, self.edit_cruise_btn, self.del_cruise_btn,
            self.core_combo, self.add_core_btn, self.edit_core_btn, self.del_core_btn,
        ):
            w.setEnabled(on)

    def _current_cruise(self) -> dict | None:
        idx = self.cruise_combo.currentIndex()
        if 0 <= idx < len(self._cruises):
            return self._cruises[idx]
        return None

    def _current_core(self) -> dict | None:
        idx = self.core_combo.currentIndex()
        if 0 <= idx < len(self._cores):
            return self._cores[idx]
        return None

    def refresh(self, keep_selection: bool = True):
        """Reload cruises/cores/files from the store."""
        prev_cruise_id = None
        prev_core_id = None
        if keep_selection:
            cruise = self._current_cruise()
            core = self._current_core()
            prev_cruise_id = cruise["cruise_id"] if cruise else None
            prev_core_id = core["core_id"] if core else None

        self.cruise_combo.blockSignals(True)
        self.cruise_combo.clear()
        self._cruises = self.store.fetch_cruises() if self.store else []
        for cr in self._cruises:
            label = cr["cruise_name"]
            if cr.get("vessel_name"):
                label += f" — {cr['vessel_name']}"
            self.cruise_combo.addItem(label)

        cruise_index = 0 if self._cruises else -1
        if prev_cruise_id is not None:
            for i, cr in enumerate(self._cruises):
                if cr["cruise_id"] == prev_cruise_id:
                    cruise_index = i
                    break
        self.cruise_combo.setCurrentIndex(cruise_index if self._cruises else -1)
        self.cruise_combo.blockSignals(False)

        self._refresh_cruise_details(prev_core_id=prev_core_id if keep_selection else None)

    def _refresh_cruise_details(self, prev_core_id: int | None = None):
        cruise = self._current_cruise()

        self.core_combo.blockSignals(True)
        self.core_combo.clear()
        self._cores = []
        if cruise is not None:
            self._cores = self.store.fetch_cores(cruise["cruise_id"])
            for c in self._cores:
                self.core_combo.addItem(c["core_name"])

        core_index = -1
        if prev_core_id is not None:
            for i, c in enumerate(self._cores):
                if c["core_id"] == prev_core_id:
                    core_index = i
                    break
        elif len(self._cores) == 1:
            core_index = 0
        self.core_combo.setCurrentIndex(core_index)
        self.core_combo.blockSignals(False)

        self._refresh_sensor_files()
        self._refresh_winch_files()

    def _refresh_cruises(self):
        """Backward-compatible alias."""
        self.refresh(keep_selection=True)

    def _refresh_sensor_files(self):
        self.sensor_table.setRowCount(0)
        core = self._current_core()
        if not self.store or core is None:
            return
        for sf in self.store.fetch_sensor_files(core["core_id"]):
            row = self.sensor_table.rowCount()
            self.sensor_table.insertRow(row)
            self.sensor_table.setItem(row, 0, QtWidgets.QTableWidgetItem(sf["file_name"]))
            self.sensor_table.setItem(row, 1, QtWidgets.QTableWidgetItem(sf.get("sensor_location") or ""))
            self.sensor_table.setItem(row, 2, QtWidgets.QTableWidgetItem(sf.get("sensor_type") or ""))
            self.sensor_table.setItem(row, 3, QtWidgets.QTableWidgetItem(sf.get("remarks") or ""))
            self.sensor_table.item(row, 0).setData(QtCore.Qt.UserRole, sf["sensor_file_id"])

    def _refresh_winch_files(self):
        self.winch_table.setRowCount(0)
        cruise = self._current_cruise()
        if not self.store or cruise is None:
            return
        for wf in self.store.fetch_winch_files(cruise["cruise_id"]):
            row = self.winch_table.rowCount()
            self.winch_table.insertRow(row)
            self.winch_table.setItem(row, 0, QtWidgets.QTableWidgetItem(wf["file_name"]))
            self.winch_table.setItem(row, 1, QtWidgets.QTableWidgetItem(str(wf.get("start_time") or "")))
            self.winch_table.setItem(row, 2, QtWidgets.QTableWidgetItem(str(wf.get("end_time") or "")))
            self.winch_table.setItem(row, 3, QtWidgets.QTableWidgetItem(wf.get("notes") or ""))
            self.winch_table.item(row, 0).setData(QtCore.Qt.UserRole, wf["winch_file_id"])

    def _on_cruise_changed(self, index: int):
        self._refresh_cruise_details()

    def _on_core_changed(self, index: int):
        self._refresh_sensor_files()

    def _add_cruise(self):
        dlg = CruiseDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        name, vessel, notes = dlg.values()
        self.store.add_cruise(name, vessel, notes)
        self.refresh(keep_selection=False)
        for i, cr in enumerate(self._cruises):
            if cr["cruise_name"] == name:
                self.cruise_combo.setCurrentIndex(i)
                self._refresh_cruise_details()
                break
        self.dataChanged.emit()

    def _edit_cruise(self):
        cruise = self._current_cruise()
        if cruise is None:
            return
        dlg = CruiseDialog(self, cruise)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        name, vessel, notes = dlg.values()
        self.store.update_cruise(cruise["cruise_id"], name, vessel, notes)
        self.refresh(keep_selection=True)
        self.dataChanged.emit()

    def _delete_cruise(self):
        cruise = self._current_cruise()
        if cruise is None:
            return
        if QtWidgets.QMessageBox.question(
            self, "Delete Cruise", "Delete this cruise and all cores/files?",
        ) != QtWidgets.QMessageBox.Yes:
            return
        self.store.delete_cruise(cruise["cruise_id"])
        self.refresh(keep_selection=False)
        self.dataChanged.emit()

    def _add_core(self):
        cruise = self._current_cruise()
        if cruise is None:
            if not self._cruises:
                QtWidgets.QMessageBox.information(
                    self, "No Cruise",
                    "Create a cruise first using the New Cruise button, then add a core.",
                )
            else:
                QtWidgets.QMessageBox.information(
                    self, "No Cruise Selected",
                    "Select a cruise from the dropdown above before adding a core.",
                )
            return
        dlg = CoreDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        core_id = self.store.add_core(cruise["cruise_id"], **dlg.values())
        self._refresh_cruise_details()
        for i, c in enumerate(self._cores):
            if c["core_id"] == core_id:
                self.core_combo.setCurrentIndex(i)
                break
        self._refresh_sensor_files()
        self.dataChanged.emit()

    def _edit_core(self):
        core = self._current_core()
        if core is None:
            return
        dlg = CoreDialog(self, core)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.store.update_core(core["core_id"], **dlg.values())
        self._refresh_cruise_details(prev_core_id=core["core_id"])
        self.dataChanged.emit()

    def _delete_core(self):
        core = self._current_core()
        if core is None:
            return
        if QtWidgets.QMessageBox.question(
            self, "Delete Core", "Delete this core and all sensor files?",
        ) != QtWidgets.QMessageBox.Yes:
            return
        self.store.delete_core(core["core_id"])
        self._refresh_cruise_details()
        self.dataChanged.emit()

    def _add_sensor_files(self):
        core = self._current_core()
        if core is None:
            QtWidgets.QMessageBox.information(
                self, "No Core Selected",
                "Select a core from the dropdown, or create one with New Core, "
                "before adding sensor files.",
            )
            return

        brand = SENSOR_BRANDS[0]
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Select Sensor Files", "",
            "Sensor files (*.rsk *.dat *.acc *.txt);;All files (*)",
        )
        if not paths:
            return

        dlg = SensorFileDialog([os.path.basename(p) for p in paths], self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            brand = dlg.sensor_type or ""
            if brand == "RBR Sensor" and ext != ".rsk":
                QtWidgets.QMessageBox.warning(
                    self, "File Type Mismatch",
                    f"{os.path.basename(path)}: RBR Sensor files must be .rsk",
                )
                continue
            if brand == "Star-Oddi Sensor" and ext not in (".dat", ".acc", ".txt"):
                QtWidgets.QMessageBox.warning(
                    self, "File Type Mismatch",
                    f"{os.path.basename(path)}: Star-Oddi Sensor files must be "
                    ".dat, .acc, or .txt",
                )
                continue
            try:
                self.store.add_sensor_file(
                    core["core_id"], path, sensor_location=dlg.location,
                    sensor_type=dlg.sensor_type, remarks=dlg.remarks or None,
                )
            except Exception as exc:
                QtWidgets.QMessageBox.warning(self, "Import Error", f"{path}:\n{exc}")
        self._refresh_sensor_files()
        self.dataChanged.emit()

    def _delete_sensor_file(self):
        row = self.sensor_table.currentRow()
        if row < 0:
            return
        fid = self.sensor_table.item(row, 0).data(QtCore.Qt.UserRole)
        self.store.delete_sensor_file(fid)
        self._refresh_sensor_files()
        self.dataChanged.emit()

    def _add_winch_file(self):
        cruise = self._current_cruise()
        if cruise is None:
            QtWidgets.QMessageBox.information(
                self, "No Cruise Selected",
                "Select a cruise from the dropdown before adding winch files.",
            )
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Winch File", "",
            "Winch files (*.dat *.csv *.txt *.raw);;All files (*)",
        )
        if not path:
            return
        dlg = WinchImportDialog(path, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.store.add_winch_file(
            cruise["cruise_id"], path, dlg.settings,
            start_time=dlg.start_time, end_time=dlg.end_time,
            notes=dlg.notes,
        )
        self._refresh_winch_files()
        self.dataChanged.emit()

    def _delete_winch_file(self):
        row = self.winch_table.currentRow()
        if row < 0:
            return
        fid = self.winch_table.item(row, 0).data(QtCore.Qt.UserRole)
        self.store.delete_winch_file(fid)
        self._refresh_winch_files()
        self.dataChanged.emit()
