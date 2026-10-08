"""Region selector overlay window flags and keyboard focus.

The overlay must cover the entire virtual desktop (including the GNOME top bar
and dock). A WM-managed Qt.Tool window is clamped to the work area, which offset
the selection from the frozen full-geometry frame, so the overlay bypasses the
window manager instead. Bypassed windows are not given keyboard focus by the WM,
so Esc-cancel depends on the widget grabbing focus/keyboard itself.
"""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtWidgets

import kapture


class _FakeGrab:
    def __init__(self):
        self.monitors = [{"left": 0, "top": 0, "width": 800, "height": 600}]

    def grab(self, _mon):
        return np.zeros((600, 800, 4), dtype=np.uint8)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class RegionSelectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_dir = tempfile.TemporaryDirectory()
        os.environ["XDG_CONFIG_HOME"] = cls.config_dir.name
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.app.setStyle("Fusion")

    @classmethod
    def tearDownClass(cls):
        cls.config_dir.cleanup()

    def _make(self):
        fake = mock.Mock()
        fake.mss.return_value = _FakeGrab()
        with mock.patch.object(kapture, "mss", fake):
            return kapture.RegionSelector()

    def test_overlay_bypasses_window_manager(self):
        sel = self._make()
        flags = sel.windowFlags()
        self.assertTrue(flags & QtCore.Qt.X11BypassWindowManagerHint)
        self.assertTrue(flags & QtCore.Qt.FramelessWindowHint)
        self.assertTrue(flags & QtCore.Qt.WindowStaysOnTopHint)

    def test_overlay_grabs_keyboard_focus_for_esc(self):
        # Bypassed windows get no WM focus, so the widget must accept focus itself.
        sel = self._make()
        self.assertEqual(sel.focusPolicy(), QtCore.Qt.StrongFocus)

    def test_escape_cancels_selection(self):
        sel = self._make()
        cancelled = []
        sel.cancelled.connect(lambda: cancelled.append(True))
        # Drive the key handler directly (no focused window under offscreen).
        from PyQt5.QtGui import QKeyEvent
        sel.keyPressEvent(QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape,
                                    QtCore.Qt.NoModifier))
        self.assertEqual(cancelled, [True])


if __name__ == "__main__":
    unittest.main()
