"""Scrolling-capture HUD (region outline + live thumbnail + stop) and the dynamic
visibility of the OCR box buttons."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtWidgets

import kapture


class OcrButtonVisibilityTest(unittest.TestCase):
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

    def test_buttons_hide_and_show_with_text_box_content(self):
        self.assertFalse(self.window._ocr_btns.isVisibleTo(self.window))
        self.window.text.setPlainText("recognized text")
        self.app.processEvents()
        self.assertTrue(self.window._ocr_btns.isVisibleTo(self.window))
        self.window.text.clear()
        self.app.processEvents()
        self.assertFalse(self.window._ocr_btns.isVisibleTo(self.window))

    def test_buttons_are_children_of_the_text_viewport(self):
        self.assertIs(self.window._ocr_btns.parent(), self.window.text.viewport())

    def test_buttons_reposition_inside_viewport(self):
        self.window.text.setPlainText("x")
        self.app.processEvents()
        vp = self.window.text.viewport()
        pos = self.window._ocr_btns.pos()
        self.assertGreaterEqual(pos.x(), 0)
        self.assertLessEqual(pos.y() + self.window._ocr_btns.height(),
                             vp.height() + 1)


class ScrollHudTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _hud(self):
        return kapture.ScrollHud(QtCore.QRect(100, 100, 400, 300), lambda: None,
                                 mode="manual")

    def test_hud_shows_thumbnail_and_height(self):
        hud = self._hud()
        img = np.full((5000, 800, 3), 255, dtype=np.uint8)
        hud.set_image(img)
        self.assertFalse(hud.thumb.pixmap().isNull())
        self.assertIn("5000", hud.lbl.text())
        hud.close()

    def test_hud_accepts_worker_tuple(self):
        hud = self._hud()
        img = np.full((600, 400, 3), 255, dtype=np.uint8)
        hud.set_image((img, 12345))          # downscaled preview + true height
        self.assertIn("12345", hud.lbl.text())
        hud.close()

    def test_hud_survives_garbage(self):
        hud = self._hud()
        hud.set_image(None)                  # must not raise
        hud.close()

    def test_region_overlay_bars_outside_region_and_click_through(self):
        """Regression: the old full-desktop overlay swallowed the wheel events
        scrolling capture needs — the frame must never cover the region."""
        region = QtCore.QRect(100, 100, 400, 300)
        ov = kapture.ScrollRegionOverlay(region)
        self.assertEqual(len(ov._wins), 4)
        vg = QtWidgets.QApplication.instance().primaryScreen().virtualGeometry()
        for w in ov._wins:
            self.assertTrue(w.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents))
            flags = w.windowFlags()
            self.assertTrue(flags & QtCore.Qt.X11BypassWindowManagerHint)
            self.assertLessEqual(w.width(), region.width() + 2 * kapture.ScrollRegionOverlay.THICK)
            self.assertLessEqual(w.height(), region.height() + 2 * kapture.ScrollRegionOverlay.THICK)
            self.assertTrue(vg.contains(w.geometry()))
            # no strip may cover ANY pixel of the capture region — QRect's
            # right()/bottom() are last-inside, off-by-one here captured the red
            # edge into the long screenshot once already
            self.assertTrue(w.geometry().intersected(region).isEmpty(),
                            msg=f"strip {w.geometry()} overlaps region {region}")
        ov.close()
        self.assertFalse(ov.isVisible())


class SeamRefineTest(unittest.TestCase):
    """find_new_content + refine_new_start must place the seam exactly: a seam off
    by a few rows duplicates/drops content and reads as a shadow band at every
    scroll step (user-reported on stitched long images)."""

    def _frames(self, h=400, w=300, shift=100, seed=7):
        rng = np.random.RandomState(seed)
        img = rng.randint(0, 256, (h * 4, w, 3), dtype=np.uint8)
        prev = img[0:h]
        cur = img[shift:shift + h]
        return prev, cur, h - shift          # true seam row in cur

    def test_match_plus_refine_recovers_exact_seam(self):
        prev, cur, true_start = self._frames()
        start, conf = kapture.find_new_content(prev, cur)
        self.assertGreaterEqual(conf, 0.9)
        self.assertEqual(start, true_start)  # ideal frames: already exact
        # simulate a mis-estimate (animated/teared frame off by a few rows)
        wrong = true_start + 6
        self.assertEqual(kapture.refine_new_start(prev, cur, wrong), true_start)
        wrong = true_start - 4
        self.assertEqual(kapture.refine_new_start(prev, cur, wrong), true_start)

    def test_refine_passthrough_at_bounds(self):
        prev, cur, _ = self._frames()
        self.assertEqual(kapture.refine_new_start(prev, cur, 3), 3)      # near top
        self.assertEqual(kapture.refine_new_start(prev, cur, 395), 395)  # near bottom


class CanvasStitchTest(unittest.TestCase):
    """Global-canvas stitching: repeatedly scrolling up and down must NOT
    duplicate content — frames already covered contribute nothing."""

    def _page(self, h=1600, w=300, seed=3):
        rng = np.random.RandomState(seed)
        return rng.randint(0, 256, (h, w, 3), dtype=np.uint8)

    def test_down_up_down_is_idempotent(self):
        page = self._page()
        vh = 400
        canvas, y = page[0:vh].copy(), 0             # stitch the first frame at the top
        seq = [0, 150, 300, 450, 300, 150, 0, 150, 300, 450, 600, 450, 600]
        for top in seq:
            frame = page[top:top + vh]
            y_est, conf = kapture.locate_frame(canvas, frame, y_hint=y)
            self.assertIsNotNone(y_est, f"frame at {top} failed to locate")
            self.assertGreaterEqual(conf, 0.9)
            self.assertEqual(y_est, top)               # exact global position
            canvas, y = kapture.stitch_frame(canvas, frame, y_est)
        # canvas grew exactly to cover [0, max(top)+vh) — never more
        self.assertEqual(canvas.shape[0], max(seq) + vh)
        self.assertTrue(np.array_equal(canvas, page[:max(seq) + vh]))

    def test_scroll_up_extends_canvas_above(self):
        page = self._page()
        vh = 400
        canvas = page[200:200 + vh].copy()             # started mid-page
        frame = page[0:vh]                             # user scrolled back to top
        y_est, conf = kapture.locate_frame(canvas, frame, y_hint=0)
        self.assertEqual(y_est, -200)                  # frame top pokes above canvas
        canvas2, y2 = kapture.stitch_frame(canvas, frame, y_est)
        self.assertEqual(canvas2.shape[0], vh + 200)
        self.assertTrue(np.array_equal(canvas2, page[:vh + 200]))

    def test_unlocatable_frame_is_skipped_not_appended(self):
        page = self._page()
        vh = 400
        canvas = page[0:vh].copy()
        other = np.random.RandomState(99).randint(0, 256, (vh, 300, 3), dtype=np.uint8)
        y_est, conf = kapture.locate_frame(canvas, other, y_hint=0)
        self.assertIsNone(y_est)                       # garbage in -> frame ignored
        self.assertLess(conf, 0.5)


class ScrollModeWiringTest(unittest.TestCase):
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
        self.window._close_scroll_hud()
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()

    def test_auto_scroll_creates_hud_and_overlay_without_running_worker(self):
        with mock.patch.object(kapture.CaptureWorker, "start") as start:
            self.window._scroll_shot((0, 0, 800, 600), 1.0,
                                     QtCore.QRect(0, 0, 800, 600))
        start.assert_called_once()
        self.assertIsNotNone(self.window._scroll_hud)
        self.assertIsNotNone(self.window._scroll_overlay)
        self.window.worker = None            # mocked: nothing to abort/wait

    def test_capture_done_closes_hud(self):
        self.window._scroll_hud = self.window._scroll_overlay = None
        with mock.patch.object(kapture.CaptureWorker, "start"):
            self.window._scroll_shot((0, 0, 800, 600), 1.0,
                                     QtCore.QRect(0, 0, 800, 600))
            hud = self.window._scroll_hud
            self.window.worker = None
        img = np.full((900, 800, 3), 255, dtype=np.uint8)
        with mock.patch.object(self.window, "_present_capture"):
            self.window._on_capture_done(img)
        self.assertIsNone(self.window._scroll_hud)
        self.assertIsNone(self.window._scroll_overlay)
        self.assertFalse(hud.isVisible())

    def test_manual_stop_closes_hud(self):
        img = np.full((600, 800, 3), 255, dtype=np.uint8)
        self.window._m_timer = None
        self.window._m_acc = img
        self.window._scroll_hud = kapture.ScrollHud(QtCore.QRect(0, 0, 10, 10),
                                                    lambda: None)
        with mock.patch.object(self.window, "_present_capture") as present:
            self.window._manual_stop()
        present.assert_called_once()
        self.assertIsNone(self.window._scroll_hud)


if __name__ == "__main__":
    unittest.main()
