"""
AlterPanel - Control panel for the "Alter" mode.

Displays DB-sourced core parameters that the user can modify.
Clicking "Estimate" re-runs piston position and calculate mode
with the altered values so the user can evaluate hypothetical
deployment configurations.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QGroupBox, QGridLayout, QVBoxLayout, QPushButton, QLabel,
    QDoubleSpinBox, QSpinBox,
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget


class AlterPanel(BaseModePanel):
    """
    Panel for the Alter mode.

    Signals
    -------
    estimate_requested : Signal()
        User clicked the Estimate button.
    """

    estimate_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # -- Core Parameters group --
        params_group = QGroupBox("Core Parameters")
        params_layout = QGridLayout()
        params_layout.setColumnStretch(1, 1)

        params_layout.addWidget(QLabel("Core Length (ft):"), 0, 0)
        self.core_length_spin = QDoubleSpinBox()
        self.core_length_spin.setRange(0.0, 500.0)
        self.core_length_spin.setDecimals(2)
        self.core_length_spin.setSingleStep(1.0)
        self.core_length_spin.setToolTip(
            "Core barrel length in feet. "
            "(Effect on calculations not yet implemented.)"
        )
        params_layout.addWidget(self.core_length_spin, 0, 1)

        params_layout.addWidget(QLabel("Scope (ft):"), 1, 0)
        self.scope_spin = QDoubleSpinBox()
        self.scope_spin.setRange(0.0, 500.0)
        self.scope_spin.setDecimals(2)
        self.scope_spin.setSingleStep(1.0)
        self.scope_spin.setToolTip(
            "Scope in feet. Increasing scope deepens piston position and "
            "delays the detected start-core point."
        )
        params_layout.addWidget(self.scope_spin, 1, 1)

        params_layout.addWidget(QLabel("Trigger Line Length (ft):"), 2, 0)
        self.trigger_line_spin = QDoubleSpinBox()
        self.trigger_line_spin.setRange(0.0, 200.0)
        self.trigger_line_spin.setDecimals(2)
        self.trigger_line_spin.setSingleStep(1.0)
        self.trigger_line_spin.setToolTip(
            "Trigger line length in feet. Changes are applied as a vertical "
            "shift to both the weight-stand and release-device depth traces "
            "before recalculating. Increasing length subtracts depth "
            "(shallower); decreasing adds depth (deeper)."
        )
        params_layout.addWidget(self.trigger_line_spin, 2, 1)

        params_layout.addWidget(QLabel("Trigger Core Length (ft):"), 3, 0)
        self.trigger_core_spin = QDoubleSpinBox()
        self.trigger_core_spin.setRange(0.0, 200.0)
        self.trigger_core_spin.setDecimals(2)
        self.trigger_core_spin.setSingleStep(1.0)
        self.trigger_core_spin.setToolTip(
            "Trigger core length in feet. "
            "(Effect on calculations not yet implemented.)"
        )
        params_layout.addWidget(self.trigger_core_spin, 3, 1)

        params_layout.addWidget(QLabel("Trigger Pen (m):"), 4, 0)
        self.trigger_pen_spin = QDoubleSpinBox()
        self.trigger_pen_spin.setRange(0.0, 100.0)
        self.trigger_pen_spin.setDecimals(2)
        self.trigger_pen_spin.setSingleStep(0.1)
        self.trigger_pen_spin.setToolTip(
            "Estimated trigger core penetration in metres. "
            "Increasing this raises the computed seafloor depth."
        )
        params_layout.addWidget(self.trigger_pen_spin, 4, 1)

        params_layout.addWidget(QLabel("Number of Pigs:"), 5, 0)
        self.num_pigs_spin = QSpinBox()
        self.num_pigs_spin.setRange(0, 20)
        self.num_pigs_spin.setToolTip(
            "Number of lead pigs on the weight stand. "
            "(Effect on calculations not yet implemented.)"
        )
        params_layout.addWidget(self.num_pigs_spin, 5, 1)

        params_group.setLayout(params_layout)
        self._layout.addWidget(params_group)

        # -- Estimate button --
        self.estimate_btn = QPushButton("Estimate")
        font = QFont()
        font.setBold(True)
        self.estimate_btn.setFont(font)
        self.estimate_btn.setEnabled(False)
        self.estimate_btn.setToolTip(
            "Re-run piston position and calculate mode with altered parameters."
        )
        self.estimate_btn.clicked.connect(self.estimate_requested)
        self._layout.addWidget(self.estimate_btn)

        # -- Log --
        self.log_widget = LogWidget(max_height=150)
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def populate_from_core_info(
        self,
        core_info: dict,
        trigger_pen: float = 0.0,
    ):
        """Fill spinboxes from database core_info dict and enable Estimate.

        Parameters
        ----------
        core_info : dict
            Database core record (keys: core_length, scope,
            trigger_line_length, trigger_core_length, pig_weights).
        trigger_pen : float
            Current trigger penetration value from the Calculate panel (m).
        """
        self.core_length_spin.setValue(float(core_info.get('core_length') or 0.0))
        self.scope_spin.setValue(float(core_info.get('scope') or 0.0))
        self.trigger_line_spin.setValue(
            float(core_info.get('trigger_line_length') or 0.0)
        )
        self.trigger_core_spin.setValue(
            float(core_info.get('trigger_core_length') or 0.0)
        )
        self.trigger_pen_spin.setValue(trigger_pen)
        self.num_pigs_spin.setValue(int(core_info.get('pig_weights') or 0))
        self.estimate_btn.setEnabled(True)

    # -- Accessors --

    def get_scope(self) -> float:
        return self.scope_spin.value()

    def get_trigger_line_length(self) -> float:
        return self.trigger_line_spin.value()

    def get_core_length(self) -> float:
        return self.core_length_spin.value()

    def get_trigger_core_length(self) -> float:
        return self.trigger_core_spin.value()

    def get_trigger_pen(self) -> float:
        return self.trigger_pen_spin.value()

    def get_num_pigs(self) -> int:
        return self.num_pigs_spin.value()
