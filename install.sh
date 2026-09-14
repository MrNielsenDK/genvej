#!/usr/bin/env bash
# Installs Genvej in the user's home directory. Does not need root.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$SHARE_DIR/genvej"
ICON_ROOT="$SHARE_DIR/icons/hicolor"

command -v python3 >/dev/null || { echo "python3 is missing" >&2; exit 1; }
python3 -c "import PySide6" 2>/dev/null || {
  echo "PySide6 is missing. Fedora/Bazzite: sudo dnf install python3-pyside6" >&2
  echo "Ubuntu/Debian: sudo apt install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets" >&2
  exit 1; }

install -d "$APP_DIR" "$BIN_DIR" "$SHARE_DIR/applications"
install -m 644 "$SOURCE_DIR/genvej.py" "$APP_DIR/genvej.py"

cat > "$BIN_DIR/genvej" <<WRAPPER
#!/usr/bin/env bash
exec python3 "$APP_DIR/genvej.py" "\$@"
WRAPPER
chmod +x "$BIN_DIR/genvej"

QT_QPA_PLATFORM=offscreen python3 "$SOURCE_DIR/data/make_icon.py" "$ICON_ROOT"
install -m 644 "$SOURCE_DIR/data/genvej.desktop" "$SHARE_DIR/applications/genvej.desktop"

command -v update-desktop-database >/dev/null && update-desktop-database "$SHARE_DIR/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$ICON_ROOT" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 --noincremental 2>/dev/null || true

echo "Genvej installed. Start it with 'genvej' or from the application menu."
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Note: $BIN_DIR is not in your PATH." ;; esac
