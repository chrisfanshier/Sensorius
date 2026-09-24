"""
PistonAnalysisPanel - Control panel for the "Piston Analysis" mode.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QGridLayout, QVBoxLayout, QPushButton, QLabel,
    QSpinBox, QDoubleSpinBox,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget


class PistonAnalysisPanel(BaseModePanel):
    """
    Panel for the Piston Analysis mode.

    Signals
    -------
    load_file_requested(str)
        User selected a CSV file to load.
    analyze_requested
        User clicked "Analyze".
    plot_original_requested
        User clicked "Plot Data".
    """

    load_file_requested = Signal(str)
    analyze_requested = Signal()
    plot_original_requested = Signal()

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

        # -- Status ----------------------------------------------------------
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("No data loaded.")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)

        status_group.setLayout(status_layout)
        self._layout.addWidget(status_group)

        # -- SG Parameters ---------------------------------------------------
        sg_group = QGroupBox("Savitzky-Golay Parameters")
        sg_layout = QGridLayout()

        sg_layout.addWidget(QLabel("Window Length:"), 0, 0)
        self.sg_window_spin = QSpinBox()
        self.sg_window_spin.setRange(5, 501)
        self.sg_window_spin.setSingleStep(2)
        self.sg_window_spin.setValue(51)
        self.sg_window_spin.setToolTip(
            "SG filter window length (must be odd). "
            "Larger values = smoother velocity."
        )
        sg_layout.addWidget(self.sg_window_spin, 0, 1)

        sg_layout.addWidget(QLabel("Polynomial Order:"), 1, 0)
        self.sg_polyorder_spin = QSpinBox()
        self.sg_polyorder_spin.setRange(1, 10)
        self.sg_polyorder_spin.setValue(3)
        sg_layout.addWidget(self.sg_polyorder_spin, 1, 1)

        sg_group.setLayout(sg_layout)
        self._layout.addWidget(sg_group)

        # -- Actions ---------------------------------------------------------
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout()

        self.plot_btn = QPushButton("Plot Data")
        self.plot_btn.clicked.connect(self.plot_original_requested)
        actions_layout.addWidget(self.plot_btn)

        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.clicked.connect(self.analyze_requested)
        actions_layout.addWidget(self.analyze_btn)

        actions_group.setLayout(actions_layout)
        self._layout.addWidget(actions_group)

        # -- Log -------------------------------------------------------------
        self.log_widget = LogWidget()
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_sg_window(self) -> int:
        return self.sg_window_spin.value()

    def get_sg_polyorder(self) -> int:
        return self.sg_polyorder_spin.value()

    def update_status(self, text: str):
        self.status_label.setText(text)

    def update_file_info(self, filename: str):
        self.file_label.setText(filename)
