"""PyQtGraph secondary view for Predict mode recoil curves."""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget, QLabel

from ...domain.processing.predict import CURVE_LABELS
from ...domain.processing.predict_overlay import ActualOverlay


def _brush(hex_color: str, alpha: int) -> pg.mkBrush:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return pg.mkBrush(c)


def _pen(hex_color: str, width: float = 2.0, style=None) -> pg.mkPen:
    return pg.mkPen(hex_color, width=width, style=style)


class PredictPlotView(QWidget):
    """Time-series bands for corer, release, and piston (matches app pyqtgraph style)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.metrics_label = QLabel("Run a prediction to see curves and piston altitudes.")
        self.metrics_label.setWordWrap(True)
        self.metrics_label.setStyleSheet(
            "QLabel { background-color: white; padding: 8px; "
            "border-bottom: 1px solid #ccc; font-size: 11pt; }"
        )
        layout.addWidget(self.metrics_label)

        self._graphics = pg.GraphicsLayoutWidget()
        self._graphics.setBackground("w")
        layout.addWidget(self._graphics)

    def clear(self) -> None:
        self._graphics.clear()
        self.metrics_label.setText("Run a prediction to see curves and piston altitudes.")

    def show_prediction(
        self,
        result: dict,
        selected_curves: list[str],
        show_piston: bool,
        show_trigger: bool = True,
        overlay: ActualOverlay | None = None,
    ) -> None:
        self._graphics.clear()
        self._update_metrics_label(result, selected_curves, overlay)

        time = result["time"]
        corer = result["corer_bands"]
        seafloor_rel = float(result["seafloor_relative_m"])
        event_summary = result["event_summary"].set_index("curve_type")

        n = len(selected_curves)
        cols = 2 if n > 1 else 1
        rows = int(math.ceil(n / cols))

        trigger = result.get("trigger_bands")
        y_values = [corer[10].min(), corer[90].max(), seafloor_rel]
        if show_trigger and trigger is not None:
            y_values.extend([trigger[10].min(), trigger[90].max()])
        for curve in selected_curves:
            rel = result["release_bands"][curve]
            y_values.extend([rel[10].min(), rel[90].max()])
            if show_piston:
                pist = result["piston_bands"][curve]
                y_values.extend([pist[10].min(), pist[90].max()])
        y_min = float(np.nanmin(y_values)) - 0.5
        y_max = float(np.nanmax(y_values)) + 0.75

        for idx, curve in enumerate(selected_curves):
            row, col = divmod(idx, cols)
            plot = self._graphics.addPlot(row=row, col=col)
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.setLabel("bottom", "Time relative to trip (s)")
            plot.setLabel("left", "Relative depth (m)")
            plot.invertY(True)
            plot.setXRange(float(time[0]), float(time[-1]), padding=0.02)
            plot.setYRange(y_max, y_min)

            title = CURVE_LABELS[curve]
            if curve == "gamma_pulse":
                title += " (sparse training data — low confidence)"
            plot.setTitle(title, color="k", size="10pt")

            self._add_band(plot, time, corer[10], corer[90], "#e6550d", 40)
            plot.plot(time, corer[50], pen=_pen("#e6550d", 2.6))

            if show_trigger and trigger is not None:
                self._add_band(plot, time, trigger[10], trigger[90], "#41ab5d", 35)
                plot.plot(time, trigger[50], pen=_pen("#238b45", 2.2))

            release = result["release_bands"][curve]
            self._add_band(plot, time, release[10], release[90], "#3182bd", 45)
            plot.plot(time, release[50], pen=_pen("#3182bd", 2.4))

            if show_piston:
                piston = result["piston_bands"][curve]
                self._add_band(plot, time, piston[10], piston[90], "#756bb1", 35)
                plot.plot(time, piston[50], pen=_pen("#756bb1", 2.2))

            if overlay is not None:
                self._plot_actual_overlay(plot, overlay, show_piston, show_trigger)

            plot.addItem(pg.InfiniteLine(0.0, angle=90, pen=_pen("#000000", 1.0, style=Qt.DashLine)))
            plot.addItem(
                pg.InfiniteLine(seafloor_rel, angle=0, pen=_pen("#444444", 1.5, style=Qt.DotLine))
            )

            ev_row = event_summary.loc[curve] if curve in event_summary.index else None
            if ev_row is not None:
                sc_t = ev_row["start_core_time_median_s"]
                sp_t = ev_row["start_pen_time_median_s"]
                if np.isfinite(sc_t):
                    plot.addItem(
                        pg.InfiniteLine(float(sc_t), angle=90, pen=_pen("#2ca02c", 1.7, style=Qt.DashDotLine))
                    )
                if np.isfinite(sp_t):
                    plot.addItem(
                        pg.InfiniteLine(float(sp_t), angle=90, pen=_pen("#984ea3", 1.7, style=Qt.DashDotLine))
                    )
                self._add_event_line_legend(plot, ev_row)

            self._annotate_panel_events(plot, ev_row)

    @staticmethod
    def _plot_actual_overlay(
        plot,
        overlay: ActualOverlay,
        show_piston: bool,
        show_trigger: bool,
    ) -> None:
        t = overlay.time
        actual_pen = _pen("#000000", 2.2, style=Qt.DashLine)
        plot.plot(t, overlay.corer_rel, pen=actual_pen, name="Actual WS")
        plot.plot(t, overlay.release_rel, pen=_pen("#08519c", 2.2, style=Qt.DashLine))
        if show_trigger and overlay.trigger_rel is not None:
            plot.plot(t, overlay.trigger_rel, pen=_pen("#006d2c", 2.2, style=Qt.DashLine))
        if show_piston and overlay.piston_rel is not None:
            plot.plot(t, overlay.piston_rel, pen=_pen("#54278f", 2.0, style=Qt.DashLine))

    @staticmethod
    def _add_band(plot, x, y_low, y_high, color: str, alpha: int) -> None:
        low = pg.PlotDataItem(x, y_low, pen=None)
        high = pg.PlotDataItem(x, y_high, pen=None)
        plot.addItem(low)
        plot.addItem(high)
        plot.addItem(pg.FillBetweenItem(low, high, brush=_brush(color, alpha)))

    @staticmethod
    def _add_event_line_legend(plot, ev_row) -> None:
        sc_t = ev_row.get("start_core_time_median_s", np.nan)
        sp_t = ev_row.get("start_pen_time_median_s", np.nan)
        if not (np.isfinite(sc_t) or np.isfinite(sp_t)):
            return
        legend = plot.addLegend(offset=(8, 8))
        if np.isfinite(sc_t):
            legend.addItem(
                pg.PlotCurveItem([], [], pen=_pen("#2ca02c", 1.7, style=Qt.DashDotLine)),
                "Start core",
            )
        if np.isfinite(sp_t):
            legend.addItem(
                pg.PlotCurveItem([], [], pen=_pen("#984ea3", 1.7, style=Qt.DashDotLine)),
                "Start pen",
            )

    @staticmethod
    def _annotate_panel_events(plot, ev_row) -> None:
        if ev_row is None:
            return
        alt_core = ev_row.get("piston_alt_start_core_median_m", np.nan)
        alt_pen = ev_row.get("piston_alt_start_pen_median_m", np.nan)
        lines = []
        if np.isfinite(alt_core):
            lines.append(f"PA@start core: {alt_core:.2f} m")
        else:
            lines.append("PA@start core: —")
        if np.isfinite(alt_pen):
            lines.append(f"PA@start pen: {alt_pen:.2f} m")
        else:
            lines.append("PA@start pen: —")
        text = pg.TextItem(
            "<br>".join(lines),
            anchor=(0, 0),
            color="#333333",
            fill=pg.mkBrush(255, 255, 255, 200),
        )
        x_range, y_range = plot.getViewBox().viewRange()
        y_span = y_range[1] - y_range[0]
        # Sit below the event-line legend in the top-left corner.
        text.setPos(x_range[0], y_range[0] + 0.12 * y_span)
        plot.addItem(text)

    def _update_metrics_label(
        self,
        result: dict,
        selected_curves: list[str],
        overlay: ActualOverlay | None = None,
    ) -> None:
        summary = result["event_summary"].set_index("curve_type")
        seafloor = float(result["seafloor_m"])
        lines = [
            f"<b>Estimated seafloor:</b> {seafloor:.2f} m abs "
            f"({result['seafloor_relative_m']:+.2f} m rel. corer @ trip)",
        ]
        if overlay is not None:
            lines.append(self._trigger_line_html(result, overlay))
        lines.append("")

        if len(selected_curves) == 1:
            curve = selected_curves[0]
            label = CURVE_LABELS.get(curve, curve)
            if curve in summary.index:
                row = summary.loc[curve]
                lines.append(f"<b>{label}</b>")
                lines.append(self._metrics_html(row))
            self.metrics_label.setText("<br>".join(lines))
            return

        lines.append("<b>Piston altitude (median across v0 ensemble)</b>")
        lines.append(
            "<table cellspacing='4'>"
            "<tr><th align='left'>Curve</th>"
            "<th align='right'>@ start core</th>"
            "<th align='right'>@ start penetration</th></tr>"
        )
        for curve in selected_curves:
            label = CURVE_LABELS.get(curve, curve)
            if curve not in summary.index:
                continue
            row = summary.loc[curve]
            alt_core = row["piston_alt_start_core_median_m"]
            alt_pen = row["piston_alt_start_pen_median_m"]
            core_txt = f"{alt_core:.2f} m" if np.isfinite(alt_core) else "—"
            pen_txt = f"{alt_pen:.2f} m" if np.isfinite(alt_pen) else "—"
            lines.append(
                f"<tr><td>{label}</td><td align='right'><b>{core_txt}</b></td>"
                f"<td align='right'><b>{pen_txt}</b></td></tr>"
            )
        lines.append("</table>")
        self.metrics_label.setText("".join(lines))

    @staticmethod
    def _trigger_line_html(result: dict, overlay: ActualOverlay) -> str:
        model_ft = float(result["inputs"].trigger_line_length_ft)
        planned = overlay.planned_trigger_line_ft
        effective = overlay.effective_trigger_line_ft
        parts = [f"<b>Trigger line (ft):</b> model input {model_ft:.2f}"]
        if planned is not None and np.isfinite(planned):
            parts.append(f"planned {planned:.2f}")
        if effective is not None and np.isfinite(effective):
            parts.append(f"measured {effective:.2f}")
            if planned is not None and np.isfinite(planned):
                delta = effective - planned
                parts.append(f"Δ(meas−plan) {delta:+.2f}")
            delta_model = effective - model_ft
            parts.append(f"Δ(meas−model) {delta_model:+.2f}")
        else:
            parts.append("measured — (no trigger sensor at trip)")
        return " | ".join(parts)

    @staticmethod
    def _metrics_html(row) -> str:
        alt_core = row["piston_alt_start_core_median_m"]
        alt_pen = row["piston_alt_start_pen_median_m"]
        core_txt = f"{alt_core:.2f} m" if np.isfinite(alt_core) else "not detected"
        pen_txt = f"{alt_pen:.2f} m" if np.isfinite(alt_pen) else "not detected"
        t_core = row["start_core_time_median_s"]
        t_pen = row["start_pen_time_median_s"]
        t_core_txt = f"{t_core:.3f} s" if np.isfinite(t_core) else "—"
        t_pen_txt = f"{t_pen:.3f} s" if np.isfinite(t_pen) else "—"
        return (
            f"<b>Piston altitude at start core:</b> {core_txt} "
            f"(t = {t_core_txt})<br>"
            f"<b>Piston altitude at start penetration:</b> {pen_txt} "
            f"(t = {t_pen_txt})"
        )
