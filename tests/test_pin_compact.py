"""Pinned annotation controls reuse the compact capture-time toolbar."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtGui, QtWidgets

import kapture


class PinnedCompactToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.image = QtGui.QImage(180, 100, QtGui.QImage.Format_RGB32)
        self.image.fill(QtGui.QColor("#d9e4ef"))
        self.editor_documents = []
        self.pin = kapture.PinnedImage(
            self.image, on_ocr=lambda _image: None,
            on_edit=self.editor_documents.append)

    def tearDown(self):
        self.pin.close()
        self.app.processEvents()

    def _edit(self):
        self.pin.set_editing(True)
        self.app.processEvents()
        self.assertTrue(self.pin.tools.note.isHidden())
        return self.pin.tools

    def _add_document_item(self):
        item = {
            "type": "rect", "a": QtCore.QPointF(8, 9),
            "b": QtCore.QPointF(70, 50),
            "color": QtGui.QColor("red"), "width": 3,
        }
        before = self.pin.canvas._content_state()
        self.pin.canvas.items.append(item)
        self.pin.canvas._commit_change(before)
        return item

    def test_pin_uses_grouped_compact_tools_and_keeps_undo_and_ocr(self):
        tools = self._edit()

        self.assertTrue(tools.compact)
        tools.group_actions["shape"]["ellipse"].trigger()
        self.assertEqual(self.pin.canvas.tool, "ellipse")
        self.assertEqual(tools.buttons["select"].size(), QtCore.QSize(40, 40))
        self.assertTrue(hasattr(tools, "undo_button"))
        picktext_action = next(action for action in tools.settings_menu.actions()
                               if action.objectName() == "tool:picktext")
        self.pin.canvas.set_word_boxes([
            (QtCore.QRectF(8, 9, 20, 12), "word")])
        picktext_action.trigger()
        self.assertEqual(self.pin.canvas.tool, "picktext")
        self.assertEqual(self.pin.canvas._word_boxes[0][1], "word")

        self._add_document_item()
        tools.undo_button.click()
        self.assertEqual(self.pin.canvas.items, [])

    def test_copy_save_finish_and_editor_handoff_keep_pin_document(self):
        tools = self._edit()
        self._add_document_item()
        action_buttons = {
            button.toolTip(): button for button in tools.findChildren(QtWidgets.QToolButton)
            if button.toolTip()
        }

        self.assertIn(kapture.t("card_copy"), action_buttons)
        self.assertIn(kapture.t("card_save"), action_buttons)
        self.assertIn(kapture.t("finish_edit"), action_buttons)
        self.assertTrue(any(action.objectName() == "setting:external"
                            and action.text() == kapture.t("open_editor")
                            for action in tools.settings_menu.actions()))

        tools.settings_menu.actions()[-1].trigger()
        self.assertEqual(len(self.editor_documents), 1)
        self.assertEqual(len(self.editor_documents[0]["items"]), 1)
        self.assertEqual(len(self.editor_documents[0]["undo"]), 1)

        self.pin._copy_image()
        self.assertFalse(QtWidgets.QApplication.clipboard().image().isNull())

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "pinned.png")
            with patch.object(QtWidgets.QFileDialog, "getSaveFileName",
                              return_value=(path, "PNG (*.png)")):
                self.pin._save_image()
            self.assertTrue(os.path.isfile(path))

        finish = action_buttons[kapture.t("finish_edit")]
        finish.click()
        self.assertFalse(self.pin._editing)
        self.assertFalse(self.pin.tools.isVisible())
        self.assertTrue(self.pin.tools.note.isHidden())
        self.assertFalse(self.pin.canvas.isVisible())

        self.pin.set_editing(True)
        self.assertIs(self.pin.tools, tools)
        self.assertEqual(len(self.pin.canvas.items), 1)
        self.assertEqual(len(self.pin.canvas._undo_stack), 1)
        self.assertTrue(self.pin.tools.note.isHidden())
        self.pin.tools.undo_button.click()
        self.assertEqual(self.pin.canvas.items, [])
        redo = next(action for action in tools.settings_menu.actions()
                    if action.objectName() == "setting:redo")
        redo.trigger()
        self.assertEqual(len(self.pin.canvas.items), 1)

    def test_full_editor_is_directly_available_from_pin_edit_toolbar(self):
        tools = self._edit()
        self.assertEqual(self.pin.editor_button.toolTip(), kapture.t("open_editor"))

        self._add_document_item()
        self.pin.editor_button.click()

        self.assertEqual(len(self.editor_documents), 1)
        self.assertEqual(len(self.editor_documents[0]["items"]), 1)

    def test_compact_toolbar_fits_pin_at_minimum_and_maximum_zoom(self):
        tools = self._edit()

        for scale in (0.1, 5.0):
            with self.subTest(scale=scale):
                self.pin._scale = scale
                self.pin._apply()
                self.app.processEvents()
                self.assertGreaterEqual(self.pin.width(), tools.width())
                self.assertLessEqual(tools.x() + tools.width(), self.pin.width())
                self.assertEqual(tools.y(), self.pin.canvas.height())
                self.assertEqual(self.pin.height(),
                                 self.pin.canvas.height() + tools.height())

    def test_opening_wide_toolbar_keeps_small_pin_inside_screen(self):
        screen = QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.pin.move(available.right() - 20, available.bottom() - 20)

        self._edit()

        self.assertGreaterEqual(self.pin.x(), available.left())
        self.assertGreaterEqual(self.pin.y(), available.top())
        self.assertLessEqual(self.pin.x() + self.pin.width(),
                             available.left() + available.width())
        self.assertLessEqual(self.pin.y() + self.pin.height(),
                             available.top() + available.height())


if __name__ == "__main__":
    unittest.main()
