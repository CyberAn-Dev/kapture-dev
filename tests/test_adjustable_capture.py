"""Post-selection resizing must keep frozen pixels and annotation coordinates."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import unittest
import numpy as np
from PyQt5 import QtWidgets, QtCore, QtGui
import kapture

class AdjustableCaptureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        y,x=np.indices((500,700))
        self.pixels=np.stack((x%256,y%256,(x+y)%256),axis=2).astype('uint8')
        self.region=QtCore.QRect(100,100,200,150)
        self.edit=kapture.InlineCaptureEditor(self.pixels[100:250,100:300].copy(),self.region,
            lambda *args:True,background=(kapture.bgr_to_qimage(self.pixels),QtCore.QRect(0,0,700,500),1.0))
        self.app.processEvents()

    def tearDown(self):
        self.edit.close();self.app.processEvents()

    def test_eight_handles_and_original_pixel_geometry(self):
        self.assertEqual(len(self.edit.handles),8)
        self.assertEqual(self.edit.viewport.geometry(),self.region)
        self.assertEqual(self.edit.canvas.scale,1.0)

    def test_expanding_left_edge_uses_frozen_pixels_and_preserves_annotations(self):
        canvas=self.edit.canvas
        before=canvas._content_state()
        canvas.items.append({'type':'rect','a':QtCore.QPointF(20,20),'b':QtCore.QPointF(60,60),
                             'color':QtGui.QColor('red'),'width':3})
        canvas._commit_change(before)
        self.edit._begin_resize('w')
        self.edit._resize_selection(QtCore.QPoint(70,180))
        self.edit._end_resize()
        self.assertEqual(self.edit._region,QtCore.QRect(70,100,230,150))
        np.testing.assert_array_equal(kapture.qimage_to_bgr(canvas.base),self.pixels[100:250,70:300])
        self.assertEqual(canvas.items[0]['a'],QtCore.QPointF(50,20))
        canvas.undo(); self.assertEqual(canvas.items,[])
        self.assertEqual(canvas.base.width(),230)
        canvas.redo();self.assertEqual(canvas.items[0]['a'],QtCore.QPointF(50,20))

    def test_corner_resize_clamps_to_frozen_desktop(self):
        self.edit._begin_resize('nw')
        self.edit._resize_selection(QtCore.QPoint(-30,-20))
        self.edit._end_resize()
        self.assertEqual(self.edit._region.topLeft(),QtCore.QPoint(0,0))
        self.assertEqual(self.edit._region.bottomRight(),self.region.bottomRight())
