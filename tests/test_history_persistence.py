"""Persistence tests for screenshot and clipboard image histories."""

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5 import QtCore, QtGui

from history_store import HistoryWriter, ImageHistoryStore


def _solid_image(color, width=8, height=8):
    image = QtGui.QImage(width, height, QtGui.QImage.Format_RGB32)
    image.fill(color)
    return image


class ImageHistoryStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_restart_restores_newest_first_images_and_descriptions(self):
        screenshots = [
            (_solid_image(QtGui.QColor("blue")), "new capture"),
            (_solid_image(QtGui.QColor("red")), "older capture"),
        ]
        clipboard = [
            _solid_image(QtGui.QColor("green")),
            _solid_image(QtGui.QColor("yellow")),
        ]
        self.assertTrue(ImageHistoryStore(self.root).save_screenshots(screenshots))
        self.assertTrue(ImageHistoryStore(self.root).save_clipboard(clipboard))

        restored_screenshots, restored_clipboard = ImageHistoryStore(self.root).load()

        self.assertEqual([desc for _, desc in restored_screenshots],
                         ["new capture", "older capture"])
        self.assertEqual(restored_screenshots[0][0].pixelColor(0, 0),
                         QtGui.QColor("blue"))
        self.assertEqual(restored_screenshots[1][0].pixelColor(0, 0),
                         QtGui.QColor("red"))
        self.assertEqual([image.pixelColor(0, 0) for image in restored_clipboard],
                         [QtGui.QColor("green"), QtGui.QColor("yellow")])

    def test_screenshot_and_clipboard_histories_are_capped(self):
        screenshots = [
            (_solid_image(QtGui.QColor(index, 0, 0)), str(index))
            for index in range(35)
        ]
        clipboard = [_solid_image(QtGui.QColor(index, 1, 0)) for index in range(12)]
        store = ImageHistoryStore(self.root)

        self.assertTrue(store.save_screenshots(screenshots))
        self.assertTrue(store.save_clipboard(clipboard))
        restored_screenshots, restored_clipboard = ImageHistoryStore(self.root).load()

        self.assertEqual(len(restored_screenshots), 30)
        self.assertEqual([desc for _, desc in restored_screenshots],
                         [str(index) for index in range(30)])
        self.assertEqual(len(restored_clipboard), 10)
        self.assertEqual(restored_clipboard[0].pixelColor(0, 0),
                         QtGui.QColor(0, 1, 0))

    def test_save_reuses_existing_pngs_and_writes_only_new_image(self):
        initial_store = ImageHistoryStore(self.root)
        first = _solid_image(QtGui.QColor("red"))
        second = _solid_image(QtGui.QColor("blue"))
        added = _solid_image(QtGui.QColor("green"))
        self.assertTrue(initial_store.save_screenshots([
            (first, "first"), (second, "second")
        ]))
        store = ImageHistoryStore(self.root)
        loaded, _ = store.load()
        first, second = loaded[0][0], loaded[1][0]

        original_save = QtGui.QImage.save
        saved_images = []

        def count_saves(image, *args, **kwargs):
            saved_images.append(image)
            return original_save(image, *args, **kwargs)

        with mock.patch.object(QtGui.QImage, "save", new=count_saves):
            self.assertTrue(store.save_screenshots([
                (first, "first"), (second, "second"), (added, "added")
            ]))

        self.assertEqual(len(saved_images), 1)
        self.assertIs(saved_images[0], added)
        restored, _ = ImageHistoryStore(self.root).load()
        self.assertEqual([desc for _, desc in restored], ["first", "second", "added"])
        self.assertEqual([image.pixelColor(0, 0) for image, _ in restored], [
            QtGui.QColor("red"), QtGui.QColor("blue"), QtGui.QColor("green")
        ])

    def test_load_skips_a_bad_image_and_keeps_other_records_in_order(self):
        store = ImageHistoryStore(self.root)
        self.assertTrue(store.save_screenshots([
            (_solid_image(QtGui.QColor("red")), "first"),
            (_solid_image(QtGui.QColor("blue")), "last"),
        ]))
        manifest_path = self.root / "screenshots" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.insert(1, {"file": "broken.png", "description": "bad"})
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        loader = ImageHistoryStore(self.root)
        restored, _ = loader.load()

        self.assertEqual([desc for _, desc in restored], ["first", "last"])
        self.assertTrue(loader.errors)

    def test_failed_image_write_keeps_previous_manifest_and_history(self):
        store = ImageHistoryStore(self.root)
        old_history = [(_solid_image(QtGui.QColor("red")), "kept")]
        self.assertTrue(store.save_screenshots(old_history))
        manifest_path = self.root / "screenshots" / "manifest.json"
        old_manifest = manifest_path.read_bytes()

        with mock.patch.object(QtGui.QImage, "save", return_value=False):
            saved = store.save_screenshots([
                (_solid_image(QtGui.QColor("blue")), "replacement")
            ])

        self.assertFalse(saved)
        self.assertTrue(store.errors)
        self.assertEqual(manifest_path.read_bytes(), old_manifest)
        restored, _ = ImageHistoryStore(self.root).load()
        self.assertEqual([(desc, image.pixelColor(0, 0)) for image, desc in restored],
                         [("kept", QtGui.QColor("red"))])

    def test_clear_removes_both_histories(self):
        store = ImageHistoryStore(self.root)
        self.assertTrue(store.save_screenshots([(_solid_image(QtGui.QColor("red")), "x")]))
        self.assertTrue(store.save_clipboard([_solid_image(QtGui.QColor("blue"))]))

        self.assertTrue(store.clear())

        self.assertEqual(ImageHistoryStore(self.root).load(), ([], []))

    def test_history_writer_returns_while_save_blocks_and_coalesces_clipboard(self):
        store = ImageHistoryStore(self.root)
        entered = threading.Event()
        release = threading.Event()
        batches = []
        original_save = store.save_clipboard

        def blocked_save(images):
            batches.append(images)
            if len(batches) == 1:
                entered.set()
                release.wait(5)
            return original_save(images)

        store.save_clipboard = blocked_save
        writer = HistoryWriter(store)
        self.addCleanup(writer.shutdown)
        red = _solid_image(QtGui.QColor("red"))
        blue = _solid_image(QtGui.QColor("blue"))
        green = _solid_image(QtGui.QColor("green"))

        self.assertTrue(writer.submit_clipboard([red]))
        self.assertTrue(entered.wait(1))
        submitted = threading.Event()

        def submit_updates():
            writer.submit_clipboard([blue])
            writer.submit_clipboard([green])
            submitted.set()

        threading.Thread(target=submit_updates, daemon=True).start()
        try:
            self.assertTrue(submitted.wait(1), "submit blocked behind PNG write")
        finally:
            release.set()
        self.assertTrue(writer.flush(timeout=5))

        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[-1][0].pixelColor(0, 0), QtGui.QColor("green"))
        _, restored = ImageHistoryStore(self.root).load()
        self.assertEqual(restored[0].pixelColor(0, 0), QtGui.QColor("green"))

    def test_history_writer_clear_runs_after_active_write_and_flush(self):
        store = ImageHistoryStore(self.root)
        entered = threading.Event()
        release = threading.Event()
        cleared = []
        original_save = store.save_screenshots

        def blocked_save(history):
            entered.set()
            release.wait(5)
            return original_save(history)

        store.save_screenshots = blocked_save
        writer = HistoryWriter(store)
        writer.cleared.connect(cleared.append)
        self.addCleanup(writer.shutdown)

        self.assertTrue(writer.submit_screenshots([
            (_solid_image(QtGui.QColor("red")), "pending")
        ]))
        self.assertTrue(entered.wait(1))
        self.assertTrue(writer.clear("screenshots"))
        self.assertTrue(writer.submit_screenshots([
            (_solid_image(QtGui.QColor("green")), "after clear")
        ]))
        try:
            self.assertFalse(writer.flush(timeout=0.01))
        finally:
            release.set()
        self.assertTrue(writer.flush(timeout=5))
        self.app.processEvents()

        self.assertIn("screenshots", cleared)
        restored = ImageHistoryStore(self.root).load_screenshots()
        self.assertEqual([description for _, description in restored], ["after clear"])
        self.assertEqual(restored[0][0].pixelColor(0, 0), QtGui.QColor("green"))

    def test_history_writer_reports_clear_failure_by_collection(self):
        store = ImageHistoryStore(self.root)
        store.clear = lambda collection=None: False
        writer = HistoryWriter(store)
        failed = []
        errors = []
        writer.clear_failed.connect(failed.append)
        writer.error.connect(errors.append)
        self.addCleanup(writer.shutdown)

        self.assertTrue(writer.clear("clipboard"))
        self.assertTrue(writer.flush(timeout=5))
        self.app.processEvents()

        self.assertEqual(failed, ["clipboard"])
        self.assertTrue(errors)

    def test_history_writer_reports_cleanup_error_after_successful_clear(self):
        store = ImageHistoryStore(self.root)
        self.assertTrue(store.save_screenshots([
            (_solid_image(QtGui.QColor("red")), "old")
        ]))
        manifest_path = self.root / "screenshots" / "manifest.json"
        old_filename = json.loads(manifest_path.read_text(encoding="utf-8"))[0]["file"]
        old_image_path = self.root / "screenshots" / old_filename
        writer = HistoryWriter(store)
        errors = []
        cleared = []
        clear_failed = []
        writer.error.connect(errors.append)
        writer.cleared.connect(cleared.append)
        writer.clear_failed.connect(clear_failed.append)
        self.addCleanup(writer.shutdown)
        original_unlink = Path.unlink

        def fail_old_image(path, *args, **kwargs):
            if path == old_image_path:
                raise OSError("simulated stale image cleanup failure")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", new=fail_old_image):
            self.assertTrue(writer.clear("screenshots"))
            self.assertTrue(writer.flush(timeout=5))
        self.app.processEvents()

        self.assertEqual(cleared, ["screenshots"])
        self.assertEqual(clear_failed, [])
        self.assertTrue(any("simulated stale image cleanup failure" in message
                            for message in errors))
        self.assertTrue(old_image_path.exists())
        self.assertEqual(ImageHistoryStore(self.root).load_screenshots(), [])

    def test_save_respects_pixel_budget_and_keeps_newest_oversize_image(self):
        old_budget = ImageHistoryStore.MAX_TOTAL_PIXELS
        self.addCleanup(setattr, ImageHistoryStore, "MAX_TOTAL_PIXELS", old_budget)
        ImageHistoryStore.MAX_TOTAL_PIXELS = 100
        store = ImageHistoryStore(self.root)
        self.assertTrue(store.save_screenshots([
            (_solid_image(QtGui.QColor("red"), 7, 7), "first fits"),
            (_solid_image(QtGui.QColor("blue"), 8, 8), "skip over budget"),
            (_solid_image(QtGui.QColor("green"), 5, 5), "later fits"),
        ]))
        restored = ImageHistoryStore(self.root).load_screenshots()
        self.assertEqual([description for _, description in restored],
                         ["first fits", "later fits"])

        self.assertTrue(store.save_screenshots([
            (_solid_image(QtGui.QColor("yellow"), 12, 12), "oversize newest"),
            (_solid_image(QtGui.QColor("purple"), 5, 5), "older"),
        ]))
        restored = ImageHistoryStore(self.root).load_screenshots()
        self.assertEqual([description for _, description in restored], ["oversize newest"])

        self.assertTrue(store.save_clipboard([
            _solid_image(QtGui.QColor("cyan"), 8, 8),
            _solid_image(QtGui.QColor("magenta"), 7, 7),
            _solid_image(QtGui.QColor("black"), 5, 5),
        ]))
        clipboard = ImageHistoryStore(self.root).load_clipboard()
        self.assertEqual([image.pixelColor(0, 0) for image in clipboard], [
            QtGui.QColor("cyan"), QtGui.QColor("black")
        ])

    def test_bounded_entries_applies_count_and_pixel_limits_to_memory_lists(self):
        old_budget = ImageHistoryStore.MAX_TOTAL_PIXELS
        self.addCleanup(setattr, ImageHistoryStore, "MAX_TOTAL_PIXELS", old_budget)
        ImageHistoryStore.MAX_TOTAL_PIXELS = 100
        first = _solid_image(QtGui.QColor("red"), 7, 7)
        too_large = _solid_image(QtGui.QColor("blue"), 8, 8)
        later = _solid_image(QtGui.QColor("green"), 5, 5)

        bounded = ImageHistoryStore.bounded_entries("screenshots", [
            (first, "first"), (too_large, "skip"), (later, "later")
        ])

        self.assertEqual([description for _, description in bounded], ["first", "later"])
        self.assertIs(bounded[0][0], first)
        many = [(_solid_image(QtGui.QColor(index, 0, 0), 1, 1), str(index))
                for index in range(35)]
        bounded_count = ImageHistoryStore.bounded_entries("screenshots", many)
        self.assertEqual([description for _, description in bounded_count],
                         [str(index) for index in range(30)])

    def test_load_checks_pixel_budget_before_decoding_each_image(self):
        old_budget = ImageHistoryStore.MAX_TOTAL_PIXELS
        self.addCleanup(setattr, ImageHistoryStore, "MAX_TOTAL_PIXELS", old_budget)
        ImageHistoryStore.MAX_TOTAL_PIXELS = 100
        store = ImageHistoryStore(self.root)
        folder = self.root / "screenshots"
        folder.mkdir(parents=True)
        records = []
        for name, color, size in (
                ("first.png", "red", 7), ("too-large.png", "blue", 8),
                ("later-fits.png", "green", 5)):
            self.assertTrue(_solid_image(QtGui.QColor(color), size, size).save(
                str(folder / name), "PNG"))
            records.append({"file": name, "description": name})
        (folder / "manifest.json").write_text(json.dumps(records), encoding="utf-8")

        original_read = QtGui.QImageReader.read
        read_count = []

        def count_reads(reader, *args, **kwargs):
            read_count.append(reader)
            return original_read(reader, *args, **kwargs)

        with mock.patch.object(QtGui.QImageReader, "read", new=count_reads):
            restored = store.load_screenshots()

        self.assertEqual(len(read_count), 2)
        self.assertEqual([description for _, description in restored],
                         ["first.png", "later-fits.png"])


if __name__ == "__main__":
    unittest.main()
