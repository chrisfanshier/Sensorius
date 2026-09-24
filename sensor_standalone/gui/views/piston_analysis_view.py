"""
PistonAnalysisView - Secondary plot for Piston Analysis mode.

Two subplots stacked vertically:

  Top:    Piston depth (absolute, m) and WS depth vs core depth (m)
          Optional horizontal line at seafloor depth.

  Bottom: WS velocity and piston velocity (m/s) vs core depth (m)
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

from ...domain.processing.piston_analysis import PistonAnalysisResult


class PistonAnalysisView(QWidget):
    """Secondary view widget for piston analysis plots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel('')
        self.info_label.setStyleSheet(
            'QLabel { background-color: white; padding: 5px; '
            'border: 1px solid gray; }'
        )
        layout.addWidget(self.info_label)

        self.graphics = pg.GraphicsLayoutWidget()
        self.graphics.setBackground('w')
        layout.addWidget(self.graphics)

        # Top subplot: depths
        self._depth_plot = self.graphics.addPlot(row=0, col=0)
        self._depth_plot.setLabel('left', 'Depth (m)')
        self._depth_plot.setLabel('bottom', 'Core Depth (m)  [0 = start-pen, negative = pre-penetration]')
        self._depth_plot.invertY(True)
        self._depth_plot.showGrid(x=True, y=True, alpha=0.3)
        self._depth_plot.setDownsampling(auto=True, mode='peak')
        self._depth_plot.setClipToView(True)
        self._depth_legend = self._depth_plot.addLegend()

        # Bottom subplot: velocities
        self._vel_plot = self.graphics.addPlot(row=1, col=0)
        self._vel_plot.setLabel('left', 'Velocity (m/s)')
        self._vel_plot.setLabel('bottom', 'Core Depth (m)  [0 = start-pen, negative = pre-penetration]')
        self._vel_plot.showGrid(x=True, y=True, alpha=0.3)
        self._vel_plot.setDownsampling(auto=True, mode='peak')
        self._vel_plot.setClipToView(True)
        self._vel_legend = self._vel_plot.addLegend()
        self._zero_line = pg.InfiniteLine(
            pos=0, angle=0, movable=False,
            pen=pg.mkPen('k', width=1),
        )
        self._vel_plot.addItem(self._zero_line, ignoreBounds=True)

        # Link x-axes
        self._vel_plot.setXLink(self._depth_plot)

        self._seafloor_line: Optional[pg.InfiniteLine] = None
        self._start_pen_depth_line: Optional[pg.InfiniteLine] = None
        self._start_pen_vel_line: Optional[pg.InfiniteLine] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plot(self, result: PistonAnalysisResult):
        """Render analysis results."""
        # Use clearPlots() to remove only data curves — leaves legend,
        # axes, and static items (zero line, seafloor line) intact.
        # Then clear legend entries so they can be re-added cleanly.
        self._depth_plot.clearPlots()
        self._vel_plot.clearPlots()
        self._depth_legend.clear()
        self._vel_legend.clear()

        # Remove previous seafloor line if any
        if self._seafloor_line is not None:
            self._depth_plot.removeItem(self._seafloor_line)
            self._seafloor_line = None

        # Remove previous start-pen markers if any
        if self._start_pen_depth_line is not None:
            self._depth_plot.removeItem(self._start_pen_depth_line)
            self._start_pen_depth_line = None
        if self._start_pen_vel_line is not None:
            self._vel_plot.removeItem(self._start_pen_vel_line)
            self._start_pen_vel_line = None

        x = result.core_depth

        # -- Depth subplot --
        self._depth_plot.plot(
            x, result.ws_depth,
            pen=pg.mkPen('#1f77b4', width=2),
            name='Weight Stand',
        )
        self._depth_plot.plot(
            x, result.piston_depth,
            pen=pg.mkPen('r', width=2),
            name='Piston',
        )

        if result.seafloor is not None:
            self._seafloor_line = pg.InfiniteLine(
                pos=result.seafloor, angle=0, movable=False,
                pen=pg.mkPen('#c0392b', width=1.5,
                             style=pg.QtCore.Qt.DashLine),
                label=f'Seafloor {result.seafloor:.1f} m',
                labelOpts={'position': 0.9, 'color': '#c0392b',
                           'anchors': [(1, 0), (1, 1)]},
            )
            self._depth_plot.addItem(self._seafloor_line)

        # Start-pen marker (vertical, both subplots)
        _start_pen_pen = pg.mkPen(color='#7f7f7f', width=1.5,
                                  style=pg.QtCore.Qt.DashLine)
        self._start_pen_depth_line = pg.InfiniteLine(
            pos=result.start_pen_core_depth_m, angle=90, movable=False,
            pen=_start_pen_pen,
            label='Start pen',
            labelOpts={'position': 0.95, 'color': '#555555'},
        )
        self._depth_plot.addItem(self._start_pen_depth_line)
        self._start_pen_vel_line = pg.InfiniteLine(
            pos=result.start_pen_core_depth_m, angle=90, movable=False,
            pen=_start_pen_pen,
        )
        self._vel_plot.addItem(self._start_pen_vel_line)

        # -- Velocity subplot --
        self._vel_plot.plot(
            x, result.ws_velocity,
            pen=pg.mkPen('#1f77b4', width=2),
            name='WS Velocity',
        )
        self._vel_plot.plot(
            x, result.piston_velocity,
            pen=pg.mkPen('r', width=2),
            name='Piston Velocity',
        )

        n = len(x)
        self.info_label.setText(
            f"Piston Analysis  |  {n} samples  |  "
            f"Core depth: {float(x[0]):.2f} \u2013 {float(x[-1]):.2f} m  "
            f"(0 = start-pen)  |  "
            f"SG window={result.sg_window}, order={result.sg_polyorder}"
        )

    def clear(self):
        """Remove all plotted data."""
        self._depth_plot.clearPlots()
        self._vel_plot.clearPlots()
        self._depth_legend.clear()
        self._vel_legend.clear()
        if self._seafloor_line is not None:
            self._depth_plot.removeItem(self._seafloor_line)
            self._seafloor_line = None
        if self._start_pen_depth_line is not None:
            self._depth_plot.removeItem(self._start_pen_depth_line)
            self._start_pen_depth_line = None
        if self._start_pen_vel_line is not None:
            self._vel_plot.removeItem(self._start_pen_vel_line)
            self._start_pen_vel_line = None
        self.info_label.setText('')
