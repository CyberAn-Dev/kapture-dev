"""Screen text grab: grab -> OCR -> copy text, editor never opens, image not copied."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtWidgets

import kapture


class TextGrabTest(unittest.TestCase):
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
        for worker in list(self.window._ocr_workers):
            worker.wait()
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_toolbar_button_exists_and_starts_textgrab(self):
        self.assertTrue(hasattr(self.window, "btn_textgrab"))
        self.assertFalse(self.window.btn_textgrab.icon().isNull())
        with mock.patch.object(self.window, "start_select") as start:
            self.window.btn_textgrab.click()
        start.assert_called_once_with("textgrab")

    def test_textgrab_region_routes_to_textgrab_shot(self):
        rect = QtCore.QRect(0, 0, 10, 10)
        self.window._mode = "textgrab"
        with mock.patch.object(self.window, "_textgrab_shot") as shot, \
                mock.patch.object(QtCore.QTimer, "singleShot") as ss:
            self.window._on_region(rect)
            ss.assert_called_once()        # scheduled with a delay like the other modes
            args = ss.call_args[0]
            self.assertEqual(args[0], 150)
            args[1]()                       # run the deferred call
            shot.assert_called_once()

    def test_grab_result_copies_text_without_opening_editor(self):
        was_visible = self.window.isVisible()
        self.app.clipboard().setText("sentinel")
        with mock.patch.object(self.window, "_flash_note") as note, \
                mock.patch.object(self.window, "_present_capture") as present:
            self.window._on_grab_ocr_result("  hello world  ", "")
        self.assertEqual(self.app.clipboard().text(), "hello world")   # trimmed + copied
        note.assert_called_once()
        present.assert_not_called()          # editor path must not run
        note.call_args[0][0]                 # a message was shown
        self.assertEqual(self.window.isVisible(), was_visible)

    def test_grab_result_no_text(self):
        self.app.clipboard().setText("keepme")
        with mock.patch.object(self.window, "_flash_note") as note:
            self.window._on_grab_ocr_result("   \n ", "")
        self.assertEqual(self.app.clipboard().text(), "keepme")        # untouched
        self.assertEqual(note.call_args[0][0], kapture.t("st_ocr_none"))

    def test_grab_result_error(self):
        self.app.clipboard().setText("keepme")
        with mock.patch.object(self.window, "_flash_note") as note:
            self.window._on_grab_ocr_result("", "tesseract not found")
        self.assertEqual(self.app.clipboard().text(), "keepme")
        self.assertEqual(note.call_args[0][0], "tesseract not found")

    def test_textgrab_shot_grabs_and_ocrs_without_present(self):
        img = np.full((40, 40, 3), 255, dtype=np.uint8)
        self.window.delay.setValue(0)
        with mock.patch.object(self.window, "_grab_ocr") as ocr, \
                mock.patch.object(self.window, "_present_capture") as present, \
                mock.patch.object(self.window, "_flash_note"):
            self.window._textgrab_shot((0, 0, 40, 40), img)
        ocr.assert_called_once()
        present.assert_not_called()
        self.assertEqual(self.window._last_phys, (0, 0, 40, 40))       # repeat works

    def test_grab_ocr_uses_config_and_own_worker(self):
        img = np.full((40, 40, 3), 255, dtype=np.uint8)
        before = len(self.window._ocr_workers)
        with mock.patch.object(kapture.OCRWorker, "start") as start:
            self.window._grab_ocr(img)
        self.assertEqual(len(self.window._ocr_workers), before + 1)
        start.assert_called_once()
        w = self.window._ocr_workers[-1]
        self.assertTrue(w.automatic)                          # bounded timeout
        self.assertEqual(w.lang, self.window.lang.currentText())


if __name__ == "__main__":
    unittest.main()
