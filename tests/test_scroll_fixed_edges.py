import os
import unittest
from unittest import mock
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
import kapture


class FixedScrollEdgesTest(unittest.TestCase):
    def setUp(self):
        self.page = np.random.RandomState(33).randint(0, 256, (1800, 300, 3), dtype=np.uint8)

    def viewport(self, top, header=40, footer=8):
        return np.concatenate((np.full((header, 300, 3), 210, np.uint8),
                               self.page[top:top+400-header-footer],
                               np.full((footer, 300, 3), 180, np.uint8)))

    def capture(self, frames, manual=True, direction=1, max_height=40000):
        worker = kapture.CaptureWorker((0, 0, 300, 400), manual=manual,
                                       max_iters=len(frames)-1, direction=direction, max_height=max_height)
        result = []
        worker.finished_img.connect(result.append)
        source = iter(frames)
        def grab(*args):
            image = next(source, None)
            if image is None:
                worker.abort()
            return image
        with mock.patch.object(kapture, 'grab_region', side_effect=grab), \
             mock.patch.object(kapture, 'MouseController'), \
             mock.patch.object(kapture.time, 'sleep'):
            worker.run()
        return result[0]

    def test_small_side_changes_do_not_reject_real_overlap(self):
        first, second = self.page[:400].copy(), self.page[100:500].copy()
        second[:, :2] = 180
        second[:, -2:] = 180
        self.assertEqual(kapture.locate_frame(first, second)[0], 100)

    def test_static_blank_with_changing_side_edges_stays_put(self):
        first = np.full((400, 300, 3), 255, np.uint8)
        second = first.copy()
        second[:, :2] = 180
        second[:, -2:] = 180
        self.assertEqual(kapture.locate_frame(first, second)[0], 0)

    def test_fixed_header_footer_are_preserved_only_once_in_both_modes(self):
        for manual in (True, False):
            with self.subTest(manual=manual):
                result = self.capture([self.viewport(y) for y in [0, 100, 200, 300]], manual)
                expected = np.concatenate((self.viewport(0)[:40], self.page[:652], self.viewport(0)[-8:]))
                np.testing.assert_array_equal(result, expected)

    def test_thin_gray_borders_do_not_repeat_at_every_seam(self):
        result = self.capture([self.viewport(y, 4, 4) for y in [0, 100, 200, 300]])
        expected = np.concatenate((self.viewport(0, 4, 4)[:4], self.page[:692], self.viewport(0, 4, 4)[-4:]))
        np.testing.assert_array_equal(result, expected)

    def test_fixed_edges_survive_up_down_revisits(self):
        result = self.capture([self.viewport(y) for y in [200, 400, 200, 0, 200, 400, 600]])
        expected = np.concatenate((self.viewport(0)[:40], self.page[:952], self.viewport(0)[-8:]))
        np.testing.assert_array_equal(result, expected)

    def test_auto_up_with_fixed_edges(self):
        result = self.capture([self.viewport(y) for y in [300, 200, 100, 0]], False, -1)
        expected = np.concatenate((self.viewport(0)[:40], self.page[:652], self.viewport(0)[-8:]))
        np.testing.assert_array_equal(result, expected)

    def test_numbered_text_extreme_edges_follow_latest_top_and_bottom(self):
        self.page = np.full((1800, 300, 3), 255, np.uint8)
        for y in range(0, 1800, 25):
            kapture.cv2.putText(self.page, f'Row {y//25:03d} abcdef 0123456789', (15, y+18),
                               kapture.cv2.FONT_HERSHEY_SIMPLEX, .5, (30, 30, 30), 1)
        result = self.capture([self.viewport(y) for y in [200, 400, 200, 0, 200, 400, 600]])
        expected = np.concatenate((self.viewport(0)[:40], self.page[:952], self.viewport(600)[-8:]))
        np.testing.assert_array_equal(result, expected)

    def test_height_limit_crops_contiguous_pixels_with_fixed_edges(self):
        for direction, positions in [(1, [0, 100, 200]), (-1, [200, 100, 0])]:
            with self.subTest(direction=direction):
                result = self.capture([self.viewport(y) for y in positions], False,
                                      direction, max_height=550)
                complete = np.concatenate((self.viewport(0)[:40], self.page[:552],
                                           self.viewport(0)[-8:]))
                expected = complete[:550] if direction == 1 else complete[-550:]
                np.testing.assert_array_equal(result, expected)

    def test_static_header_cannot_locate_unrelated_body(self):
        result = self.capture([self.viewport(0), self.viewport(1000)], False)
        np.testing.assert_array_equal(result, self.viewport(0))

    def test_identical_frames_do_not_lock_the_entire_viewport_as_header(self):
        result = self.capture([self.viewport(y) for y in [0, 0, 0, 100, 200]])
        expected = np.concatenate((self.viewport(0)[:40], self.page[:552], self.viewport(0)[-8:]))
        np.testing.assert_array_equal(result, expected)


if __name__ == '__main__':
    unittest.main()
