"""
TripDetectorPanel - Control panel for the "Trip Detector" mode.

Savitzky-Golay parameters, derivative order, threshold, and trip
detection controls.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGridLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget


class TripDetectorPanel(BaseModePanel):
    """
    Panel for the Trip Detector mode.

    Signals:
        load_file_requested(str): User selected a CSV file.
        detect_trip_requested: User clicked "Detect Trip".
        plot_original_requested: User clicked "Plot Original Data".
        export_requested: User clicked "Export Corrected Data".
    """

    load_file_requested = Signal(str)
    detect_trip_requested = Signal()
    plot_original_requested = Signal()
    export_requested = Signal()
    save_to_db_requested = Signal()

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

        # -- Savitzky-Golay Parameters --
        sg_group = QGroupBox("Savitzky-Golay Filter")
        sg_layout = QGridLayout()

        sg_layout.addWidget(QLabel("Window Length:"), 0, 0)
        self.sg_window_spin = QSpinBox()
        self.sg_window_spin.setRange(5, 501)
        self.sg_window_spin.setSingleStep(2)
        self.sg_window_spin.setValue(51)
        self.sg_window_spin.setToolTip(
            "Window length for Savitzky-Golay filter (must be odd). "
            "Larger = smoother."
        )
        sg_layout.addWidget(self.sg_window_spin, 0, 1)

        sg_layout.addWidget(QLabel("Polynomial Order:"), 1, 0)
        self.sg_poly_spin = QSpinBox()
        self.sg_poly_spin.setRange(1, 5)
        self.sg_poly_spin.setValue(3)
        self.sg_poly_spin.setToolTip("Polynomial order (typically 2-3).")
        sg_layout.addWidget(self.sg_poly_spin, 1, 1)

        sg_group.setLayout(sg_layout)
        self._layout.addWidget(sg_group)

        # -- Trip Detection Parameters --
        trip_group = QGroupBox("Trip Detection Parameters")
        trip_layout = QGridLayout()

        trip_layout.addWidget(QLabel("Derivative Order:"), 0, 0)
        self.derivative_combo = QComboBox()
        self.derivative_combo.addItems([
            "0 - Smoothed Depth",
            "1 - Velocity",
            "2 - Acceleration",
            "3 - Jerk",
        ])
        self.derivative_combo.setCurrentIndex(1)
        self.derivative_combo.setToolTip(
            "Which derivative to use for divergence detection."
        )
        trip_layout.addWidget(self.derivative_combo, 0, 1)

        trip_layout.addWidget(QLabel("Std Threshold:"), 1, 0)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.001, 100.0)
        self.threshold_spin.setSingleStep(0.1)
        self.threshold_spin.setDecimals(3)
        self.threshold_spin.setValue(0.5)
        self.threshold_spin.setToolTip(
            "Divergence threshold (std dev across sensors). "
            "Trip is detected when divergence exceeds this value."
        )
        trip_layout.addWidget(self.threshold_spin, 1, 1)

        trip_layout.addWidget(QLabel("Sampling Rate (Hz):"), 2, 0)
        self.sampling_rate_spin = QDoubleSpinBox()
        self.sampling_rate_spin.setRange(0.1, 1000.0)
        self.sampling_rate_spin.setSingleStep(1.0)
        self.sampling_rate_spin.setDecimals(1)
        self.sampling_rate_spin.setValue(32.0)
        self.sampling_rate_spin.setToolTip("Data sampling rate in Hz.")
        trip_layout.addWidget(self.sampling_rate_spin, 2, 1)

        trip_layout.addWidget(QLabel("Edge Buffer (samples):"), 3, 0)
        self.edge_buffer_spin = QSpinBox()
        self.edge_buffer_spin.setRange(0, 10000)
        self.edge_buffer_spin.setSingleStep(100)
        self.edge_buffer_spin.setValue(500)
        self.edge_buffer_spin.setToolTip(
            "Number of samples to exclude from the edges to avoid "
            "filter artifacts."
        )
        trip_layout.addWidget(self.edge_buffer_spin, 3, 1)

        trip_group.setLayout(trip_layout)
        self._layout.addWidget(trip_group)

        # -- Detection Results --
        result_group = QGroupBox("Detection Results")
        result_layout = QVBoxLayout()
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(150)
        self.result_text.setText("Click 'Detect Trip' to run analysis")
        result_layout.addWidget(self.result_text)
        result_group.setLayout(result_layout)
        self._layout.addWidget(result_group)

        # -- Actions --
        action_group = QGroupBox("Actions")
        action_layout = QVBoxLayout()

        plot_btn = QPushButton("Plot Original Data")
        plot_btn.clicked.connect(self.plot_original_requested.emit)
        action_layout.addWidget(plot_btn)

        detect_btn = QPushButton("Detect Trip")
        detect_btn.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 6px; }"
        )
        detect_btn.clicked.connect(self.detect_trip_requested.emit)
        action_layout.addWidget(detect_btn)

        export_btn = QPushButton("Export Corrected Data")
        export_btn.clicked.connect(self.export_requested.emit)
        export_btn.setToolTip(
            "Export data with trip detection metadata and "
            "applied corrections to CSV file"
        )
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
        self.file_label.setText(
            f"File: {filename}\nSensors: {sensors}  |  Rows: {rows:,}"
        )

    def get_sg_params(self) -> tuple[int, int]:
        """Return (window_length, poly_order)."""
        window = self.sg_window_spin.value()
        # Ensure window is odd
        if window % 2 == 0:
            window += 1
        return window, self.sg_poly_spin.value()

    def get_derivative_order(self) -> int:
        """Return the selected derivative order (0-3)."""
        return self.derivative_combo.currentIndex()

    def get_threshold(self) -> float:
        return self.threshold_spin.value()

    def get_sampling_rate(self) -> float:
        return self.sampling_rate_spin.value()

    def get_edge_buffer(self) -> int:
        return self.edge_buffer_spin.value()

    def display_result(self, summary: str):
        """Show detection result summary."""
        self.result_text.clear()
        self.result_text.setText(summary)
