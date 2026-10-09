"""Opt-in self-capture preserves the visible main window; cancel does not save settings."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from unittest import mock
from PyQt5 import QtCore, QtWidgets
import kapture


class CaptureVisibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(self.directory.name + '/settings.ini', QtCore.QSettings.IniFormat)
        with mock.patch.object(kapture, 'write_desktop_entry'), \
                mock.patch.object(QtCore, 'QSettings', return_value=self.settings):
            self.window = kapture.MainWindow()
        self.window._last_phys = (0, 0, 100, 100)
        self.window.show(); self.app.processEvents()

    def tearDown(self):
        self.window._history_writer.shutdown()
        self.window.tray.hide(); self.window.close(); self.window.deleteLater()
        self.app.processEvents(); self.directory.cleanup()

    def test_capture_entries_minimize_by_default_and_respect_keep_main(self):
        entries = [(name, lambda mode=name: self.window.start_select(mode))
                   for name in ('single', 'textgrab', 'manual', 'scroll')]
        entries += [('window', self.window.capture_window), ('repeat', self.window.repeat_last)]
        for keep in (False, True):
            self.settings.setValue('capture_keep_main', keep)
            for name, capture in entries:
                with self.subTest(keep=keep, entry=name), \
                        mock.patch.object(QtCore.QTimer, 'singleShot'), \
                        mock.patch.object(self.window, 'showMinimized') as minimize:
                    capture()
                    self.assertEqual(minimize.call_count, 0 if keep else 1)
                    self.assertTrue(self.window.isVisible())

    def test_general_checkbox_only_persists_when_settings_are_accepted(self):
        self.assertFalse(self.settings.value('capture_keep_main', False, type=bool))
        for accepted in (False, True):
            def edit(dialog):
                checkbox = dialog.findChild(QtWidgets.QCheckBox, 'captureKeepMain')
                self.assertIsNotNone(checkbox)
                self.assertFalse(checkbox.isChecked())
                checkbox.setChecked(True)
                return QtWidgets.QDialog.Accepted if accepted else QtWidgets.QDialog.Rejected
            with mock.patch.object(kapture, 'shortcut_backend', return_value=None), \
                    mock.patch.object(QtWidgets.QDialog, 'exec_', new=edit), \
                    mock.patch.object(kapture, 'write_desktop_entry'):
                self.window.show_settings()
            restored = QtCore.QSettings(self.settings.fileName(), QtCore.QSettings.IniFormat)
            self.assertEqual(restored.value('capture_keep_main', False, type=bool), accepted)
