"""Editor toolbar alignment and keyboard undo behavior."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtTest, QtWidgets

import kapture


class EditorControlsTest(unittest.TestCase):
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
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_output_buttons_start_beside_output_label(self):
        label_right = (self.window._output_label.mapTo(self.window, QtCore.QPoint()).x()
                       + self.window._output_label.width())
        ocr_left = self.window.btn_ocr.mapTo(self.window, QtCore.QPoint()).x()
        self.assertLessEqual(ocr_left - label_right, 20)

    def test_ctrl_z_undoes_annotation_from_toolbar_focus(self):
        self.window.canvas.items.append(object())
        self.window.btn_undo.setFocus()
        QtTest.QTest.keyClick(self.window.btn_undo, QtCore.Qt.Key_Z,
                              QtCore.Qt.ControlModifier)
        self.assertEqual(self.window.canvas.items, [])

    def test_ctrl_z_in_ocr_text_keeps_text_undo(self):
        self.window.canvas.items.append(object())
        self.window.text.setPlainText("first")
        self.window.text.moveCursor(self.window.text.textCursor().End)
        self.window.text.insertPlainText(" second")
        self.window.text.setFocus()
        QtTest.QTest.keyClick(self.window.text, QtCore.Qt.Key_Z,
                              QtCore.Qt.ControlModifier)
        self.assertEqual(self.window.text.toPlainText(), "first")
        self.assertEqual(len(self.window.canvas.items), 1)


if __name__ == "__main__":
    unittest.main()
