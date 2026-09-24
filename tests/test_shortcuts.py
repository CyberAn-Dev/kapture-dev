"""Global shortcut setup and tray-first startup behavior."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtGui, QtWidgets

import kapture


class ShortcutTest(unittest.TestCase):
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
        self.settings = QtCore.QSettings("ScrollShot", "ScrollShot")
        self.settings.clear()
        self.window = kapture.MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_gnome_key_combination_is_an_accelerator(self):
        sequence = QtGui.QKeySequence("Ctrl+Alt+K")
        self.assertEqual(kapture.gnome_accelerator(sequence), "<Control><Alt>k")
        self.assertEqual(kapture.gnome_key_sequence("<Control><Alt>k"), sequence)

    def test_gnome_shortcuts_preserve_other_custom_entries(self):
        with tempfile.TemporaryDirectory() as config_dir, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config_dir, "GSETTINGS_BACKEND": "keyfile"}):
            other = kapture.GNOME_CUSTOM_ROOT + "other-app/"
            kapture._gsettings("set", kapture.GNOME_MEDIA_SCHEMA,
                                "custom-keybindings", repr([other]))
            command = "/opt/kapture/run.sh --region"
            kapture.gnome_set_shortcuts([
                ("Region capture", "--region", command, "<Control><Alt>k")])
            paths = kapture._gnome_paths()
            self.assertEqual(paths, [other, kapture._gnome_path("--region")])
            self.assertEqual(kapture.gnome_current_key("--region"), "<Control><Alt>k")
            kapture.gnome_set_shortcuts([
                ("Region capture", "--region", command, "")])
            self.assertEqual(kapture._gnome_paths(), [other])

    def test_settings_show_shortcuts_on_gnome_and_save_background_start(self):
        def inspect(dialog):
            tabs = dialog.findChild(QtWidgets.QTabWidget)
            self.assertIn("快捷键", [tabs.tabText(i) for i in range(tabs.count())])
            dialog.findChildren(QtWidgets.QKeySequenceEdit)[0].setKeySequence(
                QtGui.QKeySequence("Ctrl+Alt+K"))
            background = next(box for box in dialog.findChildren(QtWidgets.QCheckBox)
                              if "后台" in box.text())
            background.setChecked(True)
            dialog.close()
            return QtWidgets.QDialog.Accepted

        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
                                              "GSETTINGS_BACKEND": "keyfile"}):
            with mock.patch.object(QtWidgets.QDialog, "exec_", inspect):
                self.window.show_settings()
            self.assertEqual(kapture.gnome_current_key("--region"), "<Control><Alt>k")
        self.assertTrue(self.settings.value("start_hidden", False, type=bool))

    def test_background_command_keeps_window_hidden_until_show(self):
        self.window.handle_command("background")
        self.assertFalse(self.window.isVisible())
        self.window.handle_command("show")
        self.assertTrue(self.window.isVisible())

    def test_duplicate_combinations_do_not_save_settings(self):
        def duplicate(dialog):
            edits = dialog.findChildren(QtWidgets.QKeySequenceEdit)
            for edit in edits[:2]:
                edit.setKeySequence(QtGui.QKeySequence("Ctrl+Alt+K"))
            dialog.close()
            return QtWidgets.QDialog.Accepted

        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
                                              "GSETTINGS_BACKEND": "keyfile"}), \
                mock.patch.object(QtWidgets.QDialog, "exec_", duplicate), \
                mock.patch.object(QtWidgets.QMessageBox, "warning"):
            self.window.show_settings()
            self.assertEqual(kapture._gnome_paths(), [])
        self.assertFalse(self.settings.contains("start_hidden"))


if __name__ == "__main__":
    unittest.main()
