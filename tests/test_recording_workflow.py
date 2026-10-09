"""The two recording entry points share setup, countdown and export lifecycle."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import tempfile
import unittest
from unittest import mock
from PyQt5 import QtCore, QtWidgets
import kapture


class RecordingWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(self.directory.name + '/settings.ini', QtCore.QSettings.IniFormat)
        with mock.patch.object(kapture, 'write_desktop_entry'):
            self.window = kapture.MainWindow()
        self.window.settings = self.settings
        self.listener = mock.patch.object(kapture, 'KeyListener'); self.listener.start()

    def tearDown(self):
        self.window._on_record_stop()
        self.window._history_writer.shutdown()
        self.window.tray.hide(); self.window.close(); self.window.deleteLater()
        self.app.processEvents(); self.listener.stop(); self.directory.cleanup()

    def test_recording_dialogs_follow_current_editor_theme(self):
        self.settings.setValue('ui_theme', 'vitesse_dark')
        self.window._apply_style('vitesse_dark', 'theme')
        dialogs = [kapture.RecordSetupBar(self.settings, (400, 240), QtCore.QRect(10, 20, 400, 240), self.window),
                   kapture.RecordExportDialog('/tmp/source.mp4', 15, 2, self.directory.name,
                                              'clip.mp4', self.window)]
        for dialog in dialogs:
            dialog.show(); self.app.processEvents()
            self.assertEqual(dialog.grab().toImage().pixelColor(10, 10).name(),
                             '#181818' if isinstance(dialog, kapture.RecordSetupBar) else '#121212')
            dialog.hide(); dialog.deleteLater()

    def test_recording_bar_menus_share_options_and_custom_inputs(self):
        bar = kapture.RecordSetupBar(self.settings, (400, 240), QtCore.QRect(10, 20, 400, 240), self.window)
        bar.show(); self.app.processEvents()
        self.assertLess(bar.height(), 70)
        self.assertFalse(bar.options.isVisible())
        self.assertFalse(bar.geometry().intersects(bar._region))
        bar.fps_button.menu().actions()[3].trigger()
        self.assertEqual(bar.options.fps.value(), 30)
        bar.fps_button.custom_input.setValue(27)
        self.assertEqual(bar.options.values()['fps'], 27)
        self.assertEqual(bar.fps_button.text(), '27 fps')
        bar.resolution_button.menu().actions()[3].trigger()
        self.assertEqual(bar.options.output_size(), (200, 120))
        bar.custom_width.setValue(300)
        self.assertEqual(bar.options.output_size(), (300, 180))
        self.assertEqual(bar.resolution_button.text(), '300 × 180')
        bar.countdown_button.custom_input.setValue(4)
        bar.duration_button.custom_input.setValue(12)
        self.assertEqual(bar.options.values()['countdown'], 4)
        self.assertEqual(bar.options.values()['duration'], 12)
        bar.options.save(self.settings)
        restored = kapture.RecordingOptions(self.settings, (400, 240))
        self.assertEqual(restored.values(), bar.options.values())
        bar.reject(); bar.deleteLater(); restored.deleteLater()

    def test_cancel_setup_never_starts_recording(self):
        with mock.patch.object(kapture.RecordSetupBar, 'exec_', return_value=QtWidgets.QDialog.Rejected), \
                mock.patch.object(self.window, '_begin_recording') as begin:
            self.window._start_record(QtCore.QRect(10, 20, 200, 100))
        begin.assert_not_called()
        self.assertIsNone(self.window._recorder)
        self.assertIsNone(self.window._record_setup)

    def test_countdown_uses_selected_settings_and_can_be_cancelled(self):
        def accept(dialog):
            dialog.options.fps.setValue(24)
            dialog.options.resolution.setCurrentIndex(dialog.options.resolution.findData('half'))
            dialog.options.countdown.setValue(2)
            dialog.options.duration.setValue(5)
            return QtWidgets.QDialog.Accepted
        with mock.patch.object(kapture.RecordSetupBar, 'exec_', new=accept), \
                mock.patch.object(self.window, '_begin_recording') as begin:
            self.window._start_record(QtCore.QRect(10, 20, 200, 100))
            self.assertIn('2', self.window._recbar.lbl.text())
            self.assertIsNotNone(self.window._recbar._esc)
            self.window._record_countdown_tick()
            begin.assert_not_called()
            self.window._record_countdown_tick()
            self.assertEqual(begin.call_args.args[2], dict(fps=24, output_size=(100, 50), countdown=2, duration=5))
            self.window._close_record_controls()
            self.window._start_record(QtCore.QRect(10, 20, 200, 100))
            self.window._on_record_stop()
            self.assertIsNone(self.window._record_pending)
            self.assertIsNone(self.window._record_border)
            self.assertIsNone(self.window._recbar)
            self.assertEqual(begin.call_count, 1)

    def test_export_failure_keeps_dialog_open_for_retry_and_discard_is_explicit(self):
        dialog = kapture.RecordExportDialog('/tmp/source.mp4', 15, 2, self.directory.name, 'clip.mp4', self.window)
        dialog.show()
        dialog.busy = True
        dialog.reject()
        self.assertTrue(dialog.isVisible())
        dialog._completed('', 'test error')
        self.assertTrue(dialog.isVisible())
        self.assertTrue(dialog.save_button.isEnabled())
        with mock.patch.object(QtWidgets.QMessageBox, 'question', return_value=QtWidgets.QMessageBox.Cancel):
            dialog.reject()
        self.assertTrue(dialog.isVisible())
        with mock.patch.object(QtWidgets.QMessageBox, 'question', return_value=QtWidgets.QMessageBox.Discard):
            dialog.reject()
        self.assertFalse(dialog.isVisible())
        dialog.deleteLater()
