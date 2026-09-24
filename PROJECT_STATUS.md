# Project status

## Current state

- Source installation reuses Ubuntu Python packages through a virtual environment with system package access. pip installs only `mss` and `pytesseract`.
- The settings dialog works without KDE tools; KDE 5 shortcut integration is shown only when its desktop session and commands are available.
- The interface has complete dark, light, Starship Blue, and system preference palettes; the settings tabs and their content now use matching colors.

## Completed

- Updated `install.sh`, `run.sh`, and both READMEs for the source installation path.
- Verified shell syntax, apt dependency resolution, and imports of the reused system packages in a temporary virtual environment.
- Fixed the settings dialog on non-KDE desktops by using KDE shortcut tools only in a supported Plasma 5 session, and by refreshing the KDE menu cache only when its command exists.
- Verified that the settings dialog opens and saves on Ubuntu GNOME using the locally installed program dependencies.
- Added a saved appearance selector and theme-default accent option; rounded buttons and themed toolbar icons follow the selected palette.
- Rendered the settings dialog in dark, light, Starship Blue, and system modes with the installed PyQt5 runtime and checked the resulting images.
- Updated `/opt/kapture/kapture.py` on this machine and confirmed it matches the repository source. No Kapture process was running at the time; the next launch loads this version.

## Blockers and next step

- A full source installation was not run because it requires administrator access and a download of the two remaining Python packages.
- The upstream `.deb` is independent of this repository's install script and code changes; build and publish a fork release package to distribute them through `.deb`.
- System appearance is sampled on launch and when settings are saved; changing the desktop appearance while Kapture stays open requires reopening or resaving settings.
