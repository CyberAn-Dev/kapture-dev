"""Recording options, asynchronous capture shutdown, and real ffmpeg exports."""
import json
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import shutil
import subprocess
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

from PyQt5 import QtCore, QtTest, QtWidgets

import kapture


FFMPEG = shutil.which('ffmpeg')
FFPROBE = shutil.which('ffprobe')


@unittest.skipUnless(FFMPEG and FFPROBE, 'ffmpeg and ffprobe are required')
class RecordingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.recording_path = self.directory / 'capture.mp4'
        self.recorder = kapture.Recorder(
            (20, 30, 1600, 900), str(self.recording_path), fps=24,
            output_size=(800, 450), duration=17,
        )
        self.exporters = []

    def tearDown(self):
        for exporter in self.exporters:
            self._stop_process(exporter.proc)
            exporter.deleteLater()
        self._stop_process(self.recorder.proc)
        self.recorder._stop_timer.stop()
        self.recorder.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    @staticmethod
    def _stop_process(process):
        if process.state() != QtCore.QProcess.NotRunning:
            process.kill()
            process.waitForFinished(3000)

    def _wait_for_result(self, result, timeout=20):
        deadline = time.monotonic() + timeout
        while not result and time.monotonic() < deadline:
            QtTest.QTest.qWait(20)
        self.assertTrue(result, 'ffmpeg did not report completion before timeout')
        return result[0]

    def _make_synthetic_video(self, path):
        subprocess.run([
            FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=96x64:rate=8', '-t', '1.5', '-an',
            '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p',
            '-r', '8', str(path),
        ], check=True, capture_output=True, text=True, timeout=20)

    def _probe_video(self, path):
        result = subprocess.run([
            FFPROBE, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries',
            'stream=codec_name,width,height,avg_frame_rate,nb_read_frames',
            '-of', 'json', str(path),
        ], check=True, capture_output=True, text=True, timeout=20)
        streams = json.loads(result.stdout)['streams']
        self.assertEqual(len(streams), 1)
        return streams[0]

    def test_options_feed_frame_rate_resolution_and_duration_to_capture_args(self):
        settings = QtCore.QSettings(
            str(self.directory / 'settings.ini'), QtCore.QSettings.IniFormat,
        )
        options = kapture.RecordingOptions(settings, (1600, 900))
        options.fps.setValue(24)
        options.resolution.setCurrentIndex(options.resolution.findData('custom'))
        options.width.setValue(800)
        options.countdown.setValue(5)
        options.duration.setValue(17)

        values = options.values()
        self.assertEqual(values, {
            'fps': 24, 'output_size': (800, 450), 'duration': 17, 'countdown': 5,
        })

        recorder = kapture.Recorder(
            (20, 30, 1600, 900), str(self.recording_path), parent=None,
            fps=values['fps'], output_size=values['output_size'],
            duration=values['duration'],
        )
        args = recorder._record_args()
        self.assertEqual(args[args.index('-framerate') + 1], '24')
        self.assertEqual(args[args.index('-video_size') + 1], '1600x900')
        self.assertEqual(args[args.index('-vf') + 1], 'scale=800:450:flags=lanczos')
        self.assertEqual(args[args.index('-t') + 1], '17')
        recorder.deleteLater()

    def test_stop_does_not_wait_for_ffmpeg(self):
        process = mock.Mock()
        process.state.return_value = QtCore.QProcess.Running
        self.recorder.proc = process
        phases = []
        self.recorder.phase.connect(phases.append)

        self.recorder.stop()

        process.write.assert_called_once_with(b'q')
        process.closeWriteChannel.assert_called_once_with()
        process.waitForFinished.assert_not_called()
        self.assertEqual(phases, ['mp4'])
        self.assertTrue(self.recorder.stopping)
        self.recorder._stop_timer.stop()

    def test_failed_capture_reports_error_without_saved_path(self):
        result = []
        self.recorder.completed.connect(lambda *args: result.append(args))

        self.recorder._record_finished(1, QtCore.QProcess.NormalExit)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], '')
        self.assertTrue(result[0][1])

    def test_real_ffmpeg_exports_mp4_gif_and_mkv_with_expected_streams(self):
        source = self.directory / 'synthetic.mp4'
        self._make_synthetic_video(source)
        self.assertEqual(self._probe_video(source)['width'], 96)

        expected = {'mp4': ('h264', 8), 'gif': ('gif', 4), 'mkv': ('h264', 8)}
        for format_name, (codec, fps) in expected.items():
            destination = self.directory / f'export.{format_name}'
            exporter = kapture.RecordingExporter(str(source), fps=4, duration=1.5)
            self.exporters.append(exporter)
            result = []
            progress = []
            exporter.completed.connect(lambda *args, result=result: result.append(args))
            exporter.progress.connect(progress.append)
            exporter.start(str(destination), format_name)

            saved_path, error = self._wait_for_result(result)
            self.assertEqual(error, '', f'{format_name} export failed: {error}')
            self.assertEqual(saved_path, str(destination))
            self.assertEqual(progress[-1], 100)
            stream = self._probe_video(destination)
            self.assertEqual(stream['codec_name'], codec)
            self.assertEqual((stream['width'], stream['height']), (96, 64))
            self.assertEqual(Fraction(stream['avg_frame_rate']), fps)
            self.assertGreater(int(stream['nb_read_frames']), 0)
            subprocess.run([
                FFMPEG, '-v', 'error', '-i', str(destination), '-f', 'null', '-',
            ], check=True, capture_output=True, text=True, timeout=20)

        self.assertTrue(source.is_file())

    def test_failed_export_preserves_source_and_existing_destination(self):
        source = self.directory / 'raw-capture.mp4'
        source_bytes = b'raw recording bytes kept after export failure'
        source.write_bytes(source_bytes)
        destination = self.directory / 'existing.mp4'
        existing_bytes = b'previous destination must survive'
        destination.write_bytes(existing_bytes)

        exporter = kapture.RecordingExporter(str(source), fps=8, duration=1)
        self.exporters.append(exporter)
        result = []
        exporter.completed.connect(lambda *args: result.append(args))
        exporter.start(str(destination), 'mp4')

        saved_path, error = self._wait_for_result(result)

        self.assertEqual(saved_path, '')
        self.assertTrue(error)
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(destination.read_bytes(), existing_bytes)
        self.assertEqual(list(self.directory.glob('.existing-*')), [])

    def test_record_bar_displays_capture_settings_and_disables_stop_while_finishing(self):
        with mock.patch.object(kapture, 'KeyListener'):
            bar = kapture.RecordBar(
                lambda: None, QtCore.QRect(200, 180, 200, 100), fps=24,
                output_size=(800, 450), duration=17,
            )
        try:
            self.assertIn('24 fps', bar.lbl.text())
            self.assertIn('800 × 450', bar.lbl.text())
            self.assertIn('/ 17s', bar.lbl.text())
            bar.set_phase('mp4')
            bar.set_progress(-1)
            self.assertEqual(bar.progress_bar.maximum(), 0)
            self.assertFalse(bar.btn.isEnabled())
        finally:
            bar.close()


if __name__ == '__main__':
    unittest.main()
