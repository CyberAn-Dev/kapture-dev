# Project status

## Current state

- Source installation reuses Ubuntu Python packages through a virtual environment with system package access. pip installs only `mss` and `pytesseract`.
- The shortcuts tab is visible on every desktop. GNOME custom shortcuts and KDE Plasma 5 KHotKeys can be edited in-app; other desktops show the command lines to bind in system settings.
- A General setting can hide the main window on launch while the existing tray process remains active; the show-window command or tray can bring it back.
- The interface has complete dark, light, Starship Blue, One Dark Pro Darker, Vitesse Dark, and system preference palettes; the settings tabs and their content use matching colors.
- Capture and utility controls are visually grouped. Annotation and output actions occupy separate rows, avoiding the previous toolbar width overflow.
- Theme and accent selection in the settings dialog previews immediately without changing saved preferences; Cancel restores the saved appearance and OK persists the selection.
- Output actions align beside their label. Ctrl+Z undoes annotations except when the OCR text box has focus, where it undoes text edits. Automatic OCR is enabled by default and can be disabled in settings.

## Completed

- Updated `install.sh`, `run.sh`, and both READMEs for the source installation path.
- Verified shell syntax, apt dependency resolution, and imports of the reused system packages in a temporary virtual environment.
- Fixed the settings dialog on non-KDE desktops by using KDE shortcut tools only in a supported Plasma 5 session, and by refreshing the KDE menu cache only when its command exists.
- Verified that the settings dialog opens and saves on Ubuntu GNOME using the locally installed program dependencies.
- Added a saved appearance selector and theme-default accent option; rounded buttons and themed toolbar icons follow the selected palette.
- Rendered the settings dialog in dark, light, Starship Blue, and system modes with the installed PyQt5 runtime and checked the resulting images.
- Updated `/opt/kapture/kapture.py` on this machine, confirmed it matches the repository source, and restarted the active user service; it is active with the current fixes.
- Added an offscreen Qt regression test for live theme preview, Cancel restoration, and OK persistence.
- Added offscreen Qt checks for the two new themes and for all actions remaining visible at the default 820 px width; inspected dark-theme renders at 820 px and button geometry at 700 px.
- Verified automatic OCR with the locally installed Tesseract engine on a generated `HELLO 123` image; the recognized text appeared while the captured image remained on the clipboard.
- Added focused checks for output alignment, context-aware Ctrl+Z, automatic OCR settings, and suppression of stale results from earlier captures.
- The complete offscreen Qt test suite passes (15 tests); fixed the older theme-preview test to reuse its existing QApplication so the suite exits cleanly.
- Added GNOME shortcut editing with isolated GSettings integration checks; verified that Kapture entries can be added and cleared without changing unrelated custom shortcut entries. A 560×470 settings render shows the nine shortcut rows inside a scrollable page.
- Diagnosed the user's "Alt+` shortcut dead" reports. Root cause #1: `gnome_accelerator()` wrote literal punctuation (`<Alt>`` `) instead of the X keysym name (`<Alt>grave`); GTK parses the former to keysym 0, so the binding registered but never fired. Fixed with a punctuation→keysym map; verified every punctuation key now parses via `Gtk.accelerator_parse`.
- Root cause #2 of the shortcut going dead again *after* that fix: GNOME only activates shortcuts listed in the master `media-keys custom-keybindings` array. An earlier in-place correction set the `kapture-region` subpath's `binding` to `<Alt>grave` but never re-added its path to that array, so the master list was `@as []` and the binding never fired. Restored the array to `['.../kapture-region/']`; the stored `<Alt>grave` parses to keysym 96 (live) and the media-keys plugin hot-reloads on the dconf change. The user confirmed Alt+\` works again.
- Added PixPin-style pin-to-clipboard: new `--pin1`/`--pin2` actions (Ctrl+1 pins the newest system-clipboard image, Ctrl+2 the previous one), sourced from a `QClipboard.dataChanged` image history (newest first, capped at 10). `PinnedImage` now closes on Esc (StrongFocus + keyPressEvent). Defaults `{"--pin1": "Ctrl+1", "--pin2": "Ctrl+2"}` are prefilled in the shortcuts tab and auto-registered once on first GNOME run. Verified: `<Control>1/2` parse to live keysyms; a new 7-test offscreen suite plus the 15 existing tests pass (22 total).
- Root cause of the tray no-response: it is NOT a tray-code or libqgtk3 defect. D-Bus capture proved gnome-shell delivers the physical click (`com.canonical.dbusmenu.Event`) to the running Kapture, and injected events open the settings dialog and main window normally. The real symptom is GNOME focus-stealing prevention — a tray/background activation carries no user-input timestamp, so the restored window stays Iconic/unfocused behind the current window. Added `MainWindow._bring_to_front()` (clear minimized flag + raise + deferred re-raise) routed through the show and settings commands.
- Region-selector overlay now bypasses the window manager (`Qt.X11BypassWindowManagerHint` instead of `Qt.Tool`, matching ManualBar/RecordBar/WindowPicker): a WM-managed Tool window is clamped to the work area, which offset the selection from the frozen full-geometry frame and let the top bar/dock interfere. A bypassed window gets no WM keyboard focus, so the widget now sets `StrongFocus` and grabs/releases the keyboard itself to keep Esc working. New offscreen tests cover flags, focus policy and Esc-cancel (28 tests total).
- Settings save no longer silently unregisters shortcuts. `gnome_current_key()` reads the action's subpath directly instead of only when the path is in the master array, so a binding dropped from that array still shows in the dialog; an empty row on save now keeps the stored binding and re-registers it, and only the row's ✕ button clears path and binding. This was the recurring "Alt+\` died after saving settings" cycle. A third outage had a separate cause: the bound command runs the dev-repo `run.sh`, whose `.venv` did not exist in a fresh checkout (gitignored) — fixed on this machine with a `.venv → /opt/kapture/.venv` symlink; the user confirmed Alt+\` and capture work after these fixes.
- Floating capture card enlarged (thumbnail 220→340 px wide / 260→400 px tall) and its five action buttons switched from emoji glyphs (which render as empty boxes without an emoji font) to the same vector `line_icon` set as the main toolbar; the pen icon was redrawn as a pencil with a squiggle for legibility.
- Automatic OCR text is held (`_ocr_pending`) until the captured image is actually shown in the editor, so text no longer appears "before the image loads"; crop drops stale pending results. Measured OCR latency: 0.23 s (eng), 0.56 s (chi_sim+eng) on a 1200×800 capture.
- PixPin-style text grab: the editor's default annotation tool is now **picktext** — drag a dashed box over text and the crop is OCR'd and copied (Enter re-OCRs the last region; the box never lands in annotations). Background OCR no longer writes "OCR 完成（N 字符）" to the status bar while the editor is off screen. The card's action buttons are one segmented rounded bar with hairline dividers and localized tooltips. Main-window tooltips verified present (they always were, via `_retranslate`). 33 tests green (4 new picktext cases).

## Blockers and next step

- A full source installation was not run because it requires administrator access and a download of the two remaining Python packages.
- The upstream `.deb` is independent of this repository's install script and code changes; build and publish a fork release package to distribute them through `.deb`.
- System appearance is sampled on launch and when settings are saved; changing the desktop appearance while Kapture stays open requires reopening or resaving settings.
- PixPin comparison identified screenshot-time UI element detection, QR recognition, configurable annotation toolbar, richer pin content and management, and OCR interaction for pinned images as product gaps; these are not part of this fix.
- GNOME may already own a chosen global combination; such a conflict must be resolved in the desktop's Keyboard settings.
- A persistent user service `~/.config/systemd/user/kapture.service` (runs /opt/kapture, WantedBy=default.target) was drafted to replace the transient unit, but has not yet been installed/enabled; the running instance is still the transient `kapture-fixed-20260924.service`.
- The `_bring_to_front` tray-restore fix is unverified on the live GNOME session — it only proves out after restarting the running instance and clicking the tray icon.
- /opt/kapture/kapture.py is owned by the upstream `.deb`; syncing the fix there is overwritten by any future kapture package upgrade. Rebuilding a fork `.deb` remains the durable distribution path.
