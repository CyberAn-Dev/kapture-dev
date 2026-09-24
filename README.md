<div align="center">

<img src="kapture.png" alt="Kapture logo" width="120" />

# Kapture

**A fast, all-in-one screenshot · OCR · screen-recording tool for Linux (X11).**

Region / window / **scrolling long screenshots**, on-image annotation, built-in
**OCR (Chinese & English)**, screen recording, pin-to-screen, and beautified export —
all in one lightweight PyQt5 app.

[English](README.md) · [简体中文](README.zh-CN.md)

![Platform](https://img.shields.io/badge/platform-Linux%20%C2%B7%20X11-2b2b2b)
![Desktop](https://img.shields.io/badge/desktop-Kubuntu%20%C2%B7%20Ubuntu%20%C2%B7%20KDE-1793d1)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-41cd52)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
[![Latest release](https://img.shields.io/github/v/release/ycwei5/kapture?label=download&color=6c5ce7)](https://github.com/ycwei5/kapture/releases/latest)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/ycwei5/kapture/pulls)

</div>

---

<div align="center">

<img src="docs/images/editor.png" alt="Kapture editor — scrolling screenshot with annotations and OCR" width="820" />

<sub>The editor: a long screenshot with arrows, boxes, highlight, numbered steps, blur — and one-click OCR.</sub>

</div>

## What is Kapture?

**Kapture** is a free and open-source **screenshot tool for Linux** that puts capturing,
**scrolling (long) screenshots**, **OCR text recognition**, image annotation, and **screen recording**
into a single, keyboard-driven app. It is built with Python + PyQt5 and targets **X11** desktops such as
**Kubuntu, Ubuntu, and KDE Plasma**.

If you have been looking for a Linux alternative to Snipaste, ShareX, Flameshot, or a
**Linux scrolling screenshot / long screenshot tool with OCR**, Kapture is built exactly for that.

## ✨ Features

### 📸 Capture
- **Region capture** — drag a box to grab any part of the screen.
- **Window capture** — click a window to capture it.
- **Auto scrolling capture** — Kapture scrolls the target and stitches every frame into one
  seamless **long screenshot** (perfect for web pages, chat logs, code, documents).
- **Manual scrolling capture** — you scroll, Kapture stitches.
- **Repeat last area** — re-shoot the exact same region instantly.
- **Screen color picker** — eyedropper any pixel on screen.

### 🖍️ Annotate
Rectangle · Ellipse · Arrow · Line · Pen · Text · **Numbered steps** · Highlight ·
**Blur / mosaic** (hide sensitive info) · **Magnifier** · Crop — with adjustable color &
line width, plus undo and clear.

### 🔤 OCR (text recognition)
- Powered by **Tesseract**, recognizes **Simplified / Traditional Chinese and English**.
- Layout modes (block / auto / single column / single line) and an image-enhance toggle for accuracy.
- Extracted text is **copied to the clipboard** automatically.

### 🎬 Output & share
- **Auto-copy to clipboard** after capture, with a floating thumbnail in the corner.
- **📌 Pin to screen** — keep a screenshot floating on top (drag to move, scroll to zoom, double-click to close).
- **🎨 Beautify export** — gradient background, rounded corners, drop shadow.
- **⏺ Screen recording** to **MP4 / GIF** with adjustable frame rate.
- **🕘 History** of recent captures.

### ⚙️ Workflow
- **Global keyboard shortcuts** — bind any capture action system-wide (written straight into KDE).
- Configurable save folder, filename template, auto-copy / auto-save / open-editor behavior.
- Switch between dark, light, Starship Blue, [One Dark Pro Darker](https://github.com/Binaryify/OneDark-Pro/blob/master/themes/OneDark-Pro-darker.json), [Vitesse Dark](https://github.com/antfu/vscode-theme-vitesse/blob/main/themes/vitesse-dark.json), and system appearance in **Settings → Interface** (system preference is read on launch or when saving settings), with a separate accent color choice and a **bilingual UI (中文 / English)**. Selection previews immediately; OK saves it and Cancel restores the previous appearance. The two new palettes adapt their upstream colors to Kapture's controls; Starship Blue follows the prompt's blue color concept rather than the terminal's ANSI palette.
- Capture, options, history, and settings are visually grouped; annotation and output actions use separate rows so every button remains visible at the default window width.
- Lives quietly in the **system tray**, single-instance.

## 🖼️ Screenshots

| Editor — capture, annotate & OCR | Settings — folders, shortcuts, OCR, theme |
| :---: | :---: |
| <img src="docs/images/editor.png" alt="Kapture annotation editor" width="420" /> | <img src="docs/images/settings.png" alt="Kapture settings dialog" width="420" /> |

## 🚀 Installation

> **Requirements:** an **X11 session** on Kubuntu / Ubuntu / KDE.
> Check with `echo $XDG_SESSION_TYPE` — it should print `x11`.

### Option A — `.deb` package (recommended)

Download the latest **`kapture_*_all.deb`** from the
[**Releases**](https://github.com/ycwei5/kapture/releases/latest) page, then:

```bash
sudo apt install ./kapture_1.0.0_all.deb
```

`apt` pulls in Tesseract (Chinese + English), ffmpeg, fonts and the Qt runtime automatically.
On first install it builds an isolated Python environment, so **an internet connection is
required during installation**. Launch **Kapture** from your app menu, or run `kapture`.
Uninstall with `sudo apt remove kapture`.

### Option B — from source

```bash
# 1. Clone
git clone https://github.com/ycwei5/kapture.git
cd kapture

# 2. One-shot install (system deps + Python venv + app menu entry)
bash install.sh
```

The installer uses `apt` for the **Tesseract engine + Chinese language packs + ffmpeg**
and for PyQt5, OpenCV, NumPy, Pillow, and pynput. Its virtual environment reuses those
system packages; `pip` only installs `mss` and `pytesseract`. The launcher ignores user
site packages so they cannot override the system versions. The `.deb` above is a
separate upstream package and does not use this script. The installer also registers a
**Kapture** entry in your application menu.

## ▶️ Usage

- Search **Kapture** in your application menu, **or** run `./run.sh` from the terminal.
- Kapture runs as a single instance and lives in the **system tray** (right-click to quit).
- Bind **global shortcuts** in ⚙ **Settings → Shortcuts** — they are written to KDE automatically.

### Command line

`run.sh` jumps straight to an action — handy for binding to your own hotkeys:

```bash
./run.sh --region    # region capture
./run.sh --window    # window capture
./run.sh --scroll    # auto scrolling long screenshot
./run.sh --manual    # manual scrolling long screenshot
./run.sh --color     # screen color picker
```

## 💡 Tips for scrolling capture

- Select a **scrollable target window** (browser, chat, document). When capture starts,
  Kapture moves the cursor to the center of the selected area and sends scroll-wheel events —
  **don't move the mouse** after it begins.
- Use the **Speed** control in the top bar; lower it for smooth-scrolling / lazy-loading pages.
- Sticky headers/footers may repeat in a long screenshot (a common limitation of scrolling
  capture); the current version does not auto-trim them.

## 📦 Dependencies

| Type | Packages |
| --- | --- |
| **System (apt)** | `tesseract-ocr`, `tesseract-ocr-chi-sim`, `tesseract-ocr-chi-tra`, `fonts-noto-cjk`, `ffmpeg` |
| **Python (venv)** | `PyQt5`, `mss`, `opencv-python-headless`, `numpy`, `pillow`, `pynput`, `pytesseract` |

## ❓ FAQ

**Does Kapture work on Wayland?**
Not yet. Kapture targets **X11**, because simulated scrolling and full-screen grabbing are
restricted under Wayland. Run on an X11 session (`echo $XDG_SESSION_TYPE` → `x11`).

**Which languages can the OCR read?**
Simplified Chinese, Traditional Chinese, and English (`chi_sim+eng`, `chi_sim`, `chi_tra+eng`, `eng`),
powered by Tesseract. Recognized text is copied to your clipboard.

**Can it take a full-page / long screenshot of a web page?**
Yes — that is the **auto scrolling capture** feature. Kapture scrolls and stitches frames into one tall image.

**Is it free?**
Yes, Kapture is open source under the **MIT License**.

**Which desktops are supported?**
Built and tested on **Kubuntu / Ubuntu / KDE Plasma** on X11. Other X11 desktops likely work;
the global-shortcut writer is KDE-specific.

## 🤝 Contributing

Issues and pull requests are welcome! If you hit a bug or want a feature, please
[open an issue](https://github.com/ycwei5/kapture/issues). The whole app is a single,
readable `kapture.py` — easy to dive into.

## 📄 License

[MIT](LICENSE) © 2026 ycwei5

---

<div align="center">
<sub>

**Keywords:** Linux screenshot tool · scrolling screenshot · long screenshot · screenshot OCR ·
Tesseract OCR Linux · screen capture Ubuntu · Kubuntu KDE screenshot · screen recorder Linux ·
annotation tool · pin screenshot · X11 · PyQt5 · Snipaste / ShareX / Flameshot alternative for Linux

If Kapture is useful to you, please consider giving it a ⭐ — it helps others discover the project.

</sub>
</div>
