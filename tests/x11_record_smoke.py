"""Opt-in Xorg recording: generated page only; output stored in a temporary directory."""
import sys,time,tempfile,json,subprocess
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt5 import QtCore,QtWidgets,QtGui,QtTest
import numpy as np
import kapture

def run():
    app=QtWidgets.QApplication([])
    assert app.platformName()=='xcb'
    with tempfile.TemporaryDirectory(prefix='kapture-record-check-') as directory:
        QtCore.QSettings.setPath(QtCore.QSettings.NativeFormat,QtCore.QSettings.UserScope,directory)
        with mock.patch.object(kapture,'write_desktop_entry'):
            window=kapture.MainWindow()
        window.settings.setValue('save_dir',directory);window.settings.setValue('record_gif',True)
        page=QtWidgets.QLabel('Kapture recording test\nMP4 + GIF')
        page.setAlignment(QtCore.Qt.AlignCenter)
        page.setStyleSheet('background:#f4f5f8;color:#20252c;font-size:26px;')
        page.setWindowFlags(QtCore.Qt.FramelessWindowHint|QtCore.Qt.X11BypassWindowManagerHint)
        page.setGeometry(380,250,400,240);page.show();QtTest.QTest.qWait(200)
        baseline=kapture.grab_region(380,250,400,240)
        ticks=[];timer=QtCore.QTimer();timer.setInterval(20);timer.timeout.connect(lambda:ticks.append(1))
        try:
            window._start_record(page.geometry())
            recorder=window._recorder;bar=window._recbar
            assert recorder is not None and window._record_border.isVisible()
            assert 'MP4 + GIF' in bar.lbl.text()
            assert not bar.geometry().intersects(page.geometry())
            QtTest.QTest.qWait(700)
            np.testing.assert_array_equal(kapture.grab_region(380,250,400,240),baseline)
            red=kapture.grab_region(377,270,3,30)
            assert ((red[:,:,2]>180)&(red[:,:,1]<110)).all(), 'Visible red border required'
            results=[];recorder.completed.connect(lambda *args:results.append(args))
            bar.grab().save('/tmp/kapture-record-bar.png')
            timer.start();start=time.monotonic();window._on_record_stop()
            assert time.monotonic()-start<.3,'Stop must not block the GUI'
            deadline=time.monotonic()+20
            while not results and time.monotonic()<deadline:QtTest.QTest.qWait(20)
            assert results and not results[0][1],results
            assert ticks and window._recorder is None and window._record_border is None
            for path in results[0][0].splitlines():
                info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',path]))
                stream=info['streams'][0]
                assert stream['width']>0 and stream['height']>0
                print('PASS',stream['codec_name'],stream['width'],stream['height'])
            video=kapture.cv2.VideoCapture(results[0][0].splitlines()[0]);ok,frame=video.read();video.release()
            assert ok and frame.shape[:2]==(240,400)
            assert np.mean(np.abs(frame.astype(float)-baseline.astype(float)))<8,'Video contains unexpected overlay'
            print('PASS: red frame, no control contamination, responsive MP4/GIF finalization, playable output')
        finally:
            timer.stop()
            if window._recorder:
                window._recorder.export_gif=False;window._on_record_stop()
                QtTest.QTest.qWait(500)
            page.close();window.tray.hide();window.close();window._history_writer.shutdown()

if __name__=='__main__':run()
