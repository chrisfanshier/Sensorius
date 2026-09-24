"""
PistonPositionPanel - Control panel for the "Piston Position" mode.

Provides inputs for scope and core length, auto-detects weight-stand
and release-device sensors, shows the calculated start-core index, and
lets the user recalculate / plot the piston position estimate.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGridLayout,
    QComboBox, QDoubleSpinBox, QDateTimeEdit,
)
from PySide6.QtCore import Signal, QDateTime

from .base_panel import BaseModePanel
from ...domain.processing.calculations import DEFAULT_PISTON_OFFSET_M
from ..widgets.log_widget import LogWidget


class PistonPositionPanel(BaseModePanel):
    """
    Panel for the Piston Position mode.

    Signals
    -------
    load_file_requested(str)
        User selected a CSV file.
    calculate_requested
        User clicked "Calculate & Plot".
    plot_original_requested
        User clicked "Plot Original Data".
    """

    load_file_requested = Signal(str)
    calculate_requested = Signal()
    plot_original_requested = Signal()
    export_piston_requested = Signal()
    save_to_db_requested = Signal()

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

        # -- Parameters ------------------------------------------------------
        param_group = QGroupBox("Parameters (feet)")
        param_layout = QGridLayout()

        param_layout.addWidget(QLabel("Scope:"), 0, 0)
        self.scope_spin = QDoubleSpinBox()
        self.scope_spin.setRange(0.0, 1000.0)
        self.scope_spin.setDecimals(2)
        self.scope_spin.setSingleStep(0.5)
        self.scope_spin.setValue(0.0)
        param_layout.addWidget(self.scope_spin, 0, 1)
        param_layout.addWidget(QLabel("ft"), 0, 2)

        param_layout.addWidget(QLabel("Core Length:"), 1, 0)
        self.core_length_spin = QDoubleSpinBox()
        self.core_length_spin.setRange(0.0, 1000.0)
        self.core_length_spin.setDecimals(2)
        self.core_length_spin.setSingleStep(1.0)
        self.core_length_spin.setValue(0.0)
        param_layout.addWidget(self.core_length_spin, 1, 1)
        param_layout.addWidget(QLabel("ft"), 1, 2)

        param_layout.addWidget(QLabel("Offset Constant:"), 2, 0)
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(0.0, 100.0)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSingleStep(0.25)
        self.offset_spin.setValue(DEFAULT_PISTON_OFFSET_M)
        param_layout.addWidget(self.offset_spin, 2, 1)
        param_layout.addWidget(QLabel("m"), 2, 2)

        param_group.setLayout(param_layout)
        self._layout.addWidget(param_group)

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

        # -- Actions ---------------------------------------------------------
        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout()

        plot_orig_btn = QPushButton("Plot Original Data")
        plot_orig_btn.clicked.connect(self.plot_original_requested.emit)
        action_layout.addWidget(plot_orig_btn)

        calc_btn = QPushButton("Calculate && Plot Piston")
        calc_btn.clicked.connect(self.calculate_requested.emit)
        action_layout.addWidget(calc_btn)

        export_btn = QPushButton("Export Data")
        export_btn.clicked.connect(self.export_piston_requested.emit)
        action_layout.addWidget(export_btn)

        action_group.setLayout(action_layout)
        self._layout.addWidget(action_group)

        # -- Log -------------------------------------------------------------
        self.log_widget = LogWidget("Log", max_height=200)
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

    def populate_sensor_combos(self, columns_and_names: list[tuple[str, str]],
                                weight_stand_col: str | None = None,
                                release_col: str | None = None):
        """Fill the weight-stand / release combo boxes.

        Parameters
        ----------
        columns_and_names : list of (column_name, display_name)
            All available depth columns with their display names.
        weight_stand_col, release_col : str or None
            Auto-detected column names to pre-select.
        """
        self.weight_stand_combo.blockSignals(True)
        self.release_combo.blockSignals(True)

        self.weight_stand_combo.clear()
        self.release_combo.clear()

        for col, name in columns_and_names:
            self.weight_stand_combo.addItem(name, userData=col)
            self.release_combo.addItem(name, userData=col)

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

        self.weight_stand_combo.blockSignals(False)
        self.release_combo.blockSignals(False)

    def set_parameters_from_metadata(self, metadata: dict):
        """Pre-fill scope, core-length, and trip time from CSV metadata."""
        # Always set so a null DB value resets the spinbox instead of leaving
        # a stale value from the previously loaded core.
        self.scope_spin.setValue(metadata.get('scope', 0.0))
        self.core_length_spin.setValue(metadata.get('core_length', 0.0))
        if 'trip_time' in metadata:
            self.set_trip_time(metadata['trip_time'], source='CSV header')

    def set_trip_time(self, dt_str: str, source: str = ''):
        """Set the trip time and update its source label.

        Parameters
        ----------
        dt_str : str
            ISO-style datetime string, e.g. '2025-06-15 15:13:29.688'.
        source : str
            Human-readable origin description, e.g. 'trip detector' or 'CSV header'.
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
        """Return the trip time as seconds since epoch.

        Uses the same naive-as-UTC convention as
        ``SensorData.get_timestamps_epoch()`` so that
        ``np.searchsorted`` finds the correct index regardless
        of the local system timezone.
        """
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

    def get_offset_constant(self) -> float:
        return self.offset_spin.value()

    def set_offset_constant(self, value: float) -> None:
        """Set the offset-constant spinbox value."""
        self.offset_spin.setValue(float(value))

    def update_start_core_info(self, index: int, timestamp_str: str = ''):
        """Update the start-core info label."""
        text = f"Index: {index}"
        if timestamp_str:
            text += f"\nTime: {timestamp_str}"
        self.start_core_label.setText(text)

    def get_weight_stand_col(self) -> str | None:
        """Return the currently selected weight-stand column name."""
        return self.weight_stand_combo.currentData()

    def get_release_col(self) -> str | None:
        """Return the currently selected release-device column name."""
        return self.release_combo.currentData()

    def get_scope(self) -> float:
        return self.scope_spin.value()

    def get_core_length(self) -> float:
        return self.core_length_spin.value()
