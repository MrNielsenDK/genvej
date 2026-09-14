#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renders the README screenshots in docs/ from made-up web apps.

Run with the real Qt platform, not offscreen — otherwise the theme icons are missing:

    env -u QT_QPA_PLATFORM python3 data/screenshot.py

Nothing is shown on screen, and nothing from the user's own browsers or files is used:
the web apps, icons and window rule live in a temporary directory.
"""

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["XDG_CURRENT_DESKTOP"] = "KDE"  # otherwise the Window group is disabled

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

QtWidgets.QApplication.setDesktopFileName("genvej")
application = QtWidgets.QApplication([])
import genvej as g

temporary = Path(tempfile.mkdtemp())
g.HOME = temporary
g.APPS_DIR = temporary / ".local/share/applications"
g.APPS_DIR.mkdir(parents=True)
g.ICON_ROOT = temporary / ".local/share/icons/hicolor"
g.SNAP_BIN = temporary / "snap-bin"
g.refresh_caches = lambda: None
g.kwin_reconfigure = lambda: None
icon_dir = temporary / "icons"
icon_dir.mkdir()

brave = g.Browser("brave-flatpak", "Brave (Flatpak)",
                  ["flatpak", "run", "--command=brave", "com.brave.Browser"], None, "brave")
chromium = g.Browser("chromium", "Chromium", ["/usr/bin/chromium"], None, "chromium")
browsers = [brave, chromium]
g.detect_browsers = lambda: browsers

# (name, URL or app id, browser, icon colour, installed by the browser)
APPS = [
    ("Wikipedia", "https://en.wikipedia.org/", chromium, "#3a3a3a", False),
    ("OpenStreetMap", "https://www.openstreetmap.org/", brave, "#7ebc6f", False),
    ("Mastodon", "https://mastodon.social/home", brave, "#6364ff", False),
    ("Excalidraw", "fdbfhcclmbpfnfkhgbnkfefkjmgfjbfe", brave, "#6965db", True),
    ("Proton Mail", "https://mail.proton.me/", brave, "#6d4aff", False),
    ("Jellyfin", "https://jellyfin.local:8096/web/", chromium, "#aa5cc3", False),
    ("Home Assistant", "http://homeassistant.local:8123/", chromium, "#18bcf2", False),
    ("Photopea", "kmdjnbhlehmgoejhpiibajcobcgnlapo", brave, "#18a497", True),
]
SELECTED = "Mastodon"


def letter_icon(name: str, colour: str) -> str:
    """A coloured square with the first letter — no real logos in the repository."""
    image = QtGui.QImage(256, 256, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QtGui.QColor(colour))
    painter.drawRoundedRect(QtCore.QRectF(8, 8, 240, 240), 56, 56)
    font = QtGui.QFont()
    font.setPixelSize(140)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QtGui.QColor("white"))
    painter.drawText(QtCore.QRectF(0, 0, 256, 256), Qt.AlignCenter, name[0])
    painter.end()
    path = icon_dir / f"{g.slugify(name)}.png"
    image.save(str(path))
    return str(path)


def write_apps() -> None:
    for name, target, browser, colour, installed in APPS:
        argument = f"--app-id={target}" if installed else f"--app={target}"
        exec_line = g.build_exec([*browser.argv, "--profile-directory=Default", argument])
        lines = ["[Desktop Entry]", "Type=Application", f"Name={name}", f"Exec={exec_line}",
                 f"Icon={letter_icon(name, colour)}"]
        if installed:
            lines.append(f"StartupWMClass={browser.wm_prefix}-{target}-Default")
        else:
            lines.append(f"{g.MARKER}=true")
        (g.APPS_DIR / f"{g.slugify(name)}.desktop").write_text("\n".join(lines) + "\n")

    # A window rule on the selected app, so the details pane has something to show.
    selected = next(app for app in APPS if app[0] == SELECTED)
    screen = QtGui.QGuiApplication.primaryScreen().availableGeometry()
    g.write_window_rule(g.wm_class_name(selected[2], selected[1], "", "Default"), SELECTED,
                        (screen.width() // 2, screen.height()), (screen.width() // 2, 0))


def render_main_window(target: Path) -> g.MainWindow:
    window = g.MainWindow()
    window.resize(980, 520)
    window.centralWidget().setSizes([520, 460])
    for row in range(window.list_widget.count()):
        if window.list_widget.item(row).text() == SELECTED:
            window.list_widget.setCurrentRow(row)
    # A hidden window never recomputes the height of word-wrapped labels, and the pane is
    # wide enough for single lines here.
    for label in window.detail_fields.values():
        label.setWordWrap(False)
    path_field = window.detail_fields["path"]
    path_field.setText(path_field.text().replace(str(temporary), "~"))
    window.grab()  # the first grab lays out the splitter
    application.processEvents()
    window.grab().save(str(target))
    return window


def render_editor(target: Path, parent: QtWidgets.QWidget) -> None:
    app = next(app for app in g.find_web_apps() if app.name == SELECTED)
    dialog = g.EditorDialog(browsers, app, parent)
    dialog.adjustSize()
    dialog.grab().save(str(target))


def main() -> None:
    output = REPO / "docs"
    output.mkdir(exist_ok=True)
    write_apps()
    window = render_main_window(output / "main-window.png")
    render_editor(output / "editor.png", window)
    print(f"wrote main-window.png and editor.png in {output}")


if __name__ == "__main__":
    main()
