#!/usr/bin/env bash
# Build the public release bundle from the current working tree.
# Usage: ./make_release.sh <version>   e.g. ./make_release.sh 1.1.2
#
# The development tree keeps tests/ and local tooling; the release tree ships
# only what a user needs. Output, all under dist/:
#   release/kapture-<version>/       exported release tree
#   kapture_<version>_all.deb        Debian package (built from the release tree)
#   kapture-<version>.tar.gz         source archive
#   kapture-<version>.zip            source archive
set -euo pipefail

VERSION="${1:?usage: make_release.sh <version>   e.g. 1.1.2}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="kapture-$VERSION"
RELEASE="$DIR/dist/release/$NAME"

# --- release manifest: exactly what the public bundle contains --- #
FILES=(
    kapture.py
    history_store.py
    run.sh
    install.sh
    build_deb.sh
    kapture.png
    README.md
    README.zh-CN.md
    LICENSE
    docs/
)

rm -rf "$RELEASE"
mkdir -p "$RELEASE"
for item in "${FILES[@]}"; do
    [ -e "$DIR/$item" ] || { echo "missing required file: $item" >&2; exit 1; }
    cp -a "$DIR/$item" "$RELEASE/$item"
done

# --- the release tree must be self-contained and never carry test files --- #
find "$RELEASE" -name '__pycache__' -type d -prune -exec rm -rf {} +
if find "$RELEASE" -name 'test_*.py' -o -name 'x11_*_smoke.py' | grep -q .; then
    echo "release tree unexpectedly contains test files" >&2
    exit 1
fi
for required in kapture.py history_store.py run.sh build_deb.sh LICENSE; do
    [ -f "$RELEASE/$required" ] || { echo "release tree missing $required" >&2; exit 1; }
done

chmod 755 "$RELEASE/run.sh" "$RELEASE/install.sh" "$RELEASE/build_deb.sh"

# --- .deb built from the release tree, not the development tree --- #
# build_deb.sh resolves paths relative to itself, so its output lands inside
# the release tree; move it out and keep the tree free of build artifacts.
"$RELEASE/build_deb.sh" "$VERSION" >/dev/null
mv "$RELEASE/dist/kapture_${VERSION}_all.deb" "$DIR/dist/release/kapture_${VERSION}_all.deb"
rm -rf "$RELEASE/dist"

# --- source archives --- #
TARBALL="$DIR/dist/release/$NAME.tar.gz"
ZIP="$DIR/dist/release/$NAME.zip"
tar -czf "$TARBALL" -C "$DIR/dist/release" "$NAME"
if command -v zip >/dev/null 2>&1; then
    (cd "$DIR/dist/release" && rm -f "$NAME.zip" && zip -qr "$NAME.zip" "$NAME")
else
    echo "note: zip is not installed, only the tar.gz was produced" >&2
fi

echo
echo "RELEASE BUNDLE ($NAME)"
ls -1 "$DIR/dist/release"
echo
echo "contents:"
tar -tzf "$TARBALL" | sed 's|^[^/]*/||' | grep -v '/$' | sort | sed 's/^/  /'
