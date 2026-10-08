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
        page.setGeometry(300,220,680,350);page.show();QtTest.QTest.qWait(150)
        try:
            window._mode='single'
            selector=kapture.RegionSelector()
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
            editor.tools.buttons['rect'].click()
            for typ,pt,button,buttons in [
                (QtCore.QEvent.MouseButtonPress,(20,32),QtCore.Qt.LeftButton,QtCore.Qt.LeftButton),
                (QtCore.QEvent.MouseMove,(600,90),QtCore.Qt.NoButton,QtCore.Qt.LeftButton),
                (QtCore.QEvent.MouseButtonRelease,(600,90),QtCore.Qt.LeftButton,QtCore.Qt.NoButton)]:
                app.sendEvent(editor.canvas,QtGui.QMouseEvent(typ,QtCore.QPointF(*pt),button,buttons,QtCore.Qt.NoModifier))
            assert len(editor.canvas.items)==1
            observed=[]
            def type_text():
                dialog=app.activeModalWidget()
                observed.append(QtWidgets.QWidget.keyboardGrabber() is None)
                from Xlib import display, X
                from Xlib.ext import xtest
                connection=display.Display()
                root=connection.screen().root
                top=connection.create_resource_object('window',int(dialog.winId()))
                while top.query_tree().parent.id != root.id:
                    top=top.query_tree().parent
                stack=[child.id for child in root.query_tree().children]
                observed.append(stack.index(top.id)>stack.index(int(editor.winId())))
                key=connection.keysym_to_keycode(ord('a'))
                xtest.fake_input(connection,X.KeyPress,key)
                xtest.fake_input(connection,X.KeyRelease,key);connection.sync()
                QtTest.QTest.qWait(100)
                observed.append(dialog.textValue() == 'a')
                dialog.accept();connection.close()
            QtCore.QTimer.singleShot(80,type_text)
            editor.tools.buttons['text'].click()
            QtTest.QTest.mouseClick(editor.canvas,QtCore.Qt.LeftButton,pos=QtCore.QPoint(100,220))
            assert observed == [True,True,True], 'Text dialog must receive real keys and appear above capture overlay'
            assert len(editor.canvas.items)==2
            editor.grab().save('/tmp/kapture-inline-x11.png')
            editor.finish('editor');QtTest.QTest.qWait(100)
            assert len(window.canvas.items)==2
            window.canvas.undo();assert len(window.canvas.items)==1
            window.canvas.redo();assert len(window.canvas.items)==2
            pin=window._new_pin(window.canvas.render_flattened(),window.canvas.snapshot_document())
            pin.set_editing(True);QtTest.QTest.qWait(100)
            pin.grab().save('/tmp/kapture-pin-x11.png')
            assert len(pin.canvas.items)==2
            pin.canvas.undo();assert len(pin.canvas.items)==1
            pin.close()
            print('PASS: actual X11 selection pixels, inline annotations, modal text keyboard, editor/pin handoff, undo/redo')
        finally:
            if window._inline_editor is not None: window._inline_editor.close()
            selector.close();page.close();window.close();window.tray.hide()
            app.processEvents()
            writer=getattr(window,'_history_writer',None)
            if writer: writer.shutdown()


if __name__=='__main__': run()
