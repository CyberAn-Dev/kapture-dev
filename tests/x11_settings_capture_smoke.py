"""Opt-in Xorg regression: native input must work while Settings is modal."""
import sys, tempfile, traceback
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PyQt5 import QtCore, QtWidgets, QtTest
from Xlib import display, X, XK, protocol
import kapture


def send_mouse(widget, event_type, point, state=0):
    connection = display.Display()
    local = widget.mapFromGlobal(point)
    window = connection.create_resource_object('window', int(widget.winId()))
    fields = dict(time=X.CurrentTime, root=connection.screen().root, window=window,
                  child=X.NONE, same_screen=1, root_x=point.x(), root_y=point.y(),
                  event_x=local.x(), event_y=local.y(), state=state)
    types = {X.ButtonPress: (protocol.event.ButtonPress, X.ButtonPressMask, 1),
             X.MotionNotify: (protocol.event.MotionNotify, X.PointerMotionMask, 0),
             X.ButtonRelease: (protocol.event.ButtonRelease, X.ButtonReleaseMask, 1)}
    event, mask, detail = types[event_type]
    window.send_event(event(detail=detail, **fields), event_mask=mask)
    connection.sync(); connection.close()


def run():
    app = QtWidgets.QApplication([])
    assert app.platformName() == 'xcb'
    with tempfile.TemporaryDirectory(prefix='kapture-settings-capture-') as directory:
        QtCore.QSettings.setPath(QtCore.QSettings.NativeFormat, QtCore.QSettings.UserScope, directory)
        settings = QtCore.QSettings('ScrollShot', 'ScrollShot')
        settings.setValue('auto_ocr', False); settings.setValue('snap_windows', False)
        settings.setValue('ui_theme', 'vitesse_dark'); settings.setValue('ui_accent', 'theme')
        with mock.patch.object(kapture, 'write_desktop_entry'):
            main = kapture.MainWindow()
        main.setGeometry(260, 140, 820, 660); main.show()
        state = {}; errors = []; completed = []

        def guard(callback):
            def call():
                try: callback()
                except Exception:
                    errors.append(traceback.format_exc())
                    if main._inline_editor: main._inline_editor.close()
                    if getattr(main, 'selector', None): main.selector.close()
                    if main._settings_dialog: main._settings_dialog.reject()
            return call

        def begin():
            dialog = main._settings_dialog
            assert dialog is app.activeModalWidget()
            state['dialog'] = dialog
            state['name'] = next(edit for edit in dialog.findChildren(QtWidgets.QLineEdit)
                                 if '{date}' in edit.text())
            state['name'].setText('UNSAVED_{date}_{time}')
            state['checkbox'] = dialog.findChild(QtWidgets.QCheckBox, 'captureKeepMain')
            state['checkbox'].setChecked(True)
            state['checkbox'].setFocus(); app.processEvents()
            assert not settings.value('capture_keep_main', False, type=bool)
            state['region'] = QtCore.QRect(dialog.mapToGlobal(QtCore.QPoint()), dialog.size())
            region = state['region']
            state['pixels'] = kapture.grab_region(region.x(), region.y(), region.width(), region.height())
            np.testing.assert_array_equal(state['pixels'], kapture.qimage_to_bgr(dialog.grab().toImage()),
                                          err_msg='The captured pixels must contain the actual Settings widget')
            main.handle_command('single')
            QtCore.QTimer.singleShot(350, guard(press))

        def press():
            selector = main.selector
            assert selector.parent() is state['dialog']
            assert selector is app.activeModalWidget()
            assert state['dialog'].isVisible() and not main.isMinimized()
            send_mouse(selector, X.ButtonPress, state['region'].topLeft())
            QtCore.QTimer.singleShot(50, guard(move))

        def move():
            assert main.selector.origin is not None, 'Native mouse press was blocked by Settings'
            send_mouse(main.selector, X.MotionNotify, state['region'].bottomRight(), X.Button1Mask)
            QtCore.QTimer.singleShot(50, guard(release))

        def release():
            send_mouse(main.selector, X.ButtonRelease, state['region'].bottomRight(), X.Button1Mask)
            QtCore.QTimer.singleShot(250, guard(copy))

        def copy():
            editor = main._inline_editor
            assert editor is not None and editor is app.activeModalWidget()
            assert editor.parent() is state['dialog']
            np.testing.assert_array_equal(kapture.qimage_to_bgr(editor.canvas.base), state['pixels'])
            editor.canvas.base.save('/tmp/kapture-settings-self-capture.png')
            button = editor.action_buttons['copy']
            point = button.mapToGlobal(button.rect().center())
            send_mouse(editor, X.ButtonPress, point)
            send_mouse(editor, X.ButtonRelease, point, X.Button1Mask)
            QtCore.QTimer.singleShot(100, guard(check))

        def check():
            assert main._inline_editor is None, 'Native copy click was blocked'
            dialog = state['dialog']
            assert dialog.isVisible() and dialog is app.activeModalWidget()
            assert state['name'].text() == 'UNSAVED_{date}_{time}'
            assert state['checkbox'].isChecked()
            assert not settings.value('capture_keep_main', False, type=bool)
            np.testing.assert_array_equal(kapture.qimage_to_bgr(app.clipboard().image()), state['pixels'])
            main.handle_command('single')
            QtCore.QTimer.singleShot(350, guard(cancel_capture))

        def cancel_capture():
            selector = main.selector
            assert selector is app.activeModalWidget()
            connection = display.Display()
            window = connection.create_resource_object('window', int(selector.winId()))
            key = connection.keysym_to_keycode(XK.string_to_keysym('Escape'))
            window.send_event(protocol.event.KeyPress(time=X.CurrentTime, root=connection.screen().root,
                window=window, child=X.NONE, same_screen=1, root_x=0, root_y=0,
                event_x=0, event_y=0, state=0, detail=key), event_mask=X.KeyPressMask)
            connection.sync(); connection.close()
            QtCore.QTimer.singleShot(100, guard(check_cancel))

        def check_cancel():
            assert not main.selector.isVisible()
            assert main._inline_editor is None
            assert state['dialog'] is app.activeModalWidget()
            assert state['name'].text() == 'UNSAVED_{date}_{time}'
            completed.append(True); state['dialog'].reject()

        def timeout():
            if not completed: raise AssertionError('Settings capture did not finish within 8 seconds')
        QtCore.QTimer.singleShot(300, guard(begin))
        QtCore.QTimer.singleShot(8000, guard(timeout))
        try:
            with mock.patch.object(kapture, 'shortcut_backend', return_value=None):
                main.show_settings()
            assert not errors, '\n'.join(errors)
            assert completed and main._settings_dialog is None
            assert not settings.value('capture_keep_main', False, type=bool)
            assert settings.value('name_tmpl', 'Kapture_{date}_{time}') == 'Kapture_{date}_{time}'
            print('PASS: native X11 selection/copy/Esc, exact Settings pixels, unsaved changes preserved and Cancel respected')
        finally:
            main._history_writer.shutdown(); main.tray.hide(); main.close()


if __name__ == '__main__':
    run()
