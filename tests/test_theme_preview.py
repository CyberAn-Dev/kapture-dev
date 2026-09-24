"""The appearance picker previews without saving until OK is pressed."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_CURRENT_DESKTOP"] = "ubuntu:GNOME"

from PyQt5 import QtCore, QtWidgets

import kapture


class ThemePreviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_dir = tempfile.TemporaryDirectory()
        os.environ["XDG_CONFIG_HOME"] = cls.config_dir.name
        cls.app = QtWidgets.QApplication([])
        cls.app.setStyle("Fusion")

    @classmethod
    def tearDownClass(cls):
        cls.config_dir.cleanup()

    def setUp(self):
        self.desktop_patch = mock.patch.object(kapture, "write_desktop_entry")
        self.desktop_patch.start()
        settings = QtCore.QSettings("ScrollShot", "ScrollShot")
        settings.clear()
        settings.setValue("ui_theme", "dark")
        settings.setValue("ui_accent", "theme")
        self.window = kapture.MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_selection_previews_both_windows_cancel_restores_and_ok_saves(self):
        self.assertEqual(self.window.grab().toImage().pixelColor(10, 10).name(), "#1b1b20")

        def select_light(dialog):
            tabs = dialog.findChild(QtWidgets.QTabWidget)
            tabs.setCurrentIndex(tabs.count() - 1)
            dialog.show()
            self.app.processEvents()
            theme = next(combo for combo in dialog.findChildren(QtWidgets.QComboBox)
                         if combo.findData("light") >= 0)
            theme.setCurrentIndex(theme.findData("light"))
            self.app.processEvents()
            self.assertEqual(self.window.grab().toImage().pixelColor(10, 10).name(),
                             "#f5f5f7")
            self.assertEqual(dialog.grab().toImage().pixelColor(200, 200).name(),
                             "#ffffff")
            self.assertEqual(self.window.settings.value("ui_theme"), "dark")
            return result

        result = QtWidgets.QDialog.Rejected
        with mock.patch.object(QtWidgets.QDialog, "exec_", select_light):
            self.window.show_settings()
        self.app.processEvents()
        self.assertEqual(self.window.grab().toImage().pixelColor(10, 10).name(), "#1b1b20")
        self.assertEqual(self.window.settings.value("ui_theme"), "dark")

        result = QtWidgets.QDialog.Accepted
        with mock.patch.object(QtWidgets.QDialog, "exec_", select_light):
            self.window.show_settings()
        self.assertEqual(self.window.settings.value("ui_theme"), "light")
        self.assertEqual(self.window.grab().toImage().pixelColor(10, 10).name(), "#f5f5f7")


if __name__ == "__main__":
    unittest.main()
