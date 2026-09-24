# Project status

## Current state

- Source installation reuses Ubuntu Python packages through a virtual environment with system package access. pip installs only `mss` and `pytesseract`.
- The settings dialog works without KDE tools; KDE 5 shortcut integration is shown only when its desktop session and commands are available.
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
- The complete offscreen Qt test suite passes (10 tests); fixed the older theme-preview test to reuse its existing QApplication so the suite exits cleanly.

## Blockers and next step

- A full source installation was not run because it requires administrator access and a download of the two remaining Python packages.
- The upstream `.deb` is independent of this repository's install script and code changes; build and publish a fork release package to distribute them through `.deb`.
- System appearance is sampled on launch and when settings are saved; changing the desktop appearance while Kapture stays open requires reopening or resaving settings.
- PixPin comparison identified screenshot-time UI element detection, QR recognition, configurable annotation toolbar, richer pin content and management, and OCR interaction for pinned images as product gaps; these are not part of this fix.
