"""
ViewDataPanel - Control panel for the "View Data" mode.

Provides file loading, basic data display, and plot controls.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGridLayout,
)
from PySide6.QtCore import Signal

from .base_panel import BaseModePanel
from ..widgets.log_widget import LogWidget


class ViewDataPanel(BaseModePanel):
    """
    Panel for the View Data mode.
    
    Signals:
        load_file_requested(str): filepath selected by user.
        plot_depths_requested: User wants to plot depths.
        plot_differences_requested: User wants to plot differences.
    """

    load_file_requested = Signal(str)
    plot_depths_requested = Signal()
    plot_differences_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Data info
        info_group = QGroupBox("Data Information")
        info_layout = QVBoxLayout()
        self.file_label = QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        info_layout.addWidget(self.file_label)

        self.data_info_label = QLabel("")
        self.data_info_label.setWordWrap(True)
        info_layout.addWidget(self.data_info_label)

        info_group.setLayout(info_layout)
        self._layout.addWidget(info_group)

        # Plot controls
        plot_group = QGroupBox("Plot Controls")
        plot_layout = QVBoxLayout()

        depths_btn = QPushButton("Plot Depths")
        depths_btn.clicked.connect(self.plot_depths_requested.emit)
        plot_layout.addWidget(depths_btn)

        diff_btn = QPushButton("Plot Differences")
        diff_btn.clicked.connect(self.plot_differences_requested.emit)
        plot_layout.addWidget(diff_btn)

        plot_group.setLayout(plot_layout)
        self._layout.addWidget(plot_group)

        # Log
        self.log_widget = LogWidget("Log", max_height=200)
        self._layout.addWidget(self.log_widget)

        self._finish_layout()

    def update_file_info(self, filename: str, sensors: int, rows: int,
                         time_range: str = '', depth_range: str = '',
                         core_title: str = ''):
        """Update the file info display."""
        self.file_label.setText(f"File: {filename}")
        info = f"Sensors: {sensors}  |  Rows: {rows:,}"
        if time_range:
            info += f"\nTime: {time_range}"
        if depth_range:
            info += f"\nDepth: {depth_range}"
        if core_title:
            info += f"\nCore: {core_title}"
        self.data_info_label.setText(info)
