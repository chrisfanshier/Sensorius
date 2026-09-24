"""PredictPanel - forward recoil prediction what-if mode."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget
from ...domain.processing.predict import CURVE_LABELS, CURVE_TYPES, Inputs, default_inputs


class PredictPanel(BaseModePanel):
    load_calibration_requested = Signal()
    predict_requested = Signal()
    overlay_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        defaults = default_inputs()

        calib_group = QGroupBox("Recoil Calibration")
        calib_layout = QVBoxLayout()
        self.calib_label = QLabel("No calibration loaded")
        self.calib_label.setWordWrap(True)
        calib_layout.addWidget(self.calib_label)
        load_btn = QPushButton("Load Calibration JSON…")
        load_btn.clicked.connect(self.load_calibration_requested.emit)
        calib_layout.addWidget(load_btn)
        calib_group.setLayout(calib_layout)
        self._layout.addWidget(calib_group)

        primary = QGroupBox("Deployment (required)")
        primary_form = QFormLayout()
        self.rope_combo = QComboBox()
        self.rope_combo.addItem("HMPE", "hmpe")
        self.rope_combo.addItem("Steel", "steel")
        self.rope_combo.setCurrentIndex(0 if defaults.rope_type == "hmpe" else 1)
        primary_form.addRow("Rope type:", self.rope_combo)

        self.depth_spin = self._depth_spin(defaults.depth_m)
        primary_form.addRow("Release depth at trip (m):", self.depth_spin)

        self.corer_spin = self._weight_spin(defaults.corer_lbs)
        primary_form.addRow("Corer weight (lb):", self.corer_spin)

        self.trigger_core_len_spin = self._ft_spin(defaults.trigger_core_length_ft, 100.0)
        primary_form.addRow("Trigger core length (ft):", self.trigger_core_len_spin)

        self.trigger_pen_spin = self._ft_spin(defaults.trigger_core_penetration_ft, 100.0)
        primary_form.addRow("Trigger core penetration (ft):", self.trigger_pen_spin)
        primary.setLayout(primary_form)
        self._layout.addWidget(primary)

        geometry = QGroupBox("Geometry")
        geo_form = QFormLayout()
        self.scope_spin = self._ft_spin(defaults.scope_ft, 500.0)
        geo_form.addRow("Scope (ft):", self.scope_spin)
        self.trigger_line_spin = self._ft_spin(defaults.trigger_line_length_ft, 500.0)
        geo_form.addRow("Trigger line length (ft):", self.trigger_line_spin)
        self.main_core_len_spin = self._ft_spin(defaults.main_core_length_ft, 500.0)
        geo_form.addRow("Main core length (ft):", self.main_core_len_spin)
        self.release_above_spin = self._small_spin(defaults.release_above_corer_m, 0.0, 20.0, 3)
        geo_form.addRow("Release above corer (m):", self.release_above_spin)
        self.rope_dia_spin = self._small_spin(defaults.rope_diameter_mm, 1.0, 100.0, 2)
        geo_form.addRow("Rope diameter (mm):", self.rope_dia_spin)
        geometry.setLayout(geo_form)
        self._layout.addWidget(geometry)

        corer_phys = QGroupBox("Corer freefall physics")
        corer_form = QFormLayout()
        self.displaced_vol_spin = self._small_spin(defaults.displaced_volume_m3, 0.0, 5.0, 3)
        corer_form.addRow("Displaced volume (m³):", self.displaced_vol_spin)
        self.added_mass_spin = self._small_spin(defaults.added_mass_coefficient, 0.0, 5.0, 2)
        corer_form.addRow("Added mass coefficient:", self.added_mass_spin)
        self.barrel_dia_spin = self._small_spin(defaults.barrel_diameter_in, 0.1, 50.0, 2)
        corer_form.addRow("Barrel diameter (in):", self.barrel_dia_spin)
        self.lead_flow_spin = self._small_spin(defaults.lead_flow_diameter_in, 0.1, 50.0, 2)
        corer_form.addRow("Lead flow diameter (in):", self.lead_flow_spin)
        self.lead_drag_spin = self._small_spin(defaults.lead_drag_coefficient, 0.0, 5.0, 2)
        corer_form.addRow("Lead drag coefficient:", self.lead_drag_spin)
        corer_phys.setLayout(corer_form)
        self._layout.addWidget(corer_phys)

        v0_group = QGroupBox("Pre-trip velocity ensemble")
        v0_form = QFormLayout()
        self.v0_mean_spin = self._small_spin(defaults.v0_mean_ms, -5.0, 5.0, 3, step=0.01)
        v0_form.addRow("Mean v0 (m/s):", self.v0_mean_spin)
        self.v0_std_spin = self._small_spin(defaults.v0_std_ms, 0.0, 3.0, 3, step=0.01)
        v0_form.addRow("v0 std dev (m/s):", self.v0_std_spin)
        self.v0_min_spin = self._small_spin(defaults.v0_min_ms, -5.0, 5.0, 3, step=0.01)
        v0_form.addRow("v0 min (m/s):", self.v0_min_spin)
        self.v0_max_spin = self._small_spin(defaults.v0_max_ms, -5.0, 5.0, 3, step=0.01)
        v0_form.addRow("v0 max (m/s):", self.v0_max_spin)
        self.v0_scenarios_spin = QSpinBox()
        self.v0_scenarios_spin.setRange(3, 2001)
        self.v0_scenarios_spin.setValue(defaults.v0_scenarios)
        v0_form.addRow("Scenarios:", self.v0_scenarios_spin)
        self.random_seed_spin = QSpinBox()
        self.random_seed_spin.setRange(0, 2_000_000_000)
        self.random_seed_spin.setValue(defaults.random_seed)
        v0_form.addRow("Random seed:", self.random_seed_spin)
        v0_group.setLayout(v0_form)
        self._layout.addWidget(v0_group)

        time_group = QGroupBox("Time grid")
        time_form = QFormLayout()
        self.time_before_spin = self._small_spin(defaults.time_before_s, 0.0, 20.0, 2)
        time_form.addRow("Seconds before trip:", self.time_before_spin)
        self.time_after_spin = self._small_spin(defaults.time_after_s, 0.5, 30.0, 2)
        time_form.addRow("Seconds after trip:", self.time_after_spin)
        self.dt_spin = QComboBox()
        for val in (0.005, 0.01, 0.02, 0.05):
            self.dt_spin.addItem(f"{val:g} s", val)
        self.dt_spin.setCurrentIndex(1)
        time_form.addRow("Output time step:", self.dt_spin)
        time_group.setLayout(time_form)
        self._layout.addWidget(time_group)

        plot_group = QGroupBox("Plot options")
        plot_layout = QVBoxLayout()
        mode_row = QHBoxLayout()
        self.single_curve_radio = QRadioButton("Single curve")
        self.all_curves_radio = QRadioButton("All curves")
        self.single_curve_radio.setChecked(True)
        mode_row.addWidget(self.single_curve_radio)
        mode_row.addWidget(self.all_curves_radio)
        plot_layout.addLayout(mode_row)
        self.curve_combo = QComboBox()
        for curve in CURVE_TYPES:
            self.curve_combo.addItem(CURVE_LABELS[curve], curve)
        plot_layout.addWidget(self.curve_combo)
        self.show_piston_check = QCheckBox("Show piston trajectory")
        self.show_piston_check.setChecked(True)
        self.show_piston_check.toggled.connect(self._on_plot_option_toggled)
        plot_layout.addWidget(self.show_piston_check)
        self.show_trigger_check = QCheckBox("Show trigger core/weight")
        self.show_trigger_check.setChecked(True)
        self.show_trigger_check.toggled.connect(self._on_plot_option_toggled)
        plot_layout.addWidget(self.show_trigger_check)
        self.overlay_actual_check = QCheckBox("Overlay actual sensor data")
        self.overlay_actual_check.setToolTip(
            "Plot measured weight stand, release, and piston on the model "
            "(single curve panel). Drag the trip line on the main plot to realign."
        )
        self.overlay_actual_check.toggled.connect(self._on_plot_option_toggled)
        plot_layout.addWidget(self.overlay_actual_check)
        self.trigger_line_label = QLabel("")
        self.trigger_line_label.setWordWrap(True)
        self.trigger_line_label.setStyleSheet("QLabel { color: #333; }")
        plot_layout.addWidget(self.trigger_line_label)
        plot_group.setLayout(plot_layout)
        self._layout.addWidget(plot_group)

        predict_btn = QPushButton("Run Prediction")
        predict_btn.clicked.connect(self.predict_requested.emit)
        self._layout.addWidget(predict_btn)

        self.log = LogWidget()
        self._layout.addWidget(self.log)

        self._finish_layout()

    def _on_plot_option_toggled(self, _checked: bool) -> None:
        """Drop the checkbox state; overlay_changed carries no arguments."""
        self.overlay_changed.emit()

    def update_calibration_info(self, filename: str, info_lines: list[str]) -> None:
        lines = [f"Loaded: {filename}"] + info_lines
        self.calib_label.setText("\n".join(lines))

    def get_inputs(self) -> Inputs:
        return Inputs(
            depth_m=self.depth_spin.value(),
            corer_lbs=self.corer_spin.value(),
            rope_type=self.rope_combo.currentData(),
            rope_diameter_mm=self.rope_dia_spin.value(),
            v0_mean_ms=self.v0_mean_spin.value(),
            v0_std_ms=self.v0_std_spin.value(),
            v0_min_ms=self.v0_min_spin.value(),
            v0_max_ms=self.v0_max_spin.value(),
            v0_scenarios=self.v0_scenarios_spin.value(),
            random_seed=self.random_seed_spin.value(),
            time_before_s=self.time_before_spin.value(),
            time_after_s=self.time_after_spin.value(),
            dt_s=float(self.dt_spin.currentData()),
            release_above_corer_m=self.release_above_spin.value(),
            displaced_volume_m3=self.displaced_vol_spin.value(),
            added_mass_coefficient=self.added_mass_spin.value(),
            barrel_diameter_in=self.barrel_dia_spin.value(),
            lead_flow_diameter_in=self.lead_flow_spin.value(),
            lead_drag_coefficient=self.lead_drag_spin.value(),
            scope_ft=self.scope_spin.value(),
            main_core_length_ft=self.main_core_len_spin.value(),
            trigger_line_length_ft=self.trigger_line_spin.value(),
            trigger_core_length_ft=self.trigger_core_len_spin.value(),
            trigger_core_penetration_ft=self.trigger_pen_spin.value(),
        )

    def get_selected_curves(self) -> list[str]:
        if self.all_curves_radio.isChecked():
            return list(CURVE_TYPES)
        return [self.curve_combo.currentData()]

    def show_piston(self) -> bool:
        return self.show_piston_check.isChecked()

    def show_trigger(self) -> bool:
        return self.show_trigger_check.isChecked()

    def overlay_actual_enabled(self) -> bool:
        return self.overlay_actual_check.isChecked()

    def populate_from_metadata(self, metadata: dict) -> None:
        """Fill geometry spinboxes from loaded core / CSV metadata."""
        if not metadata:
            return
        scope = metadata.get("scope")
        if scope is not None:
            self.scope_spin.setValue(float(scope))
        core_len = metadata.get("core_length")
        if core_len is not None:
            self.main_core_len_spin.setValue(float(core_len))
        trig_len = metadata.get("trigger_core_length")
        if trig_len is not None:
            self.trigger_core_len_spin.setValue(float(trig_len))
        trig_line = metadata.get("trigger_line_length")
        if trig_line is not None:
            self.trigger_line_spin.setValue(float(trig_line))

    def update_trigger_line_comparison(
        self,
        planned_ft: float | None,
        effective_ft: float | None,
        model_ft: float | None,
    ) -> None:
        parts = []
        if model_ft is not None:
            parts.append(f"Model input: {model_ft:.2f} ft")
        if planned_ft is not None:
            parts.append(f"Planned (core): {planned_ft:.2f} ft")
        if effective_ft is not None:
            parts.append(f"Measured @ trip: {effective_ft:.2f} ft")
            if planned_ft is not None:
                parts.append(f"Δ(meas−plan): {effective_ft - planned_ft:+.2f} ft")
            if model_ft is not None:
                parts.append(f"Δ(meas−model): {effective_ft - model_ft:+.2f} ft")
        elif self.overlay_actual_check.isChecked():
            parts.append("Measured @ trip: — (select trigger sensor in Calculate)")
        self.trigger_line_label.setText(" | ".join(parts))

    @staticmethod
    def _depth_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(1.0, 6000.0)
        spin.setDecimals(1)
        spin.setSingleStep(50.0)
        spin.setValue(value)
        return spin

    @staticmethod
    def _weight_spin(value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(100.0, 20000.0)
        spin.setDecimals(1)
        spin.setSingleStep(100.0)
        spin.setValue(value)
        return spin

    @staticmethod
    def _ft_spin(value: float, max_ft: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(0.0, max_ft)
        spin.setDecimals(2)
        spin.setSingleStep(0.5)
        spin.setValue(value)
        return spin

    @staticmethod
    def _small_spin(
        value: float,
        min_v: float,
        max_v: float,
        decimals: int,
        step: float = 0.1,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(min_v, max_v)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin
