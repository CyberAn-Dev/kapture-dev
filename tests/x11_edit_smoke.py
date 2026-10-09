"""Opt-in real-X11 capture/edit smoke. Uses a demo window and isolated settings.

QT_QPA_PLATFORM=xcb PYTHONNOUSERSITE=1 .venv/bin/python tests/x11_edit_smoke.py
Screenshots of this test's own widgets are written to /tmp/kapture-*-x11.png.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui, QtTest
import kapture


def run():
    app=QtWidgets.QApplication([])
    assert app.platformName() == 'xcb', 'Requires X11'
    app.setStyle('Fusion')
    with tempfile.TemporaryDirectory(prefix='kapture-edit-smoke-') as config:
        QtCore.QSettings.setPath(QtCore.QSettings.NativeFormat,QtCore.QSettings.UserScope,config)
        with mock.patch.object(kapture,'write_desktop_entry'):
            window=kapture.MainWindow()
        window.tray.hide()
        window.settings.setValue('auto_ocr',False)
        window.settings.setValue('auto_copy',False)
        window.settings.setValue('snap_windows',False)
        pixels=np.full((350,680,3),248,np.uint8)
        kapture.cv2.putText(pixels,'Kapture - capture and edit',(30,70),
                           kapture.cv2.FONT_HERSHEY_SIMPLEX,1,(35,35,40),2)
        kapture.cv2.putText(pixels,'Select a tool. Annotate. Copy.',(30,125),
                           kapture.cv2.FONT_HERSHEY_SIMPLEX,.7,(70,70,90),1)
        page=QtWidgets.QLabel()
        page.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.X11BypassWindowManagerHint)
        page.setPixmap(QtGui.QPixmap.fromImage(kapture.bgr_to_qimage(pixels)))
        page.setGeometry(300,220,680,350);page.show();page.raise_();QtTest.QTest.qWait(300)
        try:
            window._mode='single'
            selector=kapture.RegionSelector()
            window.selector=selector
            selector.selected.connect(window._on_region)
            selector.show();QtTest.QTest.qWait(100)
            QtTest.QTest.mousePress(selector,QtCore.Qt.LeftButton,pos=QtCore.QPoint(300,220))
            # Send a drag with its button state; some Qt platforms omit that in mouseMove.
            app.sendEvent(selector,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
                QtCore.QPointF(979,569),QtCore.Qt.NoButton,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier))
            QtTest.QTest.mouseRelease(selector,QtCore.Qt.LeftButton,pos=QtCore.QPoint(979,569))
            QtTest.QTest.qWait(350)
            editor=window._inline_editor
            assert editor is not None and editor.isVisible()
            np.testing.assert_array_equal(kapture.qimage_to_bgr(editor.canvas.base),pixels)
            assert len(editor.handles)==8
            left=editor.handles['w']
            QtTest.QTest.mousePress(left,QtCore.Qt.LeftButton,pos=left.rect().center())
            global_pos=QtCore.QPoint(280,390)
            app.sendEvent(left,QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
                QtCore.QPointF(left.mapFromGlobal(global_pos)),QtCore.QPointF(global_pos),
                QtCore.Qt.NoButton,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier))
            assert editor._region.left()==280
            assert editor.loupe.isVisible()
            editor.grab().save('/tmp/kapture-adjust-loupe-x11.png')
            QtTest.QTest.mouseRelease(left,QtCore.Qt.LeftButton,pos=left.rect().center())
            assert not editor.loupe.isVisible()
            from Xlib import display, X, XK
            from Xlib.ext import xtest
            button,menu,_=editor.tools._compact_groups['shape']
            button.click();QtTest.QTest.qWait(100)
            assert menu.isVisible()
            menu.setActiveAction(menu.actions()[0])
            connection=display.Display()
            for symbol in (XK.XK_Down,XK.XK_Return):
                key=connection.keysym_to_keycode(symbol)
                xtest.fake_input(connection,X.KeyPress,key)
                xtest.fake_input(connection,X.KeyRelease,key)
                connection.sync();QtTest.QTest.qWait(100)
            connection.close()
            assert editor.canvas.tool=='ellipse', 'Dropdown must receive real X11 menu keys'
            assert not menu.isVisible()
            color_visible=[]
            def choose_color():
                dialog=app.activeModalWidget()
                connection=display.Display()
                root=connection.screen().root
                top=connection.create_resource_object('window',int(dialog.winId()))
                while top.query_tree().parent.id != root.id:
                    top=top.query_tree().parent
                stack=[child.id for child in root.query_tree().children]
                color_visible.append(stack.index(top.id)>stack.index(int(editor.winId())))
                dialog.setCurrentColor(QtGui.QColor('#e02020'));dialog.accept()
                connection.close()
            QtCore.QTimer.singleShot(100,choose_color)
            editor.tools.choose_color()
            assert color_visible==[True], 'Color settings must appear above capture'
            editor.tools.buttons['rect'].click()
            for typ,pt,button,buttons in [
                (QtCore.QEvent.MouseButtonPress,(20,32),QtCore.Qt.LeftButton,QtCore.Qt.LeftButton),
                (QtCore.QEvent.MouseMove,(600,90),QtCore.Qt.NoButton,QtCore.Qt.LeftButton),
                (QtCore.QEvent.MouseButtonRelease,(600,90),QtCore.Qt.LeftButton,QtCore.Qt.NoButton)]:
                app.sendEvent(editor.canvas,QtGui.QMouseEvent(typ,QtCore.QPointF(*pt),button,buttons,QtCore.Qt.NoModifier))
            assert len(editor.canvas.items)==1
            editor.tools.buttons['text'].click()
            QtTest.QTest.mouseClick(editor.canvas,QtCore.Qt.LeftButton,pos=QtCore.QPoint(100,220))
            field=editor.canvas._text_editor
            assert field is not None and field.isVisible()
            assert app.activeModalWidget() is None
            from Xlib import display, X, XK
            from Xlib.ext import xtest
            connection=display.Display()
            def real_key(keysym):
                key=connection.keysym_to_keycode(keysym)
                xtest.fake_input(connection,X.KeyPress,key)
                xtest.fake_input(connection,X.KeyRelease,key)
                connection.sync();QtTest.QTest.qWait(80)
            real_key(ord('a'))
            assert field.text() == 'a', 'Inline input must receive actual X11 keys'
            # Exercise the same native input-method commit used by Chinese IMEs.
            event=QtGui.QInputMethodEvent();event.setCommitString('中文')
            app.sendEvent(field,event)
            assert field.text() == 'a中文'
            real_key(XK.XK_Return)
            connection.close()
            assert editor.isVisible(), 'Enter finishes text, not the capture'
            assert editor.canvas._text_editor is None
            assert editor.canvas.items[-1]['text'] == 'a中文'
            assert len(editor.canvas.items)==2
            editor.grab().save('/tmp/kapture-inline-x11.png')
            editor.grab(editor.viewport.geometry().united(editor.tools.geometry()).adjusted(-7,-7,7,7)).save('/tmp/kapture-toolbar-detail.png')
            editor.finish('editor');QtTest.QTest.qWait(100)
            window._apply_style(theme='vitesse_dark')
            window.text.setPlainText('\n'.join(f'OCR result line {i:03d}' for i in range(180)))
            QtTest.QTest.qWait(80)
            before=window.btn_copy_all.mapToGlobal(QtCore.QPoint())
            window.text.verticalScrollBar().setValue(window.text.verticalScrollBar().maximum())
            QtTest.QTest.qWait(80)
            assert window.btn_copy_all.mapToGlobal(QtCore.QPoint())==before
            window.grab().save('/tmp/kapture-main-x11.png')
            assert len(window.canvas.items)==2
            window.canvas.undo();assert len(window.canvas.items)==1
            window.canvas.redo();assert len(window.canvas.items)==2
            pin=window._new_pin(window.canvas.render_flattened(),window.canvas.snapshot_document())
            pin.set_editing(True);QtTest.QTest.qWait(100)
            assert pin.tools.compact
            pin.grab().save('/tmp/kapture-pin-x11.png')
            assert len(pin.canvas.items)==2
            pin.tools.undo_button.click();assert len(pin.canvas.items)==1
            pin.close()
            print('PASS: actual X11 selection pixels, inline annotations, in-place text and input-method commit, editor/pin handoff, undo/redo')
        finally:
            if window._inline_editor is not None: window._inline_editor.close()
            selector.close();page.close();window.close();window.tray.hide()
            app.processEvents()
            writer=getattr(window,'_history_writer',None)
            if writer: writer.shutdown()


if __name__=='__main__': run()
