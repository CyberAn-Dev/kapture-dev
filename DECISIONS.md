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

- Startup shortcut registration is self-healing, not first-run-only: `_ensure_default_shortcuts` re-registers every stored binding back into the master `custom-keybindings` array (a bound action is rewritten with its own value, so user choices survive) and repeats once after 6 s to outrace GNOME's login-time clobber. Root-cause evidence: after each login only the `DEFAULT_KEYS` paths (pin1/pin2) were present while the stored region binding stayed outside the array — the exact state settings-save repaired by hand, hence "Alt+` only works after opening settings".
- A blank shortcut row on save means "not bound", never "unbind": it keeps the stored binding and re-registers the path in the master array. Only the row's ✕ button (`explicit_clear`) removes the path and resets name/command/binding. Rationale: an action can vanish from the master `custom-keybindings` array while its binding stays stored; showing it as empty and then saving deleted it for good (the repeated Alt+\` failure).
- `gnome_current_key()` reads the action subpath directly, not only when the path is listed in the master array, so stored-but-unregistered bindings still display and can be repaired by a plain save.
- The region-selection overlay uses `X11BypassWindowManagerHint` rather than `Qt.Tool`, matching the other overlays, so it covers the top bar/dock and its geometry matches the frozen frame. Because bypassed windows receive no WM keyboard focus, the overlay grabs/releases the keyboard itself; Esc-cancel depends on this.
- Live verification runs the repository `kapture.py` through the repository `run.sh`, whose `.venv` symlink points at `/opt/kapture/.venv`, leaving the root-owned `/opt/kapture/kapture.py` untouched and requiring no sudo.

## Screen text grab (toolbar action) and OCR box buttons

- 截屏取词 is a capture mode (`--mode textgrab`), not an editor tool: region → grab → background OCR → trimmed text to clipboard only; the editor never opens, no image is copied, no thumbnail. Reuses the frozen frame, delay countdown and `_last_phys` (repeat) like normal region capture.
- Its OCR runs on a dedicated `OCRWorker` (`automatic=True` for the 20 s bound) instead of `run_ocr()`, so the editor's `_ocr_serial`/pending/toast state stays untouched; feedback is a standalone `_flash_note` (a `_make_hint`-style bypass-WM toast) because the editor's `_toast` lives inside the OCR text box and would be invisible. Not in `SHORTCUT_ACTIONS` for now — toolbar-only.
- The OCR box bottom-left holds 全部识别 (re-runs `run_ocr(copy_result=False)`) and 全部复制 (copies the text box, empty box keeps the clipboard). Implemented by wrapping `self.text` in a container widget with a button row rather than overlaying buttons.
- picktext keeps the I-beam cursor only while the pointer is over a recognized word box (checked in `mouseMoveEvent` via `_word_at`); the default cursor is the arrow, and word-box-free images never show an I-beam. Rationale: a permanent I-beam suggested selectable text everywhere there is none.
- 全部识别/全部复制 are children of `QPlainTextEdit.viewport()` (a container-widget row below the box was the first cut and rejected), positioned in the viewport's bottom-left and shown only while `textChanged` reports non-empty content — one signal covers OCR results, picktext copies, crops and manual edits.
- Scrolling-capture feedback is a shared `ScrollHud` (live thumbnail + height + stop, placed outside the region) plus a red region frame. Both modes use it; `ManualBar` is deleted. Auto mode streams previews through a new `CaptureWorker.frame` signal, downscaled to 1200 px before emitting (queued-signal cost stays bounded for 40 000 px captures); the HUD's stop calls `worker.abort()`, reusing the worker's existing partial-result emit path instead of a new one.
- The region frame is four thin always-on-top strips hugging the region's outer edge, NOT a full-desktop translucent overlay: `WA_TransparentForMouseEvents` is Qt-application-local and does not make an X11 top-level window click-through, so a full-desktop overlay swallowed pynput's wheel events and the auto scrolling capture could no longer scroll (self-inflicted regression, fixed by construction — the strips never cover the region and are mouse-transparent).
- Automatic and manual scrolling share `CaptureWorker` and global-canvas matching. Manual grabbing, matching, stitching, and preview downsampling run off the GUI thread. Both directions extend only outside the existing canvas; automatic capture defaults downward and exposes upward capture in its toolbar dropdown.
- Match textured strips only, validate the full overlap, and reject ambiguous repeated-row matches. An unchanged frame stays at its previous location; seam refinement preserves the proposed offset on ties and touches only overlap rows. Convert only the bounded canvas search region. Manual unlocatable frames prompt the user to return to captured content; automatic capture stops with the continuous partial image instead of advancing its reference across missing content. Featureless/repeated pages cannot always be positioned uniquely from pixels alone.
- Before every framebuffer grab, the GUI hides both border windows and HUD, then acknowledges after 100 ms for compositor repaint. The worker waits at most 3 s; Esc wakes it on cancellation. Controls reappear between grabs. This avoids compositor shadows entering the selected region, including systems that ignore no-shadow hints. The HUD is hidden when no screen has room outside the region; a temporary global Esc listener remains available and is removed on completion. Starting another region capture while one is active is refused.
- HUD aspect ratio comes entirely from the preview array, while the displayed pixel height is passed separately from the original canvas. Automatic and manual modes use the same payload.
- Clipboard history compares complete QImage content directly, replacing partial SHA1 sampling; central-only changes must create a new history entry. No new hash or fingerprint is introduced.
- Explicit image saving exports the flattened annotated QImage only. A failed write reports failure; it must never fall back to the original unannotated image or claim success.

## Persistent autostart unit

- `~/.config/systemd/user/kapture.service` runs the **dev repo** `run.sh --background` (latest code, no sudo, survives without /opt) rather than `/opt/kapture` (root-owned, upstream-upgrade-overwritten). Trade-off accepted: deleting/moving the dev checkout breaks autostart.
- `WantedBy=graphical-session.target` + `PartOf=graphical-session.target` (the unit must die and restart with the graphical session, and a plain `--background` process exiting is a clean exit that `Restart=on-failure` will not resurrect); no hard-coded `Environment=DISPLAY=:0` — the real `DISPLAY`/`XAUTHORITY`/`DBUS_SESSION_BUS_ADDRESS` come via `PassEnvironment` from the user manager, so a different screen number cannot break startup.

## Floating card icons and OCR display gating

- The floating capture card uses the `line_icon` vector set, not emoji: emoji render as empty boxes on systems without an emoji font, and vector icons inherit the app's existing icon style. Icons are validated by counting non-transparent pixels (`toImage()` without Format_ARGB32 ignores alpha and yields a false "full").
- Automatic OCR results are held in `_ocr_pending` until `_show_preview()` puts the image on the canvas, keyed by `_ocr_serial`; a crop invalidates the pending text. Chosen over delaying/slowing OCR itself — the engine (0.23–0.56 s) is not the bottleneck, ordering is.
- In-editor text grab is a canvas tool (`picktext`), not a separate mode: drag → `textGrabRequested(QRectF)` → OCR only that crop with `copy_result=True`; Enter re-OCRs the remembered `_last_pick_rect`. picktext is the default selected tool. The dashed box is preview-only and excluded from annotations/exports, same rule as crop.

## Pending follow-ups from user feedback

- (none currently open)
