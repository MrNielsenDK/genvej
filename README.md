# Genvej

Turn websites into real desktop apps on Linux — and clean them up again.

Genvej (Danish for *shortcut*) is a small Qt 6 program that gathers all your web apps
in one place: the ones you create yourself from a URL, and the ones your Chromium-based
browser installed as PWAs. Other web app managers only see the shortcuts they created
themselves; Genvej finds all of them, because it reads the `.desktop` files directly.

## Features

- Create a web app from a URL — pick the browser, profile and icon
- Fetch the icon automatically from the website (favicon, apple-touch-icon or manifest)
- List every existing web app, no matter who created it
- Rename and change the icon, including on PWAs the browser installed itself
- Choose how the app's window opens — halves, quarters, maximized or full screen, on the
  screen of your choice (requires KDE Plasma)
- Move a web app from the desktop into the application menu — Brave installed as a Snap
  can only put its PWAs on the desktop
- Remove a web app completely, including its icon files and window rule
- Open the browser's apps page in the right profile, for when a PWA needs to be
  uninstalled in the browser as well

## Requirements

- Linux with a freedesktop-compliant desktop (KDE Plasma, GNOME, …)
- `python3` and `PySide6`
- At least one Chromium-based browser

Window size and placement use KWin window rules and are only available on KDE Plasma.
Everything else works on any desktop.

## Installation

```bash
git clone https://github.com/MrNielsenDK/genvej.git
cd genvej
./install.sh
```

The installer puts everything under `~/.local` and does not need root. Start Genvej from
the application menu or by running `genvej`.

PySide6 is already included on Fedora Atomic desktops such as Kinoite and Bazzite.
Elsewhere:

| Distribution | Command |
| --- | --- |
| Fedora | `sudo dnf install python3-pyside6` |
| Ubuntu / Debian | `sudo apt install python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets` |

There are no third-party Python packages, no build step and no virtualenv, so Genvej runs
directly on immutable systems without layering packages.

To uninstall, run `./uninstall.sh`. Your web apps are left in place.

## Supported browsers

Brave, Google Chrome, Chromium, Microsoft Edge and Vivaldi — as a system package or a
Flatpak. Brave and Chromium are also supported as a Snap.

Firefox is not supported, since it has no equivalent of Chromium's `--app=` mode.

## How it works

Genvej keeps no database of its own. Every time the list is refreshed, it scans
`~/.local/share/applications`, the Flatpak browsers' application directories and the
desktop for `.desktop` files whose `Exec` line contains `--app=` or `--app-id=`.

- **`--app=<url>`** is a regular shortcut. Genvej can edit everything about it.
- **`--app-id=<id>`** is a PWA the browser installed itself. The URL lives inside the
  browser profile, so Genvej only changes the name and icon. Removing it deletes the
  shortcut, but the browser may restore it — uninstall it on the browser's apps page
  (e.g. `brave://apps`) as well.

Window size, position and state are written as rules to KWin's `kwinrulesrc`, the same file
KDE's own window rules editor uses. Rules made by others are left alone. A rule takes
effect the next time the app's window opens.

## Known limitations

- A web app cannot minimize to the system tray when closed. The close button is handled
  inside the browser, and Wayland gives outside programs no way to intercept it.
- The user interface is English only.

## License

Genvej is free software, licensed under the
[GNU General Public License v3.0 or later](LICENSE).
