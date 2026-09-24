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

import cv2
import numpy as np
from PIL import Image

import mss
from pynput.mouse import Controller as MouseController

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QRect, QThread, pyqtSignal


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


def set_lang(code):
    global _LANG
    _LANG = code if code in ("zh", "en") else "zh"


def t(key):
    e = TR.get(key)
    if not e:
        return key
    return e.get(_LANG) or e.get("zh") or key


TR = {
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
    "t_history": {"zh": "历史截图", "en": "History"},
    "t_settings": {"zh": "设置", "en": "Settings"},
    "lab_delay": {"zh": "延时", "en": "Delay"},
    "lab_speed": {"zh": "滚速", "en": "Speed"},
    "lab_width": {"zh": "线宽", "en": "Width"},
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
    "a_magnify": {"zh": "放大镜", "en": "Magnifier"},
    "a_crop": {"zh": "裁剪", "en": "Crop"},
    "a_color": {"zh": "标注颜色", "en": "Annotation color"},
    "a_undo": {"zh": "撤销", "en": "Undo"},
    "a_clear": {"zh": "清除标注", "en": "Clear annotations"},
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
    "set_sc_hint": {"zh": "设置全局快捷键(任意界面可触发,自动写入 KDE):",
                    "en": "Set global shortcuts (work anywhere, written to KDE):"},
    "set_ocr_deflang": {"zh": "默认识别语言", "en": "Default OCR language"},
    "set_ocr_deflayout": {"zh": "默认版面", "en": "Default layout"},
    "set_ocr_enh": {"zh": "图像增强(放大+二值化,提升准确率)",
                    "en": "Image enhance (upscale + threshold, better accuracy)"},
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
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color), max(1.5, size / 13.0))
    pen.setCapStyle(Qt.RoundCap); pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    u = size / 24.0

    def Pt(x, y): return QtCore.QPointF(x * u, y * u)
    def L(x1, y1, x2, y2): p.drawLine(Pt(x1, y1), Pt(x2, y2))
    def Rr(x, y, w, h, r=0):
        rc = QtCore.QRectF(x * u, y * u, w * u, h * u)
        (p.drawRoundedRect(rc, r * u, r * u) if r else p.drawRect(rc))
    def Ell(x, y, w, h): p.drawEllipse(QtCore.QRectF(x * u, y * u, w * u, h * u))
    def glyph(ch, frac=0.7):
        f = p.font(); f.setPixelSize(int(size * frac)); f.setBold(True); p.setFont(f)
        p.drawText(QtCore.QRectF(0, 0, size, size), Qt.AlignCenter, ch)
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
    elif name == "settings":   # gear
        Ell(9, 9, 6, 6)
        for k in range(8):
            a = math.radians(k * 45)
            L(12 + 8 * math.cos(a), 12 + 8 * math.sin(a),
              12 + 10.5 * math.cos(a), 12 + 10.5 * math.sin(a))
    elif name == "ocr":
        if _LANG == "en":
            glyph("OCR", 0.4)
        else:
            glyph("字", 0.78)
    elif name == "copy":
        Rr(8, 8, 11, 11, 2); Rr(5, 5, 11, 11, 2)
    elif name == "pin":
        L(12, 13, 12, 19); Ell(8, 5, 8, 8)
    elif name == "beautify":   # sparkle/star
        for (cx, cy, s) in [(11, 11, 6), (17, 6, 2.6)]:
            L(cx - s, cy, cx + s, cy); L(cx, cy - s, cx, cy + s)
    elif name == "save":
        L(12, 4, 12, 15); head(12, 15, math.pi / 2); L(6, 19, 18, 19)
    elif name == "rect":
        Rr(5, 6, 14, 12, 1)
    elif name == "ellipse":
        Ell(5, 6, 14, 12)
    elif name == "arrow":
        L(6, 18, 17, 7); head(17, 7, math.radians(-45))
    elif name == "line":
        L(6, 18, 18, 6)
    elif name == "pen":
        L(6, 18, 15, 9); Rr(14, 6, 4, 4, 1); L(6, 18, 7.5, 16.5)
    elif name == "text":
        glyph("T", 0.8)
    elif name == "number":
        Ell(5, 5, 14, 14); glyph("1", 0.5)
    elif name == "highlight":
        pen2 = QtGui.QPen(QtGui.QColor(color), 5 * u); pen2.setCapStyle(Qt.FlatCap)
        p.setPen(pen2); L(7, 11, 17, 11)
        p.setPen(pen); L(6, 18, 18, 18)
    elif name == "blur":       # mosaic
        for ix in range(3):
            for iy in range(3):
                if (ix + iy) % 2 == 0:
                    p.fillRect(QtCore.QRectF((6 + ix * 4) * u, (6 + iy * 4) * u,
                                             3.4 * u, 3.4 * u), QtGui.QColor(color))
                else:
                    Rr(6 + ix * 4, 6 + iy * 4, 3.4, 3.4)
    elif name == "magnify":
        Ell(5, 5, 10, 10); L(14, 14, 19, 19)
    elif name == "crop":
        L(8, 4, 8, 17); L(8, 17, 20, 17); L(4, 7, 16, 7); L(16, 7, 16, 20)
    elif name == "undo":
        p.drawArc(QtCore.QRectF(6 * u, 7 * u, 13 * u, 12 * u), 40 * 16, 220 * 16)
        head(7, 9.5, math.radians(120))
    elif name == "clear":      # trash can
        L(5, 7, 19, 7); Rr(7, 7, 10, 13, 1); L(10, 5, 14, 5)
        L(10, 10, 10, 17); L(14, 10, 14, 17)
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
]


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


class CaptureWorker(QThread):
    """Run scrolling + frame grabbing + stitching on a background thread to avoid freezing the UI."""
    progress = pyqtSignal(str)
    finished_img = pyqtSignal(object)   # emits the stitched BGR numpy image, or None on failure

    def __init__(self, rect_phys, scroll_clicks=3, settle=0.45,
                 max_iters=80, max_height=40000, parent=None):
        super().__init__(parent)
        self.left, self.top, self.width, self.height = rect_phys
        self.scroll_clicks = scroll_clicks
        self.settle = settle
        self.max_iters = max_iters
        self.max_height = max_height
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            mouse = MouseController()
            cx = self.left + self.width // 2
            cy = self.top + self.height // 2

            # physical pixels -> logical coordinates for pynput (pynput uses logical coordinates)
            dpr = getattr(self, "dpr", 1.0)
            mouse.position = (int(cx / dpr), int(cy / dpr))
            time.sleep(0.2)

            accumulated = grab_region(self.left, self.top, self.width, self.height)
            prev = accumulated.copy()
            no_progress = 0

            for i in range(self.max_iters):
                if self._abort:
                    self.progress.emit("Cancelled")
                    break

                mouse.scroll(0, -self.scroll_clicks)
                time.sleep(self.settle)
                cur = grab_region(self.left, self.top, self.width, self.height)

                new_start, conf = find_new_content(prev, cur)
                self.progress.emit(
                    f"Frame {i + 1}: confidence {conf:.2f}, height {accumulated.shape[0]} px"
                )

                if conf < 0.45:
                    # Match unreliable (content changed too much / animation); conservatively retry one frame
                    no_progress += 1
                elif new_start >= cur.shape[0] - 2:
                    # No new content -- most likely reached the bottom
                    no_progress += 1
                else:
                    new_part = cur[new_start:, :]
                    accumulated = np.vstack([accumulated, new_part])
                    no_progress = 0

                prev = cur

                if no_progress >= 3:
                    self.progress.emit("Reached bottom, stitching done")
                    break
                if accumulated.shape[0] >= self.max_height:
                    self.progress.emit("Max length reached, stopping")
                    break

            self.finished_img.emit(accumulated)
        except Exception as exc:                      # noqa: BLE001
            self.progress.emit(f"Error: {exc}")
            self.finished_img.emit(None)


# --------------------------------------------------------------------------- #
# Region selection overlay
# --------------------------------------------------------------------------- #
class RegionSelector(QtWidgets.QWidget):
    """Full-screen overlay over a frozen screen: drag to select a region (region mode) or pick a color (color mode).

    Before showing, grab a full-screen capture as the background (freezing the picture), and draw a
    loupe next to the cursor showing pixel-level zoom, coordinates and hex color; region mode also
    shows the selection size.
    """
    selected = pyqtSignal(QRect)
    colorPicked = pyqtSignal(object)        # emits a QColor
    cancelled = pyqtSignal()

    LOUPE = 120          # loupe side length (logical pixels)
    ZOOM = 8             # zoom factor

    def __init__(self, mode="region"):
        super().__init__()
        self.mode = mode
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

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
        hint = ("Drag to select a region, Esc to cancel" if self.mode == "region"
                else "Move to a pixel, click to pick color, Esc to cancel")
        p.setPen(QtGui.QColor(255, 255, 255, 220))
        p.drawText(20, 30, hint)

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

        self._draw_loupe(p, self.cur)

    def _draw_loupe(self, p, lp):
        L, Z = self.LOUPE, self.ZOOM
        src_px = int(L / Z * self.dpr)          # source sampling side length (physical pixels)
        sx = int(lp.x() * self.dpr) - src_px // 2
        sy = int(lp.y() * self.dpr) - src_px // 2
        src = self.bg_img.copy(sx, sy, src_px, src_px)
        zoom = src.scaled(L, L, Qt.IgnoreAspectRatio, Qt.FastTransformation)

        # Place the loupe to the lower-right of the cursor; flip it when near an edge
        ox, oy = lp.x() + 20, lp.y() + 20
        if ox + L > self.width():
            ox = lp.x() - L - 20
        if oy + L + 34 > self.height():
            oy = lp.y() - L - 34
        box = QRect(ox, oy, L, L)

        p.drawImage(box, zoom)
        # Crosshair
        p.setPen(QtGui.QPen(QtGui.QColor(0, 170, 255, 200), 1))
        p.drawLine(box.center().x(), box.top(), box.center().x(), box.bottom())
        p.drawLine(box.left(), box.center().y(), box.right(), box.center().y())
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255), 1))
        p.drawRect(box)

        col = self._pixel(lp)
        hexv = col.name().upper()
        info = QRect(ox, oy + L, L, 34)
        p.fillRect(info, QtGui.QColor(0, 0, 0, 200))
        p.fillRect(QRect(ox + 4, oy + L + 8, 18, 18), col)
        p.setPen(QtGui.QColor(255, 255, 255))
        f = p.font(); f.setPixelSize(11); p.setFont(f)
        p.drawText(QRect(ox + 26, oy + L, L - 28, 34),
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
        self.update()

    def mouseMoveEvent(self, e):
        self.cur = e.pos()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.mode != "region" or self.origin is None:
            return
        r = QRect(self.origin, e.pos()).normalized()
        gr = QRect(self.mapToGlobal(r.topLeft()), r.size())
        self.close()
        if gr.width() > 8 and gr.height() > 8:
            self.selected.emit(gr)
        else:
            self.cancelled.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()
            self.cancelled.emit()


# --------------------------------------------------------------------------- #
# Floating control bar for manual scrolling capture
# --------------------------------------------------------------------------- #
class ManualBar(QtWidgets.QWidget):
    """Floating mini-window shown while recording a manual scrolling capture: shows the current long-image height + a stop button.

    It tries to stay outside the selected region so it doesn't get captured into the screenshot.
    """
    def __init__(self, region: QRect, on_stop):
        super().__init__()
        self.setObjectName("ManualBar")
        # Use a normal always-on-top window (not Qt.Tool): when the main window is minimized, Tool windows often don't show under KDE
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.X11BypassWindowManagerHint)
        self.setWindowTitle("Kapture recording")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.dot = QtWidgets.QLabel("🔴")
        self.lbl = QtWidgets.QLabel("Manual scroll… scroll the target window down, click stop when done")
        self.btn = QtWidgets.QPushButton("⏹ Stop & stitch")
        self.btn.clicked.connect(on_stop)
        lay.addWidget(self.dot)
        lay.addWidget(self.lbl)
        lay.addWidget(self.btn)
        self.setStyleSheet(
            "#ManualBar{background:#2b2b2b;border:1px solid #c0392b;border-radius:8px;}"
            "QLabel{color:#eee;font-size:13px;}"
            "QPushButton{background:#c0392b;color:white;padding:5px 14px;"
            "border-radius:4px;font-weight:bold;}")
        self.adjustSize()
        self._place(region)

    def show_on_top(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _place(self, region: QRect):
        vg = QtWidgets.QApplication.primaryScreen().virtualGeometry()
        bw, bh = self.width(), self.height()
        # Prefer below the region, then above, then to the right, finally fall back to the top-left of the virtual desktop
        if region.bottom() + 8 + bh <= vg.bottom():
            x, y = region.left(), region.bottom() + 8
        elif region.top() - 8 - bh >= vg.top():
            x, y = region.left(), region.top() - 8 - bh
        elif region.right() + 8 + bw <= vg.right():
            x, y = region.right() + 8, region.top()
        else:
            x, y = vg.left() + 8, vg.top() + 8
        self.move(int(x), int(y))

    def set_height(self, h):
        self.lbl.setText(f"Manual scroll… height {h} px (click stop when done)")


# --------------------------------------------------------------------------- #
# Annotation canvas
# --------------------------------------------------------------------------- #
class AnnotateCanvas(QtWidgets.QWidget):
    """Display the screenshot and allow drawing rectangles/ellipses/arrows/lines/pen/text on it.

    All annotations are stored in image pixel coordinates and scaled by self.scale when displayed;
    on export they're drawn into the original image 1:1 to produce the merged image.
    """
    cropRequested = QtCore.pyqtSignal(object)   # emits the crop rect (image coordinates, QRectF)

    def __init__(self):
        super().__init__()
        self.base = None            # QImage, the original screenshot
        self.items = []             # completed annotations
        self.cur = None             # annotation currently being drawn
        self.scale = 1.0
        self.tool = "rect"
        self.color = QtGui.QColor(255, 40, 40)
        self.width = 3
        self.setMouseTracking(True)
        self.empty_background = "#222228"
        self.empty_text = "#a2a2ad"

    # --- External interface --- #
    def set_image_bgr(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, _ = rgb.shape
        self.base = QtGui.QImage(rgb.data, w, h, 3 * w,
                                 QtGui.QImage.Format_RGB888).copy()
        self.items.clear()
        self.cur = None
        self._apply_size()

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
        self.tool = name

    def set_color(self, qcolor):
        self.color = qcolor

    def set_width(self, w):
        self.width = w

    def undo(self):
        if self.items:
            self.items.pop()
            self.update()

    def clear_items(self):
        self.items.clear()
        self.update()

    def clear(self):
        """Clear the canvas (back to the no-screenshot state)."""
        self.base = None
        self.items.clear()
        self.cur = None
        self.setMinimumSize(0, 0)
        self.resize(self.parent().size() if self.parent() else QtCore.QSize(400, 300))
        self.update()

    def render_flattened(self):
        """Return a QImage with annotations baked in (1:1 pixels)."""
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
            p.drawText(self.rect(), Qt.AlignCenter, "No screenshot yet. Use the buttons above to start.")
            return
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        p.scale(self.scale, self.scale)
        p.drawImage(0, 0, self.base)
        for it in self.items:
            self._draw_item(p, it)
        if self.cur:
            self._draw_item(p, self.cur)

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
            self._draw_arrow(p, it["a"], it["b"])
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

    def _draw_arrow(self, p, a, b):
        import math
        p.drawLine(a, b)
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = 8 + self.width * 2
        for da in (math.radians(150), math.radians(-150)):
            x = b.x() + size * math.cos(ang + da)
            y = b.y() + size * math.sin(ang + da)
            p.drawLine(b, QtCore.QPointF(x, y))

    # --- Mouse interaction --- #
    def mousePressEvent(self, e):
        if self.base is None:
            return
        pt = self._to_img(e.pos())
        if self.tool == "text":
            txt, ok = QtWidgets.QInputDialog.getText(self, "Add text", "Text:")
            if ok and txt:
                self.items.append({"type": "text", "a": pt, "text": txt,
                                   "color": QtGui.QColor(self.color),
                                   "width": self.width})
                self.update()
            return
        if self.tool == "number":
            n = 1 + max([it["n"] for it in self.items
                         if it["type"] == "number"], default=0)
            self.items.append({"type": "number", "a": pt, "n": n,
                               "color": QtGui.QColor(self.color),
                               "width": self.width})
            self.update()
            return
        base = {"color": QtGui.QColor(self.color), "width": self.width}
        if self.tool == "pen":
            self.cur = dict(base, type="pen", pts=[pt])
        else:
            self.cur = dict(base, type=self.tool, a=pt, b=pt)
        self.update()

    def mouseMoveEvent(self, e):
        if self.cur is None:
            return
        pt = self._to_img(e.pos())
        if self.cur["type"] == "pen":
            self.cur["pts"].append(pt)
        else:
            self.cur["b"] = pt
        self.update()

    def mouseReleaseEvent(self, e):
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
        self.items.append(self.cur)
        self.cur = None
        self.update()


# --------------------------------------------------------------------------- #
# Floating thumbnail shown after a capture (bottom-left)
# --------------------------------------------------------------------------- #
class FloatingThumbnail(QtWidgets.QWidget):
    """A small thumbnail floating at the bottom-left after a capture: drag it elsewhere, click to edit, copy/save/pin.

    Callbacks are injected from outside: on_edit / on_copy / on_save / on_pin.
    """
    THUMB_W = 220
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

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)

        # Thumbnail
        pix = QtGui.QPixmap.fromImage(qimage)
        if pix.width() > self.THUMB_W:
            pix = pix.scaledToWidth(self.THUMB_W, Qt.SmoothTransformation)
        if pix.height() > 260:
            pix = pix.scaledToHeight(260, Qt.SmoothTransformation)
        self._thumb = QtWidgets.QLabel()
        self._thumb.setPixmap(pix)
        self._thumb.setStyleSheet("border:2px solid #444;border-radius:4px;background:#000;")
        lay.addWidget(self._thumb)

        # Action button row
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        for text, tip, cb in [("✏️", "Edit", self._do_edit),
                              ("📋", "Copy", self._do_copy),
                              ("💾", "Save", self._do_save),
                              ("📌", "Pin to screen", self._do_pin),
                              ("✕", "Close", self._do_close)]:
            btn = QtWidgets.QPushButton(text)
            btn.setToolTip(tip)
            btn.setFixedSize(34, 26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(cb)
            row.addWidget(btn)
        lay.addLayout(row)

        self.setStyleSheet(
            "FloatingThumbnail{background:transparent;}"
            "QPushButton{background:#2b2b2b;color:#eee;border:none;border-radius:4px;}"
            "QPushButton:hover{background:#0a84ff;}")
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
    """Pin a screenshot as an always-on-top floating window: drag to move, wheel to zoom, double-click/right-click to close."""
    _pins = []                                  # hold references to prevent GC

    def __init__(self, qimage):
        super().__init__()
        PinnedImage._pins.append(self)
        self._orig = QtGui.QPixmap.fromImage(qimage)
        self._scale = 1.0
        self._drag_off = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setCursor(Qt.OpenHandCursor)
        # Initial size: no more than 60% of the screen
        sg = QtWidgets.QApplication.primaryScreen().availableGeometry()
        maxw, maxh = int(sg.width() * 0.6), int(sg.height() * 0.6)
        if self._orig.width() > maxw or self._orig.height() > maxh:
            self._scale = min(maxw / self._orig.width(),
                              maxh / self._orig.height())
        self._lbl = QtWidgets.QLabel(self)
        self._lbl.setStyleSheet("border:1px solid #0a84ff;")
        self._apply()
        self.move(sg.center().x() - self.width() // 2,
                  sg.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()

    def _apply(self):
        pix = self._orig.scaled(
            max(1, int(self._orig.width() * self._scale)),
            max(1, int(self._orig.height() * self._scale)),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._lbl.setPixmap(pix)
        self._lbl.resize(pix.size())
        self.resize(pix.size())

    def wheelEvent(self, e):
        self._scale *= 1.1 if e.angleDelta().y() > 0 else 0.9
        self._scale = max(0.1, min(5.0, self._scale))
        self._apply()

    def mousePressEvent(self, e):
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
        self.close()

    def contextMenuEvent(self, e):
        m = QtWidgets.QMenu(self)
        m.addAction("Copy image", lambda: QtWidgets.QApplication.clipboard()
                    .setImage(self._orig.toImage()))
        m.addAction("Close", self.close)
        m.exec_(e.globalPos())

    def closeEvent(self, e):
        if self in PinnedImage._pins:
            PinnedImage._pins.remove(self)
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
class Recorder(QtCore.QObject):
    """Record a screen region to mp4 using ffmpeg x11grab (optionally convert to gif)."""
    def __init__(self, region, out_path, fps=15, parent=None):
        super().__init__(parent)
        self.region = region                    # (x, y, w, h) physical pixels
        self.out_path = out_path
        self.fps = fps
        self.proc = QtCore.QProcess()

    def start(self):
        import os
        x, y, w, h = self.region
        w -= w % 2; h -= h % 2                   # h264 requires even side lengths
        disp = os.environ.get("DISPLAY", ":0")
        args = ["-y", "-f", "x11grab", "-framerate", str(self.fps),
                "-video_size", f"{w}x{h}", "-i", f"{disp}+{x},{y}",
                "-codec:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", self.out_path]
        self.proc.start("ffmpeg", args)
        return self.proc.waitForStarted(3000)

    def stop(self):
        if self.proc.state() != QtCore.QProcess.NotRunning:
            self.proc.write(b"q")                # let ffmpeg finish gracefully
            self.proc.closeWriteChannel()
            if not self.proc.waitForFinished(6000):
                self.proc.terminate()
                self.proc.waitForFinished(2000)

    def to_gif(self, gif_path):
        """Convert the recorded mp4 to gif (two-pass palette method)."""
        import os, subprocess, tempfile
        pal = os.path.join(tempfile.gettempdir(), "ss_palette.png")
        vf = f"fps={min(15, self.fps)},scale=640:-1:flags=lanczos"
        subprocess.run(["ffmpeg", "-y", "-i", self.out_path, "-vf",
                        vf + ",palettegen", pal], capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-i", self.out_path, "-i", pal,
                        "-lavfi", vf + " [x]; [x][1:v] paletteuse",
                        gif_path], capture_output=True)
        return os.path.exists(gif_path)


class RecordBar(QtWidgets.QWidget):
    """Recording control bar: shows a timer and a stop button."""
    def __init__(self, on_stop):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                            Qt.X11BypassWindowManagerHint)
        self.setObjectName("RecordBar")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        self.lbl = QtWidgets.QLabel("● REC  00:00")
        self.btn = QtWidgets.QPushButton("⏹ Stop")
        self.btn.clicked.connect(on_stop)
        lay.addWidget(self.lbl); lay.addWidget(self.btn)
        self.setStyleSheet(
            "#RecordBar{background:#2b2b2b;border:1px solid #c0392b;border-radius:8px;}"
            "QLabel{color:#ff5b5b;font-weight:bold;font-size:14px;}"
            "QPushButton{background:#c0392b;color:white;padding:5px 14px;"
            "border-radius:4px;font-weight:bold;}")
        self.adjustSize()
        sg = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.move(sg.center().x() - self.width() // 2, sg.bottom() - self.height() - 30)
        self._secs = 0
        self._t = QtCore.QTimer(self); self._t.setInterval(1000)
        self._t.timeout.connect(self._tick); self._t.start()

    def _tick(self):
        self._secs += 1
        self.lbl.setText(f"● REC  {self._secs // 60:02d}:{self._secs % 60:02d}")

    def stop_timer(self):
        self._t.stop()


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kapture")
        self.resize(820, 660)
        self.image_bgr = None        # current screenshot (BGR numpy)
        self.worker = None
        self._mode = None            # 'scroll' or 'single'
        self.settings = QtCore.QSettings("ScrollShot", "ScrollShot")
        set_lang(self.settings.value("ui_lang", "zh"))      # apply the UI language
        write_desktop_entry()                               # launcher name follows the language
        self.history = []            # recent screenshots [(QImage, description)]
        self._recorder = None        # screen recorder
        self._build_ui()
        self._apply_style()
        self._setup_tray()
        self._retranslate()

    def _tbtn(self, icon, tip, checkable=False):
        b = QtWidgets.QToolButton()
        b.setIcon(line_icon(icon))
        b.setIconSize(QtCore.QSize(22, 22))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setAutoRaise(True)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _vsep(self):
        w = QtWidgets.QWidget()
        w.setObjectName("vsep")
        w.setAttribute(Qt.WA_StyledBackground, True)
        w.setFixedWidth(1)
        return w

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 8)
        layout.setSpacing(10)

        # ---------- Minimal top bar: capture features ---------- #
        top = QtWidgets.QHBoxLayout(); top.setSpacing(4)
        self.btn_single = self._tbtn("region", "")
        self.btn_window = self._tbtn("window", "")
        self.btn_scroll = self._tbtn("scroll", "")
        self.btn_manual = self._tbtn("manual", "")
        self.btn_record = self._tbtn("record", "")
        for b in (self.btn_single, self.btn_window, self.btn_scroll,
                  self.btn_manual, self.btn_record):
            top.addWidget(b)
        top.addWidget(self._vsep())
        self.btn_colorpick = self._tbtn("color", "")
        self.btn_repeat = self._tbtn("repeat", "")
        top.addWidget(self.btn_colorpick); top.addWidget(self.btn_repeat)
        top.addWidget(self._vsep())
        self._lab_delay = QtWidgets.QLabel(); self._lab_delay.setObjectName("dim")
        top.addWidget(self._lab_delay)
        self.delay = QtWidgets.QSpinBox(); self.delay.setRange(0, 10)
        self.delay.setFixedWidth(50)
        top.addWidget(self.delay)
        self._lab_speed = QtWidgets.QLabel(); self._lab_speed.setObjectName("dim")
        top.addWidget(self._lab_speed)
        self.speed = QtWidgets.QSpinBox(); self.speed.setRange(1, 10)
        self.speed.setValue(3); self.speed.setFixedWidth(50)
        top.addWidget(self.speed)
        top.addStretch(1)
        self.btn_history = self._tbtn("history", "")
        self.btn_settings = self._tbtn("settings", "")
        top.addWidget(self.btn_history); top.addWidget(self.btn_settings)
        layout.addLayout(top)

        # ---------- Tool card: annotation + OCR/export ---------- #
        card = QtWidgets.QFrame(); card.setObjectName("card")
        tools = QtWidgets.QHBoxLayout(card)
        tools.setContentsMargins(8, 6, 8, 6); tools.setSpacing(3)
        self.tool_group = QtWidgets.QButtonGroup(self)
        self._tool_btns = {}
        for name in ["rect", "ellipse", "arrow", "line", "pen", "text",
                     "number", "highlight", "blur", "magnify", "crop"]:
            b = self._tbtn(name, "", checkable=True)
            b.clicked.connect(lambda _, n=name: self.canvas.set_tool(n))
            self.tool_group.addButton(b); tools.addWidget(b)
            self._tool_btns[name] = b
            if name == "rect":
                b.setChecked(True)
        self.btn_color = QtWidgets.QToolButton()
        self.btn_color.setIcon(swatch_icon(QtGui.QColor(255, 40, 40)))
        self.btn_color.setIconSize(QtCore.QSize(20, 20))
        self.btn_color.setAutoRaise(True)
        self.btn_color.setCursor(Qt.PointingHandCursor)
        self.btn_color.clicked.connect(self.pick_color)
        tools.addWidget(self.btn_color)
        self.lwidth = QtWidgets.QSpinBox(); self.lwidth.setRange(1, 30)
        self.lwidth.setValue(3); self.lwidth.setFixedWidth(50)
        self.lwidth.valueChanged.connect(lambda v: self.canvas.set_width(v))
        tools.addWidget(self.lwidth)
        self.btn_undo = self._tbtn("undo", "")
        self.btn_undo.clicked.connect(lambda: self.canvas.undo())
        self.btn_clear = self._tbtn("clear", "")
        self.btn_clear.clicked.connect(lambda: self.canvas.clear_items())
        tools.addWidget(self.btn_undo); tools.addWidget(self.btn_clear)
        tools.addStretch(1)
        tools.addWidget(self._vsep())

        # OCR: main button runs recognition; dropdown arrow adjusts language/layout/enhancement
        self.btn_ocr = QtWidgets.QToolButton()
        self.btn_ocr.setIcon(line_icon("ocr")); self.btn_ocr.setIconSize(QtCore.QSize(22, 22))
        self.btn_ocr.setAutoRaise(True); self.btn_ocr.setCursor(Qt.PointingHandCursor)
        self.btn_ocr.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
        ocr_menu = QtWidgets.QMenu(self.btn_ocr)
        opt_w = QtWidgets.QWidget(); fl = QtWidgets.QFormLayout(opt_w)
        self.lang = QtWidgets.QComboBox()
        self.lang.addItems(["chi_sim+eng", "chi_sim", "chi_tra+eng", "eng"])
        self.psm = QtWidgets.QComboBox()
        self.psm.addItem("Block of text (psm 6)", 6); self.psm.addItem("Auto (psm 3)", 3)
        self.psm.addItem("Single column (psm 4)", 4); self.psm.addItem("Single line (psm 7)", 7)
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
        for b in (self.btn_ocr, self.btn_copy, self.btn_pin,
                  self.btn_beautify, self.btn_save):
            tools.addWidget(b)
        layout.addWidget(card)

        # ---------- Canvas ---------- #
        self.canvas = AnnotateCanvas()
        self.canvas.cropRequested.connect(self._do_crop)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        layout.addWidget(self.scroll, 3)

        # ---------- OCR text result ---------- #
        self.text = QtWidgets.QPlainTextEdit()
        layout.addWidget(self.text, 2)

        self.status = QtWidgets.QLabel()
        self.status.setObjectName("status")
        layout.addWidget(self.status)

        # ---------- Connections ---------- #
        self.btn_manual.clicked.connect(lambda: self.start_select("manual"))
        self.btn_scroll.clicked.connect(lambda: self.start_select("scroll"))
        self.btn_single.clicked.connect(lambda: self.start_select("single"))
        self.btn_ocr.clicked.connect(self.run_ocr)
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

    def _retranslate(self):
        """Refresh the main UI text according to the current language (called when switching languages)."""
        self.setWindowTitle(t("app_title"))
        tips = {
            self.btn_single: "cap_region", self.btn_window: "cap_window",
            self.btn_scroll: "cap_scroll", self.btn_manual: "cap_manual",
            self.btn_record: "cap_record", self.btn_colorpick: "cap_color",
            self.btn_repeat: "cap_repeat", self.btn_history: "t_history",
            self.btn_settings: "t_settings", self.btn_color: "a_color",
            self.btn_undo: "a_undo", self.btn_clear: "a_clear",
            self.btn_ocr: "e_ocr", self.btn_copy: "e_copy", self.btn_pin: "e_pin",
            self.btn_beautify: "e_beautify", self.btn_save: "e_save",
        }
        for w, key in tips.items():
            w.setToolTip(t(key))
        for name, b in self._tool_btns.items():
            b.setToolTip(t("a_" + name))
        self._lab_delay.setText(t("lab_delay"))
        self._lab_speed.setText(t("lab_speed"))
        self.lwidth.setToolTip(t("lab_width"))
        self._ocr_lab_lang.setText(t("ocr_lang"))
        self._ocr_lab_layout.setText(t("ocr_layout"))
        self.enhance.setText(t("ocr_enhance"))
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
                (self.btn_single, "region"), (self.btn_window, "window"),
                (self.btn_scroll, "scroll"), (self.btn_manual, "manual"),
                (self.btn_record, "record"), (self.btn_colorpick, "color"),
                (self.btn_repeat, "repeat"), (self.btn_history, "history"),
                (self.btn_settings, "settings"), (self.btn_undo, "undo"),
                (self.btn_clear, "clear"), (self.btn_ocr, "ocr"),
                (self.btn_copy, "copy"), (self.btn_pin, "pin"),
                (self.btn_beautify, "beautify"), (self.btn_save, "save")):
            icon = line_icon(name, colors["icon"])
            if button.isCheckable():
                icon.addPixmap(line_icon(name, colors["on_accent"]).pixmap(22, 22),
                               QtGui.QIcon.Normal, QtGui.QIcon.On)
            button.setIcon(icon)
        for name, button in self._tool_btns.items():
            icon = line_icon(name, colors["icon"])
            icon.addPixmap(line_icon(name, colors["on_accent"]).pixmap(22, 22),
                           QtGui.QIcon.Normal, QtGui.QIcon.On)
            button.setIcon(icon)

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
        QWidget#root, QDialog {{ background:{window}; }}
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
        QToolButton::menu-button {{ border:none; width:12px; border-top-right-radius:9px;
            border-bottom-right-radius:9px; }}
        QToolButton::menu-arrow {{ width:0; height:0; image:none; }}

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
        QScrollArea {{ border:1px solid {edge}; border-radius:12px; background:{editor}; }}

        /* tool card + separators */
        QFrame#card {{ background:{panel}; border:1px solid {edge}; border-radius:12px; }}
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

    def handle_command(self, cmd):
        """Single-instance command dispatch: sent from this process or a later-launched process."""
        if cmd in ("single", "manual", "scroll"):
            self.start_select(cmd)
        elif cmd == "window":
            self.capture_window()
        elif cmd == "color":
            self.pick_color_screen()
        else:                                   # show / show-first
            self._blank_editor()                 # don't show the previous screenshot on open
            self.showNormal()
            self.activateWindow()
            self.raise_()

    def start_select(self, mode):
        self._mode = mode
        self.showMinimized()
        QtCore.QTimer.singleShot(250, self._show_selector)

    def _show_selector(self):
        self.selector = RegionSelector()
        self.selector.selected.connect(self._on_region)
        self.selector.cancelled.connect(self._restore)
        self.selector.show()
        self.selector.activateWindow()
        self.selector.raise_()

    def _restore(self):
        self.showNormal()
        self.activateWindow()

    def _on_region(self, gr: QRect):
        dpr = QtWidgets.QApplication.primaryScreen().devicePixelRatio()
        phys = (int(gr.left() * dpr), int(gr.top() * dpr),
                int(gr.width() * dpr), int(gr.height() * dpr))
        if self._mode == "single":
            QtCore.QTimer.singleShot(150, lambda: self._single_shot(phys))
        elif self._mode == "manual":
            QtCore.QTimer.singleShot(150, lambda: self._manual_start(phys, gr))
        else:
            QtCore.QTimer.singleShot(150, lambda: self._scroll_shot(phys, dpr))

    def _single_shot(self, phys):
        self._last_phys = phys              # remember it for "repeat last area"
        self._grab_with_delay(
            lambda: self._present_capture(
                grab_region(*phys), f"Region captured: {phys[2]}×{phys[3]} px"))

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
        self._grab_with_delay(
            lambda: self._present_capture(
                grab_region(x, y, w, h), f"Window captured: {w}×{h} px"))

    # --- repeat last area --- #
    def repeat_last(self):
        if not getattr(self, "_last_phys", None):
            self.status.setText("No previous area yet")
            return
        phys = self._last_phys
        self.showMinimized()
        if getattr(self, "_thumb", None):
            self._thumb.close()
        QtCore.QTimer.singleShot(250, lambda: self._present_capture(
            grab_region(*phys), f"Repeated last area: {phys[2]}×{phys[3]} px"))

    # --- screen color picker --- #
    def pick_color_screen(self):
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

    def _scroll_shot(self, phys, dpr):
        self.status.setText("Scrolling capture… please don't move the mouse")
        self.worker = CaptureWorker(phys, scroll_clicks=self.speed.value())
        self.worker.dpr = dpr
        self.worker.progress.connect(self.status.setText)
        self.worker.finished_img.connect(self._on_capture_done)
        self.worker.start()

    def _on_capture_done(self, img):
        if img is None:
            self.status.setText("Capture failed, see the message above")
            self._restore()
        else:
            self._present_capture(img, f"Long capture done: {img.shape[1]}×{img.shape[0]} px")

    # --- manual scrolling capture --- #
    def _manual_start(self, phys, gr):
        try:
            self._m_phys = phys
            self._m_acc = grab_region(*phys)
            self._m_prev = self._m_acc.copy()
            self._m_bar = ManualBar(gr, on_stop=self._manual_stop)
            self._m_bar.show_on_top()
            self._m_timer = QtCore.QTimer(self)
            self._m_timer.setInterval(250)          # grab a frame every 250 ms
            self._m_timer.timeout.connect(self._manual_tick)
            self._m_timer.start()
        except Exception as exc:                    # noqa: BLE001
            self._restore()
            QtWidgets.QMessageBox.critical(self, "Manual capture failed to start", str(exc))

    MANUAL_MAX_H = 40000        # max manual long-image height, to avoid runaway memory growth

    def _manual_tick(self):
        cur = grab_region(*self._m_phys)
        new_start, conf = find_new_content(self._m_prev, cur)
        if conf >= 0.45 and new_start < cur.shape[0] - 2:
            self._m_acc = np.vstack([self._m_acc, cur[new_start:, :]])
        self._m_prev = cur
        self._m_bar.set_height(self._m_acc.shape[0])
        if self._m_acc.shape[0] >= self.MANUAL_MAX_H:
            self._m_bar.set_height(self._m_acc.shape[0])
            self.status.setText("Max length reached, stitching stopped automatically")
            self._manual_stop()

    def _manual_stop(self):
        if getattr(self, "_m_timer", None):
            self._m_timer.stop()
        if getattr(self, "_m_bar", None):
            self._m_bar.close()
        self._present_capture(
            self._m_acc,
            f"Manual capture done: {self._m_acc.shape[1]}×{self._m_acc.shape[0]} px")

    # --- after capture: copy to clipboard by default + bottom-left floating thumbnail --- #
    def _present_capture(self, img, status):
        self._add_history(bgr_to_qimage(img), status)
        # default behavior: copy image to clipboard (auto_copy on by default)
        copied = self.settings.value("auto_copy", True, type=bool)
        if copied:
            QtWidgets.QApplication.clipboard().setImage(bgr_to_qimage(img))
        if self.settings.value("auto_save", False, type=bool):
            self._auto_save(img)
        self.status.setText(status + ("  " + t("st_copied") if copied else ""))
        # setting: open the editor right after capture (otherwise only show the thumbnail, main window stays blank)
        if self.settings.value("open_editor", False, type=bool):
            self._load_into_editor(img)
        self._show_thumbnail(img)

    def _add_history(self, qimg, desc):
        self.history.insert(0, (qimg, desc))
        del self.history[30:]                # keep at most 30

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
            on_pin=lambda: PinnedImage(bgr_to_qimage(img)))
        self._thumb.show()
        self._thumb.raise_()

    def _quick_save(self, img):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, t("dlg_save"), self._make_filename(), "PNG (*.png);;JPEG (*.jpg)")
        if path:
            cv2.imwrite(path, img)
            self.status.setText(("Saved: " if _LANG == "en" else "已保存:") + path)

    def _load_into_editor(self, img):
        """Load the given screenshot into the editor and show it (thumbnail / history / open_editor setting)."""
        self.image_bgr = img
        self.showNormal()
        self._show_preview()
        self.activateWindow()
        self.raise_()

    def _blank_editor(self):
        """Reset the editor to a blank state (so opening the main window doesn't show the last screenshot)."""
        self.image_bgr = None
        self.canvas.clear()
        self.text.clear()
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
        self.canvas.set_image_bgr(self.image_bgr)
        self.canvas.fit_width(self.scroll.viewport().width())

    def _do_crop(self, rectf):
        if self.image_bgr is None:
            return
        h, w = self.image_bgr.shape[:2]
        x0 = max(0, int(rectf.left()));  y0 = max(0, int(rectf.top()))
        x1 = min(w, int(rectf.right())); y1 = min(h, int(rectf.bottom()))
        if x1 - x0 < 2 or y1 - y0 < 2:
            return
        self.image_bgr = self.image_bgr[y0:y1, x0:x1].copy()
        self._show_preview()                        # reset canvas (annotations are cleared)
        self.status.setText(f"Cropped: {x1 - x0}×{y1 - y0} px (annotations cleared)")

    def pick_color(self):
        c = QtWidgets.QColorDialog.getColor(self.canvas.color, self, t("dlg_pickcolor"))
        if c.isValid():
            self.canvas.set_color(c)
            self.btn_color.setIcon(swatch_icon(c))

    # --- OCR --- #
    def run_ocr(self):
        if self.image_bgr is None:
            self.status.setText(t("st_need_shot"))
            return
        try:
            import pytesseract
        except ImportError:
            self.status.setText("pytesseract not installed")
            return
        self.status.setText(t("st_ocr_running"))
        QtWidgets.QApplication.processEvents()

        if self.enhance.isChecked():
            proc = preprocess_for_ocr(self.image_bgr)   # grayscale binarized image
            pil = Image.fromarray(proc)
        else:
            pil = Image.fromarray(cv2.cvtColor(self.image_bgr, cv2.COLOR_BGR2RGB))

        # --oem 1 = LSTM engine; --psm page segmentation mode; preprocessing already upscaled, hint dpi for better segmentation
        psm = self.psm.currentData()
        config = f"--oem 1 --psm {psm} -c preserve_interword_spaces=1 --dpi 150"
        try:
            txt = pytesseract.image_to_string(
                pil, lang=self.lang.currentText(), config=config)
        except pytesseract.TesseractNotFoundError:
            self.status.setText("tesseract not found; run: apt install tesseract-ocr")
            return
        except Exception as exc:                      # noqa: BLE001
            self.status.setText(f"OCR error: {exc} (language pack may be missing)")
            return

        # Strip extra spaces commonly inserted between CJK chars (keep spaces between Latin words)
        if "chi" in self.lang.currentText():
            txt = _strip_cjk_spaces(txt)
        self.text.setPlainText(txt)
        QtWidgets.QApplication.clipboard().setText(txt)
        self.status.setText(
            (f"OCR done, copied to clipboard ({len(txt)} chars)" if _LANG == "en"
             else f"OCR 完成,已复制到剪贴板({len(txt)} 字符)"))

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
        PinnedImage(flat)
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
            cv2.imwrite(path, self.image_bgr)
            self.status.setText(("Saved: " if _LANG == "en" else "已保存:") + path)

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
        menu.addAction(t("t_settings"), self.show_settings)
        menu.addSeparator()
        menu.addAction(t("tray_quit"), self.quit_app)
        self._tray_menu = menu          # keep a reference to prevent GC
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(f"{t('app_name')} — {t('app_comment')}")

    def quit_app(self):
        if self._recorder is not None:
            self._on_record_stop()
        QtWidgets.QApplication.quit()

    def show_settings(self):
        import os
        s = self.settings
        shortcuts_available = kde_shortcuts_available()
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
        for cb in (cb_copy, cb_save, cb_edit):
            gf.addRow(cb)
        tabs.addTab(g, t("tab_general"))

        # ---------- Shortcuts ---------- #
        k = QtWidgets.QWidget(); k.setObjectName("settingsPage"); kf = QtWidgets.QFormLayout(k)
        kf.addRow(QtWidgets.QLabel(t("set_sc_hint")))
        run_sh = _run_sh_path()
        key_edits = {}
        for name, flag in SHORTCUT_ACTIONS:
            cmd_url = f"{run_sh} {flag}"
            kse = QtWidgets.QKeySequenceEdit()
            cur = kde_current_key(cmd_url) if shortcuts_available else ""
            if cur:
                kse.setKeySequence(QtGui.QKeySequence(cur))
            clr = QtWidgets.QToolButton(); clr.setText("✕")
            clr.clicked.connect(lambda _, e=kse: e.clear())
            row = QtWidgets.QHBoxLayout(); row.addWidget(kse); row.addWidget(clr)
            rw = QtWidgets.QWidget(); rw.setLayout(row)
            kf.addRow(self._action_label(flag), rw)
            key_edits[flag] = (kse, cmd_url, name)
        if shortcuts_available:
            tabs.addTab(k, t("tab_shortcuts"))

        # ---------- OCR ---------- #
        o = QtWidgets.QWidget(); o.setObjectName("settingsPage"); of = QtWidgets.QFormLayout(o)
        lang = QtWidgets.QComboBox(); lang.addItems(["chi_sim+eng", "chi_sim", "chi_tra+eng", "eng"])
        lang.setCurrentText(s.value("ocr_lang", "chi_sim+eng"))
        psm = QtWidgets.QComboBox()
        for txt, v in [("Block of text (psm 6)", 6), ("Auto (psm 3)", 3),
                       ("Single column (psm 4)", 4), ("Single line (psm 7)", 7)]:
            psm.addItem(txt, v)
        pi = psm.findData(int(s.value("ocr_psm", 6, type=int)))
        if pi >= 0:
            psm.setCurrentIndex(pi)
        enh = QtWidgets.QCheckBox(t("set_ocr_enh"))
        enh.setChecked(s.value("ocr_enhance", True, type=bool))
        of.addRow(t("set_ocr_deflang"), lang); of.addRow(t("set_ocr_deflayout"), psm); of.addRow(enh)
        of.addRow(QtWidgets.QLabel(t("set_ocr_note")))
        tabs.addTab(o, t("tab_ocr"))

        # ---------- Recording ---------- #
        r = QtWidgets.QWidget(); r.setObjectName("settingsPage"); rf = QtWidgets.QFormLayout(r)
        fps = QtWidgets.QSpinBox(); fps.setRange(5, 60); fps.setValue(s.value("record_fps", 15, type=int))
        rf.addRow(t("set_fps"), fps)
        cb_gif = QtWidgets.QCheckBox(t("set_gif")); cb_gif.setChecked(s.value("record_gif", False, type=bool))
        rf.addRow(cb_gif)
        tabs.addTab(r, t("tab_record"))

        # ---------- Interface ---------- #
        u = QtWidgets.QWidget(); u.setObjectName("settingsPage"); uf = QtWidgets.QFormLayout(u)
        theme = QtWidgets.QComboBox()
        for key, value in (("theme_system", "system"), ("theme_dark", "dark"),
                           ("theme_light", "light"), ("theme_starship", "starship")):
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
        uf.addRow(t("set_uilang"), ui_lang)
        tabs.addTab(u, t("tab_ui"))

        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject)
        outer.addWidget(bb)

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            self._apply_style()                      # discard the temporary preview
            return
        # save General / OCR / Recording / Interface
        s.setValue("save_dir", save_dir.text())
        s.setValue("name_tmpl", tmpl.text())
        s.setValue("auto_copy", cb_copy.isChecked())
        s.setValue("auto_save", cb_save.isChecked())
        s.setValue("open_editor", cb_edit.isChecked())
        s.setValue("ocr_lang", lang.currentText())
        s.setValue("ocr_psm", psm.currentData())
        s.setValue("ocr_enhance", enh.isChecked())
        s.setValue("record_fps", fps.value())
        s.setValue("record_gif", cb_gif.isChecked())
        s.setValue("ui_theme", theme.currentData())
        s.setValue("ui_accent", accent.currentData())
        s.setValue("ui_lang", ui_lang.currentData())
        # apply to the current UI
        self.lang.setCurrentText(lang.currentText())
        self.psm.setCurrentIndex(self.psm.findData(psm.currentData()))
        self.enhance.setChecked(enh.isChecked())
        set_lang(ui_lang.currentData())              # switch UI language
        write_desktop_entry(refresh=True)            # update launcher name/comment for the language
        self._apply_style()
        self._retranslate()                          # retranslate the UI immediately

        if shortcuts_available:
            # write shortcuts to KDE
            kde_backup_khotkeys()
            changed = 0
            for flag, (kse, cmd_url, name) in key_edits.items():
                key = kse.keySequence().toString(QtGui.QKeySequence.NativeText)
                key = key.split(",")[0].strip()          # keep only the first key combo
                uuid_key = f"uuid_{flag}"
                uid = s.value(uuid_key, "")
                if not uid:
                    import uuid as _uuid
                    uid = "{" + str(_uuid.uuid4()) + "}"
                    s.setValue(uuid_key, uid)
                kde_set_shortcut(name, cmd_url, key, uid)
                changed += 1
            kde_reload_shortcuts()
            self.status.setText(
                (f"Settings saved, {changed} shortcuts written to KDE" if _LANG == "en"
                 else f"设置已保存,{changed} 个快捷键已写入 KDE"))
        else:
            self.status.setText(t("st_settings_saved"))

    def _action_label(self, flag):
        return t({"--region": "cap_region", "--window": "cap_window",
                  "--scroll": "cap_scroll", "--manual": "cap_manual",
                  "--color": "cap_color"}.get(flag, "cap_region"))

    def show_history(self):
        if not self.history:
            self.status.setText(t("st_no_history"))
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"{t('hist_title')} ({len(self.history)})")
        dlg.resize(560, 480)
        v = QtWidgets.QVBoxLayout(dlg)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        inner = QtWidgets.QWidget(); grid = QtWidgets.QVBoxLayout(inner)
        for qimg, desc in self.history:
            row = QtWidgets.QPushButton()
            row.setIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(
                qimg.scaledToWidth(160, Qt.SmoothTransformation))))
            row.setIconSize(QtCore.QSize(160, 100))
            row.setText("  " + desc)
            row.setStyleSheet("text-align:left;")
            row.clicked.connect(
                lambda _, q=qimg: (self._load_history(q), dlg.accept()))
            grid.addWidget(row)
        grid.addStretch(1)
        scroll.setWidget(inner); v.addWidget(scroll)
        dlg.exec_()

    def _load_history(self, qimg):
        self.image_bgr = qimage_to_bgr(qimg)
        self._show_preview()
        self.showNormal(); self.activateWindow(); self.raise_()
        self.status.setText("Loaded from history")

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

    # ===================== P6: recording ===================== #
    def toggle_record(self):
        if self._recorder is not None:
            self._on_record_stop()
            return
        self.showMinimized()
        if getattr(self, "_thumb", None):
            self._thumb.close()
        QtCore.QTimer.singleShot(300, self._begin_record_select)

    def _begin_record_select(self):
        self.selector = RegionSelector(mode="region")
        self.selector.selected.connect(self._start_record)
        self.selector.cancelled.connect(self._restore)
        self.selector.show()
        self.selector.activateWindow(); self.selector.raise_()

    def _start_record(self, gr):
        import os
        dpr = QtWidgets.QApplication.primaryScreen().devicePixelRatio()
        phys = (int(gr.left() * dpr), int(gr.top() * dpr),
                int(gr.width() * dpr), int(gr.height() * dpr))
        d = self.settings.value("save_dir", os.path.expanduser("~/Videos"))
        os.makedirs(d, exist_ok=True)
        name = self._make_filename().replace(".png", ".mp4")
        self._rec_out = os.path.join(d, name)
        fps = self.settings.value("record_fps", 15, type=int)
        self._recorder = Recorder(phys, self._rec_out, fps=fps)
        if not self._recorder.start():
            self._recorder = None
            self._restore()
            QtWidgets.QMessageBox.critical(self, "Recording failed", "Could not start ffmpeg")
            return
        self._recbar = RecordBar(on_stop=self._on_record_stop)
        self._recbar.show(); self._recbar.raise_()

    def _on_record_stop(self):
        if self._recorder is None:
            return
        if getattr(self, "_recbar", None):
            self._recbar.stop_timer(); self._recbar.close()
        rec = self._recorder
        self._recorder = None
        rec.stop()
        out = self._rec_out
        msg = ("Recording saved: " if _LANG == "en" else "录屏已保存:") + out
        if self.settings.value("record_gif", False, type=bool):
            gif = out[:-4] + ".gif"
            if rec.to_gif(gif):
                msg += f"  GIF:{gif}"
        self.status.setText(msg)
        if hasattr(self, "tray"):
            self.tray.showMessage(t("app_name") + " — " + ("Recording saved" if _LANG == "en" else "录屏完成"), out,
                                  QtWidgets.QSystemTrayIcon.Information, 4000)
        self._restore()


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
    cli, _ = parser.parse_known_args()
    cmd = ("single" if cli.region else
           "manual" if cli.manual else
           "scroll" if cli.scroll else
           "window" if cli.window else
           "color" if cli.color else "show")

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

    win.handle_command(cmd if cmd != "show" else "show-first")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
