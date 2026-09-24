"""
CreateCalibrationPanel - Control panel for multi-cast calibration workflow.

Select a cast from the database, select stable depth regions, collect
statistics, generate and save calibration file.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QPushButton, QLabel, QComboBox, QFileDialog,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget
from ..widgets.selection_controls import SelectionControls


class CreateCalibrationPanel(BaseModePanel):
    """
    Panel for the Create Calibration mode.

    Signals:
        cruise_selected(int): User selected a cruise (emits cruise_id).
        cast_core_selected(int, dict): User selected a cast core (emits core_id, core_info).
        add_statistics_requested: Add stats from current selection.
        generate_calibration_requested: Generate calibration from collected stats.
        save_calibration_requested(str): Save generated calibration to path.
        selection_mode_changed(bool): Selection mode toggled.
        clear_selection_requested: Clear selection.
    """

    cruise_selected = Signal(int)
    cast_core_selected = Signal(int, dict)
    add_statistics_requested = Signal()
    generate_calibration_requested = Signal()
    save_calibration_requested = Signal(str)
    selection_mode_changed = Signal(bool)
    clear_selection_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Internal state
        self._cruises: list[dict] = []
        self._cores: list[dict] = []

        # -- Info box --
        info_group = QGroupBox("Instructions")
        info_layout = QVBoxLayout()
        info_label = QLabel(
            "Develop depth calibrations from multiple test casts.\n\n"
            "Workflow:\n"
            "1. Select a cruise and cast from the database\n"
            "2. Select a stable depth region on the plot\n"
            "3. Click 'Add Statistics' to collect data\n"
            "4. Repeat with different casts / regions\n"
            "5. Generate and save calibration file\n\n"
            "Use 'Depth Offset' mode to apply calibrations."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "QLabel { background-color: #e3f2fd; padding: 8px; border-radius: 4px; }"
        )
        info_layout.addWidget(info_label)
        info_group.setLayout(info_layout)
        self._layout.addWidget(info_group)

        # -- Cast selection --
        cast_group = QGroupBox("Select Cast from Database")
        cast_layout = QVBoxLayout()

        cast_layout.addWidget(QLabel("Cruise:"))
        self.cruise_combo = QComboBox()
        self.cruise_combo.addItem("Select cruise…")
        self.cruise_combo.currentIndexChanged.connect(self._on_cruise_changed)
        cast_layout.addWidget(self.cruise_combo)

        cast_layout.addWidget(QLabel("Cast (core):"))
        self.core_combo = QComboBox()
        self.core_combo.addItem("Select cast…")
        self.core_combo.setEnabled(False)
        self.core_combo.currentIndexChanged.connect(self._on_core_changed)
        cast_layout.addWidget(self.core_combo)

        self.cast_label = QLabel("No cast loaded")
        self.cast_label.setWordWrap(True)
        cast_layout.addWidget(self.cast_label)

        cast_group.setLayout(cast_layout)
        self._layout.addWidget(cast_group)

        # -- Selection --
        self.selection_controls = SelectionControls("Selection")
        self.selection_controls.selection_mode_changed.connect(
            self.selection_mode_changed.emit
        )
        self.selection_controls.clear_requested.connect(
            self.clear_selection_requested.emit
        )
        self._layout.addWidget(self.selection_controls)

        # -- Add Statistics --
        stats_group = QGroupBox("Collect Statistics")
        stats_layout = QVBoxLayout()

        add_btn = QPushButton("Add Statistics from Selection")
        add_btn.clicked.connect(self.add_statistics_requested.emit)
        stats_layout.addWidget(add_btn)

        self.stats_count_label = QLabel("0 data points collected")
        stats_layout.addWidget(self.stats_count_label)

        stats_group.setLayout(stats_layout)
        self._layout.addWidget(stats_group)

        # -- Generate Calibration --
        gen_group = QGroupBox("Generate Calibration")
        gen_layout = QVBoxLayout()

        gen_btn = QPushButton("Generate Calibration")
        gen_btn.clicked.connect(self.generate_calibration_requested.emit)
        gen_layout.addWidget(gen_btn)

        save_btn = QPushButton("Save Calibration…")
        save_btn.clicked.connect(self._on_save_calibration)
        gen_layout.addWidget(save_btn)

        self.calibration_summary_label = QLabel("")
        self.calibration_summary_label.setWordWrap(True)
        gen_layout.addWidget(self.calibration_summary_label)

        gen_group.setLayout(gen_layout)
        self._layout.addWidget(gen_group)

        # -- Log --
        self.log_widget = LogWidget("Log", max_height=150)
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_cruises(self, cruises: list[dict]):
        """Populate the cruise dropdown. Each dict must have cruise_id, cruise_name."""
        self._cruises = cruises
        self.cruise_combo.blockSignals(True)
        self.cruise_combo.clear()
        self.cruise_combo.addItem("Select cruise…")
        for cr in cruises:
            label = cr["cruise_name"]
            if cr.get("vessel_name"):
                label += f" — {cr['vessel_name']}"
            self.cruise_combo.addItem(label)
        self.cruise_combo.blockSignals(False)

    def set_cores(self, cores: list[dict]):
        """Populate the cast (core) dropdown."""
        self._cores = cores
        self.core_combo.blockSignals(True)
        self.core_combo.clear()
        self.core_combo.addItem("Select cast…")
        for ci in cores:
            label = ci["core_name"]
            if ci.get("core_type_name"):
                label += f" ({ci['core_type_name']})"
            self.core_combo.addItem(label)
        self.core_combo.setEnabled(bool(cores))
        self.core_combo.blockSignals(False)

    def update_cast_info(self, core_name: str, sensors: int, rows: int):
        self.cast_label.setText(
            f"Cast: {core_name}\nSensors: {sensors}  |  Rows: {rows:,}"
        )

    def update_stats_count(self, count: int):
        self.stats_count_label.setText(f"{count} data point(s) collected")

    def update_calibration_summary(self, text: str):
        self.calibration_summary_label.setText(text)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _on_cruise_changed(self, index: int):
        self.core_combo.blockSignals(True)
        self.core_combo.clear()
        self.core_combo.addItem("Select cast…")
        self._cores = []
        self.core_combo.setEnabled(False)
        self.core_combo.blockSignals(False)

        if index <= 0 or index > len(self._cruises):
            return
        cruise = self._cruises[index - 1]
        self.cruise_selected.emit(cruise["cruise_id"])

    def _on_core_changed(self, index: int):
        if index <= 0 or index > len(self._cores):
            return
        core = self._cores[index - 1]
        self.cast_core_selected.emit(core["core_id"], core)

    def _on_save_calibration(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Offset Calibration", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            self.save_calibration_requested.emit(file_path)
