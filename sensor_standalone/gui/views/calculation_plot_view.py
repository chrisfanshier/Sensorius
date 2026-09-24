"""
CalculationPlotView - Secondary plot for Calculate mode.

Displays a stacked-box diagram comparing core-barrel geometry at two
timestamps:

  Left column  — @ Trip:
    weight stand + core barrel + freefall estimate → seafloor

  Right column — @ Start Penetration:
    weight stand + core barrel (tip at seafloor) + piston altitude

All values are in metres on an inverted (depth-downward) y-axis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

from ...domain.processing.calculations import DEFAULT_WEIGHT_STAND_LENGTH_M


FT_TO_M = 1.0 / 3.28
WEIGHT_LENGTH = DEFAULT_WEIGHT_STAND_LENGTH_M  # backwards-compatible alias


@dataclass
class GeometryInput:
    """All the data needed to draw the geometry diagram."""
    ws_at_trip: float
    seafloor: float
    core_length_m: float
    freefall_est: float
    weight_stand_length_m: float = DEFAULT_WEIGHT_STAND_LENGTH_M
    # Start-core values (None if unavailable)
    ws_at_start_core: Optional[float] = None
    piston_at_start_core: Optional[float] = None
    piston_alt_at_start_core: Optional[float] = None
    # Start-penetration values (None if unavailable)
    ws_at_start_pen: Optional[float] = None
    piston_at_start_pen: Optional[float] = None
    piston_alt_at_start_pen: Optional[float] = None
    # Ordering flag — True when barrel hits seafloor before scope opens
    start_pen_before_start_core: bool = False
    # End-of-initial-penetration values
    ws_at_end_pen: Optional[float] = None
    # Pullout values
    ws_at_pullout: Optional[float] = None
    piston_at_pullout: Optional[float] = None


class CalculationPlotView(QWidget):
    """Secondary view widget showing core-barrel geometry diagram."""

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

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=False, y=True, alpha=0.3)
        self.plot_widget.setLabel('left', 'Depth (m)')
        self.plot_widget.getAxis('bottom').setTicks([])
        self.plot_widget.getAxis('bottom').setStyle(showValues=False)
        self.plot_widget.invertY(True)
        # Disable mouse interaction (this is a static diagram)
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.hideButtons()

        layout.addWidget(self.plot_widget)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plot_geometry(self, geo: GeometryInput):
        """Draw the stacked-box geometry diagram with up to 5 columns."""
        self._clear()

        gap = 2.0
        positions = []  # track x positions of drawn groups
        x = 0.0

        # -- GROUP 1: @ Trip --
        ws_len = geo.weight_stand_length_m
        self._draw_box(x, geo.ws_at_trip, ws_len,
                       '#3498db', 'Weight')
        self._draw_box(x, geo.ws_at_trip + ws_len,
                       geo.core_length_m, '#2ecc71', 'Core Barrel')
        self._draw_box(
            x,
            geo.ws_at_trip + ws_len + geo.core_length_m,
            geo.freefall_est, '#e74c3c', 'Freefall\nEstimate',
        )
        self._add_group_label(x, geo.ws_at_trip, '@ Trip')
        positions.append(x)
        x += gap

        # -- GROUPS 2 & 3: @ Start Core and @ Start Pen (temporal order) --
        # When start_pen occurs before start_core (barrel hits seafloor before
        # scope fully opens), draw Start Pen first to keep left=earlier.
        _groups_23 = []
        if geo.ws_at_start_core is not None:
            _groups_23.append((
                geo.ws_at_start_core,
                geo.piston_at_start_core,
                geo.piston_alt_at_start_core,
                '@ Start Core',
            ))
        if geo.ws_at_start_pen is not None:
            _groups_23.append((
                geo.ws_at_start_pen,
                geo.piston_at_start_pen,
                geo.piston_alt_at_start_pen,
                '@ Start Pen',
            ))
        if geo.start_pen_before_start_core and len(_groups_23) == 2:
            _groups_23 = list(reversed(_groups_23))
        for _ws, _piston, _piston_alt, _label in _groups_23:
            self._draw_box(x, _ws, ws_len, '#3498db', 'Weight')
            self._draw_box(x, _ws + ws_len,
                           geo.core_length_m, '#2ecc71', 'Core Barrel')
            self._draw_piston_alt(x, _piston, _piston_alt, geo.seafloor)
            self._add_group_label(x, _ws, _label)
            positions.append(x)
            x += gap

        # -- GROUP 4: @ End of Initial Penetration --
        if geo.ws_at_end_pen is not None:
            ws = geo.ws_at_end_pen
            self._draw_box(x, ws, ws_len, '#3498db', 'Weight')
            self._draw_box(x, ws + ws_len,
                           geo.core_length_m, '#2ecc71', 'Core Barrel')
            self._add_group_label(x, ws, '@ End Pen')
            positions.append(x)
            x += gap

        # -- GROUP 5: @ Pullout --
        if geo.ws_at_pullout is not None:
            ws = geo.ws_at_pullout
            self._draw_box(x, ws, ws_len, '#3498db', 'Weight')
            self._draw_box(x, ws + ws_len,
                           geo.core_length_m, '#2ecc71', 'Core Barrel')
            if geo.piston_at_pullout is not None:
                piston_alt = geo.seafloor - geo.piston_at_pullout
                self._draw_piston_alt(
                    x, geo.piston_at_pullout, piston_alt, geo.seafloor,
                )
            self._add_group_label(x, ws, '@ Pullout')
            positions.append(x)
            x += gap

        # -- Reference lines --
        sf_pen = pg.mkPen('#c0392b', width=1.5, style=Qt.DashLine)
        sf_line = pg.InfiniteLine(
            pos=geo.seafloor, angle=0, pen=sf_pen,
            label=f'Seafloor {geo.seafloor:.1f} m',
            labelOpts={
                'position': 0.9, 'color': '#c0392b',
                'anchors': [(1, 0), (1, 1)],
            },
        )
        self.plot_widget.addItem(sf_line)

        ws_pen = pg.mkPen('#7f8c8d', width=1, style=Qt.DotLine)
        ws_line = pg.InfiniteLine(
            pos=geo.ws_at_trip, angle=0, pen=ws_pen,
            label=f'WS@trip {geo.ws_at_trip:.1f} m',
            labelOpts={
                'position': 0.1, 'color': '#7f8c8d',
                'anchors': [(0, 0), (0, 1)],
            },
        )
        self.plot_widget.addItem(ws_line)

        # Auto-range
        x_max = (positions[-1] + 1.5) if positions else 1.5
        self.plot_widget.setXRange(-1, x_max, padding=0.05)

        y_min = geo.ws_at_trip - 3
        deepest_ws = geo.ws_at_trip
        for ws_val in (geo.ws_at_start_core, geo.ws_at_start_pen,
                       geo.ws_at_end_pen, geo.ws_at_pullout):
            if ws_val is not None:
                deepest_ws = max(deepest_ws, ws_val)
        y_max = max(geo.seafloor, deepest_ws + ws_len + geo.core_length_m) + 2
        # Extend if any piston is below seafloor
        for piston_alt in (geo.piston_alt_at_start_core,
                           geo.piston_alt_at_start_pen):
            if piston_alt is not None and piston_alt < 0:
                y_max = max(y_max, geo.seafloor + abs(piston_alt) + 2)
        self.plot_widget.setYRange(y_min, y_max, padding=0.02)

        # Info label
        parts = [f"Seafloor: {geo.seafloor:.3f} m"]
        parts.append(f"Freefall Est: {geo.freefall_est:.3f} m")
        if geo.piston_alt_at_start_core is not None:
            parts.append(
                f"Piston Alt @ Start Core: "
                f"{geo.piston_alt_at_start_core:.3f} m"
            )
        self.info_label.setText('  |  '.join(parts))
        # Force a repaint – PlotWidget inside QStackedWidget can stay black
        # on first show without this.
        QTimer.singleShot(0, self.plot_widget.update)

    def clear(self):
        """Clear the diagram."""
        self._clear()
        self.info_label.setText('')

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_box(self, x: float, top: float, height: float,
                  colour: str, label: str):
        """Draw a coloured box (vertical bar) with end-caps and label."""
        bar_w = 0.6
        bot = top + height
        mid_y = (top + bot) / 2.0

        # Filled rectangle via BarGraphItem
        bar = pg.BarGraphItem(
            x=[x], height=[height], width=bar_w,
            y0=[top],
            brush=pg.mkBrush(QColor(colour).lighter(140)),
            pen=pg.mkPen(colour, width=1.5),
        )
        self.plot_widget.addItem(bar)

        # End-cap lines
        cap_hw = bar_w * 0.35
        for y in (top, bot):
            cap = pg.PlotDataItem(
                [x - cap_hw, x + cap_hw], [y, y],
                pen=pg.mkPen(colour, width=2),
            )
            self.plot_widget.addItem(cap)

        # Centre label
        text = pg.TextItem(
            html=(
                f'<div style="text-align:center; color:white; '
                f'font-size:8pt; font-weight:bold; '
                f'background:{colour}; padding:2px 4px; '
                f'border-radius:3px;">'
                f'{label}<br>{height:.3f} m</div>'
            ),
            anchor=(0.5, 0.5),
        )
        text.setPos(x, mid_y)
        self.plot_widget.addItem(text)

    def _add_group_label(self, x: float, top_depth: float, label: str):
        """Add a title label above a group column."""
        text = pg.TextItem(
            html=(
                f'<div style="text-align:center; font-size:10pt; '
                f'font-weight:bold; color:#2c3e50;">'
                f'{label}</div>'
            ),
            anchor=(0.5, 1.0),
        )
        text.setPos(x, top_depth - 1.0)
        self.plot_widget.addItem(text)

    def _draw_piston_alt(self, x: float, piston_depth: Optional[float],
                         piston_alt: Optional[float],
                         seafloor: float):
        """Draw a piston-position marker line with altitude label."""
        if piston_depth is None or piston_alt is None:
            return
        bar_w = 0.6
        cap_hw = bar_w * 0.35
        colour = '#9b59b6'
        # Horizontal line at piston depth
        line = pg.PlotDataItem(
            [x - cap_hw, x + cap_hw], [piston_depth, piston_depth],
            pen=pg.mkPen(colour, width=2.5),
        )
        self.plot_widget.addItem(line)
        # Label to the right
        text = pg.TextItem(
            html=(
                f'<div style="font-size:7pt; color:{colour}; '
                f'font-weight:bold;">'
                f'Piston Alt<br>{piston_alt:.3f} m</div>'
            ),
            anchor=(0.0, 0.5),
        )
        text.setPos(x + cap_hw + 0.05, piston_depth)
        self.plot_widget.addItem(text)

    def _clear(self):
        """Clear all items from the plot."""
        self.plot_widget.clear()
