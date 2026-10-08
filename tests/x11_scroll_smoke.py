"""Opt-in compositor/scroll check: QT_QPA_PLATFORM=xcb .venv/bin/python tests/x11_scroll_smoke.py.

Opens a temporary test page on the desktop; no clipboard/settings changes.
Checks real framebuffer pixels, wheel delivery, stable chrome and HUD stop.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtTest import QTest
import kapture


class Page(QtWidgets.QWidget):
    def __init__(self, pixels):
        super().__init__()
        self.image = kapture.bgr_to_qimage(pixels)
        self.top = 0
        self.header = self.footer = 0
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.X11BypassWindowManagerHint)
        self.setGeometry(350, 200, 1000, 750)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtCore.Qt.white)
        p.fillRect(100, 100, 500, self.header, QtGui.QColor(210, 210, 210))
        p.drawImage(QtCore.QPoint(100, 100 + self.header),
                    self.image.copy(0, self.top, 500, 400 - self.header - self.footer))
        p.fillRect(100, 500 - self.footer, 500, self.footer, QtGui.QColor(180, 180, 180))

    def wheelEvent(self, event):
        self.top = max(0, min(600, self.top - (100 if event.angleDelta().y() > 0 else -100)))
        self.update()


class Visibility(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.hides = 0

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Hide:
            self.hides += 1
        return False


def run():
    app = QtWidgets.QApplication([])
    assert app.platformName() == 'xcb', 'Requires a real X11 compositor'
    pixels = np.full((1000, 500, 3), 255, np.uint8)
    for y in range(0, 1000, 25):
        kapture.cv2.putText(pixels, f'Row {y//25:03d} abcdef 0123456789', (15, y+18),
                           kapture.cv2.FONT_HERSHEY_SIMPLEX, .5, (30, 30, 30), 1)
    page = Page(pixels)
    page.show(); page.raise_(); QTest.qWait(400)
    region = QtCore.QRect(450, 300, 500, 400)
    grab = lambda: kapture.grab_region(region.x(), region.y(), region.width(), region.height())
    baseline = grab()
    overlay = kapture.ScrollRegionOverlay(region)
    hud = kapture.ScrollHud(region, lambda: None)
    try:
        hud.show_on_top(); QTest.qWait(400)
        np.testing.assert_array_equal(grab(), baseline, err_msg='Capture chrome casts a shadow into the region')
        np.testing.assert_array_equal(baseline, pixels[:400])
        visibility = Visibility()
        for w in overlay._wins + [hud]:
            w.installEventFilter(visibility)
        cases = [(manual, direction, header, footer)
                 for header, footer in [(0, 0), (40, 8), (4, 4)]
                 for manual, direction in [(False, 1), (False, -1), (True, 1)]]
        for manual, direction, header, footer in cases:
            page.header, page.footer = header, footer
            page.top = 200 if manual else (0 if direction == 1 else 600)
            page.update(); QTest.qWait(150)
            worker = kapture.CaptureWorker((450, 300, 500, 400), scroll_clicks=1,
                                           max_iters=6, manual=manual, direction=direction)
            result, frames = [], []
            steps = iter([400, 200, 0, 200, 400, 600])
            def on_frame(payload):
                hud.set_image(payload)
                frames.append(payload[1])
                if manual:
                    top = next(steps, None)
                    if top is None:
                        QTest.mouseClick(hud.btn, QtCore.Qt.LeftButton)
                    else:
                        page.top = top
                        page.update()
            hud.btn.clicked.connect(worker.abort)
            worker.frame.connect(on_frame)
            worker.finished_img.connect(result.append)
            worker.start()
            for _ in range(1000):
                QTest.qWait(10)
                if not worker.isRunning():
                    break
            if worker.isRunning():
                worker.abort(); worker.wait(5000)
                raise AssertionError('Worker did not finish within 10 seconds')
            app.processEvents()
            hud.btn.clicked.disconnect(worker.abort)
            assert result and result[0] is not None
            expected = np.concatenate((np.full((header, 500, 3), 210, np.uint8),
                                       pixels[:1000-header-footer],
                                       np.full((footer, 500, 3), 180, np.uint8)))
            np.testing.assert_array_equal(result[0], expected)
            assert visibility.hides == 0, 'Chrome blinked during capture'
            print(f'manual={manual} direction={direction} fixed={header}/{footer}: {len(frames)} frames, '
                  'exact 1000px image, zero chrome hides', flush=True)
    finally:
        overlay.close(); hud.close(); page.close()


if __name__ == '__main__':
    run()
