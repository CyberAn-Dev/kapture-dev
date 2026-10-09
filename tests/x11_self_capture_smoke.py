"""Opt-in Xorg check: the main window remains in the frozen self-capture."""
import sys
import tempfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets, QtTest
import kapture


def run():
    app = QtWidgets.QApplication([])
    assert app.platformName() == 'xcb'
    with tempfile.TemporaryDirectory(prefix='kapture-self-capture-') as directory:
        QtCore.QSettings.setPath(QtCore.QSettings.NativeFormat, QtCore.QSettings.UserScope, directory)
        with mock.patch.object(kapture, 'write_desktop_entry'):
            window = kapture.MainWindow()
        window.settings.setValue('capture_keep_main', True)
        window.settings.setValue('auto_ocr', False)
        window.settings.setValue('auto_copy', False)
        window.settings.setValue('snap_windows', False)
        window.settings.setValue('ui_theme', 'vitesse_dark')
        window._apply_style('vitesse_dark', 'theme')
        window.setGeometry(260, 140, 820, 660); window.show(); window.raise_()
        QtTest.QTest.qWait(250)
        target = QtCore.QRect(window.mapToGlobal(QtCore.QPoint(15, 10)), QtCore.QSize(600, 160))
        baseline = kapture.grab_region(target.x(), target.y(), target.width(), target.height())
        try:
            window.start_select('single')
            QtTest.QTest.qWait(300)
            selector = window.selector
            assert window.isVisible() and not window.isMinimized()
            local = target.translated(-selector.geometry().topLeft())
            dpr = selector.dpr
            frozen = selector.bg_img.copy(round(local.x()*dpr), round(local.y()*dpr),
                                          round(local.width()*dpr), round(local.height()*dpr))
            np.testing.assert_array_equal(kapture.qimage_to_bgr(frozen), baseline)
            first = selector.mapFromGlobal(target.topLeft())
            last = selector.mapFromGlobal(target.bottomRight())
            QtTest.QTest.mousePress(selector, QtCore.Qt.LeftButton, pos=first)
            app.sendEvent(selector, QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
                QtCore.QPointF(last), QtCore.Qt.NoButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier))
            QtTest.QTest.mouseRelease(selector, QtCore.Qt.LeftButton, pos=last)
            QtTest.QTest.qWait(250)
            editor = window._inline_editor
            assert editor is not None and editor.isVisible()
            np.testing.assert_array_equal(kapture.qimage_to_bgr(editor.canvas.base), baseline)
            editor.canvas.base.save('/tmp/kapture-self-capture.png')
            print('PASS: main window remains visible during selection; captured toolbar pixels are exact')
        finally:
            if window._inline_editor:
                window._inline_editor.close()
            if getattr(window, 'selector', None):
                window.selector.close()
            window._history_writer.shutdown(); window.tray.hide(); window.close()


if __name__ == '__main__':
    run()
