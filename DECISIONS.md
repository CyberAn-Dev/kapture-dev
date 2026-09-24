# Decisions

## Source installation reuses Ubuntu Python packages

- Use apt for PyQt5, OpenCV, NumPy, Pillow, pynput, and packaging; use pip only for `mss` and `pytesseract`, which are unavailable as packages in the configured Ubuntu 24.04 repositories.
- Keep a project virtual environment with `--system-site-packages` so pip installs do not modify system Python.
- Set `PYTHONNOUSERSITE=1` for installation checks and application launch. On this machine, user site NumPy 2.5.1 conflicts with apt OpenCV, while apt NumPy 1.26.4 imports successfully with it.
- The existing upstream `.deb` is separate from the source installer; changing `install.sh` does not change that package.

## Settings on non-KDE desktops

- General, OCR, recording, and interface settings remain available without KDE utilities. The KDE 5 shortcut tab and writes are used only in a Plasma 5 session with the required commands.
- Menu cache refresh commands are optional; a missing KDE utility must not prevent saving unrelated settings.
- The upstream `.deb` remains independent of this fork's source changes; a new package build is required to distribute the fix through `.deb`.

## Interface themes

- Reuse the existing QSettings and stylesheet path for complete dark, light, and Starship Blue palettes, with a system option resolved from GNOME's color preference or the Qt palette at launch/save time.
- Keep the original dark look as the default for existing installations. The accent selector defaults to the active theme's accent and resets to that default when the theme changes.
- Starship configuration specifies ANSI blue, yellow, green, and red without fixed RGB values. The Starship Blue palette is an application interpretation of those colors, not an exact terminal palette copy.
- Style QTabWidget pane, tabs, and settings pages together so their background and text cannot come from conflicting light and dark palettes.
- Preview theme and accent by passing temporary values to the existing style renderer; keep QSettings untouched until OK, and reapply saved settings on Cancel.
