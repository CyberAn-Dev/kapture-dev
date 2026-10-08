"""Pin extras: Ctrl+wheel opacity, click-through state, one-click re-OCR, menu i18n.

Pins align with PixPin: Ctrl+wheel adjusts window opacity (plain wheel still
zooms), right-click offers OCR / click-through / reset opacity, and 'O' re-runs
OCR through the main window's headless clipboard path.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

import kapture


def _solid_image(color, w=20, h=20):
    image = QtGui.QImage(w, h, QtGui.QImage.Format_RGB32)
    image.fill(color)
    return image


def _wheel(pin, up, modifiers=Qt.NoModifier):
    event = QtGui.QWheelEvent(QtCore.QPointF(10, 10), QtCore.QPointF(10, 10),
                              QtCore.QPoint(), QtCore.QPoint(0, 120 if up else -120),
                              0, 0, Qt.NoButton, modifiers, False)
    pin.wheelEvent(event)


class PinExtrasTest(unittest.TestCase):
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

    def test_ctrl_wheel_adjusts_opacity_not_zoom(self):
        pin = kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3)))
        scale0 = pin._scale
        _wheel(pin, False, Qt.ControlModifier)                   # dimmer
        self.assertLess(pin._opacity, 1.0)
        self.assertEqual(pin._scale, scale0)
        _wheel(pin, True, Qt.ControlModifier)                   # back up
        self.assertAlmostEqual(pin._opacity, 1.0)

    def test_wheel_without_ctrl_zooms_not_opacity(self):
        pin = kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3)))
        _wheel(pin, True)
        self.assertGreater(pin._scale, 1.0)
        self.assertEqual(pin._opacity, 1.0)

    def test_opacity_clamps_between_03_and_1(self):
        pin = kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3)))
        for _ in range(40):
            pin._nudge_opacity(False)
        self.assertAlmostEqual(pin._opacity, 0.3)
        for _ in range(40):
            pin._nudge_opacity(True)
        self.assertAlmostEqual(pin._opacity, 1.0)
        pin._reset_opacity()
        self.assertAlmostEqual(pin._opacity, 1.0)

    def test_click_through_state_toggles_without_x11(self):
        # Offscreen: the XShape helper must fail silently, state tracks intent.
        pin = kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3)))
        with mock.patch.object(kapture, "_x11_set_input_passthrough",
                               return_value=False) as helper:
            pin._toggle_click_through()
            self.assertTrue(pin._click_through)
            pin._toggle_click_through()
            self.assertFalse(pin._click_through)
            self.assertEqual(helper.call_count, 2)
        pin._toggle_click_through(True)                          # unpatched: no raise

    def test_tray_escape_clears_all_passthrough_pins(self):
        pins = [kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3))) for _ in range(2)]
        with mock.patch.object(kapture, "_x11_set_input_passthrough", return_value=True):
            for p in pins:
                p._toggle_click_through(True)
            self.window._disable_pin_passthrough()
        self.assertFalse(any(p._click_through for p in pins))

    def test_pin_ocr_calls_back_with_bgr(self):
        QtWidgets.QApplication.clipboard().setImage(_solid_image(QtGui.QColor(9, 9, 9)))
        self.app.processEvents()
        self.window._pin_from_clipboard(0)
        pin = kapture.PinnedImage._pins[-1]
        seen = {}
        real_init = kapture.OCRWorker.__init__

        def spy_init(self, img, *a, **k):
            seen["img"] = img
            return real_init(self, img, *a, **k)
        with mock.patch.object(kapture.OCRWorker, "__init__", spy_init), \
                mock.patch.object(kapture.OCRWorker, "start") as start:
            pin._do_ocr()
        self.assertEqual(start.call_count, 1)
        self.assertIsInstance(seen["img"], np.ndarray)
        self.assertEqual(seen["img"].shape[:2], (20, 20))        # H x W of the pinned image

    def test_unwired_pin_ignores_o_key(self):
        pin = kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3)))
        pin.activateWindow()
        pin.setFocus()
        self.app.processEvents()
        with mock.patch.object(kapture.OCRWorker, "start") as start:
            QTest.keyClick(pin, Qt.Key_O)
        self.assertEqual(start.call_count, 0)

    def test_pin_menu_labels_follow_language(self):
        pin = kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3)),
                                  on_ocr=lambda bgr: None)
        for lang in ("zh", "en"):
            kapture.set_lang(lang)
            texts = [a.text() for a in pin._build_menu().actions()]
            self.assertIn(kapture.t("p_ocr"), texts)
            self.assertIn(kapture.t("p_clickthrough"), texts)
            self.assertIn(kapture.t("p_reset_opacity"), texts)
            self.assertIn(kapture.t("card_copy"), texts)
        kapture.set_lang("zh")

    def test_pinned_from_all_sites_get_ocr_wiring(self):
        QtWidgets.QApplication.clipboard().setImage(_solid_image(QtGui.QColor(5, 5, 5)))
        self.app.processEvents()
        self.window._pin_from_clipboard(0)
        self.assertIsNotNone(kapture.PinnedImage._pins[-1]._on_ocr)
        self.window.image_bgr = np.zeros((8, 8, 3), np.uint8)
        flat = _solid_image(QtGui.QColor(7, 7, 7), 8, 8)
        with mock.patch.object(kapture, "PinnedImage") as fake_pin, \
                mock.patch.object(kapture.AnnotateCanvas, "render_flattened",
                                  return_value=flat):
            self.window.pin_image()
        self.assertIsNotNone(fake_pin.call_args.kwargs.get("on_ocr"))


if __name__ == "__main__":
    unittest.main()
