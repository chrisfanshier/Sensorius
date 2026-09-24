"""
CalibrationPlotView - Secondary plot showing regression results for each sensor pair.

Displayed after Generate Calibration is clicked in Create Calibration mode.
Each subplot shows:
  - Scatter: collected (mean_depth, mean_difference) points
  - Line: linear regression fit across the depth range
  - Annotation: equation and R² value
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from ...domain.models.calibration import DepthCalibration
from ...domain.models.analysis_result import StatisticsResult

# Color cycle for scatter points (one per collected statistic)
POINT_COLORS = ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3',
                '#ff7f00', '#a65628', '#f781bf', '#999999']


class CalibrationPlotView(QWidget):
    """
    Secondary view widget showing one regression subplot per sensor pair.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header_label = QLabel("Calibration Regressions")
        self.header_label.setStyleSheet(
            "QLabel { background-color: white; padding: 5px; "
            "border-bottom: 1px solid #ccc; font-weight: bold; }"
        )
        layout.addWidget(self.header_label)

        self._graphics = pg.GraphicsLayoutWidget()
        self._graphics.setBackground('w')
        layout.addWidget(self._graphics)

        self._plots: list[pg.PlotItem] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plot_calibration(
        self,
        calibration: DepthCalibration,
        statistics: list[StatisticsResult],
    ):
        """
        Draw one subplot per sensor-pair regression.

        Args:
            calibration: DepthCalibration produced by CalibrationBuilder.
            statistics: The list of StatisticsResult used to build it.
        """
        self._graphics.clear()
        self._plots.clear()

        regressions = calibration.regressions
        if not regressions:
            return

        n_plots = len(regressions)
        # Arrange in a single row (up to 6 pairs for 4 sensors = 6 plots)
        # Use two rows if more than 3 pairs
        cols = min(n_plots, 3)
        rows = (n_plots + cols - 1) // cols

        # Collect depth range from statistics
        depths = np.array([s.mean_depth_all_sensors for s in statistics])
        depth_min = float(depths.min()) if len(depths) else 0.0
        depth_max = float(depths.max()) if len(depths) else 1000.0
        margin = (depth_max - depth_min) * 0.1 or 50.0
        line_depths = np.linspace(
            max(0.0, depth_min - margin),
            depth_max + margin,
            300,
        )

        # Build col_name → label reverse map from calibration
        # (we need it to look up difference_means by column-pair keys)
        # The statistics store difference_means keyed by (col_j, col_i) using
        # original column names.  We match by label pairs from the regression.
        sensor_labels = calibration.sensor_labels  # ['A', 'B', ...]

        for plot_idx, reg in enumerate(regressions):
            row = plot_idx // cols
            col = plot_idx % cols

            p = self._graphics.addPlot(row=row, col=col)
            p.showGrid(x=True, y=True, alpha=0.25)
            p.setLabel('left', 'Offset (m)')
            p.setLabel('bottom', 'Depth (m)')
            p.setTitle(
                f"<b>{reg.sensor_j} − {reg.sensor_i}</b>",
                color='k', size='11pt',
            )
            self._plots.append(p)

            # ── Scatter points ────────────────────────────────────────
            label_i_idx = (
                sensor_labels.index(reg.sensor_i)
                if reg.sensor_i in sensor_labels else None
            )
            label_j_idx = (
                sensor_labels.index(reg.sensor_j)
                if reg.sensor_j in sensor_labels else None
            )

            scatter_x: list[float] = []
            scatter_y: list[float] = []

            for stat in statistics:
                y_val = self._get_diff_for_pair(
                    stat, reg.sensor_i, reg.sensor_j,
                    label_i_idx, label_j_idx, sensor_labels,
                )
                if y_val is not None:
                    scatter_x.append(stat.mean_depth_all_sensors)
                    scatter_y.append(y_val)

            if scatter_x:
                scatter = pg.ScatterPlotItem(
                    x=np.array(scatter_x),
                    y=np.array(scatter_y),
                    size=10,
                    pen=pg.mkPen('k', width=1),
                    brush=pg.mkBrush('#377eb8'),
                    symbol='o',
                )
                p.addItem(scatter)

            # ── Regression line ───────────────────────────────────────
            line_y = reg.slope * line_depths + reg.intercept
            p.plot(
                line_depths, line_y,
                pen=pg.mkPen('#e41a1c', width=2),
            )

            # ── Equation annotation ───────────────────────────────────
            sign = '+' if reg.intercept >= 0 else '-'
            eq_text = (
                f"y = {reg.slope:.5f}x {sign} {abs(reg.intercept):.4f}"
                f"   R² = {reg.r_squared:.4f}"
            )
            annotation = pg.TextItem(
                text=eq_text,
                color=(60, 60, 60),
                anchor=(0, 1),
            )
            p.addItem(annotation)
            # Position near the top-left of the data range
            y_range = line_y.max() - line_y.min() if len(line_y) else 1.0
            annotation.setPos(line_depths[0], line_y.max() + y_range * 0.05)

        self.header_label.setText(
            f"Calibration Regressions — "
            f"{len(statistics)} point(s) collected, "
            f"{n_plots} pair(s)"
        )

    def clear(self):
        """Remove all plots."""
        self._graphics.clear()
        self._plots.clear()
        self.header_label.setText("Calibration Regressions")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_diff_for_pair(
        stat: StatisticsResult,
        label_i: str,
        label_j: str,
        label_i_idx: int | None,
        label_j_idx: int | None,
        sensor_labels: list[str],
    ) -> float | None:
        """
        Extract the (j - i) difference from a StatisticsResult.

        difference_means is keyed by (col_j, col_i) using the original column
        names.  We match by position: the n-th depth column maps to the n-th
        calibration label.
        """
        # Sort keys so we can match by position
        sorted_keys = sorted(stat.difference_means.keys())

        # Try to find a key whose position matches (label_j_idx, label_i_idx)
        col_keys = list(stat.difference_means.keys())
        for key, val in stat.difference_means.items():
            col_j, col_i = key
            # Map column position to labels by counting how many depth columns
            # appear before this one.  We rely on the order they appear in
            # column_means (which preserves sensor file order).
            col_positions = list(stat.column_means.keys())
            if col_j in col_positions and col_i in col_positions:
                pos_j = col_positions.index(col_j)
                pos_i = col_positions.index(col_i)
                if (
                    label_j_idx is not None
                    and label_i_idx is not None
                    and pos_j == label_j_idx
                    and pos_i == label_i_idx
                ):
                    return float(val)

        return None
