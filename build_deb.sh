#!/usr/bin/env bash
# Build the fork's .deb package. Usage: ./build_deb.sh <version>
# Output: dist/kapture_<version>_all.deb
set -euo pipefail

VERSION="${1:?usage: build_deb.sh <version>   e.g. 1.1.0}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$DIR/dist/kapture_$VERSION"_all.deb
ROOT="$DIR/dist/deb-root"
MAINTAINER="CyberAn-Dev <cyberan.dev@gmail.com>"
UPSTREAM_HOMEPAGE="https://github.com/ycwei5/kapture"
FORK_HOMEPAGE="https://github.com/CyberAn-Dev/kapture-dev"

rm -rf "$ROOT"
INST="$ROOT/opt/kapture"
mkdir -p "$INST" \
         "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/256x256/apps" \
         "$ROOT/usr/share/doc/kapture" \
         "$ROOT/DEBIAN"

# --- payload (layout identical to the upstream 1.0.0 package) --- #
cp "$DIR/kapture.py" "$INST/kapture.py"
cp "$DIR/kapture.png" "$INST/kapture.png"
cp "$DIR/kapture.png" "$ROOT/usr/share/icons/hicolor/256x256/apps/kapture.png"
cp "$DIR/README.md" "$ROOT/usr/share/doc/kapture/README.md"
cp "$DIR/README.zh-CN.md" "$ROOT/usr/share/doc/kapture/README.zh-CN.md"
cp "$DIR/LICENSE" "$ROOT/usr/share/doc/kapture/LICENSE"

cat > "$INST/run.sh" <<'EOF'
#!/usr/bin/env bash
# Kapture launcher (Debian package). Uses the venv built by the installer.
VENV=/opt/kapture/.venv
if [ ! -x "$VENV/bin/python" ]; then
    notify-send "Kapture" "Python environment is missing.\nRun:  sudo dpkg-reconfigure kapture" 2>/dev/null || true
    echo "Kapture: Python environment missing. Run: sudo dpkg-reconfigure kapture" >&2
    exit 1
fi
exec "$VENV/bin/python" /opt/kapture/kapture.py "$@"
EOF

cat > "$ROOT/usr/bin/kapture" <<'EOF'
#!/usr/bin/env bash
# Kapture launcher (Debian package). Uses the venv built by the installer.
VENV=/opt/kapture/.venv
if [ ! -x "$VENV/bin/python" ]; then
    notify-send "Kapture" "Python environment is missing.\nRun:  sudo dpkg-reconfigure kapture" 2>/dev/null || true
    echo "Kapture: Python environment missing. Run: sudo dpkg-reconfigure kapture" >&2
    exit 1
fi
exec "$VENV/bin/python" /opt/kapture/kapture.py "$@"
EOF

cat > "$ROOT/usr/share/applications/kapture.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Kapture
GenericName=Screenshot / OCR / Recording
Comment=Scrolling screenshot, OCR, annotation and recording
Exec=/opt/kapture/run.sh
Icon=kapture
Terminal=false
StartupWMClass=kapture
Categories=Graphics;Utility;
Keywords=screenshot;ocr;scroll;capture;record;annotation;
EOF

chmod 755 "$INST/run.sh" "$ROOT/usr/bin/kapture"

# --- control --- #
cat > "$ROOT/DEBIAN/control" <<EOF
Package: kapture
Version: $VERSION
Architecture: all
Maintainer: $MAINTAINER
Depends: python3 (>= 3.10), python3-venv, python3-pip, tesseract-ocr, tesseract-ocr-chi-sim, tesseract-ocr-chi-tra, fonts-noto-cjk, ffmpeg, libgl1, libxkbcommon-x11-0, libxcb-cursor0, libxcb-xinerama0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0
Recommends: libnotify-bin
Section: graphics
Priority: optional
Homepage: $FORK_HOMEPAGE
Description: Screenshot, OCR and screen recording tool for Linux (X11)
 Kapture is an all-in-one capture tool for X11 desktops (GNOME, KDE Plasma):
 region, window and scrolling long screenshots, on-image annotation,
 cursor-style word selection over OCR results, built-in Tesseract OCR for
 Chinese and English, screen recording to MP4/GIF, pin-to-screen and
 beautified export.
 .
 Fork of $UPSTREAM_HOMEPAGE with GNOME shortcut fixes, WM-bypass region
 overlay, floating capture card and in-editor word selection.
 .
 On first install the package creates an isolated Python environment and
 downloads the required Python libraries, so an internet connection is
 needed during installation.
EOF

# --- maintainer scripts (same behaviour as upstream) --- #
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
VENV=/opt/kapture/.venv
PKGS="PyQt5 mss opencv-python-headless numpy pillow pynput python-xlib pytesseract"

if [ ! -x "$VENV/bin/python" ]; then
    echo "Kapture: creating Python environment (requires network)…"
    if python3 -m venv "$VENV" \
        && "$VENV/bin/python" -m pip install --upgrade pip --quiet \
        && "$VENV/bin/python" -m pip install --quiet $PKGS ; then
        echo "Kapture: Python environment ready."
    else
        echo "----------------------------------------------------------------"
        echo "WARNING: Kapture could not install its Python libraries."
        echo "This usually means there was no internet connection."
        echo "After connecting, finish setup with:"
        echo "    sudo dpkg-reconfigure kapture   ||   sudo apt install --reinstall kapture"
        echo "----------------------------------------------------------------"
        rm -rf "$VENV"
    fi
fi

# make the venv readable/executable by all users
[ -d "$VENV" ] && chmod -R a+rX "$VENV" 2>/dev/null || true
update-desktop-database /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q /usr/share/icons/hicolor 2>/dev/null || true
exit 0
EOF

cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ] || [ "$1" = "abort-install" ]; then
    rm -rf /opt/kapture/.venv /opt/kapture/__pycache__
    rmdir /opt/kapture 2>/dev/null || true
fi
update-desktop-database /usr/share/applications 2>/dev/null || true
exit 0
EOF

chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"

# --- copyright (upstream MIT + fork notice) --- #
{
  echo "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/"
  echo "Upstream-Name: kapture"
  echo "Upstream-Contact: ycwei5 <tardis9527@gmail.com>"
  echo "Source: $UPSTREAM_HOMEPAGE"
  echo
  echo "Files: *"
  echo "Copyright: 2025 ycwei5"
  sed 's/^/License: /' "$DIR/LICENSE" | head -30
  echo
  echo "Files: /opt/kapture/kapture.py /usr/*"
  echo "Copyright: 2025-2026 CyberAn-Dev (fork, https://github.com/CyberAn-Dev/kapture-dev)"
  echo "License: same-as-upstream"
} > "$ROOT/usr/share/doc/kapture/copyright"

dpkg-deb --build --root-owner-group "$ROOT" "$PKG"
echo "BUILT: $PKG"
dpkg-deb -I "$PKG" | sed -n '1,15p'
