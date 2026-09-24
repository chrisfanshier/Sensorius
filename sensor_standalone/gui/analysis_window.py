"""
MainWindow - The top-level application window.

Layout:
    ┌──────────────────────────────────────────────────────────┐
    │ [Mode ▾] [Cruise ▾] [Core ▾] [Load CSV…] [About]       │  ← Toolbar
    ├─────────────────┬────────────────────────────────────────┤
    │                 │                                        │
    │  Control Panel  │  Main Plot                             │
    │  (QStacked)     │                                        │
    │                 │                                        │
    │                 ├────────────────────────────────────────┤
    │                 │  Secondary View                        │
    │                 │  (velocity / stats)                    │
    │                 │                                        │
    └─────────────────┴────────────────────────────────────────┘
    │  Status bar                                              │
    └──────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QComboBox, QSplitter, QStackedWidget,
    QToolBar, QLabel, QFileDialog, QSizePolicy, QVBoxLayout,
    QMessageBox,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction

from ..gui.views.sensor_plot_view import SensorPlotView
from ..gui.views.velocity_plot_view import HeavePlotView
from ..gui.views.statistics_table import StatisticsTableView
from ..gui.views.trip_plot_view import TripPlotView
from ..gui.views.calculation_plot_view import CalculationPlotView
from ..gui.views.calibration_plot_view import CalibrationPlotView
from ..gui.views.piston_analysis_view import PistonAnalysisView
from ..gui.views.winch_plot_view import WinchPlotView
from ..gui.views.predict_plot_view import PredictPlotView
from ..gui.panels.view_data_panel import ViewDataPanel
from ..gui.panels.depth_offset_panel import DepthOffsetPanel
from ..gui.panels.time_offset_panel import TimeOffsetPanel
from ..gui.panels.create_calibration_panel import CreateCalibrationPanel
from ..gui.panels.trip_detector_panel import TripDetectorPanel
from ..gui.panels.piston_position_panel import PistonPositionPanel
from ..gui.panels.calculate_panel import CalculatePanel
from ..gui.panels.alter_panel import AlterPanel
from ..gui.panels.piston_analysis_panel import PistonAnalysisPanel
from ..gui.panels.winch_panel import WinchPanel
from ..gui.panels.predict_panel import PredictPanel
from ..controllers.analysis_controller import AnalysisController

MODES = ['View Data', 'Depth Offset', 'Time Offset', 'Create Calibration',
         'Trip Detector', 'Piston Position', 'Winch', 'Calculate', 'Alter',
         'Piston Analysis', 'Predict']


class AnalysisWindow(QMainWindow):
    """Sensorius analysis UI — cruise/core selectors and 10 analysis modes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sensorius")
        self.resize(1600, 1000)

        self.store = None

        # Controller
        self.controller = AnalysisController()
        self.controller.main_window = self

        # Database dropdown state
        self._cruises: list[dict] = []
        self._cores: list[dict] = []

        self._build_toolbar()
        self._build_central()
        self._build_status_bar()

        # Wire everything
        self.controller.connect_signals()

        # Set initial mode
        self.mode_combo.setCurrentIndex(0)
        self._on_mode_changed(MODES[0])

    def set_store(self, store):
        """Attach project store and refresh cruise/core lists."""
        self.store = store
        self.controller.set_store(store)
        self._populate_cruises()

    # ==================================================================
    # Construction
    # ==================================================================

    def _build_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel("  Mode: "))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.setMinimumWidth(200)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self.mode_combo)

        toolbar.addSeparator()

        # ── Database selectors ──
        toolbar.addWidget(QLabel("  Cruise: "))
        self.cruise_combo = QComboBox()
        self.cruise_combo.setMinimumWidth(220)
        self.cruise_combo.addItem("Select cruise…")
        self.cruise_combo.currentIndexChanged.connect(self._on_cruise_changed)
        toolbar.addWidget(self.cruise_combo)

        toolbar.addWidget(QLabel("  Core: "))
        self.core_combo = QComboBox()
        self.core_combo.setMinimumWidth(220)
        self.core_combo.addItem("Select core…")
        self.core_combo.setEnabled(False)
        self.core_combo.currentIndexChanged.connect(self._on_core_changed)
        toolbar.addWidget(self.core_combo)

        toolbar.addSeparator()

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        toolbar.addAction(about_action)

        toolbar.addSeparator()

        self.save_all_action = QAction("💾 Save All to Project", self)
        self.save_all_action.setToolTip(
            "Save all analysis results to the project database "
            "(depth offset, time offset, trip, piston, calculations)."
        )
        toolbar.addAction(self.save_all_action)

        self.restore_action = QAction("📥 Restore Results", self)
        self.restore_action.setToolTip(
            "Restore previously saved analysis results for this core "
            "(depth/time corrections, trip, piston, calculations).\n"
            "Only available when a core is loaded from the project."
        )
        self.restore_action.setEnabled(False)
        toolbar.addAction(self.restore_action)

    def _build_central(self):
        # -- Control panels (left) --
        self.panel_stack = QStackedWidget()

        self.view_panel = ViewDataPanel()
        self.depth_panel = DepthOffsetPanel()
        self.time_panel = TimeOffsetPanel()
        self.calibration_panel = CreateCalibrationPanel()
        self.trip_panel = TripDetectorPanel()
        self.piston_panel = PistonPositionPanel()
        self.calculate_panel = CalculatePanel()

        self.panel_stack.addWidget(self.view_panel)      # 0
        self.panel_stack.addWidget(self.depth_panel)      # 1
        self.panel_stack.addWidget(self.time_panel)       # 2
        self.panel_stack.addWidget(self.calibration_panel) # 3
        self.alter_panel = AlterPanel()

        self.panel_stack.addWidget(self.trip_panel)       # 4
        self.panel_stack.addWidget(self.piston_panel)     # 5

        self.winch_panel = WinchPanel()
        self.panel_stack.addWidget(self.winch_panel)      # 6

        self.panel_stack.addWidget(self.calculate_panel)  # 7
        self.panel_stack.addWidget(self.alter_panel)      # 8

        self.piston_analysis_panel = PistonAnalysisPanel()
        self.panel_stack.addWidget(self.piston_analysis_panel)  # 9

        self.predict_panel = PredictPanel()
        self.panel_stack.addWidget(self.predict_panel)  # 10

        self.panel_stack.setMinimumWidth(400)
        self.panel_stack.setMaximumWidth(550)

        # -- Main plot --
        self.main_plot = SensorPlotView()

        # -- Secondary views (bottom-right) --
        self.heave_plot = HeavePlotView()
        self.statistics_table = StatisticsTableView()
        self.trip_plot = TripPlotView()
        self.calculation_plot = CalculationPlotView()
        self.calibration_plot = CalibrationPlotView()

        self.secondary_stack = QStackedWidget()
        self.secondary_stack.addWidget(self.heave_plot)         # 0
        self.secondary_stack.addWidget(self.statistics_table)   # 1
        self.secondary_stack.addWidget(self.trip_plot)          # 2
        self.secondary_stack.addWidget(self.calculation_plot)   # 3
        self.secondary_stack.addWidget(self.calibration_plot)   # 4

        self.piston_analysis_view = PistonAnalysisView()
        self.secondary_stack.addWidget(self.piston_analysis_view)  # 5

        self.winch_plot_view = WinchPlotView()
        self.secondary_stack.addWidget(self.winch_plot_view)       # 6

        self.predict_plot_view = PredictPlotView()
        self.secondary_stack.addWidget(self.predict_plot_view)     # 7
        self.secondary_stack.setVisible(False)

        # -- Right splitter (main plot + secondary) --
        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.addWidget(self.main_plot)
        self.right_splitter.addWidget(self.secondary_stack)
        self.right_splitter.setStretchFactor(0, 3)
        self.right_splitter.setStretchFactor(1, 1)
        self.right_splitter.setSizes([750, 250])

        # -- Main splitter (panels + plots) --
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self.panel_stack)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)

        self.setCentralWidget(self.main_splitter)

        # -- Assign to controller --
        self.controller.main_plot = self.main_plot
        self.controller.heave_plot = self.heave_plot
        self.controller.statistics_table = self.statistics_table
        self.controller.trip_plot = self.trip_plot
        self.controller.calculation_plot = self.calculation_plot
        self.controller.calibration_plot = self.calibration_plot
        self.controller.view_panel = self.view_panel
        self.controller.depth_panel = self.depth_panel
        self.controller.time_panel = self.time_panel
        self.controller.calibration_panel = self.calibration_panel
        self.controller.trip_panel = self.trip_panel
        self.controller.piston_panel = self.piston_panel
        self.controller.calculate_panel = self.calculate_panel
        self.controller.alter_panel = self.alter_panel
        self.controller.piston_analysis_panel = self.piston_analysis_panel
        self.controller.piston_analysis_view = self.piston_analysis_view
        self.controller.winch_panel = self.winch_panel
        self.controller.winch_plot_view = self.winch_plot_view
        self.controller.predict_panel = self.predict_panel
        self.controller.predict_plot_view = self.predict_plot_view

    def _build_status_bar(self):
        self.statusBar().showMessage("Ready")

    # ==================================================================
    # Mode management
    # ==================================================================

    def _on_mode_changed(self, mode_name: str):
        idx = MODES.index(mode_name) if mode_name in MODES else 0
        self.panel_stack.setCurrentIndex(idx)
        self.controller.on_mode_changed(mode_name)
        self.statusBar().showMessage(f"Mode: {mode_name}")

    def set_mode(self, mode_name: str) -> None:
        """Switch to *mode_name* programmatically (same as user picking from combo)."""
        if mode_name in MODES:
            self.mode_combo.setCurrentText(mode_name)

    def get_current_mode(self) -> str:
        return self.mode_combo.currentText()

    def get_selected_cruise_id(self) -> int | None:
        """Return cruise_id for the toolbar cruise selection, or None."""
        idx = self.cruise_combo.currentIndex()
        if idx <= 0 or idx > len(self._cruises):
            return None
        return self._cruises[idx - 1]['cruise_id']

    def get_selected_core_info(self) -> dict | None:
        """Return core info dict for the toolbar core selection, or None."""
        idx = self.core_combo.currentIndex()
        if idx <= 0 or idx > len(self._cores):
            return None
        return self._cores[idx - 1]

    def show_secondary_view(self, view_type: str):
        """Show the secondary view area (velocity, statistics, or trip)."""
        if view_type == 'heave':
            self.secondary_stack.setCurrentIndex(0)
        elif view_type == 'statistics':
            self.secondary_stack.setCurrentIndex(1)
        elif view_type == 'trip':
            self.secondary_stack.setCurrentIndex(2)
        elif view_type == 'calculation':
            self.secondary_stack.setCurrentIndex(3)
        elif view_type == 'calibration_plot':
            self.secondary_stack.setCurrentIndex(4)
        elif view_type == 'piston_analysis':
            self.secondary_stack.setCurrentIndex(5)
        elif view_type == 'winch':
            self.secondary_stack.setCurrentIndex(6)
        elif view_type == 'predict':
            self.secondary_stack.setCurrentIndex(7)
        self.secondary_stack.setVisible(True)
        self._ensure_secondary_pane_height()

    def _ensure_secondary_pane_height(self):
        """Give the lower pane real height so its plot does not paint black."""
        sizes = self.right_splitter.sizes()
        if len(sizes) >= 2 and sizes[1] < 80:
            total = max(sum(sizes), self.right_splitter.height(), 1)
            self.right_splitter.setSizes([int(total * 0.72), int(total * 0.28)])

    def hide_secondary_view(self):
        self.secondary_stack.setVisible(False)

    # ==================================================================
    # Database cruise / core selection
    # ==================================================================

    def _populate_cruises(self):
        """Load cruise list from the project into the combo box."""
        self.cruise_combo.blockSignals(True)
        self.cruise_combo.clear()
        self.cruise_combo.addItem("Select cruise…")
        self._cruises = []

        if self.store is None:
            self.cruise_combo.blockSignals(False)
            self.statusBar().showMessage("No project open — use File ▸ Open Project…")
            return

        try:
            from ..persistence.loader import ProjectDataLoader
            self._cruises = ProjectDataLoader.fetch_cruises(self.store)
            for cr in self._cruises:
                label = cr["cruise_name"]
                if cr.get("vessel_name"):
                    label += f" — {cr['vessel_name']}"
                self.cruise_combo.addItem(label)
            self.cruise_combo.blockSignals(False)
            self.statusBar().showMessage(
                f"Project open — {len(self._cruises)} cruise(s) available"
            )
        except Exception as exc:
            self.cruise_combo.blockSignals(False)
            self.statusBar().showMessage(f"Error loading cruises: {exc}")

    def refresh_cruises(self, keep_selection: bool = False):
        """Refresh cruise/core combos after Data Manager changes."""
        prev_cruise = self.get_selected_cruise_id()
        prev_core_name = None
        idx = self.core_combo.currentIndex()
        if 0 < idx <= len(self._cores):
            prev_core_name = self._cores[idx - 1].get("core_name")

        self._populate_cruises()

        if keep_selection and prev_cruise is not None:
            for i, cr in enumerate(self._cruises, start=1):
                if cr["cruise_id"] == prev_cruise:
                    self.cruise_combo.setCurrentIndex(i)
                    break

        if keep_selection and prev_core_name:
            for i, ci in enumerate(self._cores, start=1):
                if ci.get("core_name") == prev_core_name:
                    self.core_combo.setCurrentIndex(i)
                    break

    def _on_cruise_changed(self, index: int):
        """Cruise combo changed — populate the core combo."""
        self.core_combo.blockSignals(True)
        self.core_combo.clear()
        self.core_combo.addItem("Select core…")
        self._cores = []

        if index <= 0 or index > len(self._cruises):
            self.core_combo.setEnabled(False)
            self.core_combo.blockSignals(False)
            return

        cruise = self._cruises[index - 1]
        if self.store is None:
            self.core_combo.setEnabled(False)
            self.core_combo.blockSignals(False)
            return

        try:
            from ..persistence.loader import ProjectDataLoader
            self._cores = ProjectDataLoader.fetch_cores_for_cruise_all_types(
                self.store, cruise["cruise_id"],
            )
            for ci in self._cores:
                label = ci["core_name"]
                if self.get_current_mode() == 'Create Calibration' and ci.get("core_type_name"):
                    label += f" ({ci['core_type_name']})"
                self.core_combo.addItem(label)
            self.core_combo.setEnabled(bool(self._cores))
            if not self._cores:
                self.statusBar().showMessage(
                    f"No cores with sensor files in {cruise['cruise_name']}"
                )
        except Exception as exc:
            self.statusBar().showMessage(f"Error fetching cores: {exc}")
            self.core_combo.setEnabled(False)

        self.core_combo.blockSignals(False)

        if self.get_current_mode() == 'Winch':
            self.controller.reload_winch_data()

    def _on_core_changed(self, index: int):
        """Core combo changed — load the sensor data."""
        if index <= 0 or index > len(self._cores):
            return

        core_info = self._cores[index - 1]
        self.statusBar().showMessage(
            f"Loading sensor data for {core_info['core_name']}…"
        )
        if self.get_current_mode() == 'Create Calibration':
            self.controller._load_cast_from_database(
                core_info["core_id"], core_info
            )
        elif self.get_current_mode() == 'Alter':
            self.controller._on_alter_core_changed(
                core_info["core_id"], core_info
            )
        else:
            cruise_id = self.get_selected_cruise_id()
            self.controller.load_from_database(
                core_info["core_id"], core_info, cruise_id=cruise_id,
            )
            if self.get_current_mode() == 'Winch':
                self.controller.reload_winch_data()

    # ==================================================================
    # Toolbar actions
    # ==================================================================

    def _show_about(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            "Sensorius",
            "Sensorius\n\n"
            "Multi-sensor depth comparison, calibration,\n"
            "and time-offset correction tool.\n\n"
            "Portable project mode — no PostgreSQL required.\n\n"
            "Built with PySide6 + pyqtgraph."
        )
