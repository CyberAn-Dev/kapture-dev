"""Editing, history, and document handoff behavior for AnnotateCanvas."""

import os
import unittest
from unittest import mock

import numpy as np

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtGui, QtTest, QtWidgets

import kapture


class CanvasEditingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.canvas = kapture.AnnotateCanvas()
        self.canvas.set_image_bgr(np.full((120, 160, 3), 240, dtype=np.uint8))
        self.canvas.show()
        self.app.processEvents()

    def tearDown(self):
        self.canvas.close()

    def _mouse(self, event_type, pos, button, buttons):
        if isinstance(pos, tuple):
            pos = QtCore.QPointF(*pos)
        event = QtGui.QMouseEvent(
            event_type, QtCore.QPointF(pos), button, buttons, QtCore.Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(self.canvas, event)

    def _drag(self, start, end):
        self._mouse(QtCore.QEvent.MouseButtonPress, start,
                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self._mouse(QtCore.QEvent.MouseMove, end,
                    QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
        self._mouse(QtCore.QEvent.MouseButtonRelease, end,
                    QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        self.app.processEvents()

    def _draw_rect(self, start=(20, 20), end=(80, 70)):
        self.canvas.set_tool("rect")
        self._drag(start, end)

    def test_redo_restores_annotation_after_undo(self):
        self._draw_rect()
        self.canvas.undo()
        self.assertEqual(self.canvas.items, [])

        redo = getattr(self.canvas, "redo", None)
        self.assertTrue(callable(redo), "AnnotateCanvas must provide redo()")
        redo()
        self.assertEqual(len(self.canvas.items), 1)
        self.assertEqual(self.canvas.items[0]["type"], "rect")

    def test_clear_items_can_be_undone_and_redone(self):
        self._draw_rect()
        self.canvas.clear_items()
        self.assertEqual(self.canvas.items, [])
        self.canvas.undo()
        self.assertEqual(len(self.canvas.items), 1)
        self.canvas.redo()
        self.assertEqual(self.canvas.items, [])

    def test_changed_signal_fires_after_document_edits(self):
        changed = QtTest.QSignalSpy(self.canvas.changed)
        self._draw_rect()
        self.canvas.clear_items()
        self.canvas.undo()
        self.assertEqual(len(changed), 3)

    def test_select_moves_shape_and_undo_restores_position(self):
        self._draw_rect()
        self.canvas.set_tool("select")
        self._drag((20, 45), (35, 55))
        rect = self.canvas.items[0]
        self.assertEqual(rect["a"], QtCore.QPointF(35, 30))
        self.assertEqual(rect["b"], QtCore.QPointF(95, 80))
        self.canvas.undo()
        self.assertEqual(self.canvas.items[0]["a"], QtCore.QPointF(20, 20))

    def test_hollow_rectangle_and_arrow_do_not_hit_their_empty_interior(self):
        self._draw_rect()
        self.canvas.set_tool("select")
        self._mouse(QtCore.QEvent.MouseButtonPress, (50, 45),
                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self.assertIsNone(self.canvas._selected_item)

        self.canvas.items.clear()
        self.canvas.set_tool("arrow")
        self._drag((20, 20), (100, 20))
        self.canvas.set_tool("select")
        self._mouse(QtCore.QEvent.MouseButtonPress, (60, 45),
                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self.assertIsNone(self.canvas._selected_item)

    def test_color_and_width_update_selected_object_with_history(self):
        self._draw_rect()
        self.canvas.set_tool("select")
        self._mouse(QtCore.QEvent.MouseButtonPress, (20, 45),
                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self.canvas.set_color(QtGui.QColor("#00aa88"))
        self.canvas.set_width(7)
        self.assertEqual(self.canvas.items[0]["color"].name(), "#00aa88")
        self.assertEqual(self.canvas.items[0]["width"], 7)
        self.canvas.undo()
        self.assertEqual(self.canvas.items[0]["color"].name(), "#00aa88")
        self.assertEqual(self.canvas.items[0]["width"], 3)
        self.canvas.undo()
        self.assertEqual(self.canvas.items[0]["color"].name(), "#ff2828")
        self.assertEqual(self.canvas.items[0]["width"], 3)
        self.canvas.redo()
        self.canvas.redo()
        self.assertEqual(self.canvas.items[0]["width"], 7)

    def test_delete_key_removes_selected_object_and_can_be_undone(self):
        self._draw_rect()
        self.canvas.set_tool("select")
        self._mouse(QtCore.QEvent.MouseButtonPress, (20, 45),
                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self.canvas.setFocus()
        QtTest.QTest.keyClick(self.canvas, QtCore.Qt.Key_Delete)
        self.assertEqual(self.canvas.items, [])
        self.canvas.undo()
        self.assertEqual(len(self.canvas.items), 1)

    def test_double_click_edits_selected_text_and_can_be_undone(self):
        self.canvas.items.append({
            "type": "text", "a": QtCore.QPointF(20, 60), "text": "Edit",
            "color": QtGui.QColor("red"), "width": 3,
        })
        self.canvas.set_tool("select")
        with mock.patch.object(QtWidgets.QInputDialog, "getText",
                               return_value=("Changed", True)) as get_text:
            self._mouse(QtCore.QEvent.MouseButtonDblClick, (22, 50),
                        QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        get_text.assert_called_once()
        self.assertEqual(self.canvas.items[0]["text"], "Changed")
        self.canvas.undo()
        self.assertEqual(self.canvas.items[0]["text"], "Edit")

    def test_selection_decoration_is_not_flattened_into_export(self):
        self._draw_rect()
        before = self.canvas.render_flattened()
        self.canvas.set_tool("select")
        self._mouse(QtCore.QEvent.MouseButtonPress, (20, 45),
                    QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        after = self.canvas.render_flattened()
        self.assertEqual(before.size(), after.size())
        for y in range(before.height()):
            for x in range(before.width()):
                self.assertEqual(before.pixel(x, y), after.pixel(x, y))

    def test_document_snapshot_restores_base_items_and_redo_history(self):
        self._draw_rect()
        self.canvas.undo()
        state = self.canvas.snapshot_document()
        self._draw_rect((90, 20), (130, 60))
        self.canvas.restore_document(state)
        self.assertEqual(self.canvas.items, [])
        self.assertEqual(self.canvas.base.size(), QtCore.QSize(160, 120))
        self.canvas.redo()
        self.assertEqual(len(self.canvas.items), 1)
        self.assertEqual(self.canvas.items[0]["a"], QtCore.QPointF(20, 20))

    def test_crop_image_is_undoable_and_keeps_crop_request_signal(self):
        self._draw_rect()
        emitted = []
        self.canvas.cropRequested.connect(emitted.append)
        self.assertTrue(self.canvas.crop_image(QtCore.QRectF(10, 10, 80, 60)))
        self.assertEqual(self.canvas.base.size(), QtCore.QSize(80, 60))
        self.assertEqual(self.canvas.items[0]["a"], QtCore.QPointF(10, 10))
        self.canvas.undo()
        self.assertEqual(self.canvas.base.size(), QtCore.QSize(160, 120))
        self.canvas.redo()
        self.assertEqual(self.canvas.base.size(), QtCore.QSize(80, 60))
        self.assertEqual(emitted, [])


if __name__ == "__main__":
    unittest.main()
