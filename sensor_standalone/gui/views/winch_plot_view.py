"""
WinchPlotView - Secondary plot for Winch mode.

One or two stacked winch time-series subplots. X-axis is linked to the main
sensor plot so pan/zoom on time is shared; Y-axis zooms independently.

Window 1 supports a draggable search region and winch trip marker.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QStackedWidget
from PySide6.QtCore import Qt, Signal

from ...persistence.winch_loader import datetime_to_epoch, timestamp_to_epoch

_WINCH_TRIP_COLOR = '#9467bd'


class WinchPlotView(QWidget):
    """Secondary view showing one or two winch parameter traces vs time."""

    winch_trip_line_changed = Signal(int)
    search_region_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._winch_df: Optional[pd.DataFrame] = None
        self._x_epochs: Optional[np.ndarray] = None
        self._x_link_target: Optional[pg.PlotItem] = None
        self._winch_trip_line: Optional[pg.InfiniteLine] = None
        self._search_region: Optional[pg.LinearRegionItem] = None
        self._search_region_plot: Optional[pg.PlotItem] = None
        self._search_region_values: Optional[tuple[float, float]] = None
        self._search_region_enabled: bool = False
        self._window1_plot: Optional[pg.PlotItem] = None
        self._plot_vlines: dict[pg.PlotItem, pg.InfiniteLine] = {}
        self._mouse_proxies: list[pg.SignalProxy] = []
        self._plotted_columns: dict[pg.PlotItem, str] = {}
        self._data_fingerprint: Optional[tuple] = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel('No winch data loaded.')
        self.info_label.setStyleSheet(
            'QLabel { background-color: white; padding: 5px; '
            'border: 1px solid gray; }'
        )
        layout.addWidget(self.info_label)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._single_graphics = self._make_graphics(num_plots=1)
        self._dual_graphics = self._make_graphics(num_plots=2)

        self._stack.addWidget(self._single_graphics['widget'])
        self._stack.addWidget(self._dual_graphics['widget'])

        self._single_plot = self._single_graphics['plots'][0]
        self._dual_plot_1 = self._dual_graphics['plots'][0]
        self._dual_plot_2 = self._dual_graphics['plots'][1]

    def _make_graphics(self, num_plots: int) -> dict:
        widget = pg.GraphicsLayoutWidget()
        widget.setBackground('w')
        plots: list[pg.PlotItem] = []
        date_axis = pg.graphicsItems.DateAxisItem.DateAxisItem(orientation='bottom')

        for row in range(num_plots):
            if row == num_plots - 1:
                plot = widget.addPlot(row=row, col=0, axisItems={'bottom': date_axis})
            else:
                plot = widget.addPlot(row=row, col=0)
            plot.setLabel('left', 'Winch')
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setDownsampling(auto=True, mode='peak')
            plot.setClipToView(True)
            plot.addLegend()
            if row > 0:
                plot.setXLink(plots[0])
            vline = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen('r', width=1, style=Qt.DashLine),
            )
            vline.setVisible(False)
            plot.addItem(vline, ignoreBounds=True)
            self._plot_vlines[plot] = vline
            plots.append(plot)

        scene = widget.scene()
        self._mouse_proxies.append(
            pg.SignalProxy(
                scene.sigMouseMoved,
                rateLimit=60,
                slot=self._on_mouse_moved,
            )
        )

        if num_plots == 1:
            plots[0].setLabel('bottom', 'Time')

        return {'widget': widget, 'plots': plots}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_x_link(self, plot_item: Optional[pg.PlotItem]) -> None:
        """Link winch plot X-axes to the main sensor plot."""
        self._x_link_target = plot_item
        for plot in (self._single_plot, self._dual_plot_1, self._dual_plot_2):
            if plot_item is not None:
                plot.setXLink(plot_item)
            else:
                plot.setXLink(None)

    def set_search_region_enabled(self, enabled: bool) -> None:
        """Show or hide the draggable search region on window 1."""
        self._search_region_enabled = enabled
        if enabled:
            self._ensure_search_region_on_window1(force=True)
        elif self._search_region is not None:
            self._search_region_values = tuple(self._search_region.getRegion())
            self.remove_search_region()

    def set_search_region_epochs(
        self,
        start_epoch: float,
        end_epoch: float,
    ) -> None:
        """Set the search window from epoch seconds and show the region."""
        lo = min(float(start_epoch), float(end_epoch))
        hi = max(float(start_epoch), float(end_epoch))
        self._search_region_values = (lo, hi)
        self._search_region_enabled = True
        if self._search_region is not None:
            self.remove_search_region()
        if self._x_epochs is not None and self._window1_plot is not None:
            self._ensure_search_region_on_window1(force=True)

    def plot(
        self,
        df: Optional[pd.DataFrame],
        column_1: Optional[str],
        column_2: Optional[str] = None,
        show_second: bool = False,
        source_label: str = '',
    ) -> None:
        """Render winch data in one or two windows."""
        self._winch_df = df

        if df is None or df.empty or not column_1:
            self._x_epochs = None
            self._data_fingerprint = None
            self._clear_all_plots()
            self.remove_winch_trip_line()
            self._invalidate_search_region(clear_values=True)
            self.info_label.setText(
                source_label or 'No winch data loaded.'
            )
            return

        x = datetime_to_epoch(df).to_numpy()
        fingerprint = (len(x), float(x[0]), float(x[-1]))
        if fingerprint != self._data_fingerprint:
            self._invalidate_search_region(clear_values=True)
        self._data_fingerprint = fingerprint
        self._x_epochs = x
        dual = show_second and column_2 and column_2 in df.columns

        if dual:
            self._stack.setCurrentIndex(1)
            self._window1_plot = self._dual_plot_1
            self._plotted_columns = {
                self._dual_plot_1: column_1,
                self._dual_plot_2: column_2,
            }
            self._plot_trace(self._dual_plot_1, x, df[column_1].to_numpy(), column_1)
            self._plot_trace(self._dual_plot_2, x, df[column_2].to_numpy(), column_2)
            self._dual_plot_1.setLabel('bottom', '')
            self._dual_plot_2.setLabel('bottom', 'Time')
        else:
            self._stack.setCurrentIndex(0)
            self._window1_plot = self._single_plot
            col = column_1 if column_1 in df.columns else None
            self._plotted_columns = {self._single_plot: column_1} if col else {}
            if col:
                self._plot_trace(self._single_plot, x, df[col].to_numpy(), col)
            self._single_plot.setLabel('bottom', 'Time')

        if self._search_region_enabled:
            self._ensure_search_region_on_window1(force=True)
        elif self._search_region_values is None:
            x_min = float(x[0])
            x_max = float(x[-1])
            span = max(x_max - x_min, 1.0)
            margin = span * 0.05
            self._search_region_values = (x_min + margin, x_max - margin)

        rows = len(df)
        label = source_label or f'{rows:,} winch samples'
        self.info_label.setText(label)

        if self._x_link_target is None:
            self._auto_range_x(x)

    def clear(self) -> None:
        self._winch_df = None
        self._x_epochs = None
        self._clear_all_plots()
        self.remove_winch_trip_line()
        self._invalidate_search_region(clear_values=True)
        self.info_label.setText('No winch data loaded.')

    def add_winch_trip_line(self, trip_index: int) -> None:
        """Place a draggable winch trip marker on window 1."""
        if self._x_epochs is None or self._window1_plot is None:
            return
        if not (0 <= trip_index < len(self._x_epochs)):
            return

        x_pos = float(self._x_epochs[trip_index])
        self.remove_winch_trip_line()

        self._winch_trip_line = pg.InfiniteLine(
            pos=x_pos, angle=90, movable=True,
            pen=pg.mkPen(_WINCH_TRIP_COLOR, width=2, style=Qt.DashLine),
            label='Winch Trip',
            labelOpts={'position': 0.9, 'color': _WINCH_TRIP_COLOR},
        )
        self._winch_trip_line.sigPositionChangeFinished.connect(
            self._on_winch_trip_line_moved
        )
        self._winch_trip_line.setZValue(20)
        self._window1_plot.addItem(self._winch_trip_line)
        self._window1_plot.update()

    def remove_winch_trip_line(self) -> None:
        if self._winch_trip_line is not None:
            try:
                self._winch_trip_line.sigPositionChangeFinished.disconnect(
                    self._on_winch_trip_line_moved
                )
            except Exception:
                pass
            if self._window1_plot is not None:
                try:
                    self._window1_plot.removeItem(self._winch_trip_line)
                except Exception:
                    pass
            self._winch_trip_line = None

    def get_search_window_timestamps(self) -> tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
        """Return the current search region as pandas timestamps."""
        if self._search_region is not None:
            start_epoch, end_epoch = self._search_region.getRegion()
        elif self._search_region_values is not None:
            start_epoch, end_epoch = self._search_region_values
        else:
            return None, None
        return (
            pd.to_datetime(start_epoch, unit='s', utc=False),
            pd.to_datetime(end_epoch, unit='s', utc=False),
        )

    def remove_search_region(self) -> None:
        if self._search_region is not None:
            try:
                self._search_region.sigRegionChanged.disconnect(
                    self._on_search_region_changed
                )
            except Exception:
                pass
            if self._window1_plot is not None:
                try:
                    self._window1_plot.removeItem(self._search_region)
                except Exception:
                    pass
            self._search_region = None
        self._search_region_plot = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _plot_trace(
        self,
        plot: pg.PlotItem,
        x: np.ndarray,
        y: np.ndarray,
        name: str,
    ) -> None:
        plot.clearPlots()
        plot.plot(
            x, y,
            pen=pg.mkPen('#d62728', width=1.5),
            name=name,
        )
        plot.setLabel('left', name)
        plot.enableAutoRange(axis='y')

    def _clear_all_plots(self) -> None:
        for plot in (self._single_plot, self._dual_plot_1, self._dual_plot_2):
            plot.clearPlots()

    def _auto_range_x(self, x: np.ndarray) -> None:
        if len(x) == 0:
            return
        x_min, x_max = float(np.min(x)), float(np.max(x))
        pad = max((x_max - x_min) * 0.02, 1.0)
        for plot in (self._single_plot, self._dual_plot_1):
            plot.setXRange(x_min - pad, x_max + pad, padding=0)

    def _invalidate_search_region(self, clear_values: bool = False) -> None:
        """Remove the on-plot search region; optionally clear stored bounds."""
        if self._search_region is not None:
            self.remove_search_region()
        if clear_values:
            self._search_region_values = None

    def _ensure_search_region_on_window1(self, force: bool = False) -> None:
        if not self._search_region_enabled:
            return
        if self._x_epochs is None or self._window1_plot is None:
            return

        if (
            not force
            and self._search_region is not None
            and self._search_region_plot is self._window1_plot
        ):
            return

        saved_values = None
        if self._search_region is not None:
            saved_values = self._search_region.getRegion()
            self.remove_search_region()

        if saved_values is None:
            if self._search_region_values is not None:
                saved_values = self._search_region_values
            else:
                x_min = float(self._x_epochs[0])
                x_max = float(self._x_epochs[-1])
                span = max(x_max - x_min, 1.0)
                margin = span * 0.05
                saved_values = (x_min + margin, x_max - margin)

        x_min = float(self._x_epochs[0])
        x_max = float(self._x_epochs[-1])
        lo, hi = float(saved_values[0]), float(saved_values[1])
        lo = max(lo, x_min)
        hi = min(hi, x_max)
        if lo >= hi:
            span = max(x_max - x_min, 1.0)
            margin = span * 0.05
            lo, hi = x_min + margin, x_max - margin

        self._search_region_values = (lo, hi)
        self._search_region = pg.LinearRegionItem(
            values=[lo, hi],
            brush=pg.mkBrush(100, 149, 237, 40),
            movable=True,
        )
        self._search_region.setZValue(5)
        self._search_region.sigRegionChanged.connect(self._on_search_region_changed)
        self._window1_plot.addItem(self._search_region)
        self._search_region_plot = self._window1_plot

    def _on_winch_trip_line_moved(self) -> None:
        if self._winch_trip_line is None or self._x_epochs is None:
            return
        if len(self._x_epochs) == 0:
            return
        x_pos = self._winch_trip_line.value()
        idx = int(np.argmin(np.abs(self._x_epochs - x_pos)))
        # Only the index is persisted, so put the line on the sample it
        # resolves to rather than leaving it where the drag ended.
        snapped = float(self._x_epochs[idx])
        if snapped != x_pos:
            self._winch_trip_line.setValue(snapped)
        self.winch_trip_line_changed.emit(idx)

    def _on_search_region_changed(self) -> None:
        if self._search_region is not None:
            self._search_region_values = tuple(self._search_region.getRegion())
        self.search_region_changed.emit()

    def _active_plots(self) -> list[pg.PlotItem]:
        if self._stack.currentIndex() == 1:
            return [self._dual_plot_1, self._dual_plot_2]
        return [self._single_plot]

    def _on_mouse_moved(self, evt) -> None:
        if self._winch_df is None or self._x_epochs is None:
            return

        pos = evt[0]
        for plot in self._active_plots():
            if not plot.sceneBoundingRect().contains(pos):
                continue

            mouse_point = plot.vb.mapSceneToView(pos)
            x_pos = mouse_point.x()

            for active in self._active_plots():
                vline = self._plot_vlines.get(active)
                if vline is not None:
                    vline.setPos(x_pos)
                    vline.setVisible(True)

            idx = int(np.argmin(np.abs(self._x_epochs - x_pos)))
            if 0 <= idx < len(self._winch_df):
                dt = self._winch_df['datetime'].iloc[idx]
                time_str = (
                    dt.strftime('%Y-%m-%d %H:%M:%S')
                    if pd.notna(dt) else 'N/A'
                )
                parts = [f'Index: {idx}', f'Time: {time_str}']
                for p, col in self._plotted_columns.items():
                    if col in self._winch_df.columns:
                        val = self._winch_df[col].iloc[idx]
                        if pd.notna(val):
                            parts.append(f'{col}: {val:.3f}')
                self.info_label.setText('  |  '.join(parts))
            return

        for plot in self._active_plots():
            vline = self._plot_vlines.get(plot)
            if vline is not None:
                vline.setVisible(False)
