"""
StatisticsTableView - Table for collecting statistics in Create Calibration mode.
"""
from __future__ import annotations

import pandas as pd

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView,
)
from PySide6.QtCore import Signal

from ...domain.models.sensor_data import SensorData
from ...domain.models.analysis_result import StatisticsResult


class StatisticsTableView(QWidget):
    """
    Table widget displaying collected statistics rows.

    Signals:
        row_removed(int): Emitted when a row is removed.
        cleared: Emitted when all rows are cleared.
    """

    row_removed = Signal(int)
    cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stats: list[StatisticsResult] = []
        self._columns: list[str] = []
        self._depth_columns: list[str] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget()
        self.table.setMinimumHeight(120)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self._remove_selected)
        btn_layout.addWidget(self.remove_btn)

        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self._clear_all)
        btn_layout.addWidget(self.clear_btn)

        self.count_label = QLabel("Stats collected: 0 data points")
        btn_layout.addWidget(self.count_label)
        btn_layout.addStretch()

        layout.addLayout(btn_layout)

    def set_columns(self, depth_columns: list[str]):
        """Configure table columns based on depth column names."""
        self._depth_columns = list(depth_columns)
        cols = ['#', 'Mean Depth']

        for i, col_i in enumerate(depth_columns):
            for j in range(i + 1, len(depth_columns)):
                col_j = depth_columns[j]
                short_j = SensorData.get_short_name(col_j)
                short_i = SensorData.get_short_name(col_i)
                cols.append(f'{short_j}-{short_i}')

        cols.extend(['N Points', 'Source File'])
        self._columns = cols

        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def add_statistics(self, stats: StatisticsResult):
        self._stats.append(stats)
        self._refresh_table()

    @property
    def statistics(self) -> list[StatisticsResult]:
        return list(self._stats)

    @property
    def count(self) -> int:
        return len(self._stats)

    def _refresh_table(self):
        self.table.setRowCount(len(self._stats))
        for row_idx, stats in enumerate(self._stats):
            col_idx = 0
            # Row number
            self.table.setItem(row_idx, col_idx, QTableWidgetItem(str(row_idx + 1)))
            col_idx += 1
            # Mean depth
            self.table.setItem(row_idx, col_idx, QTableWidgetItem(f"{stats.mean_depth_all_sensors:.1f}"))
            col_idx += 1
            # Differences
            for (j, i), val in stats.difference_means.items():
                self.table.setItem(row_idx, col_idx, QTableWidgetItem(f"{val:.4f}"))
                col_idx += 1
            # N points
            self.table.setItem(row_idx, col_idx, QTableWidgetItem(str(stats.n_points)))
            col_idx += 1
            # Source
            self.table.setItem(row_idx, col_idx, QTableWidgetItem(stats.source_file))
            col_idx += 1

        self.count_label.setText(f"Stats collected: {len(self._stats)} data points")

    def _remove_selected(self):
        rows = sorted(set(item.row() for item in self.table.selectedItems()), reverse=True)
        for row in rows:
            if 0 <= row < len(self._stats):
                self._stats.pop(row)
                self.row_removed.emit(row)
        self._refresh_table()

    def _clear_all(self):
        self._stats.clear()
        self._refresh_table()
        self.cleared.emit()

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([s.to_flat_dict() for s in self._stats])
