"""
SensorPlotView - The main persistent depth-vs-time plot.

Used by all modes. Supports:
- Plotting depth sensor traces
- Plotting pairwise depth differences
- Selection regions (double-click to start/end)
- Crosshair tracking with info label
- Y-axis inversion for depth
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal

from ...domain.models.sensor_data import SensorData

# Sensor colors
SENSOR_COLORS = ['#6baed6', '#74c476', '#fd8d3c', '#9e9ac8', '#e6550d', '#e7ba52']
SENSOR_COLORS_QT = ['b', 'g', 'r', 'm', 'c', 'y']


class SensorPlotView(QWidget):
    """
    Persistent main plot widget displaying depth vs time.

    Signals:
        selection_changed(int, int): Emitted when a selection is completed.
        selection_cleared: Emitted when selection is cleared.
    """

    selection_changed = Signal(int, int)
    selection_cleared = Signal()
    start_core_changed = Signal(int)
    trip_line_changed = Signal(int)
    end_pen_changed = Signal(int)
    pullout_changed = Signal(int)
    start_pen_changed = Signal(int)
    seafloor_changed = Signal(float)  # emits new depth (m) when dragged

    def __init__(self, parent=None, use_datetime_axis: bool = True):
        super().__init__(parent)

        self._sensor_data: SensorData | None = None
        self._selection_mode = False
        self._selecting = False
        self._drag_start_x: float | None = None
        self._selection_start_idx: int | None = None
        self._selection_end_idx: int | None = None
        self._selection_region: pg.LinearRegionItem | None = None
        self._use_datetime_axis = use_datetime_axis
        self._x_is_index = False  # True when x-axis is integer row index (e.g. differences mode)
        self._diff_series: dict[tuple[str, str], pd.Series] = {}  # cached for hover display
        self._y_inverted = False
        self._piston_plot_item = None
        self._start_core_line: pg.InfiniteLine | None = None
        self._trip_line: pg.InfiniteLine | None = None
        self._start_pen_line: pg.InfiniteLine | None = None
        self._end_pen_line: pg.InfiniteLine | None = None
        self._pullout_line: pg.InfiniteLine | None = None
        self._seafloor_line: pg.InfiniteLine | None = None
        self._smoothed_plot_items: list = []

        self._setup_ui()

    @property
    def plot_item(self) -> pg.PlotItem:
        """Underlying plot item (for X-axis linking with secondary views)."""
        return self.plot_widget.plotItem

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.info_label = QLabel('')
        self.info_label.setStyleSheet(
            'QLabel { background-color: white; padding: 5px; border: 1px solid gray; }'
        )
        layout.addWidget(self.info_label)

        # No OpenGL: secondary plots hidden in a QStackedWidget render as solid
        # black on first show. Antialiasing is left off because these traces can
        # be hundreds of thousands of samples, where antialiased software
        # rendering costs seconds per repaint.
        pg.setConfigOptions(antialias=False)
        if self._use_datetime_axis:
            date_axis = pg.graphicsItems.DateAxisItem.DateAxisItem(orientation='bottom')
            self.plot_widget = pg.PlotWidget(axisItems={'bottom': date_axis})
        else:
            self.plot_widget = pg.PlotWidget()

        self.plot_widget.setBackground('w')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.addLegend()
        self.plot_widget.setLabel('left', 'Depth (m)')

        self.plot_widget.setDownsampling(auto=True, mode='peak')
        self.plot_widget.setClipToView(True)

        self._vline = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine)
        )
        self._hline = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen('r', width=1, style=Qt.DashLine)
        )
        self.plot_widget.addItem(self._vline, ignoreBounds=True)
        self.plot_widget.addItem(self._hline, ignoreBounds=True)
        self._vline.setVisible(False)
        self._hline.setVisible(False)

        layout.addWidget(self.plot_widget)

        self._mouse_proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_mouse_moved,
        )
        self.plot_widget.scene().sigMouseClicked.connect(self._on_mouse_clicked)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_sensor_data(self, sensor_data: SensorData | None):
        self._sensor_data = sensor_data

    def _get_trace_xy_for_column(
        self,
        sensor_data: SensorData,
        col: str,
        values_override: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray] | tuple[None, None]:
        """Build per-column x/y arrays from rows where the column has data."""
        if col not in sensor_data.df.columns:
            return None, None

        dt_col = sensor_data.datetime_col
        if dt_col not in sensor_data.df.columns:
            return None, None

        # Keep only rows where this sensor column is present to avoid plotting
        # merge-artifact NaN rows from other sensors.
        sub = sensor_data.df[[dt_col, col]].dropna(subset=[dt_col, col])
        if sub.empty:
            return None, None

        x = sub[dt_col].to_numpy(dtype='datetime64[ns]').astype(np.int64) / 1e9
        if values_override is None:
            y = sub[col].to_numpy()
            return x, y

        mask = (sensor_data.df[col].notna() & sensor_data.df[dt_col].notna()).to_numpy()
        y_full = np.asarray(values_override)
        if len(y_full) != len(mask):
            return None, None
        y = y_full[mask]
        if len(y) == 0:
            return None, None
        return x, y

    def plot_depths(self, sensor_data: SensorData | None = None, title: str = ''):
        """Plot depth traces for all sensors."""
        if sensor_data is not None:
            self._sensor_data = sensor_data
        if self._sensor_data is None:
            return

        self._x_is_index = False
        self._diff_series = {}
        self._clear_plot()

        if title:
            self.plot_widget.setTitle(title)
        self.plot_widget.setLabel('left', 'Depth (m)')

        for i, col in enumerate(self._sensor_data.depth_columns):
            x, data = self._get_trace_xy_for_column(self._sensor_data, col)
            if x is None or data is None:
                continue
            pen = pg.mkPen(color=SENSOR_COLORS[i % len(SENSOR_COLORS)], width=2)
            display_name = SensorData.get_location_name(col)
            self.plot_widget.plot(
                x, data, pen=pen, name=display_name,
                connect='finite',
            )

        self._ensure_y_inverted(True)
        self.plot_widget.autoRange()
        self._draw_selection()

    def plot_depths_with_labels(
        self,
        sensor_data: SensorData,
        label_suffix: dict[str, str] | None = None,
        title: str = '',
    ):
        """Plot depths with custom label suffixes (e.g., showing offsets).

        label_suffix keys are depth column names.
        """
        self._sensor_data = sensor_data
        self._x_is_index = False
        self._diff_series = {}
        self._clear_plot()

        if title:
            self.plot_widget.setTitle(title)
        self.plot_widget.setLabel('left', 'Depth (m)')

        for i, col in enumerate(sensor_data.depth_columns):
            x, data = self._get_trace_xy_for_column(sensor_data, col)
            if x is None or data is None:
                continue
            suffix = (label_suffix or {}).get(col, '')
            display_name = SensorData.get_location_name(col)
            name = f'{display_name}{suffix}'
            pen = pg.mkPen(color=SENSOR_COLORS[i % len(SENSOR_COLORS)], width=2)
            self.plot_widget.plot(
                x, data, pen=pen, name=name,
                connect='finite',
            )

        self._ensure_y_inverted(True)
        self.plot_widget.autoRange()
        self._draw_selection()

    def plot_differences(self, sensor_data: SensorData | None = None):
        """Plot pairwise depth differences."""
        if sensor_data is not None:
            self._sensor_data = sensor_data
        if self._sensor_data is None:
            return

        self._clear_plot()
        self.plot_widget.setLabel('left', 'Depth Difference (m)')
        self.plot_widget.setTitle('Sensor Differences')

        self._x_is_index = True
        self._diff_series = self._sensor_data.compute_pairwise_differences()
        x = np.arange(len(self._sensor_data.df))

        for idx, ((col_j, col_i), series) in enumerate(self._diff_series.items()):
            pen = pg.mkPen(
                color=SENSOR_COLORS_QT[idx % len(SENSOR_COLORS_QT)], width=2
            )
            name_j = SensorData.get_short_name(col_j)
            name_i = SensorData.get_short_name(col_i)
            self.plot_widget.plot(
                x, series.values, pen=pen,
                name=f'{name_j} - {name_i}',
                connect='finite',
            )

        pen_zero = pg.mkPen('k', width=1, style=Qt.DashLine)
        self.plot_widget.plot([0, len(self._sensor_data.df) - 1], [0, 0], pen=pen_zero)

        self._ensure_y_inverted(False)
        self.plot_widget.autoRange()
        self._draw_selection()

    def clear(self):
        self._clear_plot()

    def add_trip_line(self, trip_index: int):
        if self._sensor_data is None:
            return

        if self._use_datetime_axis:
            timestamps = self._sensor_data.get_timestamps_epoch()
            if 0 <= trip_index < len(timestamps):
                x_pos = float(timestamps[trip_index])
            else:
                return
        else:
            x_pos = float(trip_index)

        self.remove_trip_line()

        self._trip_line = pg.InfiniteLine(
            pos=x_pos, angle=90, movable=True,
            pen=pg.mkPen('r', width=2, style=Qt.DashLine),
            label='Trip',
            labelOpts={'position': 0.9, 'color': 'r'},
        )
        self._trip_line.sigPositionChangeFinished.connect(self._on_trip_line_moved)
        self.plot_widget.addItem(self._trip_line)

    def remove_trip_line(self):
        if self._trip_line is not None:
            try:
                self._trip_line.sigPositionChangeFinished.disconnect(
                    self._on_trip_line_moved
                )
            except Exception:
                pass
            try:
                self.plot_widget.removeItem(self._trip_line)
            except Exception:
                pass
            self._trip_line = None

    def _snap_to_sample(self, line):
        """Move *line* onto the nearest sample and return that sample index.

        Only the index is persisted, so a line left between samples would be
        redrawn up to half a sample away from where the user dropped it the
        next time the analysis is restored. Snapping makes the position you
        see the position that gets saved.

        Safe to call from a sigPositionChangeFinished handler: setPos only
        emits sigPositionChanged, so this cannot re-enter.
        """
        if line is None or self._sensor_data is None:
            return None
        x_pos = line.value()
        if self._use_datetime_axis:
            timestamps = self._sensor_data.get_timestamps_epoch()
            if len(timestamps) == 0:
                return None
            idx = int(np.argmin(np.abs(timestamps - x_pos)))
            snapped = float(timestamps[idx])
        else:
            idx = max(0, min(int(round(x_pos)), len(self._sensor_data.df) - 1))
            snapped = float(idx)
        if snapped != x_pos:
            line.setValue(snapped)
        return idx

    def _on_trip_line_moved(self):
        idx = self._snap_to_sample(self._trip_line)
        if idx is not None:
            self.trip_line_changed.emit(idx)

    # ------------------------------------------------------------------
    # Piston position helpers
    # ------------------------------------------------------------------

    def add_piston_trace(self, x: np.ndarray, piston_depths: np.ndarray):
        self.remove_piston_trace()
        pen = pg.mkPen(color='#e41a1c', width=2, style=Qt.DashDotLine)
        self._piston_plot_item = self.plot_widget.plot(
            x, piston_depths, pen=pen, name='Piston',
            connect='finite',
        )

    # ------------------------------------------------------------------
    # Smoothed overlay helpers
    # ------------------------------------------------------------------

    def add_smoothed_traces(
        self,
        smoothed_data: dict[str, np.ndarray],
        column_order: list[str],
    ):
        """Overlay bold smoothed traces and fade existing raw traces.

        Parameters
        ----------
        smoothed_data : dict
            depth_column_name -> smoothed depth array.
        column_order : list[str]
            Ordered depth column names (for consistent colour assignment).
        """
        self.remove_smoothed_traces()

        if self._sensor_data is None:
            return

        # Fade existing raw traces (make them transparent)
        for item in self.plot_widget.plotItem.listDataItems():
            cur_pen = item.opts.get('pen')
            if cur_pen is not None and item != self._piston_plot_item:
                color = pg.mkColor(cur_pen.color())
                color.setAlpha(60)
                item.setPen(pg.mkPen(color, width=1))

        # Add prominent smoothed traces
        for col, smoothed in smoothed_data.items():
            x, y = self._get_trace_xy_for_column(
                self._sensor_data,
                col,
                values_override=np.asarray(smoothed),
            )
            if x is None or y is None:
                continue
            idx = column_order.index(col) if col in column_order else 0
            base_color = SENSOR_COLORS[idx % len(SENSOR_COLORS)]
            pen = pg.mkPen(color=base_color, width=3)
            display_name = SensorData.get_location_name(col) + ' (smooth)'
            item = self.plot_widget.plot(
                x, y, pen=pen, name=display_name,
                connect='finite',
            )
            self._smoothed_plot_items.append(item)

    def remove_smoothed_traces(self):
        """Remove all smoothed overlay traces."""
        for item in self._smoothed_plot_items:
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self._smoothed_plot_items.clear()

    def update_piston_trace(self, piston_depths: np.ndarray):
        if self._piston_plot_item is not None and self._sensor_data is not None:
            x = self._sensor_data.get_timestamps_epoch()
            self._piston_plot_item.setData(x, piston_depths)

    def remove_piston_trace(self):
        if self._piston_plot_item is not None:
            try:
                self.plot_widget.removeItem(self._piston_plot_item)
            except Exception:
                pass
            self._piston_plot_item = None

    def add_start_core_line(self, x_pos: float):
        self.remove_start_core_line()
        self._start_core_line = pg.InfiniteLine(
            pos=x_pos, angle=90, movable=True,
            pen=pg.mkPen('#e41a1c', width=2, style=Qt.DashLine),
            label='Start Core',
            labelOpts={'position': 0.9, 'color': '#e41a1c'},
        )
        self._start_core_line.sigPositionChangeFinished.connect(
            self._on_start_core_moved
        )
        self.plot_widget.addItem(self._start_core_line)

    def remove_start_core_line(self):
        if self._start_core_line is not None:
            try:
                self._start_core_line.sigPositionChangeFinished.disconnect(
                    self._on_start_core_moved
                )
            except Exception:
                pass
            try:
                self.plot_widget.removeItem(self._start_core_line)
            except Exception:
                pass
            self._start_core_line = None

    def _on_start_core_moved(self):
        idx = self._snap_to_sample(self._start_core_line)
        if idx is not None:
            self.start_core_changed.emit(idx)

    # ------------------------------------------------------------------
    # Start-penetration line (auto-computed, draggable to override)
    # ------------------------------------------------------------------

    def add_start_pen_line(self, x_pos: float):
        """Add a draggable start-of-penetration indicator line."""
        self.remove_start_pen_line()
        self._start_pen_line = pg.InfiniteLine(
            pos=x_pos, angle=90, movable=True,
            pen=pg.mkPen('#17becf', width=2, style=Qt.DashLine),
            label='Start Pen',
            labelOpts={'position': 0.85, 'color': '#17becf'},
        )
        self._start_pen_line.sigPositionChangeFinished.connect(
            self._on_start_pen_moved
        )
        self.plot_widget.addItem(self._start_pen_line)

    def remove_start_pen_line(self):
        if self._start_pen_line is not None:
            try:
                self._start_pen_line.sigPositionChangeFinished.disconnect(
                    self._on_start_pen_moved
                )
            except Exception:
                pass
            try:
                self.plot_widget.removeItem(self._start_pen_line)
            except Exception:
                pass
            self._start_pen_line = None

    def _on_start_pen_moved(self):
        idx = self._snap_to_sample(self._start_pen_line)
        if idx is not None:
            self.start_pen_changed.emit(idx)

    # ------------------------------------------------------------------
    # Seafloor line (horizontal, non-draggable)
    # ------------------------------------------------------------------

    def add_seafloor_line(self, depth: float, movable: bool = False):
        """Add a horizontal dashed line indicating the seafloor depth."""
        self.remove_seafloor_line()
        self._seafloor_line = pg.InfiniteLine(
            pos=depth, angle=0, movable=movable,
            pen=pg.mkPen('#c0392b', width=1.5, style=Qt.DashLine),
            label=f'Seafloor {depth:.1f} m',
            labelOpts={'position': 0.9, 'color': '#c0392b',
                       'anchors': [(1, 0), (1, 1)]},
        )
        if movable:
            self._seafloor_line.sigPositionChangeFinished.connect(
                self._on_seafloor_moved
            )
        self.plot_widget.addItem(self._seafloor_line)

    def remove_seafloor_line(self):
        if self._seafloor_line is not None:
            try:
                self._seafloor_line.sigPositionChangeFinished.disconnect(
                    self._on_seafloor_moved
                )
            except Exception:
                pass
            try:
                self.plot_widget.removeItem(self._seafloor_line)
            except Exception:
                pass
            self._seafloor_line = None

    def _on_seafloor_moved(self):
        if self._seafloor_line is None:
            return
        depth = float(self._seafloor_line.value())
        # Update the label to reflect the new position
        self._seafloor_line.label.setFormat(f'Seafloor {depth:.1f} m')
        self.seafloor_changed.emit(depth)

    # ------------------------------------------------------------------
    # End-of-penetration line
    # ------------------------------------------------------------------

    def add_end_pen_line(self, x_pos: float):
        """Add a draggable end-of-initial-penetration line."""
        self.remove_end_pen_line()

        self._end_pen_line = pg.InfiniteLine(
            pos=x_pos, angle=90, movable=True,
            pen=pg.mkPen('#ff7f0e', width=2, style=Qt.DashLine),
            label='End Pen',
            labelOpts={'position': 0.8, 'color': '#ff7f0e'},
        )
        self._end_pen_line.sigPositionChangeFinished.connect(
            self._on_end_pen_moved
        )
        self.plot_widget.addItem(self._end_pen_line)

    def remove_end_pen_line(self):
        if self._end_pen_line is not None:
            try:
                self._end_pen_line.sigPositionChangeFinished.disconnect(
                    self._on_end_pen_moved
                )
            except Exception:
                pass
            try:
                self.plot_widget.removeItem(self._end_pen_line)
            except Exception:
                pass
            self._end_pen_line = None

    def _on_end_pen_moved(self):
        idx = self._snap_to_sample(self._end_pen_line)
        if idx is not None:
            self.end_pen_changed.emit(idx)

    # ------------------------------------------------------------------
    # Pullout line
    # ------------------------------------------------------------------

    def add_pullout_line(self, x_pos: float):
        """Add a draggable pullout line."""
        self.remove_pullout_line()

        self._pullout_line = pg.InfiniteLine(
            pos=x_pos, angle=90, movable=True,
            pen=pg.mkPen('#2ca02c', width=2, style=Qt.DashLine),
            label='Pullout',
            labelOpts={'position': 0.7, 'color': '#2ca02c'},
        )
        self._pullout_line.sigPositionChangeFinished.connect(
            self._on_pullout_moved
        )
        self.plot_widget.addItem(self._pullout_line)

    def remove_pullout_line(self):
        if self._pullout_line is not None:
            try:
                self._pullout_line.sigPositionChangeFinished.disconnect(
                    self._on_pullout_moved
                )
            except Exception:
                pass
            try:
                self.plot_widget.removeItem(self._pullout_line)
            except Exception:
                pass
            self._pullout_line = None

    def _on_pullout_moved(self):
        idx = self._snap_to_sample(self._pullout_line)
        if idx is not None:
            self.pullout_changed.emit(idx)

    # ------------------------------------------------------------------
    # Selection mode
    # ------------------------------------------------------------------

    @property
    def selection_mode(self) -> bool:
        return self._selection_mode

    @selection_mode.setter
    def selection_mode(self, enabled: bool):
        self._selection_mode = enabled
        self.plot_widget.plotItem.vb.setMouseEnabled(x=not enabled, y=not enabled)
        if not enabled:
            self._selecting = False

    @property
    def selection(self) -> tuple[int, int] | None:
        if self._selection_start_idx is not None and self._selection_end_idx is not None:
            return (self._selection_start_idx, self._selection_end_idx)
        return None

    def clear_selection(self):
        self._selection_start_idx = None
        self._selection_end_idx = None
        self._selecting = False
        if self._selection_region is not None:
            self.plot_widget.setUpdatesEnabled(False)
            try:
                self.plot_widget.removeItem(self._selection_region)
            except Exception:
                pass
            finally:
                self._selection_region = None
                self.plot_widget.setUpdatesEnabled(True)
        self.selection_cleared.emit()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _clear_plot(self):
        self.plot_widget.setUpdatesEnabled(False)
        try:
            if self._selection_region is not None:
                try:
                    self.plot_widget.removeItem(self._selection_region)
                except Exception:
                    pass
                self._selection_region = None

            self.remove_trip_line()
            self.remove_start_core_line()
            self.remove_end_pen_line()
            self.remove_pullout_line()
            self.remove_start_pen_line()
            self.remove_seafloor_line()
            self._piston_plot_item = None
            self._smoothed_plot_items.clear()

            self.plot_widget.clear()
            self.plot_widget.addLegend()
            self._vline = pg.InfiniteLine(
                angle=90, movable=False,
                pen=pg.mkPen('r', width=1, style=Qt.DashLine),
            )
            self._hline = pg.InfiniteLine(
                angle=0, movable=False,
                pen=pg.mkPen('r', width=1, style=Qt.DashLine),
            )
            self.plot_widget.addItem(self._vline, ignoreBounds=True)
            self.plot_widget.addItem(self._hline, ignoreBounds=True)
            self._vline.setVisible(False)
            self._hline.setVisible(False)
        finally:
            self.plot_widget.setUpdatesEnabled(True)

    def _ensure_y_inverted(self, should_invert: bool):
        if should_invert != self._y_inverted:
            self.plot_widget.invertY(should_invert)
            self._y_inverted = should_invert

    def _draw_selection(self):
        if self._selection_region is not None:
            try:
                self.plot_widget.removeItem(self._selection_region)
            except Exception:
                pass
            self._selection_region = None

        if self._selection_start_idx is None or self._selection_end_idx is None:
            return
        if self._sensor_data is None:
            return

        max_idx = len(self._sensor_data.df) - 1
        start_idx = min(self._selection_start_idx, max_idx)
        end_idx = min(self._selection_end_idx, max_idx)
        if start_idx < 0 or end_idx < 0 or start_idx >= end_idx:
            return

        if self._use_datetime_axis:
            timestamps = self._sensor_data.get_timestamps_epoch()
            start_x = float(timestamps[start_idx])
            end_x = float(timestamps[end_idx])
        else:
            start_x = float(start_idx)
            end_x = float(end_idx)

        self.plot_widget.setUpdatesEnabled(False)
        try:
            self._selection_region = pg.LinearRegionItem(
                values=[start_x, end_x],
                brush=pg.mkBrush(255, 0, 0, 50),
                movable=False,
            )
            self.plot_widget.addItem(self._selection_region)
        finally:
            self.plot_widget.setUpdatesEnabled(True)

    def _on_mouse_moved(self, evt):
        if self._sensor_data is None:
            return

        pos = evt[0]
        if not self.plot_widget.sceneBoundingRect().contains(pos):
            return

        mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
        x_pos = mouse_point.x()
        y_pos = mouse_point.y()

        self._vline.setPos(x_pos)
        self._hline.setPos(y_pos)
        self._vline.setVisible(True)
        self._hline.setVisible(True)

        if self._x_is_index or not self._use_datetime_axis:
            idx = max(0, min(int(round(x_pos)), len(self._sensor_data.df) - 1))
        else:
            timestamps = self._sensor_data.get_timestamps_epoch()
            idx = int(np.argmin(np.abs(timestamps - x_pos)))

        if 0 <= idx < len(self._sensor_data.df):
            actual_time = self._sensor_data.df[self._sensor_data.datetime_col].iloc[idx]
            time_str = actual_time.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(actual_time) else 'N/A'
            info_text = f"Index: {idx}  |  Time: {time_str}  |  "

            if self._x_is_index and self._diff_series:
                for (col_j, col_i), series in self._diff_series.items():
                    val = series.iloc[idx]
                    if pd.notna(val):
                        name_j = SensorData.get_short_name(col_j)
                        name_i = SensorData.get_short_name(col_i)
                        info_text += f"{name_j}-{name_i}: {val:+.4f}m  "
            else:
                for col in self._sensor_data.depth_columns:
                    if col in self._sensor_data.df.columns:
                        val = self._sensor_data.df[col].iloc[idx]
                        if pd.notna(val):
                            loc_name = SensorData.get_location_name(col)
                            info_text += f"{loc_name}: {val:.3f}m  "

            self.info_label.setText(info_text)

    def _on_mouse_clicked(self, event):
        if self._sensor_data is None or not self._selection_mode:
            return

        if event.double():
            pos = event.scenePos()
            mouse_point = self.plot_widget.plotItem.vb.mapSceneToView(pos)
            x = mouse_point.x()

            if not self._selecting:
                self._selecting = True
                self._drag_start_x = x
            else:
                self._selecting = False
                start_x = min(self._drag_start_x, x)
                end_x = max(self._drag_start_x, x)

                if self._use_datetime_axis:
                    timestamps = self._sensor_data.get_timestamps_epoch()
                    self._selection_start_idx = int(np.argmin(np.abs(timestamps - start_x)))
                    self._selection_end_idx = int(np.argmin(np.abs(timestamps - end_x)))
                else:
                    self._selection_start_idx = max(0, int(start_x))
                    self._selection_end_idx = min(
                        len(self._sensor_data.df) - 1, int(end_x)
                    )

                self._draw_selection()
                self.selection_changed.emit(
                    self._selection_start_idx, self._selection_end_idx
                )
