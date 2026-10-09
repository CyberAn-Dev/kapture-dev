"""OCR preserves paragraph boundaries and antialiased screenshot strokes."""
import unittest
import cv2
import numpy as np
import kapture


class OcrQualityTest(unittest.TestCase):
    def test_chinese_cleanup_keeps_paragraphs_and_english_word_spaces(self):
        text = '产 品 定 位\n建 议 讨 论\n\n中 文 English words\r\n下 一 段'
        self.assertEqual(kapture._strip_cjk_spaces(text),
                         '产品定位\n建议讨论\n\n中文 English words\r\n下一段')

    def test_enhancement_preserves_soft_stroke_edges(self):
        image = np.full((30, 40, 3), 245, dtype=np.uint8)
        cv2.putText(image, 'A', (4, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    .7, (30, 30, 30), 1, cv2.LINE_AA)
        enhanced = kapture.preprocess_for_ocr(image)
        self.assertEqual(enhanced.shape, (60, 80))
        self.assertGreater(len(np.unique(enhanced)), 20)
        self.assertGreater(enhanced[0, 0], 200)

    def test_dark_screenshot_is_inverted_without_losing_gray_edges(self):
        image = np.full((30, 40, 3), 20, dtype=np.uint8)
        cv2.putText(image, 'A', (4, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    .7, (235, 235, 235), 1, cv2.LINE_AA)
        enhanced = kapture.preprocess_for_ocr(image)
        self.assertGreater(enhanced[0, 0], 200)
        self.assertGreater(len(np.unique(enhanced)), 20)
