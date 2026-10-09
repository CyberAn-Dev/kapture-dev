<div align="center">

<img src="kapture.png" alt="Kapture Dev" width="88" />

# Kapture Dev

**An open-source PixPin alternative for Linux**

Screenshots · Scrolling capture · OCR · Pinned images · Annotation · Recording

Capture, extract text, and keep visual references at hand on Linux X11.

[简体中文](README.zh-CN.md) · [Quick start](#quick-start) · [Features](#features) · [Report an issue](https://github.com/CyberAn-Dev/kapture-dev/issues)

![Platform](https://img.shields.io/badge/Linux-X11-3776ab)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

</div>

<div align="center">

<img src="docs/images/editor.png" alt="Kapture Dev editor" width="900" />

<sub>Current editor with demonstration content and OCR results.</sub>

</div>

## A familiar capture workflow

- **Capture and explain**: select a region or snap to a window, add arrows, numbered steps, or mosaic, then copy and share.
- **Get text out of images**: use automatic OCR, select part of an image, or grab text directly from the screen.
- **Keep references beside your work**: pin clipboard images, zoom, and adjust opacity.
- **Go beyond one screen**: capture automatically or scroll manually, revisiting content without appending it twice.

## Features

| Tool | What it does |
| --- | --- |
| Capture | Resize the blue selection with eight handles and a pixel loupe; use grouped tools in a single-row toolbar. |
| Scrolling capture | Start manual scrolling in the red frame from the toolbar; automatic up/down modes, live preview, and duplicate-aware stitching. |
| OCR | Chinese and English recognition, automatic OCR after capture, editor text selection, and screen text grab. |
| Pin images | Keep images on top, zoom, adjust opacity, annotate with the grouped toolbar, and drag across recognized words to copy. |
| Edit and export | Undo/redo, move/delete annotations, change color/width, type directly on the canvas and double-click to edit text, and crop. Output saves original-size annotations or adds a decorative background, padding, rounded corners, and shadow. |
| Record | Red recording frame, MP4 with optional additional GIF, save/export progress, and Esc to stop. |
| Desktop | GNOME and KDE Plasma 5 shortcuts, themes, system tray, and background launch. |

The app has English and Simplified Chinese interfaces. OCR uses Tesseract; screen recording uses ffmpeg.

## Quick start

Use an **X11** session. The install scripts target Ubuntu or Kubuntu with `apt` and require internet access.

### From source

```bash
git clone https://github.com/CyberAn-Dev/kapture-dev.git
cd kapture-dev
bash install.sh
./run.sh
```

The installer adds system dependencies and an application-menu entry. Keep the checkout in place because the launcher uses its path.

### Optional: build a `.deb`

```bash
bash build_deb.sh 1.1.0
sudo apt install ./dist/kapture_1.1.0_all.deb
```

`1.1.0` is an example version. The package is built from the current checkout; launch with `kapture` and remove with `sudo apt remove kapture`.

Upstream [releases](https://github.com/ycwei5/kapture/releases) contain the upstream app and may not include this fork's changes.

<details>
<summary>Appearance and settings</summary>

<div align="center">

<img src="docs/images/settings.png" alt="Kapture Dev settings" width="660" />

<sub>Configure shortcuts, capture behavior, OCR, and appearance.</sub>

</div>

GNOME restores saved Kapture shortcuts at startup. Change conflicting combinations in Settings. Background launch hides the window; it does not enable login autostart.

</details>

## Everyday controls

| Action | Key / gesture |
| --- | --- |
| Pin newest / previous clipboard image | Ctrl+1 / Ctrl+2 (GNOME defaults, configurable) |
| Zoom / adjust pin opacity | Scroll / Ctrl+scroll |
| Recognize text in a pin | O or context menu |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z |
| Delete selected annotation | Delete |
| Stop scrolling capture / close focused pin | Esc |

Captures open in-place editing by default: Enter copies, Esc cancels, and the toolbar opens the full editor. The “open editor after capture” setting takes priority; turn both off to use thumbnails. Right-click a pin to annotate or select text; restore click-through pins from the tray.

History stays on this machine and survives restarts: up to 10 screenshots and 10 clipboard images, with a separate 40-million-pixel budget per collection; the newest image is always retained. Clear both collections from the history window.

## Command line

Run one action with `./run.sh <option>`, for example `./run.sh --region`.

- Capture: `--region`, `--window`, `--scroll`, `--manual`, `--repeat`
- Other: `--pin1`, `--pin2`, `--color`, `--record`, `--settings`, `--show`, `--background`

## How it differs from PixPin

Kapture Dev is an independent open-source fork of [Kapture](https://github.com/ycwei5/kapture), not affiliated with [PixPin](https://pixpin.cn/). It covers everyday screenshot, scrolling capture, OCR, and pinning workflows rather than full feature parity. OCR translation, QR recognition, and recording audio are not currently provided.

- X11 only; Wayland is not supported. In-app global shortcut setup is available on GNOME and KDE Plasma 5.
- Scrolling capture is limited to 40,000 pixels in height. Dynamic pages, overlays, lazy loading, and repeated content can affect alignment; it is not a browser full-page export.
- Capture coordinates across monitors with different scaling factors are not fully verified.
- OCR accuracy depends on text size, font, and image quality. Tesseract and its Chinese and English language packs must be installed.

## Contribute and license

Report issues or propose changes in [Issues](https://github.com/CyberAn-Dev/kapture-dev/issues) and [Pull Requests](https://github.com/CyberAn-Dev/kapture-dev/pulls).

Based on [ycwei5/kapture](https://github.com/ycwei5/kapture); see [LICENSE](LICENSE) for the MIT license and upstream copyright. Theme palettes are adapted from [One Dark Pro](https://github.com/Binaryify/OneDark-Pro) and [Vitesse](https://github.com/antfu/vscode-theme-vitesse).
