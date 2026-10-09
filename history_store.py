"""Small persistent store for Kapture's recent image histories."""

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt5 import QtCore, QtGui


class ImageHistoryStore:
    """Store screenshot and system-clipboard QImage history under one root.

    ``load`` returns ``(screenshots, clipboard_images)``. Screenshot entries
    are ``(QImage, description)`` pairs; both collections are newest first.
    Save and clear methods return a success boolean and append failures to
    ``errors`` so the caller can report them without losing the in-memory list.
    """

    LIMITS = {"screenshots": 10, "clipboard": 10}
    MAX_TOTAL_PIXELS = 40_000_000

    def __init__(self, root):
        self.root = Path(root)
        self.errors = []
        self._cache = {name: [] for name in self.LIMITS}

    def load(self):
        return self.load_screenshots(), self.load_clipboard()

    def load_screenshots(self):
        return self._load_collection("screenshots")

    def load_clipboard(self):
        return self._load_collection("clipboard")

    def save_screenshots(self, history):
        return self._save_collection("screenshots", history)

    def save_clipboard(self, images):
        return self._save_collection("clipboard", images)

    def clear(self, collection=None):
        """Clear one collection or both; collection is screenshots or clipboard."""
        collections = list(self.LIMITS) if collection is None else [collection]
        if any(name not in self.LIMITS for name in collections):
            self._report(f"Unknown history collection: {collection!r}")
            return False
        succeeded = True
        for name in collections:
            if not self._save_collection(name, []):
                succeeded = False
        return succeeded

    @classmethod
    def bounded_entries(cls, collection, entries):
        """Return newest-first entries within count and total-pixel limits."""
        if collection not in cls.LIMITS:
            raise ValueError(f"Unknown history collection: {collection!r}")
        selected = []
        total_pixels = 0
        for entry in list(entries)[:cls.LIMITS[collection]]:
            image = entry[0] if collection == "screenshots" else entry
            if image.isNull():
                raise ValueError(f"Cannot keep a null {collection} image")
            pixels = image.width() * image.height()
            if not selected or total_pixels + pixels <= cls.MAX_TOTAL_PIXELS:
                selected.append(entry)
                total_pixels += pixels
        return selected

    def _folder(self, collection):
        return self.root / collection

    def _manifest_path(self, collection):
        return self._folder(collection) / "manifest.json"

    def _load_collection(self, collection):
        manifest_path = self._manifest_path(collection)
        try:
            with manifest_path.open("r", encoding="utf-8") as manifest_file:
                records = json.load(manifest_file)
        except FileNotFoundError:
            self._cache[collection] = []
            return []
        except (OSError, ValueError) as exc:
            self._report(f"Could not read {collection} history manifest: {exc}")
            return self._cached_values(collection)

        if not isinstance(records, list):
            self._report(f"Invalid {collection} history manifest")
            return self._cached_values(collection)

        loaded = []
        total_pixels = 0
        for record in records[:self.LIMITS[collection]]:
            if not isinstance(record, dict) or not isinstance(record.get("file"), str):
                self._report(f"Skipped invalid {collection} history entry")
                continue
            image_path = str(self._folder(collection) / record["file"])
            reader = QtGui.QImageReader(image_path)
            size = reader.size()
            width, height = size.width(), size.height()
            if width <= 0 or height <= 0:
                self._report(f"Skipped unreadable {collection} image: {record['file']}")
                continue
            pixels = width * height
            if loaded and total_pixels + pixels > self.MAX_TOTAL_PIXELS:
                continue
            image = reader.read()
            if image.isNull():
                self._report(f"Skipped unreadable {collection} image: {record['file']}")
                continue
            if collection == "screenshots":
                captured_at = record.get("captured_at") or image.text("captured_at")
                source = record.get("timestamp_source") or image.text("timestamp_source")
                if not captured_at:
                    try:
                        captured_at = QtCore.QDateTime.fromSecsSinceEpoch(
                            int(Path(image_path).stat().st_mtime)).toString(QtCore.Qt.ISODate)
                        source = "file"
                    except OSError:
                        captured_at = ""
                image.setText("captured_at", str(captured_at))
                image.setText("timestamp_source", str(source or "capture"))
            loaded.append({
                "image": image,
                "file": record["file"],
                "description": str(record.get("description", "")),
                "cache_key": image.cacheKey(),
            })
            total_pixels += pixels
        self._cache[collection] = loaded
        values = self._cached_values(collection)
        if len(records) > self.LIMITS[collection]:
            self._save_collection(collection, values)
        return values

    def _save_collection(self, collection, entries):
        folder = self._folder(collection)
        staged_images = []
        temporary_paths = []
        try:
            folder.mkdir(parents=True, exist_ok=True)
            previous_files = self._referenced_files(collection)
            entries = self.bounded_entries(collection, entries)
            records = []
            new_cache = []
            for entry in entries:
                if collection == "screenshots":
                    image, description = entry
                else:
                    image, description = entry, None
                if image.isNull():
                    raise OSError(f"Cannot save a null {collection} image")

                cached = self._find_cached_image(collection, image)
                if cached is None:
                    filename = f"{uuid.uuid4().hex}.png"
                    image_path = folder / filename
                    image_tmp = folder / f".{filename}.tmp"
                    temporary_paths.append(image_tmp)
                    if not image.save(str(image_tmp), "PNG"):
                        raise OSError(f"Could not save {collection} image")
                    os.replace(image_tmp, image_path)
                    staged_images.append(image_path)
                else:
                    filename = cached["file"]

                record = {"file": filename}
                if collection == "screenshots":
                    record["description"] = str(description)
                    record["captured_at"] = image.text("captured_at")
                    record["timestamp_source"] = image.text("timestamp_source")
                records.append(record)
                new_cache.append({
                    "image": image,
                    "file": filename,
                    "description": str(description) if collection == "screenshots" else "",
                    "cache_key": image.cacheKey(),
                })

            manifest_tmp = folder / f".manifest-{uuid.uuid4().hex}.tmp"
            temporary_paths.append(manifest_tmp)
            with manifest_tmp.open("w", encoding="utf-8") as manifest_file:
                json.dump(records, manifest_file, ensure_ascii=False)
                manifest_file.flush()
                os.fsync(manifest_file.fileno())
            os.replace(manifest_tmp, self._manifest_path(collection))
        except (OSError, TypeError, ValueError, AttributeError) as exc:
            self._report(f"Could not save {collection} history: {exc}")
            for path in temporary_paths + staged_images:
                try:
                    path.unlink(missing_ok=True)
                except OSError as cleanup_exc:
                    self._report(f"Could not remove temporary history file: {cleanup_exc}")
            return False

        self._cache[collection] = new_cache
        retained_files = {record["file"] for record in records}
        for filename in previous_files - retained_files:
            try:
                (folder / filename).unlink(missing_ok=True)
            except OSError as exc:
                self._report(f"Could not remove old {collection} image {filename}: {exc}")
        return True

    def _find_cached_image(self, collection, image):
        cache_key = image.cacheKey()
        for record in self._cache[collection]:
            if record["cache_key"] == cache_key:
                return record
        return None

    def _cached_values(self, collection):
        if collection == "screenshots":
            return [(record["image"], record["description"])
                    for record in self._cache[collection]]
        return [record["image"] for record in self._cache[collection]]

    def _referenced_files(self, collection):
        try:
            with self._manifest_path(collection).open("r", encoding="utf-8") as manifest_file:
                records = json.load(manifest_file)
        except FileNotFoundError:
            return set()
        except (OSError, ValueError) as exc:
            self._report(f"Could not read old {collection} history manifest: {exc}")
            return set()
        if not isinstance(records, list):
            return set()
        return {
            record["file"] for record in records
            if isinstance(record, dict) and isinstance(record.get("file"), str)
        }

    def _report(self, message):
        self.errors.append(message)


class HistoryWriter(QtCore.QObject):
    """Serialize history writes while keeping only the newest pending snapshot."""

    finished = QtCore.pyqtSignal(str)
    cleared = QtCore.pyqtSignal(str)
    clear_failed = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)

    _COLLECTIONS = ("screenshots", "clipboard")

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._condition = threading.Condition()
        self._pending = {
            name: {"clear": False, "snapshot": None}
            for name in self._COLLECTIONS
        }
        self._running = False
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-writer")

    def submit_screenshots(self, snapshot):
        try:
            copied = [(QtGui.QImage(image), str(description))
                      for image, description in list(snapshot)]
        except Exception as exc:
            self.error.emit(f"Could not queue screenshot history: {exc}")
            return False
        return self._submit("screenshots", copied)

    def submit_clipboard(self, snapshot):
        try:
            copied = [QtGui.QImage(image) for image in list(snapshot)]
        except Exception as exc:
            self.error.emit(f"Could not queue clipboard history: {exc}")
            return False
        return self._submit("clipboard", copied)

    def clear(self, collection=None):
        collections = list(self._COLLECTIONS) if collection is None else [collection]
        if any(name not in self._COLLECTIONS for name in collections):
            self.error.emit(f"Unknown history collection: {collection!r}")
            return False
        with self._condition:
            if self._closed:
                self.error.emit("History writer is shut down")
                return False
            for name in collections:
                self._pending[name]["clear"] = True
                self._pending[name]["snapshot"] = None
            self._schedule_locked()
        return True

    def flush(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._running or self._has_pending_locked():
                if not self._running:
                    self._schedule_locked()
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def shutdown(self, wait=True):
        with self._condition:
            self._closed = True
            if self._has_pending_locked() and not self._running:
                self._schedule_locked()
        if wait:
            self.flush()
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _submit(self, collection, snapshot):
        with self._condition:
            if self._closed:
                self.error.emit("History writer is shut down")
                return False
            self._pending[collection]["snapshot"] = snapshot
            self._schedule_locked()
        return True

    def _has_pending_locked(self):
        return any(item["clear"] or item["snapshot"] is not None
                   for item in self._pending.values())

    def _schedule_locked(self):
        if not self._running:
            self._running = True
            try:
                self._executor.submit(self._drain)
            except RuntimeError as exc:
                self._running = False
                self.error.emit(f"Could not start history writer: {exc}")
                self._condition.notify_all()

    def _next_job_locked(self):
        for collection in self._COLLECTIONS:
            pending = self._pending[collection]
            if pending["clear"]:
                pending["clear"] = False
                return "clear", collection, None
            if pending["snapshot"] is not None:
                snapshot = pending["snapshot"]
                pending["snapshot"] = None
                return "save", collection, snapshot
        return None

    def _drain(self):
        while True:
            with self._condition:
                job = self._next_job_locked()
                if job is None:
                    self._running = False
                    self._condition.notify_all()
                    return
            self._run_job(*job)

    def _run_job(self, operation, collection, snapshot):
        error_count = len(self.store.errors)
        try:
            if operation == "clear":
                succeeded = self.store.clear(collection)
            elif collection == "screenshots":
                succeeded = self.store.save_screenshots(snapshot)
            else:
                succeeded = self.store.save_clipboard(snapshot)
        except Exception as exc:
            if operation == "clear":
                self.clear_failed.emit(collection)
            self.error.emit(str(exc))
            return

        if succeeded:
            if operation == "clear":
                self.cleared.emit(collection)
            else:
                self.finished.emit(collection)
            for message in self.store.errors[error_count:]:
                self.error.emit(message)
            return

        messages = self.store.errors[error_count:]
        if operation == "clear":
            self.clear_failed.emit(collection)
        if messages:
            for message in messages:
                self.error.emit(message)
        else:
            self.error.emit(f"Could not {operation} {collection} history")
