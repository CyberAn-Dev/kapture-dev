"""Regression coverage for clipboard history and annotated image saving."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

import kapture


def _solid_image(color, width=64, height=64):
    image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
    image.fill(color)
    return image


class ClipboardSaveRegressionTest(unittest.TestCase):
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
        self.window._clip_images = []
        self.app.processEvents()

    def tearDown(self):
        for pin in list(kapture.PinnedImage._pins):
            pin.close()
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_clipboard_history_keeps_image_changed_only_at_center(self):
        first = _solid_image(QtGui.QColor(240, 10, 20))
        second = first.copy()
        center = (first.width() // 2, first.height() // 2)
        second.setPixelColor(*center, QtGui.QColor(10, 20, 240))

        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setImage(first)
        self.app.processEvents()
        clipboard.setImage(second)
        self.app.processEvents()

        self.assertEqual(len(self.window._clip_images), 2)
        self.assertEqual(self.window._clip_images[0].pixelColor(*center),
                         QtGui.QColor(10, 20, 240))
        self.assertEqual(self.window._clip_images[1].pixelColor(*center),
                         QtGui.QColor(240, 10, 20))

    def test_clipboard_history_does_not_repeat_identical_image(self):
        image = _solid_image(QtGui.QColor(10, 200, 10))
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setImage(image)
        self.app.processEvents()
        clipboard.setImage(image.copy())
        self.app.processEvents()

        self.assertEqual(len(self.window._clip_images), 1)

    def test_save_image_writes_annotation_from_flattened_canvas(self):
        image_bgr = np.zeros((64, 64, 3), dtype=np.uint8)
        self.window.image_bgr = image_bgr
        self.window.canvas.set_image_bgr(image_bgr)
        self.window.canvas.items.append({
            "type": "line",
            "a": QtCore.QPointF(8, 32),
            "b": QtCore.QPointF(56, 32),
            "color": QtGui.QColor(255, 0, 0),
            "width": 5,
        })

        with tempfile.TemporaryDirectory() as output_dir:
            path = os.path.join(output_dir, "annotated.png")
            with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName",
                                   return_value=(path, "")):
                self.window.save_image()

            saved = QtGui.QImage(path)
            self.assertFalse(saved.isNull())
            self.assertEqual(saved.pixelColor(32, 32), QtGui.QColor(255, 0, 0))
            self.assertEqual(saved.pixelColor(4, 4), QtGui.QColor(0, 0, 0))

    def test_failed_qt_save_does_not_fall_back_to_original_image(self):
        image_bgr = np.full((32, 32, 3), (11, 22, 33), dtype=np.uint8)
        self.window.image_bgr = image_bgr
        self.window.canvas.set_image_bgr(image_bgr)

        with tempfile.TemporaryDirectory() as output_dir:
            path = os.path.join(output_dir, "failed.png")
            with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName",
                                   return_value=(path, "")), \
                    mock.patch.object(QtGui.QImage, "save", return_value=False):
                self.window.save_image()

            wrote_output = os.path.exists(path)
            reported_success = self.window.status.text().startswith(("Saved: ", "已保存:"))
            self.assertFalse(
                wrote_output or reported_success,
                f"Qt save failure wrote_output={wrote_output}, "
                f"status={self.window.status.text()!r}",
            )


if __name__ == "__main__":
    unittest.main()
