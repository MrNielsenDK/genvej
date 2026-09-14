#!/usr/bin/env bash
# Installs Genvej.
#
# Without arguments it installs into the user's home directory and does not need
# root. With --system it installs once under /usr/local for everybody on the
# machine, which is what a management tool wants: one copy to keep updated, and
# users created later get it too.
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX=""

for arg in "$@"; do
  case "$arg" in
    --system) PREFIX="/usr/local" ;;
    --prefix=*) PREFIX="${arg#--prefix=}" ;;
    -h|--help)
      echo "Usage: ./install.sh [--system | --prefix=DIR]"
      echo "  (no option)     install into \$HOME/.local, no root needed"
      echo "  --system        install into /usr/local for every user, needs root"
      echo "  --prefix=DIR    install into DIR the same way"
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

APP_DIR="$DATA_DIR/genvej"
ICON_ROOT="$DATA_DIR/icons/hicolor"
VERSION="$(sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$SOURCE_DIR/genvej.py")"

command -v python3 >/dev/null || { echo "python3 is missing" >&2; exit 1; }
python3 -c "import PySide6" 2>/dev/null || {
  echo "PySide6 is missing. Fedora/Bazzite: sudo dnf install python3-pyside6" >&2
  echo "Ubuntu/Debian: sudo apt install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets" >&2
  exit 1; }

# A prefix install usually means /usr/local, which needs root. Say so plainly
# rather than letting install(1) fail one directory at a time.
install -d "$APP_DIR" "$BIN_DIR" "$DATA_DIR/applications" 2>/dev/null || {
  echo "Cannot write to $DATA_DIR. Run the installer with sudo." >&2; exit 1; }
install -m 644 "$SOURCE_DIR/genvej.py" "$APP_DIR/genvej.py"

cat > "$BIN_DIR/genvej" <<WRAPPER
#!/usr/bin/env bash
exec python3 "$APP_DIR/genvej.py" "\$@"
WRAPPER
chmod +x "$BIN_DIR/genvej"

QT_QPA_PLATFORM=offscreen python3 "$SOURCE_DIR/data/make_icon.py" "$ICON_ROOT"
install -m 644 "$SOURCE_DIR/data/genvej.desktop" "$DATA_DIR/applications/genvej.desktop"

command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_DIR/applications" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -f -t "$ICON_ROOT" 2>/dev/null || true
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 --noincremental 2>/dev/null || true

echo "Genvej ${VERSION:-(unknown version)} installed in $DATA_DIR. Start it with 'genvej' or from the application menu."
if [ -z "$PREFIX" ]; then
  case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "Note: $BIN_DIR is not in your PATH." ;; esac
fi
