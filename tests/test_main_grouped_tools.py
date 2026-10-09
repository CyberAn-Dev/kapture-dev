"""The main editor keeps annotation and output actions in one compact toolbar."""

import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtGui, QtWidgets

import kapture


class MainGroupedToolsTest(unittest.TestCase):
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
        self.window.resize(820, 660)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.tray.hide()
        self.window.close()
        self.desktop_patch.stop()
        kapture.set_lang("zh")

    def test_history_grid_has_centered_thumbnails_and_opens_selected_image(self):
        kapture.set_lang("zh")
        self.window._apply_style("vitesse_dark")
        images = []
        for color, width, height in (("#4d9375", 800, 450), ("#bd976a", 300, 700),
                                     ("#6394bf", 900, 300)):
            image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor(color))
            images.append(image)
        self.window.history = [(image, "Region captured: internal detail") for image in images]

        def inspect(dialog):
            dialog.show()
            self.app.processEvents()
            cards = dialog.findChildren(QtWidgets.QToolButton, "historyCard")
            self.assertEqual(len(cards), 3)
            self.assertEqual(cards[0].text(), "截图 1\n800 × 450")
            self.assertEqual(cards[0].y(), cards[1].y())
            self.assertGreater(cards[1].x(), cards[0].x())
            self.assertGreater(cards[2].y(), cards[0].y())
            self.assertEqual(cards[0].toolButtonStyle(), QtCore.Qt.ToolButtonTextUnderIcon)
            dialog.grab().save("/tmp/kapture-history-grid.png")
            cards[1].click()
            return 0

        with mock.patch.object(QtWidgets.QDialog, "exec_", new=inspect), \
                mock.patch.object(self.window, "_load_history") as load:
            self.window.show_history()
            load.assert_called_once_with(images[1])

    def test_tool_menus_choose_one_canvas_tool_and_keep_group_highlights_exclusive(self):
        groups = getattr(self.window, "_main_tool_groups", {})
        self.assertEqual(set(groups), {"shape", "stroke", "line", "text", "mosaic",
                                       "aux"})
        for group, name, canvas_name in (
                ("shape", "ellipse", "ellipse"),
                ("stroke", "highlight", "highlight"),
                ("line", "line", "line"),
                ("text", "number", "number"),
                ("mosaic", "gaussian", "blur"),
                ("aux", "crop", "crop")):
            with self.subTest(tool=name):
                action = self.window._main_tool_actions[group][name]
                action.trigger()
                self.assertEqual(self.window.canvas.tool, canvas_name)
                if name == "gaussian":
                    self.assertEqual(self.window.canvas.blur_style, "gaussian")
                checked = [key for key, (button, _menu, _names)
                           in self.window._main_tool_groups.items()
                           if button.isChecked()]
                self.assertEqual(checked, [group])
                checked_actions = [action_name
                                   for actions in self.window._main_tool_actions.values()
                                   for action_name, candidate in actions.items()
                                   if candidate.isChecked()]
                self.assertEqual(checked_actions, [name])

    def test_legacy_tool_buttons_still_change_canvas_and_toolbar_state(self):
        self.window._tool_btns["rect"].click()
        self.assertEqual(self.window.canvas.tool, "rect")
        self.assertTrue(self.window._main_tool_groups["shape"][0].isChecked())
        self.assertTrue(self.window._main_tool_actions["shape"]["rect"].isChecked())

    def test_output_menu_exposes_existing_commands_and_ocr_settings_stay_available(self):
        output = getattr(self.window, "btn_output", None)
        self.assertIsNotNone(output)
        self.assertEqual(output.text(), kapture.t("lab_output"))
        actions = {action.objectName(): action for action in output.menu().actions()
                   if action.objectName().startswith("output:")}
        self.assertEqual(set(actions), {"output:ocr", "output:copy", "output:pin",
                                        "output:save", "output:beautify"})
        self.assertIsNotNone(self.window.btn_ocr.menu())
        calls = []
        for key, method in (("ocr", "run_ocr"), ("copy", "copy_image"),
                            ("pin", "pin_image"), ("save", "save_image"),
                            ("beautify", "beautify_export")):
            with self.subTest(output=key), mock.patch.object(
                    self.window, method, side_effect=lambda *args, _key=key, **kwargs:
                    calls.append(_key)):
                actions["output:" + key].trigger()
        self.assertEqual(calls, ["ocr", "copy", "pin", "save", "beautify"])

    def test_output_and_annotation_actions_share_one_toolbar_row(self):
        self.assertFalse(self.window.btn_ocr.isHidden())
        self.assertFalse(self.window.btn_output.isHidden())
        self.assertTrue(self.window.btn_copy.isHidden())
        self.assertTrue(self.window.btn_pin.isHidden())
        self.assertTrue(self.window.btn_save.isHidden())
        self.assertTrue(self.window.btn_beautify.isHidden())
        self.assertTrue(self.window._output_label.isHidden())

    def test_toolbar_fits_820_and_700_pixel_window_widths(self):
        for language in ("zh", "en"):
            kapture.set_lang(language)
            self.window._retranslate()
            for width in (820, 700):
                self.window.resize(width, 660)
                self.app.processEvents()
                row = self.window._annotation_row
                row_rect = row.geometry()
                row_right = row.parentWidget().mapTo(
                    self.window, QtCore.QPoint(row_rect.x() + row_rect.width(), row_rect.y())).x()
                self.assertLessEqual(row_right, self.window.width() - 14,
                                     f"toolbar row overflows at {width} in {language}")
                for widget in self.window._annotation_widgets:
                    if widget.isHidden():
                        continue
                    right = widget.mapTo(self.window, QtCore.QPoint(widget.width(), 0)).x()
                    self.assertLessEqual(right, row_right,
                                         f"{widget.objectName()} overflows at {width} in {language}")

    def test_tool_and_output_menu_labels_and_icons_follow_language_and_theme(self):
        shape_button, shape_menu, _ = self.window._main_tool_groups["shape"]
        output_menu = self.window.btn_output.menu()
        shape_action = self.window._main_tool_actions["shape"]["rect"]
        output_action = next(a for a in output_menu.actions()
                             if a.objectName() == "output:save")
        old_tool_icon = shape_action.icon().cacheKey()
        old_output_icon = output_action.icon().cacheKey()

        kapture.set_lang("en")
        self.window._retranslate()
        self.assertEqual(shape_action.text(), "Rectangle")
        self.assertEqual(output_action.text(), "Save image")
        self.assertEqual(self.window.btn_output.toolTip(), "Output")
        self.window._apply_style("light")
        self.assertNotEqual(shape_action.icon().cacheKey(), old_tool_icon)
        self.assertNotEqual(output_action.icon().cacheKey(), old_output_icon)
        self.assertIsNotNone(shape_menu)
        self.assertIsNotNone(shape_button)

    def test_ocr_layout_labels_follow_chinese_and_english_in_main_and_settings(self):
        self.assertEqual(self.window.psm.itemText(0), "文本块（psm 6）")
        captured = {}

        def inspect(dialog):
            combos = dialog.findChildren(QtWidgets.QComboBox)
            psm = next(combo for combo in combos if combo.findData(6) >= 0
                       and combo is not self.window.psm)
            ui_lang = next(combo for combo in combos if combo.findData("en") >= 0)
            captured["psm"] = psm
            ui_lang.setCurrentIndex(ui_lang.findData("en"))
            self.assertEqual(psm.itemText(0), "Block of text (psm 6)")
            ui_lang.setCurrentIndex(ui_lang.findData("zh"))
            self.assertEqual(psm.itemText(0), "文本块（psm 6）")
            return QtWidgets.QDialog.Rejected

        with mock.patch.object(QtWidgets.QDialog, "exec_", inspect):
            self.window.show_settings()
        kapture.set_lang("en")
        self.window._retranslate()
        self.assertEqual(self.window.psm.itemText(0), "Block of text (psm 6)")


if __name__ == "__main__":
    unittest.main()
