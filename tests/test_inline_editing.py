"""Capture-time editing and pinned edits must preserve the editable document."""
import os
import tempfile
import unittest
from unittest import mock
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets, QtTest
import kapture

class InlineEditingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': self.tmp.name,
                                               'XDG_DATA_HOME': self.tmp.name})
        self.env.start()
        self.desktop = mock.patch.object(kapture, 'write_desktop_entry')
        self.desktop.start()
        QtCore.QSettings.setPath(QtCore.QSettings.NativeFormat, QtCore.QSettings.UserScope, self.tmp.name)
        QtCore.QSettings("ScrollShot","ScrollShot").clear()
        self.w = kapture.MainWindow()
        self.w.settings.setValue('auto_ocr', False)
        self.img = np.full((120, 240, 3), 255, dtype=np.uint8)
        self.app.clipboard().setText('keep until confirmed')

    def tearDown(self):
        for obj in [getattr(self.w, '_inline_editor', None), getattr(self.w, '_thumb', None)]:
            if obj: obj.close()
        for pin in list(kapture.PinnedImage._pins): pin.close()
        for worker in self.w._ocr_workers: worker.wait()
        self.w._history_writer.shutdown()
        self.app.processEvents()
        self.w.tray.hide(); self.w.close(); self.w.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.desktop.stop(); self.env.stop(); self.tmp.cleanup()

    def open_capture(self):
        self.w._present_capture(self.img, 'Capture')
        edit = getattr(self.w, '_inline_editor', None)
        self.assertIsNotNone(edit, 'A new capture should open inline editing by default')
        return edit

    def draw(self, canvas):
        canvas.set_tool('rect')
        for typ, pt, button, buttons in [
            (QtCore.QEvent.MouseButtonPress, (10,10), QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
            (QtCore.QEvent.MouseMove, (80,70), QtCore.Qt.NoButton, QtCore.Qt.LeftButton),
            (QtCore.QEvent.MouseButtonRelease, (80,70), QtCore.Qt.LeftButton, QtCore.Qt.NoButton)]:
            event=QtGui.QMouseEvent(typ,QtCore.QPointF(*pt),button,buttons,QtCore.Qt.NoModifier)
            self.app.sendEvent(canvas,event)

    def test_cancel_keeps_clipboard_and_history_unchanged(self):
        count=len(self.w.history)
        edit=self.open_capture()
        self.assertEqual(self.app.clipboard().text(),'keep until confirmed')
        edit.close()
        self.assertEqual(len(self.w.history),count)
        self.assertEqual(self.app.clipboard().text(),'keep until confirmed')

    def test_copy_exports_annotations_and_adds_single_history_item(self):
        edit=self.open_capture(); self.draw(edit.canvas)
        expected=edit.canvas.render_flattened()
        edit.finish('copy')
        self.assertEqual(self.app.clipboard().image(),expected)
        self.assertEqual(len(self.w.history),1)
        self.assertEqual(self.w.history[0][0],expected)
        self.assertFalse(edit.isVisible())

    def test_open_editor_keeps_annotations_editable(self):
        edit=self.open_capture(); self.draw(edit.canvas)
        edit.finish('editor')
        self.assertEqual(len(self.w.canvas.items),1)
        self.w.canvas.undo()
        self.assertEqual(len(self.w.canvas.items),0)
        self.w.canvas.redo()
        self.assertEqual(len(self.w.canvas.items),1)

    def test_pin_menu_exposes_annotation_and_selectable_text(self):
        pin=kapture.PinnedImage(kapture.bgr_to_qimage(self.img))
        labels=[a.text() for a in pin._build_menu().actions()]
        self.assertIn('标注 / 编辑',labels)
        self.assertIn('选取文字',labels)

    def test_explicit_editor_setting_still_opens_editor(self):
        self.w.settings.setValue('open_editor',True)
        self.w._present_capture(self.img,'Capture')
        self.assertTrue(self.w.isVisible())
        self.assertIsNone(getattr(self.w,'_inline_editor',None))

    def test_pin_edits_copy_and_handoff_keep_document(self):
        pin=self.w._new_pin(kapture.bgr_to_qimage(self.img))
        pin.set_editing(True)
        self.draw(pin.canvas)
        pin._copy_image()
        self.assertEqual(self.app.clipboard().image(),pin.canvas.render_flattened())
        pin._open_in_editor()
        self.assertEqual(len(self.w.canvas.items),1)
        self.w.canvas.undo()
        self.assertEqual(len(self.w.canvas.items),0)
        self.assertEqual(len(pin.canvas.items),1)

    def test_pin_word_selection_copies_at_zoomed_coordinates(self):
        pin=self.w._new_pin(kapture.bgr_to_qimage(self.img))
        pin.set_editing(True)
        pin.canvas.set_word_boxes([(QtCore.QRectF(10,10,40,20),'hello'),
                                   (QtCore.QRectF(60,10,40,20),'world')])
        pin.tools.set_tool('picktext')
        pin._scale=2; pin._apply()
        for typ,pt,button,buttons in [
            (QtCore.QEvent.MouseButtonPress,(40,30),QtCore.Qt.LeftButton,QtCore.Qt.LeftButton),
            (QtCore.QEvent.MouseMove,(140,30),QtCore.Qt.NoButton,QtCore.Qt.LeftButton),
            (QtCore.QEvent.MouseButtonRelease,(140,30),QtCore.Qt.LeftButton,QtCore.Qt.NoButton)]:
            self.app.sendEvent(pin.canvas,QtGui.QMouseEvent(typ,QtCore.QPointF(*pt),button,buttons,QtCore.Qt.NoModifier))
        self.assertEqual(self.app.clipboard().text(),'hello world')

    def test_loading_history_replaces_existing_editor_document(self):
        self.w._load_into_editor(self.img)
        image=QtGui.QImage(30,20,QtGui.QImage.Format_RGB32); image.fill(QtCore.Qt.blue)
        self.w._load_history(image)
        self.assertEqual(self.w.canvas.base.size(),QtCore.QSize(30,20))
        self.assertEqual(self.w.canvas.base.pixelColor(5,5),QtGui.QColor(QtCore.Qt.blue))

    def test_restart_restores_capture_and_clipboard_and_clear_removes_both(self):
        self.w._add_history(kapture.bgr_to_qimage(self.img),'Saved capture')
        self.app.clipboard().setImage(kapture.bgr_to_qimage(self.img))
        self.assertTrue(self.w._history_writer.flush(3))
        restored=kapture.MainWindow()
        try:
            self.assertEqual(restored.history[0][1],'Saved capture')
            stamp = restored.history[0][0].text('captured_at')
            self.assertTrue(QtCore.QDateTime.fromString(stamp, QtCore.Qt.ISODate).isValid())
            self.assertEqual(stamp, self.w.history[0][0].text('captured_at'))
            self.assertEqual(restored.history[0][0].text('timestamp_source'), 'capture')
            np.testing.assert_array_equal(kapture.qimage_to_bgr(restored._clip_images[0]),self.img)
            self.assertTrue(restored._clear_history())
            self.assertTrue(restored._history_writer.flush(3))
            self.app.processEvents()
            self.assertEqual(restored._history_store.load(),([],[]))
        finally:
            restored._history_writer.shutdown()
            restored.tray.hide();restored.close();restored.deleteLater()

    def test_second_capture_keeps_unconfirmed_document(self):
        edit=self.open_capture(); self.draw(edit.canvas)
        self.w._present_capture(np.zeros_like(self.img),'Second')
        self.assertIs(self.w._inline_editor,edit)
        self.assertTrue(edit.isVisible())
        self.assertEqual(len(edit.canvas.items),1)

    def test_closed_inline_window_is_released(self):
        edit=self.open_capture(); edit.close()
        self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.assertIsNone(self.w._inline_editor)
        self.assertEqual(self.w.findChildren(kapture.InlineCaptureEditor),[])

    def test_failed_inline_save_keeps_document_open_and_history_empty(self):
        edit=self.open_capture(); self.draw(edit.canvas)
        with mock.patch.object(QtWidgets.QFileDialog,'getSaveFileName',return_value=('/not-writable/capture.png','PNG')):
            edit.finish('save')
        self.assertTrue(edit.isVisible())
        self.assertEqual(len(self.w.history),0)
        self.assertEqual(self.app.clipboard().text(),'keep until confirmed')
        self.assertIn('保存失败',edit.tools.note.text())

    def test_closing_pin_during_ocr_retires_after_worker_finishes(self):
        import threading
        started=threading.Event(); release=threading.Event()
        def recognize(*args,**kwargs):
            started.set(); release.wait(2); return 'hello'
        pin=self.w._new_pin(kapture.bgr_to_qimage(self.img))
        with mock.patch('pytesseract.image_to_string',side_effect=recognize):
            pin.set_editing(True,'picktext')
            self.assertTrue(started.wait(1))
            workers=list(pin.tools._workers)
            pin.close()
            self.assertIn(pin,kapture.EditTools._retired)
            self.assertTrue(workers[0].isInterruptionRequested())
            release.set()
            for worker in workers: self.assertTrue(worker.wait(2000))
            self.app.processEvents()
            self.app.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
        self.assertNotIn(pin,kapture.EditTools._retired)
        self.assertNotIn(pin,kapture.PinnedImage._pins)

    def test_clear_does_not_resurrect_old_history_when_new_capture_arrives(self):
        self.w._add_history(kapture.bgr_to_qimage(self.img),'old')
        self.assertTrue(self.w._history_writer.flush(3))
        self.assertTrue(self.w._clear_history())
        self.w._add_history(kapture.bgr_to_qimage(self.img),'new')
        self.assertTrue(self.w._history_writer.flush(3))
        self.app.processEvents()
        self.assertEqual([desc for _,desc in self.w.history],['new'])
        self.assertEqual([desc for _,desc in self.w._history_store.load()[0]],['new'])

    def test_clear_failure_preserves_old_and_new_history_on_disk(self):
        self.w._add_history(kapture.bgr_to_qimage(self.img),'old')
        self.assertTrue(self.w._history_writer.flush(3))
        with mock.patch.object(self.w._history_store,'clear',return_value=False):
            self.w._clear_history()
            self.w._add_history(kapture.bgr_to_qimage(self.img),'new')
            self.assertTrue(self.w._history_writer.flush(3))
            self.app.processEvents()
            self.assertTrue(self.w._history_writer.flush(3))
        self.assertEqual([desc for _,desc in self.w.history],['new','old'])
        self.assertEqual([desc for _,desc in self.w._history_store.load()[0]],['new','old'])

    def test_capture_commands_do_not_start_during_inline_edit(self):
        edit=self.open_capture()
        self.w._last_phys=(0,0,100,100)
        with mock.patch.object(QtCore.QTimer,'singleShot') as schedule:
            self.w.capture_window()
            self.w.repeat_last()
            self.w.toggle_record()
        self.assertEqual(schedule.call_count,0)
        self.assertIs(self.w._inline_editor,edit)

    def test_inline_long_capture_uses_adjusted_region_without_committing_image(self):
        edit=self.open_capture()
        edit._region=QtCore.QRect(30,40,180,100)
        pending=[]
        with mock.patch.object(QtCore.QTimer,'singleShot',side_effect=lambda delay,fn:pending.append(fn)):
            edit.finish('scroll')
        self.assertIsNone(self.w._inline_editor)
        self.assertEqual(self.w.history,[])
        with mock.patch.object(self.w,'_manual_start') as start:
            pending[-1]()
        self.assertEqual(start.call_args.args[1],QtCore.QRect(30,40,180,100))

    def test_inline_record_uses_selection_without_second_selector(self):
        edit=self.open_capture()
        edit._region=QtCore.QRect(30,40,180,100)
        with mock.patch.object(self.w, '_start_record', return_value=True) as start:
            edit.finish('record')
        self.assertIsNone(self.w._inline_editor)
        self.assertEqual(self.w.history, [])
        start.assert_called_once_with(QtCore.QRect(30, 40, 180, 100))

    def test_cancel_record_setup_restores_inline_selection_and_annotations(self):
        edit = self.open_capture()
        edit._region = QtCore.QRect(30, 40, 180, 100)
        self.draw(edit.canvas)
        with mock.patch.object(kapture.RecordSetupBar, 'exec_', return_value=QtWidgets.QDialog.Rejected):
            edit.finish('record')
        self.assertIs(self.w._inline_editor, edit)
        self.assertTrue(edit.isVisible())
        self.assertEqual(len(edit.canvas.items), 1)
        self.assertIsNone(self.w._recorder)

    def test_save_dialog_releases_overlay_and_cancel_restores_selection(self):
        edit=self.open_capture()
        def cancel(*args):
            self.assertFalse(edit.isVisible())
            self.assertTrue(self.w._unfinished_capture())
            return ('','')
        with mock.patch.object(QtWidgets.QFileDialog,'getSaveFileName',side_effect=cancel):
            edit.finish('save')
        self.assertTrue(edit.isVisible())
        self.assertIs(self.w._inline_editor,edit)

if __name__=='__main__': unittest.main()
