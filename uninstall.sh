#!/usr/bin/env bash
# Removes Genvej. Leaves the web apps you created with it untouched.
set -euo pipefail

SHARE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
ICON_ROOT="$SHARE_DIR/icons/hicolor"

rm -rf "$SHARE_DIR/genvej"
rm -f "$HOME/.local/bin/genvej"
rm -f "$SHARE_DIR/applications/genvej.desktop"
rm -f "$ICON_ROOT"/*/apps/genvej.png

command -v update-desktop-database >/dev/null && update-desktop-database "$SHARE_DIR/applications" || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 --noincremental 2>/dev/null || true
echo "Genvej removed. Your web apps are untouched."
