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
        images[0].setText("captured_at", "2026-10-09T08:09:10Z")
        self.window.history = [(image, "Region captured: internal detail") for image in images]

        def inspect(dialog):
            dialog.show()
            self.app.processEvents()
            cards = dialog.findChildren(QtWidgets.QToolButton, "historyCard")
            self.assertEqual(len(cards), 3)
            stamp = QtCore.QDateTime.fromString(
                images[0].text("captured_at"), QtCore.Qt.ISODate
            ).toLocalTime().toString("yyyy-MM-dd HH:mm:ss")
            self.assertEqual(cards[0].text(), f"截图 1 · 800 × 450\n{stamp}")
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

    def test_annotation_icons_keep_one_left_aligned_grid_on_wide_editor(self):
        self.window.resize(1200, 660)
        self.app.processEvents()
        row = self.window._annotation_row
        first = row.itemAt(0).geometry()
        self.assertEqual(first.x(), row.geometry().x())
        icon_names = {
            "legacyTool_select", "toolGroup_shape", "toolGroup_stroke",
            "toolGroup_line", "toolGroup_text", "toolGroup_mosaic",
            "toolGroup_aux", "legacyTool_magnify", "annotationColor",
            "annotationUndo", "annotationRedo", "annotationClear",
            "mainOcrButton",
        }
        icons = [widget for widget in self.window._annotation_widgets
                 if widget.objectName() in icon_names]
        self.assertTrue(icons)
        for widget in icons:
            self.assertEqual(widget.width(), 40 if widget.property("editorDropdown") else 36)
        output_index = row.indexOf(self.window.btn_output)
        self.assertGreater(output_index, 0)
        self.assertIsNone(row.itemAt(output_index - 1).widget())
        self.assertGreater(row.itemAt(output_index - 1).geometry().width(), 0)
        row_rect = row.geometry()
        row_right = row.parentWidget().mapTo(
            self.window, QtCore.QPoint(row_rect.right() + 1, row_rect.y())).x()
        output_right = self.window.btn_output.mapTo(
            self.window, QtCore.QPoint(self.window.btn_output.width(), 0)).x()
        self.assertLessEqual(abs(row_right - output_right), 1)

    def test_editor_dropdown_icons_and_arrows_keep_a_gap_at_700px(self):
        for language in ("zh", "en"):
            with self.subTest(language=language):
                kapture.set_lang(language)
                self.window._retranslate()
                self.window.resize(700, 660)
                self.app.processEvents()

                dropdowns = [button for button in self.window.findChildren(
                    QtWidgets.QToolButton
                ) if button.property("editorDropdown") and not button.isHidden()]
                self.assertEqual(len(dropdowns), 9)
                for button in dropdowns:
                    self.assertEqual(button.size(), QtCore.QSize(40, 36))
                    option = QtWidgets.QStyleOptionToolButton()
                    button.initStyleOption(option)
                    menu_rect = button.style().subControlRect(
                        QtWidgets.QStyle.CC_ToolButton, option,
                        QtWidgets.QStyle.SC_ToolButtonMenu, button)
                    self.assertGreaterEqual(menu_rect.width(), 14)
                    self.assertEqual(menu_rect.right(), button.rect().right())

                    image = button.grab().toImage().convertToFormat(
                        QtGui.QImage.Format_ARGB32)
                    bright_columns = []
                    for x in range(image.width()):
                        for y in range(image.height()):
                            color = image.pixelColor(x, y)
                            if min(color.red(), color.green(), color.blue()) > 140 \
                                    and max(color.red(), color.green(), color.blue()) > 200:
                                bright_columns.append(x)
                                break
                    icon_columns = [x for x in bright_columns if x < 27]
                    arrow_columns = [x for x in bright_columns if x >= 27]
                    label = button.objectName() or button.toolTip()
                    self.assertTrue(icon_columns, label)
                    self.assertTrue(arrow_columns, label)
                    gap = min(arrow_columns) - max(icon_columns) - 1
                    self.assertGreaterEqual(gap, 3, label)
                    arrow_right_margin = button.width() - 1 - max(arrow_columns)
                    self.assertGreaterEqual(arrow_right_margin, 5, label)
                    self.assertTrue(menu_rect.contains(QtCore.QPoint(
                        min(arrow_columns), button.height() // 2)), label)
                    if button is self.window._main_tool_groups["shape"][0]:
                        pair_center = (min(icon_columns) + max(arrow_columns)) / 2
                        self.assertLessEqual(abs(pair_center -
                            (button.width() - 1) / 2), 1, label)

                for button in (self.window.btn_single, self.window.btn_scroll):
                    self.assertEqual(button.styleSheet(), "")
                row = self.window._annotation_row
                output_right = self.window.btn_output.mapTo(
                    self.window, QtCore.QPoint(self.window.btn_output.width(), 0)).x()
                row_rect = row.geometry()
                row_right = row.parentWidget().mapTo(
                    self.window, QtCore.QPoint(row_rect.right() + 1, row_rect.y())).x()
                self.assertLessEqual(abs(row_right - output_right), 1)

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
                                        "output:save"})
        self.assertIsNotNone(self.window.btn_ocr.menu())
        calls = []
        for key, method in (("ocr", "run_ocr"), ("copy", "copy_image"),
                            ("pin", "pin_image"), ("save", "save_image")):
            with self.subTest(output=key), mock.patch.object(
                    self.window, method, side_effect=lambda *args, _key=key, **kwargs:
                    calls.append(_key)):
                actions["output:" + key].trigger()
        self.assertEqual(calls, ["ocr", "copy", "pin", "save"])

    def test_output_and_annotation_actions_share_one_toolbar_row(self):
        self.assertFalse(self.window.btn_ocr.isHidden())
        self.assertFalse(self.window.btn_output.isHidden())
        self.assertTrue(self.window.btn_copy.isHidden())
        self.assertTrue(self.window.btn_pin.isHidden())
        self.assertTrue(self.window.btn_save.isHidden())
        self.assertTrue(self.window._output_label.isHidden())

    def test_capture_delay_and_scroll_speed_live_in_their_capture_menus(self):
        self.assertIs(self.window.btn_single.menu(), self.window._capture_menu)
        self.assertIs(self.window.btn_scroll.menu(), self.window._scroll_menu)
        self.assertEqual(self.window.btn_single.popupMode(),
                         QtWidgets.QToolButton.MenuButtonPopup)
        self.assertIs(self.window._capture_settings_action.defaultWidget(),
                      self.window._capture_options_widget)
        self.assertIs(self.window._capture_options_widget.findChild(
            QtWidgets.QSpinBox, "captureDelay"), self.window.delay)
        self.assertIn(self.window._capture_settings_action,
                      self.window._capture_menu.actions())
        self.assertIs(self.window._scroll_settings_action.defaultWidget(),
                      self.window._scroll_options_widget)
        self.assertIs(self.window._scroll_options_widget.findChild(
            QtWidgets.QSpinBox, "scrollSpeed"), self.window.speed)
        scroll_actions = self.window._scroll_menu.actions()
        self.assertIn(self.window._scroll_down_action, scroll_actions)
        self.assertIn(self.window._scroll_up_action, scroll_actions)
        self.assertLess(scroll_actions.index(self.window._scroll_settings_action),
                        scroll_actions.index(self.window._scroll_down_action))
        self.assertIn("窗口截图和截屏取词", self.window.btn_single.toolTip())

        kapture.set_lang("en")
        self.window._retranslate()
        self.assertIn("window capture and text grab", self.window.btn_single.toolTip())
        self.assertEqual(self.window._lab_delay.text(), "Delay")
        self.assertEqual(self.window._lab_speed.text(), "Speed")

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
