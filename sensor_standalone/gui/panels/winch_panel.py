"""
WinchPanel - Control panel for the "Winch" mode.

Provides auto (core-overlap) and manual winch file selection, plus
configuration for one or two winch plot windows.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QPushButton, QListWidget, QAbstractItemView,
    QRadioButton, QButtonGroup, QSpinBox, QDoubleSpinBox,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget


class WinchPanel(BaseModePanel):
    """
    Panel for Winch mode.

    Signals
    -------
    reload_requested
        User clicked reload or changed data-source settings.
    plot_settings_changed
        Column or window-count selection changed.
    detect_winch_trip_requested
        User clicked detect winch trip.
    align_winch_requested
        User clicked align winch data.
    reset_winch_requested
        User clicked reset winch alignment/detection.
    search_region_toggled(bool)
        User toggled the search window visibility checkbox.
    """

    reload_requested = Signal()
    plot_settings_changed = Signal()
    detect_winch_trip_requested = Signal()
    align_winch_requested = Signal()
    reset_winch_requested = Signal()
    search_region_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._winch_files: list[dict] = []
        self._auto_file_names: list[str] = []
        self._parameters: list[str] = []

        # -- Data source -------------------------------------------------
        source_group = QGroupBox('Winch Data Source')
        source_layout = QVBoxLayout()

        self.auto_status_label = QLabel('Auto: no core selected')
        self.auto_status_label.setWordWrap(True)
        source_layout.addWidget(self.auto_status_label)

        self.use_auto_radio = QRadioButton('Use auto (core overlap)')
        self.use_manual_radio = QRadioButton('Use manual file selection')
        self.use_auto_radio.setChecked(True)
        source_btn_group = QButtonGroup(self)
        source_btn_group.addButton(self.use_auto_radio)
        source_btn_group.addButton(self.use_manual_radio)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.use_auto_radio)
        mode_row.addWidget(self.use_manual_radio)
        mode_row.addStretch()
        source_layout.addLayout(mode_row)

        self.manual_group_box = QGroupBox('Manual Selection')
        manual_layout = QVBoxLayout()

        self.winch_file_list = QListWidget()
        self.winch_file_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.winch_file_list.setMinimumHeight(120)
        self.winch_file_list.setEnabled(False)
        manual_layout.addWidget(QLabel('Winch files (cruise):'))
        manual_layout.addWidget(self.winch_file_list)

        self.manual_group_box.setLayout(manual_layout)
        source_layout.addWidget(self.manual_group_box)

        btn_row = QHBoxLayout()
        self.reload_btn = QPushButton('Reload Winch Data')
        btn_row.addWidget(self.reload_btn)
        btn_row.addStretch()
        source_layout.addLayout(btn_row)

        source_group.setLayout(source_layout)
        self._layout.addWidget(source_group)

        # -- Plot windows ------------------------------------------------
        plot_group = QGroupBox('Winch Plots')
        plot_layout = QVBoxLayout()

        row1 = QHBoxLayout()
        row1.addWidget(QLabel('Window 1 column:'))
        self.column1_combo = QComboBox()
        self.column1_combo.setMinimumWidth(180)
        row1.addWidget(self.column1_combo)
        row1.addStretch()
        plot_layout.addLayout(row1)

        self.second_window_check = QCheckBox('Show second window')
        plot_layout.addWidget(self.second_window_check)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel('Window 2 column:'))
        self.column2_combo = QComboBox()
        self.column2_combo.setMinimumWidth(180)
        self.column2_combo.setEnabled(False)
        row2.addWidget(self.column2_combo)
        row2.addStretch()
        plot_layout.addLayout(row2)

        plot_group.setLayout(plot_layout)
        self._layout.addWidget(plot_group)

        # -- Winch trip detection & alignment -----------------------------
        align_group = QGroupBox('Winch Trip & Alignment')
        align_layout = QVBoxLayout()

        param_row = QHBoxLayout()
        param_row.addWidget(QLabel('Edge buffer (samples):'))
        self.edge_buffer_spin = QSpinBox()
        self.edge_buffer_spin.setRange(0, 100000)
        self.edge_buffer_spin.setValue(500)
        param_row.addWidget(self.edge_buffer_spin)

        param_row.addWidget(QLabel('Drop threshold:'))
        self.drop_threshold_spin = QDoubleSpinBox()
        self.drop_threshold_spin.setRange(0.0, 1e9)
        self.drop_threshold_spin.setDecimals(1)
        self.drop_threshold_spin.setValue(1000.0)
        self.drop_threshold_spin.setSingleStep(100.0)
        param_row.addWidget(self.drop_threshold_spin)
        param_row.addStretch()
        align_layout.addLayout(param_row)

        self.search_window_label = QLabel(
            'Search window: enable checkbox to adjust on winch plot (window 1)'
        )
        self.search_window_label.setWordWrap(True)
        align_layout.addWidget(self.search_window_label)

        self.show_search_region_check = QCheckBox('Show search window on plot')
        self.show_search_region_check.setChecked(False)
        align_layout.addWidget(self.show_search_region_check)

        detect_row = QHBoxLayout()
        self.detect_trip_btn = QPushButton('Detect Winch Trip')
        detect_row.addWidget(self.detect_trip_btn)
        detect_row.addStretch()
        align_layout.addLayout(detect_row)

        self.winch_trip_status_label = QLabel('Winch trip: not detected')
        self.winch_trip_status_label.setWordWrap(True)
        align_layout.addWidget(self.winch_trip_status_label)

        self.sensor_trip_status_label = QLabel('Sensor trip: not set')
        self.sensor_trip_status_label.setWordWrap(True)
        align_layout.addWidget(self.sensor_trip_status_label)

        align_row = QHBoxLayout()
        self.align_btn = QPushButton('Align Winch Data')
        self.reset_btn = QPushButton('Reset Winch')
        align_row.addWidget(self.align_btn)
        align_row.addWidget(self.reset_btn)
        align_row.addStretch()
        align_layout.addLayout(align_row)

        self.alignment_status_label = QLabel('Alignment: none')
        self.alignment_status_label.setWordWrap(True)
        align_layout.addWidget(self.alignment_status_label)

        align_group.setLayout(align_layout)
        self._layout.addWidget(align_group)

        # -- Log ---------------------------------------------------------
        self.log_widget = LogWidget()
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

        self.reload_btn.clicked.connect(self.reload_requested.emit)
        self.use_auto_radio.toggled.connect(self._on_source_mode_changed)
        self.use_manual_radio.toggled.connect(self._on_source_mode_changed)
        self.winch_file_list.itemSelectionChanged.connect(self.reload_requested.emit)
        self.column1_combo.currentTextChanged.connect(self._on_plot_column_changed)
        self.column2_combo.currentTextChanged.connect(self._on_plot_column_changed)
        self.second_window_check.toggled.connect(self._on_second_window_toggled)
        self.detect_trip_btn.clicked.connect(self.detect_winch_trip_requested.emit)
        self.align_btn.clicked.connect(self.align_winch_requested.emit)
        self.reset_btn.clicked.connect(self.reset_winch_requested.emit)
        self.show_search_region_check.toggled.connect(
            self.search_region_toggled.emit
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_cruise_winch_files(self, files: list[dict]) -> None:
        """Populate the manual file list for the current cruise."""
        self._winch_files = files
        self.winch_file_list.blockSignals(True)
        self.winch_file_list.clear()
        for f in files:
            label = f['file_name']
            if f.get('start_time') is not None:
                label += f"  ({f['start_time']} – {f['end_time']})"
            self.winch_file_list.addItem(label)
        self.winch_file_list.blockSignals(False)

    def set_auto_status(
        self,
        file_names: list[str],
        has_data: bool,
        core_name: str = '',
    ) -> None:
        """Update the auto-load status readout."""
        self._auto_file_names = file_names
        if not core_name:
            self.auto_status_label.setText('Auto: no core selected')
            return
        if has_data and file_names:
            files_str = ', '.join(file_names)
            self.auto_status_label.setText(
                f'Auto ({core_name}): {len(file_names)} file(s) — {files_str}'
            )
        else:
            self.auto_status_label.setText(
                f'Auto ({core_name}): no overlapping winch files found'
            )

    def set_parameters(self, params: list[str]) -> None:
        """Refresh column dropdowns."""
        self._parameters = params
        for combo, current in (
            (self.column1_combo, self.column1_combo.currentText()),
            (self.column2_combo, self.column2_combo.currentText()),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(params)
            if current in params:
                combo.setCurrentText(current)
            elif params:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

    def uses_manual_selection(self) -> bool:
        return self.use_manual_radio.isChecked()

    def get_selected_winch_file_ids(self) -> list[int]:
        ids: list[int] = []
        for item in self.winch_file_list.selectedItems():
            row = self.winch_file_list.row(item)
            if 0 <= row < len(self._winch_files):
                ids.append(self._winch_files[row]['winch_file_id'])
        return ids

    def get_column_1(self) -> Optional[str]:
        text = self.column1_combo.currentText()
        return text or None

    def get_column_2(self) -> Optional[str]:
        text = self.column2_combo.currentText()
        return text or None

    def show_second_window(self) -> bool:
        return self.second_window_check.isChecked()

    def update_file_info(self, text: str) -> None:
        pass  # reserved for parity with other panels

    def get_edge_buffer(self) -> int:
        return self.edge_buffer_spin.value()

    def get_drop_threshold(self) -> float:
        return self.drop_threshold_spin.value()

    def set_search_window_label(self, text: str) -> None:
        self.search_window_label.setText(text)

    def set_winch_trip_status(self, text: str) -> None:
        self.winch_trip_status_label.setText(text)

    def set_sensor_trip_status(self, text: str) -> None:
        self.sensor_trip_status_label.setText(text)

    def set_alignment_status(self, text: str) -> None:
        self.alignment_status_label.setText(text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_source_mode_changed(self, _checked: bool = False) -> None:
        manual = self.uses_manual_selection()
        self.winch_file_list.setEnabled(manual)
        self.reload_requested.emit()

    def _on_plot_column_changed(self, _text: str = '') -> None:
        """Re-emit plot_settings_changed without forwarding combo text."""
        self.plot_settings_changed.emit()

    def _on_second_window_toggled(self, checked: bool) -> None:
        self.column2_combo.setEnabled(checked)
        self.plot_settings_changed.emit()
