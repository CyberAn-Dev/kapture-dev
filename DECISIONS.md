# Decisions

## Source installation reuses Ubuntu Python packages

- Use apt for PyQt5, OpenCV, NumPy, Pillow, pynput, and packaging; use pip only for `mss` and `pytesseract`, which are unavailable as packages in the configured Ubuntu 24.04 repositories.
- Keep a project virtual environment with `--system-site-packages` so pip installs do not modify system Python.
- Set `PYTHONNOUSERSITE=1` for installation checks and application launch. On this machine, user site NumPy 2.5.1 conflicts with apt OpenCV, while apt NumPy 1.26.4 imports successfully with it.
- The existing upstream `.deb` is separate from the source installer; changing `install.sh` does not change that package.

## Settings on non-KDE desktops

- General, OCR, recording, and interface settings remain available without KDE utilities. The shortcut page uses GNOME custom keybindings in GNOME sessions, KHotKeys in supported Plasma 5 sessions, and displays manual command lines elsewhere.
- Menu cache refresh commands are optional; a missing KDE utility must not prevent saving unrelated settings.
- The upstream `.deb` remains independent of this fork's source changes; a new package build is required to distribute the fix through `.deb`.
- Reuse the existing action command line, single-instance socket, tray, and QSettings for shortcut dispatch and a start-hidden preference. GNOME writes only Kapture's custom-keybinding paths and preserves unrelated bindings; a scroll area keeps all actions accessible in the settings dialog.

## Interface themes

- Reuse the existing QSettings and stylesheet path for complete dark, light, and Starship Blue palettes, with a system option resolved from GNOME's color preference or the Qt palette at launch/save time.
- Keep the original dark look as the default for existing installations. The accent selector defaults to the active theme's accent and resets to that default when the theme changes.
- Starship configuration specifies ANSI blue, yellow, green, and red without fixed RGB values. The Starship Blue palette is an application interpretation of those colors, not an exact terminal palette copy.
- Style QTabWidget pane, tabs, and settings pages together so their background and text cannot come from conflicting light and dark palettes.
- Preview theme and accent by passing temporary values to the existing style renderer; keep QSettings untouched until OK, and reapply saved settings on Cancel.
- Keep the existing dark palette as the default. Adapt One Dark Pro Darker and Vitesse Dark from their official VS Code theme colors into the current Kapture palette fields instead of adding a separate styling engine.
- Use three compact toolbar groups for capture, options, and history/settings, with a distinct primary capture button. Split annotation and output into two visible rows instead of hiding actions in an overflow menu.

## Editor controls and automatic OCR

- Place output actions immediately after their label, keeping the row left aligned.
- Route Ctrl+Z to annotation undo when the editor controls have focus and to QPlainTextEdit undo when the OCR result box has focus.
- Enable screenshot OCR by default, show its result in the editor, and keep the screenshot image on the clipboard. Manual OCR continues to copy recognized text. A setting disables automatic OCR.
- Reuse the existing OCR preprocessing and Tesseract options inside a background QThread. Ignore older results after a new capture or editor change, and bound automatic Tesseract execution to 20 seconds.

## Pin clipboard images (Ctrl+1 / Ctrl+2)

- Pin-to-clipboard is PixPin-style: Ctrl+1 pins the most recent image on the system clipboard, Ctrl+2 pins the one before it, and Esc closes a pinned window. Reuse the existing global-shortcut pipeline (GNOME custom-keybinding / KDE KHotKey running `run.sh --pin1|--pin2`); the new actions join `SHORTCUT_ACTIONS` so they appear in the shortcuts tab automatically.
- The data source is a Kapture-internal image history built from `QClipboard.dataChanged` (newest first, capped at 10). No clipboard manager is installed and neither GNOME nor X11 exposes a readable history API, so the process must track images itself; Kapture's own `self.history` is not the source.
- Both defaults live in `DEFAULT_KEYS`: the shortcuts tab prefills them even when unregistered, and GNOME auto-registers them once on first run without overwriting an existing binding. The user accepted that global Ctrl+1/Ctrl+2 steal tab switching from Chrome/Edge/Firefox; no additional quit-style global shortcut was added (a `Ctrl+Alt+*` probe found Q free, but the user chose to keep only Ctrl+1/2).

## Shortcut save semantics and overlay window flags

- A blank shortcut row on save means "not bound", never "unbind": it keeps the stored binding and re-registers the path in the master array. Only the row's ✕ button (`explicit_clear`) removes the path and resets name/command/binding. Rationale: an action can vanish from the master `custom-keybindings` array while its binding stays stored; showing it as empty and then saving deleted it for good (the repeated Alt+\` failure).
- `gnome_current_key()` reads the action subpath directly, not only when the path is listed in the master array, so stored-but-unregistered bindings still display and can be repaired by a plain save.
- The region-selection overlay uses `X11BypassWindowManagerHint` rather than `Qt.Tool`, matching the other overlays, so it covers the top bar/dock and its geometry matches the frozen frame. Because bypassed windows receive no WM keyboard focus, the overlay grabs/releases the keyboard itself; Esc-cancel depends on this.
- Live verification runs the repository `kapture.py` under `/opt/kapture/.venv/bin/python` (the repo has no `.venv` on this machine), leaving the root-owned `/opt/kapture/kapture.py` untouched and requiring no sudo.

## Floating card icons and OCR display gating

- The floating capture card uses the `line_icon` vector set, not emoji: emoji render as empty boxes on systems without an emoji font, and vector icons inherit the app's existing icon style. Icons are validated by counting non-transparent pixels (`toImage()` without Format_ARGB32 ignores alpha and yields a false "full").
- Automatic OCR results are held in `_ocr_pending` until `_show_preview()` puts the image on the canvas, keyed by `_ocr_serial`; a crop invalidates the pending text. Chosen over delaying/slowing OCR itself — the engine (0.23–0.56 s) is not the bottleneck, ordering is.
