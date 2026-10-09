#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kapture -- screenshot / OCR / recording tool for X11 (KDE).

Features:
  - Region / window / auto-scroll / manual-scroll capture
  - Annotate, blur, pin to screen, beautify export
  - OCR (Tesseract), screen recording (ffmpeg)
  - Bilingual UI (English / Chinese) via the TR table

Dependencies (Python, installed in venv): PyQt5, mss, opencv-python-headless, numpy, pillow, pynput, pytesseract
Dependencies (system, install via apt): tesseract-ocr (+ language packs), ffmpeg
"""

import sys
import time
import threading

import cv2
import numpy as np
from PIL import Image

import mss
from pynput.mouse import Controller as MouseController
from pynput.keyboard import Listener as KeyListener, Key
from Xlib.error import ConnectionClosedError

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QRect, QThread, pyqtSignal
from history_store import ImageHistoryStore, HistoryWriter


# --------------------------------------------------------------------------- #
# Screenshot / stitching core logic
# --------------------------------------------------------------------------- #
def grab_region(left, top, width, height):
    """Grab a screen region with mss, returning a BGR numpy array."""
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
        arr = np.array(shot)            # BGRA
    return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)


def bgr_to_qimage(bgr):
    """BGR numpy -> QImage (copied, detached from the numpy buffer)."""
    from PyQt5 import QtGui as _G
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return _G.QImage(rgb.data, w, h, 3 * w, _G.QImage.Format_RGB888).copy()


ACCENT = "#6c5ce7"          # indigo/purple accent color

THEMES = {
    "dark": dict(window="#1b1b20", panel="#23232b", field="#2a2a31",
                 editor="#222228", edge="#3a3a44", text="#e6e6ea",
                 muted="#c9c9d0", dim="#a2a2ad", hover="#34343e",
                 pressed="#44444f", accent=ACCENT, on_accent="#ffffff",
                 icon="#d2d2da"),
    "light": dict(window="#f5f5f7", panel="#ffffff", field="#ffffff",
                  editor="#ffffff", edge="#d5d5dc", text="#24242a",
                  muted="#4b4b56", dim="#686875", hover="#e8e8ed",
                  pressed="#dcdce3", accent="#007aff", on_accent="#ffffff",
                  icon="#34343c"),
    "starship": dict(window="#101827", panel="#172236", field="#1e3049",
                     editor="#152137", edge="#344966", text="#f0f4ff",
                     muted="#c6d1e3", dim="#a3b1ca", hover="#29415e",
                     pressed="#355476", accent="#3b82f6", on_accent="#ffffff",
                     icon="#dce8fa"),
    "one_dark_pro_darker": dict(
        window="#1e2227", panel="#23272e", field="#2c313c",
        editor="#23272e", edge="#3e4452", text="#d7dae0",
        muted="#abb2bf", dim="#9da5b4", hover="#323842",
        pressed="#404754", accent="#4d78cc", on_accent="#f8fafd",
        icon="#d7dae0"),
    "vitesse_dark": dict(
        window="#121212", panel="#181818", field="#181818",
        editor="#121212", edge="#2f363d", text="#dbd7ca",
        muted="#bfbaaa", dim="#959da5", hover="#242424",
        pressed="#2f363d", accent="#4d9375", on_accent="#121212",
        icon="#dbd7ca"),
}


def system_prefers_dark():
    """Use GNOME's explicit preference when available, otherwise the Qt palette."""
    import os
    import subprocess
    if "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        try:
            value = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=1, check=True).stdout.strip()
            if value == "'prefer-dark'":
                return True
            if value in ("'default'", "'prefer-light'"):
                gtk_theme = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                    capture_output=True, text=True, timeout=1, check=True).stdout.strip()
                return value != "'prefer-light'" and "dark" in gtk_theme.lower()
        except (OSError, subprocess.SubprocessError):
            pass
    app = QtWidgets.QApplication.instance()
    return bool(app and app.palette().color(QtGui.QPalette.Window).lightness() < 128)

# --------------------------------------------------------------------------- #
# Lightweight i18n
# --------------------------------------------------------------------------- #
_LANG = "zh"


class NativeTextTranslator(QtCore.QTranslator):
    """Translate Qt's built-in edit actions using the selected app language."""
    labels = {
        'Undo':'撤销','Redo':'重做','Cut':'剪切','Copy':'复制','Paste':'粘贴',
        'Delete':'删除','Select All':'全选','Select all':'全选',
        'Clear':'清空','Step up':'增加','Step down':'减少',
        'OK':'确定','Cancel':'取消','Close':'关闭','Save':'保存','Open':'打开','Discard':'放弃',
        'Select Color':'选择颜色','Basic colors':'基本颜色','Custom colors':'自定义颜色',
        'Add to Custom Colors':'添加到自定义颜色','Pick Screen Color':'选取屏幕颜色',
        'Hue:':'色相：','Sat:':'饱和度：','Val:':'明度：','Red:':'红：','Green:':'绿：',
        'Blue:':'蓝：','Alpha channel:':'透明度：','HTML:':'颜色值：',
    }

    def isEmpty(self):
        return False

    def translate(self, context, source, disambiguation=None, n=-1):
        if _LANG != 'zh':
            return None
        label,separator,shortcut=source.partition('\t')
        translated=self.labels.get(label.replace('&',''))
        return translated+separator+shortcut if translated is not None else None


def set_lang(code):
    global _LANG
    _LANG = code if code in ("zh", "en") else "zh"
    app=QtWidgets.QApplication.instance()
    if app is not None and not hasattr(app,'_kapture_translator'):
        app._kapture_translator=NativeTextTranslator(app)
        app.installTranslator(app._kapture_translator)


def t(key):
    e = TR.get(key)
    if not e:
        return key
    return e.get(_LANG) or e.get("zh") or key


TR = {
    "history_clearing": {"zh":"正在清空历史…", "en":"Clearing history…"},
    "history_cleared": {"zh":"历史已清空", "en":"History cleared"},
    "pin_edit_hint": {"zh":"选择可移动标注；右键取词 / 保存，Esc 关闭钉图", "en":"Select to move; right-click for text / save; Esc closes pin"},
    "finish_capture_first": {"zh":"请先完成或取消当前截图", "en":"Finish or cancel the current capture first"},
    "a_select": {"zh":"选择 / 移动标注（Delete 删除，双击改文字）", "en":"Select / move (Delete removes, double-click edits text)"},
    "a_redo": {"zh":"重做", "en":"Redo"},
    "edit_hint": {"zh":"选择工具可移动标注；Enter 复制，Esc 取消", "en":"Select to move annotations; Enter copies, Esc cancels"},
    "select_words_hint": {"zh":"拖选文字即可复制", "en":"Drag across words to copy"},
    "open_editor": {"zh":"在编辑器打开", "en":"Open in editor"},
    "pin_edit": {"zh":"标注 / 编辑", "en":"Annotate / edit"},
    "pin_select_text": {"zh":"选取文字", "en":"Select text"},
    "finish_edit": {"zh":"完成标注", "en":"Finish editing"},
    "save_failed": {"zh":"保存失败，请选择可写入的路径", "en":"Save failed; choose a writable path"},
    "set_capture_keep_main": {"zh": "截图时保留主界面显示（可截取本工具）",
                              "en": "Keep the main window visible during screenshots"},
    "set_inline": {"zh":"截图后原位编辑（未选择直接打开编辑器时）", "en":"Edit in place after capture (unless opening the editor)"},
    "clear_history": {"zh":"清空截图与剪贴板图片历史", "en":"Clear screenshot and clipboard image history"},

    "app_title": {"zh": "Kapture", "en": "Kapture"},
    "app_name": {"zh": "Kapture", "en": "Kapture"},
    "app_generic": {"zh": "截图 / OCR / 录屏", "en": "Screenshot / OCR / Recording"},
    "app_comment": {"zh": "滚动截图、OCR 文字识别、标注与录屏",
                    "en": "Scrolling screenshot, OCR, annotation and recording"},
    # Top bar
    "cap_region": {"zh": "区域截图", "en": "Region capture"},
    "cap_window": {"zh": "窗口截图", "en": "Window capture"},
    "cap_scroll": {"zh": "自动滚动长截图", "en": "Auto scrolling capture"},
    "cap_manual": {"zh": "手动滚动长截图", "en": "Manual scrolling capture"},
    "cap_record": {"zh": "录屏", "en": "Record screen"},
    "cap_color": {"zh": "屏幕取色器", "en": "Screen color picker"},
    "cap_repeat": {"zh": "重复上次区域", "en": "Repeat last area"},
    "cap_pin1": {"zh": "钉到屏幕：当前剪贴板图", "en": "Pin current clipboard image"},
    "cap_pin2": {"zh": "钉到屏幕：上一张剪贴板图", "en": "Pin previous clipboard image"},
    "st_no_clip_img": {"zh": "剪贴板历史里没有图片", "en": "No image in clipboard history"},
    "st_pinned_clip": {"zh": "已钉住剪贴板图片", "en": "Pinned clipboard image"},
    "t_history": {"zh": "历史截图", "en": "History"},
    "t_settings": {"zh": "设置", "en": "Settings"},
    "lab_delay": {"zh": "延时", "en": "Delay"},
    "lab_speed": {"zh": "滚速", "en": "Speed"},
    "lab_width": {"zh": "线宽", "en": "Width"},
    "lab_output": {"zh": "输出", "en": "Output"},
    # Annotation
    "a_rect": {"zh": "矩形", "en": "Rectangle"},
    "a_ellipse": {"zh": "椭圆", "en": "Ellipse"},
    "a_arrow": {"zh": "箭头", "en": "Arrow"},
    "a_line": {"zh": "直线", "en": "Line"},
    "a_pen": {"zh": "画笔", "en": "Pen"},
    "a_text": {"zh": "文字", "en": "Text"},
    "a_number": {"zh": "序号", "en": "Number"},
    "a_highlight": {"zh": "高亮", "en": "Highlight"},
    "a_blur": {"zh": "打码", "en": "Blur"},
    "a_gaussian_blur": {"zh": "高斯模糊", "en": "Gaussian blur"},
    "a_magnify": {"zh": "放大镜", "en": "Magnifier"},
    "a_crop": {"zh": "裁剪", "en": "Crop"},
    "a_color": {"zh": "标注颜色", "en": "Annotation color"},
    "a_undo": {"zh": "撤销（Ctrl+Z）", "en": "Undo (Ctrl+Z)"},
    "a_clear": {"zh": "清除标注", "en": "Clear annotations"},
    "a_picktext": {"zh": "选词", "en": "Select words"},
    # Export
    "e_ocr": {"zh": "OCR 提取文字", "en": "OCR extract text"},
    "e_copy": {"zh": "复制图片", "en": "Copy image"},
    "e_pin": {"zh": "钉到屏幕", "en": "Pin to screen"},
    "e_beautify": {"zh": "美化导出", "en": "Beautify export"},
    "e_save": {"zh": "保存图片", "en": "Save image"},
    "ocr_lang": {"zh": "语言", "en": "Language"},
    "ocr_layout": {"zh": "版面", "en": "Layout"},
    "ocr_enhance": {"zh": "图像增强", "en": "Image enhance"},
    # Tray
    "tray_show": {"zh": "显示主窗口", "en": "Show main window"},
    "tray_quit": {"zh": "退出 Kapture", "en": "Quit Kapture"},
    "tray_tip": {"zh": "Kapture — 截图 / OCR / 录屏", "en": "Kapture — Capture / OCR / Record"},
    # Settings
    "set_title": {"zh": "Kapture 设置", "en": "Kapture Settings"},
    "tab_general": {"zh": "常规", "en": "General"},
    "tab_shortcuts": {"zh": "快捷键", "en": "Shortcuts"},
    "tab_ocr": {"zh": "OCR", "en": "OCR"},
    "tab_record": {"zh": "录屏", "en": "Recording"},
    "tab_ui": {"zh": "界面", "en": "Interface"},
    "set_savedir": {"zh": "保存目录", "en": "Save folder"},
    "set_browse": {"zh": "浏览…", "en": "Browse…"},
    "set_tmpl": {"zh": "文件名模板", "en": "Filename template"},
    "set_autocopy": {"zh": "截图后自动复制到剪贴板", "en": "Auto-copy to clipboard after capture"},
    "set_autosave": {"zh": "截图后自动保存到目录", "en": "Auto-save to folder after capture"},
    "set_openeditor": {"zh": "截图后直接打开编辑器(否则只显示缩略图)",
                       "en": "Open editor after capture (otherwise thumbnail only)"},
    "set_start_hidden": {"zh": "启动时在后台运行（通过托盘或快捷键唤起）",
                         "en": "Start in background (open from tray or shortcut)"},
    "set_snap_windows": {"zh": "截图时吸附窗口（悬停高亮并单击选中整个窗口、拖拽边缘对齐窗口边界）",
                         "en": "Snap to windows while selecting (hover highlights a window, click selects it; edges align to window borders)"},
    "p_ocr": {"zh": "识别文字 (O)", "en": "OCR text (O)"},
    "p_clickthrough": {"zh": "鼠标穿透", "en": "Click-through"},
    "p_reset_opacity": {"zh": "恢复不透明", "en": "Reset opacity"},
    "tray_undo_clickthrough": {"zh": "关闭全部钉图鼠标穿透",
                               "en": "Disable click-through on all pins"},
    "set_sc_hint": {"zh": "点击输入框后按组合键；清空可停用。快捷键由当前桌面管理。",
                    "en": "Click a field and press a key combo; clear to disable. Managed by your desktop."},
    "set_sc_unavailable": {"zh": "当前桌面不支持在 Kapture 中直接注册全局快捷键；可在系统设置中绑定下列命令。",
                           "en": "This desktop cannot register shortcuts here; bind the commands in system settings."},
    "set_sc_duplicate": {"zh": "两个功能不能使用同一个快捷键。", "en": "Two actions cannot use the same shortcut."},
    "set_sc_invalid": {"zh": "此快捷键组合无法注册为全局快捷键。", "en": "This key combination cannot be registered globally."},
    "set_ocr_deflang": {"zh": "默认识别语言", "en": "Default OCR language"},
    "set_ocr_deflayout": {"zh": "默认版面", "en": "Default layout"},
    "set_ocr_enh": {"zh": "图像增强(放大+二值化,提升准确率)",
                    "en": "Image enhance (upscale + threshold, better accuracy)"},
    "set_autoocr": {"zh": "截图后自动 OCR（打开编辑器并显示结果）",
                    "en": "Run OCR after capture (open editor and show text)"},
    "set_ocr_note": {"zh": "提示:中文需已安装对应 tesseract 语言包",
                     "en": "Note: install matching tesseract language data"},
    "set_fps": {"zh": "帧率 (fps)", "en": "Frame rate (fps)"},
    "set_gif": {"zh": "录屏同时导出 GIF", "en": "Also export GIF when recording"},
    "set_theme": {"zh": "外观主题", "en": "Appearance"},
    "set_accent": {"zh": "强调色", "en": "Accent color"},
    "set_uilang": {"zh": "界面语言", "en": "Interface language"},
    "theme_system": {"zh": "跟随系统（启动或保存时更新）", "en": "System (updates on launch or save)"},
    "theme_dark": {"zh": "深色", "en": "Dark"},
    "theme_light": {"zh": "浅色", "en": "Light"},
    "theme_starship": {"zh": "Starship 蓝", "en": "Starship Blue"},
    "theme_one_dark_pro_darker": {"zh": "One Dark Pro Darker", "en": "One Dark Pro Darker"},
    "theme_vitesse_dark": {"zh": "Vitesse Dark", "en": "Vitesse Dark"},
    "set_theme_preview": {"zh": "选择后立即预览；确定保存，取消还原。",
                          "en": "Preview on selection; OK saves, Cancel restores."},
    "acc_theme": {"zh": "跟随主题", "en": "Theme default"},
    "acc_indigo": {"zh": "靛蓝紫", "en": "Indigo"},
    "acc_blue": {"zh": "蓝", "en": "Blue"},
    "acc_teal": {"zh": "青绿", "en": "Teal"},
    "acc_orange": {"zh": "橙", "en": "Orange"},
    "acc_pink": {"zh": "玫红", "en": "Pink"},
    # Dialogs / status
    "dlg_save": {"zh": "保存截图", "en": "Save screenshot"},
    "dlg_savedir": {"zh": "选择保存目录", "en": "Choose save folder"},
    "dlg_beautify": {"zh": "美化导出", "en": "Beautify export"},
    "dlg_pickcolor": {"zh": "选择标注颜色", "en": "Pick annotation color"},
    "st_ready": {"zh": "就绪", "en": "Ready"},
    "st_copied": {"zh": "已复制到剪贴板", "en": "Copied to clipboard"},
    "st_need_shot": {"zh": "请先截图", "en": "Capture something first"},
    "st_ocr_running": {"zh": "OCR 识别中……", "en": "Running OCR…"},
    "st_settings_saved": {"zh": "设置已保存", "en": "Settings saved"},
    "st_no_history": {"zh": "还没有历史截图", "en": "No history yet"},
    "st_pinned": {"zh": "已钉到屏幕(拖动移动、滚轮缩放、双击关闭)",
                  "en": "Pinned (drag to move, wheel to zoom, double-click to close)"},
    "hist_title": {"zh": "历史截图", "en": "History"},
    "lab_ocr_pending": {"zh": "OCR 识别中，结果待图片打开后显示……",
                        "en": "OCR done — text shows when the image opens…"},
    "st_ocr_text": {"zh": "文字", "en": "text"},
    "st_ocr_none": {"zh": "未识别到文字", "en": "No text recognized"},
    "t_ocr": {"zh": "截屏取词", "en": "Screen text grab"},
    "hud_stop": {"zh": "⏹ 停止", "en": "⏹ Stop"},
    "hud_auto": {"zh": "自动滚动拼接中…请勿移动鼠标",
                 "en": "Auto stitching… keep the mouse still"},
    "hud_manual": {"zh": "可上下滚动；完成后点停止或按 Esc",
                   "en": "Scroll up/down; Stop or Esc when done"},
    "scroll_unmatched": {"zh": "无法对齐：请滚回已捕获区域；自动模式已停止并保留连续部分",
                         "en": "Cannot align: return to captured area; auto mode stopped with continuous result"},
    "scroll_manual_unmatched": {"zh": "暂时无法对齐：请回到已捕获区域；手动模式仍在继续",
                                 "en": "Temporarily cannot align: return to captured area; manual mode continues"},
    "scroll_down": {"zh": "自动向下滚动", "en": "Auto scroll down"},
    "scroll_up": {"zh": "自动向上滚动", "en": "Auto scroll up"},
    "t_ocr_all": {"zh": "全部识别", "en": "Recognize all"},
    "t_copy_all": {"zh": "全部复制", "en": "Copy all"},
    "card_edit": {"zh": "编辑标注", "en": "Edit annotations"},
    "card_copy": {"zh": "复制图片", "en": "Copy image"},
    "card_save": {"zh": "保存图片", "en": "Save image"},
    "card_pin": {"zh": "钉到屏幕", "en": "Pin to screen"},
    "card_close": {"zh": "关闭", "en": "Close"},
}


def swatch_icon(color, size=20):
    """A rounded color-swatch icon, used as the "current annotation color" button."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 70), 1))
    p.setBrush(QtGui.QColor(color))
    p.drawRoundedRect(QtCore.QRectF(2, 2, size - 4, size - 4), 4, 4)
    p.end()
    return QtGui.QIcon(pm)


def line_icon(name, color="#d2d2da", size=22):
    """Hand-drawn monochrome line icon (original vector, no external assets)."""
    import math
    dpr = max(1.0, QtWidgets.QApplication.instance().devicePixelRatio())
    pm = QtGui.QPixmap(round(size * dpr), round(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color), size * 1.65 / 24.0)
    pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    u = size / 24.0

    def Pt(x, y): return QtCore.QPointF(x * u, y * u)
    def L(x1, y1, x2, y2): p.drawLine(Pt(x1, y1), Pt(x2, y2))
    def Rr(x, y, w, h, r=0):
        rc = QtCore.QRectF(x * u, y * u, w * u, h * u)
        (p.drawRoundedRect(rc, r * u, r * u) if r else p.drawRect(rc))
    def Ell(x, y, w, h): p.drawEllipse(QtCore.QRectF(x * u, y * u, w * u, h * u))
    def head(x, y, ang, ln=5):
        for da in (math.radians(150), math.radians(-150)):
            p.drawLine(Pt(x, y), Pt(x + ln * math.cos(ang + da),
                                    y + ln * math.sin(ang + da)))

    if name == "region":
        for cx, cy, dx, dy in [(4, 4, 1, 1), (20, 4, -1, 1),
                               (4, 20, 1, -1), (20, 20, -1, -1)]:
            L(cx, cy, cx + 5 * dx, cy); L(cx, cy, cx, cy + 5 * dy)
    elif name == "window":
        Rr(4, 5, 16, 14, 2); L(4, 9.5, 20, 9.5)
    elif name == "scroll":
        Rr(6, 3, 12, 18, 2); L(12, 7, 12, 15); head(12, 16, math.pi / 2)
    elif name == "manual":
        Rr(7, 4, 10, 16, 3); L(12, 8, 12, 16)
        head(12, 7.5, -math.pi / 2, 3.5); head(12, 16.5, math.pi / 2, 3.5)
    elif name == "record":
        Ell(4, 4, 16, 16); p.setBrush(QtGui.QColor(color)); Ell(9, 9, 6, 6)
    elif name == "color":      # eyedropper
        L(7, 17, 15, 9); Rr(14, 6, 4, 4, 1); L(6, 18, 8, 16)
    elif name == "repeat":
        p.drawArc(QtCore.QRectF(5 * u, 5 * u, 14 * u, 14 * u), 50 * 16, 260 * 16)
        head(16.5, 7.5, math.radians(20))
    elif name == "history":
        Ell(4, 4, 16, 16); L(12, 12, 12, 7.5); L(12, 12, 15.5, 13.5)
    elif name == "settings":
        # Three quiet, balanced sliders instead of a dense gear at small sizes.
        L(5, 5, 5, 7); L(5, 11, 5, 19); Ell(3, 7, 4, 4)
        L(12, 5, 12, 13); L(12, 17, 12, 19); Ell(10, 13, 4, 4)
        L(19, 5, 19, 9); L(19, 13, 19, 19); Ell(17, 9, 4, 4)
    elif name == "editor":
        Rr(4,4,16,16,2.5)
        L(4,8,20,8)
        L(7,14,17,14);L(14,11,17,14);L(14,17,17,14)
    elif name == "ocr":
        for cx, cy, dx, dy in [(4,4,1,1),(20,4,-1,1),(4,20,1,-1),(20,20,-1,-1)]:
            L(cx,cy,cx+3*dx,cy); L(cx,cy,cx,cy+3*dy)
        L(8,9,16,9); L(12,9,12,16); L(10,16,14,16)
    elif name == "copy":
        path=QtGui.QPainterPath(Pt(7,16))
        path.lineTo(Pt(6,16));path.quadTo(Pt(4,16),Pt(4,14))
        path.lineTo(Pt(4,6));path.quadTo(Pt(4,4),Pt(6,4))
        path.lineTo(Pt(14,4));path.quadTo(Pt(16,4),Pt(16,6));path.lineTo(Pt(16,7))
        p.drawPath(path);Rr(8,8,12,12,2.5)
    elif name == "pin":
        path=QtGui.QPainterPath(Pt(8,4))
        for x,y in [(16,4),(15,11),(18,14),(6,14),(9,11),(8,4)]:
            path.lineTo(Pt(x,y))
        p.drawPath(path);L(12,14,12,21)
    elif name == "beautify":   # sparkle/star
        for (cx, cy, s) in [(11, 11, 6), (17, 6, 2.6)]:
            L(cx - s, cy, cx + s, cy); L(cx, cy - s, cx, cy + s)
    elif name == "save":
        L(12, 4, 12, 15); head(12, 15, math.pi / 2); L(6, 19, 18, 19)
    elif name == "rect":
        Rr(4, 6, 16, 12, 2.5)
    elif name == "ellipse":
        Ell(4, 6, 16, 12)
    elif name == "arrow":
        L(6, 18, 17, 7); head(17, 7, math.radians(-45))
    elif name == "line":
        L(6, 18, 18, 6)
    elif name == "pen":
        path=QtGui.QPainterPath(Pt(5,19))
        for x,y in [(6,14),(16,4),(20,8),(10,18),(5,19)]:
            path.lineTo(Pt(x,y))
        p.drawPath(path);L(14,6,18,10);L(6,14,10,18)
    elif name == "text":
        L(5,7,5,5);L(5,5,19,5);L(19,5,19,7)
        L(12,5,12,19);L(9,19,15,19)
    elif name == "number":
        Ell(4,4,16,16);L(10,10,12,8);L(12,8,12,16);L(10,16,14,16)
    elif name == "highlight":
        path=QtGui.QPainterPath(Pt(6,14))
        for x,y in [(14,6),(19,11),(11,19),(6,14)]:
            path.lineTo(Pt(x,y))
        p.drawPath(path);L(5,19,8,16);L(4,21,12,21)
    elif name == "blur":
        for x,y in [(5,5),(13,5),(5,13),(13,13)]:
            Rr(x,y,6,6,1.2)
    elif name == "gaussian":
        Ell(4,4,16,16)
        for x,y in [(9,9),(15,9),(9,15),(15,15)]:
            p.setBrush(QtGui.QColor(color));Ell(x-0.8,y-0.8,1.6,1.6)
        p.setBrush(Qt.NoBrush)
    elif name == "magnify":
        Ell(4, 4, 12, 12); L(14.5, 14.5, 20, 20)
    elif name == "crop":
        L(8, 4, 8, 17); L(8, 17, 20, 17); L(4, 7, 16, 7); L(16, 7, 16, 20)
    elif name == "select":
        p.drawPolygon(QtGui.QPolygonF([Pt(6,3),Pt(6,20),Pt(11,15),Pt(18,15)]))
    elif name in ("undo", "redo"):
        if name == "redo":
            p.translate(size,0);p.scale(-1,1)
        path=QtGui.QPainterPath(Pt(5,9))
        path.lineTo(Pt(14,9));path.cubicTo(Pt(22,9),Pt(22,19),Pt(14,19))
        p.drawPath(path);L(5,9,9,5);L(5,9,9,13)
        if name == "redo":
            p.scale(-1,1);p.translate(-size,0)
    elif name == "clear":      # trash can
        L(5, 7, 19, 7); Rr(7, 7, 10, 13, 1); L(10, 5, 14, 5)
        L(10, 10, 10, 17); L(14, 10, 14, 17)
    elif name == "close":      # ✕
        L(6, 6, 18, 18); L(18, 6, 6, 18)
    elif name == "picktext":   # cursor over a text line (cursor word selection)
        L(6, 5, 17, 5); L(6, 8.5, 13, 8.5)
        p.setBrush(QtGui.QColor(color))
        p.drawPolygon(QtGui.QPolygonF([Pt(8, 11.5), Pt(8, 20.5), Pt(10.8, 17.8),
                                       Pt(12.6, 21.5), Pt(14.4, 20.6),
                                       Pt(12.6, 17), Pt(16.2, 16.6)]))
        p.setBrush(Qt.NoBrush)
    elif name == "textgrab":   # capture-a-region + text: viewfinder corners around text lines
        for cx, cy, dx, dy in [(3, 3, 1, 1), (21, 3, -1, 1),
                               (3, 21, 1, -1), (21, 21, -1, -1)]:
            L(cx, cy, cx + 4 * dx, cy); L(cx, cy, cx, cy + 4 * dy)
        L(7, 10, 17, 10); L(7, 13.5, 17, 13.5); L(7, 17, 13, 17)
    else:
        Ell(7, 7, 10, 10)
    p.end()
    return QtGui.QIcon(pm)


def _app_dir():
    import os
    return os.path.dirname(os.path.abspath(__file__))


def _run_sh_path():
    import os
    return os.path.join(_app_dir(), "run.sh")


def _icon_path():
    import os
    return os.path.join(_app_dir(), "kapture.png")


def write_desktop_entry(refresh=False):
    """Rewrite the app menu/taskbar launcher (name, description, tooltip, icon) in the current UI language.

    Only writes the default fields (not the [zh_CN]/[en] localized variants), otherwise the system
    locale would override the language chosen inside the app; this way the launcher always follows
    the app's UI language setting.
    """
    import os, shutil, subprocess
    d = os.path.expanduser("~/.local/share/applications")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "kapture.desktop")
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={t('app_name')}\n"
        f"GenericName={t('app_generic')}\n"
        f"Comment={t('app_comment')}\n"
        f"Exec={_run_sh_path()}\n"
        f"Icon={_icon_path()}\n"
        "Terminal=false\n"
        "StartupWMClass=kapture\n"
        "Categories=Graphics;Utility;\n"
        "Keywords=screenshot;ocr;scroll;capture;录屏;截图;\n"
    )
    # Remove the old scrollshot.desktop to avoid two entries in the menu
    old_entry = os.path.join(d, "scrollshot.desktop")
    if os.path.exists(old_entry):
        os.remove(old_entry)
        refresh = True
    old = ""
    if os.path.exists(path):
        with open(path) as f:
            old = f.read()
    if old == content and not refresh:
        return
    with open(path, "w") as f:
        f.write(content)
    if refresh:
        # Refresh the desktop database and KDE menu cache (in the background, non-blocking)
        if shutil.which("update-desktop-database"):
            subprocess.Popen(["update-desktop-database", d],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        kde_cache = shutil.which("kbuildsycoca5") or shutil.which("kbuildsycoca6")
        if kde_cache:
            subprocess.Popen([kde_cache],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# (action name, command flag, internal command) -- actions that can be bound to global shortcuts
SHORTCUT_ACTIONS = [
    ("Region capture", "--region"),
    ("Window capture", "--window"),
    ("Auto scrolling capture", "--scroll"),
    ("Manual scrolling capture", "--manual"),
    ("Color picker", "--color"),
    ("Record screen", "--record"),
    ("Repeat last area", "--repeat"),
    ("Show main window", "--show"),
    ("Open settings", "--settings"),
    ("Pin current clipboard image", "--pin1"),
    ("Pin previous clipboard image", "--pin2"),
]

# Actions whose shortcut is pre-filled and auto-registered on first run so the
# pin-to-clipboard feature works out of the box (PixPin-style). Values are Qt
# PortableText; verified to round-trip to a live GNOME keysym (<Control>1 -> 49).
DEFAULT_KEYS = {"--pin1": "Ctrl+1", "--pin2": "Ctrl+2"}


GNOME_MEDIA_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_CUSTOM_SCHEMA = GNOME_MEDIA_SCHEMA + ".custom-keybinding"
GNOME_CUSTOM_ROOT = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


def shortcut_backend():
    """Return the desktop shortcut writer available in this session."""
    import os, shutil
    if kde_shortcuts_available():
        return "kde"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if "GNOME" in desktop and shutil.which("gsettings"):
        return "gnome"
    return None


# GTK parses a custom-keybinding accelerator by keysym name, not by the literal
# character: "<Alt>`" resolves to keysym 0 (dead shortcut) while "<Alt>grave" works.
# Single letters/digits parse fine, so only punctuation needs the X keysym name.
GNOME_KEYSYM_NAMES = {
    "`": "grave", "~": "asciitilde", "!": "exclam", "@": "at", "#": "numbersign",
    "$": "dollar", "%": "percent", "^": "asciicircum", "&": "ampersand",
    "*": "asterisk", "(": "parenleft", ")": "parenright", "-": "minus",
    "_": "underscore", "=": "equal", "+": "plus", "[": "bracketleft",
    "]": "bracketright", "{": "braceleft", "}": "braceright", "\\": "backslash",
    "|": "bar", ";": "semicolon", ":": "colon", "'": "apostrophe",
    '"': "quotedbl", ",": "comma", ".": "period", "/": "slash",
    "<": "less", ">": "greater", "?": "question",
}

GNOME_SPECIAL_NAMES = {  # Qt PortableText -> GNOME keysym name for non-punctuation keys
    "Esc": "Escape", "Del": "Delete", "Ins": "Insert",
    "PgUp": "Page_Up", "PgDown": "Page_Down", "Space": "space",
}


def gnome_accelerator(sequence):
    """Convert a single Qt key combination to GNOME's accelerator notation."""
    if sequence.count() != 1:
        raise ValueError("one key combination required")
    combo = int(sequence[0])
    mods = ((Qt.CTRL, "Control"), (Qt.ALT, "Alt"),
            (Qt.SHIFT, "Shift"), (Qt.META, "Super"))
    mod_bits = 0
    prefix = ""
    for bit, name in mods:
        mod_bits |= int(bit)
        if combo & int(bit):
            prefix += f"<{name}>"
    key = QtGui.QKeySequence(combo & ~mod_bits).toString(QtGui.QKeySequence.PortableText)
    if key in GNOME_SPECIAL_NAMES:
        key = GNOME_SPECIAL_NAMES[key]
    elif len(key) == 1:
        # GTK only accepts the keysym name for punctuation; letters/digits pass through.
        key = GNOME_KEYSYM_NAMES.get(key, key)
    if not key or (not prefix and len(key) == 1):
        raise ValueError("modifier or special key required")
    # Single letters/digits must stay lower-case; keysym names are used verbatim.
    return prefix + (key.lower() if len(key) == 1 else key)


def gnome_key_sequence(accelerator):
    """Display an existing GNOME shortcut in QKeySequenceEdit."""
    import re
    mods = re.findall(r"<([^>]+)>", accelerator)
    key = re.sub(r"^(?:<[^>]+>)*", "", accelerator)
    mapped = {"Control": "Ctrl", "Primary": "Ctrl", "Alt": "Alt",
              "Shift": "Shift", "Super": "Meta"}
    key = {"Escape": "Esc", "Delete": "Del", "Insert": "Ins",
           "Page_Up": "PgUp", "Page_Down": "PgDown",
           "space": "Space", "plus": "+", "minus": "-"}.get(key, key)
    # Reverse of gnome_accelerator: a punctuation keysym name must become the literal
    # character again, or QKeySequence parses it as nothing and the row shows empty.
    key = {v: k for k, v in GNOME_KEYSYM_NAMES.items()}.get(key, key)
    return QtGui.QKeySequence("+".join([*(mapped.get(mod, mod) for mod in mods), key]))


def _gsettings(*args):
    import subprocess
    try:
        result = subprocess.run(["gsettings", *args], capture_output=True,
                                text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip() or str(exc)) from exc
    return result.stdout.strip()


def _gnome_path(flag):
    return GNOME_CUSTOM_ROOT + "kapture-" + flag.lstrip("-") + "/"


def _gnome_paths():
    import ast
    value = _gsettings("get", GNOME_MEDIA_SCHEMA, "custom-keybindings")
    return [] if value == "@as []" else ast.literal_eval(value)


def gnome_current_key(flag):
    """Return the stored binding for one action.

    Read the subpath directly instead of only when it appears in the master
    custom-keybindings array: an action can be unregistered from that array
    (GNOME then ignores it) while its binding is still stored, and showing it as
    empty invited a save that deleted the binding for good.
    """
    import ast
    path = _gnome_path(flag)
    return ast.literal_eval(_gsettings("get", f"{GNOME_CUSTOM_SCHEMA}:{path}", "binding"))


def gnome_set_shortcuts(entries):
    """Update only Kapture's GNOME shortcuts; preserve unrelated custom shortcuts.

    Entries are ``(name, flag, command, key)`` or ``(name, flag, command, key,
    explicit_clear)``. An empty key keeps a stored binding and re-registers it:
    a blank row in the dialog is usually the action never having been bound, not
    the user asking to unbind it. Only ``explicit_clear`` (the row's ✕ button)
    drops the path and deletes the stored binding.
    """
    paths = _gnome_paths()
    for entry in entries:
        name, flag, command, key = entry[:4]
        explicit_clear = entry[4] if len(entry) > 4 else False
        path = _gnome_path(flag)
        schema = f"{GNOME_CUSTOM_SCHEMA}:{path}"
        if key:
            _gsettings("set", schema, "name", repr("Kapture: " + name))
            _gsettings("set", schema, "command", repr(command))
            _gsettings("set", schema, "binding", repr(key))
            if path not in paths:
                paths.append(path)
        elif explicit_clear:
            if path in paths:
                paths.remove(path)
            for key_name in ("name", "command", "binding"):
                try:
                    _gsettings("reset", schema, key_name)
                except RuntimeError:
                    pass      # nothing stored for this action
        elif _gsettings("get", schema, "binding") != "''":
            if path not in paths:
                paths.append(path)     # keep the binding and make GNOME honour it
    _gsettings("set", GNOME_MEDIA_SCHEMA, "custom-keybindings", repr(paths))


def kde_shortcuts_available():
    """The khotkeys integration below is specific to an active Plasma 5 session."""
    import os, shutil
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    return ("KDE" in desktop or "PLASMA" in desktop) and \
        os.environ.get("KDE_SESSION_VERSION", "5") == "5" and \
        all(shutil.which(cmd) for cmd in ("kreadconfig5", "kwriteconfig5", "qdbus"))


def _kread(group, key, file="khotkeysrc"):
    import subprocess
    r = subprocess.run(["kreadconfig5", "--file", file, "--group", group, "--key", key],
                       capture_output=True, text=True)
    return r.stdout.strip()


def _kwrite(group, key, value, file="khotkeysrc"):
    import subprocess
    subprocess.run(["kwriteconfig5", "--file", file, "--group", group,
                    "--key", key, value], capture_output=True)


def kde_find_block(cmd_url):
    """Find the top-level Data_N block in khotkeysrc with CommandURL==cmd_url; return (index or None, DataCount)."""
    try:
        dc = int(_kread("Data", "DataCount") or "0")
    except ValueError:
        dc = 0
    for i in range(1, dc + 1):
        if _kread(f"Data_{i}Actions0", "CommandURL") == cmd_url:
            return i, dc
    return None, dc


def kde_current_key(cmd_url):
    idx, _ = kde_find_block(cmd_url)
    return _kread(f"Data_{idx}Triggers0", "Key") if idx else ""


def kde_set_shortcut(name, cmd_url, key, uuid):
    """Set a global shortcut for cmd_url (reuse an existing block or create a new one). An empty key clears it."""
    idx, dc = kde_find_block(cmd_url)
    if idx is None:
        if not key:
            return
        idx = dc + 1
        b = f"Data_{idx}"
        _kwrite(b, "Comment", f"Kapture {name}")
        _kwrite(b, "Name", f"Kapture: {name}")
        _kwrite(b, "Enabled", "true")
        _kwrite(b, "Type", "SIMPLE_ACTION_DATA")
        _kwrite(b + "Actions", "ActionsCount", "1")
        _kwrite(b + "Actions0", "CommandURL", cmd_url)
        _kwrite(b + "Actions0", "Type", "COMMAND_URL")
        _kwrite(b + "Conditions", "Comment", "")
        _kwrite(b + "Conditions", "ConditionsCount", "0")
        _kwrite(b + "Triggers", "Comment", "Simple_action")
        _kwrite(b + "Triggers", "TriggersCount", "1")
        _kwrite(b + "Triggers0", "Type", "SHORTCUT")
        _kwrite(b + "Triggers0", "Uuid", uuid)
        _kwrite("Data", "DataCount", str(idx))
    _kwrite(f"Data_{idx}Triggers0", "Key", key)


def kde_reload_shortcuts():
    import subprocess
    subprocess.run(["qdbus", "org.kde.kded5", "/modules/khotkeys",
                    "reread_configuration"], capture_output=True)


def kde_backup_khotkeys():
    import os, shutil, time
    src = os.path.expanduser("~/.config/khotkeysrc")
    if os.path.exists(src):
        shutil.copy(src, src + f".bak.{int(time.time())}")


def qimage_to_bgr(qimg):
    """QImage -> BGR numpy."""
    img = qimg.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    arr = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())
    arr = arr[:, :w * 3].reshape(h, w, 3)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def get_window_geom_at_pointer():
    """Return the physical geometry (x, y, w, h) of the top-level window under the mouse pointer, or None on failure.

    Use Xlib to get the window under the pointer, then walk up to root's direct child (i.e. the
    top-level window with the border), whose geometry includes the title bar.
    """
    try:
        from Xlib import display as _disp
        d = _disp.Display()
        root = d.screen().root
        win = root.query_pointer().child
        if not win:
            d.close()
            return None
        cur = win
        for _ in range(32):                 # defensive upper bound
            parent = cur.query_tree().parent
            if not parent or parent.id == root.id:
                break
            cur = parent
        geo = cur.get_geometry()
        tc = cur.translate_coords(root, 0, 0)
        # translate_coords returns cur's origin offset relative to root (negate to get absolute)
        x, y = -tc.x, -tc.y
        d.close()
        if geo.width < 2 or geo.height < 2:
            return None
        return (int(x), int(y), int(geo.width), int(geo.height))
    except Exception:                       # noqa: BLE001
        return None


def list_visible_windows():
    """Top-to-bottom list of physical (x, y, w, h) rects of viewable normal top-level windows.

    Enumerates root's direct children once (the same frame windows the existing
    window capture returns, title bar included). Override-redirect windows (menus,
    tooltips, our own bypass-WM overlays) and unmapped/tiny windows are skipped.
    """
    try:
        from Xlib import display as _disp
        d = _disp.Display()
        root = d.screen().root
        out = []
        for win in reversed(root.query_tree().children):   # Xlib order is bottom-to-top
            try:
                attr = win.get_attributes()
                if attr.map_state != 2 or attr.override_redirect:   # IsViewable
                    continue
                geo = win.get_geometry()
                tc = win.translate_coords(root, 0, 0)
                x, y = -tc.x, -tc.y
                if geo.width < 30 or geo.height < 30:
                    continue
                out.append((int(x), int(y), int(geo.width), int(geo.height)))
            except Exception:                               # dead window mid-enumeration
                continue
        d.close()
        return out
    except Exception:                       # noqa: BLE001
        return []


def snap_point(px, py, xs, ys, threshold=10):
    """Snap (px, py) to the nearest guide within threshold on each axis.

    Returns (snapped_x, snapped_y, hit_x, hit_y); hit_* is None when that axis did
    not snap (used to draw guide lines only where a snap happened). During a free
    corner drag the moving edges pass exactly through the cursor, so snapping the
    cursor point is moving-edge snapping.
    """
    sx, hx = px, None
    for gx in xs:
        if abs(gx - px) <= threshold and (hx is None or abs(gx - px) < abs(hx - px)):
            hx = gx
    sy, hy = py, None
    for gy in ys:
        if abs(gy - py) <= threshold and (hy is None or abs(gy - py) < abs(hy - py)):
            hy = gy
    return (hx if hx is not None else px,
            hy if hy is not None else py, hx, hy)


def _x11_set_input_passthrough(win_id, passthrough):
    """XShape: an empty ShapeInput makes the window fully click-through;
    combining ShapeInput from Bounding restores normal input. Returns success."""
    try:
        from Xlib import display as _disp
        from Xlib.ext import shape
        d = _disp.Display()
        w = d.create_resource_object('window', int(win_id))
        if passthrough:
            w.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, [])
        else:
            w.shape_combine(shape.SO.Set, shape.SK.Input, shape.SK.Bounding, 0, 0)
        d.flush()
        d.close()
        return True
    except Exception:                       # noqa: BLE001  (offscreen / no DISPLAY / no SHAPE)
        return False


def _strip_cjk_spaces(text):
    """Remove spaces erroneously inserted between CJK characters, while keeping spaces between English words."""
    import re
    cjk = r"一-鿿　-〿＀-￯"
    # Whitespace between two CJK characters -> remove it (loop to handle adjacent cases)
    pat = re.compile(rf"([{cjk}])\s+(?=[{cjk}])")
    prev = None
    while prev != text:
        prev = text
        text = pat.sub(r"\1", text)
    return text


def preprocess_for_ocr(bgr, upscale=2.0):
    """Preprocess for OCR: upscale + grayscale + Otsu threshold (dark backgrounds auto-inverted to black text on white).

    Screenshot text is often small, anti-aliased or on a colored background; this pipeline usually
    noticeably improves Tesseract's accuracy. Returns a single-channel (grayscale) image.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if upscale and upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale,
                          interpolation=cv2.INTER_CUBIC)
    # Light denoise, then Otsu thresholding
    gray = cv2.bilateralFilter(gray, 5, 40, 40)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # If it's a dark background (white text on black), invert to black text on white -- Tesseract prefers the latter
    if th.mean() < 127:
        th = cv2.bitwise_not(th)
    return th


def find_new_content(prev_bgr, cur_bgr, min_confidence=0.5):
    """Compare the previous and current frames; return (the start row y of new content in the current frame, match confidence).

    Idea: take a horizontal template from the middle of the previous frame, template-match it in the
    current frame to find its new position after scrolling, and from that infer the row in the current
    frame corresponding to the bottom of the previous frame; everything below that row is new content.
    """
    h = prev_bgr.shape[0]
    prev_g = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2GRAY)
    cur_g = cv2.cvtColor(cur_bgr, cv2.COLOR_BGR2GRAY)

    tpl_start = int(h * 0.45)
    tpl_h = max(20, int(h * 0.35))
    tpl_start = min(tpl_start, h - tpl_h)
    template = prev_g[tpl_start:tpl_start + tpl_h, :]

    res = cv2.matchTemplate(cur_g, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    matched_y = max_loc[1]

    # The row in the current frame corresponding to the bottom of the previous frame (row h):
    new_start = matched_y + (h - tpl_start)
    return new_start, max_val


def _scroll_match_columns(width):
    """Exclude narrow viewport side borders/scrollbars from alignment only."""
    margin = min(16, width // 50)
    return slice(margin, width - margin)


def fixed_scroll_edges(previous, current):
    """Propose stationary viewport headers/footers; the caller verifies body motion.

    Equal rows alone are not evidence of scrolling. These margins are used only
    when the remaining body independently matches at a nonzero offset.
    """
    columns = _scroll_match_columns(current.shape[1])
    delta = np.abs(previous[:, columns].astype(np.int16) -
                   current[:, columns].astype(np.int16))
    same = np.max(delta, axis=(1, 2)) <= 2
    changed = np.flatnonzero(~same)
    if not len(changed):
        return 0, 0
    top, bottom = int(changed[0]), len(same) - 1 - int(changed[-1])
    limit = len(same) // 3
    return (top if top <= limit else 0, bottom if bottom <= limit else 0)

def locate_frame(canvas_bgr, frame_bgr, y_hint=0, band=2400, conf_min=0.8):
    """Locate an overlapping viewport; reject blank and ambiguous matches.

    Only the bounded search band is converted, independent of total page height.
    A strip proposes offsets; small differences pass the whole-overlap check.
    Larger localized changes need two independent anchors at one offset and
    one contiguous changed region.
    """
    ch, h = canvas_bgr.shape[0], frame_bgr.shape[0]
    if h > ch:
        return None, 0.0
    hint = int(y_hint)
    columns = _scroll_match_columns(frame_bgr.shape[1])
    if (0 <= hint <= ch - h and
            np.array_equal(canvas_bgr[hint:hint+h, columns], frame_bgr[:, columns])):
        return hint, 1.0
    y0, y1 = max(0, hint-band), min(ch, hint+band+h)
    cg = cv2.cvtColor(canvas_bgr[y0:y1, columns], cv2.COLOR_BGR2GRAY)
    fg = cv2.cvtColor(frame_bgr[:, columns], cv2.COLOR_BGR2GRAY)
    strip_h = min(h, max(24, h // 4))
    anchor_bases = tuple(dict.fromkeys((0, (h-strip_h)//2, h-strip_h)))
    anchors, candidates = [], set()
    confidence = 0.0
    for base in anchor_bases:
        strip = fg[base:base+strip_h]
        if strip.std() < 2 or cg.shape[0] < strip_h:
            continue
        anchors.append((base, strip))
        scores = cv2.matchTemplate(cg, strip, cv2.TM_CCOEFF_NORMED).ravel()
        confidence = max(confidence, float(scores.max()))
        # Bound work even on repeated table rows; ambiguity is rejected below.
        for _ in range(8):
            loc = int(scores.argmax())
            if scores[loc] < conf_min:
                break
            candidates.add(y0+loc-base)
            scores[max(0, loc-2):loc+3] = -1
    ranked = []
    for y in candidates:
        # A changed image or lazy-loaded block can invalidate one anchor. For
        # larger viewports, require two separated strips to support the same
        # offset before tolerating local differences in the full overlap.
        independent_anchors = 0
        covered_anchors = 0
        for base, strip in anchors:
            anchor_y = y + base
            if anchor_y < y0 or anchor_y + strip_h > y1:
                continue
            covered_anchors += 1
            anchor = cg[anchor_y-y0:anchor_y-y0+strip_h]
            score = float(cv2.matchTemplate(
                anchor, strip, cv2.TM_CCOEFF_NORMED
            )[0, 0])
            independent_anchors += score >= conf_min
        multi_anchor = covered_anchors >= 2
        lo, hi = max(y0, y), min(y1, y+h)
        if hi-lo < strip_h:
            continue
        delta = np.abs(cg[lo-y0:hi-y0].astype(np.int16) -
                       fg[lo-y:hi-y].astype(np.int16))
        error = float(delta.mean())
        # Preserve the original whole-overlap acceptance for small, possibly
        # separated changes. Larger local animation may use a stricter fallback
        # only when two anchors independently support the same offset.
        inconsistent_rows = np.count_nonzero(delta > 16, axis=1) > max(2, fg.shape[1] * 0.003)
        if error <= 12 and inconsistent_rows.mean() <= 0.1:
            ranked.append((error, y))
            continue
        if (error > 12 or not multi_anchor or independent_anchors < 2):
            continue
        changed_rows = np.flatnonzero(inconsistent_rows)
        if len(changed_rows) and len(changed_rows) != int(
                changed_rows[-1] - changed_rows[0] + 1):
            continue
        ranked.append((error, y))
    ranked.sort()
    if not ranked:
        return None, min(confidence, 0.49)
    error, y = ranked[0]
    # On a static text page only a few glyph pixels may distinguish rows.
    # A fixed one-level mean tolerance incorrectly erases that evidence.
    tolerance = max(0.001, error * 0.1)
    if any(abs(other-y) > 2 and err <= error+tolerance for err, other in ranked[1:]):
        return None, 0.0
    return y, max(conf_min, 1-error/255)


def stitch_frame(canvas_bgr, frame_bgr, y):
    """Merge a located frame into the canvas: prepend rows above / append rows
    below that fall outside it, drop everything that overlaps (the dedup that
    makes repeated up/down scrolling safe). Returns (canvas, y_of_frame_top)."""
    ch, h = canvas_bgr.shape[0], frame_bgr.shape[0]
    if y < 0:
        canvas_bgr = np.vstack([frame_bgr[:-y, :], canvas_bgr])
        y = 0
    ch = canvas_bgr.shape[0]
    if y + h > ch:
        canvas_bgr = np.vstack([canvas_bgr, frame_bgr[ch - y:, :]])
    return canvas_bgr, y


def refine_frame_offset(canvas_bgr, frame_bgr, y, win=8, rows=160):
    """Refine near the seam only; equal scores preserve the proposed location."""
    ch, h = canvas_bgr.shape[0], frame_bgr.shape[0]
    if win <= 0 or h > ch:
        return y
    best_y, best_diff = y, float("inf")
    for off in sorted(range(-win, win+1), key=abs):
        yy = y+off
        lo, hi = max(0, yy), min(ch, yy+h)
        if hi-lo < min(rows, h)//2:
            continue
        lo = max(lo, hi-rows)
        columns = _scroll_match_columns(frame_bgr.shape[1])
        a = canvas_bgr[lo:hi, columns].astype(np.int16)
        b = frame_bgr[lo-yy:hi-yy, columns].astype(np.int16)
        diff = float(np.abs(a-b).mean())
        if diff < best_diff:
            best_y, best_diff = yy, diff
    return best_y


def refine_new_start(prev_bgr, cur_bgr, new_start, win=16, strip=10):
    """Snap the guessed seam to the row where the current frame actually aligns with
    the bottom of the previous frame.

    Template matching is only accurate to the whole search and animated scrolling
    tears frames; a seam off by a few rows duplicates or drops content and shows up
    as a shadow-like band at every scroll step. Sliding the boundary within ±win and
    taking the position whose strip above it best matches the previous bottom removes
    that. Returns a row in cur_bgr just like find_new_content()."""
    h, w = prev_bgr.shape[:2]
    if new_start - strip < 0 or new_start + win >= cur_bgr.shape[0] or strip > h:
        return new_start
    prev_g = cv2.cvtColor(prev_bgr, cv2.COLOR_BGR2GRAY)
    cur_g = cv2.cvtColor(cur_bgr, cv2.COLOR_BGR2GRAY)
    anchor = prev_g[h - strip:h, :].astype(np.int16)
    best_diff, best_d = None, 0
    for d in range(-win, win + 1):
        y = new_start - strip + d
        if y < 0 or y + strip > cur_g.shape[0]:
            continue
        diff = int(np.abs(cur_g[y:y + strip, :].astype(np.int16) - anchor).sum())
        if best_diff is None or diff < best_diff:
            best_diff, best_d = diff, d
    return new_start + best_d if best_diff is not None else new_start


class CaptureWorker(QThread):
    """Shared automatic/manual capture and global-canvas stitching worker."""
    progress = pyqtSignal(str)
    frame = pyqtSignal(object)
    finished_img = pyqtSignal(object)
    preparing_grab = pyqtSignal()
    grabbed = pyqtSignal()

    def __init__(self, rect_phys, scroll_clicks=3, settle=0.45,
                 max_iters=80, max_height=40000, parent=None,
                 manual=False, direction=1):
        super().__init__(parent)
        self.left, self.top, self.width, self.height = rect_phys
        self.scroll_clicks, self.settle = scroll_clicks, settle
        self.max_iters, self.max_height = max_iters, max_height
        self.manual, self.direction = manual, direction
        self._abort = False
        self.hide_ui_for_grab = False
        self.grab_ready = threading.Event()

    def abort(self):
        self._abort = True
        self.grab_ready.set()

    def _grab(self):
        if self._abort:
            return None
        if self.hide_ui_for_grab:
            self.grab_ready.clear()
            if self._abort:
                return None
            self.preparing_grab.emit()
            if not self.grab_ready.wait(3):
                raise RuntimeError("Capture controls did not hide in time")
        if self._abort:
            return None
        try:
            return grab_region(self.left, self.top, self.width, self.height)
        finally:
            if self.hide_ui_for_grab:
                self.grabbed.emit()

    def _preview(self, canvas):
        image = canvas
        if canvas.shape[0] > 1200:
            scale = 1200/canvas.shape[0]
            image = cv2.resize(canvas, (max(1, int(canvas.shape[1]*scale)), 1200))
        self.frame.emit((image, int(canvas.shape[0])))

    def run(self):
        canvas = None
        header = footer = None
        try:
            mouse = None
            if not self.manual:
                mouse = MouseController()
                dpr = getattr(self, "dpr", 1.0)
                mouse.position = (int((self.left+self.width//2)/dpr),
                                  int((self.top+self.height//2)/dpr))
                time.sleep(0.2)
            canvas = self._grab()
            if canvas is None:
                return
            self._preview(canvas)
            first = canvas
            top = bottom = 0
            edges_checked = False
            y_hint, stationary, iteration = 0, 0, 0
            unmatched_frame, unmatched_streak = None, 0
            manual_unmatched_warned = False
            while not self._abort and (self.manual or iteration < self.max_iters):
                iteration += 1
                if mouse is not None:
                    mouse.scroll(0, -self.direction*self.scroll_clicks)
                time.sleep(0.25 if self.manual else self.settle)
                cur = self._grab()
                if cur is None:
                    break
                raw_cur = cur
                if not edges_checked:
                    trim_top, trim_bottom = fixed_scroll_edges(first, cur)
                    if trim_top or trim_bottom:
                        end = self.height - trim_bottom
                        body = first[trim_top:end]
                        offset, _ = locate_frame(body, cur[trim_top:end])
                        if offset is not None and offset != 0:
                            # Commit fixed margins only after independent body
                            # motion is located. Static chrome cannot match a gap.
                            top, bottom = trim_top, trim_bottom
                            header, footer = first[:top], first[end:]
                            canvas = body
                            edges_checked = True
                cur = cur[top:self.height-bottom]
                y, conf = locate_frame(canvas, cur, y_hint)
                if y is None:
                    if not self.manual:
                        self.progress.emit(t("scroll_unmatched"))
                        # Stop at the last continuous image: never advance the
                        # reference across a gap or keep scrolling farther away.
                        break
                    if unmatched_frame is None:
                        unmatched_streak = 1
                    else:
                        pixel_change = float(np.abs(
                            cur.astype(np.int16) - unmatched_frame.astype(np.int16)
                        ).mean())
                        unmatched_streak = (unmatched_streak + 1
                                             if pixel_change <= 3.0 else 1)
                    unmatched_frame = cur
                    if unmatched_streak >= 3 and not manual_unmatched_warned:
                        self.progress.emit(t("scroll_manual_unmatched"))
                        manual_unmatched_warned = True
                    continue
                unmatched_frame, unmatched_streak = None, 0
                manual_unmatched_warned = False
                if y != y_hint:
                    edges_checked = True
                y = refine_frame_offset(canvas, cur, y)
                old_h = canvas.shape[0]
                if header is not None:
                    # Repeated blank/text rows may look fixed on the first
                    # scroll. Keep the actual outermost viewport pixels, not
                    # a stale copy of those rows from the initial viewport.
                    if y < 0:
                        header = raw_cur[:top]
                    if y + cur.shape[0] > old_h:
                        footer = raw_cur[self.height-bottom:]
                canvas, y_hint = stitch_frame(canvas, cur, y)
                stationary = stationary+1 if canvas.shape[0] == old_h else 0
                image = (np.vstack((header, canvas, footer))
                         if header is not None else canvas)
                if image.shape[0] >= self.max_height:
                    # Crop the assembled image, not its body: retaining a
                    # footer from beyond the limit would introduce a gap.
                    image = (image[-self.max_height:] if y < 0
                             else image[:self.max_height])
                    canvas, header, footer = image, None, None
                self._preview(image)
                self.progress.emit(f"{image.shape[0]} px · Esc " + t("hud_stop"))
                if image.shape[0] >= self.max_height:
                    break
                if not self.manual and stationary >= 3:
                    break
        except Exception as exc:
            self.progress.emit(f"Error: {exc}")
        finally:
            if canvas is not None and header is not None:
                canvas = np.vstack((header, canvas, footer))
            self.finished_img.emit(canvas)


# --------------------------------------------------------------------------- #
# Region selection overlay
# --------------------------------------------------------------------------- #
class RegionSelector(QtWidgets.QWidget):
    """Full-screen overlay over a frozen screen: drag to select a region (region mode) or pick a color (color mode).

    Before showing, grab a full-screen capture as the background (freezing the picture), and draw a
    loupe next to the cursor showing pixel-level zoom, coordinates and hex color; region mode also
    shows the selection size.
    """
    selected = pyqtSignal(QRect, object)   # global selection rect + BGR numpy crop of the frozen frame
    colorPicked = pyqtSignal(object)        # emits a QColor
    cancelled = pyqtSignal()

    LOUPE = 120          # loupe side length (logical pixels)
    ZOOM = 8             # zoom factor
    SNAP_T = 10          # edge-snap threshold (logical pixels)

    def __init__(self, mode="region", parent=None):
        super().__init__(parent)
        self.mode = mode
        # Bypass the window manager (like ScrollHud/RecordBar/WindowPicker) so the
        # overlay covers the whole virtual desktop including the GNOME top bar and
        # dock; a WM-managed Qt.Tool window is clamped to the work area, which offset
        # the selection from the frozen full-geometry frame.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.X11BypassWindowManagerHint)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        scr = QtWidgets.QApplication.primaryScreen()
        self.dpr = scr.devicePixelRatio()
        geo = scr.virtualGeometry()
        self.vorigin = geo.topLeft()
        self.setGeometry(geo)

        # Freeze the screen: grab the full screen (physical pixels)
        with mss.mss() as sct:
            mon = sct.monitors[0]
            shot = sct.grab(mon)
            arr = np.array(shot)            # BGRA
        rgb = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGB)
        h, w, _ = rgb.shape
        self.bg_img = QtGui.QImage(rgb.data, w, h, 3 * w,
                                   QtGui.QImage.Format_RGB888).copy()
        self.bg_pix = QtGui.QPixmap.fromImage(self.bg_img)
        self.bg_pix.setDevicePixelRatio(self.dpr)

        self.origin = None
        self.cur = QtCore.QPoint(0, 0)
        # Window snapping (region mode): hover-highlight + click-select and edge guides
        self.snap = QtCore.QSettings("ScrollShot", "ScrollShot").value(
            "snap_windows", True, type=bool)
        self._wins = None          # cached window rects (widget coords), filled on show
        self._hover = None         # hovered window rect (widget coords)
        self._press_pos = None
        self._dragging = False
        self._guides = None        # (xs, ys) guide lines built at drag start
        self._snap_lines = None    # [(vertical, coord)] drawn this frame

    def showEvent(self, e):
        super().showEvent(e)
        # A WM-bypassed window is not given keyboard focus by the window manager,
        # so grab the keyboard explicitly to keep Esc working.
        self.activateWindow()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        self.grabKeyboard()
        if self.mode == "region" and self.snap and self._wins is None:
            self._wins = [self._phys_to_logical(r) for r in list_visible_windows()]

    def _phys_to_logical(self, phys):
        """Physical (x, y, w, h) on the X root -> widget logical coords."""
        x, y, w, h = phys
        return QRect(int(x / self.dpr) - self.vorigin.x(),
                     int(y / self.dpr) - self.vorigin.y(),
                     int(w / self.dpr), int(h / self.dpr))

    @staticmethod
    def hit_window(wins, pt):
        """First (top-most) rect in a top-to-bottom list containing pt, else None."""
        for r in wins:
            if r.contains(pt):
                return r
        return None

    def closeEvent(self, e):
        self.releaseKeyboard()   # no-op if we never grabbed it
        super().closeEvent(e)

    # Get the pixel color of the background at a given logical coordinate
    def _pixel(self, lp):
        x = int((lp.x()) * self.dpr)
        y = int((lp.y()) * self.dpr)
        x = max(0, min(self.bg_img.width() - 1, x))
        y = max(0, min(self.bg_img.height() - 1, y))
        return QtGui.QColor(self.bg_img.pixel(x, y))

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self.bg_pix)
        # Semi-transparent dimming
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 90))
        if _LANG == 'zh':
            hint=('拖动选择区域，Esc 取消' if self.mode=='region'
                  else '移动到目标像素，点击取色，Esc 取消')
        else:
            hint=('Drag to select a region, Esc to cancel' if self.mode=='region'
                  else 'Move to a pixel, click to pick color, Esc to cancel')
        p.setPen(QtGui.QColor(255, 255, 255, 220))
        p.drawText(20, 30, getattr(self,"hint_text",hint))

        if (self.mode == "region" and self.origin is None and self._hover
                and self.snap):
            # Hover-highlight the window under the cursor: a single click grabs it whole
            hv = self._hover
            p.drawPixmap(hv, self.bg_pix, QtCore.QRectF(
                hv.x() * self.dpr, hv.y() * self.dpr,
                hv.width() * self.dpr, hv.height() * self.dpr).toRect())
            p.setPen(QtGui.QPen(QtGui.QColor(0, 170, 255), 2))
            p.drawRect(hv)
            p.setPen(QtGui.QColor(255, 255, 255))
            p.drawText(hv.left(), max(hv.top() - 6, 12),
                       f"{hv.width()} × {hv.height()}")

        if self.mode == "region" and self.origin and self.cur:
            r = QRect(self.origin, self.cur).normalized()
            # Restore the selection to the sharp picture
            p.drawPixmap(r, self.bg_pix, QtCore.QRectF(
                r.x() * self.dpr, r.y() * self.dpr,
                r.width() * self.dpr, r.height() * self.dpr).toRect())
            p.setPen(QtGui.QPen(QtGui.QColor(0, 170, 255), 2))
            p.drawRect(r)
            p.setPen(QtGui.QColor(255, 255, 255))
            p.drawText(r.left(), max(r.top() - 6, 12),
                       f"{r.width()} × {r.height()}")
            # Magenta guide lines where edge-snapping kicked in
            if self._snap_lines:
                p.setPen(QtGui.QPen(QtGui.QColor(255, 0, 200, 180), 1))
                for vertical, c in self._snap_lines:
                    if vertical:
                        p.drawLine(c, 0, c, self.height())
                    else:
                        p.drawLine(0, c, self.width(), c)

        self._draw_loupe(p, self.cur)

    def _loupe_geometry(self):
        """Integer on-screen px per source px (s), source side, drawn side — grid-aligned at any dpr."""
        s = max(1, round(self.ZOOM / self.dpr))
        src_px = self.LOUPE // s
        return s, src_px, src_px * s

    def _draw_loupe(self, p, lp):
        L = self.LOUPE
        s, src_px, side = self._loupe_geometry()
        sx = int(lp.x() * self.dpr) - src_px // 2
        sy = int(lp.y() * self.dpr) - src_px // 2
        src = self.bg_img.copy(sx, sy, src_px, src_px)
        zoom = src.scaled(side, side, Qt.IgnoreAspectRatio, Qt.FastTransformation)

        # Place the loupe to the lower-right of the cursor; flip it when near an edge
        ox, oy = lp.x() + 20, lp.y() + 20
        if ox + side > self.width():
            ox = lp.x() - side - 20
        if oy + side + 34 > self.height():
            oy = lp.y() - side - 34
        box = QRect(ox, oy, side, side)

        p.drawImage(box, zoom)
        # Pixel grid: one cell per source pixel when cells are big enough to matter
        if s >= 4:
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 50), 1))
            for i in range(src_px + 1):
                p.drawLine(ox + i * s, oy, ox + i * s, oy + side)
                p.drawLine(ox, oy + i * s, ox + side, oy + i * s)
        # Crosshair (subtle; the center-cell stroke below carries the emphasis)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 170, 255, 120), 1))
        p.drawLine(box.center().x(), box.top(), box.center().x(), box.bottom())
        p.drawLine(box.left(), box.center().y(), box.right(), box.center().y())
        # Highlight the exact sampled pixel, then the frame
        p.setPen(QtGui.QPen(QtGui.QColor(0, 170, 255), 2))
        p.drawRect(ox + (src_px // 2) * s, oy + (src_px // 2) * s, s, s)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        p.drawRect(box)

        col = self._pixel(lp)
        hexv = col.name().upper()
        info = QRect(ox, oy + side, side, 34)
        p.fillRect(info, QtGui.QColor(0, 0, 0, 200))
        p.fillRect(QRect(ox + 4, oy + side + 8, 18, 18), col)
        p.setPen(QtGui.QColor(255, 255, 255))
        f = p.font(); f.setPixelSize(11); p.setFont(f)
        p.drawText(QRect(ox + 26, oy + side, side - 28, 34),
                   Qt.AlignVCenter,
                   f"{hexv}\n({int(lp.x()*self.dpr)},{int(lp.y()*self.dpr)})")

    def mousePressEvent(self, e):
        if self.mode == "color":
            col = self._pixel(e.pos())
            self.close()
            self.colorPicked.emit(col)
            return
        self.origin = e.pos()
        self.cur = e.pos()
        self._press_pos = e.pos()
        self._dragging = False
        self._snap_lines = None
        if self.snap:
            # Recompute the hover target at the press point too (covers synthetic
            # events and presses without a preceding move on this widget)
            self._hover = self.hit_window(self._wins or [], e.pos())
        if self.snap and self._wins is not None:
            xs = [v for r in self._wins for v in (r.left(), r.right(), r.center().x())]
            ys = [v for r in self._wins for v in (r.top(), r.bottom(), r.center().y())]
            self._guides = (xs + [0, self.width(), self.origin.x()],
                            ys + [0, self.height(), self.origin.y()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.mode == "region" and self.snap:
            if self.origin is None:
                self._hover = self.hit_window(self._wins or [], e.pos())
            elif not self._dragging:
                # Press never commits: past the threshold, it's a free region drag
                if (e.pos() - self._press_pos).manhattanLength() > 4:
                    self._dragging = True
                    self._hover = None
            if self._dragging and self._guides is not None:
                px, py, gx, gy = snap_point(e.pos().x(), e.pos().y(),
                                            self._guides[0], self._guides[1],
                                            self.SNAP_T)
                self.cur = QtCore.QPoint(px, py)
                self._snap_lines = [l for l in ((True, gx), (False, gy))
                                    if l[1] is not None]
                self.update()
                return
        self.cur = e.pos()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.mode != "region" or self.origin is None:
            return
        if not self._dragging and self._hover is not None:
            # Click without dragging: grab the hovered window whole (PixPin/Snipaste style)
            hv = self._hover
            gr = QRect(self.mapToGlobal(hv.topLeft()), hv.size()).intersected(self.geometry())
            self.close()
            if gr.width() > 8 and gr.height() > 8:
                self.selected.emit(gr, self._crop_frozen(hv))
            else:
                self.cancelled.emit()
            return
        r = QRect(self.origin, self.cur).normalized()
        gr = QRect(self.mapToGlobal(r.topLeft()), r.size())
        self.close()
        if gr.width() > 8 and gr.height() > 8:
            self.selected.emit(gr, self._crop_frozen(r))
        else:
            self.cancelled.emit()

    def _crop_frozen(self, r):
        """Crop the selection from the frozen background frame (BGR numpy), so the result
        is exactly what the user saw: no top bar/dock can reappear in a later re-grab."""
        x = max(0, int(r.x() * self.dpr))
        y = max(0, int(r.y() * self.dpr))
        w = max(1, min(int(r.width() * self.dpr), self.bg_img.width() - x))
        h = max(1, min(int(r.height() * self.dpr), self.bg_img.height() - y))
        crop = self.bg_img.copy(x, y, w, h).convertToFormat(QtGui.QImage.Format_RGB32)
        arr = np.frombuffer(crop.constBits().asstring(crop.sizeInBytes()),
                            dtype=np.uint8).reshape(h, crop.bytesPerLine() // 4, 4)
        return np.ascontiguousarray(arr[:, :w, :3])   # BGRA -> BGR (drop alpha)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()


# --------------------------------------------------------------------------- #
# Floating control bar for manual scrolling capture
# --------------------------------------------------------------------------- #
class ScrollRegionOverlay:
    """Red outline around the scrolling-capture region, PixPin-style.

    Deliberately NOT one full-desktop translucent window: Qt's
    WA_TransparentForMouseEvents is application-local and does not make an X11
    top-level click-through, so such an overlay swallows the wheel events the
    scrolling capture depends on (the bug it caused). Instead the frame is four
    thin always-on-top strips that lie entirely outside the region and are
    mouse-transparent, so the pointer always reaches the target window.
    """
    THICK = 3

    def __init__(self, region: QRect, color="#e74c3c"):
        self._wins = []
        r = QRect(region)
        t = self.THICK
        # NOTE: QRect.right()/bottom() are the LAST INSIDE pixel (left+width-1);
        # the bottom/right strips must start one past them or they overlap the
        # region and get captured into the long screenshot (red edge bug).
        bars = (QRect(r.left() - t, r.top() - t, r.width() + 2 * t, t),          # top
                QRect(r.left() - t, r.top() + r.height(), r.width() + 2 * t, t),  # bottom
                QRect(r.left() - t, r.top(), t, r.height()),                     # left
                QRect(r.right() + 1, r.top(), t, r.height()))                    # right
        for rect in bars:
            w = _BorderStrip(rect, color)
            self._wins.append(w)

    def close(self):
        for w in self._wins:
            w.close()

    def deleteLater(self):                              # noqa: N802 - Qt-style API
        for w in self._wins:
            w.deleteLater()
        self._wins = []

    def isVisible(self):                                # noqa: N802 - Qt-style API
        return any(w.isVisible() for w in self._wins)


class _BorderStrip(QtWidgets.QWidget):
    """One thin solid-color always-on-top strip; transparent to the mouse so it
    can never steal wheel events from the capture target."""
    def __init__(self, rect: QRect, color):
        super().__init__()
        self._color = QtGui.QColor(color)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.X11BypassWindowManagerHint | Qt.WindowDoesNotAcceptFocus |
                            Qt.NoDropShadowWindowHint)
        # ARGB windows avoid compositor-generated shadows outside the strips.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(rect)
        self.show()
        self.raise_()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), self._color)


class ScrollHud(QtWidgets.QWidget):
    """PixPin-style HUD for scrolling captures: live stitched thumbnail, current
    height/status, and a stop button. Shared by auto and manual modes; it stays
    outside the selected region so it is never captured."""
    THUMB_W = 150
    THUMB_H = 240

    def __init__(self, region: QRect, on_stop, mode="manual"):
        super().__init__()
        self._mode = mode
        self.setObjectName("ScrollHud")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.X11BypassWindowManagerHint | Qt.NoDropShadowWindowHint |
                            Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        self.thumb = QtWidgets.QLabel()
        self.thumb.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background:#101014;border:1px solid #555;"
                                 "border-radius:4px;color:#888;")
        self.thumb.setText("…")
        lay.addWidget(self.thumb)
        col = QtWidgets.QVBoxLayout(); col.setSpacing(8)
        self.lbl = QtWidgets.QLabel(t("hud_auto" if mode == "auto" else "hud_manual"))
        self.lbl.setWordWrap(True)
        self.btn = QtWidgets.QPushButton(t("hud_stop"))
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.clicked.connect(on_stop)
        col.addWidget(self.lbl)
        col.addStretch(1)
        col.addWidget(self.btn)
        lay.addLayout(col)
        self.setStyleSheet(
            "#ScrollHud{background:#2b2b2b;border:1px solid #c0392b;border-radius:8px;}"
            "QLabel{color:#eee;font-size:13px;}"
            "QPushButton{background:#c0392b;color:white;padding:6px 16px;"
            "border-radius:4px;font-weight:bold;}"
            "QPushButton:hover{background:#e05a4b;}")
        self._region = QRect(region)
        self.adjustSize()
        self._place()

    def paintEvent(self, event):
        # A translucent custom QWidget needs explicit stylesheet painting.
        # Keep the panel opaque while the rounded corners remain transparent.
        option = QtWidgets.QStyleOption()
        option.initFrom(self)
        painter = QtGui.QPainter(self)
        self.style().drawPrimitive(QtWidgets.QStyle.PE_Widget, option, painter, self)

    def _place(self):
        screens = QtWidgets.QApplication.screens()
        r = self._region
        bw, bh = self.width(), self.height()
        self._can_show = False
        for screen in screens:
            vg = screen.geometry()
            candidates = ((r.left(), r.bottom()+12), (r.left(), r.top()-12-bh),
                          (r.right()+12, r.top()), (r.left()-12-bw, r.top()))
            for x, y in candidates:
                x = max(vg.left(), min(x, vg.right()-bw+1))
                y = max(vg.top(), min(y, vg.bottom()-bh+1))
                rect = QRect(x, y, bw, bh)
                if vg.contains(rect) and not rect.intersects(r):
                    self.move(x, y)
                    self._can_show = True
                    return

    def show_on_top(self):
        if self._can_show:
            self.show()
            self.raise_()

    def set_image(self, payload):
        """Show the latest stitched result, letterboxed into the thumbnail.

        payload is (bgr, height_px) or a plain BGR image (manual mode passes the
        full accumulated image directly, so its height is taken from the array).
        """
        try:
            bgr, h = payload if isinstance(payload, tuple) else (payload, payload.shape[0])
            w = bgr.shape[1]
            scale = min(self.THUMB_W / w, self.THUMB_H / bgr.shape[0], 1.0)
            rgb = cv2.resize(bgr, (max(1, int(w * scale)), max(1, int(bgr.shape[0] * scale))))
            pm = QtGui.QPixmap.fromImage(bgr_to_qimage(rgb))
            self.thumb.setPixmap(pm)
            self._h = h
            self._refresh_height()
        except Exception:                              # noqa: BLE001 — HUD never breaks capture
            pass

    def _refresh_height(self):
        base = t("hud_auto" if getattr(self, "_mode", None) == "auto" else "hud_manual")
        self.lbl.setText(f"{base} · {getattr(self, '_h', 0)} px")


# --------------------------------------------------------------------------- #
# Annotation canvas
# --------------------------------------------------------------------------- #
def ungrabbed_dialog(dialog, *args, **kwargs):
    """Let modal dialogs receive keys while a bypass-WM capture owns the keyboard."""
    grabber = QtWidgets.QWidget.keyboardGrabber()
    if grabber is not None:
        grabber.releaseKeyboard()
    try:
        return dialog(*args, **kwargs)
    finally:
        if grabber is not None and grabber.isVisible():
            grabber.grabKeyboard()


class CanvasTextInput(QtWidgets.QLineEdit):
    """Native text/IME editing at an annotation's position, without a dialog."""
    def event(self, event):
        if event.type() == QtCore.QEvent.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape):
            self.parent()._finish_text(event.key() != Qt.Key_Escape)
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if event.reason()!=Qt.PopupFocusReason:
            self.parent()._finish_text()


class AnnotateCanvas(QtWidgets.QWidget):
    """Display the screenshot and allow drawing rectangles/ellipses/arrows/lines/pen/text on it.

    All annotations are stored in image pixel coordinates and scaled by self.scale when displayed;
    on export they're drawn into the original image 1:1 to produce the merged image.
    """
    cropRequested = QtCore.pyqtSignal(object)   # emits the crop rect (image coordinates, QRectF)
    textSelected = QtCore.pyqtSignal(str)       # picktext: words the user dragged over
    picktextNeedsWords = QtCore.pyqtSignal()    # picktext used before word boxes exist
    changed = QtCore.pyqtSignal()              # document content changed

    def __init__(self):
        super().__init__()
        self._text_editor = None
        self._text_index = None
        self.base = None            # QImage, the original screenshot
        self.items = []             # completed annotations
        self.cur = None             # annotation currently being drawn
        self.scale = 1.0
        self.tool = "picktext"
        self._word_boxes = []       # [(QRectF image coords, word)] from the last OCR
        self._sel_from = None       # picktext selection: index range endpoints
        self._sel_to = None
        self._selected_item = None
        self._drag_start = None
        self._drag_item = None
        self._drag_before = None
        self._drag_moved = False
        self._undo_stack = []
        self._redo_stack = []
        self._history_limit = 100
        self.blur_style = "pixelate"
        self.color = QtGui.QColor(255, 40, 40)
        self.width = 3
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.empty_background = "#222228"
        self.empty_text = "#a2a2ad"

    # --- External interface --- #
    def set_image_bgr(self, bgr):
        self._finish_text(False)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        self.base = QtGui.QImage(rgb.data, w, h, 3 * w,
                                 QtGui.QImage.Format_RGB888).copy()
        self.items.clear()
        self.cur = None
        self._word_boxes = []
        self._sel_from = self._sel_to = None
        self._selected_item = None
        self._drag_start = self._drag_item = self._drag_before = None
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._apply_size()
        self.changed.emit()

    def set_word_boxes(self, words):
        """Set the selectable word boxes [(QRectF image coords, word)] from OCR."""
        self._word_boxes = list(words)
        self._sel_from = self._sel_to = None
        self.update()

    def fit_width(self, avail_w):
        if self.base is None:
            return
        w = self.base.width()
        self.scale = min(1.0, max(0.1, (avail_w - 4) / w)) if w else 1.0
        self._apply_size()

    def _apply_size(self):
        if self.base is None:
            return
        self.setFixedSize(int(self.base.width() * self.scale),
                          int(self.base.height() * self.scale))
        self.update()

    def set_tool(self, name):
        self._finish_text()
        self.tool = name
        self._selected_item = None
        self._drag_start = self._drag_item = self._drag_before = None
        self._drag_moved = False
        # picktext shows the I-beam only while hovering a recognized word (updated in
        # mouseMoveEvent); other tools always use the normal pointer.
        self.setCursor(Qt.ArrowCursor)

    def set_color(self, qcolor):
        self.color = QtGui.QColor(qcolor)
        if self._valid_selection():
            item = self.items[self._selected_item]
            if item.get("color") != self.color:
                before = self._content_state()
                item["color"] = QtGui.QColor(self.color)
                self._commit_change(before)

    def set_width(self, w):
        self.width = w
        if self._valid_selection():
            item = self.items[self._selected_item]
            if item.get("width") != w:
                before = self._content_state()
                item["width"] = w
                self._commit_change(before)

    @staticmethod
    def _copy_item(item):
        if not isinstance(item, dict):
            return item
        result = dict(item)
        if "color" in result:
            result["color"] = QtGui.QColor(result["color"])
        for key in ("a", "b"):
            if isinstance(result.get(key), QtCore.QPointF):
                result[key] = QtCore.QPointF(result[key])
        if "pts" in result:
            result["pts"] = [QtCore.QPointF(pt) for pt in result["pts"]]
        return result

    @classmethod
    def _copy_content_state(cls, state):
        base = state.get("base")
        return {
            # QImage values are implicitly shared; later writes detach safely.
            "base": QtGui.QImage(base) if base is not None else None,
            "items": [cls._copy_item(item) for item in state.get("items", [])],
        }

    def _content_state(self):
        return self._copy_content_state({"base": self.base, "items": self.items})

    def snapshot_document(self):
        """Copy the image, annotations, and history for editor handoff."""
        self._finish_text()
        state = self._content_state()
        state["undo"] = [self._copy_content_state(item) for item in self._undo_stack]
        state["redo"] = [self._copy_content_state(item) for item in self._redo_stack]
        return state

    def _restore_content(self, state):
        self._finish_text(False)
        copied = self._copy_content_state(state)
        self.base = copied["base"]
        self.items = copied["items"]
        self.cur = None
        self._word_boxes = []
        self._sel_from = self._sel_to = None
        self._selected_item = None
        self._drag_start = self._drag_item = self._drag_before = None
        self._drag_moved = False
        if self.base is None:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(QtWidgets.QWIDGETSIZE_MAX, QtWidgets.QWIDGETSIZE_MAX)
        else:
            self._apply_size()

    def restore_document(self, state):
        """Restore a state returned by snapshot_document(), including its history."""
        self._restore_content(state)
        self._undo_stack = [self._copy_content_state(item)
                            for item in state.get("undo", [])]
        self._redo_stack = [self._copy_content_state(item)
                            for item in state.get("redo", [])]
        self.update()
        self.changed.emit()

    def _commit_change(self, before):
        self._undo_stack.append(self._copy_content_state(before))
        if len(self._undo_stack) > self._history_limit:
            del self._undo_stack[:-self._history_limit]
        self._redo_stack.clear()
        self.update()
        self.changed.emit()

    def _valid_selection(self):
        return (self._selected_item is not None
                and 0 <= self._selected_item < len(self.items)
                and isinstance(self.items[self._selected_item], dict))

    def undo(self):
        self._finish_text()
        if self._undo_stack:
            current = self._content_state()
            previous = self._undo_stack.pop()
            self._redo_stack.append(current)
            self._restore_content(previous)
            self.update()
            self.changed.emit()
        elif self.items:
            # Keep compatibility with callers that append directly to items.
            current = self._content_state()
            self._redo_stack.append(current)
            self.items.pop()
            self._selected_item = None
            self.update()
            self.changed.emit()

    def redo(self):
        self._finish_text()
        if not self._redo_stack:
            return
        current = self._content_state()
        following = self._redo_stack.pop()
        self._undo_stack.append(current)
        if len(self._undo_stack) > self._history_limit:
            del self._undo_stack[:-self._history_limit]
        self._restore_content(following)
        self.update()
        self.changed.emit()

    def clear_items(self):
        self._finish_text()
        if not self.items:
            return
        before = self._content_state()
        self.items.clear()
        self._selected_item = None
        self._commit_change(before)

    def delete_selected(self):
        if not self._valid_selection():
            return False
        before = self._content_state()
        del self.items[self._selected_item]
        self._selected_item = None
        self._commit_change(before)
        return True

    def crop_image(self, rect):
        """Crop the base image and translate annotations; return whether it changed."""
        self._finish_text()
        if self.base is None:
            return False
        bounds = QtCore.QRectF(rect).normalized().toAlignedRect().intersected(self.base.rect())
        if bounds.width() < 1 or bounds.height() < 1:
            return False
        before = self._content_state()
        self.base = self.base.copy(bounds)
        for item in self.items:
            self._translate_item(item, QtCore.QPointF(-bounds.x(), -bounds.y()))
        self._word_boxes = []
        self._sel_from = self._sel_to = None
        self._selected_item = None
        self._apply_size()
        self._commit_change(before)
        return True

    def clear(self):
        """Clear the canvas (back to the no-screenshot state)."""
        self._finish_text(False)
        if self.base is None and not self.items:
            return
        before = self._content_state()
        self.base = None
        self.items.clear()
        self.cur = None
        self._word_boxes = []
        self._sel_from = self._sel_to = None
        self._selected_item = None
        self._commit_change(before)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(QtWidgets.QWIDGETSIZE_MAX, QtWidgets.QWIDGETSIZE_MAX)
        self.resize(self.parent().size() if self.parent() else QtCore.QSize(400, 300))

    def render_flattened(self):
        """Return a QImage with annotations baked in (1:1 pixels)."""
        self._finish_text()
        if self.base is None:
            return None
        out = self.base.copy()
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        for it in self.items:
            self._draw_item(p, it)
        p.end()
        return out

    # --- Coordinate conversion --- #
    def _to_img(self, pt):
        return QtCore.QPointF(pt.x() / self.scale, pt.y() / self.scale)

    # --- Drawing --- #
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        if self.base is None:
            p.fillRect(self.rect(), QtGui.QColor(self.empty_background))
            p.setPen(QtGui.QColor(self.empty_text))
            p.drawText(self.rect(), Qt.AlignCenter, "No screenshot yet. Use the buttons above to start."
                       if _LANG == "en" else "尚无截图，请使用上方按钮开始截图。")
            return
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        p.scale(self.scale, self.scale)
        p.drawImage(0, 0, self.base)
        for index, it in enumerate(self.items):
            if self._text_editor is None or index != self._text_index:
                self._draw_item(p, it)
        if self.cur:
            self._draw_item(p, self.cur)
        if (self.tool == "select" and self._valid_selection()):
            self._draw_selection(p, self.items[self._selected_item])
        # picktext: cyan highlight under the words the user is dragging over
        if self.tool == "picktext" and self._sel_from is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(10, 132, 255, 110))
            for r, _w in self._selected_words():
                p.drawRect(r)

    def _draw_item(self, p, it):
        pen = QtGui.QPen(it["color"], it["width"], Qt.SolidLine,
                         Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        t = it["type"]
        if t == "rect":
            p.drawRect(QtCore.QRectF(it["a"], it["b"]).normalized())
        elif t == "ellipse":
            p.drawEllipse(QtCore.QRectF(it["a"], it["b"]).normalized())
        elif t == "line":
            p.drawLine(it["a"], it["b"])
        elif t == "arrow":
            self._draw_arrow(p, it["a"], it["b"], it["width"])
        elif t == "pen":
            if len(it["pts"]) > 1:
                p.drawPolyline(QtGui.QPolygonF(it["pts"]))
        elif t == "text":
            f = p.font()
            f.setPixelSize(max(12, it["width"] * 6))
            p.setFont(f)
            p.drawText(it["a"], it["text"])
        elif t == "highlight":
            self._draw_highlight(p, it)
        elif t == "blur":
            self._draw_blur(p, it)
        elif t == "number":
            self._draw_number(p, it)
        elif t == "magnify":
            self._draw_magnify(p, it)
        elif t == "crop":
            # The crop box is only drawn as a dashed preview while dragging; it doesn't go into the final image
            p.setPen(QtGui.QPen(QtGui.QColor(0, 200, 255), max(1, it["width"]),
                                Qt.DashLine))
            p.drawRect(QtCore.QRectF(it["a"], it["b"]).normalized())

    def _draw_highlight(self, p, it):
        r = QtCore.QRectF(it["a"], it["b"]).normalized()
        c = QtGui.QColor(it["color"])
        c.setAlpha(80)                              # semi-transparent, like a highlighter
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRect(r)

    def _draw_blur(self, p, it):
        if self.base is None:
            return
        r = QtCore.QRectF(it["a"], it["b"]).normalized().toRect()
        r = r.intersected(self.base.rect())
        if r.width() < 2 or r.height() < 2:
            return
        sub = self.base.copy(r)
        if it.get("blur_style", "pixelate") == "gaussian":
            bgr = qimage_to_bgr(sub)
            kernel = max(3, int(it.get("width", self.width)) * 4 + 1)
            if kernel % 2 == 0:
                kernel += 1
            blurred = cv2.GaussianBlur(bgr, (kernel, kernel), 0)
            p.drawImage(r.topLeft(), bgr_to_qimage(blurred))
            return
        factor = max(4, it["width"] * 3)            # mosaic block size scales with line width
        small = sub.scaled(max(1, r.width() // factor), max(1, r.height() // factor),
                           Qt.IgnoreAspectRatio, Qt.FastTransformation)
        mosaic = small.scaled(r.width(), r.height(),
                              Qt.IgnoreAspectRatio, Qt.FastTransformation)
        p.drawImage(r.topLeft(), mosaic)

    def _draw_number(self, p, it):
        rad = max(12.0, it["width"] * 4.0)
        c = it["a"]
        p.setBrush(QtGui.QColor(it["color"]))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 2))
        p.drawEllipse(c, rad, rad)
        f = p.font()
        f.setPixelSize(int(rad * 1.1))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor(255, 255, 255))
        p.drawText(QtCore.QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2),
                   Qt.AlignCenter, str(it["n"]))

    def _draw_magnify(self, p, it):
        if self.base is None:
            return
        import math
        c = it["a"]
        rad = math.hypot(it["b"].x() - c.x(), it["b"].y() - c.y())
        if rad < 6:
            return
        zoom = 2.0
        p.save()
        path = QtGui.QPainterPath()
        path.addEllipse(c, rad, rad)
        p.setClipPath(path)
        # Draw the original image zoomed by `zoom`, centered on c
        p.translate(c)
        p.scale(zoom, zoom)
        p.translate(-c)
        p.drawImage(0, 0, self.base)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QtGui.QPen(it["color"], max(2, it["width"])))
        p.drawEllipse(c, rad, rad)

    def _draw_arrow(self, p, a, b, width=None):
        p.drawPath(self._arrow_path(a, b, self.width if width is None else width))

    @staticmethod
    def _arrow_path(a, b, width):
        import math
        path = QtGui.QPainterPath(a)
        path.lineTo(b)
        angle = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = 8 + width * 2
        for delta in (math.radians(150), math.radians(-150)):
            point = QtCore.QPointF(
                b.x() + size * math.cos(angle + delta),
                b.y() + size * math.sin(angle + delta))
            path.moveTo(b)
            path.lineTo(point)
        return path

    @staticmethod
    def _translate_item(item, delta):
        if not isinstance(item, dict):
            return
        for key in ("a", "b"):
            if isinstance(item.get(key), QtCore.QPointF):
                item[key] = item[key] + delta
        if "pts" in item:
            item["pts"] = [point + delta for point in item["pts"]]

    def _item_path(self, item):
        path = QtGui.QPainterPath()
        kind = item.get("type")
        a, b = item.get("a"), item.get("b")
        if kind == "rect":
            path.addRect(QtCore.QRectF(a, b).normalized())
        elif kind == "ellipse":
            path.addEllipse(QtCore.QRectF(a, b).normalized())
        elif kind == "line":
            path.moveTo(a)
            path.lineTo(b)
        elif kind == "arrow":
            path = self._arrow_path(a, b, item.get("width", self.width))
        elif kind == "pen":
            points = item.get("pts", [])
            if points:
                path.moveTo(points[0])
                for point in points[1:]:
                    path.lineTo(point)
        elif kind == "text":
            font = QtGui.QFont(self.font())
            font.setPixelSize(max(12, item.get("width", self.width) * 6))
            path.addText(a, font, item.get("text", ""))
        elif kind in ("highlight", "blur"):
            path.addRect(QtCore.QRectF(a, b).normalized())
        elif kind == "number":
            radius = max(12.0, item.get("width", self.width) * 4.0)
            path.addEllipse(a, radius, radius)
        elif kind == "magnify":
            import math
            radius = math.hypot(b.x() - a.x(), b.y() - a.y())
            path.addEllipse(a, radius, radius)
        return path

    def _item_hit(self, item, point):
        path = self._item_path(item)
        if path.isEmpty():
            return False
        if item.get("type") in ("highlight", "blur", "number", "magnify"):
            if path.contains(point):
                return True
        stroker = QtGui.QPainterPathStroker()
        stroker.setWidth(max(8.0, float(item.get("width", self.width)) + 6.0))
        return stroker.createStroke(path).contains(point)

    def _item_at(self, point):
        for index in range(len(self.items) - 1, -1, -1):
            item = self.items[index]
            if isinstance(item, dict) and self._item_hit(item, point):
                return index
        return None

    def _draw_selection(self, painter, item):
        path = self._item_path(item)
        if path.isEmpty():
            return
        painter.save()
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 200, 255), 2,
                                  Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
        painter.restore()

    # --- Mouse interaction --- #
    def _word_at(self, img_pt):
        for i, (r, _w) in enumerate(self._word_boxes):
            if r.adjusted(-2, -2, 2, 2).contains(img_pt):
                return i
        return None

    def _selected_words(self):
        if self._sel_from is None or self._sel_to is None or not self._word_boxes:
            return []
        a, b = sorted((self._sel_from, self._sel_to))
        return [self._word_boxes[i] for i in range(a, b + 1) if i < len(self._word_boxes)]

    def mousePressEvent(self, e):
        if self.base is None:
            return
        pt = self._to_img(e.pos())
        if self.tool == "picktext":
            if not self._word_boxes:
                self.picktextNeedsWords.emit()
                return
            self._sel_from = self._sel_to = self._word_at(pt)
            self.update()
            return
        if self.tool == "select":
            self._selected_item = self._item_at(pt)
            self._drag_start = pt if self._selected_item is not None else None
            self._drag_item = (self._copy_item(self.items[self._selected_item])
                               if self._selected_item is not None else None)
            self._drag_before = self._content_state() if self._selected_item is not None else None
            self._drag_moved = False
            self.update()
            return
        if self.tool == "text":
            self._start_text(pt)
            return
        if self.tool == "number":
            n = 1 + max([it["n"] for it in self.items
                         if it["type"] == "number"], default=0)
            before = self._content_state()
            self.items.append({"type": "number", "a": pt, "n": n,
                               "color": QtGui.QColor(self.color),
                               "width": self.width})
            self._commit_change(before)
            return
        base = {"color": QtGui.QColor(self.color), "width": self.width}
        if self.tool == "blur":
            base["blur_style"] = self.blur_style
        if self.tool == "pen":
            self.cur = dict(base, type="pen", pts=[pt])
        else:
            self.cur = dict(base, type=self.tool, a=pt, b=pt)
        self.update()

    def mouseMoveEvent(self, e):
        if self.tool == "picktext":
            if e.buttons() & Qt.LeftButton and self._sel_from is not None:
                i = self._word_at(self._to_img(e.pos()))
                if i is not None and i != self._sel_to:
                    self._sel_to = i
                    self.update()
                return
            # not dragging: the I-beam appears only over a selectable word
            over_word = self._word_at(self._to_img(e.pos())) is not None
            want = Qt.IBeamCursor if over_word else Qt.ArrowCursor
            if self.cursor().shape() != want:
                self.setCursor(want)
            return
        if self.tool == "select":
            if (e.buttons() & Qt.LeftButton and self._drag_start is not None
                    and self._selected_item is not None):
                pt = self._to_img(e.pos())
                delta = pt - self._drag_start
                item = self._copy_item(self._drag_item)
                self._translate_item(item, delta)
                self.items[self._selected_item] = item
                self._drag_moved = not delta.isNull()
                self.update()
            return
        if self.cur is None:
            return
        pt = self._to_img(e.pos())
        if self.cur["type"] == "pen":
            self.cur["pts"].append(pt)
        else:
            self.cur["b"] = pt
        self.update()

    def mouseReleaseEvent(self, e):
        if self.tool == "picktext":
            words = [w for _r, w in self._selected_words()]
            self._sel_from = self._sel_to = None
            self.update()
            if words:
                self.textSelected.emit(" ".join(words))
            return
        if self.tool == "select":
            if self._drag_moved and self._drag_before is not None:
                self._commit_change(self._drag_before)
            self._drag_start = self._drag_item = self._drag_before = None
            self._drag_moved = False
            return
        if self.cur is None:
            return
        if self.cur["type"] == "crop":
            r = QtCore.QRectF(self.cur["a"], self.cur["b"]).normalized()
            self.cur = None
            if r.width() >= 4 and r.height() >= 4:
                self.cropRequested.emit(r)
            else:
                self.update()
            return
        before = self._content_state()
        self.items.append(self.cur)
        self.cur = None
        self._commit_change(before)

    def _start_text(self, point, index=None):
        self._finish_text()
        self._text_index = index
        self._text_item = (self._copy_item(self.items[index]) if index is not None else
                           {"type": "text", "a": point, "text": "",
                            "color": QtGui.QColor(self.color), "width": self.width})
        item = self._text_item
        editor = CanvasTextInput(self)
        self._text_editor = editor
        size = max(1, round(max(12, item["width"] * 6) * self.scale))
        editor.setStyleSheet("QLineEdit { background: transparent; border: 1px dashed #808080;"
                            f"color: {item['color'].name()}; font-size: {size}px; padding: 0px; }}")
        editor.setTextMargins(0, 0, 0, 0)
        editor.setText(item["text"])
        metrics = editor.fontMetrics()
        x = max(0, min(round(item["a"].x()*self.scale)-2, self.size().width()-24))
        y = max(0, round(item["a"].y()*self.scale)-metrics.ascent()-2)
        editor.setGeometry(x, y, max(24, self.size().width()-x), metrics.height()+4)
        editor.show(); editor.raise_(); editor.setFocus(Qt.MouseFocusReason)
        editor.selectAll()
        self.update()

    def _finish_text(self, commit=True):
        editor = self._text_editor
        if editor is None:
            return
        self._text_editor = None
        index = self._text_index
        self._text_index = None
        text = editor.text()
        item = self._text_item
        if QtWidgets.QWidget.keyboardGrabber() is editor:
            editor.releaseKeyboard()
        editor.hide(); editor.deleteLater()
        if commit and text != item["text"]:
            before = self._content_state()
            item["text"] = text
            if index is not None:
                if text:
                    self.items[index] = item
                else:
                    del self.items[index]
                    self._selected_item = None
            elif text:
                self.items.append(item)
            self._commit_change(before)
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.base is None or self.tool != "select":
            return
        index = self._item_at(self._to_img(e.pos()))
        if index is None or self.items[index].get("type") != "text":
            return
        self._selected_item = index
        self._start_text(self.items[index]["a"], index)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.delete_selected():
                e.accept()
                return
        if e.key() == Qt.Key_Escape and self._selected_item is not None:
            self._selected_item = None
            self.update()
            e.accept()
            return
        super().keyPressEvent(e)


# --------------------------------------------------------------------------- #
# Floating thumbnail shown after a capture (bottom-left)
# --------------------------------------------------------------------------- #
class CompactStatusLabel(QtWidgets.QLabel):
    """A one-line status hint above its toolbar, without changing toolbar width."""
    def __init__(self, parent, anchor):
        super().__init__(parent)
        self._anchor = anchor
        self.setStyleSheet('QLabel{color:#eeeeef;background:#24242c;'
                           'border:1px solid #626273;border-radius:4px;padding:3px 7px;}')
        self.setWordWrap(False)
        self.setMaximumWidth(420)
        self.hide()

    def setText(self, text):
        super().setText(text)
        if not text:
            self.hide()
            return
        self.setToolTip(text)
        self.adjustSize()
        self.show()
        self.reposition()
        self.raise_()

    def reposition(self):
        if self.isHidden() or self._anchor is None or self.parentWidget() is None:
            return
        self.adjustSize()
        parent = self.parentWidget()
        toolbar_top = parent.mapFromGlobal(self._anchor.mapToGlobal(QtCore.QPoint(0, 0)))
        x = max(0, min(toolbar_top.x(), parent.width() - self.width()))
        y = toolbar_top.y() - self.height() - 4
        if y < 0:
            y = toolbar_top.y() + self._anchor.height() + 4
        y = max(0, min(y, parent.height() - self.height()))
        self.move(x, y)


class EditTools(QtWidgets.QFrame):
    """Shared controls for the existing canvas in pins and capture-time editing."""
    _retired = set()

    _tool_names = ('select', 'picktext', 'rect', 'ellipse', 'arrow', 'line', 'pen',
                   'text', 'number', 'highlight', 'blur', 'gaussian', 'magnify', 'crop')

    def __init__(self, canvas, parent=None, compact=False):
        super().__init__(parent)
        self.compact = bool(compact)
        self._closing = False
        self.canvas = canvas
        self._workers = []
        self._generation = 0
        self.setObjectName('editTools')
        self.setStyleSheet('#editTools{background:#24242c;border:1px solid #626273;border-radius:6px;}'
                           'QToolButton,QPushButton{color:#eeeeef;background:#30303a;padding:4px;}'
                           'QToolButton:checked{background:#6656d9;} QLabel{color:#eeeeef;}'
                           'QMenu{color:#eeeeef;background:#24242c;border:1px solid #626273;}'
                           'QMenu::item{padding:6px 22px;} QMenu::item:selected{background:#6656d9;}')
        if self.compact:
            self.setStyleSheet(self.styleSheet() +
                '#editTools{background:#25272c;border:1px solid #484b53;border-radius:8px;}'
                'QToolButton{background:transparent;border:0;border-radius:7px;padding:0px;color:#f1f3f5;}'
                'QToolButton:hover{background:#3b424d;}'
                'QToolButton:pressed,QToolButton:checked{background:#3c526c;}'
                'QToolButton#captureCopy{background:#355f86;}'
                'QToolButton#captureCopy:hover{background:#4275a2;}')
        layout = QtWidgets.QHBoxLayout(self) if self.compact else QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6) if self.compact else layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(4)
        row = layout if self.compact else QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        if not self.compact:
            layout.addLayout(row)
        self.buttons = {}
        self.group_actions = {}
        self._compact_groups = {}
        self._setting_tool_actions = {}
        self._menu_grabbers = {}
        self.current_tool = None
        self.group = QtWidgets.QButtonGroup(self)
        for name in self._tool_names:
            button = QtWidgets.QToolButton(self)
            icon_name = name
            button.setIcon(self._icon(icon_name))
            button.setIconSize(QtCore.QSize(26, 26) if self.compact else QtCore.QSize(20, 20))
            button.setToolTip(t('a_gaussian_blur' if name == 'gaussian' else 'a_' + name))
            button.setCheckable(True)
            button.setFixedSize(40, 40) if self.compact else button.setFixedSize(30, 30)
            button.clicked.connect(lambda _, n=name: self.set_tool(n))
            self.group.addButton(button)
            self.buttons[name] = button

        self.color = QtWidgets.QToolButton(self)
        self.color.setIcon(swatch_icon(canvas.color))
        self.color.setToolTip(t('dlg_pickcolor'))
        self.color.clicked.connect(self.choose_color)
        self.line_width = QtWidgets.QSpinBox(self)
        self.line_width.setRange(1, 30)
        self.line_width.setValue(canvas.width)
        self.line_width.setFixedWidth(54)
        self.line_width.valueChanged.connect(canvas.set_width)

        self.actions = row if self.compact else QtWidgets.QHBoxLayout()
        self.actions.setSpacing(4)
        if not self.compact:
            layout.addLayout(self.actions)

        if self.compact:
            self.color.hide()
            self._build_compact_tools(row)
            self._build_settings_menu()
        else:
            for name in self._tool_names:
                row.addWidget(self.buttons[name])
            row.addWidget(self.color)
            row.addWidget(self.line_width)
            self.action_button('undo', t('a_undo'), canvas.undo)
            self.action_button('redo', t('a_redo'), canvas.redo)
            self.action_button('clear', t('a_clear'), canvas.clear_items)
        if self.compact:
            self.note = CompactStatusLabel(parent or self, self)
        else:
            self.note = QtWidgets.QLabel(t('edit_hint'))
            self.note.setWordWrap(True)
            self.note.setMaximumWidth(460)
            layout.addWidget(self.note)
        canvas.picktextNeedsWords.connect(self.recognize)
        canvas.textSelected.connect(self.copy_words)
        canvas.cropRequested.connect(canvas.crop_image)
        canvas.changed.connect(self.invalidate_words)
        self.set_tool('arrow')
        self._shortcuts = []
        for key, action in [('Ctrl+Z', canvas.undo), ('Ctrl+Shift+Z',canvas.redo),
                            ('Ctrl+Y',canvas.redo), ('Delete',canvas.delete_selected)]:
            shortcut = QtWidgets.QShortcut(QtGui.QKeySequence(key), parent or self)
            shortcut.activated.connect(action); self._shortcuts.append(shortcut)

    def _new_tool_button(self, name, size=30, hidden=False):
        button = self.buttons[name]
        button.setFixedSize(size, size)
        if hidden:
            button.hide()
        return button

    def _make_tool_action(self, menu, name, group=None):
        label = t('a_gaussian_blur' if name == 'gaussian' else 'a_' + name)
        action = QtWidgets.QAction(self._icon(name),
                                   label, menu)
        action.setObjectName('tool:' + name)
        action.setCheckable(True)
        if group is not None:
            group.addAction(action)
        action.triggered.connect(lambda _checked=False, n=name: self.buttons[n].click())
        return action

    def _build_compact_tools(self, row):
        select = self.buttons['select']
        row.addWidget(select)

        groups = [
            ('shape', 'rect', ('rect', 'ellipse')),
            ('stroke', 'pen', ('pen', 'highlight')),
            ('line', 'arrow', ('arrow', 'line')),
            ('text', 'text', ('text', 'number')),
            ('magnify', 'magnify', ('magnify',)),
            ('mosaic', 'blur', ('blur', 'gaussian')),
        ]
        for key, initial, names in groups:
            button = QtWidgets.QToolButton(self)
            button.setIcon(self._icon(initial))
            button.setIconSize(QtCore.QSize(26, 26))
            button.setText('⌄' if len(names)>1 else '')
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setToolTip(t('a_' + initial))
            button.setFixedSize(46 if len(names)>1 else 40,40)
            button.setCheckable(True)
            menu = QtWidgets.QMenu(self)
            menu.setWindowFlags(menu.windowFlags() | Qt.Popup | Qt.FramelessWindowHint |
                                Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
            menu.setAttribute(Qt.WA_ShowWithoutActivating, False)
            actions = {}
            action_group = QtWidgets.QActionGroup(menu)
            action_group.setExclusive(True)
            for name in names:
                action = self._make_tool_action(menu, name, action_group)
                menu.addAction(action)
                actions[name] = action
            self.group_actions[key] = actions
            self._compact_groups[key] = (button, menu, tuple(names))
            menu.aboutToHide.connect(lambda m=menu: self._menu_hidden(m))
            if len(names)>1:
                button.clicked.connect(lambda _checked=False, b=button, m=menu:
                                       self._popup_compact_menu(b, m))
            else:
                button.clicked.connect(lambda _checked=False,n=initial:self.set_tool(n))
            row.addWidget(button)

        self.undo_button = self.action_button('undo', t('a_undo') + ' · Ctrl+Z', self.canvas.undo)
        settings_button = QtWidgets.QToolButton(self)
        settings_button.setIcon(self._icon('settings'))
        settings_button.setIconSize(QtCore.QSize(26, 26))
        settings_button.setFixedSize(40, 40) if self.compact else button.setFixedSize(30, 30)
        settings_button.setToolTip(t('t_settings'))
        self.settings_menu = QtWidgets.QMenu(self)
        self.settings_menu.setWindowFlags(
            self.settings_menu.windowFlags() | Qt.Popup | Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.settings_menu.aboutToHide.connect(
            lambda m=self.settings_menu: self._menu_hidden(m))
        settings_button.clicked.connect(lambda _checked=False:
                                        self._popup_compact_menu(settings_button, self.settings_menu))
        self.settings_button = settings_button
        row.addWidget(settings_button)
        separator=QtWidgets.QFrame(self)
        separator.setFixedSize(1,26)
        separator.setStyleSheet('background:#535963;border:0;')
        row.addWidget(separator)

        # Keep legacy direct access such as tools.buttons['rect'].click() working;
        # aliases drive the same canvas state but never overlap the compact row.
        for name, tool_button in self.buttons.items():
            if name != 'select':
                tool_button.hide()

    def _build_settings_menu(self):
        menu = self.settings_menu
        color_action = menu.addAction(swatch_icon(self.canvas.color), t('a_color'))
        color_action.setObjectName('setting:color')
        color_action.triggered.connect(self.choose_color)
        width_action = QtWidgets.QWidgetAction(menu)
        width_action.setObjectName('setting:width')
        width_action.setText(t('lab_width'))
        width_widget = QtWidgets.QWidget(menu)
        width_layout = QtWidgets.QHBoxLayout(width_widget)
        width_layout.setContentsMargins(12, 2, 12, 2)
        width_label = QtWidgets.QLabel(t('lab_width'), width_widget)
        width_layout.addWidget(width_label)
        width_layout.addWidget(self.line_width)
        width_action.setDefaultWidget(width_widget)
        menu.addAction(width_action)
        menu.addSeparator()
        for name in ('picktext', 'crop'):
            action = self._make_tool_action(menu, name)
            action.setObjectName('tool:' + name)
            self._setting_tool_actions[name] = action
            menu.addAction(action)
        menu.addSeparator()
        for key, label, icon, callback in (
                ('undo', t('a_undo'), 'undo', self.canvas.undo),
                ('redo', t('a_redo'), 'redo', self.canvas.redo),
                ('clear', t('a_clear'), 'clear', self.canvas.clear_items)):
            action = menu.addAction(self._icon(icon), label)
            action.setObjectName('setting:' + key)
            action.triggered.connect(callback)

    def _popup_compact_menu(self, button, menu):
        old = self._menu_grabbers.get(menu)
        if old is not None:
            return
        # Checkable tool buttons toggle before clicked() runs. Opening a menu
        # must not create a second highlighted tool, especially when canceled.
        self._sync_tool_buttons(self.current_tool)
        grabber = QtWidgets.QWidget.keyboardGrabber()
        if grabber is not None:
            grabber.releaseKeyboard()
        self._menu_grabbers[menu] = grabber
        pos = button.mapToGlobal(QtCore.QPoint(0, button.height()))
        menu.popup(pos)
        if not menu.isVisible():
            self._restore_menu_keyboard(menu)

    def _restore_menu_keyboard(self, menu):
        if menu not in self._menu_grabbers:
            return
        previous = self._menu_grabbers.pop(menu)
        current = QtWidgets.QWidget.keyboardGrabber()
        restore = current is None
        if current is menu or (current is not None and menu.isAncestorOf(current)):
            current.releaseKeyboard()
            restore = True
        if (previous is not None and previous.isVisible() and restore
                and not isinstance(previous, QtWidgets.QMenu)
                and not menu.isAncestorOf(previous)):
            previous.grabKeyboard()

    def _menu_hidden(self, menu):
        self._restore_menu_keyboard(menu)
        self._sync_tool_buttons(self.current_tool)

    def add_setting_action(self, icon, label, action):
        """Add a parent-provided command (such as opening the full editor)."""
        if not self.compact:
            raise RuntimeError('setting-menu actions are only available in compact mode')
        item = self.settings_menu.addAction(self._icon(icon), label)
        item.setObjectName('setting:external')
        item.triggered.connect(action)
        return item

    def _icon(self, name):
        return line_icon(name, color='#eef0f5' if self.compact else '#d2d2da',
                         size=26 if self.compact else 22)

    def action_button(self, icon, label, action):
        button = QtWidgets.QToolButton()
        button.setIcon(self._icon(icon)); button.setToolTip(label)
        button.setFixedSize(40,40) if self.compact else button.setFixedSize(30,30)
        button.setIconSize(QtCore.QSize(26,26) if self.compact else QtCore.QSize(20,20))
        if self.compact and icon == 'copy':
            button.setObjectName('captureCopy')
        button.clicked.connect(action)
        self.actions.addWidget(button)
        return button

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.compact and hasattr(self, 'note'):
            self.note.reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.compact and hasattr(self, 'note'):
            self.note.reposition()

    def set_tool(self, name):
        if name not in self.buttons:
            return
        self.current_tool = name
        if name == 'gaussian':
            self.canvas.blur_style = 'gaussian'
            self.canvas.set_tool('blur')
        else:
            if name == 'blur':
                self.canvas.blur_style = 'pixelate'
            self.canvas.set_tool(name)
        self._sync_tool_buttons(name)
        if name == 'picktext' and not self.canvas._word_boxes:
            self.recognize()

    def _sync_tool_buttons(self, name):
        if name is None:
            return
        for tool_name, button in self.buttons.items():
            button.setChecked(tool_name == name)
        for key, (button, _menu, names) in self._compact_groups.items():
            button.setChecked(name in names)
            if name in names:
                button.setIcon(self._icon(name))
                button.setToolTip(t('a_gaussian_blur' if name == 'gaussian' else 'a_' + name))
            for option, action in self.group_actions.get(key, {}).items():
                action.setChecked(option == name)
        for tool_name, action in self._setting_tool_actions.items():
            action.setChecked(tool_name == name)

    def choose_color(self):
        dialog=QtWidgets.QColorDialog(self.canvas.color,self)
        dialog.setOption(QtWidgets.QColorDialog.DontUseNativeDialog,True)
        if self.window().windowFlags() & Qt.X11BypassWindowManagerHint:
            dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowStaysOnTopHint |
                                  Qt.X11BypassWindowManagerHint)
        accepted=ungrabbed_dialog(dialog.exec_)
        color=dialog.selectedColor() if accepted else QtGui.QColor()
        dialog.deleteLater()
        if color.isValid():
            self.canvas.set_color(color); self.color.setIcon(swatch_icon(color))
            if self.compact:
                for action in self.settings_menu.actions():
                    if action.objectName() == 'setting:color':
                        action.setIcon(swatch_icon(color))
                        break

    def invalidate_words(self):
        self._generation += 1
        self.canvas.set_word_boxes([])

    def recognize(self):
        if self._workers or self.canvas.base is None:
            return
        self.note.setText(t('st_ocr_running'))
        settings = QtCore.QSettings('ScrollShot','ScrollShot')
        generation = self._generation
        worker = OCRWorker(qimage_to_bgr(self.canvas.render_flattened()),
                           settings.value('ocr_lang','chi_sim+eng'),
                           int(settings.value('ocr_psm',6)),
                           settings.value('ocr_enhance', True, type=bool), True, self)
        self._workers.append(worker)
        worker.wordsReady.connect(lambda words: self._words_ready(generation, words))
        worker.result.connect(lambda text, error: self._result(generation, text, error))
        worker.finished.connect(lambda: self._release(worker))
        worker.start()

    def _words_ready(self, generation, words):
        if generation == self._generation:
            self.canvas.set_word_boxes(words)

    def _result(self, generation, text, error):
        if generation == self._generation:
            self.note.setText(error or (t('select_words_hint') if text.strip() else t('st_ocr_none')))

    def _release(self, worker):
        self._workers.remove(worker); worker.deleteLater()
        if self._closing and not self._workers:
            window = self.window()
            self._retired.discard(window)
            window.deleteLater()

    def retire(self):
        self._closing = True
        self._generation += 1
        if self.compact:
            self.note.hide()
            self.note.deleteLater()
        if self._workers:
            self._retired.add(self.window())
            for worker in self._workers:
                worker.requestInterruption()
        else:
            self.window().deleteLater()

    def copy_words(self, text):
        QtWidgets.QApplication.clipboard().setText(text)
        self.note.setText(t('st_copied'))


class CaptureResizeHandle(QtWidgets.QWidget):
    """An edge hit area with one visible corner/midpoint grip."""
    def __init__(self, edge, owner):
        super().__init__(owner)
        self.edge = edge
        self.setMouseTracking(True)
        self.setCursor({'n':Qt.SizeVerCursor,'s':Qt.SizeVerCursor,
                        'w':Qt.SizeHorCursor,'e':Qt.SizeHorCursor,
                        'nw':Qt.SizeFDiagCursor,'se':Qt.SizeFDiagCursor,
                        'ne':Qt.SizeBDiagCursor,'sw':Qt.SizeBDiagCursor}[edge])

    def paintEvent(self, event):
        painter=QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(QtGui.QColor('white'),1))
        painter.setBrush(QtGui.QColor('#249cff'))
        painter.drawEllipse(self.rect().center(),3,3)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            owner=self.parent()
            owner._begin_resize(self.edge)
            owner._loupe_pos=owner.mapFromGlobal(event.globalPos())
            owner.loupe.show();owner.loupe.raise_();owner.loupe.update()

    def mouseMoveEvent(self, event):
        owner=self.parent()
        owner._loupe_pos=owner.mapFromGlobal(event.globalPos())
        if event.buttons() & Qt.LeftButton:
            owner._resize_selection(event.globalPos())
        owner.loupe.update();owner.loupe.show();owner.loupe.raise_()

    def mouseReleaseEvent(self, event):
        self.parent()._end_resize()

    def leaveEvent(self, event):
        if self.parent()._resize_edge is None:
            self.parent().loupe.hide()


class CaptureLoupe(QtWidgets.QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):
        owner=self.parent()
        painter=QtGui.QPainter(self)
        owner._draw_loupe(painter,owner._loupe_pos)


class InlineCaptureEditor(QtWidgets.QWidget):
    """Edit the selected image on the desktop before committing any output."""
    dismissed = pyqtSignal()

    def __init__(self, image, region, on_finish, parent=None, background=None):
        super().__init__(parent, Qt.Window | Qt.FramelessWindowHint |
                         Qt.WindowStaysOnTopHint | Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        if isinstance(parent, QtWidgets.QDialog) and parent.isModal():
            self.setWindowModality(Qt.ApplicationModal)
        self._on_finish = on_finish
        self._confirmed = False
        screen = QtWidgets.QApplication.screenAt(region.center()) if region else None
        screen = screen or QtWidgets.QApplication.primaryScreen()
        self._background = background
        self._resize_edge = None
        self._loupe_pos = QtCore.QPoint()
        self.handles = {}
        bounds = background[1] if background is not None else screen.geometry()
        if background is not None:
            self.bg_img, _, self.dpr = background
        self._region = QRect(region) if region is not None else None
        self.setGeometry(bounds)
        self.canvas = AnnotateCanvas()
        self.canvas.set_image_bgr(image)
        self.viewport = QtWidgets.QScrollArea(self)
        self.viewport.setWidget(self.canvas)
        self.viewport.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.viewport.setStyleSheet('QScrollArea{background:#202026;border:0;border-radius:0;padding:0;}')
        self.tools = EditTools(self.canvas, self, compact=True)
        self.action_buttons = {}
        for icon,label,action in [('scroll',t('cap_manual'),'scroll'),('record',t('cap_record'),'record'),
                                  ('ocr',t('e_ocr'),'ocr'),('pin',t('card_pin'),'pin'),
                                  ('save',t('card_save'),'save'),
                                  ('editor',t('open_editor'),'editor'),
                                  ('close',t('card_close'),'cancel'),
                                  ('copy',t('card_copy'),'copy')]:
            self.action_buttons[action] = self.tools.action_button(icon,label,
                lambda _,a=action:self._action(a))
        self.editor_button = self.action_buttons['editor']
        self.tools.add_setting_action('editor',t('open_editor'),lambda:self.finish('editor'))
        self.tools.adjustSize()
        self.loupe = CaptureLoupe(self)
        self.loupe.setGeometry(self.rect())
        if background is not None:
            self.handles = {edge:CaptureResizeHandle(edge,self)
                            for edge in ('nw','n','ne','e','se','s','sw','w')}
        self.canvas.changed.connect(self._fit_canvas)
        self._fit_canvas()
        for key, action in [('Escape',self.close),('Return',lambda:self.finish('copy')),
                            ('Ctrl+C',lambda:self.finish('copy')),
                            ('Ctrl+S',lambda:self.finish('save'))]:
            shortcut=QtWidgets.QShortcut(QtGui.QKeySequence(key),self)
            shortcut.activated.connect(action)
        QtWidgets.QApplication.instance().focusChanged.connect(self._focus_changed)
        self.show(); self.raise_(); self.activateWindow(); self.setFocus()

    def _focus_changed(self, old, current):
        if self.isVisible() and current is not None and self.isAncestorOf(current) and current.window() is self:
            current.grabKeyboard()

    def _release_keyboard(self):
        grabber = QtWidgets.QWidget.keyboardGrabber()
        if grabber is self or (grabber is not None and self.isAncestorOf(grabber)):
            grabber.releaseKeyboard()

    LOUPE = RegionSelector.LOUPE
    ZOOM = RegionSelector.ZOOM
    _loupe_geometry = RegionSelector._loupe_geometry
    _draw_loupe = RegionSelector._draw_loupe
    _pixel = RegionSelector._pixel

    def _action(self, action):
        if action == 'cancel':
            self.close()
        elif action == 'ocr':
            self.canvas._finish_text()
            self.tools.set_tool('picktext')
        else:
            self.finish(action)

    def _can_resize(self):
        return (self._background is not None and self._region is not None and
                self.canvas.base is not None and
                self.canvas.base.size() == QtCore.QSize(round(self._region.width()*self.dpr),
                                                       round(self._region.height()*self.dpr)))

    def _fit_canvas(self):
        if self.canvas.base is None:
            return
        bounds=self.geometry()
        area=self._region or QRect(bounds.center()-QtCore.QPoint(320,200),QtCore.QSize(640,400))
        area=area.intersected(bounds).translated(-bounds.topLeft())
        if self._can_resize():
            self.viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.viewport.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.viewport.setGeometry(area)
            self.canvas.scale=1.0/self.dpr
            self.canvas._apply_size()
        else:
            self.viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.viewport.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            width=min(max(80,area.width()),max(80,self.width()-20))
            height=min(max(60,area.height()),max(60,self.height()-self.tools.height()-24))
            x=max(10,min(area.x(),self.width()-width-10))
            y=max(10,min(area.y(),self.height()-height-10))
            self.viewport.setGeometry(x,y,width,height)
            self.canvas.fit_width(width)
            if self.canvas.height()>height:
                self.canvas.fit_width(width-self.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent))
        area=self.viewport.geometry()
        screen=QtWidgets.QApplication.screenAt(self.mapToGlobal(area.center()))
        available=(screen.geometry().translated(-bounds.topLeft()).intersected(self.rect())
                   if screen else self.rect())
        tx=max(available.left()+4,min(area.right()+1-self.tools.width(),available.right()-self.tools.width()-3))
        ty=area.bottom()+10
        if ty+self.tools.height()>available.bottom()-3:
            ty=max(available.top()+4,area.top()-self.tools.height()-10)
        self.tools.move(tx,ty); self.tools.raise_()
        x,y,w,h=area.x(),area.y(),area.width(),area.height()
        grips={'nw':QRect(x-5,y-5,10,10),'ne':QRect(x+w-5,y-5,10,10),
               'sw':QRect(x-5,y+h-5,10,10),'se':QRect(x+w-5,y+h-5,10,10),
               'n':QRect(x+5,y-5,max(1,w-10),10),'s':QRect(x+5,y+h-5,max(1,w-10),10),
               'w':QRect(x-5,y+5,10,max(1,h-10)),'e':QRect(x+w-5,y+5,10,max(1,h-10))}
        for edge,handle in self.handles.items():
            handle.setGeometry(grips[edge]);handle.setVisible(self._can_resize());handle.raise_()
        self.action_buttons['scroll'].setEnabled(self._can_resize())
        self.action_buttons['record'].setEnabled(self._can_resize())
        self.update()

    def _begin_resize(self, edge):
        self.canvas._finish_text()
        self._resize_edge=edge
        self._resize_start=QRect(self._region)
        self._resize_document=self.canvas.snapshot_document()

    def _resize_selection(self, global_pos):
        if self._resize_edge is None:
            return
        r=QRect(self._resize_start)
        bounds=self._background[1]
        x=max(bounds.left(),min(global_pos.x(),bounds.right()))
        y=max(bounds.top(),min(global_pos.y(),bounds.bottom()))
        if 'w' in self._resize_edge: r.setLeft(min(x,r.right()-8))
        if 'e' in self._resize_edge: r.setRight(max(x,r.left()+8))
        if 'n' in self._resize_edge: r.setTop(min(y,r.bottom()-8))
        if 's' in self._resize_edge: r.setBottom(max(y,r.top()+8))
        self._region=r
        local=r.translated(-bounds.topLeft())
        base=self.bg_img.copy(round(local.x()*self.dpr),round(local.y()*self.dpr),
                              round(local.width()*self.dpr),round(local.height()*self.dpr))
        offset=QtCore.QPointF((self._resize_start.x()-r.x())*self.dpr,
                             (self._resize_start.y()-r.y())*self.dpr)
        def reframe(state):
            result=self.canvas._copy_content_state(state)
            result['base']=base
            for item in result['items']:
                self.canvas._translate_item(item,offset)
            return result
        state=reframe(self._resize_document)
        state['undo']=[reframe(value) for value in self._resize_document['undo']]
        state['redo']=[reframe(value) for value in self._resize_document['redo']]
        self.canvas.restore_document(state)
        self._loupe_pos=self.mapFromGlobal(global_pos)
        self.loupe.update()

    def _end_resize(self):
        self._resize_edge=None
        self.loupe.hide()

    def paintEvent(self, event):
        painter=QtGui.QPainter(self)
        if self._background is not None:
            painter.drawImage(self.rect(),self.bg_img)
        painter.fillRect(self.rect(),QtGui.QColor(0,0,0,110))
        painter.setPen(QtGui.QPen(QtGui.QColor('#249cff'),2))
        painter.drawRect(self.viewport.geometry().adjusted(-1,-1,1,1))

    def showEvent(self, event):
        super().showEvent(event)
        self.grabKeyboard()

    def finish(self, action):
        if self._confirmed:
            return
        # Release the X11 keyboard grab before any native save dialog is opened.
        self._release_keyboard()
        if action in ('save', 'record'):
            self.hide()  # Native dialogs belong to the window-manager layer.
        if self._on_finish(action,self.canvas):
            self._confirmed=True
            self.close()
        else:
            self.show();self.raise_();self.activateWindow();self.grabKeyboard()

    def closeEvent(self, event):
        self._release_keyboard()
        self.dismissed.emit()
        self.tools.retire()
        event.accept()


class FloatingThumbnail(QtWidgets.QWidget):
    """A small thumbnail floating at the bottom-left after a capture: drag it elsewhere, click to edit, copy/save/pin.

    Callbacks are injected from outside: on_edit / on_copy / on_save / on_pin.
    """
    THUMB_W = 340
    AUTO_HIDE_MS = 8000

    def __init__(self, qimage, on_edit, on_copy, on_save, on_pin):
        super().__init__()
        self._img = qimage
        self._on_edit, self._on_copy = on_edit, on_copy
        self._on_save, self._on_pin = on_save, on_pin
        self._press_pos = None
        self._dragging = False

        # Managed by the window manager (don't bypass the WM): this way, during drag export the WM can
        # properly take over/release the mouse pointer grab, avoiding a stuck drag that "freezes" the whole desktop
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_AlwaysShowToolTips)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        # Thumbnail
        pix = QtGui.QPixmap.fromImage(qimage)
        if pix.width() > self.THUMB_W:
            pix = pix.scaledToWidth(self.THUMB_W, Qt.SmoothTransformation)
        if pix.height() > 400:
            pix = pix.scaledToHeight(400, Qt.SmoothTransformation)
        self._thumb = QtWidgets.QLabel()
        self._thumb.setPixmap(pix)
        self._thumb.setStyleSheet("border:2px solid #444;border-radius:4px;background:#000;")
        lay.addWidget(self._thumb)

        # Action bar — one segmented bar (PixPin-style): icon buttons in a
        # single rounded strip divided by hairlines, instead of loose buttons.
        bar = QtWidgets.QFrame()
        bar.setObjectName("cardBar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for i, (icon_name, tip_key, cb) in enumerate([
                ("pen", "card_edit", self._do_edit),
                ("copy", "card_copy", self._do_copy),
                ("save", "card_save", self._do_save),
                ("pin", "card_pin", self._do_pin),
                ("close", "card_close", self._do_close)]):
            if i:
                sep = QtWidgets.QFrame()
                sep.setFrameShape(QtWidgets.QFrame.VLine)
                sep.setObjectName("cardSep")
                row.addWidget(sep)
            btn = QtWidgets.QToolButton()
            btn.setIcon(line_icon(icon_name, size=22))
            btn.setIconSize(QtCore.QSize(22, 22))
            btn.setToolTip(t(tip_key))
            btn.setFixedSize(44, 34)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(cb)
            row.addWidget(btn)
        lay.addWidget(bar, alignment=Qt.AlignHCenter)

        self.setStyleSheet(
            "FloatingThumbnail{background:transparent;}"
            "QFrame#cardBar{background:#2b2b2b;border-radius:6px;}"
            "QFrame#cardBar QToolButton{background:transparent;border:none;}"
            "QFrame#cardBar QToolButton:hover{background:#0a84ff;}"
            "QFrame#cardSep{background:#4a4a52;max-width:1px;border:none;}")
        self.adjustSize()
        self._place()

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timer.start(self.AUTO_HIDE_MS)

    def _place(self):
        vg = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.move(vg.left() + 20, vg.bottom() - self.height() - 20)

    # Pause auto-hide while hovered
    def enterEvent(self, _):
        self._timer.stop()

    def leaveEvent(self, _):
        self._timer.start(self.AUTO_HIDE_MS)

    # Drag: small movement = click to open editor; large drag = drag out image/file
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press_pos = e.pos()
            self._dragging = False

    def mouseMoveEvent(self, e):
        if self._press_pos is None:
            return
        if (e.pos() - self._press_pos).manhattanLength() < \
                QtWidgets.QApplication.startDragDistance():
            return
        self._dragging = True
        self._press_pos = None              # prevent this drag from later being treated as a click
        self._timer.stop()
        try:
            # Write a temp file, providing both image data and a file URL for broader target-app compatibility
            import tempfile, os
            path = os.path.join(tempfile.gettempdir(), "scrollshot_drag.png")
            self._img.save(path)
            mime = QtCore.QMimeData()
            mime.setImageData(self._img)
            mime.setUrls([QtCore.QUrl.fromLocalFile(path)])
            drag = QtGui.QDrag(self)
            drag.setMimeData(mime)
            thumb = self._thumb.pixmap()
            if thumb:
                drag.setPixmap(thumb.scaledToWidth(120, Qt.SmoothTransformation))
            drag.exec_(Qt.CopyAction)
        except Exception:                   # noqa: BLE001
            pass                            # a failed drag isn't fatal; never get stuck

    def mouseReleaseEvent(self, e):
        if self._press_pos is not None and not self._dragging:
            self._do_edit()
        self._press_pos = None

    # Actions
    def _do_edit(self):
        self.close(); self._on_edit()

    def _do_copy(self):
        self._on_copy()
        self._do_close()

    def _do_save(self):
        self._timer.stop(); self._on_save()

    def _do_pin(self):
        self._on_pin(); self._do_close()

    def _do_close(self):
        self._timer.stop(); self.close()


# --------------------------------------------------------------------------- #
# Pin image to screen (sticky image)
# --------------------------------------------------------------------------- #
class PinnedImage(QtWidgets.QWidget):
    """Pin a screenshot as an always-on-top floating window: drag to move, wheel to zoom
    (Ctrl+wheel adjusts opacity), double-click to close, right-click for actions
    (copy / OCR / click-through / reset opacity)."""
    _pins = []                                  # hold references to prevent GC

    def __init__(self, qimage, on_ocr=None, on_edit=None):
        super().__init__()
        PinnedImage._pins.append(self)
        self._orig = QtGui.QPixmap.fromImage(qimage)
        self._scale = 1.0
        self._drag_off = None
        self._on_ocr = on_ocr                   # callback(BGR numpy), MainWindow._pin_ocr
        self._on_edit = on_edit
        self._editing = False
        self.tools = None
        self._opacity = 1.0
        self._click_through = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setCursor(Qt.OpenHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)      # so Esc reaches this frameless Tool window
        # Initial size: no more than 60% of the screen
        sg = QtWidgets.QApplication.primaryScreen().availableGeometry()
        maxw, maxh = int(sg.width() * 0.6), int(sg.height() * 0.6)
        if self._orig.width() > maxw or self._orig.height() > maxh:
            self._scale = min(maxw / self._orig.width(),
                              maxh / self._orig.height())
        self._lbl = QtWidgets.QLabel(self)
        self._lbl.setStyleSheet("border:1px solid #0a84ff;")
        self.canvas = AnnotateCanvas()
        self.canvas.setParent(self)
        self.canvas.set_image_bgr(qimage_to_bgr(qimage))
        self.canvas.hide()
        self.canvas.changed.connect(self._document_changed)
        self._apply()
        self.move(sg.center().x() - self.width() // 2,
                  sg.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()                          # grab keyboard so Esc closes the pin

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.setFocus()                          # re-grab after a click on the child label

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
        elif e.key() == Qt.Key_E:
            self.set_editing(not self._editing)
        elif e.key() == Qt.Key_O and self._on_ocr is not None:
            self._do_ocr()
        else:
            super().keyPressEvent(e)

    def _do_ocr(self):
        if self._on_ocr is not None:
            self._on_ocr(qimage_to_bgr(self._orig.toImage()))

    def _nudge_opacity(self, up):
        self._opacity = max(0.3, min(1.0, round(self._opacity + (0.05 if up else -0.05), 2)))
        self.setWindowOpacity(self._opacity)

    def _reset_opacity(self):
        self._opacity = 1.0
        self.setWindowOpacity(1.0)

    def _toggle_click_through(self, on=None):
        """Mouse pass-through via XShape (empty ShapeInput). State tracks intent;
        a missing SHAPE extension/offscreen session fails silently. The tray offers
        an escape hatch because while on, this window receives no input at all."""
        self._click_through = (not self._click_through) if on is None else bool(on)
        try:
            _x11_set_input_passthrough(self.winId(), self._click_through)
        except Exception:                       # noqa: BLE001
            pass

    def _document_changed(self):
        self._orig = QtGui.QPixmap.fromImage(self.canvas.render_flattened())
        self._apply()

    def set_editing(self, editing=True, tool='select'):
        self._editing = editing
        if editing and self.tools is None:
            self.tools = EditTools(self.canvas, self, compact=True)
            self.tools.action_button('ocr', t('e_ocr'), lambda:self.tools.set_tool('picktext'))
            self.tools.action_button('save', t('card_save'), self._save_image)
            if self._on_edit:
                self.editor_button = self.tools.action_button(
                    'editor', t('open_editor'), self._open_in_editor)
                self.tools.add_setting_action('editor', t('open_editor'), self._open_in_editor)
            self.tools.action_button(
                'close', t('finish_edit'), lambda: self.set_editing(False))
            self.tools.action_button('copy', t('card_copy'), self._copy_image)
            self.tools.adjustSize()
        self._lbl.setVisible(not editing)
        self.canvas.setVisible(editing)
        if self.tools:
            self.tools.setVisible(editing)
            for shortcut in self.tools._shortcuts:
                shortcut.setEnabled(editing)
            if editing:
                self.tools.set_tool(tool)
            else:
                self.canvas._finish_text()
                self.tools._generation += 1
                for worker in self.tools._workers:
                    worker.requestInterruption()
                self.tools.note.setText('')
        self._apply()

    def _copy_image(self):
        QtWidgets.QApplication.clipboard().setImage(self.canvas.render_flattened())

    def _save_image(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,t('dlg_save'),'Kapture.png','PNG (*.png);;JPEG (*.jpg)')
        if path and not self.canvas.render_flattened().save(path):
            QtWidgets.QMessageBox.warning(self,t('dlg_save'),t('save_failed'))

    def _open_in_editor(self):
        if self._on_edit:
            self._on_edit(self.canvas.snapshot_document())

    def _apply(self):
        pix = self._orig.scaled(
            max(1, int(self._orig.width() * self._scale)),
            max(1, int(self._orig.height() * self._scale)),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._lbl.setPixmap(pix)
        self._lbl.resize(pix.size())
        if self._editing:
            self.canvas.scale = self._scale
            self.canvas._apply_size()
            self.canvas.move(0,0)
            self.tools.move(0,self.canvas.height())
            self.resize(max(self.canvas.size().width(),self.tools.width()),
                        self.canvas.height()+self.tools.height())
        else:
            self.resize(pix.size())
        screen = QtGui.QGuiApplication.screenAt(self.frameGeometry().topLeft())
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            max_x = max(available.left(), available.right() - self.width() + 1)
            max_y = max(available.top(), available.bottom() - self.height() + 1)
            self.move(min(max(self.x(), available.left()), max_x),
                      min(max(self.y(), available.top()), max_y))

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self._nudge_opacity(e.angleDelta().y() > 0)
            return
        self._scale *= 1.1 if e.angleDelta().y() > 0 else 0.9
        self._scale = max(0.1, min(5.0, self._scale))
        self._apply()

    def mousePressEvent(self, e):
        if self._editing:
            return
        if e.button() == Qt.LeftButton:
            self._drag_off = e.globalPos() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag_off is not None:
            self.move(e.globalPos() - self._drag_off)

    def mouseReleaseEvent(self, e):
        self._drag_off = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        if not self._editing:
            self.close()

    def _build_menu(self):
        m = QtWidgets.QMenu(self)
        m.addAction(t('pin_edit'),lambda:self.set_editing(not self._editing))
        m.addAction(t('pin_select_text'),lambda:self.set_editing(True,'picktext'))
        m.addAction(t('card_copy'),self._copy_image)
        m.addAction(t('card_save'),self._save_image)
        if self._on_edit:
            m.addAction(t('open_editor'),self._open_in_editor)
        if self._on_ocr is not None:
            m.addAction(t("p_ocr"), self._do_ocr)
        m.addAction(t("p_clickthrough"), lambda: self._toggle_click_through(True))
        m.addAction(t("p_reset_opacity"), self._reset_opacity)
        m.addAction(t("card_close"), self.close)
        return m

    def contextMenuEvent(self, e):
        self._build_menu().exec_(e.globalPos())

    def closeEvent(self, e):
        if self in PinnedImage._pins:
            PinnedImage._pins.remove(self)
        if self.tools:
            self.tools.retire()
        else:
            self.deleteLater()
        e.accept()


# --------------------------------------------------------------------------- #
# Window picker (click any window to capture it)
# --------------------------------------------------------------------------- #
class WindowPicker(QtCore.QObject):
    """Listen for a single mouse click: left button picks the geometry of the window under the pointer, right button cancels."""
    picked = pyqtSignal(object)             # (x,y,w,h) or None (cancelled)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None

    def start(self):
        from pynput import mouse

        def on_click(x, y, button, pressed):
            if not pressed:
                return
            if str(button) == "Button.left":
                self.picked.emit(get_window_geom_at_pointer())
                return False                # stop listening
            if str(button) == "Button.right":
                self.picked.emit(None)
                return False
        self._listener = mouse.Listener(on_click=on_click)
        self._listener.start()


def _make_hint(text):
    """A small always-on-top hint bar (centered at the top of the screen)."""
    w = QtWidgets.QLabel(text)
    w.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                     Qt.X11BypassWindowManagerHint)
    w.setStyleSheet("background:#2b2b2b;color:#fff;padding:8px 16px;"
                    "border:1px solid #0a84ff;border-radius:6px;font-size:14px;")
    w.adjustSize()
    sg = QtWidgets.QApplication.primaryScreen().availableGeometry()
    w.move(sg.center().x() - w.width() // 2, sg.top() + 40)
    return w


# --------------------------------------------------------------------------- #
# Screen recording: ffmpeg x11grab
# --------------------------------------------------------------------------- #
class RecordingOptions(QtWidgets.QWidget):
    """Shared defaults and per-capture options; resolution always preserves aspect ratio."""
    def __init__(self, settings, size=None, parent=None):
        super().__init__(parent)
        self.size = size
        form = QtWidgets.QFormLayout(self)
        self._form = form
        self.fps = QtWidgets.QSpinBox(); self.fps.setRange(1, 60)
        self.fps.setValue(settings.value('record_fps', 15, type=int))
        self.fps.setSuffix(' fps')
        self.resolution = QtWidgets.QComboBox()
        for zh, en, value in [('原始大小', 'Original', 'original'),
                              ('适配 1920 × 1080', 'Fit 1920 × 1080', '1080'),
                              ('适配 1280 × 720', 'Fit 1280 × 720', '720'),
                              ('50%', '50%', 'half'), ('25%', '25%', 'quarter'),
                              ('自定义宽度', 'Custom width', 'custom')]:
            self.resolution.addItem(zh if _LANG == 'zh' else en, value)
        self.resolution.setCurrentIndex(max(0, self.resolution.findData(
            settings.value('record_resolution', 'original'))))
        self.width = QtWidgets.QSpinBox(); self.width.setRange(2, 7680); self.width.setSingleStep(2)
        self.width.setValue(settings.value('record_width', 1280, type=int)); self.width.setSuffix(' px')
        self.countdown = QtWidgets.QSpinBox(); self.countdown.setRange(0, 30)
        self.countdown.setValue(settings.value('record_countdown', 3, type=int))
        self.duration = QtWidgets.QSpinBox(); self.duration.setRange(0, 3600)
        self.duration.setValue(settings.value('record_duration', 0, type=int))
        self.duration.setSpecialValueText('手动停止' if _LANG == 'zh' else 'Manual stop')
        for spin in (self.countdown, self.duration):
            spin.setSuffix(' 秒' if _LANG == 'zh' else ' s')
        self.preview = QtWidgets.QLabel()
        for zh, en, widget in [('帧率', 'Frame rate', self.fps), ('分辨率', 'Resolution', self.resolution),
                              ('输出宽度', 'Output width', self.width), ('开始倒计时', 'Countdown', self.countdown),
                              ('录制时长', 'Duration', self.duration)]:
            form.addRow(zh if _LANG == 'zh' else en, widget)
        form.addRow(self.preview)
        self.resolution.currentIndexChanged.connect(self._update_preview)
        self.width.valueChanged.connect(self._update_preview)
        self._update_preview()

    def output_size(self):
        if self.size is None:
            return None
        w, h = self.size
        mode = self.resolution.currentData()
        scale = {'half': .5, 'quarter': .25}.get(mode, 1.)
        if mode in ('1080', '720'):
            mw, mh = (1920, 1080) if mode == '1080' else (1280, 720)
            scale = min(1., mw / w, mh / h)
        elif mode == 'custom':
            scale = self.width.value() / w
        return max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)

    def _update_preview(self):
        custom = self.resolution.currentData() == 'custom'
        self.width.setVisible(custom)
        self._form.labelForField(self.width).setVisible(custom)
        size = self.output_size()
        self.preview.setText((('输出：' if _LANG == 'zh' else 'Output: ') + f'{size[0]} × {size[1]}')
                             if size else ('分辨率保持区域比例' if _LANG == 'zh' else 'Aspect ratio is preserved'))

    def values(self):
        return dict(fps=self.fps.value(), output_size=self.output_size(),
                    duration=self.duration.value(), countdown=self.countdown.value())

    def save(self, settings):
        for key, value in [('fps', self.fps.value()), ('resolution', self.resolution.currentData()),
                           ('width', self.width.value()), ('duration', self.duration.value()),
                           ('countdown', self.countdown.value())]:
            settings.setValue('record_' + key, value)


class RecordSetupBar(QtWidgets.QDialog):
    """Region-adjacent recording controls; reuse RecordingOptions for values/defaults."""
    _place = ScrollHud._place
    paintEvent = ScrollHud.paintEvent

    def __init__(self, settings, size, region=None, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName('recordSetupBar')
        self.setWindowTitle('录屏' if _LANG == 'zh' else 'Recording')
        self._region = QRect(region) if region is not None else QRect()
        theme = settings.value('ui_theme', 'dark')
        if theme == 'system': theme = 'dark' if system_prefers_dark() else 'light'
        colors = THEMES.get(theme, THEMES['dark'])
        inherited = parent.styleSheet() if parent is not None else ''
        self.setStyleSheet(inherited + f'''
            QDialog#recordSetupBar {{ background:{colors['panel']}; border:1px solid {colors['edge']}; border-radius:9px; }}
            QToolButton#recordOption {{ padding:0px 18px 0px 8px; min-height:36px; }}
            QToolButton#recordOption::menu-indicator {{ subcontrol-origin:padding;
                subcontrol-position:center right; right:6px; width:6px; height:6px; }}
            QToolButton#recordStart {{ background:{colors['accent']}; color:{colors['on_accent']};
                padding:0px 12px; min-height:36px; }}
        ''')
        self.options = RecordingOptions(settings, size, self)
        self.options.hide()
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(8, 6, 8, 6); row.setSpacing(4)
        self.fps_button = self._number_menu(row, self.options.fps, (10, 15, 24, 30, 60),
                                            '帧率' if _LANG == 'zh' else 'Frame rate',
                                            lambda value: f'{value} fps')
        self.resolution_button = self._menu_button(row, '分辨率' if _LANG == 'zh' else 'Resolution')
        resolution_menu = self.resolution_button.menu()
        self._resolution_actions = []
        for index in range(self.options.resolution.count() - 1):
            action = resolution_menu.addAction(self.options.resolution.itemText(index))
            action.setCheckable(True)
            action.triggered.connect(lambda _, i=index: self.options.resolution.setCurrentIndex(i))
            self._resolution_actions.append(action)
        resolution_menu.addSeparator()
        custom = QtWidgets.QWidget(); form = QtWidgets.QHBoxLayout(custom)
        form.addWidget(QtWidgets.QLabel('自定义宽度' if _LANG == 'zh' else 'Custom width'))
        self.custom_width = QtWidgets.QSpinBox(); self.custom_width.setRange(2, 7680)
        self.custom_width.setSingleStep(2); self.custom_width.setSuffix(' px')
        self.custom_width.setValue(self.options.width.value()); form.addWidget(self.custom_width)
        custom_action = QtWidgets.QWidgetAction(resolution_menu); custom_action.setDefaultWidget(custom)
        resolution_menu.addAction(custom_action)
        self.custom_width.valueChanged.connect(self._custom_resolution)
        # Enter also selects an unchanged custom value.
        self.custom_width.lineEdit().returnPressed.connect(lambda: self._custom_resolution(self.custom_width.value()))
        self.custom_width.lineEdit().returnPressed.connect(resolution_menu.close)
        self.options.resolution.currentIndexChanged.connect(self._update_resolution)
        self.options.width.valueChanged.connect(self._update_resolution)
        self._update_resolution()
        self.countdown_button = self._number_menu(row, self.options.countdown, (0, 3, 5, 10),
            '开始倒计时' if _LANG == 'zh' else 'Countdown',
            lambda value: (f'{value} 秒后开始' if value else '无倒计时') if _LANG == 'zh'
                          else (f'Start in {value}s' if value else 'No countdown'))
        self.duration_button = self._number_menu(row, self.options.duration, (0, 5, 10, 15, 30, 60),
            '录制时长' if _LANG == 'zh' else 'Duration',
            lambda value: (f'录制 {value} 秒' if value else '手动停止') if _LANG == 'zh'
                          else (f'Record {value}s' if value else 'Manual stop'))
        separator = QtWidgets.QFrame(); separator.setFrameShape(QtWidgets.QFrame.VLine)
        separator.setFixedHeight(24); row.addWidget(separator)
        self.start_button = QtWidgets.QToolButton(); self.start_button.setObjectName('recordStart')
        self.start_button.setText('开始录制' if _LANG == 'zh' else 'Start')
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.clicked.connect(self.accept); row.addWidget(self.start_button)
        self.cancel_button = QtWidgets.QToolButton()
        self.cancel_button.setIcon(line_icon('close', size=22, color=colors['icon']))
        self.cancel_button.setIconSize(QtCore.QSize(22, 22)); self.cancel_button.setFixedSize(36, 36)
        self.cancel_button.setToolTip('取消录屏 · Esc' if _LANG == 'zh' else 'Cancel recording · Esc')
        self.cancel_button.clicked.connect(self.reject); row.addWidget(self.cancel_button)
        self._reposition()

    def _reposition(self):
        self.adjustSize()
        self._place()
        if not self._can_show:
            # Full-screen capture has no outside space; setup disappears before capture starts.
            screen = QtWidgets.QApplication.screenAt(self._region.center()) or QtWidgets.QApplication.primaryScreen()
            bounds = screen.availableGeometry()
            self.move(bounds.center().x() - self.width() // 2, bounds.bottom() - self.height() - 12)

    def _menu_button(self, row, tooltip):
        button = QtWidgets.QToolButton(); button.setObjectName('recordOption')
        button.setToolTip(tooltip); button.setCursor(Qt.PointingHandCursor)
        button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        button.setMenu(QtWidgets.QMenu(button)); row.addWidget(button)
        button.menu().aboutToHide.connect(self._reposition)
        return button

    def _number_menu(self, row, control, presets, tooltip, label):
        button = self._menu_button(row, tooltip)
        menu = button.menu(); actions = []
        for value in presets:
            action = menu.addAction(label(value)); action.setCheckable(True)
            action.triggered.connect(lambda _, n=value: control.setValue(n))
            actions.append((value, action))
        menu.addSeparator()
        custom = QtWidgets.QWidget(); form = QtWidgets.QHBoxLayout(custom)
        form.addWidget(QtWidgets.QLabel('自定义' if _LANG == 'zh' else 'Custom'))
        spin = QtWidgets.QSpinBox(); spin.setRange(control.minimum(), control.maximum())
        spin.setValue(control.value()); spin.setSuffix(control.suffix())
        if control.specialValueText(): spin.setSpecialValueText(control.specialValueText())
        form.addWidget(spin)
        action = QtWidgets.QWidgetAction(menu); action.setDefaultWidget(custom); menu.addAction(action)
        spin.valueChanged.connect(control.setValue)
        spin.lineEdit().returnPressed.connect(menu.close)
        def update(value):
            button.setText(label(value))
            spin.setValue(value)
            for number, candidate in actions: candidate.setChecked(number == value)
        control.valueChanged.connect(update); update(control.value())
        button.custom_input = spin
        return button

    def _custom_resolution(self, width):
        self.options.width.setValue(width)
        self.options.resolution.setCurrentIndex(self.options.resolution.findData('custom'))

    def _update_resolution(self):
        size = self.options.output_size()
        self.resolution_button.setText(f'{size[0]} × {size[1]}')
        for index, action in enumerate(self._resolution_actions):
            action.setChecked(index == self.options.resolution.currentIndex())


class RecordingExporter(QtCore.QObject):
    progress = pyqtSignal(int)
    completed = pyqtSignal(str, str)

    def __init__(self, source, fps, duration, parent=None):
        super().__init__(parent)
        self.source, self.fps, self.duration = source, fps, duration
        self.proc = QtCore.QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read_progress)
        self.proc.readyReadStandardError.connect(self._read_error)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._process_error)
        self._buffer = ''; self._error = ''; self._done = True

    def start(self, path, format_name):
        from pathlib import Path
        import uuid
        self.path, self.format_name = path, format_name
        target = Path(path)
        self.staging = str(target.with_name('.' + target.stem + '-' + uuid.uuid4().hex + target.suffix))
        self._buffer = ''; self._error = ''; self._done = False
        args = ['-y', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats', '-i', self.source]
        if format_name == 'gif':
            filters = f'fps={self.fps},split[a][b];[a]palettegen[p];[b][p]paletteuse'
            args += ['-filter_complex_threads', '1', '-filter_complex', filters, '-loop', '0', '-f', 'gif']
        else:
            args += ['-map', '0:v:0', '-c:v', 'copy']
            if format_name == 'mp4':
                args += ['-movflags', '+faststart']
            args += ['-f', 'mp4' if format_name == 'mp4' else 'matroska']
        self.progress.emit(0 if self.duration > 0 else -1)
        self.proc.start('ffmpeg', args + [self.staging])

    def _read_progress(self):
        self._buffer += bytes(self.proc.readAllStandardOutput()).decode(errors='replace')
        lines = self._buffer.split('\n'); self._buffer = lines.pop()
        for line in lines:
            key, _, value = line.partition('=')
            if key == 'out_time_us' and self.duration > 0:
                try: self.progress.emit(min(99, max(0, round(int(value) / 1000000 / self.duration * 100))))
                except ValueError: pass

    def _read_error(self):
        self._error = (self._error + bytes(self.proc.readAllStandardError()).decode(errors='replace'))[-3000:]

    def _process_error(self, error):
        if error == QtCore.QProcess.FailedToStart:
            self._finish(self.proc.errorString())

    def _finished(self, code, status):
        import os
        self._read_progress(); self._read_error()
        error = self._error if code != 0 or status != QtCore.QProcess.NormalExit else ''
        if code != 0 or status != QtCore.QProcess.NormalExit or not Recorder._valid_file(self.staging):
            self._finish(error or ('导出失败' if _LANG == 'zh' else 'Export failed'))
            return
        try: os.replace(self.staging, self.path)
        except OSError as exc: self._finish(str(exc)); return
        self._finish('')

    def _finish(self, error):
        from pathlib import Path
        if self._done: return
        self._done = True
        if error:
            try: Path(self.staging).unlink(missing_ok=True)
            except OSError: pass
        else:
            self.progress.emit(100)
        self.completed.emit('' if error else self.path, error)


class RecordExportDialog(QtWidgets.QDialog):
    def __init__(self, source, fps, duration, directory, filename, parent=None):
        super().__init__(parent)
        if parent is not None:
            self.setStyleSheet(parent.styleSheet())
        self.setWindowTitle('导出录屏' if _LANG == 'zh' else 'Export recording')
        self.setMinimumWidth(420)
        self.directory, self.filename = directory, filename
        self.saved_paths = []
        self.busy = False
        layout = QtWidgets.QVBoxLayout(self)
        self.format = QtWidgets.QComboBox()
        for label, value in [('MP4 · 视频', 'mp4'), ('GIF · 动图', 'gif'), ('MKV · 视频', 'mkv')]:
            self.format.addItem(label if _LANG == 'zh' else value.upper(), value)
        layout.addWidget(QtWidgets.QLabel('选择格式，可分别导出多个版本' if _LANG == 'zh'
                                         else 'Choose a format; export multiple versions if needed'))
        layout.addWidget(self.format)
        self.progress = QtWidgets.QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        self.message = QtWidgets.QLabel(); self.message.setWordWrap(True); layout.addWidget(self.message)
        row = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton('导出…' if _LANG == 'zh' else 'Export…')
        self.close_button = QtWidgets.QPushButton('放弃录屏' if _LANG == 'zh' else 'Discard recording')
        row.addWidget(self.save_button); row.addStretch(); row.addWidget(self.close_button); layout.addLayout(row)
        self.exporter = RecordingExporter(source, fps, duration, self)
        self.exporter.progress.connect(self._progress)
        self.exporter.completed.connect(self._completed)
        self.save_button.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)

    def _save(self):
        from pathlib import Path
        extension = self.format.currentData()
        suggested = str(Path(self.directory) / Path(self.filename).with_suffix('.' + extension))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, self.windowTitle(), suggested,
                                                       f'{extension.upper()} (*.{extension})')
        if not path: return
        if not Path(path).suffix: path += '.' + extension
        self.busy = True; self.save_button.setEnabled(False); self.close_button.setEnabled(False)
        self.format.setEnabled(False); self.progress.show()
        self.message.setText('正在导出…' if _LANG == 'zh' else 'Exporting…')
        self.exporter.start(path, extension)

    def _progress(self, value):
        self.progress.setRange(0, 0 if value < 0 else 100)
        if value >= 0: self.progress.setValue(value)

    def _completed(self, path, error):
        self.busy = False; self.save_button.setEnabled(True); self.close_button.setEnabled(True)
        self.format.setEnabled(True)
        if error:
            self.message.setText(('导出失败，可重试：' if _LANG == 'zh' else 'Export failed; retry: ') + error)
        else:
            self.saved_paths.append(path)
            self.message.setText(('已保存：' if _LANG == 'zh' else 'Saved: ') + path)
            self.close_button.setText('完成' if _LANG == 'zh' else 'Done')

    def reject(self):
        if self.busy: return
        if not self.saved_paths:
            answer = QtWidgets.QMessageBox.question(self, self.windowTitle(),
                '尚未导出，放弃这段录屏？' if _LANG == 'zh' else 'Discard this recording without exporting?',
                QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Cancel)
            if answer != QtWidgets.QMessageBox.Discard: return
        super().reject()


class Recorder(QtCore.QObject):
    """Capture an Xorg region to a temporary MP4 without blocking the UI."""
    phase = pyqtSignal(str)
    progress = pyqtSignal(int)
    completed = pyqtSignal(str, str)  # temporary recording path, error

    def __init__(self, region, out_path, fps=15, parent=None, output_size=None, duration=0):
        super().__init__(parent)
        self.region, self.out_path, self.fps = region, out_path, fps
        self.output_size, self.duration = output_size, duration
        self.proc = QtCore.QProcess(self)
        self.stopping = False
        self._done = False
        self._duration = 0.0
        self._buffers = {}
        self._errors = {}
        for process in (self.proc,):
            process.readyReadStandardOutput.connect(lambda p=process:self._read_progress(p))
            process.readyReadStandardError.connect(lambda p=process:self._read_error(p))
            process.errorOccurred.connect(lambda error,p=process:self._process_error(p,error))
        self.proc.finished.connect(self._record_finished)

        self._stop_timer=QtCore.QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._stop_timeout)

    def _record_args(self):
        import os
        x, y, w, h = self.region
        w -= w % 2; h -= h % 2
        args = ['-y', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats',
                '-f', 'x11grab', '-probesize', '32', '-analyzeduration', '0',
                '-framerate', str(self.fps), '-video_size', f'{w}x{h}',
                '-i', f"{os.environ.get('DISPLAY', ':0')}+{x},{y}"]
        if self.output_size and tuple(self.output_size) != (w, h):
            args += ['-vf', f'scale={self.output_size[0]}:{self.output_size[1]}:flags=lanczos']
        if self.duration:
            args += ['-t', str(self.duration)]
        return args + ['-codec:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', self.out_path]

    def start(self):
        self.proc.start('ffmpeg',self._record_args())
        return self.proc.waitForStarted(3000)

    def _read_error(self, process):
        text=bytes(process.readAllStandardError()).decode(errors='replace')
        self._errors[process]=(self._errors.get(process,'')+text)[-3000:]

    def _read_progress(self, process):
        data=self._buffers.get(process,'')+bytes(process.readAllStandardOutput()).decode(errors='replace')
        lines=data.split('\n');self._buffers[process]=lines.pop()
        for line in lines:
            key,_,value=line.partition('=')
            if key != 'out_time_us':
                continue
            try: seconds=max(0,int(value)/1000000)
            except ValueError: continue
            if process is self.proc:
                self._duration=max(self._duration,seconds)


    def stop(self):
        if self.stopping or self._done:
            return
        self.stopping=True
        self.phase.emit('mp4');self.progress.emit(-1)
        if self.proc.state()!=QtCore.QProcess.NotRunning:
            self.proc.write(b'q');self.proc.closeWriteChannel()
            self._stop_timer.start(8000)

    def _stop_timeout(self):
        if self.proc.state()!=QtCore.QProcess.NotRunning:
            self._errors[self.proc]='ffmpeg did not finish saving within 8 seconds.'
            self.proc.kill()

    def _process_error(self, process, error):
        if error==QtCore.QProcess.FailedToStart:
            self._complete('',process.errorString())

    @staticmethod
    def _valid_file(path):
        import os
        return os.path.isfile(path) and os.path.getsize(path)>0

    def _record_finished(self, code, status):
        self._stop_timer.stop()
        self._read_progress(self.proc);self._read_error(self.proc)
        if self._done:
            return
        self.stopping=True
        if code!=0 or status!=QtCore.QProcess.NormalExit or not self._valid_file(self.out_path):
            self._complete('',self._errors.get(self.proc,'') or 'MP4 recording failed.')
        else:
            self._complete(self.out_path,'')

    def _complete(self, paths, error):
        if self._done:
            return
        self._done=True
        if not error:self.progress.emit(100)
        self.completed.emit(paths,error)


class RecordBar(QtWidgets.QWidget):
    """Timer, explicit output format, and nonblocking save/export progress."""
    stopRequested=pyqtSignal()
    _place=ScrollHud._place
    show_on_top=ScrollHud.show_on_top
    paintEvent=ScrollHud.paintEvent

    def __init__(self, on_stop, region=None, fps=15, output_size=None, duration=0):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.X11BypassWindowManagerHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName('RecordBar')
        self._region=QRect(region) if region is not None else QRect()
        self._format = f'{fps} fps' + (f' · {output_size[0]} × {output_size[1]}' if output_size else '')
        self._limit = duration
        self.stopRequested.connect(on_stop)
        lay=QtWidgets.QVBoxLayout(self);lay.setContentsMargins(12,8,12,8)
        row=QtWidgets.QHBoxLayout()
        self.lbl=QtWidgets.QLabel()
        self.btn=QtWidgets.QPushButton('Stop' if _LANG=='en' else '停止')
        self.btn.clicked.connect(self.stopRequested.emit)
        row.addWidget(self.lbl);row.addWidget(self.btn);lay.addLayout(row)
        self.progress_bar=QtWidgets.QProgressBar();self.progress_bar.hide()
        lay.addWidget(self.progress_bar)
        self.setStyleSheet('#RecordBar{background:#25272c;border:1px solid #e74c3c;border-radius:8px;}'
            'QLabel{color:#f0f0f4;font-size:14px;} QPushButton{background:#c0392b;color:white;'
            'padding:5px 14px;border:0;border-radius:4px;}'
            'QProgressBar{color:white;border:1px solid #555;border-radius:3px;text-align:center;}'
            'QProgressBar::chunk{background:#4385be;}')
        self._secs=0;self._tick_label()
        self.adjustSize();self._place()
        self._t=QtCore.QTimer(self);self._t.setInterval(1000)
        self._t.timeout.connect(self._tick);self._t.start()
        self._esc=KeyListener(on_press=lambda key:self.stopRequested.emit() if key==Key.esc else None)
        self._esc.start()
        self.setToolTip('Esc: stop' if _LANG=='en' else 'Esc：停止录屏')

    def _tick_label(self):
        limit = f' / {self._limit}s' if self._limit else ''
        self.lbl.setText(f'● {self._format}  {self._secs//60:02d}:{self._secs%60:02d}{limit} · Esc')

    def _tick(self):
        self._secs+=1;self._tick_label()

    def set_countdown(self, seconds):
        self.btn.setText('取消' if _LANG == 'zh' else 'Cancel')
        self.lbl.setText(f'{seconds} 秒后开始录屏' if _LANG == 'zh' else f'Recording starts in {seconds}s')
        self.adjustSize(); self._place()

    def start_timer(self):
        self.btn.setText('停止' if _LANG == 'zh' else 'Stop')
        self._secs = 0; self._tick_label(); self._t.start()
        if self._esc is None:
            self._esc = KeyListener(on_press=lambda key:self.stopRequested.emit() if key==Key.esc else None)
            self._esc.start()
        self.adjustSize(); self._place()

    def set_phase(self, phase):
        self.stop_timer();self.btn.setEnabled(False)
        text = 'Finishing recording…' if _LANG == 'en' else '正在完成录屏…'
        self.lbl.setText(text);self.progress_bar.show();self.adjustSize()
        if phase == 'mp4':
            # ffmpeg may still be capturing its last frame: keep controls outside.
            self.hide();self._place();self.show_on_top()
        else:
            screen=QtWidgets.QApplication.screenAt(self._region.center()) or QtWidgets.QApplication.primaryScreen()
            self.move(screen.availableGeometry().center()-self.rect().center())
            self.show();self.raise_()

    def set_progress(self, value):
        self.progress_bar.setRange(0,0 if value<0 else 100)
        if value>=0:self.progress_bar.setValue(value)

    def stop_timer(self):
        self._t.stop()
        if self._esc is not None:
            self._esc.stop();self._esc=None

    def closeEvent(self,event):
        self.stop_timer();super().closeEvent(event)


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class OCRWorker(QThread):
    result = pyqtSignal(str, str)     # recognized text, or an error message
    wordsReady = pyqtSignal(object)   # list of (QRectF in image coords, word)

    def __init__(self, img, lang, psm, enhance, automatic, parent=None):
        super().__init__(parent)
        self.img = img.copy()
        self.lang = lang
        self.psm = psm
        self.enhance = enhance
        self.automatic = automatic
        QtWidgets.QApplication.instance().aboutToQuit.connect(self._stop_for_exit)

    def _stop_for_exit(self):
        self.requestInterruption()
        self.wait()

    def _word_boxes(self, pil, upscale):
        """Per-word boxes via Tesseract's TSV data, mapped back to image coords."""
        import pytesseract
        try:
            data = pytesseract.image_to_data(pil, lang=self.lang,
                                             config=f"--psm {self.psm}", timeout=20,
                                             output_type=pytesseract.Output.DICT)
        except Exception:
            return []
        out = []
        for i, word in enumerate(data.get("text", [])):
            word = (word or "").strip()
            if not word or int(data.get("conf", ["0"] * len(data["text"]))[i] or -1) < 30:
                continue
            try:
                x, y = float(data["left"][i]) / upscale, float(data["top"][i]) / upscale
                w, h = float(data["width"][i]) / upscale, float(data["height"][i]) / upscale
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue
            out.append((QtCore.QRectF(x, y, w, h), word))
        return out

    def run(self):
        try:
            import pytesseract
        except ImportError:
            self.result.emit("", "pytesseract not installed")
            return
        try:
            if self.enhance:
                pil = Image.fromarray(preprocess_for_ocr(self.img))
                upscale = 2.0          # preprocess_for_ocr upscales 2x
            else:
                pil = Image.fromarray(cv2.cvtColor(self.img, cv2.COLOR_BGR2RGB))
                upscale = 1.0
            config = f"--oem 1 --psm {self.psm} -c preserve_interword_spaces=1 --dpi 150"
            txt = pytesseract.image_to_string(
                pil, lang=self.lang, config=config, timeout=20)
        except pytesseract.TesseractNotFoundError:
            self.result.emit("", "tesseract not found; run: apt install tesseract-ocr")
            return
        except Exception as exc:                      # noqa: BLE001
            self.result.emit("", f"OCR error: {exc} (language pack may be missing)")
            return
        if "chi" in self.lang:
            txt = _strip_cjk_spaces(txt)
        self.result.emit(txt, "")
        if self.isInterruptionRequested():
            return
        try:
            words = self._word_boxes(pil, upscale)
            if words:
                self.wordsReady.emit(words)
        except Exception:                              # noqa: BLE001
            pass                                       # word boxes are an extra, never fatal


class MainWindow(QtWidgets.QWidget):
    scroll_stop_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        # Background/tray apps are often not the "active" window (GNOME refuses
        # activation), and Qt suppresses hover tooltips on inactive windows —
        # without this, tooltips only appear after clicking into the window.
        self.setAttribute(Qt.WA_AlwaysShowToolTips)
        self.setWindowTitle("Kapture")
        self.resize(820, 660)
        self.image_bgr = None        # current screenshot (BGR numpy)
        self.worker = None
        self._mode = None            # 'scroll' or 'single'
        self.settings = QtCore.QSettings("ScrollShot", "ScrollShot")
        set_lang(self.settings.value("ui_lang", "zh"))      # apply the UI language
        write_desktop_entry()                               # launcher name follows the language
        from pathlib import Path
        self._history_store = ImageHistoryStore(Path(self.settings.fileName()).parent / 'history')
        self.history, self._clip_images = self._history_store.load()
        self._clip_images = [im.convertToFormat(QtGui.QImage.Format_ARGB32) for im in self._clip_images]
        self._history_writer = HistoryWriter(self._history_store)
        self._pending_history = {}
        QtWidgets.QApplication.instance().aboutToQuit.connect(self._history_writer.shutdown)
        self._inline_editor = None
        self._settings_dialog = None
        self._capture_background = None
        self._capture_rect = None
        self._canvas_base_key = None
        QtWidgets.QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        self._recorder = None        # screen recorder
        self._ocr_workers = []
        self._ocr_serial = 0
        self._ocr_pending = None        # (serial, text) held until the editor shows the image
        self._ocr_image_shown = False   # canvas currently paints self.image_bgr
        self._words_inflight = False    # background OCR running to fill word boxes
        self._build_ui()
        self._apply_style()
        self._setup_tray()
        self._retranslate()
        self.canvas.changed.connect(self._canvas_changed)
        self._history_writer.error.connect(self._history_error)
        self._history_writer.cleared.connect(self._history_cleared)
        self._history_writer.clear_failed.connect(self._history_clear_failed)
        if self._history_store.errors:
            self.status.setText(self._history_store.errors[-1])

    def _tbtn(self, icon, tip, checkable=False, editor_dropdown=False):
        b = QtWidgets.QToolButton(self)
        b.setIcon(line_icon(icon,size=24))
        b.setIconSize(QtCore.QSize(24, 24))
        b.setFixedSize(36, 36)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if editor_dropdown:
            b.setProperty("editorDropdown", True)
        else:
            b.setStyleSheet("QToolButton{padding:3px;}")
        b.setAutoRaise(True)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _vsep(self):
        w = QtWidgets.QWidget()
        w.setObjectName("vsep")
        w.setAttribute(Qt.WA_StyledBackground, True)
        # Keep dividers out of the row's horizontal expansion calculation.
        w.setFixedWidth(1)
        w.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)
        return w

    def _toolbar_group(self, widgets):
        group = QtWidgets.QFrame()
        group.setObjectName("toolbarGroup")
        row = QtWidgets.QHBoxLayout(group)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(4)
        for widget in widgets:
            row.addWidget(widget)
        return group

    def _add_annotation_widget(self, widget, layout):
        widget.setProperty("annotationToolbarItem", True)
        layout.addWidget(widget)
        widget.show()
        self._annotation_widgets.append(widget)

    @staticmethod
    def _psm_layout_labels(language=None):
        language = language or _LANG
        if language == "zh":
            return ("文本块（psm 6）", "自动（psm 3）",
                    "单列（psm 4）", "单行（psm 7）")
        return ("Block of text (psm 6)", "Auto (psm 3)",
                "Single column (psm 4)", "Single line (psm 7)")

    @classmethod
    def _localize_psm_combo(cls, combo, language=None):
        for index, label in enumerate(cls._psm_layout_labels(language)):
            if index < combo.count():
                combo.setItemText(index, label)

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 8)
        layout.setSpacing(10)

        # ---------- Capture, capture options, and window actions ---------- #
        top = QtWidgets.QHBoxLayout(); top.setSpacing(8)
        self.btn_single = self._tbtn("region", "", editor_dropdown=True)
        self.btn_single.setObjectName("primaryCapture")
        self.btn_single.setFixedWidth(40)
        self._capture_menu = QtWidgets.QMenu(self.btn_single)
        self.btn_single.setMenu(self._capture_menu)
        self.btn_single.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.btn_textgrab = self._tbtn("textgrab", "")
        self.btn_window = self._tbtn("window", "")
        self.btn_scroll = self._tbtn("scroll", "", editor_dropdown=True)
        self._scroll_direction = 1
        self._scroll_menu = QtWidgets.QMenu(self.btn_scroll)
        self._scroll_down_action = self._scroll_menu.addAction("", lambda: self._start_auto_scroll(1))
        self._scroll_up_action = self._scroll_menu.addAction("", lambda: self._start_auto_scroll(-1))
        self.btn_scroll.setMenu(self._scroll_menu)
        self.btn_scroll.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        self.btn_scroll.setFixedWidth(40)
        self.btn_manual = self._tbtn("manual", "")
        self.btn_record = self._tbtn("record", "")
        top.addWidget(self._toolbar_group((self.btn_single, self.btn_textgrab,
                                           self.btn_window,
                                           self.btn_scroll, self.btn_manual,
                                           self.btn_record)))
        self.btn_colorpick = self._tbtn("color", "")
        self.btn_repeat = self._tbtn("repeat", "")
        self._lab_delay = QtWidgets.QLabel(); self._lab_delay.setObjectName("dim")
        self.delay = QtWidgets.QSpinBox(); self.delay.setRange(0, 10)
        self.delay.setObjectName("captureDelay")
        self.delay.setFixedWidth(50)
        self._lab_speed = QtWidgets.QLabel(); self._lab_speed.setObjectName("dim")
        self.speed = QtWidgets.QSpinBox(); self.speed.setRange(1, 10)
        self.speed.setObjectName("scrollSpeed")
        self.speed.setValue(3); self.speed.setFixedWidth(50)
        capture_options = QtWidgets.QWidget()
        capture_form = QtWidgets.QFormLayout(capture_options)
        capture_form.addRow(self._lab_delay, self.delay)
        self._capture_options_widget = capture_options
        self._capture_settings_action = QtWidgets.QWidgetAction(self._capture_menu)
        self._capture_settings_action.setObjectName("captureSettings")
        self._capture_settings_action.setDefaultWidget(capture_options)
        self._capture_menu.addAction(self._capture_settings_action)

        scroll_options = QtWidgets.QWidget()
        scroll_form = QtWidgets.QFormLayout(scroll_options)
        scroll_form.addRow(self._lab_speed, self.speed)
        self._scroll_options_widget = scroll_options
        self._scroll_settings_action = QtWidgets.QWidgetAction(self._scroll_menu)
        self._scroll_settings_action.setObjectName("scrollSettings")
        self._scroll_settings_action.setDefaultWidget(scroll_options)
        self._scroll_menu.insertAction(self._scroll_down_action,
                                       self._scroll_settings_action)
        self._scroll_menu.insertSeparator(self._scroll_down_action)

        top.addWidget(self._toolbar_group((self.btn_colorpick, self.btn_repeat)))
        top.addStretch(1)
        self.btn_history = self._tbtn("history", "")
        self.btn_settings = self._tbtn("settings", "")
        top.addWidget(self._toolbar_group((self.btn_history, self.btn_settings)))
        layout.addLayout(top)

        # ---------- Annotation tools and output actions ---------- #
        card = QtWidgets.QFrame(); card.setObjectName("card")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(8, 6, 8, 6)
        card_layout.setSpacing(0)
        tools = QtWidgets.QHBoxLayout()
        # Use the card's padding as the only inset for the icon row.
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(3)
        card_layout.addLayout(tools)
        self._annotation_row = tools
        self._annotation_widgets = []
        self._main_tool_groups = {}
        self._main_tool_actions = {}
        self._main_tool_current = {}
        self.tool_group = QtWidgets.QButtonGroup(self)
        self.tool_group.setExclusive(True)
        self._tool_btns = {}
        for name in ["picktext", "select", "rect", "ellipse", "arrow", "line", "pen",
                     "text", "number", "highlight", "blur", "magnify", "crop"]:
            b = self._tbtn(name, "", checkable=True)
            b.setObjectName("legacyTool_" + name)
            b.hide()
            b.clicked.connect(lambda _, n=name: self._set_main_tool(n))
            self.tool_group.addButton(b)
            self._tool_btns[name] = b

        grouped_tools = (
            ("shape", "rect", ("rect", "ellipse")),
            ("stroke", "pen", ("pen", "highlight")),
            ("line", "arrow", ("arrow", "line")),
            ("text", "text", ("text", "number")),
            ("mosaic", "blur", ("blur", "gaussian")),
            ("aux", "picktext", ("picktext", "crop")),
        )
        self.btn_select = self._tool_btns["select"]
        self._add_annotation_widget(self.btn_select, tools)
        for key, initial, names in grouped_tools:
            button = QtWidgets.QToolButton(self)
            button.setObjectName("toolGroup_" + key)
            button.setIcon(line_icon(initial, size=22))
            button.setIconSize(QtCore.QSize(22, 22))
            button.setProperty("editorDropdown", True)
            button.setFixedSize(40, 36)
            button.setCheckable(True)
            button.setAutoRaise(True)
            button.setCursor(Qt.PointingHandCursor)
            menu = QtWidgets.QMenu(self)
            menu.setObjectName("toolMenu_" + key)
            action_group = QtWidgets.QActionGroup(menu)
            action_group.setExclusive(True)
            actions = {}
            for name in names:
                label_key = "a_gaussian_blur" if name == "gaussian" else "a_" + name
                action = menu.addAction(line_icon(name), t(label_key))
                action.setObjectName("tool:" + name)
                action.setCheckable(True)
                action_group.addAction(action)
                action.triggered.connect(
                    lambda _checked=False, tool=name: self._set_main_tool(tool))
                actions[name] = action
            button.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
            button.setMenu(menu)
            button.clicked.connect(
                lambda _checked=False, group_key=key, fallback=initial:
                self._set_main_tool(self._main_tool_current.get(group_key, fallback)))
            self._main_tool_groups[key] = (button, menu, tuple(names))
            self._main_tool_actions[key] = actions
            self._add_annotation_widget(button, tools)

        self.btn_magnify = self._tool_btns["magnify"]
        self._add_annotation_widget(self.btn_magnify, tools)
        self.btn_color = QtWidgets.QToolButton()
        self.btn_color.setObjectName("annotationColor")
        self.btn_color.setIcon(swatch_icon(QtGui.QColor(255, 40, 40)))
        self.btn_color.setIconSize(QtCore.QSize(20, 20))
        self.btn_color.setFixedSize(36, 36)
        self.btn_color.setAutoRaise(True)
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.clicked.connect(self.pick_color)
        self._add_annotation_widget(self.btn_color, tools)
        self.lwidth = QtWidgets.QSpinBox(); self.lwidth.setRange(1, 30)
        self.lwidth.setObjectName("annotationWidth")
        self.lwidth.setValue(3); self.lwidth.setFixedWidth(48)
        self.lwidth.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.lwidth.valueChanged.connect(lambda v: self.canvas.set_width(v))
        self._add_annotation_widget(self.lwidth, tools)
        self.btn_undo = self._tbtn("undo", "")
        self.btn_undo.setObjectName("annotationUndo")
        self.btn_undo.clicked.connect(lambda: self.canvas.undo())
        self.btn_clear = self._tbtn("clear", "")
        self.btn_clear.setObjectName("annotationClear")
        self.btn_clear.clicked.connect(lambda: self.canvas.clear_items())
        self._annotation_separator = self._vsep()
        self.tools_redo_separator = self._vsep()
        tools.addWidget(self._annotation_separator)
        self._add_annotation_widget(self.btn_undo, tools)
        self.btn_redo = self._tbtn('redo',t('a_redo'))
        self.btn_redo.setObjectName("annotationRedo")
        self.btn_redo.clicked.connect(self._redo_current_context)
        self._add_annotation_widget(self.btn_redo, tools)
        self._add_annotation_widget(self.btn_clear, tools)

        tools.addWidget(self.tools_redo_separator)
        self.btn_output = QtWidgets.QToolButton(self)
        self.btn_output.setObjectName("outputMenuButton")
        self.btn_output.setIcon(line_icon("save", size=22))
        self.btn_output.setIconSize(QtCore.QSize(22, 22))
        self.btn_output.setText(t("lab_output"))
        self.btn_output.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_output.setFixedHeight(36)
        self.btn_output.setAutoRaise(True)
        self.btn_output.setCursor(Qt.PointingHandCursor)
        self.btn_output.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self._output_menu = QtWidgets.QMenu(self.btn_output)
        self._output_actions = {}
        for key, icon, label_key, callback in (
                ("ocr", "ocr", "e_ocr", lambda: self.run_ocr()),
                ("copy", "copy", "e_copy", lambda: self.copy_image()),
                ("pin", "pin", "e_pin", lambda: self.pin_image()),
                ("save", "save", "e_save", lambda: self.save_image()),
                ("beautify", "beautify", "e_beautify", lambda: self.beautify_export())):
            action = self._output_menu.addAction(line_icon(icon), t(label_key))
            action.setObjectName("output:" + key)
            action.triggered.connect(callback)
            self._output_actions[key] = action
        self.btn_output.setMenu(self._output_menu)

        # Legacy references remain available for integrations and tests; their
        # commands are exposed in the output menu instead of a separate toolbar.
        self._output_label = QtWidgets.QLabel(t("lab_output"), self)
        self._output_label.setObjectName("dim")
        self._output_label.hide()

        # OCR: main button runs recognition; dropdown arrow adjusts language/layout/enhancement
        self.btn_ocr = QtWidgets.QToolButton()
        self.btn_ocr.setIcon(line_icon("ocr")); self.btn_ocr.setIconSize(QtCore.QSize(22, 22))
        self.btn_ocr.setObjectName("mainOcrButton")
        self.btn_ocr.setProperty("editorDropdown", True)
        self.btn_ocr.setFixedSize(40, 36)
        self.btn_ocr.setAutoRaise(True); self.btn_ocr.setCursor(Qt.PointingHandCursor)
        self.btn_ocr.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        ocr_menu = QtWidgets.QMenu(self.btn_ocr)
        opt_w = QtWidgets.QWidget(); fl = QtWidgets.QFormLayout(opt_w)
        self.lang = QtWidgets.QComboBox()
        self.lang.addItems(["chi_sim+eng", "chi_sim", "chi_tra+eng", "eng"])
        self.psm = QtWidgets.QComboBox()
        for label, value in zip(self._psm_layout_labels(), (6, 3, 4, 7)):
            self.psm.addItem(label, value)
        self.enhance = QtWidgets.QCheckBox()
        # Apply the OCR defaults saved in settings
        self.lang.setCurrentText(self.settings.value("ocr_lang", "chi_sim+eng"))
        pidx = self.psm.findData(int(self.settings.value("ocr_psm", 6, type=int)))
        if pidx >= 0:
            self.psm.setCurrentIndex(pidx)
        self.enhance.setChecked(self.settings.value("ocr_enhance", True, type=bool))
        self._ocr_lab_lang = QtWidgets.QLabel()
        self._ocr_lab_layout = QtWidgets.QLabel()
        fl.addRow(self._ocr_lab_lang, self.lang)
        fl.addRow(self._ocr_lab_layout, self.psm)
        fl.addRow(self.enhance)
        wa = QtWidgets.QWidgetAction(ocr_menu); wa.setDefaultWidget(opt_w)
        ocr_menu.addAction(wa); self.btn_ocr.setMenu(ocr_menu)

        self.btn_copy = self._tbtn("copy", "")
        self.btn_pin = self._tbtn("pin", "")
        self.btn_beautify = self._tbtn("beautify", "")
        self.btn_save = self._tbtn("save", "")
        for b in (self.btn_copy, self.btn_pin, self.btn_beautify, self.btn_save):
            b.hide()
        self._add_annotation_widget(self.btn_ocr, tools)
        # Keep annotation and OCR actions packed to the left; let the output
        # menu use the right edge of the row.
        tools.addStretch(1)
        self._add_annotation_widget(self.btn_output, tools)
        layout.addWidget(card)

        # ---------- Canvas ---------- #
        self.canvas = AnnotateCanvas()
        self._sync_main_tool(self.canvas.tool)
        self.canvas.cropRequested.connect(self._do_crop)
        self.canvas.textSelected.connect(self._on_text_selected)
        self.canvas.picktextNeedsWords.connect(self._ensure_word_boxes)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        layout.addWidget(self.scroll, 3)

        # ---------- OCR result with fixed floating actions ---------- #
        self._ocr_panel=QtWidgets.QFrame()
        self._ocr_panel.setObjectName('ocrPanel')
        ocr_layout=QtWidgets.QVBoxLayout(self._ocr_panel)
        ocr_layout.setContentsMargins(1,1,1,1);ocr_layout.setSpacing(0)
        self._ocr_btns=QtWidgets.QWidget(self._ocr_panel)
        self._ocr_btns.setObjectName('ocrActions')
        self._ocr_btns.setAttribute(Qt.WA_StyledBackground,True)
        br=QtWidgets.QHBoxLayout(self._ocr_btns)
        br.setContentsMargins(4,3,4,3);br.setSpacing(6)
        self.btn_ocr_all=QtWidgets.QPushButton()
        self.btn_copy_all=QtWidgets.QPushButton()
        for button in (self.btn_ocr_all,self.btn_copy_all):
            button.setFixedHeight(28);button.setCursor(Qt.PointingHandCursor)
            br.addWidget(button)
        self.text=QtWidgets.QPlainTextEdit()
        self.text.setObjectName('ocrText')
        ocr_layout.addWidget(self.text,1)
        self._ocr_panel.installEventFilter(self)
        self.text.viewport().installEventFilter(self)
        layout.addWidget(self._ocr_panel,2)

        self.status = QtWidgets.QLabel()
        self.status.setObjectName("status")
        # The status line is no longer shown: capture/OCR feedback arrives via the
        # floating card and the OCR-box toast. The label still exists because
        # internal logic reads/writes its text as state.
        self.status.hide()

        # ---------- Connections ---------- #
        self.btn_manual.clicked.connect(lambda: self.start_select("manual"))
        self.btn_scroll.clicked.connect(lambda: self._start_auto_scroll(1))
        self.btn_single.clicked.connect(lambda: self.start_select("single"))
        self.btn_textgrab.clicked.connect(lambda: self.start_select("textgrab"))
        self.btn_ocr.clicked.connect(lambda: self.run_ocr())
        self.btn_ocr_all.clicked.connect(lambda: self.run_ocr(copy_result=False))
        self.btn_copy_all.clicked.connect(self._copy_all_text)
        self.text.textChanged.connect(self._update_ocr_btns)   # buttons follow content
        self._update_ocr_btns()
        self.btn_copy.clicked.connect(self.copy_image)
        self.btn_pin.clicked.connect(self.pin_image)
        self.btn_save.clicked.connect(self.save_image)
        self.btn_window.clicked.connect(self.capture_window)
        self.btn_colorpick.clicked.connect(self.pick_color_screen)
        self.btn_repeat.clicked.connect(self.repeat_last)
        self.btn_record.clicked.connect(self.toggle_record)
        self.btn_beautify.clicked.connect(self.beautify_export)
        self.btn_history.clicked.connect(self.show_history)
        self.btn_settings.clicked.connect(self.show_settings)
        self._undo_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence.Undo, self)
        self._undo_shortcut.setContext(Qt.WindowShortcut)
        self._undo_shortcut.activated.connect(self._undo_current_context)
        self._redo_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence('Ctrl+Shift+Z'),self)
        self._redo_shortcut.activated.connect(self._redo_current_context)
        self._delete_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence('Delete'),self.canvas)
        self._delete_shortcut.setContext(Qt.WidgetShortcut)
        self._delete_shortcut.activated.connect(self.canvas.delete_selected)

    def _set_main_tool(self, name):
        if name not in self._tool_btns and name != "gaussian":
            return
        if name == "gaussian":
            self.canvas.blur_style = "gaussian"
            canvas_tool = "blur"
        else:
            if name == "blur":
                self.canvas.blur_style = "pixelate"
            canvas_tool = name
        self.canvas.set_tool(canvas_tool)
        self._tool_btns["blur" if name == "gaussian" else name].setChecked(True)
        self._sync_main_tool(name)

    def _sync_main_tool(self, name):
        if name not in self._tool_btns and name != "gaussian":
            return
        source_tool = "blur" if name == "gaussian" else name
        for tool_name, button in self._tool_btns.items():
            button.setChecked(tool_name == source_tool)
        for group_key, (button, _menu, names) in self._main_tool_groups.items():
            active = name in names
            button.setChecked(active)
            if active:
                self._main_tool_current[group_key] = name
            for tool_name, action in self._main_tool_actions[group_key].items():
                action.setChecked(tool_name == name)
        self._refresh_theme_icons()

    def _update_main_tool_labels(self):
        for key, (button, _menu, _names) in self._main_tool_groups.items():
            current = self._main_tool_current.get(key)
            if current is not None:
                button.setToolTip(t("a_gaussian_blur" if current == "gaussian"
                                    else "a_" + current))

    def _undo_current_context(self):
        focus = QtWidgets.QApplication.focusWidget()
        if focus is self.text or self.text.isAncestorOf(focus):
            self.text.undo()
        else:
            self.canvas.undo()

    def _redo_current_context(self):
        if self.text.hasFocus():
            self.text.redo()
        else:
            self.canvas.redo()

    def _canvas_changed(self):
        if self.canvas.base is None:
            return
        key = self.canvas.base.cacheKey()
        if key != self._canvas_base_key:
            self.image_bgr = qimage_to_bgr(self.canvas.base)
            self._canvas_base_key = key
            self._ocr_serial += 1
            self._ocr_pending = None
            self.text.clear()

    def _load_document(self, state, show=True):
        self._ocr_serial += 1
        self._ocr_pending = None
        self.text.clear()
        self.image_bgr = qimage_to_bgr(state['base'])
        self.canvas.restore_document(state)
        self.canvas.fit_width(self.scroll.viewport().width())
        self._ocr_image_shown = True
        if show:
            self._bring_to_front()

    def _new_pin(self, qimage, state=None):
        pin = PinnedImage(qimage, on_ocr=self._pin_ocr, on_edit=self._load_document)
        if state is not None:
            pin.canvas.restore_document(state)
        return pin

    def _retranslate(self):
        """Refresh the main UI text according to the current language (called when switching languages)."""
        self.setWindowTitle(t("app_title"))
        tips = {
            self.btn_single: "cap_region", self.btn_textgrab: "t_ocr",
            self.btn_window: "cap_window",
            self.btn_scroll: "cap_scroll", self.btn_manual: "cap_manual",
            self.btn_record: "cap_record", self.btn_colorpick: "cap_color",
            self.btn_repeat: "cap_repeat", self.btn_history: "t_history",
            self.btn_settings: "t_settings", self.btn_color: "a_color",
            self.btn_undo: "a_undo", self.btn_redo: "a_redo", self.btn_clear: "a_clear",
            self.btn_ocr: "e_ocr", self.btn_copy: "e_copy", self.btn_pin: "e_pin",
            self.btn_beautify: "e_beautify", self.btn_save: "e_save",
            self.btn_output: "lab_output",
        }
        for w, key in tips.items():
            w.setToolTip(t(key))
        delay_scope_note = (
            "延时也适用于窗口截图和截屏取词。" if _LANG == "zh" else
            "Delay also applies to window capture and text grab.")
        self.btn_single.setToolTip(t("cap_region") + "\n" + delay_scope_note)
        self.btn_output.setText(t("lab_output"))
        self.btn_ocr_all.setText(t("t_ocr_all"))
        self.btn_copy_all.setText(t("t_copy_all"))
        for name, b in self._tool_btns.items():
            b.setToolTip(t("a_" + name))
        self._update_main_tool_labels()
        for group_key, actions in self._main_tool_actions.items():
            for name, action in actions.items():
                action.setText(t("a_gaussian_blur" if name == "gaussian" else "a_" + name))
        for name, action in self._output_actions.items():
            action.setText(t({"ocr": "e_ocr", "copy": "e_copy", "pin": "e_pin",
                              "save": "e_save", "beautify": "e_beautify"}[name]))
        self._lab_delay.setText(t("lab_delay"))
        self._lab_speed.setText(t("lab_speed"))
        self._scroll_down_action.setText(t("scroll_down"))
        self._scroll_up_action.setText(t("scroll_up"))
        self._output_label.setText(t("lab_output"))
        self.lwidth.setToolTip(t("lab_width"))
        self._ocr_lab_lang.setText(t("ocr_lang"))
        self._ocr_lab_layout.setText(t("ocr_layout"))
        self.enhance.setText(t("ocr_enhance"))
        self._localize_psm_combo(self.psm)
        self._refresh_theme_icons()                  # OCR icon follows the language: 字 / OCR
        self.text.setPlaceholderText(
            "OCR result will appear here…" if _LANG == "en" else "OCR 识别结果会显示在这里……")
        if not self.status.text() or self.status.text() in (t("st_ready"), "就绪", "Ready"):
            self.status.setText(t("st_ready"))
        self._build_tray_menu()

    # --- Selection + capture flow --- #
    def _refresh_theme_icons(self, theme=None):
        if theme is None:
            theme = self.settings.value("ui_theme", "dark")
        if theme == "system":
            theme = "dark" if system_prefers_dark() else "light"
        colors = THEMES.get(theme, THEMES["dark"])
        for button, name in (
                (self.btn_single, "region"), (self.btn_textgrab, "textgrab"),
                (self.btn_window, "window"),
                (self.btn_scroll, "scroll"), (self.btn_manual, "manual"),
                (self.btn_record, "record"), (self.btn_colorpick, "color"),
                (self.btn_repeat, "repeat"), (self.btn_history, "history"),
                (self.btn_settings, "settings"), (self.btn_undo, "undo"),
                (self.btn_redo,"redo"), (self.btn_clear, "clear"), (self.btn_ocr, "ocr"),
                (self.btn_copy, "copy"), (self.btn_pin, "pin"),
                (self.btn_beautify, "beautify"), (self.btn_save, "save"),
                (self.btn_output, "save")):
            icon = line_icon(name, colors["on_accent"] if button is self.btn_single
                             else colors["icon"],size=button.iconSize().width())
            if button.isCheckable():
                icon.addPixmap(line_icon(name, colors["on_accent"],size=button.iconSize().width()).pixmap(button.iconSize()),
                               QtGui.QIcon.Normal, QtGui.QIcon.On)
            button.setIcon(icon)
        for name, button in self._tool_btns.items():
            icon = line_icon(name, colors["icon"],size=button.iconSize().width())
            icon.addPixmap(line_icon(name, colors["on_accent"],size=button.iconSize().width()).pixmap(button.iconSize()),
                           QtGui.QIcon.Normal, QtGui.QIcon.On)
            button.setIcon(icon)
        for key, (button, _menu, names) in self._main_tool_groups.items():
            name = self._main_tool_current.get(key, names[0])
            icon = line_icon(name, colors["icon"], size=button.iconSize().width())
            icon.addPixmap(line_icon(name, colors["on_accent"],
                                     size=button.iconSize().width()).pixmap(button.iconSize()),
                           QtGui.QIcon.Normal, QtGui.QIcon.On)
            button.setIcon(icon)
            for action_name, action in self._main_tool_actions[key].items():
                action.setIcon(line_icon(action_name, colors["icon"], size=22))
        output_icons = {"ocr": "ocr", "copy": "copy", "pin": "pin",
                        "save": "save", "beautify": "beautify"}
        for name, action in self._output_actions.items():
            action.setIcon(line_icon(output_icons[name], colors["icon"], size=22))

    def _apply_style(self, theme=None, accent=None):
        """Apply one complete palette to the editor and its child dialogs."""
        self.setObjectName("root")
        if theme is None:
            theme = self.settings.value("ui_theme", "dark")
        if theme == "system":
            theme = "dark" if system_prefers_dark() else "light"
        c = THEMES.get(theme, THEMES["dark"])
        a = accent if accent is not None else self.settings.value("ui_accent", "theme")
        if a == "theme" or not QtGui.QColor(a).isValid():
            a = c["accent"]
        window, panel, field, editor = (c[k] for k in ("window", "panel", "field", "editor"))
        edge, fg, muted, dim = (c[k] for k in ("edge", "text", "muted", "dim"))
        hover, pressed, on_accent = (c[k] for k in ("hover", "pressed", "on_accent"))
        self.canvas.empty_background = editor
        self.canvas.empty_text = dim
        self.canvas.update()
        self.setStyleSheet(f"""
        QWidget#root, QDialog, QWidget#historyGrid {{ background:{window}; }}
        QToolButton#historyCard {{ background:{panel}; border:1px solid {edge}; }}
        QToolButton#historyCard:hover {{ background:{hover}; border-color:{a}; }}
        QWidget {{ color:{fg}; font-size:13px; }}
        QLabel {{ color:{muted}; }}
        QLabel#dim {{ color:{dim}; font-size:12px; }}

        /* icon buttons (top bar + toolbar) */
        QToolButton {{
            background:transparent; border:1px solid transparent;
            border-radius:9px; padding:6px;
        }}
        QToolButton:hover   {{ background:{hover}; }}
        QToolButton:pressed {{ background:{pressed}; }}
        QToolButton:checked {{ background:{a}; }}
        QToolButton#primaryCapture {{ background:{a}; border:1px solid {a}; }}
        QToolButton#primaryCapture:hover {{ border-color:{on_accent}; }}
        QToolButton::menu-button {{ border:none; width:12px; border-top-right-radius:9px;
            border-bottom-right-radius:9px; }}


        QToolButton[editorDropdown="true"] {{ padding:0px 8px 0px 0px; }}
        QToolButton[editorDropdown="true"]::menu-button {{ width:10px; }}
        QToolButton[editorDropdown="true"]::menu-arrow {{
            subcontrol-origin:padding; subcontrol-position:center right;
            right:1px; width:8px; height:8px;
        }}

        QToolButton#outputMenuButton {{ padding:0px 14px 0px 6px; }}
        QToolButton#outputMenuButton::menu-indicator {{
            subcontrol-origin:padding; subcontrol-position:center right;
            right:4px; width:6px; height:6px;
        }}

        /* normal buttons (dialogs etc.) */
        QPushButton {{
            background:{panel}; color:{fg};
            border:1px solid {edge}; border-radius:10px;
            padding:7px 16px; min-height:22px;
        }}
        QPushButton:hover  {{ background:{hover}; border-color:{dim}; }}
        QPushButton:pressed{{ background:{pressed}; }}
        QPushButton:default {{ background:{a}; border:1px solid {a}; color:{on_accent}; }}
        QPushButton:default:hover {{ background:{a}; }}

        QComboBox, QSpinBox, QLineEdit {{
            background:{field}; color:{fg}; border:1px solid {edge}; border-radius:8px;
            padding:4px 8px; min-height:22px; selection-background-color:{a};
        }}
        QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color:{dim}; }}
        QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color:{a}; }}
        QComboBox QAbstractItemView {{
            background:{panel}; color:{fg}; border:1px solid {edge};
            selection-background-color:{a}; selection-color:{on_accent};
            outline:0; padding:4px;
        }}
        QComboBox::drop-down {{ border:none; width:18px; }}

        QCheckBox {{ color:{muted}; spacing:7px; }}
        QCheckBox::indicator {{ width:16px; height:16px; border-radius:5px;
            border:1px solid {edge}; background:{field}; }}
        QCheckBox::indicator:checked {{ background:{a}; border-color:{a}; }}

        QPlainTextEdit, QTextEdit {{
            background:{editor}; border:1px solid {edge}; border-radius:10px;
            padding:8px; color:{fg}; selection-background-color:{a};
        }}
        QFrame#ocrPanel {{ background:{editor}; border:1px solid {edge}; border-radius:10px; }}
        QPlainTextEdit#ocrText {{ border:none; }}
        QWidget#ocrActions {{ background:{editor}; border:none; border-radius:9px; }}
        QWidget#ocrActions QPushButton {{
            border-radius:6px; padding:2px 10px; min-height:0;
        }}
        QScrollArea {{ border:1px solid {edge}; border-radius:12px; background:{editor}; }}

        /* tool card + separators */
        QFrame#card {{ background:{panel}; border:1px solid {edge}; border-radius:12px; }}
        QFrame#toolbarGroup {{ background:{panel}; border:1px solid {edge}; border-radius:12px; }}
        QFrame#toolbarDivider {{ background:{edge}; border:none; }}
        QWidget#vsep {{ background:{edge}; }}

        QScrollBar:vertical {{ background:transparent; width:10px; margin:3px; }}
        QScrollBar::handle:vertical {{ background:{dim}; border-radius:5px; min-height:26px; }}
        QScrollBar::handle:vertical:hover {{ background:{a}; }}
        QScrollBar:horizontal {{ background:transparent; height:10px; margin:3px; }}
        QScrollBar::handle:horizontal {{ background:{dim}; border-radius:5px; min-width:26px; }}
        QScrollBar::handle:horizontal:hover {{ background:{a}; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}

        QLabel#status {{ color:{dim}; padding:4px 2px; }}
        QMenu {{ background:{panel}; color:{fg}; border:1px solid {edge};
                 padding:6px; border-radius:10px; }}
        QMenu::item {{ padding:7px 22px; border-radius:7px; }}
        QMenu::item:selected {{ background:{a}; color:{on_accent}; }}

        /* all tab surfaces must share the same palette as their labels */
        QTabWidget::pane {{ background:{panel}; border:1px solid {edge};
                            border-radius:11px; top:-1px; }}
        QWidget#settingsPage {{ background:{panel}; }}
        QTabBar::tab {{ background:{window}; color:{muted};
                       border:1px solid {edge}; border-bottom:none;
                       border-top-left-radius:8px; border-top-right-radius:8px;
                       min-width:58px; padding:8px 12px; margin-right:3px; }}
        QTabBar::tab:selected {{ background:{panel}; color:{fg}; }}
        QTabBar::tab:hover:!selected {{ background:{hover}; color:{fg}; }}
        """)
        app = QtWidgets.QApplication.instance()
        if app:
            pal = app.palette()
            pal.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(panel))
            pal.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(fg))
            app.setPalette(pal)
        self._refresh_theme_icons(theme)

    def _bring_to_front(self):
        """Restore and foreground the window even when launched from the tray/background.

        A tray or shortcut activation carries no user-input timestamp, so GNOME's
        focus-stealing prevention rejects the plain activateWindow()/raise_() and the
        window stays Iconic behind the current window. Clearing the minimized flag and
        re-raising after the event loop settles restores it reliably on X11 and KDE.
        """
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        # Re-assert on the next event-loop turn: some compositors only honour the
        # request once the restore has been processed.
        QtCore.QTimer.singleShot(0, lambda: (self.raise_(), self.activateWindow()))

    def _unfinished_capture(self):
        if self._inline_editor is not None:
            self._inline_editor.tools.note.setText(t('finish_capture_first'))
            return True
        return False

    def handle_command(self, cmd):
        """Single-instance command dispatch: sent from this process or a later-launched process."""
        if self._unfinished_capture() and not (cmd == 'record' and self._recorder is not None):
            return
        if cmd == "background":
            self.hide()
        elif cmd in ("single", "manual", "scroll", "textgrab"):
            self.start_select(cmd)
        elif cmd == "window":
            self.capture_window()
        elif cmd == "color":
            self.pick_color_screen()
        elif cmd == "record":
            self.toggle_record()
        elif cmd == "repeat":
            self.repeat_last()
        elif cmd in ("pin1", "pin2"):
            self._pin_from_clipboard(0 if cmd == "pin1" else 1)
        elif cmd == "settings":
            self._bring_to_front()          # give the modal dialog a visible, active parent
            self.show_settings()
        else:                                   # show / show-first
            self._blank_editor()                 # don't show the previous screenshot on open
            self._bring_to_front()

    def start_select(self, mode):
        if self.worker is not None and self.worker.isRunning():
            self.status.setText("Stop the current scrolling capture with Esc first")
            return
        if self._unfinished_capture():
            return
        self._capture_background = None
        self._capture_rect = None
        self._mode = mode
        if not self.settings.value("capture_keep_main", False, type=bool) and self._settings_dialog is None:
            self.showMinimized()
        QtCore.QTimer.singleShot(250, self._show_selector)

    def _show_selector(self):
        self.selector = RegionSelector(parent=self._settings_dialog)
        if self._settings_dialog is not None:
            self.selector.setWindowModality(Qt.ApplicationModal)
        self.selector.selected.connect(self._on_region)
        self.selector.cancelled.connect(self._restore)
        self.selector.show()
        self.selector.activateWindow()
        self.selector.raise_()

    def _restore(self):
        self.showNormal()
        if self._settings_dialog is not None:
            self._settings_dialog.raise_(); self._settings_dialog.activateWindow()
        else:
            self.activateWindow()

    def _on_region(self, gr: QRect, frozen=None):
        selector=getattr(self,'selector',None)
        self._capture_background = ((QtGui.QImage(selector.bg_img),QRect(selector.geometry()),selector.dpr)
                                    if selector is not None and frozen is not None else None)
        self._capture_rect = QRect(gr)
        dpr = QtWidgets.QApplication.primaryScreen().devicePixelRatio()
        phys = (int(gr.left() * dpr), int(gr.top() * dpr),
                int(gr.width() * dpr), int(gr.height() * dpr))
        if self._mode == "single":
            QtCore.QTimer.singleShot(150, lambda: self._single_shot(phys, frozen))
        elif self._mode == "textgrab":
            QtCore.QTimer.singleShot(150, lambda: self._textgrab_shot(phys, frozen))
        elif self._mode == "manual":
            QtCore.QTimer.singleShot(150, lambda: self._manual_start(phys, gr))
        else:
            QtCore.QTimer.singleShot(150, lambda: self._scroll_shot(phys, dpr, gr))

    def _freeze_region(self, phys):
        screen=QtWidgets.QApplication.primaryScreen()
        bounds=screen.virtualGeometry()
        dpr=screen.devicePixelRatio()
        bg=grab_region(round(bounds.x()*dpr),round(bounds.y()*dpr),
                       round(bounds.width()*dpr),round(bounds.height()*dpr))
        image=bgr_to_qimage(bg)
        self._capture_background=(image,QRect(bounds),dpr)
        x,y,w,h=phys
        return qimage_to_bgr(image.copy(x-round(bounds.x()*dpr),y-round(bounds.y()*dpr),w,h))

    def _single_shot(self, phys, frozen=None):
        self._last_phys = phys              # remember it for "repeat last area"
        # Prefer the frozen-frame crop the user actually saw; only fall back to a live
        # re-grab (e.g. "repeat last area") where no overlay was on screen.
        grab = (lambda: frozen) if frozen is not None else (lambda: self._freeze_region(phys))
        self._grab_with_delay(
            lambda: self._present_capture(grab(), f"Region captured: {phys[2]}×{phys[3]} px"))

    # --- screen text grab (PixPin "text" mode): grab → OCR → clipboard, no editor --- #
    def _textgrab_shot(self, phys, frozen=None):
        """Grab the selected region, OCR it, and copy only the text — the editor
        never opens and the image is not put on the clipboard."""
        self._last_phys = phys              # remember it for "repeat last area"
        grab = (lambda: frozen) if frozen is not None else (lambda: grab_region(*phys))

        def go():
            img = grab()
            if img is None:
                return
            self._flash_note(t("st_ocr_running"))
            self._grab_ocr(img)
        self._grab_with_delay(go)

    def _grab_ocr(self, img):
        """Background OCR for the text-grab action. Reuses the configured language,
        layout and enhancement but runs its own worker, so the editor's serial/toast/
        text-box state is untouched."""
        worker = OCRWorker(img, self.lang.currentText(), self.psm.currentData(),
                           self.enhance.isChecked(), automatic=True, parent=self)
        self._ocr_workers.append(worker)
        worker.result.connect(self._on_grab_ocr_result)
        worker.finished.connect(lambda: self._release_ocr_worker(worker))
        worker.start()

    def _on_grab_ocr_result(self, txt, error):
        if error:
            self._flash_note(error)
            return
        text = (txt or "").strip()
        if not text:
            self._flash_note(t("st_ocr_none"))
            return
        QtWidgets.QApplication.clipboard().setText(text)
        n = len(text)
        self._flash_note(f"Copied {n} chars" if _LANG == "en" else f"已复制 {n} 字符")

    def _pin_ocr(self, bgr):
        """Re-OCR a pinned image: same headless path as text-grab (clipboard + toast)."""
        self._flash_note(t("st_ocr_running"))
        self._grab_ocr(bgr)

    def _disable_pin_passthrough(self):
        """Tray escape hatch: a click-through pin receives no input, so the tray is
        the only way back when more than one pin is involved."""
        for p in list(PinnedImage._pins):
            if p._click_through:
                p._toggle_click_through(False)

    def _flash_note(self, msg):
        """Standalone on-top toast for actions that never open the editor (the editor's
        own _toast lives inside the OCR text box and would be invisible here)."""
        note = _make_hint(msg)
        note.show()
        self._flash_notes = [w for w in getattr(self, "_flash_notes", [])
                             if w.isVisible()]          # drop faded ones, keep refs live
        self._flash_notes.append(note)
        QtCore.QTimer.singleShot(2600, note.close)


    # --- delay countdown --- #
    def _grab_with_delay(self, grab_fn):
        delay = self.delay.value()
        if delay <= 0:
            grab_fn()
            return
        self._cd_left = delay
        self._cd_hint = _make_hint(f"Capturing in {self._cd_left}s…")
        self._cd_hint.show()
        self._cd_timer = QtCore.QTimer(self)
        self._cd_timer.setInterval(1000)

        def tick():
            self._cd_left -= 1
            if self._cd_left <= 0:
                self._cd_timer.stop()
                self._cd_hint.close()
                grab_fn()
            else:
                self._cd_hint.setText(f"Capturing in {self._cd_left}s…")
                self._cd_hint.adjustSize()
        self._cd_timer.timeout.connect(tick)
        self._cd_timer.start()

    # --- window capture --- #
    def capture_window(self):
        if self._unfinished_capture():
            return
        if not self.settings.value("capture_keep_main", False, type=bool) and self._settings_dialog is None:
            self.showMinimized()
        if getattr(self, "_thumb", None):
            self._thumb.close()
        QtCore.QTimer.singleShot(300, self._begin_window_pick)

    def _begin_window_pick(self):
        self._win_hint = _make_hint("Click the window to capture (right-click to cancel)")
        self._win_hint.show()
        self._wpicker = WindowPicker(self)
        self._wpicker.picked.connect(self._on_window_picked)
        self._wpicker.start()

    def _on_window_picked(self, geom):
        if getattr(self, "_win_hint", None):
            self._win_hint.close()
        if geom is None:
            self._restore()
            self.status.setText("Window capture cancelled")
            return
        x, y, w, h = geom
        self._last_phys = geom
        dpr=QtWidgets.QApplication.primaryScreen().devicePixelRatio()
        self._capture_rect=QRect(int(x/dpr),int(y/dpr),int(w/dpr),int(h/dpr))
        self._grab_with_delay(
            lambda: self._present_capture(
                self._freeze_region((x,y,w,h)), f"Window captured: {w}×{h} px"))

    # --- repeat last area --- #
    def repeat_last(self):
        if self._unfinished_capture():
            return
        if not getattr(self, "_last_phys", None):
            self.status.setText("No previous area yet")
            return
        phys = self._last_phys
        dpr=QtWidgets.QApplication.primaryScreen().devicePixelRatio()
        self._capture_rect=QRect(*(int(v/dpr) for v in phys))
        if not self.settings.value("capture_keep_main", False, type=bool) and self._settings_dialog is None:
            self.showMinimized()
        if getattr(self, "_thumb", None):
            self._thumb.close()
        QtCore.QTimer.singleShot(250, lambda: self._present_capture(
            self._freeze_region(phys), f"Repeated last area: {phys[2]}×{phys[3]} px"))

    # --- screen color picker --- #
    def pick_color_screen(self):
        if self._unfinished_capture():
            return
        self.showMinimized()
        if getattr(self, "_thumb", None):
            self._thumb.close()
        QtCore.QTimer.singleShot(250, self._begin_color_pick)

    def _begin_color_pick(self):
        self.selector = RegionSelector(mode="color")
        self.selector.colorPicked.connect(self._on_color_picked)
        self.selector.cancelled.connect(self._restore)
        self.selector.show()
        self.selector.activateWindow()
        self.selector.raise_()

    def _on_color_picked(self, col):
        hexv = col.name().upper()
        rgb = (col.red(), col.green(), col.blue())
        QtWidgets.QApplication.clipboard().setText(hexv)
        self._restore()
        self.status.setText(f"Picked {hexv}  rgb{rgb}, copied to clipboard")

    def _start_auto_scroll(self, direction):
        self._scroll_direction = direction
        self.start_select("scroll")

    def _scroll_shot(self, phys, dpr, gr=None):
        self._start_scroll_worker(phys, gr or QRect(*phys), dpr, manual=False)

    def _start_scroll_worker(self, phys, gr, dpr, manual):
        self._capture_background = None
        if self.worker is not None and self.worker.isRunning():
            return
        self.status.setText(t("hud_manual" if manual else "hud_auto") + " · Esc")
        self._scroll_overlay = ScrollRegionOverlay(gr)
        self._scroll_hud = ScrollHud(gr, self._auto_scroll_stop,
                                     mode="manual" if manual else "auto")
        self._scroll_hud.show_on_top()
        self.worker = CaptureWorker(phys, scroll_clicks=self.speed.value(),
                                    manual=manual, direction=self._scroll_direction)
        self.worker.dpr = dpr
        # Both modes keep their shadow-free, outside-region controls visible.
        # Mapping/unmapping per frame causes blinking and interrupts stop clicks.
        self.worker.hide_ui_for_grab = False
        self.worker.preparing_grab.connect(self._prepare_scroll_grab)
        self.worker.grabbed.connect(self._show_scroll_controls)
        self.worker.progress.connect(self._scroll_progress)
        self.worker.frame.connect(self._scroll_hud.set_image)
        self.worker.finished_img.connect(self._on_capture_done)
        self._scroll_message = ""
        try:
            self.scroll_stop_requested.disconnect(self._auto_scroll_stop)
        except TypeError:
            pass
        self.scroll_stop_requested.connect(self._auto_scroll_stop)
        self._scroll_keys = KeyListener(on_press=self._scroll_key_pressed)
        try:
            self._scroll_keys.start()
            self._scroll_keys.wait()
        except Exception as exc:
            self._close_scroll_hud()
            self.status.setText(f"Cannot start capture stop key: {exc}")
            self._restore()
            return
        self.worker.start()

    def _scroll_key_pressed(self, key):
        if key == Key.esc:
            self.scroll_stop_requested.emit()

    def _prepare_scroll_grab(self):
        worker = self.worker
        if worker is None or worker._abort:
            return
        if self._scroll_hud is not None:
            self._scroll_hud.hide()
        if self._scroll_overlay is not None:
            for window in self._scroll_overlay._wins:
                window.hide()
        # Let the compositor remove both the windows and their shadows before
        # the background thread reads the framebuffer.
        QtCore.QTimer.singleShot(100, worker.grab_ready.set)

    def _show_scroll_controls(self):
        if self.worker is None or self.worker._abort:
            return
        if self._scroll_overlay is not None:
            for window in self._scroll_overlay._wins:
                window.show()
        if self._scroll_hud is not None:
            self._scroll_hud.show_on_top()

    def _scroll_progress(self, message):
        self._scroll_message = message
        self.status.setText(message)
        if self._scroll_hud is not None:
            self._scroll_hud.lbl.setText(message)

    def _close_scroll_hud(self):
        listener = getattr(self, "_scroll_keys", None)
        if listener is not None:
            if listener.running:
                try:
                    listener.stop()
                except ConnectionClosedError:
                    pass  # The listener may already have closed its XRecord connection.
            self._scroll_keys = None
        for attr in ("_scroll_hud", "_scroll_overlay"):
            widget = getattr(self, attr, None)
            if widget is not None:
                widget.close()
                widget.deleteLater()
            setattr(self, attr, None)

    def _auto_scroll_stop(self):
        if self.worker is not None:
            self.worker.abort()

    def _on_capture_done(self, img):
        self._close_scroll_hud()
        message = getattr(self, "_scroll_message", "")
        if img is None:
            self.status.setText(message or "Capture cancelled")
            self._restore()
        else:
            self._present_capture(img, f"Long capture: {img.shape[1]}×{img.shape[0]} px")
            if message in (t("scroll_unmatched"), t("scroll_manual_unmatched")) \
                    or message.startswith("Error:"):
                self.status.setText(message)

    def _manual_start(self, phys, gr):
        self._start_scroll_worker(phys, gr, 1.0, manual=True)

    def _manual_stop(self):
        self._auto_scroll_stop()

    # --- after capture: copy to clipboard by default + bottom-left floating thumbnail --- #
    def _present_capture(self, img, status):
        if self._unfinished_capture():
            return
        if self.settings.value('inline_edit',True,type=bool) and not self.settings.value('open_editor',False,type=bool):
            if self._inline_editor is not None:
                self._inline_editor.close()
            if getattr(self,'_thumb',None):
                self._thumb.close()
            if self._settings_dialog is None:
                self.hide()
            self._inline_editor = InlineCaptureEditor(img,self._capture_rect,
                lambda action,canvas:self._finish_inline(action,canvas,status),self._settings_dialog or self,
                background=self._capture_background)
            self._inline_editor.action_buttons['record'].setToolTip(t('cap_record') + (' · 设置帧率、分辨率和时长' if _LANG == 'zh' else ' · Frame rate, resolution and duration'))
            self._inline_editor.dismissed.connect(self._inline_closed)
            return
        self._commit_capture(img,status)

    def _inline_closed(self):
        self._inline_editor = None

    def _finish_inline(self, action, canvas, status):
        editor=self._inline_editor
        if editor is not None and editor._region is not None:
            self._capture_rect=QRect(editor._region)
            dpr=(editor.dpr if editor._background is not None
                 else QtWidgets.QApplication.primaryScreen().devicePixelRatio())
            gr=QRect(editor._region)
            phys=(round(gr.x()*dpr),round(gr.y()*dpr),round(gr.width()*dpr),round(gr.height()*dpr))
            self._last_phys=phys
            if action in ('scroll','record'):
                if action == 'scroll':
                    QtCore.QTimer.singleShot(180,lambda:self._manual_start(phys,gr))
                else:
                    return self._start_record(gr)
                return True
        image=canvas.render_flattened()
        if action == 'save':
            path,_=QtWidgets.QFileDialog.getSaveFileName(self._inline_editor,t('dlg_save'),
                                                       self._make_filename(),'PNG (*.png);;JPEG (*.jpg)')
            if not path:
                return False
            if not image.save(path):
                self._inline_editor.tools.note.setText(t('save_failed'))
                return False
        state=canvas.snapshot_document()
        self._add_history(image,status)
        if action == 'copy' or self.settings.value('auto_copy',True,type=bool):
            QtWidgets.QApplication.clipboard().setImage(image)
        if action != 'save' and self.settings.value('auto_save',False,type=bool):
            self._auto_save(qimage_to_bgr(image))
        self._load_document(state,show=action == 'editor')
        if action == 'pin':
            self._new_pin(image,state)
        if action == 'editor' and self.settings.value('auto_ocr',True,type=bool):
            self.run_ocr(copy_result=False)
        return True

    def _commit_capture(self, img, status):
        self._ocr_serial += 1          # an older OCR result must not replace this capture
        self._add_history(bgr_to_qimage(img), status)
        # default behavior: copy image to clipboard (auto_copy on by default)
        copied = self.settings.value("auto_copy", True, type=bool)
        if copied:
            QtWidgets.QApplication.clipboard().setImage(bgr_to_qimage(img))
        if self.settings.value("auto_save", False, type=bool):
            self._auto_save(img)
        self.status.setText(status + ("  " + t("st_copied") if copied else ""))
        # Auto OCR needs the captured image in the editor to display its result, but it
        # does not have to be on screen: show the window only when open_editor is on.
        auto_ocr = self.settings.value("auto_ocr", True, type=bool)
        show = self.settings.value("open_editor", False, type=bool)
        if auto_ocr or show:
            self._load_into_editor(img, show=show)
        self._show_thumbnail(img)
        if auto_ocr:
            QtCore.QTimer.singleShot(0, lambda captured=img: self._auto_ocr_for(captured))

    def _add_history(self, qimg, desc):
        qimg = QtGui.QImage(qimg)
        qimg.setText("captured_at", QtCore.QDateTime.currentDateTime().toString(Qt.ISODate))
        qimg.setText("timestamp_source", "capture")
        history = self._pending_history.get('screenshots', self.history)
        history.insert(0, (qimg, desc))
        history[:] = self._history_store.bounded_entries('screenshots', history)
        self._history_writer.submit_screenshots(history)

    # --- system-clipboard image history: source for Ctrl+1 / Ctrl+2 pin ---- #
    def _on_clipboard_changed(self):
        """Track images copied from ANY app; newest first, capped at 10. Skips our own writes."""
        mime = QtWidgets.QApplication.clipboard().mimeData()
        if not mime.hasImage():
            return
        qimg = QtGui.QImage(mime.imageData()).convertToFormat(QtGui.QImage.Format_ARGB32)
        if qimg.isNull():
            return
        images = self._pending_history.get('clipboard', self._clip_images)
        if images and images[0] == qimg:
            return
        images.insert(0, qimg)
        images[:] = self._history_store.bounded_entries('clipboard', images)
        self._history_writer.submit_clipboard(images)

    def _pin_from_clipboard(self, index):
        """Pin clipboard-history image at index (0 = current, 1 = previous). No-op if missing."""
        if index >= len(self._clip_images):
            self.status.setText(t("st_no_clip_img"))
            return
        self._new_pin(self._clip_images[index])
        self.status.setText(t("st_pinned_clip"))

    def _ensure_default_shortcuts(self):
        """Self-heal the GNOME shortcut registration (startup + one delayed retry).

        Something outside Kapture keeps emptying the master custom-keybindings
        array around login, which silently kills every shortcut even though the
        per-action bindings stay stored (the recurring "Alt+` works only after
        opening settings" symptom: saving in settings re-registers the paths).
        Re-register every stored binding on startup — an existing binding is
        rewritten with its own value (no-op for the user) and its path is put
        back into the master array — then repeat once after the session settles
        in case GNOME's login-time sync races and clobbers the array again.
        Unbound actions in DEFAULT_KEYS are registered with their defaults;
        a user's own choice is never overwritten.
        """
        if shortcut_backend() != "gnome":
            return
        run_sh = _run_sh_path()
        entries = []
        for name, flag in SHORTCUT_ACTIONS:
            key = gnome_current_key(flag)
            if not key and flag in DEFAULT_KEYS:
                key = gnome_accelerator(QtGui.QKeySequence(DEFAULT_KEYS[flag]))
            entries.append((name, flag, f"{run_sh} {flag}", key))
        gnome_set_shortcuts(entries)
        if not getattr(self, "_shortcut_healed_once", False):
            self._shortcut_healed_once = True
            QtCore.QTimer.singleShot(6000, self._ensure_default_shortcuts)

    def _auto_save(self, img):
        import os
        d = self.settings.value("save_dir", os.path.expanduser("~/Pictures"))
        os.makedirs(d, exist_ok=True)
        name = self._make_filename()
        path = os.path.join(d, name)
        cv2.imwrite(path, img)
        self.status.setText(self.status.text() + f"  auto-saved to {path}")

    def _make_filename(self):
        """Build a filename from the template; supports {date}{time}{n}."""
        import datetime
        tmpl = self.settings.value("name_tmpl", "Kapture_{date}_{time}")
        now = datetime.datetime.now()
        n = int(self.settings.value("counter", 0, type=int)) + 1
        self.settings.setValue("counter", n)
        name = (tmpl.replace("{date}", now.strftime("%Y%m%d"))
                    .replace("{time}", now.strftime("%H%M%S"))
                    .replace("{n}", str(n)))
        return name + ".png"

    def _show_thumbnail(self, img):
        if getattr(self, "_thumb", None):
            self._thumb.close()
        qimg = bgr_to_qimage(img)
        # Bind callbacks to this specific image, not self.image_bgr (the main window may be blank)
        self._thumb = FloatingThumbnail(
            qimg,
            on_edit=lambda: self._load_into_editor(img),
            on_copy=lambda: QtWidgets.QApplication.clipboard().setImage(
                bgr_to_qimage(img)),
            on_save=lambda: self._quick_save(img),
            on_pin=lambda: self._new_pin(bgr_to_qimage(img)))
        self._thumb.show()
        self._thumb.raise_()

    def _quick_save(self, img):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, t("dlg_save"), self._make_filename(), "PNG (*.png);;JPEG (*.jpg)")
        if path:
            cv2.imwrite(path, img)
            self.status.setText(("Saved: " if _LANG == "en" else "已保存:") + path)

    def _load_into_editor(self, img, show=True):
        """Load the given screenshot into the editor. With show=False it loads silently
        (auto-OCR works on it) and the window only appears when the user opens it."""
        self._ocr_serial += 1
        self.image_bgr = img
        self._ocr_image_shown = False
        self.canvas.clear()
        if show:
            self.showNormal()
            self._show_preview()
            self.activateWindow()
            self.raise_()

    def _blank_editor(self):
        """Reset the editor to a blank state (so opening the main window doesn't show the last screenshot)."""
        self._ocr_serial += 1
        self.image_bgr = None
        self.canvas.clear()
        self.text.clear()
        self._ocr_pending = None
        self._ocr_image_shown = False
        self.status.setText(t("st_ready"))

    def _open_editor(self):
        if self.image_bgr is None:
            return
        self.showNormal()
        self._show_preview()
        self.activateWindow()
        self.raise_()

    # --- preview --- #
    def _show_preview(self):
        if self.image_bgr is None:
            return
        if self.canvas.base is None or not self._ocr_image_shown:
            self.canvas.blockSignals(True)
            self.canvas.set_image_bgr(self.image_bgr)
            self.canvas.blockSignals(False)
            self._canvas_base_key = self.canvas.base.cacheKey()
        self.canvas.fit_width(self.scroll.viewport().width())
        self._ocr_image_shown = True
        # Release any automatic OCR result that finished before the image was on screen.
        if self._ocr_pending and self._ocr_pending[0] == self._ocr_serial:
            _serial, txt = self._ocr_pending
            self._ocr_pending = None
            self.text.setPlainText(txt)

    def _ensure_word_boxes(self):
        """picktext clicked before any OCR ran: recognize the whole image once
        so word boxes exist for cursor selection."""
        if self.image_bgr is None:
            return
        if self.canvas._word_boxes or getattr(self, "_words_inflight", False):
            return
        self._words_inflight = True
        self._toast(t("st_ocr_running"))
        self.run_ocr(copy_result=False)

    def _on_text_selected(self, words_text):
        """picktext release: the user dragged over recognized words — copy them."""
        QtWidgets.QApplication.clipboard().setText(words_text)
        self.text.setPlainText(words_text)
        n = len(words_text)
        self._toast((f"Copied {n} chars" if _LANG == "en" else f"已复制 {n} 字符"))

    def _toast(self, msg):
        """Transient note floating in the bottom-right of the OCR text box;
        fades away by itself (the status bar stays clean)."""
        tip = getattr(self, "_toast_lbl", None)
        if tip is None:
            tip = QtWidgets.QLabel(self.text)
            tip.setObjectName("ocrToast")
            tip.setAlignment(Qt.AlignCenter)
            tip.setStyleSheet(
                "QLabel#ocrToast{background:rgba(40,40,48,215);color:#e8e8ec;"
                "border-radius:6px;padding:5px 12px;}")
            tip.setAttribute(Qt.WA_TransparentForMouseEvents)
            tip.setGraphicsEffect(QtWidgets.QGraphicsOpacityEffect(tip))
            self._toast_lbl = tip
            self.text.installEventFilter(self)
        tip.setText(msg)
        tip.adjustSize()
        self._place_toast()
        tip.show()
        eff = tip.graphicsEffect()
        eff.setOpacity(1.0)
        anim = QtCore.QPropertyAnimation(eff, b"opacity", tip)
        anim.setDuration(4000)
        anim.setStartValue(1.0)
        anim.setKeyValueAt(0.55, 1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(lambda: tip.hide())
        anim.start()
        self._toast_anim = anim          # keep a reference while running

    def _place_toast(self):
        tip = getattr(self, "_toast_lbl", None)
        if tip is None:
            return
        vp = self.text.viewport()
        tip.move(vp.width() - tip.width() - 12, vp.height() - tip.height() - 10)

    def eventFilter(self, obj, ev):
        if obj is self.text and ev.type() == QtCore.QEvent.Resize:
            self._place_toast()
        if obj in (self._ocr_panel,self.text.viewport()) and ev.type()==QtCore.QEvent.Resize:
            self._place_ocr_btns()
        return super().eventFilter(obj, ev)

    def _place_ocr_btns(self):
        self._ocr_btns.adjustSize()
        viewport=self.text.viewport()
        corner=viewport.mapTo(self._ocr_panel,QtCore.QPoint(viewport.width(),0))
        self._ocr_btns.move(max(2,corner.x()-self._ocr_btns.width()-4),corner.y()+3)
        self._ocr_btns.raise_()

    def _update_ocr_btns(self):
        """Show 全部识别/全部复制 only while the OCR box actually holds text."""
        has = bool(self.text.toPlainText().strip())
        self._ocr_btns.setVisible(has)
        if has:self._place_ocr_btns()

    def _do_crop(self, rectf):
        self.canvas.crop_image(rectf)
        self.canvas.fit_width(self.scroll.viewport().width())

    def pick_color(self):
        c = QtWidgets.QColorDialog.getColor(self.canvas.color, self, t("dlg_pickcolor"))
        if c.isValid():
            self.canvas.set_color(c)
            self.btn_color.setIcon(swatch_icon(c))

    # --- OCR --- #
    def _auto_ocr_for(self, img):
        if self.image_bgr is img:
            self.run_ocr(copy_result=False)

    def run_ocr(self, copy_result=True, img=None):
        img = self.image_bgr if img is None else img
        if img is None:
            self.status.setText(t("st_need_shot"))
            return
        self._ocr_serial += 1
        serial = self._ocr_serial
        self._toast(t("st_ocr_running"))       # OCR chatter lives in the OCR box, not the status bar
        worker = OCRWorker(img, self.lang.currentText(),
                           self.psm.currentData(), self.enhance.isChecked(),
                           automatic=not copy_result, parent=self)
        self._ocr_workers.append(worker)
        worker.result.connect(
            lambda txt, error: self._on_ocr_result(serial, txt, error, copy_result))
        worker.wordsReady.connect(lambda words: self._on_words_ready(words) if serial == self._ocr_serial else None)
        worker.finished.connect(lambda: self._release_ocr_worker(worker))
        worker.start()

    def _on_words_ready(self, words):
        self._words_inflight = False
        if self.image_bgr is not None and words:
            self.canvas.set_word_boxes(words)
            if self._ocr_image_shown:
                self._toast(f"{len(words)} 个可取词" if _LANG == "zh"
                            else f"{len(words)} selectable words")

    def _release_ocr_worker(self, worker):
        self._ocr_workers.remove(worker)
        worker.deleteLater()

    def _on_ocr_result(self, serial, txt, error, copy_result):
        if serial != self._ocr_serial:
            return
        if error:
            if self._ocr_image_shown:
                self._toast(error)
            return
        if copy_result:
            QtWidgets.QApplication.clipboard().setText(txt)
        if not copy_result and not self._ocr_image_shown:
            # Background capture: the editor is not on screen — stay silent and
            # hold the text until the user actually opens the image.
            self._ocr_pending = (serial, txt)
            return
        if _LANG == "en":
            self._toast(f"OCR done{' and copied' if copy_result else ''} ({len(txt)} chars)")
        else:
            self._toast(f"OCR 完成{'，已复制文字' if copy_result else ''}（{len(txt)} 字符）")
        self.text.setPlainText(txt)

    def _copy_all_text(self):
        """Copy the whole OCR text box to the clipboard (bottom-left OCR box button)."""
        txt = self.text.toPlainText().strip()
        if not txt:
            self._toast(t("st_ocr_none"))
            return
        QtWidgets.QApplication.clipboard().setText(txt)
        n = len(txt)
        self._toast(f"Copied {n} chars" if _LANG == "en" else f"已复制 {n} 字符")

    # --- copy image to clipboard --- #
    def copy_image(self):
        if self.image_bgr is None:
            self.status.setText(t("st_need_shot"))
            return
        flat = self.canvas.render_flattened()   # with annotations
        if flat is None:
            self.status.setText("No image to copy")
            return
        QtWidgets.QApplication.clipboard().setImage(flat)
        n = len(self.canvas.items)
        extra = (f" ({n} annotations)" if _LANG == "en" else f"(含 {n} 处标注)") if n else ""
        self.status.setText(
            (f"Image copied to clipboard{extra}, ready to paste "
             f"({flat.width()}×{flat.height()} px)") if _LANG == "en" else
            (f"图片已复制到剪贴板{extra},可直接粘贴 "
             f"({flat.width()}×{flat.height()} px)"))

    # --- pin to screen --- #
    def pin_image(self):
        if self.image_bgr is None:
            self.status.setText(t("st_need_shot"))
            return
        flat = self.canvas.render_flattened()
        if flat is None:
            return
        self._new_pin(flat, self.canvas.snapshot_document())
        self.status.setText(t("st_pinned"))

    # --- save --- #
    def save_image(self):
        if self.image_bgr is None:
            self.status.setText(t("st_need_shot"))
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, t("dlg_save"), "screenshot.png", "PNG (*.png);;JPEG (*.jpg)")
        if not path:
            return
        flat = self.canvas.render_flattened()   # image with annotations merged in
        if flat is not None and flat.save(path):
            self.status.setText(("Saved: " if _LANG == "en" else "已保存:") + path)
        else:
            self.status.setText(("Save failed: " if _LANG == "en" else "保存失败:") + path)

    # ===================== P4: tray / settings / history ===================== #
    def _setup_tray(self):
        self.tray = QtWidgets.QSystemTrayIcon(self)
        import os
        ip = _icon_path()
        icon = (QtGui.QIcon(ip) if os.path.exists(ip)
                else self.style().standardIcon(QtWidgets.QStyle.SP_DesktopIcon))
        self.tray.setIcon(icon)
        self.setWindowIcon(icon)
        self.tray.activated.connect(
            lambda r: self.handle_command("show")
            if r == QtWidgets.QSystemTrayIcon.Trigger else None)
        self._build_tray_menu()
        self.tray.show()

    def _build_tray_menu(self):
        menu = QtWidgets.QMenu()
        menu.addAction(t("cap_region"), lambda: self.handle_command("single"))
        menu.addAction(t("cap_window"), lambda: self.handle_command("window"))
        menu.addAction(t("cap_color"), lambda: self.handle_command("color"))
        menu.addAction(t("cap_record"), self.toggle_record)
        menu.addSeparator()
        menu.addAction(t("tray_show"), lambda: self.handle_command("show"))
        menu.addAction(t("t_settings"), lambda: self.handle_command("settings"))
        menu.addAction(t("tray_undo_clickthrough"), self._disable_pin_passthrough)
        menu.addSeparator()
        menu.addAction(t("tray_quit"), self.quit_app)
        self._tray_menu = menu          # keep a reference to prevent GC
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(f"{t('app_name')} — {t('app_comment')}")

    def quit_app(self):
        export_dialog = getattr(self, '_record_export', None)
        if export_dialog is not None:
            export_dialog.raise_(); export_dialog.activateWindow(); return
        if getattr(self, "_record_pending", None):
            self._on_record_stop()
        if self.worker is not None and self.worker.isRunning():
            self.worker.abort()
            self.worker.wait()
        self._close_scroll_hud()
        if self._recorder is not None:
            self._quit_after_record=True
            self._on_record_stop()
            return
        for worker in self._ocr_workers:
            worker.wait()
        QtWidgets.QApplication.quit()

    def show_settings(self):
        if self._settings_dialog is not None:
            self._settings_dialog.raise_(); self._settings_dialog.activateWindow(); return
        import os
        s = self.settings
        backend = shortcut_backend()
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(t("set_title"))
        dlg.resize(560, 470)
        outer = QtWidgets.QVBoxLayout(dlg)
        tabs = QtWidgets.QTabWidget()
        outer.addWidget(tabs)

        # ---------- General ---------- #
        g = QtWidgets.QWidget(); g.setObjectName("settingsPage"); gf = QtWidgets.QFormLayout(g)
        save_dir = QtWidgets.QLineEdit(s.value("save_dir", os.path.expanduser("~/Pictures")))
        browse = QtWidgets.QPushButton(t("set_browse"))
        browse.clicked.connect(lambda: save_dir.setText(
            QtWidgets.QFileDialog.getExistingDirectory(dlg, t("dlg_savedir")) or save_dir.text()))
        hb = QtWidgets.QHBoxLayout(); hb.addWidget(save_dir); hb.addWidget(browse)
        gf.addRow(t("set_savedir"), hb)
        tmpl = QtWidgets.QLineEdit(s.value("name_tmpl", "Kapture_{date}_{time}"))
        tmpl.setToolTip("{date} {time} {n}")
        gf.addRow(t("set_tmpl"), tmpl)
        cb_copy = QtWidgets.QCheckBox(t("set_autocopy")); cb_copy.setChecked(s.value("auto_copy", True, type=bool))
        cb_save = QtWidgets.QCheckBox(t("set_autosave")); cb_save.setChecked(s.value("auto_save", False, type=bool))
        cb_edit = QtWidgets.QCheckBox(t("set_openeditor")); cb_edit.setChecked(s.value("open_editor", False, type=bool))
        cb_inline = QtWidgets.QCheckBox(t('set_inline'))
        cb_inline.setChecked(s.value('inline_edit',True,type=bool))
        cb_capture_keep_main = QtWidgets.QCheckBox(t("set_capture_keep_main"))
        cb_capture_keep_main.setObjectName("captureKeepMain")
        cb_capture_keep_main.setChecked(s.value("capture_keep_main", False, type=bool))
        cb_background = QtWidgets.QCheckBox(t("set_start_hidden"))
        cb_background.setChecked(s.value("start_hidden", False, type=bool))
        cb_snap = QtWidgets.QCheckBox(t("set_snap_windows"))
        cb_snap.setChecked(s.value("snap_windows", True, type=bool))
        for cb in (cb_copy, cb_save, cb_edit, cb_inline, cb_capture_keep_main, cb_background, cb_snap):
            gf.addRow(cb)
        tabs.addTab(g, t("tab_general"))

        # ---------- Shortcuts ---------- #
        k = QtWidgets.QWidget(); k.setObjectName("settingsPage"); kf = QtWidgets.QFormLayout(k)
        kf.addRow(QtWidgets.QLabel(t("set_sc_hint")))
        run_sh = _run_sh_path()
        key_edits = {}
        cleared = set()      # rows whose ✕ was clicked: the only way to unbind
        for name, flag in SHORTCUT_ACTIONS:
            cmd_url = f"{run_sh} {flag}"
            kse = QtWidgets.QKeySequenceEdit()
            cur = (kde_current_key(cmd_url) if backend == "kde" else
                   gnome_current_key(flag) if backend == "gnome" else "")
            if cur:
                kse.setKeySequence(gnome_key_sequence(cur) if backend == "gnome"
                                   else QtGui.QKeySequence(cur))
            elif flag in DEFAULT_KEYS:
                # Pre-fill the advertised default even before it is registered, so the
                # pin-to-clipboard shortcuts are visible out of the box.
                kse.setKeySequence(QtGui.QKeySequence(DEFAULT_KEYS[flag]))
            clr = QtWidgets.QToolButton(); clr.setText("✕")
            clr.clicked.connect(lambda _, e=kse, f=flag: (e.clear(), cleared.add(f)))
            row = QtWidgets.QHBoxLayout(); row.addWidget(kse); row.addWidget(clr)
            rw = QtWidgets.QWidget(); rw.setLayout(row)
            kf.addRow(self._action_label(flag), rw)
            key_edits[flag] = (kse, cmd_url, name)
        if backend is None:
            kf.addRow(QtWidgets.QLabel(t("set_sc_unavailable")))
            for name, flag in SHORTCUT_ACTIONS:
                kf.addRow(self._action_label(flag), QtWidgets.QLabel(f"{run_sh} {flag}"))
            for edit, _, _ in key_edits.values():
                edit.setEnabled(False)
        shortcut_scroll = QtWidgets.QScrollArea()
        shortcut_scroll.setWidgetResizable(True)
        shortcut_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        shortcut_scroll.setWidget(k)
        tabs.addTab(shortcut_scroll, t("tab_shortcuts"))

        # ---------- OCR ---------- #
        o = QtWidgets.QWidget(); o.setObjectName("settingsPage"); of = QtWidgets.QFormLayout(o)
        lang = QtWidgets.QComboBox(); lang.addItems(["chi_sim+eng", "chi_sim", "chi_tra+eng", "eng"])
        lang.setCurrentText(s.value("ocr_lang", "chi_sim+eng"))
        psm = QtWidgets.QComboBox()
        for label, value in zip(self._psm_layout_labels(), (6, 3, 4, 7)):
            psm.addItem(label, value)
        pi = psm.findData(int(s.value("ocr_psm", 6, type=int)))
        if pi >= 0:
            psm.setCurrentIndex(pi)
        enh = QtWidgets.QCheckBox(t("set_ocr_enh"))
        enh.setChecked(s.value("ocr_enhance", True, type=bool))
        of.addRow(t("set_ocr_deflang"), lang); of.addRow(t("set_ocr_deflayout"), psm); of.addRow(enh)
        cb_autoocr = QtWidgets.QCheckBox(t("set_autoocr"))
        cb_autoocr.setChecked(s.value("auto_ocr", True, type=bool))
        of.addRow(cb_autoocr)
        of.addRow(QtWidgets.QLabel(t("set_ocr_note")))
        tabs.addTab(o, t("tab_ocr"))

        # ---------- Recording ---------- #
        r = QtWidgets.QWidget(); r.setObjectName("settingsPage"); rf = QtWidgets.QVBoxLayout(r)
        record_options = RecordingOptions(s, parent=r)
        rf.addWidget(record_options)
        rf.addWidget(QtWidgets.QLabel('每次录屏前可调整，结束后选择导出格式' if _LANG == 'zh'
                                      else 'Adjust before recording; choose the format after stopping'))
        tabs.addTab(r, t("tab_record"))

        # ---------- Interface ---------- #
        u = QtWidgets.QWidget(); u.setObjectName("settingsPage"); uf = QtWidgets.QFormLayout(u)
        theme = QtWidgets.QComboBox()
        for key, value in (("theme_system", "system"), ("theme_dark", "dark"),
                           ("theme_light", "light"), ("theme_starship", "starship"),
                           ("theme_one_dark_pro_darker", "one_dark_pro_darker"),
                           ("theme_vitesse_dark", "vitesse_dark")):
            theme.addItem(t(key), value)
        theme.setCurrentIndex(max(0, theme.findData(s.value("ui_theme", "dark"))))
        uf.addRow(t("set_theme"), theme)
        accent = QtWidgets.QComboBox()
        accents = [("acc_theme", "theme"), ("acc_indigo", "#6c5ce7"),
                   ("acc_blue", "#0a84ff"),
                   ("acc_teal", "#10b981"), ("acc_orange", "#f59e0b"),
                   ("acc_pink", "#ec4899")]
        for key, hexv in accents:
            accent.addItem(t(key), hexv)
        accent.setCurrentIndex(max(0, accent.findData(s.value("ui_accent", "theme"))))
        theme.currentIndexChanged.connect(lambda _: accent.setCurrentIndex(0))
        theme.currentIndexChanged.connect(
            lambda _: self._apply_style(theme.currentData(), accent.currentData()))
        accent.currentIndexChanged.connect(
            lambda _: self._apply_style(theme.currentData(), accent.currentData()))
        uf.addRow(t("set_accent"), accent)
        uf.addRow(QtWidgets.QLabel(t("set_theme_preview")))
        ui_lang = QtWidgets.QComboBox()
        ui_lang.addItem("中文", "zh"); ui_lang.addItem("English", "en")
        ui_lang.setCurrentIndex(0 if _LANG == "zh" else 1)
        ui_lang.currentIndexChanged.connect(
            lambda _index: self._localize_psm_combo(psm, ui_lang.currentData()))
        uf.addRow(t("set_uilang"), ui_lang)
        tabs.addTab(u, t("tab_ui"))

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        outer.addWidget(bb)

        self._settings_dialog = dlg
        try:
            accepted = dlg.exec_() == QtWidgets.QDialog.Accepted
        finally:
            self._settings_dialog = None
        if not accepted:
            self._apply_style()                      # discard the temporary preview
            return
        if backend:
            try:
                keys = {}
                for flag, (kse, _, _) in key_edits.items():
                    sequence = kse.keySequence()
                    portable = sequence.toString(QtGui.QKeySequence.PortableText)
                    if portable:
                        if portable in keys:
                            raise ValueError(t("set_sc_duplicate"))
                        keys[portable] = flag
                        if backend == "gnome":
                            gnome_accelerator(sequence)
                        elif sequence.count() != 1:
                            raise ValueError(t("set_sc_invalid"))
                if backend == "gnome":
                    gnome_set_shortcuts([
                        (name, flag, cmd_url,
                         gnome_accelerator(kse.keySequence())
                         if not kse.keySequence().isEmpty() else "",
                         flag in cleared)
                        for flag, (kse, cmd_url, name) in key_edits.items()])
                else:
                    kde_backup_khotkeys()
                    for flag, (kse, cmd_url, name) in key_edits.items():
                        key = kse.keySequence().toString(QtGui.QKeySequence.NativeText)
                        uuid_key = f"uuid_{flag}"
                        uid = s.value(uuid_key, "")
                        if not uid:
                            import uuid as _uuid
                            uid = "{" + str(_uuid.uuid4()) + "}"
                            s.setValue(uuid_key, uid)
                        kde_set_shortcut(name, cmd_url, key, uid)
                    kde_reload_shortcuts()
            except (ValueError, OSError, RuntimeError) as exc:
                self._apply_style()
                QtWidgets.QMessageBox.warning(self, t("tab_shortcuts"),
                                              str(exc) or t("set_sc_invalid"))
                return
            self.status.setText(
                (f"Settings saved, {len(keys)} shortcuts active on {backend.upper()}"
                 if _LANG == "en" else f"设置已保存，{len(keys)} 个快捷键已在 {backend.upper()} 启用"))
        else:
            self.status.setText(t("st_settings_saved"))
        # Save other preferences only after shortcuts have been validated and written.
        s.setValue("save_dir", save_dir.text())
        s.setValue("name_tmpl", tmpl.text())
        s.setValue("auto_copy", cb_copy.isChecked())
        s.setValue("auto_save", cb_save.isChecked())
        s.setValue("open_editor", cb_edit.isChecked())
        s.setValue("start_hidden", cb_background.isChecked())
        s.setValue("inline_edit", cb_inline.isChecked())
        s.setValue("capture_keep_main", cb_capture_keep_main.isChecked())
        s.setValue("snap_windows", cb_snap.isChecked())
        s.setValue("ocr_lang", lang.currentText())
        s.setValue("ocr_psm", psm.currentData())
        s.setValue("ocr_enhance", enh.isChecked())
        s.setValue("auto_ocr", cb_autoocr.isChecked())
        record_options.save(s)
        s.setValue("ui_theme", theme.currentData())
        s.setValue("ui_accent", accent.currentData())
        s.setValue("ui_lang", ui_lang.currentData())
        self.lang.setCurrentText(lang.currentText())
        self.psm.setCurrentIndex(self.psm.findData(psm.currentData()))
        self.enhance.setChecked(enh.isChecked())
        set_lang(ui_lang.currentData())
        write_desktop_entry(refresh=True)
        self._apply_style()
        self._retranslate()

    def _action_label(self, flag):
        return t({"--region": "cap_region", "--window": "cap_window",
                  "--scroll": "cap_scroll", "--manual": "cap_manual",
                  "--color": "cap_color", "--record": "cap_record",
                  "--repeat": "cap_repeat", "--show": "tray_show",
                  "--settings": "t_settings", "--pin1": "cap_pin1",
                  "--pin2": "cap_pin2"}.get(flag, "cap_region"))

    def _history_error(self, message):
        self.status.setText(message)
        self.tray.showMessage(t('app_name'), message, QtWidgets.QSystemTrayIcon.Warning)

    def _clear_history(self):
        if self._pending_history:
            return False
        self._history_clear_had_error = False
        self._pending_history = {'screenshots': [], 'clipboard': []}
        if not self._history_writer.clear():
            self._pending_history.clear()
            return False
        self.status.setText(t('history_clearing'))
        return True

    def _history_cleared(self, collection):
        if collection not in self._pending_history:
            return
        images = self._pending_history.pop(collection)
        if collection == 'screenshots':
            self.history = images
        else:
            self._clip_images = images
        if not self._pending_history and not self._history_clear_had_error:
            self.status.setText(t('history_cleared'))

    def _history_clear_failed(self, collection):
        self._history_clear_had_error = True
        new = self._pending_history.pop(collection, [])
        if collection == 'screenshots':
            self.history = self._history_store.bounded_entries(collection, new + self.history)
            self._history_writer.submit_screenshots(self.history)
        else:
            self._clip_images = self._history_store.bounded_entries(collection, new + self._clip_images)
            self._history_writer.submit_clipboard(self._clip_images)

    def show_history(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"{t('hist_title')} ({len(self.history)})")
        dlg.resize(600, 560)
        v = QtWidgets.QVBoxLayout(dlg)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(16)
        header = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(
            f"最近 {len(self.history)} 张 · 最多保留 10 张" if _LANG == "zh"
            else f"{len(self.history)} recent · Up to 10 screenshots")
        header.addWidget(label)
        header.addStretch()
        clear = QtWidgets.QPushButton(t('clear_history'))
        clear.clicked.connect(lambda: dlg.accept() if self._clear_history() else None)
        header.addWidget(clear)
        v.addLayout(header)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        inner.setObjectName("historyGrid")
        grid = QtWidgets.QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        for index, (qimg, _desc) in enumerate(self.history):
            card = QtWidgets.QToolButton()
            card.setObjectName("historyCard")
            card.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            card.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(qimg.scaled(
                230, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))))
            card.setIconSize(QtCore.QSize(230, 140))
            title = f"截图 {index + 1}" if _LANG == "zh" else f"Screenshot {index + 1}"
            captured_at = QtCore.QDateTime.fromString(qimg.text("captured_at"), Qt.ISODate)
            stamp = captured_at.toLocalTime().toString("yyyy-MM-dd HH:mm:ss")
            card.setText(f"{title} · {qimg.width()} × {qimg.height()}\n{stamp}" if stamp
                         else f"{title}\n{qimg.width()} × {qimg.height()}")
            card.setToolTip("点击继续编辑" if _LANG == "zh" else "Click to edit")
            if qimg.text("timestamp_source") == "file":
                card.setToolTip(card.toolTip() + ("\n旧截图：显示文件保存时间" if _LANG == "zh"
                                                  else "\nOlder screenshot: file save time"))
            card.setMinimumSize(250, 196)
            card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            card.clicked.connect(lambda _, q=qimg: (self._load_history(q), dlg.accept()))
            grid.addWidget(card, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch((len(self.history) + 1) // 2, 1)
        if not self.history:
            empty = QtWidgets.QLabel("暂无截图" if _LANG == "zh" else "No screenshots yet")
            empty.setAlignment(Qt.AlignCenter)
            grid.addWidget(empty, 0, 0, 1, 2)
        scroll.setWidget(inner)
        v.addWidget(scroll)
        dlg.exec_()

    def _load_history(self, qimg):
        self._load_into_editor(qimage_to_bgr(qimg))
        self.status.setText("已打开历史截图" if _LANG == "zh" else "Loaded from history")

    # ===================== P5: beautify export ===================== #
    def _beautify_image(self):
        """Place the current (annotated) screenshot on a gradient background with rounded corners and a shadow; return a QImage."""
        flat = self.canvas.render_flattened()
        if flat is None:
            return None
        src = QtGui.QPixmap.fromImage(flat)
        pad, radius = 64, 18
        out_w, out_h = src.width() + pad * 2, src.height() + pad * 2
        out = QtGui.QImage(out_w, out_h, QtGui.QImage.Format_ARGB32)
        out.fill(Qt.transparent)
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        grad = QtGui.QLinearGradient(0, 0, out_w, out_h)
        grad.setColorAt(0, QtGui.QColor("#ff9a9e"))
        grad.setColorAt(1, QtGui.QColor("#a18cd1"))
        bg = QtGui.QPainterPath()
        bg.addRoundedRect(QtCore.QRectF(0, 0, out_w, out_h), 24, 24)
        p.fillPath(bg, grad)
        img_rect = QtCore.QRectF(pad, pad, src.width(), src.height())
        sh = QtGui.QPainterPath()
        sh.addRoundedRect(img_rect.translated(0, 8), radius, radius)
        p.fillPath(sh, QtGui.QColor(0, 0, 0, 90))
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(img_rect, radius, radius)
        p.setClipPath(clip)
        p.drawPixmap(int(pad), int(pad), src)
        p.end()
        return out

    def beautify_export(self):
        if self.image_bgr is None:
            self.status.setText(t("st_need_shot"))
            return
        out = self._beautify_image()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, t("dlg_beautify"), "beautified.png", "PNG (*.png)")
        if path and out is not None and out.save(path):
            self.status.setText(("Beautified export: " if _LANG == "en" else "已美化导出:") + path)

    # ===================== Recording ===================== #
    def toggle_record(self):
        active_dialog = getattr(self, '_record_export', None) or getattr(self, '_record_setup', None)
        if active_dialog is not None:
            active_dialog.raise_(); active_dialog.activateWindow(); return
        if self._recorder is not None or getattr(self, '_record_pending', None):
            self._on_record_stop()
            return
        if self._unfinished_capture():
            return
        self.showMinimized()
        if getattr(self, "_thumb", None):
            self._thumb.close()
        QtCore.QTimer.singleShot(300, self._begin_record_select)

    def _begin_record_select(self):
        self.selector = RegionSelector(mode="region")
        self.selector.hint_text=('Select recording region, Esc to cancel' if _LANG == 'en'
                                 else '框选录屏区域，Esc 取消')
        self.selector.selected.connect(self._start_record)
        self.selector.cancelled.connect(self._restore)
        self.selector.show()
        self.selector.activateWindow(); self.selector.raise_()

    def _start_record(self, gr, frozen=None):
        if self._recorder is not None or getattr(self, '_record_pending', None):
            return
        screen = QtWidgets.QApplication.screenAt(gr.center()) or QtWidgets.QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        phys = (int(gr.x()*dpr), int(gr.y()*dpr), int(gr.width()*dpr), int(gr.height()*dpr))
        phys = phys[:2] + (phys[2]-phys[2]%2, phys[3]-phys[3]%2)
        if min(phys[2:]) < 2:
            self._restore(); return
        gr = QRect(round(phys[0]/dpr), round(phys[1]/dpr), round(phys[2]/dpr), round(phys[3]/dpr))
        self._record_border = ScrollRegionOverlay(gr)
        dialog = RecordSetupBar(self.settings, phys[2:], gr, self)
        self._record_setup = dialog
        accepted = dialog.exec_() == QtWidgets.QDialog.Accepted
        self._record_setup = None
        if not accepted:
            self._close_record_controls()
            dialog.deleteLater()
            if self._inline_editor is None:
                self._restore()
            return False
        options = dialog.options.values()
        dialog.options.save(self.settings)
        dialog.deleteLater()
        self.hide()
        self._record_pending = (phys, gr, options)
        self._recbar = RecordBar(self._on_record_stop, gr, fps=options['fps'],
                                 output_size=options['output_size'], duration=options['duration'])
        self._recbar._t.stop()
        self._record_countdown_left = options['countdown']
        self._record_countdown = QtCore.QTimer(self)
        self._record_countdown.setInterval(1000)
        self._record_countdown.timeout.connect(self._record_countdown_tick)
        self._recbar.show_on_top()
        if self._record_countdown_left:
            self._recbar.set_countdown(self._record_countdown_left)
            self._record_countdown.start()
        else:
            # Give the setup toolbar a chance to leave the Xorg framebuffer.
            self._record_countdown.setInterval(180)
            self._record_countdown.start()
        return True

    def _record_countdown_tick(self):
        self._record_countdown_left -= 1
        if self._record_countdown_left > 0:
            self._recbar.set_countdown(self._record_countdown_left)
            return
        self._record_countdown.stop(); self._record_countdown.deleteLater()
        self._record_countdown = None
        pending = self._record_pending
        self._record_pending = None
        if pending:
            self._begin_recording(*pending)

    def _begin_recording(self, phys, gr, options):
        import tempfile
        from pathlib import Path
        try:
            self._record_temp = tempfile.mkdtemp(prefix='kapture-record-')
        except OSError as error:
            self._close_record_controls(); self._restore(); self.status.setText(str(error)); return
        self._rec_out = str(Path(self._record_temp) / 'recording.mp4')
        rec = Recorder(phys, self._rec_out, fps=options['fps'], parent=self,
                       output_size=options['output_size'], duration=options['duration'])
        self._recorder = rec
        rec.phase.connect(self._record_phase)
        rec.progress.connect(self._recbar.set_progress)
        rec.completed.connect(self._record_completed)
        self._recbar.start_timer()
        self.status.setText('Recording…' if _LANG == 'en' else '录屏中…')
        rec.start()

    def _record_phase(self, phase):
        if getattr(self, '_record_border', None):
            self._record_border.close(); self._record_border.deleteLater(); self._record_border = None
        if getattr(self, '_recbar', None):
            self._recbar.set_phase(phase)

    def _close_record_controls(self):
        for name in ('_record_border', '_recbar'):
            widget = getattr(self, name, None)
            if widget:
                widget.close(); widget.deleteLater(); setattr(self, name, None)

    def _on_record_stop(self):
        if getattr(self, '_record_pending', None):
            self._record_pending = None
            self._record_countdown.stop(); self._record_countdown.deleteLater()
            self._record_countdown = None
            self._close_record_controls(); self._restore()
        elif self._recorder is not None:
            self._recorder.stop()

    def _record_completed(self, path, error):
        import os
        import shutil
        from pathlib import Path
        rec = self._recorder
        self._recorder = None
        self._close_record_controls()
        self._restore()
        paths = []
        if path and not error:
            directory = self.settings.value('save_dir', os.path.expanduser('~/Videos'))
            filename = str(Path(self._make_filename()).with_suffix('.mp4'))
            if getattr(self, '_quit_after_record', False):
                try:
                    Path(directory).mkdir(parents=True, exist_ok=True)
                    target = Path(directory) / filename
                    # Exiting must retain the recording without asking for export settings.
                    if target.exists():
                        target = target.with_stem(target.stem + '-' + str(time.time_ns()))
                    shutil.copyfile(path, target)
                    paths = [str(target)]
                except OSError as exc:
                    error = str(exc)
            else:
                dialog = RecordExportDialog(path, rec.fps, rec._duration, directory, filename, self)
                self._record_export = dialog
                dialog.exec_()
                self._record_export = None
                paths = dialog.saved_paths
                dialog.deleteLater()
        if rec is not None:
            rec.deleteLater()
        if getattr(self, '_record_temp', None):
            if error:
                error += '\n' + self._record_temp
            else:
                shutil.rmtree(self._record_temp)
            self._record_temp = None
        if error:
            message = ('Recording/export failed: ' if _LANG == 'en' else '录制或导出失败：') + error
        elif paths:
            message = ('Saved: ' if _LANG == 'en' else '已保存：') + '\n'.join(paths)
        else:
            message = 'Recording discarded' if _LANG == 'en' else '已放弃录屏'
        self.status.setText(message)
        if paths or error:
            self.tray.showMessage(t('app_name'), message, QtWidgets.QSystemTrayIcon.Warning if error
                                  else QtWidgets.QSystemTrayIcon.Information, 6000)
        if getattr(self, '_quit_after_record', False):
            self.quit_app()


SERVER_NAME = "scrollshot-single-instance"


def main():
    import argparse
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket
    parser = argparse.ArgumentParser(
        description="Kapture -- scrolling screenshot + OCR + annotation")
    parser.add_argument("--region", action="store_true", help="go straight to region capture on launch")
    parser.add_argument("--manual", action="store_true", help="go straight to manual scrolling capture on launch")
    parser.add_argument("--scroll", action="store_true", help="go straight to auto scrolling capture on launch")
    parser.add_argument("--window", action="store_true", help="go straight to window capture on launch")
    parser.add_argument("--color", action="store_true", help="go straight to screen color picking on launch")
    parser.add_argument("--record", action="store_true", help="start or stop screen recording")
    parser.add_argument("--repeat", action="store_true", help="repeat the last selected area")
    parser.add_argument("--show", action="store_true", help="show the main window")
    parser.add_argument("--settings", action="store_true", help="open settings")
    parser.add_argument("--background", action="store_true", help="keep running with the main window hidden")
    parser.add_argument("--pin1", action="store_true", help="pin the current clipboard image to screen")
    parser.add_argument("--pin2", action="store_true", help="pin the previous clipboard image to screen")
    cli, _ = parser.parse_known_args()
    cmd = ("single" if cli.region else
           "manual" if cli.manual else
           "scroll" if cli.scroll else
           "window" if cli.window else
           "color" if cli.color else
           "record" if cli.record else
           "repeat" if cli.repeat else
           "pin1" if cli.pin1 else
           "pin2" if cli.pin2 else
           "settings" if cli.settings else
           "background" if cli.background else "show")

    # Single instance: if one is already running, send it the command and exit; never spawn a second process
    probe = QLocalSocket()
    probe.connectToServer(SERVER_NAME)
    if probe.waitForConnected(300):
        probe.write(cmd.encode())
        probe.flush()
        probe.waitForBytesWritten(500)
        probe.disconnectFromServer()
        return                                   # do not create a second process

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Kapture")
    app.setApplicationDisplayName("Kapture")
    app.setDesktopFileName("kapture")            # associate the taskbar entry with kapture.desktop
    import os as _os
    if _os.path.exists(_icon_path()):
        app.setWindowIcon(QtGui.QIcon(_icon_path()))
    app.setStyle("Fusion")                       # consistent base widget look

    class _FastTip(QtWidgets.QProxyStyle):
        """Shorter tooltip delay: 0.5 s instead of the ~1 s+ platform default."""
        def styleHint(self, hint, option=None, widget=None, returnData=None):
            if hint == QtWidgets.QStyle.SH_ToolTip_WakeUpDelay:
                return 500
            return super().styleHint(hint, option, widget, returnData)

    app.setStyle(_FastTip("Fusion"))
    # Dark tooltips via palette (avoid styling QToolTip in QSS, which clips the text)
    pal = app.palette()
    pal.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor("#2a2a31"))
    pal.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor("#e8e8ec"))
    app.setPalette(pal)
    app.setQuitOnLastWindowClosed(False)         # closing the editor window doesn't quit the process

    # Global exception fallback: show a dialog instead of letting the program die silently
    def _excepthook(etype, evalue, tb):
        import traceback
        msg = "".join(traceback.format_exception(etype, evalue, tb))
        sys.stderr.write(msg)
        try:
            QtWidgets.QMessageBox.critical(None, "Kapture", str(evalue))
        except Exception:                            # noqa: BLE001
            pass
    sys.excepthook = _excepthook

    win = MainWindow()

    # Register the default pin-to-clipboard shortcuts on GNOME (only the primary
    # instance reaches here; subsequent launches forward a command and exit).
    try:
        win._ensure_default_shortcuts()
    except (ValueError, OSError, RuntimeError):
        pass                                       # never block startup on shortcut registration

    # Start a local server to receive commands from subsequent launches
    QLocalServer.removeServer(SERVER_NAME)           # clear any stale socket
    server = QLocalServer()
    server.listen(SERVER_NAME)

    def on_conn():
        c = server.nextPendingConnection()
        if c.waitForReadyRead(500):
            win.handle_command(bytes(c.readAll()).decode().strip())
        c.disconnectFromServer()
    server.newConnection.connect(on_conn)

    initial = ("background" if cmd == "show" and
               win.settings.value("start_hidden", False, type=bool) and not cli.show
               else cmd)
    win.handle_command(initial)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
