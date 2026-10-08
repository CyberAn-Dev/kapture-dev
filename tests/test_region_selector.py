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

    # --- window snapping ---------------------------------------------------- #

    def test_snap_point_snaps_nearest_within_threshold(self):
        sx, sy, gx, gy = kapture.snap_point(103, 50, [100, 200], [80], threshold=10)
        self.assertEqual((sx, sy), (100, 50))                    # x snapped, y had no guide
        self.assertEqual((gx, gy), (100, None))
        sx, sy, gx, gy = kapture.snap_point(130, 50, [100], [80], threshold=10)
        self.assertEqual((sx, sy, gx, gy), (130, 50, None, None))  # both out of range
        sx, _, gx, _ = kapture.snap_point(104, 0, [100, 106], [], threshold=10)
        self.assertEqual((sx, gx), (106, 106))                   # nearest wins

    def test_hit_window_picks_topmost(self):
        low = QtCore.QRect(0, 0, 200, 200)
        high = QtCore.QRect(50, 50, 100, 100)
        # Top-to-bottom order: the smaller upper window comes first in the list.
        self.assertEqual(kapture.RegionSelector.hit_window([high, low], QtCore.QPoint(60, 60)), high)
        self.assertEqual(kapture.RegionSelector.hit_window([high, low], QtCore.QPoint(10, 10)), low)
        self.assertIsNone(kapture.RegionSelector.hit_window([high, low], QtCore.QPoint(300, 300)))

    def test_loupe_geometry_uses_integer_steps(self):
        sel = self._make()
        for dpr in (1.0, 1.5, 2.0):
            sel.dpr = dpr
            s, src_px, side = sel._loupe_geometry()
            self.assertIsInstance(s, int)
            self.assertGreaterEqual(s, 1)
            self.assertEqual(side, src_px * s)                   # grid lands on cell edges

    def _selector_with_windows(self, rects):
        sel = self._make()
        sel.snap = True
        sel._wins = list(rects)
        sel.setGeometry(0, 0, 800, 600)                          # full virtual desktop
        return sel

    def _press_move_release(self, sel, press_at, move_to):
        from PyQt5.QtGui import QMouseEvent
        Qt = QtCore.Qt
        def ev(kind, pos, buttons=Qt.LeftButton):
            return QMouseEvent(kind, QtCore.QPointF(pos), QtCore.QPointF(pos),
                               buttons, buttons, Qt.NoModifier)
        sel.mousePressEvent(ev(QtCore.QEvent.MouseButtonPress, press_at))
        sel.mouseMoveEvent(ev(QtCore.QEvent.MouseMove, move_to))
        sel.mouseReleaseEvent(ev(QtCore.QEvent.MouseButtonRelease, move_to, Qt.NoButton))

    def test_click_selects_hovered_window_whole(self):
        win = QtCore.QRect(100, 50, 300, 200)
        sel = self._selector_with_windows([win])
        got = []
        sel.selected.connect(lambda rect, img: got.append(rect))
        self._press_move_release(sel, QtCore.QPoint(150, 100), QtCore.QPoint(152, 101))
        self.assertEqual(got, [QtCore.QRect(100, 50, 300, 200)])

    def test_drag_beyond_threshold_switches_to_free_region(self):
        win = QtCore.QRect(100, 50, 300, 200)
        sel = self._selector_with_windows([win])
        got = []
        sel.selected.connect(lambda rect, img: got.append(rect))
        # Endpoint deliberately >10px from every edge/center guide
        self._press_move_release(sel, QtCore.QPoint(150, 100), QtCore.QPoint(265, 170))
        self.assertEqual(len(got), 1)
        self.assertNotEqual(got[0], QtCore.QRect(100, 50, 300, 200))
        self.assertEqual(got[0].topLeft(), QtCore.QPoint(150, 100))
        self.assertEqual(got[0].bottomRight(), QtCore.QPoint(265, 170))

    def test_drag_snaps_moving_edge_to_window_border(self):
        win = QtCore.QRect(100, 50, 300, 200)                     # right edge x=399
        sel = self._selector_with_windows([win])
        got = []
        sel.selected.connect(lambda rect, img: got.append(rect))
        # Release 4px short of the right border and 4px past the bottom border
        self._press_move_release(sel, QtCore.QPoint(120, 60), QtCore.QPoint(395, 246))
        self.assertEqual(got[0].bottomRight(), QtCore.QPoint(399, 249))

    def test_no_snap_setting_disables_hover(self):
        sel = self._make()
        sel.snap = False
        sel._wins = [QtCore.QRect(0, 0, 400, 300)]
        cancelled = []
        sel.cancelled.connect(lambda: cancelled.append(True))
        self._press_move_release(sel, QtCore.QPoint(10, 10), QtCore.QPoint(11, 11))
        self.assertEqual(cancelled, [True])                      # tiny click, no window grab

    def test_list_visible_windows_swallows_no_display(self):
        self.assertIsInstance(kapture.list_visible_windows(), list)  # never raises


if __name__ == "__main__":
    unittest.main()
