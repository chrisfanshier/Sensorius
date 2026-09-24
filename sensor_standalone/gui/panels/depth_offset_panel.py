"""
DepthOffsetPanel - Control panel for the "Depth Offset" mode.

Load data, load calibration, map calibration labels to columns,
apply depth corrections.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGridLayout,
    QComboBox, QCheckBox, QDoubleSpinBox, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget
from ...domain.models.sensor_data import SensorData


class DepthOffsetPanel(BaseModePanel):
    """
    Panel for the Depth Offset mode.

    Signals:
        load_file_requested(str): User selected a CSV file.
        load_calibration_requested(str): User selected a JSON calibration file.
        apply_corrections_requested: User clicked "Apply Corrections".
        reset_requested: User clicked "Reset".
        export_requested: User clicked "Export Corrected Data".
        plot_original_requested: User clicked "Plot Original".
    """

    load_file_requested = Signal(str)
    load_calibration_requested = Signal(str)
    apply_corrections_requested = Signal()
    reset_requested = Signal()
    export_requested = Signal()
    save_to_db_requested = Signal()
    plot_original_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # -- Data Information --
        data_group = QGroupBox("Data Information")
        data_layout = QVBoxLayout()
        self.file_label = QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        data_layout.addWidget(self.file_label)

        self.data_info_label = QLabel("")
        self.data_info_label.setWordWrap(True)
        data_layout.addWidget(self.data_info_label)

        data_group.setLayout(data_layout)
        self._layout.addWidget(data_group)

        # -- Calibration File --
        calib_group = QGroupBox("Calibration File")
        calib_layout = QVBoxLayout()
        self.calib_label = QLabel("No calibration loaded")
        self.calib_label.setWordWrap(True)
        calib_layout.addWidget(self.calib_label)

        calib_btn = QPushButton("Load JSON Calibration")
        calib_btn.clicked.connect(self._on_load_calibration)
        calib_layout.addWidget(calib_btn)

        calib_group.setLayout(calib_layout)
        self._layout.addWidget(calib_group)

        # -- Calibration Mapping --
        # Maps each calibration label (A, B, C) to a real depth column
        self.mapping_group = QGroupBox("Calibration Label Mapping")
        self.mapping_layout = QGridLayout()
        self.mapping_combos: dict[str, QComboBox] = {}  # cal_label -> combo
        self.mapping_group.setLayout(self.mapping_layout)
        self._layout.addWidget(self.mapping_group)

        # -- Reference Sensor --
        ref_group = QGroupBox("Reference Sensor")
        ref_layout = QVBoxLayout()
        ref_row = QHBoxLayout()
        ref_row.addWidget(QLabel("Reference:"))
        self.ref_sensor_combo = QComboBox()
        # Populated dynamically from calibration labels
        ref_row.addWidget(self.ref_sensor_combo)
        ref_row.addStretch()
        ref_layout.addLayout(ref_row)
        note = QLabel("(Reference will not be modified)")
        note.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        ref_layout.addWidget(note)
        ref_group.setLayout(ref_layout)
        self._layout.addWidget(ref_group)

        # -- Regression Corrections --
        self.correction_plan_group = QGroupBox("Regression Corrections")
        self.correction_plan_layout = QVBoxLayout()
        self.correction_checkboxes: dict[str, dict] = {}
        plan_label = QLabel("Load calibration and select reference to see plan")
        plan_label.setWordWrap(True)
        plan_label.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        self.correction_plan_layout.addWidget(plan_label)
        self.correction_plan_group.setLayout(self.correction_plan_layout)
        self._layout.addWidget(self.correction_plan_group)

        # -- Manual Offset Corrections --
        self.manual_group = QGroupBox("Manual Depth Corrections")
        self.manual_layout = QGridLayout()
        self.manual_offset_spinboxes: dict[str, QDoubleSpinBox] = {}
        # Populated dynamically when data is loaded
        self.manual_group.setLayout(self.manual_layout)
        self._layout.addWidget(self.manual_group)

        # -- Actions --
        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout()

        plot_orig_btn = QPushButton("Plot Original Data")
        plot_orig_btn.clicked.connect(self.plot_original_requested.emit)
        action_layout.addWidget(plot_orig_btn)

        apply_btn = QPushButton("Apply Corrections & Plot")
        apply_btn.clicked.connect(self.apply_corrections_requested.emit)
        action_layout.addWidget(apply_btn)

        reset_btn = QPushButton("Reset to Original")
        reset_btn.clicked.connect(self.reset_requested.emit)
        action_layout.addWidget(reset_btn)

        export_btn = QPushButton("Export Corrected Data")
        export_btn.clicked.connect(self.export_requested.emit)
        action_layout.addWidget(export_btn)

        action_group.setLayout(action_layout)
        self._layout.addWidget(action_group)

        # -- Log --
        self.log_widget = LogWidget("Log", max_height=200)
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    # ------------------------------------------------------------------
    # Public helpers for controller
    # ------------------------------------------------------------------

    def update_file_info(self, filename: str, sensors: int, rows: int, core_title: str = ''):
        text = f"File: {filename}\nSensors: {sensors}  |  Rows: {rows:,}"
        if core_title:
            text += f"\nCore: {core_title}"
        self.file_label.setText(text)

    def update_calibration_info(self, filename: str, info_lines: list[str]):
        self.calib_label.setText(f"Loaded: {filename}")
        for line in info_lines:
            self.log_widget.log(line)

    def setup_manual_offsets(self, depth_columns: list[str]):
        """Build manual offset spinboxes for each depth column."""
        # Clear previous
        while self.manual_layout.count():
            item = self.manual_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.manual_offset_spinboxes = {}

        for i, col in enumerate(depth_columns):
            short = SensorData.get_short_name(col)
            self.manual_layout.addWidget(QLabel(f"{short}:"), i, 0)
            spinbox = QDoubleSpinBox()
            spinbox.setRange(-1000, 1000)
            spinbox.setSingleStep(0.01)
            spinbox.setDecimals(4)
            spinbox.setValue(0.0)
            spinbox.setToolTip(col)
            self.manual_layout.addWidget(spinbox, i, 1)
            self.manual_layout.addWidget(QLabel("m"), i, 2)
            self.manual_offset_spinboxes[col] = spinbox

    def setup_calibration_mapping(self, cal_labels: list[str], depth_columns: list[str]):
        """Set up mapping combos: calibration label -> depth column.

        Args:
            cal_labels: Labels from the calibration file (e.g. ['A', 'B', 'C']).
            depth_columns: Real depth column names from the loaded data.
        """
        # Clear previous
        while self.mapping_layout.count():
            item = self.mapping_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.mapping_combos.clear()

        self.mapping_layout.addWidget(QLabel("Cal. Label"), 0, 0)
        self.mapping_layout.addWidget(QLabel("Depth Column"), 0, 1)

        # Build ref sensor combo from calibration labels
        self.ref_sensor_combo.clear()
        self.ref_sensor_combo.addItems(cal_labels)

        short_names = [SensorData.get_short_name(c) for c in depth_columns]

        for i, cal_label in enumerate(cal_labels):
            row = i + 1
            self.mapping_layout.addWidget(QLabel(f"Sensor {cal_label}:"), row, 0)
            combo = QComboBox()
            combo.addItem("(unmapped)", "")
            for j, col in enumerate(depth_columns):
                combo.addItem(short_names[j], col)
                combo.setItemData(combo.count() - 1, col)

            # Auto-select by position if possible
            if i < len(depth_columns):
                combo.setCurrentIndex(i + 1)  # +1 for "(unmapped)"

            self.mapping_layout.addWidget(combo, row, 1)
            self.mapping_combos[cal_label] = combo

    def get_calibration_mapping(self) -> dict[str, str]:
        """Return mapping: calibration_label -> depth_column_name."""
        result = {}
        for cal_label, combo in self.mapping_combos.items():
            col = combo.currentData()
            if col:
                result[cal_label] = col
        return result

    def update_correction_plan(self, applicable: list[dict]):
        """Update the correction plan checkboxes."""
        while self.correction_plan_layout.count():
            item = self.correction_plan_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.correction_checkboxes = {}

        if not applicable:
            label = QLabel("No applicable corrections found")
            label.setStyleSheet("QLabel { color: orange; }")
            self.correction_plan_layout.addWidget(label)
            return

        ref = self.ref_sensor_combo.currentText()
        info_label = QLabel(f"<b>Reference: Sensor {ref}</b> (will not be modified)")
        self.correction_plan_layout.addWidget(info_label)

        for item in applicable:
            reg = item['reg']
            example_depth = 250.0
            example_offset = reg.predict_offset(example_depth)
            example_correction = item['sign'] * example_offset

            checkbox = QCheckBox(
                f"Apply to Sensor {item['target']}: "
                f"{reg.sensor_j}-{reg.sensor_i} "
                f"(~{example_correction:+.3f}m @ 250m)"
            )
            checkbox.setChecked(True)
            checkbox.setToolTip(
                f"Regression: {reg.sensor_j} - {reg.sensor_i}\n"
                f"Slope: {reg.slope:.6f}\n"
                f"Intercept: {reg.intercept:.6f}\n"
                f"R\u00b2: {reg.r_squared:.4f}"
            )
            self.correction_checkboxes[item['target']] = {
                'checkbox': checkbox,
                'reg': reg,
                'sign': item['sign'],
            }
            self.correction_plan_layout.addWidget(checkbox)

    def get_manual_offsets(self) -> dict[str, float]:
        """Return manual offsets: depth_column -> offset_meters."""
        return {col: spin.value() for col, spin in self.manual_offset_spinboxes.items()}

    def get_enabled_calibration_targets(self) -> list[str]:
        """Return list of calibration labels whose checkbox is checked."""
        return [
            label for label, info in self.correction_checkboxes.items()
            if info['checkbox'].isChecked()
        ]

    def get_ref_sensor(self) -> str:
        """Return the selected reference calibration label."""
        return self.ref_sensor_combo.currentText()

    def set_ref_sensor(self, label: str) -> None:
        """Select *label* in the reference sensor combo (no-op if not found)."""
        for i in range(self.ref_sensor_combo.count()):
            if self.ref_sensor_combo.itemText(i) == label:
                self.ref_sensor_combo.setCurrentIndex(i)
                return

    def set_calibration_mapping(self, mapping: dict[str, str]) -> None:
        """Set combo selections to match *mapping* (cal_label -> depth_column).

        Only updates combos that already exist (populated by
        ``setup_calibration_mapping``); silently skips unknown labels.
        """
        for cal_label, col in mapping.items():
            combo = self.mapping_combos.get(cal_label)
            if combo is None:
                continue
            for i in range(combo.count()):
                if combo.itemData(i) == col:
                    combo.setCurrentIndex(i)
                    break

    def set_manual_offsets(self, offsets: dict[str, float]) -> None:
        """Set manual-offset spinbox values from *offsets* (column -> metres).

        Only spinboxes already created by ``setup_manual_offsets`` are updated.
        """
        for col, value in offsets.items():
            spin = self.manual_offset_spinboxes.get(col)
            if spin is not None:
                spin.setValue(float(value))

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _on_load_calibration(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Offset Calibration", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            self.load_calibration_requested.emit(file_path)
