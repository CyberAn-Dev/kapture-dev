"""Compact capture controls still drive the shared annotation canvas."""
import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

import kapture


class CompactToolsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.canvas = kapture.AnnotateCanvas()
        source = np.zeros((48, 48, 3), dtype=np.uint8)
        source[::2, ::2] = (255, 255, 255)
        source[1::2, 1::2] = (255, 255, 255)
        self.canvas.set_image_bgr(source)
        self.host = QtWidgets.QWidget()
        self.tools = kapture.EditTools(self.canvas, self.host, compact=True)

    def tearDown(self):
        self.host.close()
        self.canvas.close()
        self.app.processEvents()

    def test_compact_groups_select_the_existing_canvas_tools(self):
        for group, option in (("shape", "ellipse"), ("stroke", "highlight"),
                              ("line", "line"), ("text", "number")):
            with self.subTest(tool=option):
                self.tools.group_actions[group][option].trigger()
                self.assertEqual(self.canvas.tool, option)
                selected = [name for name, button in self.tools.buttons.items()
                            if button.isChecked()]
                self.assertEqual(selected, [option])
                selected_groups = [key for key, (button, _menu, _names)
                                   in self.tools._compact_groups.items()
                                   if button.isChecked()]
                self.assertEqual(selected_groups, [group])
                selected_actions = [name for actions in self.tools.group_actions.values()
                                    for name, action in actions.items()
                                    if action.isChecked()]
                self.assertEqual(selected_actions, [option])

    def test_legacy_tool_buttons_remain_clickable(self):
        self.tools.buttons["rect"].click()
        self.assertEqual(self.canvas.tool, "rect")
        self.tools.buttons["blur"].click()
        self.assertEqual(self.canvas.tool, "blur")

    def test_mosaic_dropdown_selects_and_records_gaussian_style(self):
        self.tools.group_actions["mosaic"]["gaussian"].trigger()
        self.assertEqual(self.canvas.tool, "blur")
        self.assertEqual(self.canvas.blur_style, "gaussian")
        self.tools.buttons["blur"].click()
        self.assertEqual(self.canvas.blur_style, "pixelate")

        self.tools.buttons["gaussian"].click()
        self.canvas.cur = {
            "type": "blur", "a": QtCore.QPointF(4, 4), "b": QtCore.QPointF(40, 40),
            "color": QtGui.QColor("red"), "width": 3,
            "blur_style": self.canvas.blur_style,
        }
        self.canvas.mouseReleaseEvent(QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease, QtCore.QPointF(40, 40),
            QtCore.Qt.LeftButton, QtCore.Qt.NoButton, QtCore.Qt.NoModifier))
        self.assertEqual(self.canvas.items[-1]["blur_style"], "gaussian")

    def test_compact_controls_are_one_row_and_keep_external_actions_layout(self):
        self.assertIs(self.tools.layout(), self.tools.actions)
        self.assertTrue(self.tools.color.isHidden())
        self.assertTrue(self.tools.note.isHidden())
        row_count = self.tools.actions.count()
        self.tools.note.setText("OCR complete")
        self.assertFalse(self.tools.note.isHidden())
        self.assertEqual(self.tools.actions.count(), row_count)
        self.assertIs(self.tools.note.parentWidget(), self.host)
        self.tools.note.setText("")
        self.assertTrue(self.tools.note.isHidden())
        self.assertIs(self.tools.layout(), self.tools.actions)
        old_count = self.tools.actions.count()
        action = self.tools.action_button("save", "Save", lambda: None)
        self.assertEqual(self.tools.actions.count(), old_count + 1)
        self.assertIs(self.tools.actions.itemAt(old_count).widget(), action)

    def test_compact_tool_aliases_are_hidden_to_prevent_overlap(self):
        for name, button in self.tools.buttons.items():
            if name == "select":
                self.assertFalse(button.isHidden())
            else:
                self.assertTrue(button.isHidden(), name)

    def test_compact_menu_is_popup_and_parent_can_add_full_editor_entry(self):
        _, menu, _ = self.tools._compact_groups["shape"]
        self.assertTrue(menu.windowFlags() & QtCore.Qt.X11BypassWindowManagerHint)
        editor_action = self.tools.add_setting_action("pen", "Full editor", lambda: None)
        self.assertEqual(editor_action.text(), "Full editor")
        self.assertEqual(editor_action.objectName(), "setting:external")

    def test_cancelled_dropdown_does_not_leave_a_stale_tool_highlight(self):
        self.tools.group_actions["shape"]["ellipse"].trigger()
        self.assertEqual(self.canvas.tool, "ellipse")

        for key, (button, menu, names) in self.tools._compact_groups.items():
            button.click()
            menu.hide()
            self.app.processEvents()
            with self.subTest(opened=key):
                current = self.tools.current_tool
                expected = current in names
                self.assertEqual(button.isChecked(), expected)
                active = [group_button for group_button, _menu, _names
                          in self.tools._compact_groups.values()
                          if group_button.isChecked()]
                expected_active = ([group_button for group_button, _menu, group_names
                                    in self.tools._compact_groups.values()
                                    if current in group_names])
                self.assertEqual(active, expected_active)

    def test_full_editor_is_a_direct_action_on_capture_toolbar(self):
        callbacks = []
        pixels = np.zeros((32, 32, 3), dtype=np.uint8)
        editor = kapture.InlineCaptureEditor(
            pixels, QtCore.QRect(100, 100, 32, 32),
            lambda action, _canvas: callbacks.append(action) or True)
        try:
            self.assertEqual(editor.editor_button.toolTip(), kapture.t("open_editor"))
            editor.editor_button.click()
            self.assertEqual(callbacks, ["editor"])
        finally:
            editor.close()
            self.app.processEvents()

    def test_settings_menu_keeps_width_and_undo_redo_commands_functional(self):
        self.tools.line_width.setValue(9)
        self.assertEqual(self.canvas.width, 9)

        self.canvas.items.append({
            "type": "rect", "a": QtCore.QPointF(4, 4), "b": QtCore.QPointF(30, 30),
            "color": QtGui.QColor("red"), "width": 3,
        })
        actions = {action.objectName(): action
                   for action in self.tools.settings_menu.actions()
                   if action.objectName().startswith("setting:")}
        self.tools.undo_button.click()
        self.assertEqual(self.canvas.items, [])
        actions["setting:redo"].trigger()
        self.assertEqual(len(self.canvas.items), 1)
        actions["setting:clear"].trigger()
        self.assertEqual(self.canvas.items, [])

    def test_pixelated_blur_remains_default_and_gaussian_blur_is_distinct(self):
        bounds = (QtCore.QPointF(4, 4), QtCore.QPointF(42, 42))
        base = {"a": bounds[0], "b": bounds[1], "color": QtGui.QColor("red"),
                "width": 3, "type": "blur"}
        self.canvas.items = [dict(base)]
        default_pixels = kapture.qimage_to_bgr(self.canvas.render_flattened())
        self.canvas.items = [dict(base, blur_style="pixelate")]
        explicit_pixels = kapture.qimage_to_bgr(self.canvas.render_flattened())
        np.testing.assert_array_equal(default_pixels, explicit_pixels)

        self.canvas.items = [dict(base, blur_style="gaussian")]
        gaussian_pixels = kapture.qimage_to_bgr(self.canvas.render_flattened())
        self.assertFalse(np.array_equal(default_pixels[4:42, 4:42],
                                        gaussian_pixels[4:42, 4:42]))


if __name__ == "__main__":
    unittest.main()
