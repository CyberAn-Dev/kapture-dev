"""Native editing menus follow Kapture language while preserving shortcuts/actions."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
from PyQt5 import QtWidgets
import kapture

class NativeTextLanguageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):self.original=kapture._LANG
    def tearDown(self):kapture.set_lang(self.original)

    def test_chinese_plain_text_menu_keeps_real_copy_and_shortcuts(self):
        kapture.set_lang('zh')
        text=QtWidgets.QPlainTextEdit('中文测试');text.selectAll()
        menu=text.createStandardContextMenu()
        labels=[action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertEqual([label.split('\t')[0] for label in labels],
                         ['撤销','重做','剪切','复制','粘贴','删除','全选'])
        copy=next(action for action in menu.actions() if action.text().startswith('复制'))
        self.assertIn('Ctrl+C',copy.text());self.assertTrue(copy.isEnabled())
        copy.trigger();self.assertEqual(self.app.clipboard().text(),'中文测试')
        text.close();menu.close()

    def test_line_edit_menu_and_runtime_language_switch(self):
        text=QtWidgets.QLineEdit('text');text.selectAll()
        kapture.set_lang('zh');menu=text.createStandardContextMenu()
        self.assertTrue(any(action.text().startswith('复制') for action in menu.actions()))
        menu.close();kapture.set_lang('en');menu=text.createStandardContextMenu()
        self.assertTrue(any('Copy' in action.text() for action in menu.actions()))
        self.assertTrue(any('Ctrl+C' in action.text() for action in menu.actions()))
        text.close();menu.close()
