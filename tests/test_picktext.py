"""Editor defaults to picktext: cursor-select recognized words -> copy on release."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets, QtTest

import kapture


class PickTextTest(unittest.TestCase):
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

    WORDS = [(QtCore.QRectF(10, 10, 40, 14), "hello"),
             (QtCore.QRectF(55, 10, 40, 14), "world"),
             (QtCore.QRectF(10, 30, 40, 14), "second")]

    def _drag(self, from_pt, to_pt):
        c = self.window.canvas
        def post(w, p, typ, btn):
            ev = QtGui.QMouseEvent(typ, p, btn, btn, QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(w, ev)
        post(c, from_pt, QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton)
        post(c, to_pt, QtCore.QEvent.MouseMove, QtCore.Qt.LeftButton)
        post(c, to_pt, QtCore.QEvent.MouseButtonRelease, QtCore.Qt.NoButton)

    def test_editor_defaults_to_picktext(self):
        self.assertEqual(self.window.canvas.tool, "picktext")
        self.assertTrue(self.window._tool_btns["picktext"].isChecked())

    def test_first_click_on_empty_words_triggers_recognition(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window._load_into_editor(img)
        self.window.canvas.set_image_bgr(img)
        with mock.patch.object(self.window, "run_ocr") as run_ocr:
            self._drag(QtCore.QPoint(20, 15), QtCore.QPoint(20, 15))
            run_ocr.assert_called_once_with(copy_result=False)

    def test_drag_over_words_copies_them(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window.canvas.set_image_bgr(img)
        self.window.canvas.set_word_boxes(self.WORDS)
        self._drag(QtCore.QPoint(20, 15), QtCore.QPoint(70, 15))
        self.assertEqual(self.app.clipboard().text(), "hello world")
        self.assertEqual(self.window.text.toPlainText(), "hello world")

    def test_single_word_click_copies_it(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window.canvas.set_image_bgr(img)
        self.window.canvas.set_word_boxes(self.WORDS)
        self._drag(QtCore.QPoint(30, 36), QtCore.QPoint(30, 36))
        self.assertEqual(self.app.clipboard().text(), "second")

    def test_word_boxes_cleared_with_new_image(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window.canvas.set_image_bgr(img)
        self.window.canvas.set_word_boxes(self.WORDS)
        self.window.canvas.set_image_bgr(img.copy())
        self.assertEqual(self.window.canvas._word_boxes, [])

    def test_words_ready_populates_canvas(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window.image_bgr = img
        self.window._on_words_ready(self.WORDS)
        self.assertEqual(len(self.window.canvas._word_boxes), 3)

    def test_crop_tool_still_works(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window.image_bgr = img
        self.window.canvas.set_image_bgr(img)
        self.window.canvas.set_tool("crop")
        self._drag(QtCore.QPoint(10, 20), QtCore.QPoint(150, 60))
        self.assertEqual(self.window.canvas.base.height(), 40)

    def _move(self, pt):
        ev = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, pt,
                               QtCore.Qt.NoButton, QtCore.Qt.NoButton,
                               QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(self.window.canvas, ev)

    def test_picktext_cursor_is_arrow_off_words_ibeam_over_words(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window.canvas.set_image_bgr(img)
        self.window.canvas.set_word_boxes(self.WORDS)
        self._move(QtCore.QPoint(300, 150))          # empty area
        self.assertEqual(self.window.canvas.cursor().shape(), QtCore.Qt.ArrowCursor)
        self._move(QtCore.QPoint(30, 17))            # over "hello"
        self.assertEqual(self.window.canvas.cursor().shape(), QtCore.Qt.IBeamCursor)
        self._move(QtCore.QPoint(300, 150))          # back off -> arrow again
        self.assertEqual(self.window.canvas.cursor().shape(), QtCore.Qt.ArrowCursor)

    def test_picktext_cursor_stays_arrow_without_word_boxes(self):
        img = np.full((200, 400, 3), 255, dtype=np.uint8)
        self.window.canvas.set_image_bgr(img)
        self._move(QtCore.QPoint(30, 17))
        self.assertEqual(self.window.canvas.cursor().shape(), QtCore.Qt.ArrowCursor)

    def test_ocr_box_all_buttons_exist_and_are_localized(self):
        self.assertTrue(self.window.btn_ocr_all.text())
        self.assertTrue(self.window.btn_copy_all.text())

    def test_copy_all_copies_text_box_content(self):
        self.app.clipboard().setText("sentinel")
        self.window.text.setPlainText("  line one\nline two  ")
        self.window.btn_copy_all.click()
        self.assertEqual(self.app.clipboard().text(), "line one\nline two")

    def test_copy_all_on_empty_box_keeps_clipboard(self):
        self.app.clipboard().setText("keepme")
        self.window.text.clear()
        self.window.btn_copy_all.click()
        self.assertEqual(self.app.clipboard().text(), "keepme")

    def test_recognize_all_reruns_ocr(self):
        with mock.patch.object(self.window, "run_ocr") as run_ocr:
            self.window.btn_ocr_all.click()
        run_ocr.assert_called_once_with(copy_result=False)


if __name__ == "__main__":
    unittest.main()
