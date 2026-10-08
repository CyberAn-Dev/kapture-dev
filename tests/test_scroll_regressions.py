import os
import unittest
from unittest import mock

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
import kapture


class ScrollRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_static_blank_does_not_grow(self):
        frame = np.full((400, 300, 3), 255, np.uint8)
        y, _ = kapture.locate_frame(frame, frame, 0)
        self.assertEqual(y, 0)
        self.assertEqual(kapture.refine_frame_offset(frame, frame, y), 0)

    def test_constant_changed_frame_is_not_a_location(self):
        first = np.full((400, 300, 3), 255, np.uint8)
        second = np.full_like(first, 100)
        self.assertIsNone(kapture.locate_frame(first, second, 0)[0])

    def test_down_up_down_matches_page_pixels(self):
        page = np.random.RandomState(45).randint(0, 256, (1600, 180, 3), dtype=np.uint8)
        canvas, hint, origin = page[400:800].copy(), 0, 400
        for top in [550, 400, 250, 100, 250, 400, 550, 700]:
            frame = page[top:top+400]
            y, _ = kapture.locate_frame(canvas, frame, hint)
            self.assertEqual(y, top-origin)
            y = kapture.refine_frame_offset(canvas, frame, y)
            canvas, hint = kapture.stitch_frame(canvas, frame, y)
            origin = min(origin, top)
        np.testing.assert_array_equal(canvas, page[100:1100])

    def test_preview_uses_thumbnail_aspect_and_original_height(self):
        hud = kapture.ScrollHud(QtCore.QRect(0, 0, 400, 300), lambda: None)
        self.addCleanup(hud.close)
        hud.set_image((np.zeros((1200, 240, 3), np.uint8), 6000))
        pm = hud.thumb.pixmap()
        self.assertEqual((pm.width(), pm.height()), (48, 240))
        self.assertIn('6000', hud.lbl.text())

    def test_fullscreen_region_never_has_visible_hud_inside(self):
        region = self.app.primaryScreen().virtualGeometry()
        hud = kapture.ScrollHud(region, lambda: None)
        self.addCleanup(hud.close)
        hud.show_on_top()
        self.assertFalse(hud.isVisible() and hud.geometry().intersects(region))

    def test_auto_unmatched_frame_cannot_bridge_a_gap(self):
        page = np.random.RandomState(6).randint(0, 256, (2000, 100, 3), dtype=np.uint8)
        worker = kapture.CaptureWorker((0, 0, 100, 400), max_iters=3)
        results = []
        worker.finished_img.connect(results.append)
        with mock.patch.object(kapture, 'MouseController'), mock.patch.object(kapture.time, 'sleep'), mock.patch.object(kapture, 'grab_region', side_effect=[page[:400], page[900:1300], page[1000:1400], page[1100:1500]]):
            worker.run()
        np.testing.assert_array_equal(results[0], page[:400])

    def test_auto_up_produces_exact_page_pixels(self):
        page = np.random.RandomState(8).randint(0, 256, (1000, 100, 3), dtype=np.uint8)
        worker = kapture.CaptureWorker((0, 0, 100, 400), max_iters=2, direction=-1)
        results = []
        worker.finished_img.connect(results.append)
        with mock.patch.object(kapture, 'MouseController') as mouse, mock.patch.object(kapture.time, 'sleep'), mock.patch.object(kapture, 'grab_region', side_effect=[page[400:800], page[200:600], page[:400]]):
            worker.run()
        np.testing.assert_array_equal(results[0], page[:800])
        self.assertEqual(mouse.return_value.scroll.call_args_list,
                         [mock.call(0, 3), mock.call(0, 3)])

    def test_repeated_rows_with_no_unique_anchor_are_rejected(self):
        rows = np.random.RandomState(2).randint(0, 256, (20, 100, 3), dtype=np.uint8)
        page = np.tile(rows, (40, 1, 1))
        self.assertIsNone(kapture.locate_frame(page[:400], page[10:410])[0])

    def test_localized_loaded_content_does_not_reject_stable_overlap(self):
        page = np.random.RandomState(73).randint(0, 256, (1200, 300, 3), dtype=np.uint8)
        previous = page[:400].copy()
        current = page[100:500].copy()
        current[100:140] = np.random.RandomState(1140).randint(
            0, 256, (40, 300, 3), dtype=np.uint8
        )

        y, _ = kapture.locate_frame(previous, current, 100)

        self.assertEqual(y, 100)
        stitched, _ = kapture.stitch_frame(previous, current, y)
        np.testing.assert_array_equal(stitched, page[:500])

    def test_two_small_loaded_regions_preserve_stable_overlap(self):
        page = np.random.RandomState(74).randint(0, 256, (1200, 300, 3), dtype=np.uint8)
        previous = page[:400].copy()
        current = page[100:500].copy()
        current[100:112] = np.random.RandomState(1112).randint(
            0, 256, (12, 300, 3), dtype=np.uint8
        )
        current[130:142] = np.random.RandomState(1142).randint(
            0, 256, (12, 300, 3), dtype=np.uint8
        )

        y, _ = kapture.locate_frame(previous, current, 100)

        self.assertEqual(y, 100)
        stitched, _ = kapture.stitch_frame(previous, current, y)
        np.testing.assert_array_equal(stitched, page[:500])

    def test_single_local_match_cannot_establish_frame_position(self):
        canvas = np.random.RandomState(81).randint(0, 256, (400, 300, 3), dtype=np.uint8)
        current = np.random.RandomState(82).randint(0, 256, (400, 300, 3), dtype=np.uint8)
        current[150:250] = canvas[50:150]

        y, _ = kapture.locate_frame(canvas, current, -100)

        self.assertIsNone(y)

    def test_numbered_text_rows_are_distinguishable(self):
        image = QtGui.QImage(540, 1000, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.white)
        painter = QtGui.QPainter(image)
        painter.setPen(QtCore.Qt.black)
        for y in range(0, 1000, 25):
            painter.drawText(15, y+19, f'Row {y//25:03d} repeated text 0123456789')
        painter.end()
        bgra = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8).reshape(1000, 540, 4)
        page = bgra[:, :, :3].copy()
        y, _ = kapture.locate_frame(page[300:700], page[450:850])
        self.assertEqual(y, 150)
        # Shared boilerplate must not bridge a missing interval when only the
        # row numbers distinguish two non-overlapping viewports.
        self.assertIsNone(kapture.locate_frame(page[:400], page[600:1000])[0])

    def test_manual_worker_handles_reverse_scroll_without_mouse_injection(self):
        page = np.random.RandomState(3).randint(0, 256, (1000, 100, 3), dtype=np.uint8)
        worker = kapture.CaptureWorker((0, 0, 100, 400), manual=True)
        frames = iter([page[200:600], page[400:800], page[200:600], page[:400]])
        results = []
        worker.finished_img.connect(results.append)
        def grab(*args):
            try:
                return next(frames)
            except StopIteration:
                worker.abort()
                return None
        with mock.patch.object(kapture, 'MouseController') as mouse, mock.patch.object(kapture.time, 'sleep'), mock.patch.object(kapture, 'grab_region', side_effect=grab):
            worker.run()
        mouse.assert_not_called()
        np.testing.assert_array_equal(results[0], page[:800])

    def _chrome_mocks(self):
        # Mock overlays whose _wins lists must stay iterable for hide/show/close.
        overlay = mock.patch.object(kapture, 'ScrollRegionOverlay').start()
        hud = mock.patch.object(kapture, 'ScrollHud').start()
        overlay.return_value._wins = []
        self.addCleanup(mock.patch.stopall)
        return overlay, hud

    def _run_worker_loop(self, window):
        # Pump the event loop so the hide-timer and queued signals fire while
        # the worker thread runs (a plain wait() would deadlock the 100 ms timer).
        from PyQt5.QtTest import QTest
        for _ in range(1500):
            if not window.worker.isRunning():
                break
            self.app.processEvents()
            QTest.qWait(10)
        window.worker.wait(5000)
        self.app.processEvents()

    def test_manual_mode_never_hides_capture_chrome(self):
        # The old manual mode grabbed continuously without touching the red
        # frame/HUD; hiding per frame (~2Hz) makes them blink and pulls the
        # stop button out from under the cursor. Neither mode should hide.
        page = np.random.RandomState(3).randint(0, 256, (1000, 100, 3), dtype=np.uint8)
        window = kapture.MainWindow()
        self.addCleanup(window.close)
        self._chrome_mocks()
        window._present_capture = mock.Mock()      # clipboard/editor irrelevant here
        flags = []
        real_prepare = window._prepare_scroll_grab
        window._prepare_scroll_grab = lambda: (flags.append('hide'), real_prepare())[1]
        frames = iter([page[200:600], page[400:800]])
        def grab(*args):
            try:
                return next(frames)
            except StopIteration:
                window.worker.abort()
                return None
        with mock.patch.object(kapture, 'grab_region', side_effect=grab), \
                mock.patch.object(kapture.time, 'sleep'), \
                mock.patch.object(kapture, 'KeyListener'):
            window._start_scroll_worker((0, 0, 100, 400), QtCore.QRect(0, 0, 100, 400),
                                        1.0, manual=True)
            self._run_worker_loop(window)
        self.assertFalse(flags, 'manual capture hid the frame/HUD: ' + str(flags))

    def test_auto_mode_never_hides_capture_chrome(self):
        page = np.random.RandomState(8).randint(0, 256, (1000, 100, 3), dtype=np.uint8)
        window = kapture.MainWindow()
        self.addCleanup(window.close)
        self._chrome_mocks()
        window._present_capture = mock.Mock()
        flags = []
        real_prepare = window._prepare_scroll_grab
        window._prepare_scroll_grab = lambda: (flags.append('hide'), real_prepare())[1]
        frames = iter([page[400:800], page[200:600]])
        def grab(*args):
            try:
                return next(frames)
            except StopIteration:
                window.worker.abort()
                return None
        with mock.patch.object(kapture, 'grab_region', side_effect=grab), \
                mock.patch.object(kapture, 'MouseController'), \
                mock.patch.object(kapture.time, 'sleep'), \
                mock.patch.object(kapture, 'KeyListener'):
            window._start_scroll_worker((0, 0, 100, 400), QtCore.QRect(0, 0, 100, 400),
                                        1.0, manual=False)
            self._run_worker_loop(window)
        self.assertFalse(flags, 'auto capture hid the frame/HUD: ' + str(flags))


if __name__ == '__main__':
    unittest.main()
