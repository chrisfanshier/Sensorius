"""
AnalysisController - Central coordinator for the application.

Manages mode switching, data flow between panels/views, and calls
into domain processing logic. This keeps the GUI panels thin and
the business logic testable.

All depth columns keep their ORIGINAL CSV names throughout -- no
A/B/C/D aliasing ever occurs in this layer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
from scipy import stats as sp_stats

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..domain.models.sensor_data import SensorData, CorrectionRecord
from ..domain.models.calibration import DepthCalibration
from ..domain.models.analysis_result import StatisticsResult, TimeOffsetResult
from ..domain.processing.depth_correction import DepthCorrectionProcessor
from ..domain.processing.time_correction import TimeCorrectionProcessor
from ..domain.processing.trip_detection import TripDetectionProcessor
from ..domain.processing.calibration_builder import CalibrationBuilder
from ..domain.processing.statistics import compute_statistics
from ..domain.processing.piston_position import (
    compute_piston_position, detect_start_core,
)
from ..domain.processing.calculations import (
    compute_calculations,
    format_results,
    apply_savgol,
    DEFAULT_WEIGHT_STAND_LENGTH_M,
)
from ..domain.processing.piston_analysis import (
    PistonAnalysisProcessor,
)
from ..domain.processing.winch_trip_detection import WinchTripDetectionProcessor
from ..gui.views.calculation_plot_view import GeometryInput
from ..persistence.calibration_io import CalibrationIO
from ..persistence.recoil_calibration_io import RecoilCalibrationIO
from ..domain.models.recoil_calibration import RecoilCalibration
from ..domain.processing.predict import run_prediction, training_warnings
from ..domain.processing.predict_overlay import build_actual_overlay
from ..persistence.loader import ProjectDataLoader
from ..persistence.winch_loader import WinchLoader, get_winch_parameters, datetime_to_epoch, timestamp_to_epoch
from ..persistence import results_io
from ..persistence.project import ProjectStore


class AnalysisController:
    """
    Coordinates all application logic.

    Holds references to GUI panels and views, connects signals,
    and delegates to domain processing.
    """

    def __init__(self):
        # State
        self.sensor_data: Optional[SensorData] = None      # Primary data
        self.original_data: Optional[SensorData] = None     # Backup for reset
        self._loaded_file_path: Optional[str] = None        # Full path to loaded file
        self._loaded_core_id: Optional[int] = None           # core_id when loaded from DB
        self._loaded_cruise_id: Optional[int] = None         # cruise_id when loaded from DB
        self.calibration: Optional[DepthCalibration] = None
        self.generated_calibration: Optional[DepthCalibration] = None
        self.time_offset_results: Optional[list[TimeOffsetResult]] = None
        self.trip_detection_result = None
        self._heave_profiles: Optional[dict[str, np.ndarray]] = None
        self._heave_time_axis: Optional[np.ndarray] = None
        self._heave_fs: Optional[float] = None
        self._heave_sel: Optional[tuple[int, int]] = None
        self.collected_statistics: list[StatisticsResult] = []
        self._piston_start_core_idx: Optional[int] = None
        self._piston_values: Optional[np.ndarray] = None
        self._start_pen_idx: Optional[int] = None
        # Set when the user drags the start-pen line; suppresses the automatic
        # core-tip/seafloor intersection so the drag is not recomputed away.
        self._manual_start_pen: Optional[int] = None

        # GUI references (set by main_window after construction)
        self.main_window = None
        self.main_plot = None
        self.secondary_view = None  # heave plot or stats table
        self.heave_plot = None
        self.statistics_table = None
        self.trip_plot = None
        self.calculation_plot = None
        self.calibration_plot = None
        self.piston_analysis_view = None
        self.winch_panel = None
        self.winch_plot_view = None

        # Winch mode state
        self._winch_df: Optional[pd.DataFrame] = None
        self._winch_df_original: Optional[pd.DataFrame] = None
        self._winch_file_names: list[str] = []
        self._winch_file_ids: list[int] = []
        self._winch_list_cruise_id: Optional[int] = None
        self._winch_trip_idx: Optional[int] = None
        self._winch_trip_result = None
        self._winch_time_offset_sec: float = 0.0
        self._winch_aligned: bool = False
        self._winch_load_mode: str = 'auto'

        # Panels
        self.view_panel = None
        self.depth_panel = None
        self.time_panel = None
        self.calibration_panel = None
        self.trip_panel = None
        self.piston_panel = None
        self.calculate_panel = None
        self.alter_panel = None
        self.piston_analysis_panel = None
        self.winch_panel = None
        self.predict_panel = None
        self.predict_plot_view = None
        self.recoil_calibration: Optional[RecoilCalibration] = None
        self._last_predict_result = None
        self._predict_settings = QSettings("Sensorius", "sensor_standalone")
        self._loaded_core_info: Optional[dict] = None

        # Alter mode state
        self._alter_core_info: Optional[dict] = None

        # Calculate mode state
        self._calc_start_core_idx: Optional[int] = None
        self._end_pen_idx: Optional[int] = None
        self._pullout_idx: Optional[int] = None
        self._last_calc_results = None
        self._last_calc_inputs: Optional[dict] = None
        self._manual_seafloor: Optional[float] = None  # None = use trigger formula

        self.store: Optional[ProjectStore] = None
        self._data_loader: Optional[ProjectDataLoader] = None
        self._winch_loader: Optional[WinchLoader] = None

    def set_store(self, store: Optional[ProjectStore]):
        """Attach the open project store (or None when no project is open)."""
        self.store = store
        self._data_loader = ProjectDataLoader(store) if store else None
        self._winch_loader = WinchLoader(store) if store else None

    # ==================================================================
    # Initialization - called by MainWindow
    # ==================================================================

    def connect_signals(self):
        """Wire up all panel signals to controller methods."""
        # View Data panel
        self.view_panel.plot_depths_requested.connect(self.plot_depths)
        self.view_panel.plot_differences_requested.connect(self.plot_differences)

        # Depth Offset panel
        self.depth_panel.load_calibration_requested.connect(self.load_calibration)
        self.depth_panel.ref_sensor_combo.currentTextChanged.connect(
            self._update_depth_correction_plan
        )
        self.depth_panel.apply_corrections_requested.connect(self.apply_depth_corrections)
        self.depth_panel.reset_requested.connect(self.reset_to_original)
        self.depth_panel.export_requested.connect(self.export_corrected_csv)
        self.depth_panel.plot_original_requested.connect(self.plot_depths)

        # Time Offset panel
        self.time_panel.selection_mode_changed.connect(self._set_selection_mode)
        self.time_panel.clear_selection_requested.connect(self._clear_selection)
        self.time_panel.calculate_offsets_requested.connect(self.calculate_time_offsets)
        self.time_panel.apply_correction_requested.connect(self.apply_time_corrections)
        self.time_panel.apply_manual_requested.connect(self.apply_manual_time_corrections)
        self.time_panel.reset_requested.connect(self.reset_to_original)
        self.time_panel.export_requested.connect(self.export_corrected_csv)
        self.time_panel.plot_original_requested.connect(self.plot_depths)

        # Create Calibration panel
        self.calibration_panel.cruise_selected.connect(self._on_cal_cruise_selected)
        self.calibration_panel.cast_core_selected.connect(self._load_cast_from_database)
        self.calibration_panel.selection_mode_changed.connect(self._set_selection_mode)
        self.calibration_panel.clear_selection_requested.connect(self._clear_selection)
        self.calibration_panel.add_statistics_requested.connect(self._add_statistics)
        self.calibration_panel.generate_calibration_requested.connect(
            self._generate_calibration
        )
        self.calibration_panel.save_calibration_requested.connect(
            self._save_calibration
        )

        # Main plot selection signal
        self.main_plot.selection_changed.connect(self._on_selection_changed)
        self.main_plot.selection_cleared.connect(self._on_selection_cleared)

        # Trip Detector panel
        self.trip_panel.detect_trip_requested.connect(self.detect_trip)
        self.trip_panel.plot_original_requested.connect(self.plot_depths)
        self.trip_panel.export_requested.connect(self.export_trip_csv)

        # Piston Position panel
        self.piston_panel.calculate_requested.connect(self.calculate_piston)
        self.piston_panel.plot_original_requested.connect(self.plot_depths)

        # Main plot start_core drag signal
        self.main_plot.start_core_changed.connect(self._on_start_core_moved)

        # Main plot trip line drag signal
        self.main_plot.trip_line_changed.connect(self._on_trip_line_moved)

        # Main plot end-of-penetration line drag signal
        self.main_plot.end_pen_changed.connect(self._on_end_pen_moved)

        # Main plot pullout line drag signal
        self.main_plot.pullout_changed.connect(self._on_pullout_moved)

        # Main plot start-pen drag signal
        self.main_plot.start_pen_changed.connect(self._on_start_pen_moved)

        # Main plot seafloor drag signal
        self.main_plot.seafloor_changed.connect(self._on_seafloor_dragged)

        # Calculate panel seafloor override signals
        self.calculate_panel.seafloor_override_changed.connect(
            self._on_seafloor_override_changed
        )
        self.calculate_panel.seafloor_estimate_requested.connect(
            self._estimate_seafloor_from_trip
        )

        # Piston export
        self.piston_panel.export_piston_requested.connect(self.export_piston_csv)

        # Save All to DB — single toolbar action
        if self.main_window is not None:
            self.main_window.save_all_action.triggered.connect(self.save_all_to_db)
            self.main_window.restore_action.triggered.connect(self._on_restore_results)

        # Calculate panel
        self.calculate_panel.calculate_requested.connect(self.run_calculations)
        self.calculate_panel.plot_original_requested.connect(
            self._plot_calculate_mode
        )
        self.calculate_panel.export_results_requested.connect(
            self.export_calculation_results
        )
        self.calculate_panel.reset_lines_requested.connect(self._reset_lines)
        self.calculate_panel.export_diagram_requested.connect(
            self.export_calculation_diagram
        )

        # Alter panel
        if self.alter_panel is not None:
            self.alter_panel.estimate_requested.connect(
                self._run_alter_estimation
            )

        # Piston Analysis panel
        if self.piston_analysis_panel is not None:
            self.piston_analysis_panel.plot_original_requested.connect(
                self.plot_depths
            )
            self.piston_analysis_panel.analyze_requested.connect(
                self.run_piston_analysis
            )

        # Predict panel
        if self.predict_panel is not None:
            self.predict_panel.load_calibration_requested.connect(
                self._prompt_load_recoil_calibration
            )
            self.predict_panel.predict_requested.connect(self.run_predict)
            self.predict_panel.overlay_changed.connect(self._on_predict_overlay_changed)

        # Winch panel
        if self.winch_panel is not None:
            self.winch_panel.reload_requested.connect(self.reload_winch_data)
            self.winch_panel.plot_settings_changed.connect(
                self._update_winch_plot
            )
            self.winch_panel.detect_winch_trip_requested.connect(
                self.detect_winch_trip
            )
            self.winch_panel.align_winch_requested.connect(
                self.align_winch_data
            )
            self.winch_panel.reset_winch_requested.connect(
                self.reset_winch_alignment
            )
            self.winch_panel.search_region_toggled.connect(
                self._on_winch_search_region_toggled
            )

        if self.winch_plot_view is not None:
            self.winch_plot_view.winch_trip_line_changed.connect(
                self._on_winch_trip_line_moved
            )
            self.winch_plot_view.search_region_changed.connect(
                self._on_winch_search_region_changed
            )

    # ==================================================================
    # Data Loading
    # ==================================================================

    def load_from_database(self, core_id: int, core_info: dict, cruise_id: Optional[int] = None):
        """Load sensor data for a core from the open project."""
        if self._data_loader is None:
            self._show_error("No Project", "Open or create a project first.")
            return
        try:
            self.main_plot.clear_selection()

            self.sensor_data = self._data_loader.load_core_sensor_data(
                core_id, core_info,
            )
            self.original_data = self.sensor_data.copy()
            self._loaded_file_path = None
            self._loaded_core_id = core_id
            self._loaded_cruise_id = cruise_id
            self._loaded_core_info = dict(core_info)
            self._alter_core_info = dict(core_info)

            self._reset_analysis_state()
            self._apply_core_trigger_penetration(core_info)
            self._update_all_panels_file_info()
            self.main_plot.set_sensor_data(self.sensor_data)
            self.plot_depths()

            self._log_active(
                f"Loaded from project: {core_info.get('core_name', core_id)} "
                f"({self.sensor_data.row_count:,} rows, "
                f"{self.sensor_data.num_sensors} sensors)"
            )
            if self.main_window:
                self.main_window.statusBar().showMessage(
                    f"Loaded {core_info.get('core_name', '')} — "
                    f"{self.sensor_data.row_count:,} rows, "
                    f"{self.sensor_data.num_sensors} sensors"
                )
            if self.main_window is not None:
                self.main_window.restore_action.setEnabled(True)
        except Exception as e:
            self._show_error("Project Load Error", str(e))
            self._log_active(f"LOAD ERROR: {e}")

    def _apply_core_trigger_penetration(self, core_info: dict):
        """Pre-fill Calculate panel from core metadata when available."""
        if self.calculate_panel is None:
            return
        pen = core_info.get("trigger_core_penetration")
        if pen is not None:
            try:
                val = float(pen)
                if val > 0:
                    self.calculate_panel.set_trigger_pen(val)
            except (TypeError, ValueError):
                pass

    def _sync_trigger_penetration_to_core(self):
        """Persist trigger penetration from Calculate panel back to the core row."""
        if self.store is None or self._loaded_core_id is None or self.calculate_panel is None:
            return
        pen = self.calculate_panel.get_trigger_pen()
        if pen and pen > 0:
            self.store.update_trigger_core_penetration(self._loaded_core_id, pen)

    def _reset_analysis_state(self):
        """Clear stale analysis state from a previous load."""
        self.trip_detection_result = None
        self._piston_start_core_idx = None
        self._piston_values = None
        self._start_pen_idx = None
        self._manual_start_pen = None
        self._calc_start_core_idx = None
        self._end_pen_idx = None
        self._pullout_idx = None
        self._last_calc_results = None
        self._last_calc_inputs = None
        self._manual_seafloor = None
        self._heave_profiles = None
        self._heave_sel = None
        self._reset_winch_state()
        # Restore button requires a DB core with saved results
        if self.main_window is not None:
            self.main_window.restore_action.setEnabled(False)

    def _reset_winch_state(self):
        """Drop winch data and alignment belonging to the previously loaded core.

        Alignment is core-specific, so leaving it set would let the previous
        core's trip index and file ids be written to the new core's row.
        """
        self._winch_df = None
        self._winch_df_original = None
        self._winch_file_names = []
        self._winch_file_ids = []
        self._clear_winch_trip_state()

    def load_calibration(self, file_path: str):
        """Load a JSON calibration file and set up mapping UI."""
        try:
            self.calibration = CalibrationIO.load(file_path)
            filename = Path(file_path).name

            info_lines = [f"Loaded calibration: {filename}"]
            for reg in self.calibration.regressions:
                info_lines.append(
                    f"  {reg.sensor_j} - {reg.sensor_i}: "
                    f"slope={reg.slope:.6f}, intercept={reg.intercept:.6f}, "
                    f"R\u00b2={reg.r_squared:.4f}"
                )

            self.depth_panel.update_calibration_info(filename, info_lines)

            # Set up calibration label -> column mapping UI
            cal_labels = self.calibration.sensor_labels
            if self.sensor_data is not None:
                self.depth_panel.setup_calibration_mapping(
                    cal_labels, self.sensor_data.depth_columns,
                )

            self._update_depth_correction_plan()
            self._log_active(f"Calibration loaded: {filename}")
        except Exception as e:
            self._show_error("Calibration Error", str(e))
            self._log_active(f"ERROR loading calibration: {e}")

    # ==================================================================
    # Plotting
    # ==================================================================

    def plot_depths(self):
        """Plot depth traces on the main plot."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return
        title = self.sensor_data.core_title or ''
        self.main_plot.plot_depths(self.sensor_data, title=title)

    def plot_differences(self):
        """Plot pairwise differences on the main plot."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return
        self.main_plot.plot_differences(self.sensor_data)

    # ==================================================================
    # Depth Offset Mode
    # ==================================================================

    def apply_depth_corrections(self):
        """
        Apply depth calibration and manual offsets.

        Uses the calibration label -> column mapping from the depth panel
        and delegates to the DepthCorrectionProcessor.
        """
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        try:
            # Work on a copy from original
            working = self.original_data.copy()
            panel = self.depth_panel

            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("APPLYING CORRECTIONS")
            panel.log_widget.log(f"{'='*50}")

            # Apply regression corrections if calibration loaded
            correction_results = {}
            if self.calibration is not None and panel.correction_checkboxes:
                # Get calibration mapping and reference (only needed for regression)
                cal_mapping = panel.get_calibration_mapping()  # cal_label -> col_name
                ref_label = panel.get_ref_sensor()             # calibration label

                # Find corresponding column for reference
                ref_col = cal_mapping.get(ref_label)
                if ref_col is None:
                    self._show_warning(
                        f"Reference sensor '{ref_label}' is not mapped to a column.\n"
                        f"Check the calibration label mapping."
                    )
                    return

                ref_short = SensorData.get_short_name(ref_col)
                panel.log_widget.log(
                    f"Reference: {ref_label} = {ref_short} (will NOT be modified)"
                )
                panel.log_widget.log(f"{'='*50}")
                enabled_targets = panel.get_enabled_calibration_targets()

                panel.log_widget.log("\nApplying depth-dependent corrections...")
                correction_results = DepthCorrectionProcessor.apply_calibration(
                    working,
                    self.calibration,
                    ref_col,
                    cal_mapping,
                    enabled_targets,
                )

                for col, stats in correction_results.items():
                    short = SensorData.get_short_name(col)
                    panel.log_widget.log(
                        f"\n{short}: correction range "
                        f"{stats['min']:+.4f}m to {stats['max']:+.4f}m"
                    )
                    panel.log_widget.log(
                        f"  Mean: {stats['mean']:+.4f}m \u00b1 {stats['std']:.4f}m"
                    )

            # Apply manual offsets
            manual = panel.get_manual_offsets()
            applied_manual = DepthCorrectionProcessor.apply_manual_offsets(
                working, manual,
            )
            if applied_manual:
                panel.log_widget.log("\nManual offsets:")
                for col, offset in applied_manual.items():
                    short = SensorData.get_short_name(col)
                    panel.log_widget.log(f"  {short}: {offset:+.4f}m")

            self.sensor_data = working
            self.main_plot.set_sensor_data(self.sensor_data)

            # Build label suffixes showing applied corrections
            suffixes = {}
            for col in working.depth_columns:
                if col in correction_results or col in applied_manual:
                    short = SensorData.get_short_name(col)
                    suffixes[col] = f" ({short} corrected)"

            self.main_plot.plot_depths_with_labels(
                self.sensor_data, suffixes,
                title=self.sensor_data.core_title or 'Corrected Data',
            )

            panel.log_widget.log("Corrections applied and plotted!")

        except Exception as e:
            self._show_error("Correction Error", str(e))
            self.depth_panel.log_widget.log(f"ERROR: {e}")

    def _update_depth_correction_plan(self, _=None):
        """Update the correction plan display based on current calibration + ref."""
        if self.calibration is None:
            self.depth_panel.update_correction_plan([])
            return

        ref = self.depth_panel.ref_sensor_combo.currentText()
        applicable = self.calibration.get_applicable_corrections(ref)
        self.depth_panel.update_correction_plan(applicable)

    # ==================================================================
    # Time Offset Mode
    # ==================================================================

    def calculate_time_offsets(self):
        """Calculate time offsets using heave cross-correlation method."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        sel = self.main_plot.selection
        if sel is None:
            self._show_warning("Please select a time range first")
            return

        try:
            start_idx, end_idx = sel
            panel = self.time_panel
            low_freq, high_freq, filter_order = panel.get_filter_params()
            ref_col = panel.get_ref_col()

            if ref_col is None:
                self._show_warning("Select a reference sensor")
                return

            ref_short = SensorData.get_short_name(ref_col)
            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("CALCULATING TIME OFFSETS (Heave Cross-Correlation)")
            panel.log_widget.log(f"Range: rows {start_idx}-{end_idx}")
            panel.log_widget.log(
                f"Bandpass: {low_freq:.3f}-{high_freq:.3f} Hz, order {filter_order}"
            )
            panel.log_widget.log(f"Reference: {ref_short}")
            panel.log_widget.log(f"{'='*50}")

            # Compute heave profiles for visualization
            heaves, fs = TimeCorrectionProcessor.compute_heave_profiles(
                self.sensor_data, start_idx, end_idx,
                low_freq, high_freq, filter_order,
            )
            self._heave_profiles = heaves
            self._heave_fs = fs
            self._heave_sel = (start_idx, end_idx)

            panel.log_widget.log(
                f"Sampling rate: {fs:.2f} Hz ({1/fs:.4f}s interval)"
            )

            # Build a relative-seconds time axis for the selection
            dt_col = self.sensor_data.datetime_col
            df_sel = self.sensor_data.df.iloc[start_idx:end_idx + 1]
            timestamps = pd.to_datetime(df_sel[dt_col])
            t_sec = (timestamps - timestamps.iloc[0]).dt.total_seconds().values
            self._heave_time_axis = t_sec

            # Calculate offsets
            self.time_offset_results = TimeCorrectionProcessor.calculate_offsets(
                self.sensor_data, start_idx, end_idx,
                ref_col, low_freq, high_freq, filter_order,
            )

            for r in self.time_offset_results:
                short = SensorData.get_short_name(r.sensor_column)
                if r.is_reference:
                    panel.log_widget.log(f"{short}: 0.0000s (reference)")
                else:
                    panel.log_widget.log(
                        f"{short}: {r.offset_seconds:+.4f}s "
                        f"(heave RMS: {r.rms_value:.6f}m)"
                    )

            panel.display_offsets(self.time_offset_results)

            # Show uncorrected heave on secondary plot
            if self.heave_plot is not None:
                self.heave_plot.plot_heave_uncorrected(
                    heaves, ref_col, time_axis=t_sec,
                )
                self.main_window.show_secondary_view('heave')

            panel.log_widget.log("Offset calculation complete!")

        except Exception as e:
            self._show_error("Calculation Error", str(e))
            self.time_panel.log_widget.log(f"ERROR: {e}")

    def apply_time_corrections(self):
        """Apply calculated time offsets."""
        if self.time_offset_results is None:
            self._show_warning("Calculate offsets first")
            return

        try:
            panel = self.time_panel
            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("APPLYING TIME CORRECTIONS")
            panel.log_widget.log(f"{'='*50}")

            self.sensor_data = TimeCorrectionProcessor.apply_offsets(
                self.sensor_data, self.time_offset_results
            )
            self.main_plot.set_sensor_data(self.sensor_data)

            # Build label suffixes keyed by column name
            suffixes = {}
            for r in self.time_offset_results:
                if not r.is_reference:
                    suffixes[r.sensor_column] = f" ({r.offset_seconds:+.4f}s)"
                else:
                    suffixes[r.sensor_column] = " (ref)"

            self.main_plot.plot_depths_with_labels(
                self.sensor_data, suffixes,
                title=self.sensor_data.core_title or 'Time-Corrected',
            )

            # Update heave plot to show corrected alignment
            if (self.heave_plot is not None
                    and self._heave_profiles is not None
                    and self._heave_sel is not None):
                ref_col = panel.get_ref_col()
                low_freq, high_freq, filter_order = panel.get_filter_params()
                start_idx, end_idx = self._heave_sel

                # Recompute heave on the corrected data for the same range
                heaves_corrected, _ = TimeCorrectionProcessor.compute_heave_profiles(
                    self.sensor_data, start_idx, end_idx,
                    low_freq, high_freq, filter_order,
                )

                offsets_dict = {
                    r.sensor_column: r.offset_seconds
                    for r in self.time_offset_results
                    if not r.is_reference
                }

                self.heave_plot.plot_heave_corrected(
                    heaves_original=self._heave_profiles,
                    heaves_corrected=heaves_corrected,
                    ref_col=ref_col,
                    offsets=offsets_dict,
                    time_axis=self._heave_time_axis,
                )

            for r in self.time_offset_results:
                if not r.is_reference:
                    short = SensorData.get_short_name(r.sensor_column)
                    panel.log_widget.log(
                        f"Applied {r.offset_seconds:+.4f}s shift to {short}"
                    )
            panel.log_widget.log("Time corrections applied!")

        except Exception as e:
            self._show_error("Correction Error", str(e))
            self.time_panel.log_widget.log(f"ERROR: {e}")

    def apply_manual_time_corrections(self):
        """Apply manual constant time shifts."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        try:
            panel = self.time_panel
            manual = panel.get_manual_offsets()

            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("APPLYING MANUAL TIME CORRECTIONS")
            panel.log_widget.log(f"{'='*50}")

            applied = TimeCorrectionProcessor.apply_manual_offsets(
                self.sensor_data, manual
            )

            if not applied:
                panel.log_widget.log("No non-zero offsets to apply.")
                return

            self.main_plot.set_sensor_data(self.sensor_data)

            suffixes = {}
            for col, offset in applied.items():
                short = SensorData.get_short_name(col)
                suffixes[col] = f" ({offset:+.3f}s)"
                panel.log_widget.log(f"Applied {offset:+.4f}s shift to {short}")

            self.main_plot.plot_depths_with_labels(
                self.sensor_data, suffixes,
                title=self.sensor_data.core_title or 'Time-Corrected',
            )

            panel.log_widget.log("Manual time corrections applied!")

        except Exception as e:
            self._show_error("Correction Error", str(e))
            self.time_panel.log_widget.log(f"ERROR: {e}")

    # ==================================================================
    # Create Calibration Mode
    # ==================================================================

    def _on_cal_cruise_selected(self, cruise_id: int):
        """Populate cast (core) dropdown for the selected cruise."""
        if self.store is None:
            return
        try:
            cores = ProjectDataLoader.fetch_cores_for_cruise_all_types(
                self.store, cruise_id,
            )
            self.calibration_panel.set_cores(cores)
            if not cores:
                self.calibration_panel.log_widget.log(
                    "No cores with sensor files found for this cruise."
                )
        except Exception as e:
            self._show_error("Database Error", str(e))
            self.calibration_panel.log_widget.log(f"ERROR fetching cores: {e}")

    def _load_cast_from_database(self, core_id: int, core_info: dict):
        """Load a cast from the project for calibration creation."""
        if self._data_loader is None:
            self._show_error("No Project", "Open or create a project first.")
            return
        try:
            panel = self.calibration_panel
            core_name = core_info.get('core_name', str(core_id))
            panel.log_widget.log(f"\nLoading cast: {core_name}")

            self.main_plot.clear_selection()

            data = self._data_loader.load_core_sensor_data(core_id, core_info)
            self.sensor_data = data
            self.original_data = data.copy()

            self.main_plot.set_sensor_data(self.sensor_data)
            self.main_plot.plot_depths(self.sensor_data)

            panel.update_cast_info(
                core_name, data.num_sensors, data.row_count,
            )
            panel.log_widget.log(
                f"Loaded {data.row_count:,} rows, {data.num_sensors} sensors"
            )

        except Exception as e:
            self._show_error("Load Error", str(e))
            self.calibration_panel.log_widget.log(f"ERROR: {e}")

    def _add_statistics(self):
        """Add statistics from current selection to the collection."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        sel = self.main_plot.selection
        if sel is None:
            self._show_warning("Select a range first")
            return

        try:
            start_idx, end_idx = sel

            stats = compute_statistics(self.sensor_data, start_idx, end_idx)
            self.collected_statistics.append(stats)

            # Update stats table
            if self.statistics_table is not None:
                if self.statistics_table.count == 0:
                    self.statistics_table.set_columns(
                        self.sensor_data.depth_columns,
                    )
                self.statistics_table.add_statistics(stats)

            self.calibration_panel.update_stats_count(
                len(self.collected_statistics),
            )
            self.calibration_panel.log_widget.log(
                f"Added stats: depth={stats.mean_depth_all_sensors:.1f}m, "
                f"n={stats.n_points}"
            )

        except Exception as e:
            self._show_error("Statistics Error", str(e))
            self.calibration_panel.log_widget.log(f"ERROR: {e}")

    def _generate_calibration(self):
        """Generate a calibration from collected statistics."""
        if len(self.collected_statistics) < 2:
            self._show_warning("Need at least 2 statistics entries")
            return

        try:
            panel = self.calibration_panel

            # Auto-detect sensor count from loaded data
            if self.sensor_data is not None:
                n = len(self.sensor_data.depth_columns)
            else:
                n = len({
                    col
                    for s in self.collected_statistics
                    for col in s.column_means
                })

            # Build col_to_label mapping from column position
            # The calibration file uses A, B, C ... labels
            from ..domain.processing.calibration_builder import DEFAULT_CAL_LABELS
            labels = DEFAULT_CAL_LABELS[:n]
            col_to_label = None
            if self.sensor_data is not None:
                cols = self.sensor_data.depth_columns[:n]
                col_to_label = {col: label for col, label in zip(cols, labels)}

            self.generated_calibration = CalibrationBuilder.build(
                self.collected_statistics, n, labels,
                col_to_label=col_to_label,
            )

            # Build summary — sensor key first, then equations
            summary_lines = ["Calibration generated:"]

            if col_to_label is not None:
                summary_lines.append("  Sensor key:")
                for col, label in col_to_label.items():
                    summary_lines.append(
                        f"    {label} = {SensorData.get_full_label(col)}"
                    )

            for reg in self.generated_calibration.regressions:
                summary_lines.append(
                    f"  {reg.sensor_j}-{reg.sensor_i}: "
                    f"y={reg.slope:.6f}x + {reg.intercept:.6f} "
                    f"(R\u00b2={reg.r_squared:.4f})"
                )
            summary = "\n".join(summary_lines)

            panel.update_calibration_summary(summary)
            panel.log_widget.log(summary)

            # Show calibration regression plots in secondary panel
            if self.calibration_plot is not None:
                self.calibration_plot.plot_calibration(
                    self.generated_calibration, self.collected_statistics
                )
                if self.main_window is not None:
                    self.main_window.show_secondary_view('calibration_plot')

        except Exception as e:
            self._show_error("Generation Error", str(e))
            self.calibration_panel.log_widget.log(f"ERROR: {e}")

    def _save_calibration(self, file_path: str):
        """Save generated calibration to file."""
        if self.generated_calibration is None:
            self._show_warning("Generate a calibration first")
            return

        try:
            CalibrationIO.save(self.generated_calibration, file_path)
            self.calibration_panel.log_widget.log(
                f"Saved calibration to {Path(file_path).name}"
            )
        except Exception as e:
            self._show_error("Save Error", str(e))

    # ==================================================================
    # Trip Detector Mode
    # ==================================================================

    def detect_trip(self):
        """Detect sensor trip point using Savitzky-Golay divergence."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        try:
            panel = self.trip_panel
            sg_window, sg_poly = panel.get_sg_params()
            deriv_order = panel.get_derivative_order()
            threshold = panel.get_threshold()
            sampling_rate = panel.get_sampling_rate()
            edge_buffer = panel.get_edge_buffer()

            panel.log_widget.log(f"\n{'='*50}")
            panel.log_widget.log("TRIP DETECTION")
            panel.log_widget.log(f"SG window={sg_window}, poly={sg_poly}")
            panel.log_widget.log(f"Derivative order={deriv_order}")
            panel.log_widget.log(f"Threshold={threshold}, Rate={sampling_rate} Hz")
            panel.log_widget.log(f"Edge buffer={edge_buffer} samples")
            panel.log_widget.log(f"{'='*50}")

            # Build depth arrays keyed by column name (interpolated)
            depths = {}
            for col in self.sensor_data.depth_columns:
                if col in self.sensor_data.df.columns:
                    vals = (
                        self.sensor_data.df[col]
                        .interpolate().ffill().bfill().values
                    )
                    depths[col] = vals

            if len(depths) < 2:
                self._show_warning("Need at least 2 sensors for trip detection")
                return

            timestamps = self.sensor_data.get_timestamps()

            result = TripDetectionProcessor.detect_trip(
                depths, timestamps,
                sg_window=sg_window,
                sg_poly=sg_poly,
                derivative_order=deriv_order,
                std_threshold=threshold,
                sampling_rate=sampling_rate,
                edge_buffer=edge_buffer,
            )

            # Log results
            panel.log_widget.log(f"\n{result.summary}")
            panel.display_result(result.summary)

            self.trip_detection_result = result

            # Auto-fill trip time on piston panel
            if self.piston_panel is not None and result.trip_datetime is not None:
                self.piston_panel.set_trip_time(
                    str(result.trip_datetime), source='trip detector',
                )

            # Auto-fill trip time on calculate panel
            if self.calculate_panel is not None and result.trip_datetime is not None:
                self.calculate_panel.set_trip_time(
                    str(result.trip_datetime), source='trip detector',
                )

            # Show trip line on the main depth plot
            self.plot_depths()
            self.main_plot.add_trip_line(result.trip_index)

            # Show derivative plots on secondary view
            if self.trip_plot is not None:
                self.trip_plot.plot_trip_result(result)
                self.main_window.show_secondary_view('trip')

            panel.log_widget.log("Trip detection complete!")

        except Exception as e:
            self._show_error("Trip Detection Error", str(e))
            self.trip_panel.log_widget.log(f"ERROR: {e}")

    # ==================================================================
    # Piston Position Mode
    # ==================================================================

    def calculate_piston(self):
        """Calculate and plot the piston position estimate."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        panel = self.piston_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        scope_ft = panel.get_scope()
        core_ft = panel.get_core_length()
        offset_constant = panel.get_offset_constant()

        if ws_col is None or rel_col is None:
            self._show_warning("Select both Weight Stand and Release Device sensors")
            return
        if scope_ft <= 0 or core_ft <= 0:
            self._show_warning("Scope and Core Length must be > 0")
            return

        try:
            if ws_col not in self.sensor_data.df.columns:
                self._show_warning(
                    f"Weight Stand column not found: "
                    f"{SensorData.get_short_name(ws_col)}"
                )
                return
            if rel_col not in self.sensor_data.df.columns:
                self._show_warning(
                    f"Release Device column not found: "
                    f"{SensorData.get_short_name(rel_col)}"
                )
                return

            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            # Determine trip index for gating start_core detection
            trip_idx = self._resolve_trip_index()

            # Detect start_core (only searches AFTER trip_idx)
            start_idx = detect_start_core(
                ws_vals, rel_vals, scope_ft, trip_idx=trip_idx,
            )
            self._piston_start_core_idx = start_idx

            n_total = len(ws_vals)
            if start_idx >= n_total - 1:
                panel.log_widget.log(
                    "Warning: start_core not detected – the "
                    "|release − weight_stand| separation never "
                    "exceeded scope after the trip point.  "
                    "You can drag the red start-core line to "
                    "set it manually."
                )

            self._plot_piston(
                ws_vals, rel_vals, scope_ft, core_ft, start_idx,
                offset_constant,
            )

            # Update panel info
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= start_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[start_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            panel.update_start_core_info(start_idx, ts_str)

            ws_short = SensorData.get_short_name(ws_col)
            rel_short = SensorData.get_short_name(rel_col)
            panel.log_widget.log(
                f"Weight Stand: {ws_short}, Release: {rel_short}"
            )
            panel.log_widget.log(
                f"Scope: {scope_ft} ft, Core length: {core_ft} ft"
            )
            panel.log_widget.log(f"Offset constant: {offset_constant} m")
            panel.log_widget.log(f"Trip index (gate): {trip_idx}")
            panel.log_widget.log(f"Start core detected at index {start_idx}")
            if ts_str:
                panel.log_widget.log(f"  Time: {ts_str}")
            panel.log_widget.log("Piston position plotted!")

        except Exception as e:
            self._show_error("Piston Calculation Error", str(e))
            panel.log_widget.log(f"ERROR: {e}")

    def _plot_piston(self, ws_vals, rel_vals, scope_ft, core_ft, start_idx,
                     offset_constant: float = 1.25):
        """Compute piston position and overlay on the depth plot."""
        piston = compute_piston_position(
            ws_vals, rel_vals, scope_ft, core_ft, start_idx,
            offset_constant=offset_constant,
        )
        x = self.sensor_data.get_timestamps_epoch()

        # Plot base depth traces first
        self.plot_depths()

        # Re-add trip line if we have a result (plot_depths clears it)
        if (hasattr(self, 'trip_detection_result')
                and self.trip_detection_result is not None):
            self.main_plot.add_trip_line(
                self.trip_detection_result.trip_index,
            )

        # Store piston values for export
        self._piston_values = piston

        # Add piston trace
        self.main_plot.add_piston_trace(x, piston)

        # Add draggable start_core line
        if 0 <= start_idx < len(x):
            self.main_plot.add_start_core_line(float(x[start_idx]))

    def _resolve_trip_index(self) -> int:
        """Determine the trip gate index for start_core detection.

        Priority:
        1. Trip time entered / selected on the piston panel (epoch).
        2. Trip detection result stored from the trip-detector mode.
        3. Fallback: 0 (search from beginning).
        """
        if self.sensor_data is None:
            return 0

        panel = self.piston_panel
        trip_epoch = panel.get_trip_time_epoch()

        # Check if the panel has a meaningful trip time set
        # (QDateTimeEdit defaults to 2000-01-01 -> epoch ~946684800)
        if trip_epoch > 946684800:
            x = self.sensor_data.get_timestamps_epoch()
            if len(x) > 0:
                idx = int(np.searchsorted(x, trip_epoch))
                return min(idx, len(x) - 1)

        # No panel trip time -- try stored detection result
        if (hasattr(self, 'trip_detection_result')
                and self.trip_detection_result is not None):
            return self.trip_detection_result.trip_index

        return 0

    def _on_start_core_moved(self, new_idx: int):
        """Handle the user dragging the start_core line to a new position."""
        if self.sensor_data is None:
            return
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )

        # Handle Calculate mode: just update the stored index and panel label
        if mode in ('Calculate', 'Piston Analysis'):
            self._calc_start_core_idx = new_idx
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= new_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[new_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            if mode == 'Calculate':
                self.calculate_panel.update_start_core_info(new_idx, ts_str)
                self.calculate_panel.log_widget.log(
                    f"Start core moved to index {new_idx}"
                )
            else:
                if self.piston_analysis_panel is not None:
                    self.piston_analysis_panel.log_widget.log(
                        f"Start core moved to index {new_idx}"
                    )
            return

        if mode != 'Piston Position':
            return

        panel = self.piston_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        scope_ft = panel.get_scope()
        core_ft = panel.get_core_length()
        offset_constant = panel.get_offset_constant()

        if ws_col is None or rel_col is None:
            return

        try:
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            self._piston_start_core_idx = new_idx

            # Recompute piston with new start_core and update trace in-place
            piston = compute_piston_position(
                ws_vals, rel_vals, scope_ft, core_ft, new_idx,
                offset_constant=offset_constant,
            )
            self._piston_values = piston
            self.main_plot.update_piston_trace(piston)

            # Update panel info
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= new_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[new_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            panel.update_start_core_info(new_idx, ts_str)
            panel.log_widget.log(f"Start core moved to index {new_idx}")

        except Exception as e:
            panel.log_widget.log(f"ERROR updating piston: {e}")

    def _on_trip_line_moved(self, new_idx: int):
        """Handle the user dragging the trip line to a new position."""
        if self.sensor_data is None:
            return

        dt_col = self.sensor_data.datetime_col
        new_ts = None
        if (dt_col in self.sensor_data.df.columns
                and 0 <= new_idx < len(self.sensor_data.df)):
            ts = self.sensor_data.df[dt_col].iloc[new_idx]
            if pd.notna(ts):
                new_ts = pd.Timestamp(ts)

        # Update stored trip index in detection result (if available). The
        # datetime has to move with it: both are persisted, and a stale
        # datetime would disagree with the index in the saved row.
        if self.trip_detection_result is not None:
            self.trip_detection_result.trip_index = new_idx
            if new_ts is not None:
                self.trip_detection_result.trip_datetime = new_ts

        if new_ts is not None:
            if self.piston_panel is not None:
                self.piston_panel.set_trip_time(str(new_ts), source='plot drag')
            if self.calculate_panel is not None:
                self.calculate_panel.set_trip_time(
                    str(new_ts), source='plot drag',
                )

        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )

        if mode == 'Winch':
            self._update_winch_sensor_trip_status()

        # Handle Calculate mode – just log the move
        if mode == 'Calculate':
            self.calculate_panel.log_widget.log(
                f"Trip line moved to index {new_idx}"
            )
            return

        if mode == 'Predict':
            self._update_predict_trigger_line_display()
            if self._last_predict_result is not None:
                self._refresh_predict_plot()
            if self.predict_panel is not None:
                self._log_predict(f"Trip line moved to index {new_idx}")
            return

        # If piston has already been calculated, recalculate with new trip gate
        if mode != 'Piston Position' or self._piston_start_core_idx is None:
            return

        panel = self.piston_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        scope_ft = panel.get_scope()
        core_ft = panel.get_core_length()
        offset_constant = panel.get_offset_constant()

        if ws_col is None or rel_col is None or scope_ft <= 0 or core_ft <= 0:
            return

        try:
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            start_idx = self._piston_start_core_idx

            # If start_core would now be before the new trip gate, re-detect it
            if start_idx < new_idx:
                start_idx = detect_start_core(
                    ws_vals, rel_vals, scope_ft, trip_idx=new_idx,
                )
                self._piston_start_core_idx = start_idx

                # Move the start_core line to the new position
                x_all = self.sensor_data.get_timestamps_epoch()
                if 0 <= start_idx < len(x_all):
                    self.main_plot.remove_start_core_line()
                    self.main_plot.add_start_core_line(float(x_all[start_idx]))

                # Update start_core info in panel
                dt_col = self.sensor_data.datetime_col
                ts_str = ''
                if (dt_col in self.sensor_data.df.columns
                        and 0 <= start_idx < len(self.sensor_data.df)):
                    ts = self.sensor_data.df[dt_col].iloc[start_idx]
                    if pd.notna(ts):
                        ts_str = str(ts)
                panel.update_start_core_info(start_idx, ts_str)

            piston = compute_piston_position(
                ws_vals, rel_vals, scope_ft, core_ft, start_idx,
                offset_constant=offset_constant,
            )
            self._piston_values = piston
            self.main_plot.update_piston_trace(piston)
            panel.log_widget.log(
                f"Trip line moved to index {new_idx}, piston recalculated"
            )

        except Exception as e:
            panel.log_widget.log(f"ERROR updating piston after trip move: {e}")

    def _on_end_pen_moved(self, new_idx: int):
        """Handle the user dragging the end-of-penetration line."""
        if self.sensor_data is None:
            return

        self._end_pen_idx = new_idx

        # Update the panel label
        dt_col = self.sensor_data.datetime_col
        ts_str = ''
        if (dt_col in self.sensor_data.df.columns
                and 0 <= new_idx < len(self.sensor_data.df)):
            ts = self.sensor_data.df[dt_col].iloc[new_idx]
            if pd.notna(ts):
                ts_str = str(ts)
        self.calculate_panel.update_end_pen_info(new_idx, ts_str)
        self.calculate_panel.log_widget.log(
            f"End-of-penetration line moved to index {new_idx}"
        )

    def _on_pullout_moved(self, new_idx: int):
        """Handle the user dragging the pullout line."""
        if self.sensor_data is None:
            return

        self._pullout_idx = new_idx

        dt_col = self.sensor_data.datetime_col
        ts_str = ''
        if (dt_col in self.sensor_data.df.columns
                and 0 <= new_idx < len(self.sensor_data.df)):
            ts = self.sensor_data.df[dt_col].iloc[new_idx]
            if pd.notna(ts):
                ts_str = str(ts)
        self.calculate_panel.update_pullout_info(new_idx, ts_str)
        self.calculate_panel.log_widget.log(
            f"Pullout line moved to index {new_idx}"
        )

    def _on_start_pen_moved(self, new_idx: int):
        """Handle the user dragging the start-penetration line."""
        if self.sensor_data is None:
            return
        self._start_pen_idx = new_idx
        self._manual_start_pen = new_idx
        if self.calculate_panel is not None:
            self.calculate_panel.log_widget.log(
                f"Start pen moved to index {new_idx} (manual override; "
                "reload the core to go back to the computed position)"
            )

    def _on_seafloor_dragged(self, depth: float):
        """Handle the user dragging the seafloor line on the main plot."""
        if self.calculate_panel is None:
            return
        # Only update when manual override is active
        if self.calculate_panel.seafloor_check.isChecked():
            self.calculate_panel.seafloor_spin.blockSignals(True)
            self.calculate_panel.seafloor_spin.setValue(depth)
            self.calculate_panel.seafloor_spin.blockSignals(False)
            self._manual_seafloor = depth
            # Recompute start_pen line to reflect new seafloor position
            trip_idx = self._resolve_calc_trip_index()
            self._update_start_pen_line(trip_idx)

    def _on_seafloor_override_changed(self, value):
        """Handle checkbox toggle or spinbox change from calculate panel."""
        self._manual_seafloor = float(value) if value is not None else None
        trip_idx = self._resolve_calc_trip_index()
        if self._manual_seafloor is not None:
            # Draw movable seafloor line
            self.main_plot.add_seafloor_line(self._manual_seafloor, movable=True)
        else:
            # Revert to trigger-formula seafloor (non-draggable) or remove
            self._update_start_pen_line(trip_idx)
            return
        self._update_start_pen_line(trip_idx)

    def _estimate_seafloor_from_trip(self):
        """Fill the seafloor spinbox with WS[trip] + core_length + L_WS + scope."""
        if self.sensor_data is None or self.calculate_panel is None:
            return
        trip_idx = self._resolve_calc_trip_index()
        if trip_idx is None:
            self._show_warning("Trip time not set — cannot estimate seafloor.")
            return
        panel = self.calculate_panel
        ws_col = panel.get_weight_stand_col()
        if not ws_col or ws_col not in self.sensor_data.df.columns:
            self._show_warning("Weight-stand column not set.")
            return
        ws_vals = (
            self.sensor_data.df[ws_col]
            .interpolate().ffill().bfill().values
        )
        md = self.sensor_data.metadata
        FT_TO_M_local = 1.0 / 3.28
        core_length_ft = md.get('core_length') or 0.0
        scope_ft = md.get('scope') or 0.0
        ws_len_m = panel.get_weight_stand_length_m()
        estimate = (
            float(ws_vals[trip_idx])
            + core_length_ft * FT_TO_M_local
            + ws_len_m
            + scope_ft * FT_TO_M_local
        )
        panel.set_seafloor_override(estimate)
        panel.log_widget.log(
            f"Seafloor estimate (WS[trip]+core+L_WS+scope): {estimate:.2f} m  "
            f"[upper bound — actual seafloor is shallower by freefall distance]"
        )

    def _reset_lines(self):
        """Reset end-of-penetration and pullout lines to auto-calculated positions."""
        self._end_pen_idx = None
        self._pullout_idx = None
        self.calculate_panel.end_pen_label.setText("Not set")
        self.calculate_panel.pullout_label.setText("Not set")
        self._plot_calculate_mode()
        self.calculate_panel.log_widget.log(
            "End-of-penetration and pullout lines reset to auto"
        )

    # ==================================================================
    # Calculate Mode
    # ==================================================================

    def run_calculations(self):
        """Run coring analysis calculations and display results in the log."""
        if self.sensor_data is None:
            self._show_warning("No data loaded")
            return

        panel = self.calculate_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()
        trig_col = panel.get_trigger_col()  # May be None

        if ws_col is None or rel_col is None:
            self._show_warning(
                "Select both Weight Stand and Release Device sensors"
            )
            return

        try:
            # Retrieve depth arrays (interpolated)
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )

            trig_vals = None
            if (trig_col is not None
                    and trig_col in self.sensor_data.df.columns):
                trig_vals = (
                    self.sensor_data.df[trig_col]
                    .interpolate().ffill().bfill().values
                )

            # Optional Savitzky-Golay smoothing
            if panel.get_smoothing_enabled():
                sg_win, sg_poly = panel.get_sg_params()
                panel.log_widget.log(
                    f"Applying Savitzky-Golay smoothing "
                    f"(window={sg_win}, poly={sg_poly})"
                )
                ws_vals = apply_savgol(ws_vals, sg_win, sg_poly)
                rel_vals = apply_savgol(rel_vals, sg_win, sg_poly)
                if trig_vals is not None:
                    trig_vals = apply_savgol(trig_vals, sg_win, sg_poly)

            timestamps_epoch = self.sensor_data.get_timestamps_epoch()

            # Resolve trip index from the calculate panel
            trip_idx = self._resolve_calc_trip_index()

            # Resolve start_core index
            start_core_idx = self._calc_start_core_idx

            # Piston values (from a previous Piston Position calculation)
            piston = self._piston_values

            # If smoothing is enabled and piston exists, we should
            # also smooth piston for consistency
            if piston is not None and panel.get_smoothing_enabled():
                sg_win, sg_poly = panel.get_sg_params()
                piston = apply_savgol(piston, sg_win, sg_poly)

            # Metadata from CSV header
            md = self.sensor_data.metadata
            trigger_core_length_ft = md.get('trigger_core_length')
            core_length_ft = md.get('core_length')
            trigger_pen = panel.get_trigger_pen()
            weight_stand_length_m = panel.get_weight_stand_length_m()

            panel.log_widget.log("")

            # Log what data is available
            ws_short = SensorData.get_short_name(ws_col)
            rel_short = SensorData.get_short_name(rel_col)
            panel.log_widget.log(f"Weight Stand: {ws_short}")
            panel.log_widget.log(f"Release Device: {rel_short}")
            if trig_vals is not None:
                panel.log_widget.log(
                    f"Trigger Core/Weight: "
                    f"{SensorData.get_short_name(trig_col)}"
                )
            else:
                panel.log_widget.log(
                    "Trigger Core/Weight: not available"
                )

            if trip_idx is not None:
                panel.log_widget.log(f"Trip index: {trip_idx}")
            else:
                panel.log_widget.log("Trip time: not set")

            if start_core_idx is not None:
                panel.log_widget.log(
                    f"Start core index: {start_core_idx}"
                )
            else:
                panel.log_widget.log("Start core: not available")

            if piston is not None:
                panel.log_widget.log("Piston position: available")
            else:
                panel.log_widget.log("Piston position: not computed")

            if trigger_core_length_ft is not None:
                panel.log_widget.log(
                    f"Trigger core length: {trigger_core_length_ft} ft"
                )
            if core_length_ft is not None:
                panel.log_widget.log(
                    f"Core length: {core_length_ft} ft"
                )
            if trigger_pen > 0:
                panel.log_widget.log(
                    f"Trigger penetration: {trigger_pen} m"
                )

            end_pen_idx = self._end_pen_idx
            if end_pen_idx is not None:
                panel.log_widget.log(
                    f"End of initial penetration index: {end_pen_idx}"
                )
            else:
                panel.log_widget.log(
                    "End of initial penetration: not set (using trip+5s)"
                )

            pullout_idx = self._pullout_idx
            if pullout_idx is not None:
                panel.log_widget.log(
                    f"Pullout index: {pullout_idx}"
                )
            else:
                panel.log_widget.log(
                    "Pullout: not set (using ws_max)"
                )

            # Run calculations
            results = compute_calculations(
                weight_stand=ws_vals,
                release=rel_vals,
                timestamps_epoch=timestamps_epoch,
                trip_idx=trip_idx,
                start_core_idx=start_core_idx,
                piston=piston,
                trigger_core=trig_vals,
                trigger_core_length_ft=trigger_core_length_ft,
                trigger_pen=trigger_pen,
                core_length_ft=core_length_ft,
                end_pen_idx=end_pen_idx,
                pullout_idx=pullout_idx,
                seafloor_override=self._manual_seafloor,
                weight_stand_length_m=weight_stand_length_m,
            )

            # Store results & inputs for export
            self._last_calc_results = results
            self._last_calc_inputs = {
                'weight_stand_col': ws_col,
                'release_col': rel_col,
                'trigger_col': trig_col,
                'smoothing_enabled': panel.get_smoothing_enabled(),
                'sg_window': panel.get_sg_params()[0] if panel.get_smoothing_enabled() else None,
                'sg_poly': panel.get_sg_params()[1] if panel.get_smoothing_enabled() else None,
                'trip_idx': trip_idx,
                'start_core_idx': start_core_idx,
                'piston_available': piston is not None,
                'trigger_core_length_ft': trigger_core_length_ft,
                'core_length_ft': core_length_ft,
                'trigger_pen': trigger_pen,
                'weight_stand_length_m': weight_stand_length_m,
            }

            panel.log_widget.log(format_results(results))

            planned_trig = md.get("trigger_line_length")
            if results.eff_trig_line_ft is not None:
                eff = results.eff_trig_line_ft
                panel.log_widget.log(
                    f"Trigger line — measured: {eff:.2f} ft"
                )
                if planned_trig is not None:
                    panel.log_widget.log(
                        f"Trigger line — planned (core): {float(planned_trig):.2f} ft, "
                        f"Δ(meas−plan): {eff - float(planned_trig):+.2f} ft"
                    )
                if self.predict_panel is not None:
                    pred_ft = self.predict_panel.get_inputs().trigger_line_length_ft
                    panel.log_widget.log(
                        f"Trigger line — predict model input: {pred_ft:.2f} ft, "
                        f"Δ(meas−model): {eff - pred_ft:+.2f} ft"
                    )

            # Show smoothed traces on the plot if smoothing is enabled
            if panel.get_smoothing_enabled():
                smoothed_data = {}
                smoothed_data[ws_col] = ws_vals
                smoothed_data[rel_col] = rel_vals
                if trig_vals is not None and trig_col is not None:
                    smoothed_data[trig_col] = trig_vals
                self.main_plot.add_smoothed_traces(
                    smoothed_data,
                    self.sensor_data.depth_columns,
                )
            else:
                self.main_plot.remove_smoothed_traces()

            # Update piston trace on the plot with the (possibly smoothed) values
            if piston is not None:
                self.main_plot.update_piston_trace(piston)

            # Update the geometry diagram in the secondary view
            self._update_calculation_plot(
                results, ws_vals, piston, trip_idx,
                start_core_idx, core_length_ft,
                end_pen_idx, pullout_idx,
            )

            # Refresh start_pen line on upper plot with current seafloor
            self._update_start_pen_line(trip_idx)

        except Exception as e:
            self._show_error("Calculation Error", str(e))
            panel.log_widget.log(f"ERROR: {e}")

    def _update_calculation_plot(
        self,
        results,
        ws_vals: np.ndarray,
        piston: Optional[np.ndarray],
        trip_idx: Optional[int],
        start_core_idx: Optional[int],
        core_length_ft: Optional[float],
        end_pen_idx: Optional[int] = None,
        pullout_idx: Optional[int] = None,
    ):
        """Build a GeometryInput and update the secondary diagram."""
        if self.calculation_plot is None:
            return
        if trip_idx is None or results.seafloor is None:
            self.calculation_plot.clear()
            return
        if core_length_ft is None or core_length_ft <= 0:
            self.calculation_plot.clear()
            return

        FT_TO_M = 1.0 / 3.28
        core_length_m = core_length_ft * FT_TO_M
        n = len(ws_vals)
        freefall_est = results.freefall_est if results.freefall_est is not None else 0.0

        # -- Start Core values --
        ws_at_sc = None
        piston_at_sc = None
        piston_alt_sc = None
        if start_core_idx is not None and 0 <= start_core_idx < n:
            ws_at_sc = float(ws_vals[start_core_idx])
            if piston is not None and start_core_idx < len(piston):
                piston_at_sc = float(piston[start_core_idx])
                piston_alt_sc = results.piston_alt  # seafloor - piston[start_core]

        # -- Start Penetration values --
        # start_pen = first index >= trip where core_tip >= seafloor
        # (independent of start_core — barrel may reach seafloor before scope opens)
        ws_at_sp = None
        piston_at_sp = None
        piston_alt_sp = None
        pen_before_core = False
        ws_len_m = (
            self.calculate_panel.get_weight_stand_length_m()
            if self.calculate_panel is not None
            else DEFAULT_WEIGHT_STAND_LENGTH_M
        )
        core_tip_series = ws_vals + ws_len_m + core_length_m
        after_search = core_tip_series[trip_idx:]
        pen_candidates = np.where(after_search >= results.seafloor)[0]
        if len(pen_candidates) > 0:
            sp_idx = trip_idx + int(pen_candidates[0])
            if 0 <= sp_idx < n:
                ws_at_sp = float(ws_vals[sp_idx])
                if piston is not None and sp_idx < len(piston):
                    piston_at_sp = float(piston[sp_idx])
                    piston_alt_sp = results.seafloor - piston_at_sp
                if (start_core_idx is not None
                        and sp_idx < start_core_idx):
                    pen_before_core = True

        # -- End-of-penetration values --
        ws_at_ep = None
        if end_pen_idx is not None and 0 <= end_pen_idx < n:
            ws_at_ep = float(ws_vals[end_pen_idx])

        # -- Pullout values --
        ws_at_po = None
        piston_at_po = None
        if pullout_idx is not None and 0 <= pullout_idx < n:
            ws_at_po = float(ws_vals[pullout_idx])
            if piston is not None and pullout_idx < len(piston):
                piston_at_po = float(piston[pullout_idx])

        geo = GeometryInput(
            ws_at_trip=float(ws_vals[trip_idx]),
            seafloor=results.seafloor,
            core_length_m=core_length_m,
            freefall_est=freefall_est,
            weight_stand_length_m=ws_len_m,
            ws_at_start_core=ws_at_sc,
            piston_at_start_core=piston_at_sc,
            piston_alt_at_start_core=piston_alt_sc,
            ws_at_start_pen=ws_at_sp,
            piston_at_start_pen=piston_at_sp,
            piston_alt_at_start_pen=piston_alt_sp,
            start_pen_before_start_core=pen_before_core,
            ws_at_end_pen=ws_at_ep,
            ws_at_pullout=ws_at_po,
            piston_at_pullout=piston_at_po,
        )
        self.calculation_plot.plot_geometry(geo)

    def _resolve_calc_trip_index(self) -> Optional[int]:
        """Determine the trip index for the calculate panel.

        Priority:
        1. Trip time entered / selected on the calculate panel (epoch).
        2. Trip detection result stored from the trip-detector mode.
        3. None (calculations that need trip_idx will be skipped).
        """
        if self.sensor_data is None:
            return None

        panel = self.calculate_panel
        trip_epoch = panel.get_trip_time_epoch()

        if trip_epoch > 946684800:
            x = self.sensor_data.get_timestamps_epoch()
            if len(x) > 0:
                idx = int(np.searchsorted(x, trip_epoch))
                return min(idx, len(x) - 1)

        if (hasattr(self, 'trip_detection_result')
                and self.trip_detection_result is not None):
            return self.trip_detection_result.trip_index

        return None

    def _sync_trip_to_calculate_panel(self):
        """Push the best-known trip time into the calculate panel.

        Sources (in priority order):
        1. Trip detection result (most accurate).
        2. Piston panel trip time (user may have edited it).
        3. CSV header metadata (already set during file load).
        """
        if self.trip_detection_result is not None:
            dt = self.trip_detection_result.trip_datetime
            if dt is not None:
                self.calculate_panel.set_trip_time(
                    str(dt), source='trip detector'
                )
                return
        # Fall back to piston panel value
        if self.piston_panel is not None:
            epoch = self.piston_panel.get_trip_time_epoch()
            if epoch > 946684800:
                qdt = self.piston_panel.trip_time_edit.dateTime()
                dt_str = qdt.toString('yyyy-MM-dd HH:mm:ss.zzz')
                self.calculate_panel.set_trip_time(
                    dt_str, source='piston panel'
                )

    def _plot_calculate_mode(self):
        """Plot depth traces with trip and start_core lines for calculate mode."""
        if self.sensor_data is None:
            return

        self.plot_depths()

        # Re-add trip line if available
        trip_idx = self._resolve_calc_trip_index()
        if trip_idx is not None:
            self.main_plot.add_trip_line(trip_idx)

        # Re-add start_core line if available
        if self._calc_start_core_idx is not None:
            x = self.sensor_data.get_timestamps_epoch()
            idx = self._calc_start_core_idx
            if 0 <= idx < len(x):
                self.main_plot.add_start_core_line(float(x[idx]))

        # Add start_pen line (non-draggable, auto-computed)
        self._update_start_pen_line(trip_idx)

        # Add end-of-penetration line
        x = self.sensor_data.get_timestamps_epoch()
        if self._end_pen_idx is not None and 0 <= self._end_pen_idx < len(x):
            self.main_plot.add_end_pen_line(float(x[self._end_pen_idx]))
        elif trip_idx is not None:
            # Auto-initialize to trip + 5s
            target = x[trip_idx] + 5.0
            ep_idx = int(np.argmin(np.abs(x - target)))
            self._end_pen_idx = ep_idx
            self.main_plot.add_end_pen_line(float(x[ep_idx]))
            # Update panel label
            dt_col = self.sensor_data.datetime_col
            ts_str = ''
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= ep_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[ep_idx]
                if pd.notna(ts):
                    ts_str = str(ts)
            self.calculate_panel.update_end_pen_info(ep_idx, ts_str)

        # Add pullout line
        if self._pullout_idx is not None and 0 <= self._pullout_idx < len(x):
            self.main_plot.add_pullout_line(float(x[self._pullout_idx]))
        elif self._end_pen_idx is not None:
            # Auto-initialize to ws_max after end_pen
            ep = self._end_pen_idx
            panel = self.calculate_panel
            ws_col = panel.get_weight_stand_col()
            if ws_col is not None and ws_col in self.sensor_data.df.columns:
                ws_vals = (
                    self.sensor_data.df[ws_col]
                    .interpolate().ffill().bfill().values
                )
                # Look for max WS in a 10-min window after end_pen
                window_10min = int(np.argmin(np.abs(x - (x[ep] + 600.0))))
                window_10min = min(window_10min, len(ws_vals) - 1)
                search_slice = ws_vals[ep:window_10min + 1]
                if len(search_slice) > 0:
                    po_idx = ep + int(np.nanargmax(search_slice))
                else:
                    po_idx = ep
                self._pullout_idx = po_idx
                self.main_plot.add_pullout_line(float(x[po_idx]))
                dt_col = self.sensor_data.datetime_col
                ts_str = ''
                if (dt_col in self.sensor_data.df.columns
                        and 0 <= po_idx < len(self.sensor_data.df)):
                    ts = self.sensor_data.df[dt_col].iloc[po_idx]
                    if pd.notna(ts):
                        ts_str = str(ts)
                self.calculate_panel.update_pullout_info(po_idx, ts_str)

        # Also show piston trace if available
        if self._piston_values is not None:
            x = self.sensor_data.get_timestamps_epoch()
            self.main_plot.add_piston_trace(x, self._piston_values)

    def _plot_winch_mode(self):
        """Plot sensor depths with any already-computed overlays (no auto-init)."""
        if self.sensor_data is None:
            return

        self.plot_depths()

        trip_idx = self._resolve_calc_trip_index()
        if trip_idx is not None:
            self.main_plot.add_trip_line(trip_idx)

        start_core_idx = self._calc_start_core_idx
        if start_core_idx is None:
            start_core_idx = self._piston_start_core_idx
        if start_core_idx is not None:
            x = self.sensor_data.get_timestamps_epoch()
            if 0 <= start_core_idx < len(x):
                self.main_plot.add_start_core_line(float(x[start_core_idx]))

        x = self.sensor_data.get_timestamps_epoch()
        if self._start_pen_idx is not None and 0 <= self._start_pen_idx < len(x):
            self.main_plot.add_start_pen_line(float(x[self._start_pen_idx]))
        if self._end_pen_idx is not None and 0 <= self._end_pen_idx < len(x):
            self.main_plot.add_end_pen_line(float(x[self._end_pen_idx]))
        if self._pullout_idx is not None and 0 <= self._pullout_idx < len(x):
            self.main_plot.add_pullout_line(float(x[self._pullout_idx]))

        if self._manual_seafloor is not None:
            self.main_plot.add_seafloor_line(self._manual_seafloor, movable=True)

        if self._piston_values is not None:
            self.main_plot.add_piston_trace(x, self._piston_values)

    def reload_winch_data(self):
        """Load winch data (auto or manual) and refresh the winch plot."""
        if self.winch_panel is None:
            return

        log = self.winch_panel.log_widget
        cruise_id = self._loaded_cruise_id
        if cruise_id is None and self.main_window is not None:
            cruise_id = self.main_window.get_selected_cruise_id()

        if cruise_id is None:
            self.winch_panel.set_auto_status([], False)
            self.winch_panel.set_cruise_winch_files([])
            self._winch_list_cruise_id = None
            self._winch_df = None
            self._winch_df_original = None
            self._winch_file_names = []
            self._winch_file_ids = []
            self._clear_winch_trip_state()
            self.winch_panel.set_parameters([])
            self._update_winch_plot()
            log.log('Select a cruise to load winch files.')
            return

        if self._winch_list_cruise_id != cruise_id:
            try:
                cruise_files = self._winch_loader.fetch_winch_files_for_cruise(cruise_id)
                self.winch_panel.set_cruise_winch_files(cruise_files)
                self._winch_list_cruise_id = cruise_id
            except Exception as exc:
                log.log(f'ERROR fetching winch file list: {exc}')
                self.winch_panel.set_cruise_winch_files([])
                self._winch_list_cruise_id = None

        core_name = ''
        if self.sensor_data is not None:
            core_name = self.sensor_data.core_title or ''

        auto_df = None
        auto_names: list[str] = []
        auto_ids: list[int] = []
        if self._loaded_core_id is not None:
            try:
                auto_df, auto_names, auto_ids = self._winch_loader.load_core_winch_data(
                    self._loaded_core_id, cruise_id,
                )
            except Exception as exc:
                log.log(f'ERROR in auto winch load: {exc}')

        self.winch_panel.set_auto_status(
            auto_names, auto_df is not None, core_name=core_name,
        )

        if self.winch_panel.uses_manual_selection():
            file_ids = self.winch_panel.get_selected_winch_file_ids()
            if not file_ids:
                self._winch_df = None
                self._winch_file_names = []
                self._winch_file_ids = []
                log.log('Manual mode: select one or more winch files.')
            else:
                try:
                    self._winch_df, self._winch_file_names = (
                        self._winch_loader.load_winch_files_concat(file_ids)
                    )
                    self._winch_file_ids = list(file_ids)
                    self._winch_load_mode = 'manual'
                    if self._winch_df is not None:
                        log.log(
                            f'Manual load: {len(self._winch_file_names)} file(s), '
                            f'{len(self._winch_df):,} samples.'
                        )
                    else:
                        log.log('Manual load: could not parse selected files.')
                except Exception as exc:
                    self._winch_df = None
                    self._winch_file_names = []
                    self._winch_file_ids = []
                    log.log(f'ERROR loading manual winch files: {exc}')
        else:
            self._winch_df = auto_df
            self._winch_file_names = auto_names
            self._winch_file_ids = auto_ids
            self._winch_load_mode = 'auto'
            if auto_df is not None:
                log.log(
                    f'Auto load: {len(auto_names)} file(s), '
                    f'{len(auto_df):,} samples.'
                )
            elif self._loaded_core_id is not None:
                log.log('Auto load: no overlapping winch data for this core.')

        params = get_winch_parameters(self._winch_df)
        self.winch_panel.set_parameters(params)
        self._snapshot_winch_original()
        self._update_winch_plot()
        self._update_winch_sensor_trip_status()
        self._sync_winch_search_region_visibility()

    def _sync_winch_search_region_visibility(self) -> None:
        """Show or hide the plot search region to match the panel checkbox."""
        if self.winch_panel is None or self.winch_plot_view is None:
            return
        if self.winch_panel.show_search_region_check.isChecked():
            self.winch_plot_view.set_search_region_enabled(True)

    def _refresh_winch_ui(self) -> None:
        """Refresh winch plots without reloading data from the database."""
        if self.winch_plot_view is not None and self.main_plot is not None:
            self.winch_plot_view.set_x_link(self.main_plot.plot_item)
        self._update_winch_plot()
        self._update_winch_sensor_trip_status()
        self._sync_winch_search_region_visibility()

    def _snapshot_winch_original(self) -> None:
        """Store a copy of loaded winch data and clear trip/alignment state."""
        if self._winch_df is not None:
            self._winch_df_original = self._winch_df.copy()
        else:
            self._winch_df_original = None
        self._clear_winch_trip_state()

    def _clear_winch_trip_state(self) -> None:
        """Clear winch trip detection and alignment metadata."""
        self._winch_trip_idx = None
        self._winch_trip_result = None
        self._winch_time_offset_sec = 0.0
        self._winch_aligned = False
        if self.winch_plot_view is not None:
            self.winch_plot_view.remove_winch_trip_line()
        if self.winch_panel is not None:
            self.winch_panel.set_winch_trip_status('Winch trip: not detected')
            self.winch_panel.set_alignment_status('Alignment: none')

    def detect_winch_trip(self) -> None:
        """Detect winch trip from a rapid drop in window 1 column."""
        if self.winch_panel is None or self.winch_plot_view is None:
            return

        log = self.winch_panel.log_widget
        if self._winch_df is None or self._winch_df.empty:
            log.log('No winch data loaded.')
            return

        column = self.winch_panel.get_column_1()
        if not column or column not in self._winch_df.columns:
            log.log('Select a column in window 1 for trip detection.')
            return

        values = (
            pd.to_numeric(self._winch_df[column], errors='coerce')
            .to_numpy(dtype=float)
        )
        timestamps = self._winch_df['datetime']
        search_start, search_end = (
            self.winch_plot_view.get_search_window_timestamps()
        )

        result = WinchTripDetectionProcessor.detect_trip(
            values,
            timestamps,
            column,
            edge_buffer=self.winch_panel.get_edge_buffer(),
            drop_threshold=self.winch_panel.get_drop_threshold(),
            search_start=search_start,
            search_end=search_end,
        )

        if result is None:
            log.log(
                'No winch trip found in search window '
                f'(threshold={self.winch_panel.get_drop_threshold():.1f}).'
            )
            self._winch_trip_idx = None
            self._winch_trip_result = None
            self.winch_plot_view.remove_winch_trip_line()
            self.winch_panel.set_winch_trip_status('Winch trip: not detected')
            return

        self._winch_trip_result = result
        self._winch_trip_idx = result.trip_index
        self.winch_plot_view.add_winch_trip_line(result.trip_index)
        self.winch_panel.set_winch_trip_status(
            f'Winch trip: index {result.trip_index}, '
            f'{result.trip_datetime}  (drop {result.drop_magnitude:.1f})'
        )
        log.log(
            f'Winch trip detected at index {result.trip_index} '
            f'({result.trip_datetime}), drop={result.drop_magnitude:.1f}'
        )

    def align_winch_data(self) -> None:
        """Shift winch datetimes so winch_trip matches sensor_trip."""
        if self.winch_panel is None:
            return

        log = self.winch_panel.log_widget
        if self._winch_df is None or self._winch_trip_idx is None:
            log.log('Detect winch trip before aligning.')
            return
        if self.sensor_data is None:
            log.log('No sensor data loaded.')
            return

        sensor_idx = self._resolve_calc_trip_index()
        if sensor_idx is None:
            log.log(
                'Sensor trip not set. Run Trip Detector or set trip on main plot.'
            )
            return

        sensor_epochs = self.sensor_data.get_timestamps_epoch()
        if not (0 <= sensor_idx < len(sensor_epochs)):
            log.log('Sensor trip index is out of range.')
            return

        winch_epochs = datetime_to_epoch(self._winch_df).to_numpy()
        if not (0 <= self._winch_trip_idx < len(winch_epochs)):
            log.log('Winch trip index is out of range.')
            return

        sensor_epoch = float(sensor_epochs[sensor_idx])

        if self._winch_df_original is not None:
            orig_epochs = datetime_to_epoch(self._winch_df_original).to_numpy()
            winch_epoch_orig = float(orig_epochs[self._winch_trip_idx])
        else:
            winch_epoch_orig = float(winch_epochs[self._winch_trip_idx])

        offset_sec = sensor_epoch - winch_epoch_orig

        base_df = (
            self._winch_df_original.copy()
            if self._winch_df_original is not None
            else self._winch_df.copy()
        )
        self._winch_df = base_df
        self._winch_df['datetime'] = (
            self._winch_df['datetime'] + pd.Timedelta(seconds=offset_sec)
        )
        self._winch_time_offset_sec = offset_sec
        self._winch_aligned = True

        self._update_winch_plot()
        if self._winch_trip_idx is not None:
            self.winch_plot_view.add_winch_trip_line(self._winch_trip_idx)

        sensor_dt = self.sensor_data.df[self.sensor_data.datetime_col].iloc[sensor_idx]
        winch_dt = self._winch_df['datetime'].iloc[self._winch_trip_idx]
        status = (
            f'Alignment: offset {offset_sec:+.3f} s applied '
            f'(sensor {sensor_dt}, winch {winch_dt})'
        )
        self.winch_panel.set_alignment_status(status)
        log.log(status)

    def reset_winch_alignment(self) -> None:
        """Restore original winch data and clear trip detection."""
        if self.winch_panel is None:
            return

        log = self.winch_panel.log_widget
        if self._winch_df_original is not None:
            self._winch_df = self._winch_df_original.copy()
        else:
            self._winch_df = None

        self._clear_winch_trip_state()
        self._update_winch_plot()
        self._on_winch_search_region_changed()
        log.log('Winch data reset to original; trip detection cleared.')

    def _on_winch_trip_line_moved(self, new_idx: int) -> None:
        """Handle user dragging the winch trip line."""
        self._winch_trip_idx = new_idx
        if self.winch_panel is None or self._winch_df is None:
            return
        if 0 <= new_idx < len(self._winch_df):
            dt = self._winch_df['datetime'].iloc[new_idx]
            self.winch_panel.set_winch_trip_status(
                f'Winch trip: index {new_idx}, {dt}  (dragged)'
            )
            self.winch_panel.log_widget.log(
                f'Winch trip line moved to index {new_idx}'
            )

    def _on_winch_search_region_changed(self) -> None:
        """Update panel label when search region is adjusted on the plot."""
        if self.winch_panel is None or self.winch_plot_view is None:
            return
        start, end = self.winch_plot_view.get_search_window_timestamps()
        if start is not None and end is not None:
            self.winch_panel.set_search_window_label(
                f'Search window: {start} – {end}'
            )
        elif self.winch_panel.show_search_region_check.isChecked():
            self.winch_panel.set_search_window_label(
                'Search window: drag blue region on winch plot (window 1)'
            )
        else:
            self.winch_panel.set_search_window_label(
                'Search window: enable checkbox to adjust on winch plot (window 1)'
            )

    def _on_winch_search_region_toggled(self, enabled: bool) -> None:
        """Show or hide the draggable search region on the winch plot."""
        if self.winch_plot_view is not None:
            self.winch_plot_view.set_search_region_enabled(enabled)
        self._on_winch_search_region_changed()

    def _update_winch_sensor_trip_status(self) -> None:
        """Refresh sensor trip readout on the winch panel."""
        if self.winch_panel is None:
            return
        if self.sensor_data is None:
            self.winch_panel.set_sensor_trip_status('Sensor trip: not set')
            return

        sensor_idx = self._resolve_calc_trip_index()
        if sensor_idx is None:
            self.winch_panel.set_sensor_trip_status('Sensor trip: not set')
            return

        dt_col = self.sensor_data.datetime_col
        if dt_col in self.sensor_data.df.columns and 0 <= sensor_idx < len(self.sensor_data.df):
            dt = self.sensor_data.df[dt_col].iloc[sensor_idx]
            self.winch_panel.set_sensor_trip_status(
                f'Sensor trip: index {sensor_idx}, {dt}'
            )
        else:
            self.winch_panel.set_sensor_trip_status(
                f'Sensor trip: index {sensor_idx}'
            )

    def _update_winch_plot(self):
        """Refresh winch secondary plots from current panel settings."""
        if self.winch_plot_view is None or self.winch_panel is None:
            return

        col1 = self.winch_panel.get_column_1()
        col2 = self.winch_panel.get_column_2()
        show_second = self.winch_panel.show_second_window()

        if self._winch_file_names:
            source = f"Source: {', '.join(self._winch_file_names)}"
        elif self.winch_panel.uses_manual_selection():
            source = 'Manual: no files selected'
        else:
            source = 'Auto: no overlapping winch data'

        self.winch_plot_view.plot(
            self._winch_df,
            column_1=col1,
            column_2=col2,
            show_second=show_second,
            source_label=source,
        )

        if self._winch_trip_idx is not None:
            self.winch_plot_view.add_winch_trip_line(self._winch_trip_idx)

        self._on_winch_search_region_changed()

    def _build_winch_save_payload(self) -> tuple[Optional[dict], Optional[dict]]:
        """Build flat columns and params section for aligned winch data."""
        if (
            not self._winch_aligned
            or self._winch_trip_idx is None
            or self._winch_df_original is None
            or not self._winch_file_ids
        ):
            return None, None

        idx = int(self._winch_trip_idx)
        if not (0 <= idx < len(self._winch_df_original)):
            return None, None

        trip_dt = self._winch_df_original['datetime'].iloc[idx]
        if pd.isna(trip_dt):
            return None, None

        trip_dt_native = pd.Timestamp(trip_dt).to_pydatetime().replace(tzinfo=None)

        search_start, search_end = (None, None)
        if self.winch_plot_view is not None:
            search_start, search_end = (
                self.winch_plot_view.get_search_window_timestamps()
            )

        sensor_idx = self._resolve_calc_trip_index()
        sensor_dt_native = None
        if (
            sensor_idx is not None
            and self.sensor_data is not None
            and 0 <= sensor_idx < len(self.sensor_data.df)
        ):
            dt_col = self.sensor_data.datetime_col
            if dt_col in self.sensor_data.df.columns:
                sensor_dt = self.sensor_data.df[dt_col].iloc[sensor_idx]
                if pd.notna(sensor_dt):
                    sensor_dt_native = (
                        pd.Timestamp(sensor_dt).to_pydatetime().replace(tzinfo=None)
                    )

        panel = self.winch_panel
        flat_data = {
            'winch_trip_index': idx,
            'winch_trip_datetime': trip_dt_native,
            'winch_time_offset_sec': float(self._winch_time_offset_sec),
        }
        params = {
            'load_mode': self._winch_load_mode,
            'winch_file_ids': list(self._winch_file_ids),
            'winch_file_names': list(self._winch_file_names),
            'detection': {
                'column': panel.get_column_1() if panel else None,
                'edge_buffer': panel.get_edge_buffer() if panel else 500,
                'drop_threshold': panel.get_drop_threshold() if panel else 1000.0,
                'search_start': (
                    search_start.isoformat() if search_start is not None else None
                ),
                'search_end': (
                    search_end.isoformat() if search_end is not None else None
                ),
            },
            'trip_index': idx,
            'trip_datetime_original': trip_dt_native.isoformat(),
            'time_offset_sec': float(self._winch_time_offset_sec),
            'aligned': True,
            'sensor_trip_index_at_align': sensor_idx,
            'sensor_trip_datetime_at_align': (
                sensor_dt_native.isoformat() if sensor_dt_native else None
            ),
            'display': {
                'window1_column': panel.get_column_1() if panel else None,
                'window2_column': panel.get_column_2() if panel else None,
                'show_second_window': (
                    panel.show_second_window() if panel else False
                ),
            },
        }
        return flat_data, params

    def _update_start_pen_line(
        self,
        trip_idx: Optional[int] = None,
        ws_override: Optional[np.ndarray] = None,
        core_length_ft_override: Optional[float] = None,
        tc_length_ft_override: Optional[float] = None,
        trig_override: Optional[np.ndarray] = None,
    ):
        """Recompute and display the start-penetration and seafloor lines.

        Parameters
        ----------
        ws_override : np.ndarray or None
            Pre-built weight-stand array to use instead of reading from the
            dataframe.  Pass this when the values have already been shifted
            (e.g. during Alter-mode estimation) so the start_pen line
            reflects the modified trace.
        core_length_ft_override : float or None
            Override for core barrel length in feet.  When provided, used
            instead of the value stored in sensor metadata (e.g. Alter mode).
        tc_length_ft_override : float or None
            Override for trigger core length in feet (Alter mode).
        trig_override : np.ndarray or None
            Pre-shifted trigger core array (Alter mode).
        """
        self.main_plot.remove_start_pen_line()
        self.main_plot.remove_seafloor_line()
        if self.sensor_data is None or trip_idx is None:
            return
        x = self.sensor_data.get_timestamps_epoch()
        md = self.sensor_data.metadata
        core_length_ft = core_length_ft_override if core_length_ft_override is not None else md.get('core_length')
        if not core_length_ft or core_length_ft <= 0:
            return
        FT_TO_M_local = 1.0 / 3.28
        core_length_m = core_length_ft * FT_TO_M_local
        panel = self.calculate_panel
        ws_col = panel.get_weight_stand_col()
        trig_col = panel.get_trigger_col()
        if not ws_col or ws_col not in self.sensor_data.df.columns:
            return
        if ws_override is not None:
            ws_vals = ws_override
        else:
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
        sf = None
        # Manual override takes priority over trigger-sensor formula
        if self._manual_seafloor is not None:
            sf = self._manual_seafloor
        elif trig_col and trig_col in self.sensor_data.df.columns:
            if trig_override is not None:
                trig_vals = trig_override
            else:
                trig_vals = (
                    self.sensor_data.df[trig_col]
                    .interpolate().ffill().bfill().values
                )
            tc_len_ft = tc_length_ft_override if tc_length_ft_override is not None else md.get('trigger_core_length')
            trigger_pen = panel.get_trigger_pen()
            if tc_len_ft and tc_len_ft > 0:
                sf = (float(trig_vals[trip_idx])
                      + tc_len_ft * FT_TO_M_local
                      - trigger_pen)
        if sf is None:
            return
        # Add seafloor line (movable when using manual override)
        movable = self._manual_seafloor is not None
        self.main_plot.add_seafloor_line(sf, movable=movable)
        # A dragged start_pen wins over the computed intersection, otherwise
        # every recompute (seafloor edit, calculate re-run, restore) would
        # silently undo the drag.
        if self._manual_start_pen is not None:
            if 0 <= self._manual_start_pen < len(x):
                self._start_pen_idx = self._manual_start_pen
                self.main_plot.add_start_pen_line(
                    float(x[self._manual_start_pen])
                )
                return
        # Add start_pen line
        ws_len_m = panel.get_weight_stand_length_m()
        core_tip = ws_vals + ws_len_m + core_length_m
        search_from = trip_idx
        after = core_tip[search_from:]
        candidates = np.where(after >= sf)[0]
        if len(candidates) > 0:
            sp_idx = search_from + int(candidates[0])
            if 0 <= sp_idx < len(x):
                self._start_pen_idx = sp_idx
                self.main_plot.add_start_pen_line(float(x[sp_idx]))

    def export_calculation_results(self):
        """Export the last calculation results, inputs, and corrections to a text file."""
        if self._last_calc_results is None or self._last_calc_inputs is None:
            self._show_warning(
                "No calculation results to export.\n"
                "Click 'Calculate' first."
            )
            return

        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data and self.sensor_data.core_title
            else 'data'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_calculations_{timestamp}.txt"

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Calculation Results", default_name,
            "Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self._write_calculation_export(file_path)
            self._log_active(f"Results exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                "Calculation results exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def export_calculation_diagram(self):
        """Export the geometry diagram to an image file."""
        if self.calculation_plot is None:
            self._show_warning("No diagram to export.")
            return

        import pyqtgraph.exporters as exporters

        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data and self.sensor_data.core_title
            else 'diagram'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_geometry_{timestamp}.png"

        file_path, selected_filter = QFileDialog.getSaveFileName(
            self.main_window, "Export Geometry Diagram", default_name,
            "PNG Image (*.png);;SVG Image (*.svg);;All Files (*)"
        )
        if not file_path:
            return

        try:
            plot_item = self.calculation_plot.plot_widget.plotItem
            if file_path.lower().endswith('.svg'):
                exporter = exporters.SVGExporter(plot_item)
            else:
                exporter = exporters.ImageExporter(plot_item)
                exporter.parameters()['width'] = 1600
            exporter.export(file_path)
            self._log_active(f"Diagram exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                "Geometry diagram exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def _write_calculation_export(self, file_path: str):
        """Write calculation results with full context to a text file."""
        from datetime import datetime
        from ..domain.processing.calculations import FT_TO_M

        res = self._last_calc_results
        inp = self._last_calc_inputs
        sd = self.sensor_data
        panel = self.calculate_panel

        lines = []
        lines.append("=" * 60)
        lines.append("CORING ANALYSIS CALCULATION REPORT")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)

        # Source data
        lines.append("")
        lines.append("--- Source Data ---")
        if sd is not None:
            lines.append(f"  File:        {sd.source_file}")
            lines.append(f"  Core:        {sd.core_title}")
            lines.append(f"  Rows:        {sd.row_count:,}")
            lines.append(f"  Sensors:     {sd.num_sensors}")
            tr = sd.time_range
            if tr:
                lines.append(f"  Time range:  {tr[0]} to {tr[1]}")

        # Corrections applied
        lines.append("")
        lines.append("--- Corrections Applied ---")
        if sd is not None and sd.corrections:
            time_corrections = [
                c for c in sd.corrections
                if c.correction_type == 'time_shift'
            ]
            depth_corrections = [
                c for c in sd.corrections
                if c.correction_type in ('depth_calibration', 'depth_manual')
            ]
            if time_corrections:
                lines.append("  Time corrections:")
                for corr in time_corrections:
                    shift = corr.parameters.get('shift_seconds', 0)
                    sign = '+' if shift >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    lines.append(f"    {short}: {sign}{shift:.4f}s")
            if depth_corrections:
                lines.append("  Depth corrections:")
                for corr in depth_corrections:
                    offset = corr.parameters.get('offset', 0)
                    sign = '+' if offset >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    lines.append(f"    {short}: {sign}{offset:.4f}m")
        else:
            lines.append("  None")

        # Inputs / configuration
        lines.append("")
        lines.append("--- Calculation Inputs ---")
        ws_col = inp['weight_stand_col']
        rel_col = inp['release_col']
        trig_col = inp['trigger_col']
        lines.append(
            f"  Weight Stand:         "
            f"{SensorData.get_short_name(ws_col)}"
        )
        lines.append(
            f"  Release Device:       "
            f"{SensorData.get_short_name(rel_col)}"
        )
        if trig_col:
            lines.append(
                f"  Trigger Core/Weight:  "
                f"{SensorData.get_short_name(trig_col)}"
            )
        else:
            lines.append("  Trigger Core/Weight:  not available")

        if inp['smoothing_enabled']:
            lines.append(
                f"  Savitzky-Golay:       enabled "
                f"(window={inp['sg_window']}, poly={inp['sg_poly']})"
            )
        else:
            lines.append("  Savitzky-Golay:       disabled")

        if inp['trip_idx'] is not None:
            lines.append(f"  Trip index:           {inp['trip_idx']}")
            # Also show the trip datetime
            if sd is not None:
                dt_col = sd.datetime_col
                if (dt_col in sd.df.columns
                        and 0 <= inp['trip_idx'] < len(sd.df)):
                    ts = sd.df[dt_col].iloc[inp['trip_idx']]
                    if pd.notna(ts):
                        lines.append(f"  Trip time:            {ts}")
        else:
            lines.append("  Trip index:           not set")

        if inp['start_core_idx'] is not None:
            lines.append(
                f"  Start core index:     {inp['start_core_idx']}"
            )
            if sd is not None:
                dt_col = sd.datetime_col
                if (dt_col in sd.df.columns
                        and 0 <= inp['start_core_idx'] < len(sd.df)):
                    ts = sd.df[dt_col].iloc[inp['start_core_idx']]
                    if pd.notna(ts):
                        lines.append(
                            f"  Start core time:      {ts}"
                        )
        else:
            lines.append("  Start core index:     not available")

        lines.append(
            f"  Piston position:      "
            f"{'available' if inp['piston_available'] else 'not computed'}"
        )

        tc_len = inp['trigger_core_length_ft']
        if tc_len is not None:
            lines.append(
                f"  Trigger core length:  {tc_len} ft "
                f"({tc_len * FT_TO_M:.3f} m)"
            )
        else:
            lines.append("  Trigger core length:  not available")

        cl = inp['core_length_ft']
        if cl is not None:
            lines.append(
                f"  Core length:          {cl} ft "
                f"({cl * FT_TO_M:.3f} m)"
            )
        else:
            lines.append("  Core length:          not available")

        lines.append(
            f"  Trigger penetration:  {inp['trigger_pen']:.2f} m"
        )

        # Results
        lines.append("")
        lines.append("--- Calculated Values ---")

        def _fmt(label: str, val, unit: str = "m") -> str:
            if val is None:
                return f"  {label:<30s}  N/A"
            return f"  {label:<30s}  {val:>10.4f} {unit}"

        lines.append(_fmt("Recoil Max:", res.recoil_max))
        lines.append(_fmt("Fall Distance:", res.fall_dist))
        lines.append(_fmt("Suck-in:", res.suck_in))
        lines.append(_fmt("Recoil at Start Core:", res.recoil_start))
        lines.append(_fmt("Freefall at Start Core:", res.freefall_start))
        lines.append(_fmt("Piston Suck:", res.piston_suck))

        if res.seafloor is not None:
            lines.append(
                f"  {'Seafloor Depth:':<30s}  {res.seafloor:>10.4f} m"
            )
        else:
            lines.append(f"  {'Seafloor Depth:':<30s}  N/A")

        lines.append(_fmt("Piston Altitude:", res.piston_alt))
        lines.append(_fmt("Penetration Deficit:", res.pen_deficit))
        lines.append(_fmt("Freefall Estimate:", res.freefall_est))

        if res.notes:
            lines.append("")
            lines.append("--- Notes ---")
            for note in res.notes:
                lines.append(f"  {note}")

        lines.append("")
        lines.append("=" * 60)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    # ==================================================================
    # Common Operations
    # ==================================================================

    def reset_to_original(self):
        """Reset data to the original loaded state."""
        if self.original_data is None:
            self._show_warning("No original data to reset to")
            return

        self.sensor_data = self.original_data.copy()
        self.main_plot.set_sensor_data(self.sensor_data)
        self.plot_depths()
        self.time_offset_results = None
        self._log_active("Data reset to original")

    def export_corrected_csv(self):
        """Export the current sensor data to CSV."""
        if self.sensor_data is None:
            self._show_warning("No data to export")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Data", "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self.sensor_data.df.to_csv(file_path, index=False)
            self._log_active(f"Exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success", "Data exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def export_trip_csv(self):
        """Export the current sensor data with trip detection metadata."""
        if self.sensor_data is None:
            self._show_warning("No data to export")
            return

        if self.trip_detection_result is None:
            self._show_warning("No trip detection has been performed yet")
            return

        # Generate default filename
        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data.core_title else 'data'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_corrected_{timestamp}.csv"

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Trip Data", default_name,
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self._write_trip_csv(file_path)
            self._log_active(f"Exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                f"Data exported with trip metadata!\n\n"
                f"Trip detected at: {self.trip_detection_result.trip_datetime}"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def _write_trip_csv(self, file_path: str):
        """Write CSV with full metadata header including trip and corrections."""
        from datetime import datetime

        header_lines = []

        # Try to read original header from source file
        if self._loaded_file_path and Path(self._loaded_file_path).exists():
            try:
                with open(self._loaded_file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('#') and not line.strip() == '#':
                            header_lines.append(line.rstrip())
                        elif line.strip().startswith('datetime'):
                            break
            except Exception:
                pass

        # If we couldn't read the original, create basic header
        if not header_lines:
            header_lines = [
                "# Export from Sediment App - Sensor Alignment Tool",
                f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            if self.sensor_data.core_title:
                header_lines.append(f"# Core: {self.sensor_data.core_title}")
            header_lines.append(
                f"# Data shape: {self.sensor_data.row_count:,} rows "
                f"\u00d7 {len(self.sensor_data.df.columns)} columns"
            )
            time_range = self.sensor_data.time_range
            if time_range:
                header_lines.append(
                    f"# Time range: {time_range[0]} to {time_range[1]}"
                )

        # Add trip detection info
        trip = self.trip_detection_result
        header_lines.append("#")
        header_lines.append(
            f"# Trip detected at: {trip.trip_datetime} "
            f"(index: {trip.trip_index})"
        )

        # Add correction information
        if self.sensor_data.corrections:
            header_lines.append("#")
            time_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type == 'time_shift'
            ]
            depth_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type in ('depth_calibration', 'depth_manual')
            ]

            if time_corrections:
                header_lines.append("# Time corrections applied:")
                for corr in time_corrections:
                    shift = corr.parameters.get('shift_seconds', 0)
                    sign = '+' if shift >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(
                        f"#   {short}: {sign}{shift:.2f}s"
                    )

            if depth_corrections:
                header_lines.append("# Depth corrections applied:")
                for corr in depth_corrections:
                    offset = corr.parameters.get('offset', 0)
                    sign = '+' if offset >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(
                        f"#   {short}: {sign}{offset:.3f}m"
                    )
        else:
            header_lines.append("#")
            header_lines.append("# No corrections applied")

        header_lines.append("#")

        # Write file
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            for line in header_lines:
                f.write(line + '\n')
            self.sensor_data.df.to_csv(f, index=False)

    def export_piston_csv(self):
        """Export sensor data with a piston_position column and piston metadata."""
        if self.sensor_data is None:
            self._show_warning("No data to export")
            return

        if self._piston_values is None:
            self._show_warning(
                "No piston position calculated yet.\n"
                "Click 'Calculate & Plot Piston' first."
            )
            return

        core_name = (
            self.sensor_data.core_title.replace(' ', '_')
            if self.sensor_data.core_title else 'data'
        )
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        default_name = f"{core_name}_piston_{timestamp}.csv"

        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Piston Data", default_name,
            "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        try:
            self._write_piston_csv(file_path)
            self._log_active(f"Exported to {Path(file_path).name}")
            QMessageBox.information(
                self.main_window, "Success",
                "Piston data exported successfully!"
            )
        except Exception as e:
            self._show_error("Export Error", str(e))

    def _write_piston_csv(self, file_path: str):
        """Write CSV with piston_position column and full metadata header."""
        from datetime import datetime

        header_lines = []

        # Try to read original header from source file
        if self._loaded_file_path and Path(self._loaded_file_path).exists():
            try:
                with open(self._loaded_file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('#') and not line.strip() == '#':
                            header_lines.append(line.rstrip())
                        elif line.strip().startswith('datetime'):
                            break
            except Exception:
                pass

        if not header_lines:
            header_lines = [
                "# Export from Sediment App - Sensor Alignment Tool",
                f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ]
            if self.sensor_data.core_title:
                header_lines.append(f"# Core: {self.sensor_data.core_title}")
            header_lines.append(
                f"# Data shape: {self.sensor_data.row_count:,} rows "
                f"\u00d7 {len(self.sensor_data.df.columns)} columns"
            )
            time_range = self.sensor_data.time_range
            if time_range:
                header_lines.append(
                    f"# Time range: {time_range[0]} to {time_range[1]}"
                )

        # Trip time metadata
        panel = self.piston_panel
        header_lines.append("#")
        qdt = panel.trip_time_edit.dateTime()
        d, t = qdt.date(), qdt.time()
        trip_str = (
            f"{d.year()}-{d.month():02d}-{d.day():02d} "
            f"{t.hour():02d}:{t.minute():02d}:{t.second():02d}"
            f".{t.msec():03d}"
        )
        header_lines.append(f"# trip_time: {trip_str}")

        # Start core metadata
        start_idx = self._piston_start_core_idx
        if start_idx is not None:
            header_lines.append(f"# start_core_index: {start_idx}")
            dt_col = self.sensor_data.datetime_col
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= start_idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[start_idx]
                if pd.notna(ts):
                    header_lines.append(f"# start_core_time: {ts}")

        # Offsets from corrections
        if self.sensor_data.corrections:
            time_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type == 'time_shift'
            ]
            depth_corrections = [
                c for c in self.sensor_data.corrections
                if c.correction_type in ('depth_calibration', 'depth_manual')
            ]

            if time_corrections:
                header_lines.append("#")
                header_lines.append("# Time corrections applied:")
                for corr in time_corrections:
                    shift = corr.parameters.get('shift_seconds', 0)
                    sign = '+' if shift >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(f"#   {short}: {sign}{shift:.4f}s")

            if depth_corrections:
                header_lines.append("#")
                header_lines.append("# Depth corrections applied:")
                for corr in depth_corrections:
                    offset = corr.parameters.get('offset', 0)
                    sign = '+' if offset >= 0 else ''
                    short = SensorData.get_short_name(corr.sensor_column)
                    header_lines.append(f"#   {short}: {sign}{offset:.4f}m")
        else:
            header_lines.append("#")
            header_lines.append("# No depth/time corrections applied")

        header_lines.append("#")

        # Build dataframe with piston_position column added
        df_out = self.sensor_data.df.copy()
        piston_col = np.full(len(df_out), np.nan)
        n = min(len(self._piston_values), len(df_out))
        piston_col[:n] = self._piston_values[:n]
        df_out.insert(len(df_out.columns), 'piston_position', piston_col)

        # Write file
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            for line in header_lines:
                f.write(line + '\n')
            df_out.to_csv(f, index=False)

    # ==================================================================
    # Save to Database
    # ==================================================================

    def _upsert_analysis_result(self,
                                 flat_data: Optional[dict] = None,
                                 params_section: Optional[dict] = None) -> None:
        """
        Write into this core's single analysis result row.

        Each core has one row, created on its first save and updated by every
        later save, so each panel contributes to one consolidated record
        regardless of which session it was saved from.
        """
        if self._loaded_core_id is None or self.store is None:
            self._show_warning(
                "Cannot save.\n\n"
                "Load a core from the project to enable saving analysis results."
            )
            return

        try:
            result_id, created = results_io.upsert_result(
                self.store, self._loaded_core_id, flat_data, params_section,
            )
            verb = "saved to" if created else "updated in"
            msg = f"Analysis result {verb} project (result_id={result_id})"

            self._sync_trigger_penetration_to_core()

            self._log_active(msg)
            if self.main_window:
                self.main_window.statusBar().showMessage(msg, 5000)

        except Exception as e:
            self._show_error("Project Save Error", str(e))

    # ------------------------------------------------------------------

    def save_all_to_db(self):
        """Save all available analysis results to the DB in a single upsert."""
        if self._loaded_core_id is None or self.store is None:
            self._show_warning(
                "Cannot save.\n\n"
                "Load a core from the project to enable saving analysis results."
            )
            return

        import pandas as pd
        flat_data: dict = {}
        params_section: dict = {}
        saved: list = []
        skipped: list = []

        # --- Depth offset ---
        # Every section here replaces its stored counterpart wholesale, so an
        # empty panel must be skipped rather than written: a save from a
        # session that never visited this mode would otherwise blank a
        # calibration saved earlier.
        if self.sensor_data is None:
            skipped.append("depth offset (no data)")
        else:
            panel = self.depth_panel
            calib_json = self.calibration.to_dict() if self.calibration is not None else None
            depth_section = {
                "calib_json": calib_json,
                "label_mapping": panel.get_calibration_mapping(),
                "reference_sensor": panel.get_ref_sensor(),
                "manual_offsets": panel.get_manual_offsets(),
            }
            if any(depth_section.values()):
                params_section["depth_offset"] = depth_section
                saved.append("depth offset")
            else:
                skipped.append("depth offset (nothing set)")

        # --- Time offset ---
        if self.sensor_data is None:
            skipped.append("time offset (no data)")
        else:
            panel = self.time_panel
            low_hz, high_hz, order = panel.get_filter_params()
            offsets_data = []
            if self.time_offset_results:
                for r in self.time_offset_results:
                    offsets_data.append({
                        "sensor_col": r.sensor_column,
                        "offset_seconds": r.offset_seconds,
                        "rms_value": r.rms_value,
                        "is_reference": r.is_reference,
                    })
            manual_time_offsets = panel.get_manual_offsets()
            # The filter settings alone are just spinbox defaults; only a
            # computed or hand-entered offset counts as real content.
            if offsets_data or manual_time_offsets:
                params_section["time_offset"] = {
                    "reference_col": panel.get_ref_col(),
                    "filter_low_hz": low_hz,
                    "filter_high_hz": high_hz,
                    "filter_order": order,
                    "manual_offsets": manual_time_offsets,
                    "offsets": offsets_data,
                }
                saved.append("time offset")
            else:
                skipped.append("time offset (nothing set)")

        # --- Trip detection ---
        if self.trip_detection_result is not None:
            panel = self.trip_panel
            sg_window, sg_poly = panel.get_sg_params()
            trip_dt_native = (
                pd.Timestamp(self.trip_detection_result.trip_datetime)
                .to_pydatetime().replace(tzinfo=None)
            )
            flat_data["trip_index"] = int(self.trip_detection_result.trip_index)
            flat_data["trip_datetime"] = trip_dt_native
            params_section["trip"] = {
                "sg_window": sg_window,
                "sg_poly": sg_poly,
                "derivative_order": panel.get_derivative_order(),
                "threshold": panel.get_threshold(),
                "sampling_rate_hz": panel.get_sampling_rate(),
                "edge_buffer": panel.get_edge_buffer(),
            }
            saved.append("trip detection")
        else:
            skipped.append("trip (not detected)")

        # --- Piston position ---
        if self._piston_start_core_idx is not None:
            panel = self.piston_panel
            idx = self._piston_start_core_idx
            start_dt = None
            if self.sensor_data is not None:
                dt_col = self.sensor_data.datetime_col
                if (dt_col in self.sensor_data.df.columns
                        and 0 <= idx < len(self.sensor_data.df)):
                    ts = self.sensor_data.df[dt_col].iloc[idx]
                    if pd.notna(ts):
                        start_dt = (
                            pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None)
                        )
            flat_data["start_core_index"] = int(idx)
            if start_dt is not None:
                flat_data["start_core_datetime"] = start_dt
            params_section["piston"] = {
                "weight_stand_col": panel.get_weight_stand_col(),
                "release_col": panel.get_release_col(),
                "scope_ft": panel.get_scope(),
                "core_length_ft": panel.get_core_length(),
                "offset_constant_m": panel.get_offset_constant(),
            }
            saved.append("piston position")
        else:
            skipped.append("piston position (not calculated)")

        # --- Calculation results ---
        if self._last_calc_results is not None and self._last_calc_inputs is not None:
            r = self._last_calc_results
            inp = self._last_calc_inputs
            calc_flat = {
                "result_recoil_max":     r.recoil_max,
                "result_recoil_time_s":  r.recoil_time_s,
                "result_fall_dist":      r.fall_dist,
                "result_suck_in":        r.suck_in,
                "result_recoil_start":   r.recoil_start,
                "result_freefall_start": r.freefall_start,
                "result_piston_suck":    r.piston_suck,
                "result_seafloor":       r.seafloor,
                "result_piston_alt":     r.piston_alt,
                "result_pen_deficit":    r.pen_deficit,
                "result_freefall_est":   r.freefall_est,
                "result_eff_trig_line":  r.eff_trig_line_ft,
                "trigger_pen_m":         inp.get("trigger_pen"),
            }
            flat_data.update({k: v for k, v in calc_flat.items() if v is not None})
            params_section["calc_inputs"] = {
                "weight_stand_col":       inp.get("weight_stand_col"),
                "release_col":            inp.get("release_col"),
                "trigger_col":            inp.get("trigger_col"),
                "smoothing_enabled":      inp.get("smoothing_enabled"),
                "sg_window":              inp.get("sg_window"),
                "sg_poly":                inp.get("sg_poly"),
                "trip_idx":               inp.get("trip_idx"),
                "start_core_idx":         inp.get("start_core_idx"),
                "end_pen_idx":            self._end_pen_idx,
                "pullout_idx":            self._pullout_idx,
                "start_pen_idx":          self._start_pen_idx,
                "start_pen_manual":       self._manual_start_pen,
                "trigger_pen_m":          inp.get("trigger_pen"),
                "core_length_ft":         inp.get("core_length_ft"),
                "trigger_core_length_ft": inp.get("trigger_core_length_ft"),
                "weight_stand_length_m":  inp.get("weight_stand_length_m"),
                "seafloor_manual":        self._manual_seafloor,
            }
            params_section["calc_notes"] = list(r.notes)
            saved.append("calculations")
        else:
            skipped.append("calculations (not run)")

        # --- Winch alignment (only when aligned) ---
        if self._winch_aligned and self._winch_trip_idx is not None:
            winch_flat, winch_params = self._build_winch_save_payload()
            if winch_flat and winch_params:
                flat_data.update(winch_flat)
                params_section["winch"] = winch_params
                saved.append("winch alignment")
            else:
                skipped.append("winch alignment (incomplete data)")
        else:
            skipped.append("winch alignment (not aligned)")

        # Read the stored row before writing over it.
        stale_note = self._stale_calc_warning(saved)

        self._upsert_analysis_result(
            flat_data=flat_data if flat_data else None,
            params_section=params_section if params_section else None,
        )

        parts = []
        if saved:
            parts.append(f"Saved: {', '.join(saved)}")
        if skipped:
            parts.append(f"Skipped: {', '.join(skipped)}")
        self._log_active("Save All — " + " | ".join(parts))
        if stale_note:
            self._log_active(stale_note)
            self._show_warning(stale_note)

    # Flat columns produced only by Calculate mode.
    _CALC_RESULT_COLUMNS = (
        "result_recoil_max", "result_recoil_time_s", "result_fall_dist",
        "result_suck_in", "result_recoil_start", "result_freefall_start",
        "result_piston_suck", "result_seafloor", "result_piston_alt",
        "result_pen_deficit", "result_freefall_est", "result_eff_trig_line",
    )

    def _stale_calc_warning(self, saved: list) -> Optional[str]:
        """Warn when a save leaves stored calculations behind their inputs.

        With one row per core, re-saving part of the analysis keeps whatever
        calculation results were already stored. Those were derived from the
        inputs as they stood at the time, so the row stops being internally
        consistent until Calculate is re-run. Nothing is lost either way, but
        the mismatch is invisible unless we say so.

        Returns the warning text, or None when the row is consistent.
        """
        if "calculations" in saved:
            return None
        upstream = [s for s in saved if s != "winch alignment"]
        if not upstream:
            return None
        if self._loaded_core_id is None or self.store is None:
            return None
        try:
            existing = results_io.fetch_latest_result(
                self.store, self._loaded_core_id
            )
        except Exception:
            return None
        if existing is None:
            return None
        if not any(existing.get(c) is not None
                   for c in self._CALC_RESULT_COLUMNS):
            return None
        return (
            "Saved calculation results for this core are now out of date.\n\n"
            f"This save updated {', '.join(upstream)}, but the stored "
            "calculations were computed from the earlier values.\n\n"
            "Run Calculate and save again to bring them back in step."
        )

    def save_depth_offset_to_db(self):
        """Save depth offset correction parameters to the DB."""
        if self.sensor_data is None:
            self._show_warning("No data loaded.")
            return

        panel = self.depth_panel
        calib_json = (
            self.calibration.to_dict() if self.calibration is not None else None
        )
        params_section = {
            "depth_offset": {
                "calib_json": calib_json,
                "label_mapping": panel.get_calibration_mapping(),
                "reference_sensor": panel.get_ref_sensor(),
                "manual_offsets": panel.get_manual_offsets(),
            }
        }
        self._upsert_analysis_result(params_section=params_section)

    def save_time_offset_to_db(self):
        """Save time offset correction parameters and results to the DB."""
        if self.sensor_data is None:
            self._show_warning("No data loaded.")
            return

        panel = self.time_panel
        low_hz, high_hz, order = panel.get_filter_params()
        offsets_data = []
        if self.time_offset_results:
            for r in self.time_offset_results:
                offsets_data.append({
                    "sensor_col": r.sensor_column,
                    "offset_seconds": r.offset_seconds,
                    "rms_value": r.rms_value,
                    "is_reference": r.is_reference,
                })
        params_section = {
            "time_offset": {
                "reference_col": panel.get_ref_col(),
                "filter_low_hz": low_hz,
                "filter_high_hz": high_hz,
                "filter_order": order,
                "manual_offsets": panel.get_manual_offsets(),
                "offsets": offsets_data,
            }
        }
        self._upsert_analysis_result(params_section=params_section)

    def save_trip_to_db(self):
        """Save trip detection result and parameters to the DB."""
        if self.trip_detection_result is None:
            self._show_warning("No trip has been detected yet.")
            return

        panel = self.trip_panel
        sg_window, sg_poly = panel.get_sg_params()
        trip_dt = self.trip_detection_result.trip_datetime
        # Convert to plain Python datetime for SQLAlchemy / JSON
        import pandas as pd
        trip_dt_native = pd.Timestamp(trip_dt).to_pydatetime().replace(tzinfo=None)

        flat_data = {
            "trip_index": int(self.trip_detection_result.trip_index),
            "trip_datetime": trip_dt_native,
        }
        params_section = {
            "trip": {
                "sg_window": sg_window,
                "sg_poly": sg_poly,
                "derivative_order": panel.get_derivative_order(),
                "threshold": panel.get_threshold(),
                "sampling_rate_hz": panel.get_sampling_rate(),
                "edge_buffer": panel.get_edge_buffer(),
            }
        }
        self._upsert_analysis_result(flat_data=flat_data,
                                      params_section=params_section)

    def save_piston_to_db(self):
        """Save piston position parameters and start-core index to the DB."""
        if self._piston_start_core_idx is None:
            self._show_warning("Piston position has not been calculated yet.")
            return

        panel = self.piston_panel
        ws_col = panel.get_weight_stand_col()
        rel_col = panel.get_release_col()

        start_dt = None
        idx = self._piston_start_core_idx
        if self.sensor_data is not None:
            dt_col = self.sensor_data.datetime_col
            if (dt_col in self.sensor_data.df.columns
                    and 0 <= idx < len(self.sensor_data.df)):
                ts = self.sensor_data.df[dt_col].iloc[idx]
                import pandas as pd
                if pd.notna(ts):
                    start_dt = (
                        pd.Timestamp(ts).to_pydatetime().replace(tzinfo=None)
                    )

        flat_data = {
            "start_core_index": int(idx),
            "start_core_datetime": start_dt,
        }
        params_section = {
            "piston": {
                "weight_stand_col": ws_col,
                "release_col": rel_col,
                "scope_ft": panel.get_scope(),
                "core_length_ft": panel.get_core_length(),
                "offset_constant_m": panel.get_offset_constant(),
            }
        }
        self._upsert_analysis_result(flat_data=flat_data,
                                      params_section=params_section)

    def save_calculations_to_db(self):
        """Save all calculation results and inputs to the DB."""
        if self._last_calc_results is None or self._last_calc_inputs is None:
            self._show_warning(
                "No calculation results available.  Click 'Calculate' first."
            )
            return

        r = self._last_calc_results
        inp = self._last_calc_inputs
        flat_data = {
            "result_recoil_max":     r.recoil_max,
            "result_recoil_time_s":  r.recoil_time_s,
            "result_fall_dist":      r.fall_dist,
            "result_suck_in":        r.suck_in,
            "result_recoil_start":   r.recoil_start,
            "result_freefall_start": r.freefall_start,
            "result_piston_suck":    r.piston_suck,
            "result_seafloor":       r.seafloor,
            "result_piston_alt":     r.piston_alt,
            "result_pen_deficit":    r.pen_deficit,
            "result_freefall_est":   r.freefall_est,
            "result_eff_trig_line":  r.eff_trig_line_ft,
            "trigger_pen_m":         inp.get("trigger_pen"),
        }
        # Drop None floats so we don't overwrite already-set columns with NULL
        flat_data = {k: v for k, v in flat_data.items() if v is not None}

        inp = self._last_calc_inputs
        params_section = {
            "calc_inputs": {
                "weight_stand_col":        inp.get("weight_stand_col"),
                "release_col":             inp.get("release_col"),
                "trigger_col":             inp.get("trigger_col"),
                "smoothing_enabled":       inp.get("smoothing_enabled"),
                "sg_window":               inp.get("sg_window"),
                "sg_poly":                 inp.get("sg_poly"),
                "trip_idx":                inp.get("trip_idx"),
                "start_core_idx":          inp.get("start_core_idx"),
                "end_pen_idx":             self._end_pen_idx,
                "pullout_idx":             self._pullout_idx,
                "start_pen_idx":           self._start_pen_idx,
                "start_pen_manual":        self._manual_start_pen,
                "trigger_pen_m":           inp.get("trigger_pen"),
                "core_length_ft":          inp.get("core_length_ft"),
                "trigger_core_length_ft":  inp.get("trigger_core_length_ft"),
                "weight_stand_length_m":   inp.get("weight_stand_length_m"),
                "seafloor_manual":         self._manual_seafloor,
            },
            "calc_notes": list(r.notes),
        }
        self._upsert_analysis_result(flat_data=flat_data,
                                      params_section=params_section)

    # ==================================================================
    # Selection handling
    # ==================================================================

    def _set_selection_mode(self, enabled: bool):
        self.main_plot.selection_mode = enabled

    def _clear_selection(self):
        self.main_plot.clear_selection()
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )
        if mode == 'Time Offset':
            self.time_panel.selection_controls.clear_info()
        elif mode == 'Create Calibration':
            self.calibration_panel.selection_controls.clear_info()

    def _on_selection_changed(self, start_idx: int, end_idx: int):
        """Called when user completes a selection on the main plot."""
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )

        n = end_idx - start_idx + 1
        extra = ''
        if self.sensor_data is not None:
            dt_col = self.sensor_data.datetime_col
            if dt_col in self.sensor_data.df.columns:
                t_start = self.sensor_data.df[dt_col].iloc[start_idx]
                t_end = self.sensor_data.df[dt_col].iloc[end_idx]
                extra = f"{t_start} to {t_end}"

        if mode == 'Time Offset':
            self.time_panel.selection_controls.update_selection_info(
                start_idx, end_idx, extra,
            )
        elif mode == 'Create Calibration':
            self.calibration_panel.selection_controls.update_selection_info(
                start_idx, end_idx, extra,
            )

    def _on_selection_cleared(self):
        pass  # Already handled by _clear_selection

    # ==================================================================
    # Mode switching
    # ==================================================================

    def on_mode_changed(self, mode_name: str):
        """Called by MainWindow when mode changes."""
        if self.main_window is None:
            return

        # Disable selection mode when leaving a selection-enabled mode
        self.main_plot.selection_mode = False
        # Reset toggle buttons on panels that have selection controls
        if self.time_panel is not None:
            self.time_panel.selection_controls.toggle_btn.setChecked(False)
            self.time_panel.selection_controls._on_toggled()
        if self.calibration_panel is not None:
            self.calibration_panel.selection_controls.toggle_btn.setChecked(False)
            self.calibration_panel.selection_controls._on_toggled()

        # Clear selection region when entering non-selection modes
        if mode_name not in ('Time Offset', 'Create Calibration'):
            self.main_plot.clear_selection()

        # Show/hide secondary view
        if mode_name == 'Time Offset':
            self.main_window.show_secondary_view('heave')
        elif mode_name == 'Create Calibration':
            self.main_window.show_secondary_view('statistics')
            # Populate cruise dropdown when entering this mode
            try:
                cruises = ProjectDataLoader.fetch_cruises(self.store)
                self.calibration_panel.set_cruises(cruises)
            except Exception:
                pass  # DB unavailable — user will see empty dropdown
        elif mode_name == 'Trip Detector':
            self.main_window.show_secondary_view('trip')
        elif mode_name == 'Calculate':
            self.main_window.show_secondary_view('calculation')
        elif mode_name == 'Alter':
            if self.alter_panel is not None:
                core_info = self._alter_core_info
                if core_info is None and self.sensor_data is not None:
                    core_info = self.sensor_data.metadata
                if core_info is not None:
                    tpen = (
                        self.calculate_panel.get_trigger_pen()
                        if self.calculate_panel is not None else 0.0
                    )
                    self.alter_panel.populate_from_core_info(
                        core_info, trigger_pen=tpen
                    )
            if self._last_calc_results is not None:
                self.main_window.show_secondary_view('calculation')
            else:
                self.main_window.hide_secondary_view()
        elif mode_name == 'Piston Analysis':
            self.main_window.show_secondary_view('piston_analysis')
        elif mode_name == 'Winch':
            self.main_window.show_secondary_view('winch')
            if self._winch_df is not None and self._winch_aligned:
                self._refresh_winch_ui()
            else:
                if self.winch_plot_view is not None and self.main_plot is not None:
                    self.winch_plot_view.set_x_link(self.main_plot.plot_item)
                self.reload_winch_data()
        elif mode_name == 'Predict':
            self.main_window.show_secondary_view('predict')
            if self.sensor_data is not None:
                self._populate_predict_panel_from_session()
                self._plot_predict_mode()
            if self.recoil_calibration is None:
                self._prompt_load_recoil_calibration()
            elif self._last_predict_result is not None:
                self._refresh_predict_plot()
            self._update_predict_trigger_line_display()
        else:
            self.main_window.hide_secondary_view()

        # Clean up piston overlays when leaving overlay-preserving modes
        if mode_name not in (
            'Piston Position', 'Calculate', 'Alter', 'Piston Analysis', 'Winch',
            'Predict',
        ):
            self.main_plot.remove_piston_trace()
            self.main_plot.remove_start_core_line()
            self.main_plot.remove_end_pen_line()
            self.main_plot.remove_pullout_line()

        # When entering Piston Analysis mode, restore all Calculate-mode overlays
        if mode_name == 'Piston Analysis':
            if self.sensor_data is not None:
                self._plot_calculate_mode()
                if self._piston_values is not None:
                    self.main_plot.update_piston_trace(self._piston_values)
            return

        # When entering Winch mode, restore existing overlays and winch plots
        if mode_name == 'Winch':
            if self.sensor_data is not None:
                self._plot_winch_mode()
            return

        # When entering Calculate mode, restore trip / start_core / piston lines
        if mode_name == 'Calculate':
            self.main_plot.remove_piston_trace()
            self.main_plot.remove_start_core_line()
            self.main_plot.remove_smoothed_traces()
            if self.sensor_data is not None:
                # Sync start_core from piston mode BEFORE plotting
                # (always refresh – piston mode may have updated it)
                if self._piston_start_core_idx is not None:
                    self._calc_start_core_idx = self._piston_start_core_idx
                    dt_col = self.sensor_data.datetime_col
                    ts_str = ''
                    idx = self._calc_start_core_idx
                    if (dt_col in self.sensor_data.df.columns
                            and 0 <= idx < len(self.sensor_data.df)):
                        ts = self.sensor_data.df[dt_col].iloc[idx]
                        if pd.notna(ts):
                            ts_str = str(ts)
                    self.calculate_panel.update_start_core_info(idx, ts_str)

                # Sync trip time from trip detector / piston panel
                self._sync_trip_to_calculate_panel()

                self._plot_calculate_mode()
                return  # _plot_calculate_mode already sets sensor data

        # Re-plot current data if available
        if self.sensor_data is not None:
            self.main_plot.set_sensor_data(self.sensor_data)

    # ==================================================================
    # Alter mode
    # ==================================================================

    def _on_alter_core_changed(self, core_id: int, core_info: dict):
        """Store the selected core info and populate the Alter panel."""
        self._alter_core_info = core_info
        if self.alter_panel is not None:
            self.alter_panel.populate_from_core_info(core_info)
            self.alter_panel.log_widget.log(
                f"Core selected: {core_info.get('core_name', core_id)}"
            )

    def _run_alter_estimation(self):
        """Re-run piston position + calculate with altered parameters."""
        if self.alter_panel is None:
            return

        log = self.alter_panel.log_widget

        if self.sensor_data is None:
            log.log("No data loaded.")
            return
        if self._last_calc_results is None:
            log.log(
                "No Calculate result available. "
                "Run Calculate mode first, then return here."
            )
            return

        # Use explicit core selection if available, otherwise fall back to
        # the metadata of the currently loaded sensor data.
        effective_core_info = self._alter_core_info
        if effective_core_info is None:
            effective_core_info = self.sensor_data.metadata
        if not effective_core_info:
            log.log("No core parameters available.")
            return

        FT_TO_M = 1.0 / 3.28

        db_scope_ft = float(effective_core_info.get('scope') or 0.0)
        db_trig_line_ft = float(
            effective_core_info.get('trigger_line_length') or 0.0
        )
        db_core_length_ft = float(effective_core_info.get('core_length') or 0.0)
        db_tc_length_ft = float(
            effective_core_info.get('trigger_core_length') or 0.0
        )

        new_scope_ft = self.alter_panel.get_scope()
        new_trig_line_ft = self.alter_panel.get_trigger_line_length()
        new_core_length_ft = self.alter_panel.get_core_length()
        new_tc_length_ft = self.alter_panel.get_trigger_core_length()

        # Log what changed
        log.log("")
        log.log("=== Alter Estimation ===")
        log.log(
            f"Scope:              {db_scope_ft:.2f} ft → {new_scope_ft:.2f} ft"
            f"  (Δ {new_scope_ft - db_scope_ft:+.2f} ft)"
        )
        log.log(
            f"Trigger line:       {db_trig_line_ft:.2f} ft → "
            f"{new_trig_line_ft:.2f} ft"
            f"  (Δ {new_trig_line_ft - db_trig_line_ft:+.2f} ft)"
        )
        log.log(
            f"Core length:        {db_core_length_ft:.2f} ft → "
            f"{new_core_length_ft:.2f} ft"
            f"  (Δ {new_core_length_ft - db_core_length_ft:+.2f} ft)"
        )
        log.log(
            f"Trigger core length: {db_tc_length_ft:.2f} ft → "
            f"{new_tc_length_ft:.2f} ft"
            f"  (Δ {new_tc_length_ft - db_tc_length_ft:+.2f} ft)"
        )
        if (self.alter_panel.get_num_pigs() !=
                int(effective_core_info.get('pig_weights') or 0)):
            log.log(
                "Number of pigs change detected — not yet implemented, ignored."
            )

        try:
            panel = self.calculate_panel

            ws_col = panel.get_weight_stand_col()
            rel_col = panel.get_release_col()
            trig_col = panel.get_trigger_col()

            if ws_col is None or rel_col is None:
                log.log(
                    "ERROR: Weight Stand and Release Device columns must be "
                    "set in the Calculate panel."
                )
                return

            # Build arrays (same interpolation as run_calculations)
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            rel_vals = (
                self.sensor_data.df[rel_col]
                .interpolate().ffill().bfill().values
            )
            trig_vals = None
            if (trig_col is not None
                    and trig_col in self.sensor_data.df.columns):
                trig_vals = (
                    self.sensor_data.df[trig_col]
                    .interpolate().ffill().bfill().values
                )

            # Apply optional Savitzky-Golay smoothing (same as Calculate)
            if panel.get_smoothing_enabled():
                sg_win, sg_poly = panel.get_sg_params()
                ws_vals = apply_savgol(ws_vals, sg_win, sg_poly)
                rel_vals = apply_savgol(rel_vals, sg_win, sg_poly)
                if trig_vals is not None:
                    trig_vals = apply_savgol(trig_vals, sg_win, sg_poly)

            timestamps_epoch = self.sensor_data.get_timestamps_epoch()

            # Apply trigger line length shift to WS and release
            delta_trig_m = (new_trig_line_ft - db_trig_line_ft) * FT_TO_M
            ws_mod = ws_vals - delta_trig_m
            rel_mod = rel_vals - delta_trig_m

            # Apply trigger core length shift to all three traces.
            # A longer trigger core fires the trip shallower (all sensors rise by Δ).
            # Seafloor stays constant because trace shift and length change cancel.
            delta_tc_m = (new_tc_length_ft - db_tc_length_ft) * FT_TO_M
            ws_mod = ws_mod - delta_tc_m
            rel_mod = rel_mod - delta_tc_m
            if trig_vals is not None:
                trig_vals = trig_vals - delta_tc_m

            # Determine which columns have altered traces for overlay display
            total_shift_m = delta_trig_m + delta_tc_m
            if total_shift_m != 0.0:
                overlay = {ws_col: ws_mod, rel_col: rel_mod}
                if trig_col is not None and trig_vals is not None:
                    overlay[trig_col] = trig_vals
                self.main_plot.add_smoothed_traces(
                    overlay, self.sensor_data.depth_columns,
                )
            else:
                self.main_plot.remove_smoothed_traces()

            # Resolve trip index (fixed — same as Calculate mode used)
            trip_idx = self._resolve_calc_trip_index()

            # Re-detect start_core with new scope on shifted arrays
            new_start_core_idx = None
            if trip_idx is not None:
                new_start_core_idx = detect_start_core(
                    ws_mod, rel_mod, new_scope_ft, trip_idx=trip_idx,
                )

            # Update start_core line on main plot
            x = self.sensor_data.get_timestamps_epoch()
            self.main_plot.remove_start_core_line()
            if new_start_core_idx is not None and 0 <= new_start_core_idx < len(x):
                self.main_plot.add_start_core_line(float(x[new_start_core_idx]))

            # Core length for piston computation — use altered value from panel
            core_ft = new_core_length_ft if new_core_length_ft > 0 else db_core_length_ft
            offset_constant = self.piston_panel.get_offset_constant()

            # Re-compute piston position
            altered_piston = None
            if new_start_core_idx is not None and core_ft > 0:
                altered_piston = compute_piston_position(
                    ws_mod, rel_mod,
                    new_scope_ft, core_ft,
                    new_start_core_idx,
                    offset_constant=offset_constant,
                )
                self.main_plot.update_piston_trace(altered_piston)

            # Metadata for calculate
            md = self.sensor_data.metadata
            trigger_core_length_ft = new_tc_length_ft if new_tc_length_ft > 0 else db_tc_length_ft
            core_length_ft = core_ft
            trigger_pen = self.alter_panel.get_trigger_pen()
            ws_len_m = self.calculate_panel.get_weight_stand_length_m()

            # Re-run calculations
            results = compute_calculations(
                weight_stand=ws_mod,
                release=rel_mod,
                timestamps_epoch=timestamps_epoch,
                trip_idx=trip_idx,
                start_core_idx=new_start_core_idx,
                piston=altered_piston,
                trigger_core=trig_vals,
                trigger_core_length_ft=trigger_core_length_ft,
                trigger_pen=trigger_pen,
                core_length_ft=core_length_ft,
                end_pen_idx=self._end_pen_idx,
                pullout_idx=self._pullout_idx,
                weight_stand_length_m=ws_len_m,
            )

            log.log(format_results(results))

            # Update geometry diagram
            self._update_calculation_plot(
                results, ws_mod, altered_piston, trip_idx,
                new_start_core_idx, core_ft,
                self._end_pen_idx, self._pullout_idx,
            )
            # Refresh start_pen / seafloor lines using the shifted WS array and altered core length
            self._update_start_pen_line(
                trip_idx, ws_override=ws_mod,
                core_length_ft_override=core_length_ft,
                tc_length_ft_override=trigger_core_length_ft,
                trig_override=trig_vals,
            )
            if self.main_window is not None:
                self.main_window.show_secondary_view('calculation')

        except Exception as exc:
            log.log(f"ERROR during estimation: {exc}")

    # ==================================================================
    # Piston Analysis Mode
    # ==================================================================

    def run_piston_analysis(self):
        """Run piston analysis over the core-opening interval and display results."""
        panel = self.piston_analysis_panel
        log = panel.log_widget if panel is not None else None

        def _err(msg):
            if log:
                log.log(f"ERROR: {msg}")
            self._show_warning(msg)

        if self.sensor_data is None:
            _err("No data loaded.")
            return
        if self._start_pen_idx is None:
            _err(
                "Start-penetration index not set.\n"
                "Run Calculate mode first (or drag the Start Pen line)."
            )
            return
        if self._pullout_idx is None:
            _err(
                "Pullout index not set.\n"
                "Run Calculate mode first (or drag the Pullout line)."
            )
            return
        if self._piston_values is None:
            _err(
                "No piston position data.\n"
                "Run Piston Position mode first."
            )
            return

        calc_panel = self.calculate_panel
        ws_col = calc_panel.get_weight_stand_col() if calc_panel else None
        if not ws_col or ws_col not in self.sensor_data.df.columns:
            _err("Weight-stand column not set or not found.")
            return

        # Resolve start_core_idx: prefer calc/piston-analysis mode drag value,
        # fall back to piston-position detected value, then None (→ start_pen).
        start_core_idx = (
            self._calc_start_core_idx
            if self._calc_start_core_idx is not None
            else self._piston_start_core_idx
        )

        # Validate ordering
        if start_core_idx is not None and start_core_idx > self._start_pen_idx:
            _err(
                f"start_core (index {start_core_idx}) is after start_pen "
                f"(index {self._start_pen_idx}).  Drag start_core to a "
                "position before or at start_pen and try again."
            )
            return

        try:
            ws_vals = (
                self.sensor_data.df[ws_col]
                .interpolate().ffill().bfill().values
            )
            ts = self.sensor_data.get_timestamps_epoch()
            piston_vals = self._piston_values

            seafloor = None
            if self._manual_seafloor is not None:
                seafloor = self._manual_seafloor
            elif self._last_calc_results is not None:
                sf = getattr(self._last_calc_results, 'seafloor', None)
                if sf is not None:
                    seafloor = float(sf)

            sg_window = panel.get_sg_window() if panel else 51
            sg_polyorder = panel.get_sg_polyorder() if panel else 3

            result = PistonAnalysisProcessor.compute_analysis(
                ws_vals=ws_vals,
                piston_vals=piston_vals,
                timestamps_epoch=ts,
                start_pen_idx=self._start_pen_idx,
                pullout_idx=self._pullout_idx,
                start_core_idx=start_core_idx,
                sg_window=sg_window,
                sg_polyorder=sg_polyorder,
                seafloor=seafloor,
            )

            if self.piston_analysis_view is not None:
                self.piston_analysis_view.plot(result)
            if self.main_window is not None:
                self.main_window.show_secondary_view('piston_analysis')

            n = len(result.core_depth)
            x = result.core_depth
            pre_pen_m = float(x[0]) if float(x[0]) < 0 else 0.0
            if log:
                log.log(
                    f"Piston analysis complete — {n} samples, "
                    f"core depth {float(x[0]):.2f} \u2013 {float(x[-1]):.2f} m "
                    f"(0 = start-pen), "
                    f"SG window={result.sg_window}"
                )
            if panel:
                status = (
                    f"Analyzed {n} samples. "
                    f"Range: {float(x[0]):.2f} – {float(x[-1]):.2f} m"
                )
                if pre_pen_m < 0:
                    status += f"  ({abs(pre_pen_m):.2f} m pre-penetration)"
                panel.update_status(status)

        except Exception as exc:
            _err(f"Piston analysis failed: {exc}")

    # ==================================================================
    # Restore from Database
    # ==================================================================

    def _on_restore_results(self) -> None:
        """Handle the 'Restore Results' toolbar action."""
        from ..persistence import results_io as _rio

        if self._loaded_core_id is None or self.store is None:
            self._show_warning(
                "No core loaded.\n"
                "Select a core from the project first."
            )
            return

        try:
            result_id = _rio.latest_result_id(self.store, self._loaded_core_id)
        except Exception as e:
            self._show_error("Restore Error", f"Could not query saved results:\n{e}")
            return

        if result_id is None:
            self._show_warning("No saved analysis results found for this core.")
            return

        self.restore_from_db(result_id)

    def restore_from_db(self, result_id: int) -> None:
        """Re-apply all analysis steps stored in an analysis_results row."""
        if self.store is None:
            self._show_error("Restore Error", "No project is open.")
            return

        from ..persistence import results_io as _rio

        row = _rio.fetch_result_by_id(self.store, result_id)
        if row is None:
            self._show_error(
                "Restore Error", f"Result #{result_id} not found in database."
            )
            return

        params = row.get('params') or {}
        restored: list[str] = []
        skipped: list[str] = []

        def log(msg: str):
            self._log_active(msg)

        log(f"Restoring analysis result #{result_id}…")

        # ── 1. Depth corrections ──────────────────────────────────────
        if 'depth_offset' in params:
            try:
                ok = self._restore_depth_corrections(params['depth_offset'], log)
                (restored if ok else skipped).append(
                    "depth corrections" if ok else "depth corrections (no-op)"
                )
            except Exception as e:
                log(f"  ERROR depth corrections: {e}")
                skipped.append(f"depth corrections ({e})")
        else:
            skipped.append("depth corrections (not saved)")

        # ── 2. Time corrections ───────────────────────────────────────
        if 'time_offset' in params:
            try:
                ok = self._restore_time_corrections(params['time_offset'], log)
                (restored if ok else skipped).append(
                    "time corrections" if ok else "time corrections (no-op)"
                )
            except Exception as e:
                log(f"  ERROR time corrections: {e}")
                skipped.append(f"time corrections ({e})")
        else:
            skipped.append("time corrections (not saved)")

        # ── 3. Trip ───────────────────────────────────────────────────
        trip_index = row.get('trip_index')
        trip_datetime = row.get('trip_datetime')
        if trip_index is not None and trip_datetime is not None:
            try:
                ok = self._restore_trip(int(trip_index), trip_datetime, log)
                (restored if ok else skipped).append("trip")
            except Exception as e:
                log(f"  ERROR trip restore: {e}")
                skipped.append(f"trip ({e})")
        else:
            skipped.append("trip (not saved)")

        # ── 3b. Winch alignment ───────────────────────────────────────
        if 'winch' in params and params['winch'].get('aligned'):
            try:
                ok = self._restore_winch(params['winch'], row, log)
                (restored if ok else skipped).append("winch alignment")
            except Exception as e:
                log(f"  ERROR winch restore: {e}")
                skipped.append(f"winch alignment ({e})")
        else:
            skipped.append("winch alignment (not saved)")

        # ── 4. Piston position ────────────────────────────────────────
        start_core_index = row.get('start_core_index')
        if 'piston' in params and start_core_index is not None:
            try:
                ok = self._restore_piston(
                    params['piston'], int(start_core_index), log
                )
                (restored if ok else skipped).append("piston position")
            except Exception as e:
                log(f"  ERROR piston restore: {e}")
                skipped.append(f"piston position ({e})")
        else:
            skipped.append("piston position (not saved)")

        # ── 5. Calculations ───────────────────────────────────────────
        if 'calc_inputs' in params:
            try:
                ok = self._restore_calculate(params['calc_inputs'], log)
                (restored if ok else skipped).append("calculations")
            except Exception as e:
                log(f"  ERROR calculations restore: {e}")
                skipped.append(f"calculations ({e})")
        else:
            skipped.append("calculations (not saved)")

        # Switch to Calculate mode to show the restored state
        if self.main_window is not None and restored:
            # set_mode is a no-op signal when already in that mode; always replot.
            if 'winch alignment' in restored:
                self.main_window.set_mode('Winch')
                self._plot_winch_mode()
            else:
                self.main_window.set_mode('Calculate')
                self._plot_calculate_mode()

        parts = []
        if restored:
            parts.append(f"Restored: {', '.join(restored)}")
        if skipped:
            parts.append(f"Skipped: {', '.join(skipped)}")
        summary = "Restore complete — " + " | ".join(parts)
        log(summary)
        if self.main_window:
            self.main_window.statusBar().showMessage(summary, 8000)

    # ------------------------------------------------------------------
    # Restore helpers (one per analysis stage)
    # ------------------------------------------------------------------

    def _restore_depth_corrections(self, depth_params: dict, log) -> bool:
        """Re-apply depth calibration and manual offsets from saved params."""
        if self.sensor_data is None or self.original_data is None:
            return False

        from ..domain.models.calibration import DepthCalibration

        calib_json = depth_params.get('calib_json')
        label_mapping = depth_params.get('label_mapping') or {}
        ref_sensor = depth_params.get('reference_sensor') or ''
        manual_offsets = depth_params.get('manual_offsets') or {}

        working = self.original_data.copy()
        applied_any = False

        # Reconstruct calibration and apply regression corrections
        if calib_json:
            try:
                self.calibration = DepthCalibration.from_dict(calib_json)
            except Exception as e:
                log(f"  Warning: could not reconstruct calibration: {e}")
                self.calibration = None

        if self.calibration is not None and label_mapping and ref_sensor:
            ref_col = label_mapping.get(ref_sensor)
            if ref_col and ref_col in working.df.columns:
                # All mapped labels except the reference are enabled targets
                enabled = [
                    lbl for lbl in label_mapping
                    if lbl != ref_sensor and label_mapping[lbl] in working.df.columns
                ]
                DepthCorrectionProcessor.apply_calibration(
                    working, self.calibration, ref_col, label_mapping, enabled
                )
                log(f"  Depth regression corrections applied ({len(enabled)} sensors)")
                applied_any = True

        if manual_offsets:
            applied = DepthCorrectionProcessor.apply_manual_offsets(working, manual_offsets)
            if applied:
                log(f"  Manual depth offsets applied: {len(applied)} sensors")
                applied_any = True

        self.sensor_data = working
        self.main_plot.set_sensor_data(self.sensor_data)
        self.main_plot.plot_depths(self.sensor_data, title=self.sensor_data.core_title or '')

        # Update panel UI to reflect restored state (best effort)
        if self.depth_panel is not None:
            if self.calibration is not None and label_mapping:
                self.depth_panel.setup_calibration_mapping(
                    list(label_mapping.keys()), self.sensor_data.depth_columns
                )
                self.depth_panel.set_calibration_mapping(label_mapping)
                if ref_sensor:
                    self.depth_panel.set_ref_sensor(ref_sensor)
            if manual_offsets:
                self.depth_panel.setup_manual_offsets(self.sensor_data.depth_columns)
                self.depth_panel.set_manual_offsets(manual_offsets)

        return applied_any

    def _restore_time_corrections(self, time_params: dict, log) -> bool:
        """Re-apply time corrections from saved params."""
        if self.sensor_data is None:
            return False

        offsets_data = time_params.get('offsets') or []
        manual_offsets = time_params.get('manual_offsets') or {}
        ref_col = time_params.get('reference_col')

        # Update panel UI
        if self.time_panel is not None:
            if ref_col:
                self.time_panel.set_ref_col(ref_col)

        if offsets_data:
            # Reconstruct TimeOffsetResult objects and apply via existing method
            from ..domain.models.analysis_result import TimeOffsetResult
            self.time_offset_results = [
                TimeOffsetResult(
                    sensor_column=item['sensor_col'],
                    offset_seconds=float(item['offset_seconds'] or 0),
                    rms_value=float(item.get('rms_value') or 0),
                    is_reference=bool(item.get('is_reference', False)),
                )
                for item in offsets_data
            ]
            self.apply_time_corrections()
            log(f"  Time corrections applied ({len(offsets_data)} sensors)")
            return True

        if any(v != 0 for v in manual_offsets.values()):
            if self.time_panel is not None:
                self.time_panel.set_manual_offsets(manual_offsets)
            self.apply_manual_time_corrections()
            log("  Manual time corrections applied")
            return True

        return False

    def _restore_trip(self, trip_index: int, trip_datetime, log) -> bool:
        """Restore trip detection state from saved flat columns."""
        if self.sensor_data is None:
            return False

        import numpy as np
        from ..domain.processing.trip_detection import TripDetectionResult

        # The saved index is exact, the saved datetime may not be. Calculate and
        # Piston modes re-derive the trip index from their panel time widget, so
        # that widget has to agree with trip_index to the sample or the restored
        # trip lands on a neighbouring sample.
        ts = pd.Timestamp(trip_datetime)
        dt_col = self.sensor_data.datetime_col
        if (dt_col in self.sensor_data.df.columns
                and 0 <= trip_index < len(self.sensor_data.df)):
            sample_ts = self.sensor_data.df[dt_col].iloc[trip_index]
            if pd.notna(sample_ts):
                ts = pd.Timestamp(sample_ts)

        n = self.sensor_data.row_count
        depth_cols = self.sensor_data.depth_columns

        self.trip_detection_result = TripDetectionResult(
            trip_index=trip_index,
            trip_datetime=ts,
            confidence=1.0,
            derivative_order=1,
            derivative_label='Restored from DB',
            threshold=0.0,
            derivative_profiles={col: np.zeros(n) for col in depth_cols},
            divergence=np.zeros(n),
            depth_columns=depth_cols,
        )

        ts_str = str(ts)
        if self.piston_panel is not None:
            self.piston_panel.set_trip_time(ts_str, source='DB restore')
        if self.calculate_panel is not None:
            self.calculate_panel.set_trip_time(ts_str, source='DB restore')

        self.main_plot.add_trip_line(trip_index)
        log(f"  Trip restored: index {trip_index}, time {ts.strftime('%Y-%m-%d %H:%M:%S')}")
        return True

    def _restore_winch(self, winch_params: dict, row: dict, log) -> bool:
        """Restore aligned winch data from saved flat columns and params."""
        if not winch_params.get('aligned'):
            return False

        file_ids = winch_params.get('winch_file_ids') or []
        if not file_ids:
            log('  Winch alignment: skipped (no winch_file_ids)')
            return False

        df, names = self._winch_loader.load_winch_files_concat(file_ids)
        if df is None or df.empty:
            log('  Winch alignment: skipped (could not reload winch files)')
            return False

        trip_idx = row.get('winch_trip_index')
        if trip_idx is None:
            trip_idx = winch_params.get('trip_index')
        if trip_idx is None:
            log('  Winch alignment: skipped (no trip index)')
            return False
        trip_idx = int(trip_idx)

        offset_sec = row.get('winch_time_offset_sec')
        if offset_sec is None:
            offset_sec = winch_params.get('time_offset_sec')
        offset_sec = float(offset_sec or 0.0)

        self._winch_df_original = df.copy()
        self._winch_df = df.copy()
        if offset_sec != 0.0:
            self._winch_df['datetime'] = (
                self._winch_df['datetime'] + pd.Timedelta(seconds=offset_sec)
            )

        self._winch_file_ids = [int(i) for i in file_ids]
        self._winch_file_names = names or winch_params.get('winch_file_names') or []
        self._winch_load_mode = winch_params.get('load_mode') or 'manual'
        self._winch_trip_idx = trip_idx
        self._winch_time_offset_sec = offset_sec
        self._winch_aligned = True

        if self.winch_panel is not None:
            panel = self.winch_panel
            detection = winch_params.get('detection') or {}
            display = winch_params.get('display') or {}

            panel.edge_buffer_spin.setValue(
                int(detection.get('edge_buffer') or panel.get_edge_buffer())
            )
            panel.drop_threshold_spin.setValue(
                float(detection.get('drop_threshold') or panel.get_drop_threshold())
            )

            panel.use_manual_radio.blockSignals(True)
            panel.use_auto_radio.blockSignals(True)
            panel.use_manual_radio.setChecked(self._winch_load_mode == 'manual')
            panel.use_auto_radio.setChecked(self._winch_load_mode != 'manual')
            panel.use_manual_radio.blockSignals(False)
            panel.use_auto_radio.blockSignals(False)
            panel.winch_file_list.setEnabled(self._winch_load_mode == 'manual')

            params = get_winch_parameters(self._winch_df)
            panel.set_parameters(params)

            col1 = display.get('window1_column') or detection.get('column')
            if col1 and col1 in params:
                panel.column1_combo.setCurrentText(col1)

            show_second = bool(display.get('show_second_window'))
            panel.second_window_check.setChecked(show_second)
            col2 = display.get('window2_column')
            if show_second and col2 and col2 in params:
                panel.column2_combo.setCurrentText(col2)

            trip_dt = self._winch_df_original['datetime'].iloc[trip_idx]
            panel.set_winch_trip_status(
                f'Winch trip: index {trip_idx}, {trip_dt}  (restored)'
            )
            panel.set_alignment_status(
                f'Alignment: offset {offset_sec:+.3f} s applied (restored)'
            )

        search_start = detection.get('search_start')
        search_end = detection.get('search_end')

        self._update_winch_plot()

        if self.winch_plot_view is not None and search_start and search_end:
            try:
                self.winch_plot_view.set_search_region_epochs(
                    timestamp_to_epoch(search_start),
                    timestamp_to_epoch(search_end),
                )
                panel.show_search_region_check.blockSignals(True)
                panel.show_search_region_check.setChecked(True)
                panel.show_search_region_check.blockSignals(False)
            except Exception as exc:
                log(f'  Winch search window restore warning: {exc}')
        else:
            self._sync_winch_search_region_visibility()

        if self.winch_plot_view is not None and self._winch_trip_idx is not None:
            self.winch_plot_view.add_winch_trip_line(self._winch_trip_idx)

        self._update_winch_sensor_trip_status()
        log(
            f'  Winch alignment restored: {len(self._winch_file_ids)} file(s), '
            f'trip index {trip_idx}, offset {offset_sec:+.3f} s'
        )
        return True

    def _restore_piston(self, piston_params: dict, start_core_index: int, log) -> bool:
        """Restore piston position state and re-compute the piston trace."""
        if self.sensor_data is None:
            return False

        ws_col = piston_params.get('weight_stand_col')
        rel_col = piston_params.get('release_col')
        scope_ft = float(piston_params.get('scope_ft') or 0)
        core_ft = float(piston_params.get('core_length_ft') or 0)
        offset_constant = float(piston_params.get('offset_constant_m') or 1.25)

        if not ws_col or not rel_col or scope_ft <= 0 or core_ft <= 0:
            log("  Piston position: skipped (missing parameters)")
            return False

        if (ws_col not in self.sensor_data.df.columns
                or rel_col not in self.sensor_data.df.columns):
            log("  Piston position: skipped (saved columns not found in data)")
            return False

        # Update panel UI
        if self.piston_panel is not None:
            self.piston_panel.set_parameters_from_metadata(
                {'scope': scope_ft, 'core_length': core_ft}
            )
            self.piston_panel.set_offset_constant(offset_constant)

        self._piston_start_core_idx = start_core_index
        ws_vals = (
            self.sensor_data.df[ws_col].interpolate().ffill().bfill().values
        )
        rel_vals = (
            self.sensor_data.df[rel_col].interpolate().ffill().bfill().values
        )
        self._plot_piston(ws_vals, rel_vals, scope_ft, core_ft,
                          start_core_index, offset_constant)
        log(f"  Piston position restored: start_core index {start_core_index}")
        return True

    def _restore_calculate(self, calc_params: dict, log) -> bool:
        """Restore calculate-mode state (indices, seafloor) and re-run calculations."""
        if self.sensor_data is None:
            return False

        # Restore scalar state
        end_pen = calc_params.get('end_pen_idx')
        pullout = calc_params.get('pullout_idx')
        sc = calc_params.get('start_core_idx')
        sf = calc_params.get('seafloor_manual')
        sp = calc_params.get('start_pen_idx')
        sp_manual = calc_params.get('start_pen_manual')

        if end_pen is not None:
            self._end_pen_idx = int(end_pen)
        if pullout is not None:
            self._pullout_idx = int(pullout)
        if sc is not None:
            self._calc_start_core_idx = int(sc)
        if sf is not None:
            self._manual_seafloor = float(sf)
            if self.calculate_panel is not None:
                self.calculate_panel.show_seafloor_override(self._manual_seafloor)
        if sp is not None:
            self._start_pen_idx = int(sp)
        # Only a dragged start_pen is pinned on restore; an auto-computed one
        # is left to recompute so it tracks the restored inputs.
        if sp_manual is not None:
            self._manual_start_pen = int(sp_manual)

        # Restore panel column picks before re-running; without them
        # _update_start_pen_line cannot draw the restored start_pen line.
        if self.calculate_panel is not None and self.sensor_data is not None:
            ws_col = calc_params.get('weight_stand_col')
            rel_col = calc_params.get('release_col')
            trig_col = calc_params.get('trigger_col')
            if ws_col or rel_col or trig_col:
                columns_and_names = [
                    (col, SensorData.get_location_name(col))
                    for col in self.sensor_data.depth_columns
                ]
                self.calculate_panel.populate_sensor_combos(
                    columns_and_names, ws_col, rel_col, trig_col,
                )

        # Restore panel numeric params
        if self.calculate_panel is not None:
            trigger_pen = calc_params.get('trigger_pen_m')
            sg_w = calc_params.get('sg_window')
            sg_p = calc_params.get('sg_poly')
            if trigger_pen is not None:
                self.calculate_panel.set_trigger_pen(float(trigger_pen))
            ws_len = calc_params.get("weight_stand_length_m")
            if ws_len is not None:
                self.calculate_panel.set_weight_stand_length_m(float(ws_len))
            if sg_w is not None and sg_p is not None:
                self.calculate_panel.set_sg_params(int(sg_w), int(sg_p))

        try:
            self.run_calculations()
            log("  Calculations re-run successfully")
        except Exception as e:
            log(f"  Warning: calculations re-run failed: {e}")

        return True

    # ==================================================================
    # Helpers
    # ==================================================================

    def _update_all_panels_file_info(self):
        """Update file info on all panels after data load."""
        if self.sensor_data is None:
            return

        sd = self.sensor_data
        tr = sd.time_range
        dr = sd.depth_range
        time_str = f"{tr[0]} to {tr[1]}" if tr else ''
        depth_str = f"{dr[0]:.1f}m to {dr[1]:.1f}m" if dr else ''

        self.view_panel.update_file_info(
            sd.source_file, sd.num_sensors, sd.row_count,
            time_str, depth_str, sd.core_title,
        )
        self.depth_panel.update_file_info(
            sd.source_file, sd.num_sensors, sd.row_count, sd.core_title,
        )
        self.time_panel.update_file_info(
            sd.source_file, sd.num_sensors, sd.row_count,
        )
        if self.trip_panel is not None:
            self.trip_panel.update_file_info(
                sd.source_file, sd.num_sensors, sd.row_count,
            )

        # Set up manual offsets on the depth panel
        self.depth_panel.setup_manual_offsets(sd.depth_columns)
        self.depth_panel.log_widget.log(
            f"Found {len(sd.depth_columns)} depth columns:"
        )
        for col in sd.depth_columns:
            short = SensorData.get_short_name(col)
            self.depth_panel.log_widget.log(f"  {short}")

        # Populate calibration mapping if calibration already loaded
        if self.calibration is not None:
            self.depth_panel.setup_calibration_mapping(
                self.calibration.sensor_labels, sd.depth_columns,
            )

        # Populate time offset ref sensor combo and manual offset spinboxes
        self.time_panel.populate_ref_sensor_combo(sd.depth_columns)
        self.time_panel.setup_manual_offsets(sd.depth_columns)

        # Update piston panel
        if self.piston_panel is not None:
            self.piston_panel.update_file_info(
                sd.source_file, sd.num_sensors, sd.row_count,
                sd.core_title,
            )
            # Populate sensor combos with (column, display_name) tuples
            columns_and_names = [
                (col, SensorData.get_location_name(col))
                for col in sd.depth_columns
            ]
            ws_col = sd.find_column_by_location('Weight Stand')
            rel_col = sd.find_column_by_location('Release')
            self.piston_panel.populate_sensor_combos(
                columns_and_names, ws_col, rel_col,
            )
            # Pre-fill parameters from metadata
            self.piston_panel.set_parameters_from_metadata(sd.metadata)

        # Update calculate panel
        if self.calculate_panel is not None:
            self.calculate_panel.update_file_info(
                sd.source_file, sd.num_sensors, sd.row_count,
                sd.core_title,
            )
            columns_and_names = [
                (col, SensorData.get_location_name(col))
                for col in sd.depth_columns
            ]
            ws_col = sd.find_column_by_location('Weight Stand')
            rel_col = sd.find_column_by_location('Release')
            trig_col = sd.find_column_by_location('Trigger')
            self.calculate_panel.populate_sensor_combos(
                columns_and_names, ws_col, rel_col, trig_col,
            )
            self.calculate_panel.set_parameters_from_metadata(sd.metadata)

        # Update piston analysis panel
        if self.piston_analysis_panel is not None:
            self.piston_analysis_panel.update_file_info(
                f"{sd.source_file}  ({sd.core_title})"
                if sd.core_title else sd.source_file
            )

    def _log_active(self, msg: str):
        """Log to the currently active panel."""
        mode = (
            self.main_window.get_current_mode() if self.main_window else None
        )
        if mode == 'View Data':
            self.view_panel.log_widget.log(msg)
        elif mode == 'Depth Offset':
            self.depth_panel.log_widget.log(msg)
        elif mode == 'Time Offset':
            self.time_panel.log_widget.log(msg)
        elif mode == 'Create Calibration':
            self.calibration_panel.log_widget.log(msg)
        elif mode == 'Trip Detector':
            self.trip_panel.log_widget.log(msg)
        elif mode == 'Piston Position':
            self.piston_panel.log_widget.log(msg)
        elif mode == 'Calculate':
            self.calculate_panel.log_widget.log(msg)
        elif mode == 'Piston Analysis' and self.piston_analysis_panel is not None:
            self.piston_analysis_panel.log_widget.log(msg)
        elif mode == 'Predict' and self.predict_panel is not None:
            self.predict_panel.log.log(msg)

    # ==================================================================
    # Predict mode
    # ==================================================================

    def _prompt_load_recoil_calibration(self) -> None:
        last_path = self._predict_settings.value("predict/last_calibration_path", "")
        start_dir = str(Path(last_path).parent) if last_path else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self.main_window,
            "Load Recoil Calibration",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if file_path:
            self.load_recoil_calibration(file_path)

    def load_recoil_calibration(self, file_path: str) -> None:
        try:
            self.recoil_calibration = RecoilCalibrationIO.load(file_path)
            self._predict_settings.setValue("predict/last_calibration_path", file_path)
            filename = Path(file_path).name
            if self.predict_panel is not None:
                self.predict_panel.update_calibration_info(
                    filename,
                    self.recoil_calibration.summary_lines(),
                )
            self._log_predict(f"Recoil calibration loaded: {filename}")
        except Exception as e:
            self._show_error("Calibration Error", str(e))
            self._log_predict(f"ERROR loading recoil calibration: {e}")

    def run_predict(self) -> None:
        if self.predict_panel is None or self.predict_plot_view is None:
            return
        if self.recoil_calibration is None:
            self._show_warning("Load a recoil calibration JSON file first.")
            self._prompt_load_recoil_calibration()
            return

        log = self.predict_panel.log
        try:
            inputs = self.predict_panel.get_inputs()
            if inputs.v0_min_ms > inputs.v0_max_ms:
                self._show_error("Invalid inputs", "v0 min must be <= v0 max.")
                return

            cal = self.recoil_calibration.body
            for warning in training_warnings(inputs, cal):
                log.log(f"WARNING: {warning}")

            log.log("Running forward prediction…")
            result = run_prediction(inputs, cal)
            self._last_predict_result = result

            log.log(
                f"Seafloor estimate: {result['seafloor_m']:.2f} m "
                f"(rel. corer trip {result['seafloor_relative_m']:+.2f} m)"
            )
            log.log(
                f"Corer depth at trip: {result['corer_depth_at_trip_m']:.2f} m | "
                f"Release depth at trip: {result['release_depth_at_trip_m']:.2f} m"
            )

            summary = result["event_summary"]
            for _, row in summary.iterrows():
                curve = row["curve_type"]
                log.log(
                    f"{curve}: start_core t={row['start_core_time_median_s']:.3f}s, "
                    f"piston alt={row['piston_alt_start_core_median_m']:.2f} m | "
                    f"start_pen t={row['start_pen_time_median_s']:.3f}s, "
                    f"piston alt={row['piston_alt_start_pen_median_m']:.2f} m"
                )

            self._refresh_predict_plot()
            log.log("Prediction complete.")
        except Exception as e:
            self._show_error("Prediction Error", str(e))
            log.log(f"ERROR: {e}")

    def _refresh_predict_plot(self) -> None:
        if (
            self.predict_panel is None
            or self.predict_plot_view is None
            or self._last_predict_result is None
        ):
            return
        curves = self.predict_panel.get_selected_curves()
        overlay = None
        if self.predict_panel.overlay_actual_enabled():
            try:
                overlay = self._build_predict_overlay(self._last_predict_result)
                curves = [curves[0]] if curves else curves
            except Exception as e:
                self._log_predict(f"Overlay skipped: {e}")
        self.predict_plot_view.show_prediction(
            self._last_predict_result,
            curves,
            self.predict_panel.show_piston(),
            show_trigger=self.predict_panel.show_trigger(),
            overlay=overlay,
        )
        self._update_predict_trigger_line_display(overlay)

    def _on_predict_overlay_changed(self) -> None:
        if self._last_predict_result is not None:
            self._refresh_predict_plot()
        else:
            self._update_predict_trigger_line_display()

    def _populate_predict_panel_from_session(self) -> None:
        if self.predict_panel is None or self.sensor_data is None:
            return
        md = dict(self.sensor_data.metadata or {})
        if self._loaded_core_info:
            for key in (
                "scope", "core_length", "trigger_core_length",
                "trigger_line_length",
            ):
                val = self._loaded_core_info.get(key)
                if val is not None:
                    md[key] = val
        self.predict_panel.populate_from_metadata(md)
        self._sync_trip_to_calculate_panel()

    def _plot_predict_mode(self) -> None:
        """Main depth plot with draggable trip line for overlay alignment."""
        if self.sensor_data is None:
            return
        self.plot_depths()
        trip_idx = self._resolve_calc_trip_index()
        if trip_idx is not None:
            self.main_plot.add_trip_line(trip_idx)
        if self._calc_start_core_idx is not None:
            self.main_plot.add_start_core_line(self._calc_start_core_idx)
        if self._piston_values is not None:
            x = self.sensor_data.get_timestamps_epoch()
            self.main_plot.add_piston_trace(x, self._piston_values)

    def _build_predict_overlay(self, result: dict):
        if self.sensor_data is None or self.calculate_panel is None:
            raise ValueError("Load sensor data and configure Calculate sensors first")
        ws_col = self.calculate_panel.get_weight_stand_col()
        rel_col = self.calculate_panel.get_release_col()
        trig_col = self.calculate_panel.get_trigger_col()
        if ws_col is None or rel_col is None:
            raise ValueError("Select weight stand and release sensors in Calculate mode")

        trip_idx = self._resolve_calc_trip_index()
        if trip_idx is None:
            raise ValueError("Set trip time (Calculate panel or trip detector)")

        ws_vals = (
            self.sensor_data.df[ws_col]
            .interpolate().ffill().bfill().values
        )
        rel_vals = (
            self.sensor_data.df[rel_col]
            .interpolate().ffill().bfill().values
        )
        trig_vals = None
        if trig_col and trig_col in self.sensor_data.df.columns:
            trig_vals = (
                self.sensor_data.df[trig_col]
                .interpolate().ffill().bfill().values
            )

        panel = self.calculate_panel
        if panel.get_smoothing_enabled():
            sg_win, sg_poly = panel.get_sg_params()
            ws_vals = apply_savgol(ws_vals, sg_win, sg_poly)
            rel_vals = apply_savgol(rel_vals, sg_win, sg_poly)
            if trig_vals is not None:
                trig_vals = apply_savgol(trig_vals, sg_win, sg_poly)

        piston = self._piston_values
        if piston is not None and panel.get_smoothing_enabled():
            sg_win, sg_poly = panel.get_sg_params()
            piston = apply_savgol(piston, sg_win, sg_poly)

        md = self.sensor_data.metadata or {}
        planned = md.get("trigger_line_length")
        if self._loaded_core_info and self._loaded_core_info.get("trigger_line_length"):
            planned = self._loaded_core_info.get("trigger_line_length")

        inputs = result["inputs"]
        return build_actual_overlay(
            weight_stand=ws_vals,
            release=rel_vals,
            timestamps_epoch=self.sensor_data.get_timestamps_epoch(),
            trip_idx=trip_idx,
            time_grid=result["time"],
            release_above_corer_m=inputs.release_above_corer_m,
            piston=piston,
            trigger_core=trig_vals,
            planned_trigger_line_ft=float(planned) if planned is not None else None,
        )

    def _update_predict_trigger_line_display(self, overlay=None) -> None:
        if self.predict_panel is None:
            return
        model_ft = None
        if self._last_predict_result is not None:
            model_ft = float(self._last_predict_result["inputs"].trigger_line_length_ft)
        else:
            model_ft = self.predict_panel.get_inputs().trigger_line_length_ft

        effective_ft = None
        planned_ft = None
        if overlay is not None:
            effective_ft = overlay.effective_trigger_line_ft
            planned_ft = overlay.planned_trigger_line_ft
        elif self._last_calc_results is not None:
            effective_ft = self._last_calc_results.eff_trig_line_ft
        if planned_ft is None and self.sensor_data is not None:
            md = self.sensor_data.metadata or {}
            planned = md.get("trigger_line_length")
            if planned is None and self._loaded_core_info:
                planned = self._loaded_core_info.get("trigger_line_length")
            if planned is not None:
                planned_ft = float(planned)

        self.predict_panel.update_trigger_line_comparison(
            planned_ft, effective_ft, model_ft,
        )

    def _log_predict(self, msg: str) -> None:
        if self.predict_panel is not None:
            self.predict_panel.log.log(msg)

    def _show_error(self, title: str, msg: str):
        if self.main_window:
            QMessageBox.critical(self.main_window, title, msg)

    def _show_warning(self, msg: str):
        if self.main_window:
            QMessageBox.warning(self.main_window, "Warning", msg)
