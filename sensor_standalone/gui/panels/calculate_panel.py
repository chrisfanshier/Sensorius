"""
CalculatePanel - Control panel for the "Calculate" analysis mode.

Provides inputs for Savitzky-Golay smoothing, trigger penetration,
sensor assignment, and displays computed coring analysis values
in the log widget.

This mode is intended to be used after depth/time corrections,
trip detection, and piston position have been applied, but will
still calculate values that are available without trip time, start
core, or piston position.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGridLayout, QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox,
    QDateTimeEdit,
)
from PySide6.QtCore import Signal, QDateTime

from .base_panel import BaseModePanel
from ...domain.processing.calculations import DEFAULT_WEIGHT_STAND_LENGTH_M
from ..widgets.log_widget import LogWidget


class CalculatePanel(BaseModePanel):
    """
    Panel for the Calculate analysis mode.

    Signals
    -------
    load_file_requested(str)
        User selected a CSV file to load.
    calculate_requested
        User clicked "Calculate".
    plot_original_requested
        User clicked "Plot Original Data".
    """

    load_file_requested = Signal(str)
    calculate_requested = Signal()
    plot_original_requested = Signal()
    export_results_requested = Signal()
    export_diagram_requested = Signal()
    save_to_db_requested = Signal()
    reset_lines_requested = Signal()
    seafloor_override_changed = Signal(object)   # float or None
    seafloor_estimate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # -- Data Information ------------------------------------------------
        data_group = QGroupBox("Data Information")
        data_layout = QVBoxLayout()
        self.file_label = QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        data_layout.addWidget(self.file_label)

        data_group.setLayout(data_layout)
        self._layout.addWidget(data_group)

        # -- Sensor Assignment -----------------------------------------------
        sensor_group = QGroupBox("Sensor Assignment")
        sensor_layout = QGridLayout()

        sensor_layout.addWidget(QLabel("Weight Stand:"), 0, 0)
        self.weight_stand_combo = QComboBox()
        sensor_layout.addWidget(self.weight_stand_combo, 0, 1)

        sensor_layout.addWidget(QLabel("Release Device:"), 1, 0)
        self.release_combo = QComboBox()
        sensor_layout.addWidget(self.release_combo, 1, 1)

        sensor_layout.addWidget(QLabel("Trigger Core/Weight:"), 2, 0)
        self.trigger_combo = QComboBox()
        self.trigger_combo.addItem("(not available)", userData=None)
        sensor_layout.addWidget(self.trigger_combo, 2, 1)

        sensor_group.setLayout(sensor_layout)
        self._layout.addWidget(sensor_group)

        # -- Trip Time -------------------------------------------------------
        trip_group = QGroupBox("Trip Time")
        trip_layout = QVBoxLayout()

        self.trip_time_edit = QDateTimeEdit()
        self.trip_time_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss.zzz")
        self.trip_time_edit.setCalendarPopup(True)
        trip_layout.addWidget(self.trip_time_edit)

        self.trip_time_source_label = QLabel("Not set")
        self.trip_time_source_label.setStyleSheet(
            "QLabel { color: gray; font-style: italic; }"
        )
        self.trip_time_source_label.setWordWrap(True)
        trip_layout.addWidget(self.trip_time_source_label)

        trip_group.setLayout(trip_layout)
        self._layout.addWidget(trip_group)

        # -- Start Core Info -------------------------------------------------
        sc_group = QGroupBox("Start Core")
        sc_layout = QVBoxLayout()

        self.start_core_label = QLabel("Not calculated yet")
        self.start_core_label.setWordWrap(True)
        sc_layout.addWidget(self.start_core_label)

        note = QLabel("Drag the red dashed line on the plot to adjust.")
        note.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        note.setWordWrap(True)
        sc_layout.addWidget(note)

        sc_group.setLayout(sc_layout)
        self._layout.addWidget(sc_group)

        # -- End of Initial Penetration --------------------------------------
        ep_group = QGroupBox("End of Initial Penetration")
        ep_layout = QVBoxLayout()

        self.end_pen_label = QLabel("Not set")
        self.end_pen_label.setWordWrap(True)
        ep_layout.addWidget(self.end_pen_label)

        ep_note = QLabel(
            "Drag the orange dashed line on the plot to set.\n"
            "Used for fall_dist, suck_in, and piston_suck."
        )
        ep_note.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        ep_note.setWordWrap(True)
        ep_layout.addWidget(ep_note)

        ep_group.setLayout(ep_layout)
        self._layout.addWidget(ep_group)

        # -- Pullout ---------------------------------------------------------
        po_group = QGroupBox("Pullout")
        po_layout = QVBoxLayout()

        self.pullout_label = QLabel("Not set")
        self.pullout_label.setWordWrap(True)
        po_layout.addWidget(self.pullout_label)

        po_note = QLabel(
            "Drag the green dashed line on the plot to set.\n"
            "WS depth at this point is used for piston_suck."
        )
        po_note.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        po_note.setWordWrap(True)
        po_layout.addWidget(po_note)

        po_group.setLayout(po_layout)
        self._layout.addWidget(po_group)

        # -- Reset Lines button ----------------------------------------------
        reset_lines_btn = QPushButton("Reset Lines to Auto")
        reset_lines_btn.setToolTip(
            "Reset End-of-Penetration and Pullout lines\n"
            "back to their auto-calculated positions."
        )
        reset_lines_btn.clicked.connect(self.reset_lines_requested.emit)
        self._layout.addWidget(reset_lines_btn)

        # -- Smoothing -------------------------------------------------------
        smooth_group = QGroupBox("Savitzky-Golay Smoothing")
        smooth_layout = QGridLayout()

        self.smooth_check = QCheckBox("Enable Smoothing")
        smooth_layout.addWidget(self.smooth_check, 0, 0, 1, 3)

        smooth_layout.addWidget(QLabel("Window Length:"), 1, 0)
        self.sg_window_spin = QSpinBox()
        self.sg_window_spin.setRange(5, 501)
        self.sg_window_spin.setSingleStep(2)
        self.sg_window_spin.setValue(51)
        smooth_layout.addWidget(self.sg_window_spin, 1, 1)
        self._window_note = QLabel("(odd)")
        self._window_note.setStyleSheet("QLabel { color: gray; }")
        smooth_layout.addWidget(self._window_note, 1, 2)

        smooth_layout.addWidget(QLabel("Polynomial:"), 2, 0)
        self.sg_poly_spin = QSpinBox()
        self.sg_poly_spin.setRange(1, 10)
        self.sg_poly_spin.setValue(3)
        smooth_layout.addWidget(self.sg_poly_spin, 2, 1)

        smooth_group.setLayout(smooth_layout)
        self._layout.addWidget(smooth_group)

        # -- Trigger Penetration ---------------------------------------------
        trigger_group = QGroupBox("Trigger Penetration (m)")
        trigger_layout = QGridLayout()

        trigger_layout.addWidget(QLabel("Trigger Pen:"), 0, 0)
        self.trigger_pen_spin = QDoubleSpinBox()
        self.trigger_pen_spin.setRange(0.0, 100.0)
        self.trigger_pen_spin.setDecimals(2)
        self.trigger_pen_spin.setSingleStep(0.1)
        self.trigger_pen_spin.setValue(0.0)
        trigger_layout.addWidget(self.trigger_pen_spin, 0, 1)
        trigger_layout.addWidget(QLabel("m"), 0, 2)

        self.trigger_pen_note = QLabel(
            "Estimated trigger core penetration.\n"
            "Required for seafloor-based calculations."
        )
        self.trigger_pen_note.setStyleSheet(
            "QLabel { color: gray; font-style: italic; }"
        )
        self.trigger_pen_note.setWordWrap(True)
        trigger_layout.addWidget(self.trigger_pen_note, 1, 0, 1, 3)

        trigger_group.setLayout(trigger_layout)
        self._layout.addWidget(trigger_group)

        ws_len_group = QGroupBox("Weight Stand Length (m)")
        ws_len_layout = QGridLayout()
        ws_len_layout.addWidget(QLabel("Weight stand length:"), 0, 0)
        self.weight_stand_length_spin = QDoubleSpinBox()
        self.weight_stand_length_spin.setRange(0.5, 5.0)
        self.weight_stand_length_spin.setDecimals(2)
        self.weight_stand_length_spin.setSingleStep(0.1)
        self.weight_stand_length_spin.setValue(DEFAULT_WEIGHT_STAND_LENGTH_M)
        self.weight_stand_length_spin.setToolTip(
            "Length of the weight stand in metres. The depth sensor is at the "
            "top; the barrel hangs below. Used for core-tip depth, freefall "
            "estimate, penetration deficit, and the default piston offset "
            "(length − 0.25 m)."
        )
        ws_len_layout.addWidget(self.weight_stand_length_spin, 0, 1)
        ws_len_layout.addWidget(QLabel("m"), 0, 2)
        ws_len_group.setLayout(ws_len_layout)
        self._layout.addWidget(ws_len_group)

        # -- Manual Seafloor Override ----------------------------------------
        sf_group = QGroupBox("Manual Seafloor Override")
        sf_layout = QVBoxLayout()

        self.seafloor_check = QCheckBox("Override seafloor depth")
        self.seafloor_check.setToolTip(
            "When checked the value below is used instead of the\n"
            "trigger-sensor formula. Drag the red dashed line on\n"
            "the plot to adjust."
        )
        sf_layout.addWidget(self.seafloor_check)

        sf_spin_row = QHBoxLayout()
        self.seafloor_spin = QDoubleSpinBox()
        self.seafloor_spin.setRange(0.0, 15000.0)
        self.seafloor_spin.setDecimals(2)
        self.seafloor_spin.setSingleStep(1.0)
        self.seafloor_spin.setValue(0.0)
        self.seafloor_spin.setEnabled(False)
        sf_spin_row.addWidget(self.seafloor_spin)
        sf_spin_row.addWidget(QLabel("m"))
        sf_layout.addLayout(sf_spin_row)

        self.seafloor_estimate_btn = QPushButton("Estimate from Trip")
        self.seafloor_estimate_btn.setToolTip(
            "Sets depth to:  WS[trip] + core_length + weight stand length + scope\n"
            "(assumes zero freefall — actual seafloor is shallower)"
        )
        self.seafloor_estimate_btn.setEnabled(False)
        self.seafloor_estimate_btn.clicked.connect(
            self.seafloor_estimate_requested.emit
        )
        sf_layout.addWidget(self.seafloor_estimate_btn)

        sf_note = QLabel(
            "Estimate is an upper bound; actual seafloor is shallower\n"
            "by the freefall distance."
        )
        sf_note.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        sf_note.setWordWrap(True)
        sf_layout.addWidget(sf_note)

        sf_group.setLayout(sf_layout)
        self._layout.addWidget(sf_group)

        # Connect checkbox to enable/disable controls
        self.seafloor_check.toggled.connect(self._on_seafloor_check_toggled)
        self.seafloor_spin.valueChanged.connect(self._on_seafloor_value_changed)

        # -- Actions ---------------------------------------------------------
        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout()

        plot_orig_btn = QPushButton("Plot Original Data")
        plot_orig_btn.clicked.connect(self.plot_original_requested.emit)
        action_layout.addWidget(plot_orig_btn)

        calc_btn = QPushButton("Calculate")
        calc_btn.clicked.connect(self.calculate_requested.emit)
        action_layout.addWidget(calc_btn)

        export_btn = QPushButton("Export Results")
        export_btn.clicked.connect(self.export_results_requested.emit)
        action_layout.addWidget(export_btn)

        export_diag_btn = QPushButton("Export Diagram")
        export_diag_btn.clicked.connect(self.export_diagram_requested.emit)
        action_layout.addWidget(export_diag_btn)

        action_group.setLayout(action_layout)
        self._layout.addWidget(action_group)

        # -- Log -------------------------------------------------------------
        self.log_widget = LogWidget("Results", max_height=300)
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    # ------------------------------------------------------------------
    # Public helpers for controller
    # ------------------------------------------------------------------

    def update_file_info(self, filename: str, sensors: int, rows: int,
                         core_title: str = ''):
        text = f"File: {filename}\nSensors: {sensors}  |  Rows: {rows:,}"
        if core_title:
            text += f"\nCore: {core_title}"
        self.file_label.setText(text)

    def populate_sensor_combos(
        self,
        columns_and_names: list[tuple[str, str]],
        weight_stand_col: str | None = None,
        release_col: str | None = None,
        trigger_col: str | None = None,
    ):
        """Fill the sensor combo boxes.

        Parameters
        ----------
        columns_and_names : list of (column_name, display_name)
        weight_stand_col, release_col, trigger_col : str or None
            Auto-detected column names to pre-select.
        """
        self.weight_stand_combo.blockSignals(True)
        self.release_combo.blockSignals(True)
        self.trigger_combo.blockSignals(True)

        self.weight_stand_combo.clear()
        self.release_combo.clear()
        self.trigger_combo.clear()

        # Trigger combo always starts with a "not available" placeholder
        self.trigger_combo.addItem("(not available)", userData=None)

        for col, name in columns_and_names:
            self.weight_stand_combo.addItem(name, userData=col)
            self.release_combo.addItem(name, userData=col)
            self.trigger_combo.addItem(name, userData=col)

        if weight_stand_col is not None:
            for i in range(self.weight_stand_combo.count()):
                if self.weight_stand_combo.itemData(i) == weight_stand_col:
                    self.weight_stand_combo.setCurrentIndex(i)
                    break

        if release_col is not None:
            for i in range(self.release_combo.count()):
                if self.release_combo.itemData(i) == release_col:
                    self.release_combo.setCurrentIndex(i)
                    break

        if trigger_col is not None:
            for i in range(self.trigger_combo.count()):
                if self.trigger_combo.itemData(i) == trigger_col:
                    self.trigger_combo.setCurrentIndex(i)
                    break

        self.weight_stand_combo.blockSignals(False)
        self.release_combo.blockSignals(False)
        self.trigger_combo.blockSignals(False)

    def set_parameters_from_metadata(self, metadata: dict):
        """Pre-fill trip time from CSV metadata."""
        if 'trip_time' in metadata:
            self.set_trip_time(metadata['trip_time'], source='CSV header')

    def set_trip_time(self, dt_str: str, source: str = ''):
        """Set the trip time widget.

        Parameters
        ----------
        dt_str : str
            ISO-style datetime string.
        source : str
            Human-readable origin description.
        """
        import pandas as pd
        try:
            ts = pd.to_datetime(dt_str)
            qdt = QDateTime(
                ts.year, ts.month, ts.day,
                ts.hour, ts.minute, ts.second, ts.microsecond // 1000,
            )
            self.trip_time_edit.setDateTime(qdt)
            if source:
                self.trip_time_source_label.setText(f"Source: {source}")
        except Exception:
            pass

    def get_trip_time_epoch(self) -> float:
        """Return the trip time as seconds since epoch (naive-as-UTC)."""
        import pandas as pd
        qdt = self.trip_time_edit.dateTime()
        d = qdt.date()
        t = qdt.time()
        ts = pd.Timestamp(
            year=d.year(), month=d.month(), day=d.day(),
            hour=t.hour(), minute=t.minute(), second=t.second(),
            microsecond=t.msec() * 1000,
        )
        return ts.value / 1e9

    def update_start_core_info(self, index: int, timestamp_str: str = ''):
        """Update the start-core info label."""
        text = f"Index: {index}"
        if timestamp_str:
            text += f"\nTime: {timestamp_str}"
        self.start_core_label.setText(text)

    def update_end_pen_info(self, index: int, timestamp_str: str = ''):
        """Update the end-of-penetration info label."""
        text = f"Index: {index}"
        if timestamp_str:
            text += f"\nTime: {timestamp_str}"
        self.end_pen_label.setText(text)

    def update_pullout_info(self, index: int, timestamp_str: str = ''):
        """Update the pullout info label."""
        text = f"Index: {index}"
        if timestamp_str:
            text += f"\nTime: {timestamp_str}"
        self.pullout_label.setText(text)

    def get_weight_stand_col(self) -> str | None:
        return self.weight_stand_combo.currentData()

    def get_release_col(self) -> str | None:
        return self.release_combo.currentData()

    def get_trigger_col(self) -> str | None:
        return self.trigger_combo.currentData()

    def get_trigger_pen(self) -> float:
        return self.trigger_pen_spin.value()

    def set_trigger_pen(self, value: float) -> None:
        """Set the trigger-penetration spinbox value."""
        self.trigger_pen_spin.setValue(float(value))

    def get_weight_stand_length_m(self) -> float:
        return self.weight_stand_length_spin.value()

    def set_weight_stand_length_m(self, value: float) -> None:
        self.weight_stand_length_spin.setValue(float(value))

    def get_smoothing_enabled(self) -> bool:
        return self.smooth_check.isChecked()

    def get_sg_params(self) -> tuple[int, int]:
        """Return (window_length, polynomial_order)."""
        win = self.sg_window_spin.value()
        # Ensure odd
        if win % 2 == 0:
            win += 1
        return win, self.sg_poly_spin.value()

    def set_sg_params(self, window: int, polyorder: int) -> None:
        """Set Savitzky-Golay window length and polynomial order spinboxes."""
        self.sg_window_spin.setValue(int(window))
        self.sg_poly_spin.setValue(int(polyorder))

    # ------------------------------------------------------------------
    # Seafloor override helpers
    # ------------------------------------------------------------------

    def _on_seafloor_check_toggled(self, checked: bool):
        self.seafloor_spin.setEnabled(checked)
        self.seafloor_estimate_btn.setEnabled(checked)
        if checked:
            self.seafloor_override_changed.emit(self.seafloor_spin.value())
        else:
            self.seafloor_override_changed.emit(None)

    def _on_seafloor_value_changed(self, value: float):
        if self.seafloor_check.isChecked():
            self.seafloor_override_changed.emit(value)

    def get_seafloor_override(self) -> float | None:
        """Return the manual seafloor depth, or None if override is off."""
        if self.seafloor_check.isChecked():
            return self.seafloor_spin.value()
        return None

    def set_seafloor_override(self, depth: float):
        """Set the spinbox value (does not check the checkbox)."""
        self.seafloor_spin.setValue(depth)

    def show_seafloor_override(self, depth: float | None):
        """Display a restored override without re-emitting it.

        The caller already holds the value. Emitting would let the checkbox
        push the spinbox's stale 0.0 back out and wipe the restored depth.
        """
        self.seafloor_check.blockSignals(True)
        self.seafloor_spin.blockSignals(True)
        self.seafloor_check.setChecked(depth is not None)
        if depth is not None:
            self.seafloor_spin.setValue(float(depth))
        self.seafloor_check.blockSignals(False)
        self.seafloor_spin.blockSignals(False)
        self.seafloor_spin.setEnabled(depth is not None)
        self.seafloor_estimate_btn.setEnabled(depth is not None)
