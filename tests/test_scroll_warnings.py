import os
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtWidgets

import kapture


class ScrollWarningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _run_worker(self, frames, *, manual, max_iters=20):
        worker = kapture.CaptureWorker((0, 0, 100, 400), manual=manual,
                                       max_iters=max_iters)
        progress = []
        results = []
        worker.progress.connect(progress.append)
        worker.finished_img.connect(results.append)
        frames = iter(frames)

        def grab(*_args):
            try:
                return next(frames)
            except StopIteration:
                worker.abort()
                return None

        with mock.patch.object(kapture, "MouseController"), \
                mock.patch.object(kapture.time, "sleep"), \
                mock.patch.object(kapture, "grab_region", side_effect=grab):
            worker.run()
        return progress, results[0]

    def test_manual_transient_unmatched_frame_is_silent_and_recovery_resets(self):
        page = np.random.RandomState(41).randint(0, 256, (1200, 100, 3), dtype=np.uint8)
        unrelated = np.random.RandomState(42).randint(0, 256, (400, 100, 3), dtype=np.uint8)
        progress, _ = self._run_worker([
            page[:400], unrelated, page[100:500],
        ], manual=True)

        manual_warning = kapture.t("scroll_manual_unmatched")
        self.assertNotIn(manual_warning, progress)
        self.assertNotIn(kapture.t("scroll_unmatched"), progress)
        self.assertEqual(progress[-1], f"500 px · Esc {kapture.t('hud_stop')}")

    def test_manual_stable_unmatched_frames_warn_once_without_stopping(self):
        page = np.random.RandomState(43).randint(0, 256, (1200, 100, 3), dtype=np.uint8)
        unrelated = np.random.RandomState(44).randint(0, 256, (400, 100, 3), dtype=np.uint8)
        progress, canvas = self._run_worker(
            [page[:400], unrelated, unrelated.copy(), unrelated.copy(), unrelated.copy(),
             page[100:500]],
            manual=True,
        )

        manual_warning = kapture.t("scroll_manual_unmatched")
        self.assertEqual(progress.count(manual_warning), 1)
        self.assertNotIn(kapture.t("scroll_unmatched"), progress)
        self.assertEqual(canvas.shape[0], 500)
        self.assertEqual(progress[-1], f"500 px · Esc {kapture.t('hud_stop')}")

    def test_manual_match_clears_unmatched_streak(self):
        page = np.random.RandomState(47).randint(0, 256, (1200, 100, 3), dtype=np.uint8)
        unrelated = np.random.RandomState(48).randint(0, 256, (400, 100, 3), dtype=np.uint8)
        progress, _ = self._run_worker(
            [page[:400], unrelated, unrelated.copy(), unrelated.copy(),
             page[100:500], unrelated, unrelated.copy(), unrelated.copy()],
            manual=True,
        )

        self.assertEqual(progress.count(kapture.t("scroll_manual_unmatched")), 2)

    def test_auto_unmatched_still_uses_stop_warning(self):
        page = np.random.RandomState(45).randint(0, 256, (1200, 100, 3), dtype=np.uint8)
        unrelated = np.random.RandomState(46).randint(0, 256, (400, 100, 3), dtype=np.uint8)
        progress, canvas = self._run_worker([page[:400], unrelated], manual=False,
                                            max_iters=3)

        self.assertIn(kapture.t("scroll_unmatched"), progress)
        self.assertNotIn(kapture.t("scroll_manual_unmatched"), progress)
        self.assertEqual(canvas.shape[0], 400)


if __name__ == "__main__":
    unittest.main()
