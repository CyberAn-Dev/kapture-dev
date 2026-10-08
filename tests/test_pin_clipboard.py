"""Pin-to-clipboard shortcuts: system-clipboard history, Esc close, and defaults."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

import kapture


def _solid_image(color):
    image = QtGui.QImage(20, 20, QtGui.QImage.Format_RGB32)
    image.fill(color)
    return image


class PinClipboardTest(unittest.TestCase):
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

    def test_clipboard_images_are_tracked_newest_first(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setImage(_solid_image(QtGui.QColor(255, 0, 0)))
        self.app.processEvents()
        clipboard.setImage(_solid_image(QtGui.QColor(0, 0, 255)))
        self.app.processEvents()
        self.assertEqual(len(self.window._clip_images), 2)
        self.assertGreater(self.window._clip_images[0].pixelColor(0, 0).blue(), 200)

    def test_duplicate_clipboard_image_is_not_readded(self):
        image = _solid_image(QtGui.QColor(10, 200, 10))
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setImage(image)
        self.app.processEvents()
        clipboard.setImage(image)                 # same content re-signalled
        self.app.processEvents()
        self.assertEqual(len(self.window._clip_images), 1)

    def test_pin_current_creates_window_and_out_of_range_is_noop(self):
        QtWidgets.QApplication.clipboard().setImage(_solid_image(QtGui.QColor(255, 0, 0)))
        self.app.processEvents()
        before = len(kapture.PinnedImage._pins)
        self.window._pin_from_clipboard(0)
        self.assertEqual(len(kapture.PinnedImage._pins), before + 1)
        self.window._pin_from_clipboard(5)        # beyond history: no new window, no crash
        self.assertEqual(len(kapture.PinnedImage._pins), before + 1)

    def test_escape_closes_pinned_image(self):
        pin = kapture.PinnedImage(_solid_image(QtGui.QColor(1, 2, 3)))
        self.app.processEvents()
        pin.activateWindow()
        pin.setFocus()
        self.app.processEvents()
        before = len(kapture.PinnedImage._pins)
        QTest.keyClick(pin, Qt.Key_Escape)
        self.app.processEvents()
        self.assertEqual(len(kapture.PinnedImage._pins), before - 1)

    def test_gnome_accelerator_round_trips_pin_defaults(self):
        for combo in ("Ctrl+1", "Ctrl+2"):
            accelerator = kapture.gnome_accelerator(QtGui.QKeySequence(combo))
            self.assertEqual(kapture.gnome_key_sequence(accelerator),
                             QtGui.QKeySequence(combo))

    def test_punctuation_keysyms_display_and_round_trip(self):
        # A registered "<Alt>grave" must show as Alt+` in the settings tab, not blank,
        # and saving it again must write the same keysym back.
        for accelerator, combo in (("<Alt>grave", "Alt+`"),
                                   ("<Control><Alt>period", "Ctrl+Alt+."),
                                   ("<Super>bracketleft", "Meta+[")):
            sequence = kapture.gnome_key_sequence(accelerator)
            self.assertFalse(sequence.isEmpty(), accelerator)
            self.assertEqual(kapture.gnome_accelerator(sequence), accelerator)

    def test_frozen_frame_crop_matches_selection(self):
        # The region result is cropped from the overlay's frozen frame (what the user
        # saw), not re-grabbed later — so a reappearing top bar/dock cannot corrupt it.
        class FakeSelector:                       # only dpr/bg_img are used by the crop
            dpr = 2.0
        sel = FakeSelector()
        img = QtGui.QImage(100, 60, QtGui.QImage.Format_RGB888)
        img.fill(QtGui.QColor(10, 20, 30))
        for y in range(10, 20):                      # paint a known patch (image px)
            for x in range(20, 30):
                img.setPixelColor(x, y, QtGui.QColor(200, 100, 50))
        sel.bg_img = img
        bgr = kapture.RegionSelector._crop_frozen(sel, QtCore.QRect(10, 5, 20, 10))  # logical -> 2x physical
        self.assertEqual(bgr.shape, (20, 40, 3))              # H x W x BGR
        # Patch at image px x 20-29 / y 10-19 == crop origin (physical 20,10), so it
        # sits at rows/cols 0-9 inside the crop.
        self.assertEqual(tuple(int(v) for v in bgr[5, 5]), (50, 100, 200))   # inside the patch (BGR)
        self.assertEqual(tuple(int(v) for v in bgr[15, 25]), (30, 20, 10))   # surrounding background

    def test_default_shortcuts_are_registered_once(self):
        with tempfile.TemporaryDirectory() as config_dir, mock.patch.dict(
                os.environ, {"XDG_CONFIG_HOME": config_dir, "GSETTINGS_BACKEND": "keyfile",
                             "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}):
            self.assertEqual(kapture.gnome_current_key("--pin1"), "")
            self.window._ensure_default_shortcuts()
            self.assertEqual(kapture.gnome_current_key("--pin1"), "<Control>1")
            self.assertEqual(kapture.gnome_current_key("--pin2"), "<Control>2")

    def test_settings_prefill_pin_defaults_when_unregistered(self):
        def inspect(dialog):
            edits = dialog.findChildren(QtWidgets.QKeySequenceEdit)
            flags = [flag for _, flag in kapture.SHORTCUT_ACTIONS]
            portable = {flag: edits[i].keySequence().toString(
                QtGui.QKeySequence.PortableText) for i, flag in enumerate(flags)}
            self.assertEqual(portable["--pin1"], "Ctrl+1")
            self.assertEqual(portable["--pin2"], "Ctrl+2")
            self.assertEqual(portable["--region"], "")   # no default -> stays empty
            dialog.close()
            return QtWidgets.QDialog.Rejected

        with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
                                          "GSETTINGS_BACKEND": "keyfile"}), \
                mock.patch.object(QtWidgets.QDialog, "exec_", inspect):
            self.window.show_settings()


if __name__ == "__main__":
    unittest.main()
