# Kapture Dev

**Screenshots, scrolling capture, OCR, annotation, and pinned images for Linux X11.**

Based on [ycwei5/kapture](https://github.com/ycwei5/kapture), this fork adds bidirectional scrolling capture, OCR text selection, clipboard image pins, window snapping, GNOME shortcut recovery, and more themes.

[简体中文](README.zh-CN.md)

<div align="center">

<img src="docs/images/editor.png" alt="Kapture Dev editor" width="900" />

<sub>Current editor with demonstration content and OCR results.</sub>

</div>

## Features

| Tool | What it does |
| --- | --- |
| Capture | Region or window capture, window snapping, color picker, and repeat last region. |
| Scrolling capture | Automatic up/down or manual scrolling, with live preview and duplicate-aware stitching. |
| OCR | Chinese and English recognition, automatic OCR after capture, editor text selection, and screen text grab. |
| Pin images | Keep clipboard images on top; move, resize, adjust opacity, or copy recognized text. |
| Edit and export | Annotate, crop, save, copy, or export with a background and shadow. |
| Record | Capture the screen as MP4 or GIF; adjust frame rate. |
| Desktop | GNOME and KDE Plasma 5 shortcuts, themes, system tray, and background launch. |

The app has English and Simplified Chinese interfaces. OCR uses Tesseract; screen recording uses ffmpeg.

## Settings

<div align="center">

<img src="docs/images/settings.png" alt="Kapture Dev settings" width="660" />

<sub>Configure shortcuts, capture behavior, OCR, and appearance.</sub>

</div>

GNOME restores saved Kapture shortcuts at startup. Change conflicting combinations in Settings. Background launch hides the window; it does not enable login autostart.

## Install

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

## Command line

Run one action with `./run.sh <option>`, for example `./run.sh --region`.

- Capture: `--region`, `--window`, `--scroll`, `--manual`, `--repeat`
- Other: `--pin1`, `--pin2`, `--color`, `--record`, `--settings`, `--show`, `--background`

## Limits

- X11 only; Wayland is not supported. In-app global shortcut setup is available on GNOME and KDE Plasma 5.
- Scrolling capture is limited to 40,000 pixels in height. Dynamic pages, overlays, lazy loading, and repeated content can affect alignment; it is not a browser full-page export.
- OCR accuracy depends on text size, font, and image quality. Tesseract and its Chinese and English language packs must be installed.

## Contribute and license

Report issues or propose changes in [Issues](https://github.com/CyberAn-Dev/kapture-dev/issues) and [Pull Requests](https://github.com/CyberAn-Dev/kapture-dev/pulls).

Based on [ycwei5/kapture](https://github.com/ycwei5/kapture); see [LICENSE](LICENSE) for the MIT license and upstream copyright. Theme palettes are adapted from [One Dark Pro](https://github.com/Binaryify/OneDark-Pro) and [Vitesse](https://github.com/antfu/vscode-theme-vitesse).
