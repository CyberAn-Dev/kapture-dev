"""Opt-in Xorg smoke: generated page, shared setup, timed stop and three exports."""
import sys, time, tempfile, json, subprocess
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt5 import QtCore, QtGui, QtWidgets, QtTest
import numpy as np
import kapture


def run():
    app = QtWidgets.QApplication([])
    assert app.platformName() == 'xcb'
    with tempfile.TemporaryDirectory(prefix='kapture-record-check-') as directory:
        QtCore.QSettings.setPath(QtCore.QSettings.NativeFormat, QtCore.QSettings.UserScope, directory)
        with mock.patch.object(kapture, 'write_desktop_entry'):
            window = kapture.MainWindow()
        window.settings.setValue('save_dir', directory)
        window.settings.setValue('ui_theme', 'vitesse_dark')
        window.settings.setValue('ui_accent', 'theme')
        window.settings.setValue('auto_ocr', False)
        window._apply_style('vitesse_dark', 'theme')
        page = QtWidgets.QLabel('Kapture recording test\nMP4 · GIF · MKV')
        page.setAlignment(QtCore.Qt.AlignCenter)
        page.setStyleSheet('background:#f4f5f8;color:#20252c;font-size:26px;')
        page.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.X11BypassWindowManagerHint)
        page.setGeometry(380, 250, 400, 240); page.show(); QtTest.QTest.qWait(200)
        baseline = kapture.grab_region(380, 250, 400, 240)
        ticks = []; paths = []; exported = []
        timer = QtCore.QTimer(); timer.setInterval(20); timer.timeout.connect(lambda: ticks.append(1))

        def setup(dialog):
            dialog.options.fps.setValue(10)
            dialog.options.resolution.setCurrentIndex(dialog.options.resolution.findData('half'))
            dialog.options.countdown.setValue(1)
            dialog.options.duration.setValue(2)
            dialog.show(); app.processEvents()
            dialog.grab().save('/tmp/kapture-record-setup.png'); dialog.hide()
            return QtWidgets.QDialog.Accepted

        def export(dialog):
            dialog.show(); app.processEvents()
            dialog.grab().save('/tmp/kapture-record-export.png')
            for extension in ('mp4', 'gif', 'mkv'):
                result = []
                callback = lambda *args: result.append(args)
                dialog.exporter.completed.connect(callback)
                path = str(Path(directory) / ('export.' + extension))
                dialog.exporter.start(path, extension)
                deadline = time.monotonic() + 15
                while not result and time.monotonic() < deadline:
                    QtTest.QTest.qWait(20)
                assert result and not result[0][1], result
                dialog.exporter.completed.disconnect(callback)
                paths.append(path)
            exported.append(True)
            dialog.hide()
            return QtWidgets.QDialog.Rejected

        try:
            background = QtGui.QImage(1200, 800, QtGui.QImage.Format_RGB32)
            background.fill(QtCore.Qt.darkGray)
            window._capture_rect = page.geometry()
            window._capture_background = (background, QtCore.QRect(0, 0, 1200, 800), 1.)
            window._present_capture(baseline, 'Generated recording test')
            inline = window._inline_editor
            assert inline.action_buttons['record'].isEnabled()
            def cancel_setup():
                dialog = window._record_setup
                assert dialog.isVisible() and not inline.isVisible()
                QtTest.QTest.keyClick(dialog, QtCore.Qt.Key_Escape)
            QtCore.QTimer.singleShot(100, cancel_setup)
            inline.finish('record')
            assert window._inline_editor is inline and inline.isVisible()
            assert window._recorder is None
            with mock.patch.object(kapture.RecordSetupDialog, 'exec_', new=setup), \
                    mock.patch.object(kapture.RecordExportDialog, 'exec_', new=export):
                inline.finish('record')
                assert window._inline_editor is None
                assert window._record_pending and window._recorder is None
                window._recbar.grab().save('/tmp/kapture-record-countdown.png')
                deadline = time.monotonic() + 4
                while window._recorder is None and time.monotonic() < deadline:
                    QtTest.QTest.qWait(20)
                recorder = window._recorder
                assert recorder is not None and window._record_border.isVisible()
                assert '10 fps' in window._recbar.lbl.text()
                assert not window._recbar.geometry().intersects(page.geometry())
                QtTest.QTest.qWait(300)
                np.testing.assert_array_equal(kapture.grab_region(380, 250, 400, 240), baseline)
                red = kapture.grab_region(377, 270, 3, 30)
                assert ((red[:, :, 2] > 180) & (red[:, :, 1] < 110)).all()
                window._recbar.grab().save('/tmp/kapture-record-bar.png')
                timer.start()
                deadline = time.monotonic() + 25
                while not exported and time.monotonic() < deadline:
                    QtTest.QTest.qWait(20)
                assert exported and ticks and window._recorder is None
                assert window._record_border is None and window._record_temp is None
            for path in paths:
                info = json.loads(subprocess.check_output([
                    'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]))
                stream = info['streams'][0]
                assert (stream['width'], stream['height']) == (200, 120), stream
                assert abs(float(info['format']['duration']) - 2) < .3, info
                numerator, denominator = map(int, stream['r_frame_rate'].split('/'))
                assert abs(numerator / denominator - 10) < .1, stream
                subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'null', '-'], check=True)
                print('PASS', stream['codec_name'], '200x120', '10 fps', '2 seconds')
            video = kapture.cv2.VideoCapture(paths[0]); ok, frame = video.read(); video.release()
            expected = kapture.cv2.resize(baseline, (200, 120))
            assert ok and np.mean(np.abs(frame.astype(float) - expected.astype(float))) < 10
            print('PASS: shared setup, countdown, automatic stop, clean frame, three playable exports')
        finally:
            timer.stop()
            if window._recorder:
                window._recorder.proc.kill(); window._recorder.proc.waitForFinished(3000)
            window._on_record_stop()
            page.close(); window.tray.hide(); window.close(); window._history_writer.shutdown()


if __name__ == '__main__':
    run()
