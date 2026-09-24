"""Sensorius standalone entry point: python -m sensor_standalone"""
import sys

from pyqtgraph.Qt import QtWidgets

from .gui.main_window import MainWindow, install_excepthook


def main():
    install_excepthook()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
