"""Theme choices and default-width toolbar usability."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtWidgets

import kapture


class ThemeLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_dir = tempfile.TemporaryDirectory()
        os.environ["XDG_CONFIG_HOME"] = cls.config_dir.name
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setStyle("Fusion")

    @classmethod
    def tearDownClass(cls):
        cls.config_dir.cleanup()

    def setUp(self):
        self.desktop_patch = mock.patch.object(kapture, "write_desktop_entry")
        self.desktop_patch.start()
        QtCore.QSettings("ScrollShot", "ScrollShot").clear()
        self.window = kapture.MainWindow()
        self.window.resize(820, 660)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_new_dark_themes_are_selectable_and_preview_their_backgrounds(self):
        def inspect(dialog):
            dialog.show()
            self.app.processEvents()
            theme = next(combo for combo in dialog.findChildren(QtWidgets.QComboBox)
                         if combo.findData("dark") >= 0)
            for key, expected in (("one_dark_pro_darker", "#1e2227"),
                                  ("vitesse_dark", "#121212")):
                index = theme.findData(key)
                self.assertGreaterEqual(index, 0, key)
                theme.setCurrentIndex(index)
                self.app.processEvents()
                actual = self.window.grab().toImage().pixelColor(10, 10).name()
                self.assertEqual(actual, expected)
            dialog.close()
            return QtWidgets.QDialog.Rejected

        with mock.patch.object(QtWidgets.QDialog, "exec_", inspect):
            self.window.show_settings()

    def test_default_width_keeps_save_and_settings_buttons_visible(self):
        self.assertLessEqual(self.window.width(), 820)
        for button in (self.window.btn_save, self.window.btn_settings):
            right = button.mapTo(self.window, QtCore.QPoint(0, 0)).x() + button.width()
            self.assertLessEqual(right, self.window.width() - 10)


if __name__ == "__main__":
    unittest.main()
