"""
TripPlotView - Secondary plot for trip detector mode.

Two-row layout:
  Top:    Divergence (std dev across sensor derivatives) with threshold line
  Bottom: Individual sensor Savitzky-Golay velocity/derivative profiles

Both plots show a dashed red vertical line at the detected trip index.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSplitter
from PySide6.QtCore import Qt

from ...domain.models.sensor_data import SensorData
from ...domain.processing.trip_detection import TripDetectionResult

SENSOR_COLORS = ['#6baed6', '#74c476', '#fd8d3c', '#9e9ac8', '#e6550d', '#e7ba52']


class TripPlotView(QWidget):
    """
    Secondary plot widget for trip detection results.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel('')
        self.info_label.setStyleSheet(
            'QLabel { background-color: white; padding: 5px; border: 1px solid gray; }'
        )
        layout.addWidget(self.info_label)

        self._splitter = QSplitter(Qt.Vertical)

        self.divergence_plot = pg.PlotWidget()
        self.divergence_plot.setBackground('w')
        self.divergence_plot.showGrid(x=True, y=True, alpha=0.3)
        self.divergence_plot.addLegend()
        self.divergence_plot.setLabel('left', 'Divergence (Std Dev)')
        self.divergence_plot.setLabel('bottom', 'Sample Index')
        self.divergence_plot.setDownsampling(auto=True, mode='peak')
        self.divergence_plot.setClipToView(True)
        self._splitter.addWidget(self.divergence_plot)

        self.derivatives_plot = pg.PlotWidget()
        self.derivatives_plot.setBackground('w')
        self.derivatives_plot.showGrid(x=True, y=True, alpha=0.3)
        self.derivatives_plot.addLegend()
        self.derivatives_plot.setLabel('left', 'Derivative')
        self.derivatives_plot.setLabel('bottom', 'Sample Index')
        self.derivatives_plot.setDownsampling(auto=True, mode='peak')
        self.derivatives_plot.setClipToView(True)
        self._splitter.addWidget(self.derivatives_plot)

        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 1)

        layout.addWidget(self._splitter)

        self._div_vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self._div_hline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self.divergence_plot.addItem(self._div_vline, ignoreBounds=True)
        self.divergence_plot.addItem(self._div_hline, ignoreBounds=True)
        self._div_vline.setVisible(False)
        self._div_hline.setVisible(False)

        self._der_vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self._der_hline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self.derivatives_plot.addItem(self._der_vline, ignoreBounds=True)
        self.derivatives_plot.addItem(self._der_hline, ignoreBounds=True)
        self._der_vline.setVisible(False)
        self._der_hline.setVisible(False)

        self._mouse_proxy_div = pg.SignalProxy(
            self.divergence_plot.scene().sigMouseMoved,
            rateLimit=60, slot=self._on_mouse_moved_div,
        )
        self._mouse_proxy_der = pg.SignalProxy(
            self.derivatives_plot.scene().sigMouseMoved,
            rateLimit=60, slot=self._on_mouse_moved_der,
        )

        self._n_samples: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plot_trip_result(self, result: TripDetectionResult):
        """
        Plot full trip detection results.

        Args:
            result: TripDetectionResult from the processor.
        """
        self._clear_plots()

        n = len(result.divergence)
        self._n_samples = n
        x = np.arange(n, dtype=float)
        trip_idx = result.trip_index

        # ---- Top plot: divergence ----
        self.divergence_plot.setTitle(
            f'{result.derivative_label} Divergence'
        )
        self.divergence_plot.setLabel('left', 'Divergence (Std Dev)')

        self.divergence_plot.plot(
            x, result.divergence,
            pen=pg.mkPen('#7b3294', width=2),
            name='Divergence (Std Dev)',
            connect='finite',
        )

        threshold_line = pg.InfiniteLine(
            pos=result.threshold, angle=0,
            pen=pg.mkPen('#e08214', width=1, style=Qt.DotLine),
            label=f'Threshold = {result.threshold}',
            labelOpts={'position': 0.9, 'color': '#e08214'},
        )
        self.divergence_plot.addItem(threshold_line)

        trip_line_div = pg.InfiniteLine(
            pos=trip_idx, angle=90,
            pen=pg.mkPen('r', width=2, style=Qt.DashLine),
            label=f'Trip @ {trip_idx}',
            labelOpts={'position': 0.9, 'color': 'r'},
        )
        self.divergence_plot.addItem(trip_line_div)

        self.divergence_plot.autoRange()

        # ---- Bottom plot: individual derivatives ----
        self.derivatives_plot.setTitle(
            f'Individual Sensor {result.derivative_label}'
        )
        self.derivatives_plot.setLabel('left', result.derivative_label)

        for i, col in enumerate(result.depth_columns):
            profile = result.derivative_profiles[col]
            display_name = SensorData.get_short_name(col)
            color = SENSOR_COLORS[i % len(SENSOR_COLORS)]
            self.derivatives_plot.plot(
                x, profile,
                pen=pg.mkPen(color, width=2),
                name=f'{display_name} {result.derivative_label}',
                connect='finite',
            )

        zero_line = pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen('gray', width=1, style=Qt.DotLine),
        )
        self.derivatives_plot.addItem(zero_line)

        trip_line_der = pg.InfiniteLine(
            pos=trip_idx, angle=90,
            pen=pg.mkPen('r', width=2, style=Qt.DashLine),
            label=f'Trip @ {trip_idx}',
            labelOpts={'position': 0.9, 'color': 'r'},
        )
        self.derivatives_plot.addItem(trip_line_der)

        self.derivatives_plot.autoRange()
        self.derivatives_plot.setXLink(self.divergence_plot)

        self.info_label.setText(
            f"Trip detected at sample {trip_idx}  |  "
            f"Time: {result.trip_datetime}  |  "
            f"Confidence: {result.confidence:.0%}"
        )

    def clear(self):
        self._clear_plots()
        self.info_label.setText('')
        self._n_samples = 0

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _clear_plots(self):
        for pw in (self.divergence_plot, self.derivatives_plot):
            pw.setUpdatesEnabled(False)
            try:
                pw.clear()
                pw.addLegend()
            finally:
                pw.setUpdatesEnabled(True)

        self._div_vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self._div_hline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self.divergence_plot.addItem(self._div_vline, ignoreBounds=True)
        self.divergence_plot.addItem(self._div_hline, ignoreBounds=True)
        self._div_vline.setVisible(False)
        self._div_hline.setVisible(False)

        self._der_vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self._der_hline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine),
        )
        self.derivatives_plot.addItem(self._der_vline, ignoreBounds=True)
        self.derivatives_plot.addItem(self._der_hline, ignoreBounds=True)
        self._der_vline.setVisible(False)
        self._der_hline.setVisible(False)

    def _on_mouse_moved_div(self, evt):
        pos = evt[0]
        if not self.divergence_plot.sceneBoundingRect().contains(pos):
            return
        mp = self.divergence_plot.plotItem.vb.mapSceneToView(pos)
        self._div_vline.setPos(mp.x())
        self._div_hline.setPos(mp.y())
        self._div_vline.setVisible(True)
        self._div_hline.setVisible(True)
        idx = max(0, min(int(mp.x()), self._n_samples - 1)) if self._n_samples else 0
        self.info_label.setText(f"Sample: {idx}  |  Divergence: {mp.y():.6f}")

    def _on_mouse_moved_der(self, evt):
        pos = evt[0]
        if not self.derivatives_plot.sceneBoundingRect().contains(pos):
            return
        mp = self.derivatives_plot.plotItem.vb.mapSceneToView(pos)
        self._der_vline.setPos(mp.x())
        self._der_hline.setPos(mp.y())
        self._der_vline.setVisible(True)
        self._der_hline.setVisible(True)
        idx = max(0, min(int(mp.x()), self._n_samples - 1)) if self._n_samples else 0
        self.info_label.setText(f"Sample: {idx}  |  Derivative: {mp.y():.6f}")
