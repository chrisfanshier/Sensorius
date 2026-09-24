"""
TimeOffsetPanel - Control panel for the "Time Offset" mode.

Bandpass filter parameters, reference sensor selection, heave cross-correlation.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGridLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget
from ..widgets.selection_controls import SelectionControls
from ...domain.models.sensor_data import SensorData
from ...domain.models.analysis_result import TimeOffsetResult


class TimeOffsetPanel(BaseModePanel):
    """
    Panel for the Time Offset mode.

    Signals:
        load_file_requested(str): User selected a CSV file.
        calculate_offsets_requested: User clicked "Calculate Offsets".
        apply_correction_requested: User clicked "Apply Correction".
        reset_requested: User clicked "Reset".
        export_requested: User clicked "Export Corrected Data".
        plot_original_requested: User clicked "Plot Original Data".
        selection_mode_changed(bool): Selection mode toggled.
        clear_selection_requested: Clear selection.
    """

    load_file_requested = Signal(str)
    calculate_offsets_requested = Signal()
    apply_correction_requested = Signal()
    apply_manual_requested = Signal()
    reset_requested = Signal()
    export_requested = Signal()
    save_to_db_requested = Signal()
    plot_original_requested = Signal()
    selection_mode_changed = Signal(bool)
    clear_selection_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # -- Data Information --
        data_group = QGroupBox("Data Information")
        data_layout = QVBoxLayout()
        self.file_label = QLabel("No data loaded")
        self.file_label.setWordWrap(True)
        data_layout.addWidget(self.file_label)

        data_group.setLayout(data_layout)
        self._layout.addWidget(data_group)

        # -- Bandpass Filter --
        filter_group = QGroupBox("Heave Isolation Filter (Butterworth Bandpass)")
        filter_layout = QGridLayout()

        filter_layout.addWidget(QLabel("Low Freq (Hz):"), 0, 0)
        self.low_freq_spin = QDoubleSpinBox()
        self.low_freq_spin.setRange(0.001, 10.0)
        self.low_freq_spin.setSingleStep(0.01)
        self.low_freq_spin.setDecimals(3)
        self.low_freq_spin.setValue(0.05)
        self.low_freq_spin.setToolTip("Lower cutoff frequency. 0.05 Hz = 20 s period.")
        filter_layout.addWidget(self.low_freq_spin, 0, 1)

        filter_layout.addWidget(QLabel("High Freq (Hz):"), 1, 0)
        self.high_freq_spin = QDoubleSpinBox()
        self.high_freq_spin.setRange(0.01, 50.0)
        self.high_freq_spin.setSingleStep(0.05)
        self.high_freq_spin.setDecimals(3)
        self.high_freq_spin.setValue(0.5)
        self.high_freq_spin.setToolTip("Upper cutoff frequency. 0.5 Hz = 2 s period.")
        filter_layout.addWidget(self.high_freq_spin, 1, 1)

        filter_layout.addWidget(QLabel("Filter Order:"), 2, 0)
        self.filter_order_spin = QSpinBox()
        self.filter_order_spin.setRange(1, 10)
        self.filter_order_spin.setValue(4)
        self.filter_order_spin.setToolTip("Butterworth filter order.")
        filter_layout.addWidget(self.filter_order_spin, 2, 1)

        filter_group.setLayout(filter_layout)
        self._layout.addWidget(filter_group)

        # -- Reference Sensor --
        ref_group = QGroupBox("Reference Sensor")
        ref_layout = QVBoxLayout()
        ref_row = QHBoxLayout()
        ref_row.addWidget(QLabel("Reference:"))
        self.ref_sensor_combo = QComboBox()
        # Populated dynamically when data is loaded
        ref_row.addWidget(self.ref_sensor_combo)
        ref_row.addStretch()
        ref_layout.addLayout(ref_row)
        note = QLabel("(Reference time will not change)")
        note.setStyleSheet("QLabel { color: gray; font-style: italic; }")
        ref_layout.addWidget(note)
        ref_group.setLayout(ref_layout)
        self._layout.addWidget(ref_group)

        # -- Selection --
        self.selection_controls = SelectionControls("Time Range Selection")
        self.selection_controls.selection_mode_changed.connect(
            self.selection_mode_changed.emit
        )
        self.selection_controls.clear_requested.connect(
            self.clear_selection_requested.emit
        )
        self._layout.addWidget(self.selection_controls)

        # -- Calculated Offsets --
        offset_group = QGroupBox("Calculated Time Offsets")
        offset_layout = QVBoxLayout()
        self.offset_text = QTextEdit()
        self.offset_text.setReadOnly(True)
        self.offset_text.setMaximumHeight(150)
        self.offset_text.setText("Click 'Calculate Offsets' to compute time lags")
        offset_layout.addWidget(self.offset_text)
        offset_group.setLayout(offset_layout)
        self._layout.addWidget(offset_group)

        # -- Manual Time Corrections --
        self.manual_group = QGroupBox("Manual Time Corrections")
        self.manual_layout = QGridLayout()
        self.manual_offset_spinboxes: dict[str, QDoubleSpinBox] = {}
        self.manual_group.setLayout(self.manual_layout)
        self._layout.addWidget(self.manual_group)

        # -- Actions --
        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout()

        plot_btn = QPushButton("Plot Original Data")
        plot_btn.clicked.connect(self.plot_original_requested.emit)
        action_layout.addWidget(plot_btn)

        calc_btn = QPushButton("Calculate Offsets")
        calc_btn.clicked.connect(self.calculate_offsets_requested.emit)
        action_layout.addWidget(calc_btn)

        apply_btn = QPushButton("Apply Heave Correction")
        apply_btn.clicked.connect(self.apply_correction_requested.emit)
        action_layout.addWidget(apply_btn)

        apply_manual_btn = QPushButton("Apply Manual Corrections")
        apply_manual_btn.clicked.connect(self.apply_manual_requested.emit)
        action_layout.addWidget(apply_manual_btn)

        reset_btn = QPushButton("Reset to Original")
        reset_btn.clicked.connect(self.reset_requested.emit)
        action_layout.addWidget(reset_btn)

        export_btn = QPushButton("Export Corrected Data")
        export_btn.clicked.connect(self.export_requested.emit)
        action_layout.addWidget(export_btn)

        action_group.setLayout(action_layout)
        self._layout.addWidget(action_group)

        # -- Log --
        self.log_widget = LogWidget("Log", max_height=150)
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def update_file_info(self, filename: str, sensors: int, rows: int):
        self.file_label.setText(f"File: {filename}\nSensors: {sensors}  |  Rows: {rows:,}")

    def populate_ref_sensor_combo(self, depth_columns: list[str]):
        """Populate the reference sensor dropdown with real column short names."""
        self.ref_sensor_combo.clear()
        for col in depth_columns:
            short = SensorData.get_short_name(col)
            self.ref_sensor_combo.addItem(short, userData=col)

    def get_ref_col(self) -> str | None:
        """Return the depth column name selected as reference."""
        return self.ref_sensor_combo.currentData()

    def display_offsets(self, results: list[TimeOffsetResult]):
        """Update the offset display with calculation results."""
        self.offset_text.clear()
        self.offset_text.append("Calculated Time Offsets:")
        self.offset_text.append("=" * 40)
        for r in results:
            short = SensorData.get_short_name(r.sensor_column)
            if r.is_reference:
                self.offset_text.append(f"{short}: 0.000s (reference)")
            else:
                self.offset_text.append(
                    f"{short}: {r.offset_seconds:+.3f}s  (RMS: {r.rms_value:.6f})"
                )

    def setup_manual_offsets(self, depth_columns: list[str]):
        """Build manual time-offset spinboxes for each depth column."""
        while self.manual_layout.count():
            item = self.manual_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.manual_offset_spinboxes = {}

        for i, col in enumerate(depth_columns):
            short = SensorData.get_short_name(col)
            self.manual_layout.addWidget(QLabel(f"{short}:"), i, 0)
            spinbox = QDoubleSpinBox()
            spinbox.setRange(-3600.0, 3600.0)
            spinbox.setSingleStep(0.1)
            spinbox.setDecimals(3)
            spinbox.setValue(0.0)
            spinbox.setToolTip(col)
            self.manual_layout.addWidget(spinbox, i, 1)
            self.manual_layout.addWidget(QLabel("s"), i, 2)
            self.manual_offset_spinboxes[col] = spinbox

    def get_manual_offsets(self) -> dict[str, float]:
        """Return manual offsets: depth_column -> offset_seconds."""
        return {col: spin.value() for col, spin in self.manual_offset_spinboxes.items()}

    def set_manual_offsets(self, offsets: dict[str, float]) -> None:
        """Set manual time-offset spinbox values from *offsets* (column -> seconds).

        Only spinboxes already created by ``setup_manual_offsets`` are updated.
        """
        for col, value in offsets.items():
            spin = self.manual_offset_spinboxes.get(col)
            if spin is not None:
                spin.setValue(float(value))

    def set_ref_col(self, col: str) -> None:
        """Select the reference sensor whose column name equals *col*."""
        for i in range(self.ref_sensor_combo.count()):
            if self.ref_sensor_combo.itemData(i) == col:
                self.ref_sensor_combo.setCurrentIndex(i)
                return

    def get_filter_params(self) -> tuple[float, float, int]:
        return (
            self.low_freq_spin.value(),
            self.high_freq_spin.value(),
            self.filter_order_spin.value(),
        )

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------
