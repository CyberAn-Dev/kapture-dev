"""Screenshot OCR starts automatically while preserving image copy behavior."""

import os
import tempfile
import threading
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtTest, QtWidgets

import kapture


class AutoOcrTest(unittest.TestCase):
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
        self.settings.setValue("ocr_lang", "eng")
        self.window = kapture.MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        for worker in list(self.window._ocr_workers):
            worker.wait()
        self.app.processEvents()
        if getattr(self.window, "_thumb", None):
            self.window._thumb.close()
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_capture_recognizes_text_without_replacing_image_clipboard(self):
        image = np.full((40, 120, 3), 255, dtype=np.uint8)
        with mock.patch("pytesseract.image_to_string", return_value="hello") as engine:
            self.window._present_capture(image, "Captured")
            for _ in range(200):
                QtTest.QTest.qWait(10)
                if self.window.text.toPlainText() == "hello":
                    break
        self.assertTrue(engine.called)
        self.assertEqual(self.window.text.toPlainText(), "hello")
        self.assertIs(self.window.image_bgr, image)
        self.assertTrue(self.app.clipboard().mimeData().hasImage())

    def test_auto_ocr_can_be_disabled_without_opening_editor(self):
        def disable_auto_ocr(dialog):
            checkbox = next(box for box in dialog.findChildren(QtWidgets.QCheckBox)
                            if "OCR" in box.text())
            self.assertTrue(checkbox.isChecked())
            checkbox.setChecked(False)
            dialog.close()
            return QtWidgets.QDialog.Accepted

        with mock.patch.object(QtWidgets.QDialog, "exec_", disable_auto_ocr):
            self.window.show_settings()
        self.assertFalse(self.settings.value("auto_ocr", True, type=bool))
        image = np.full((40, 120, 3), 255, dtype=np.uint8)
        with mock.patch("pytesseract.image_to_string", return_value="hello") as engine:
            self.window._present_capture(image, "Captured")
            self.app.processEvents()
        engine.assert_not_called()
        self.assertIsNone(self.window.image_bgr)

    def test_older_capture_result_cannot_replace_newer_text(self):
        started = threading.Event()
        release = threading.Event()
        calls = 0

        def recognize(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                release.wait(2)
                return "old"
            return "new"

        image = np.full((40, 120, 3), 255, dtype=np.uint8)
        with mock.patch("pytesseract.image_to_string", side_effect=recognize):
            self.window._present_capture(image, "First")
            for _ in range(200):
                QtTest.QTest.qWait(10)
                if started.is_set():
                    break
            self.assertTrue(started.is_set())
            self.window._present_capture(image.copy(), "Second")
            for _ in range(200):
                QtTest.QTest.qWait(10)
                if self.window.text.toPlainText() == "new":
                    break
            release.set()
            for worker in list(self.window._ocr_workers):
                worker.wait()
            self.app.processEvents()
        self.assertEqual(self.window.text.toPlainText(), "new")

    def test_manual_ocr_button_copies_recognized_text(self):
        image = np.full((40, 120, 3), 255, dtype=np.uint8)
        self.window._load_into_editor(image)
        with mock.patch("pytesseract.image_to_string", return_value="manual"):
            self.window.btn_ocr.click()
            for _ in range(200):
                QtTest.QTest.qWait(10)
                if self.window.text.toPlainText() == "manual":
                    break
        self.assertEqual(self.window.text.toPlainText(), "manual")
        self.assertEqual(self.app.clipboard().text(), "manual")


if __name__ == "__main__":
    unittest.main()
