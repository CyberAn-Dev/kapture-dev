"""Recording output must be finalized asynchronously and failures surfaced."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path
from PyQt5 import QtCore,QtWidgets,QtTest
import kapture

class RecordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.rec=kapture.Recorder((0,0,120,80),str(Path(self.tmp.name)/'clip.mp4'),export_gif=True)

    def tearDown(self):
        for process in (self.rec.proc,self.rec.converter):
            if isinstance(process,QtCore.QProcess) and process.state()!=QtCore.QProcess.NotRunning:
                process.kill();process.waitForFinished(3000)
        self.rec.deleteLater();self.app.processEvents();self.tmp.cleanup()

    def test_stop_does_not_wait_for_ffmpeg_and_is_idempotent(self):
        original=self.rec.proc
        fake=mock.Mock()
        fake.state.return_value=QtCore.QProcess.Running
        self.rec.proc=fake
        phases=[];self.rec.phase.connect(phases.append)
        self.rec.stop();self.rec.stop()
        fake.write.assert_called_once_with(b'q')
        fake.waitForFinished.assert_not_called()
        self.assertEqual(phases,['mp4'])
        self.rec._stop_timer.stop();self.rec.proc=original

    def test_failed_recording_never_reports_saved(self):
        result=[];self.rec.completed.connect(lambda *args:result.append(args))
        self.rec._record_finished(1,QtCore.QProcess.NormalExit)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0][0],'');self.assertTrue(result[0][1])

    def test_gif_failure_preserves_mp4_and_reports_error(self):
        result=[];self.rec.completed.connect(lambda *args:result.append(args))
        self.rec.gif_path=str(Path(self.tmp.name)/'clip.gif')
        self.rec._gif_finished(1,QtCore.QProcess.NormalExit)
        self.assertEqual(result[0][0],self.rec.out_path)
        self.assertTrue(result[0][1])

    def test_real_ffmpeg_mp4_and_gif_finish_with_progress_and_live_event_loop(self):
        args=['-y','-loglevel','error','-progress','pipe:1','-nostats','-f','lavfi',
              '-i','testsrc2=size=120x80:rate=10','-t','0.8','-c:v','libx264',
              '-threads','1','-pix_fmt','yuv420p',self.rec.out_path]
        result=[];progress=[];phases=[];ticks=[]
        timer=QtCore.QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        self.rec.completed.connect(lambda *args:result.append(args))
        self.rec.progress.connect(progress.append);self.rec.phase.connect(phases.append)
        with mock.patch.object(self.rec,'_record_args',return_value=args):
            self.assertTrue(self.rec.start())
        deadline=time.monotonic()+15
        while not result and time.monotonic()<deadline:QtTest.QTest.qWait(20)
        timer.stop()
        self.assertTrue(result,'ffmpeg timed out')
        self.assertEqual(result[0][1],'')
        self.assertEqual(len(result[0][0].splitlines()),2)
        self.assertTrue(Path(self.rec.out_path).stat().st_size>0)
        self.assertTrue(Path(self.rec.gif_path).stat().st_size>0)
        self.assertIn('gif',phases);self.assertEqual(progress[-1],100)
        self.assertTrue(ticks)

    def test_record_bar_names_format_and_stays_outside_region_while_saving(self):
        with mock.patch.object(kapture,'KeyListener'):
            bar=kapture.RecordBar(lambda:None,QtCore.QRect(200,180,200,100),True)
        try:
            self.assertIn('MP4 + GIF',bar.lbl.text())
            bar.show_on_top();bar.set_phase('mp4');bar.set_progress(-1)
            self.assertFalse(bar.geometry().intersects(bar._region))
            self.assertEqual(bar.progress_bar.maximum(),0)
            self.assertFalse(bar.btn.isEnabled())
            bar.set_phase('gif');bar.set_progress(45)
            self.assertEqual(bar.progress_bar.value(),45)
        finally:bar.close()
