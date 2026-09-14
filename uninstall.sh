#!/usr/bin/env bash
# Removes Genvej. Leaves the web apps you created with it untouched.
#
# Mirrors install.sh: no option removes the copy in your home directory,
# --system removes the one under /usr/local.
set -euo pipefail

PREFIX=""
for arg in "$@"; do
  case "$arg" in
    --system) PREFIX="/usr/local" ;;
    --prefix=*) PREFIX="${arg#--prefix=}" ;;
    -h|--help)
      echo "Usage: ./uninstall.sh [--system | --prefix=DIR]"
      exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

if [ -n "$PREFIX" ]; then
  DATA_DIR="$PREFIX/share"
  BIN_DIR="$PREFIX/bin"
else
  DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
  BIN_DIR="$HOME/.local/bin"
fi
ICON_ROOT="$DATA_DIR/icons/hicolor"

rm -rf "$DATA_DIR/genvej"
rm -f "$BIN_DIR/genvej"
rm -f "$DATA_DIR/applications/genvej.desktop"
rm -f "$ICON_ROOT"/*/apps/genvej.png

command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_DIR/applications" || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 --noincremental 2>/dev/null || true
echo "Genvej removed from $DATA_DIR. Your web apps are untouched."
