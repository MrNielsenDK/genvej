# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Genvej

A Qt 6 desktop program for creating, editing and removing web apps (PWAs) on Linux.
It can both create new shortcuts from a URL and manage the PWAs a Chromium-based
browser installed itself — the latter is why the project exists, since the
alternatives on Flathub (`dev.heppen.webapps`, `net.codelogistics.webapps`,
`org.pvermeer.WebAppHub`) can only see their own.

## Files

| Path | Role |
| --- | --- |
| `genvej.py` | The whole program — logic and GUI in one module |
| `data/make_icon.py` | Draws the program icon with QPainter, no image files in the repo. Takes the icon root as an argument and is run offscreen by `install.sh` |
| `data/genvej.desktop` | Menu entry |
| `install.sh` / `uninstall.sh` | Installation in `~/.local`, without root |
| `data/screenshot.py` | Renders the README screenshots in `docs/` from made-up web apps |
| `LICENSE` | GPL-3.0; source files carry `SPDX-License-Identifier: GPL-3.0-or-later` |

Once installed, the code lives in `~/.local/share/genvej/genvej.py`. Always run `./install.sh`
after a change — the program runs from the installed copy, not from the repo.

The version number exists in one place only: `VERSION` near the top of `genvej.py`. It is
shown with `genvej --version` and in the main window's status bar, and `install.sh` reads it
with `sed`, so keep the line in the form `VERSION = "x.y.z"`. Releases are GitHub Releases
tagged `v<VERSION>`; users download GitHub's source archive and run `install.sh`.
`gh release create --target <short commit hash>` failed with HTTP 422 ("tag_name is not a
valid tag"), so create and push the tag first:

```bash
git tag -a v1.2.3 -m "Genvej 1.2.3" && git push origin v1.2.3
gh release create v1.2.3 --verify-tag --title "Genvej 1.2.3" --notes-file notes.md
gh release download v1.2.3 --archive=tar.gz   # genvej-1.2.3.tar.gz → genvej-1.2.3/, as the README says
```

## Structure

`genvej.py` is split into sections: .desktop handling, browsers and profiles, discovered
web apps, icons, window rules, editor dialog, writing and removal, main window.

- **No database of its own.** Web apps are derived from the `.desktop` files on every
  `reload()`: `scan_dirs()` → `find_web_apps()` → `WebApp`. A file is a web app if `Exec`
  contains `--app=` or `--app-id=`; Genvej's own files also have `X-Genvej=true` (`managed`).
- **The browser is recognized by its argv.** `detect_browsers()` builds one `Browser` object
  per installation type (system package, `-snap`, `-flatpak`) from `BROWSER_TABLE` and
  `ALT_BINARIES`. `WebApp.argv_prefix` is the Exec words before the first `--app`/`--app-id`/
  `--profile-directory`/`--class`, and a web app belongs to the browser whose `argv` equals
  it (`find_browser()`, `EditorDialog.load_existing()`). If the way argv is written or read
  changes, both sides must follow.
- **All writes** go through `save_webapp()`, `patch_desktop()`, `remove_webapp()` and
  `move_to_menu()` and end with `refresh_caches()`. Window geometry is the one exception to
  "no database of its own": it lives in KWin's `kwinrulesrc`, where `write_window_rule()` and
  `remove_window_rule()` own one group at a time.
- **Paths are module globals** (`HOME`, `APPS_DIR`, `ICON_ROOT`, `SNAP_BIN`), read when the
  functions are called — that is what makes monkeypatching in tests possible. Do not bind them
  as default arguments or at import time. `kwin_rules_file()` is not a global but is derived
  from `HOME` at call time, so it follows along by itself.
- Fetching icons from websites runs in `IconFetcher` (QThread), so the dialog doesn't freeze.
- **Export is the inverse of `apply`.** `export_manifest()` builds the manifest both **Export…**
  and `genvej export` write, so whatever `cli_apply_entry()` learns to read, export must learn
  to write. Icons are embedded as `data:` URIs by `icon_data_uri()` — a path means nothing on
  another machine — and `cli_image()` decodes them. The browser is written without its
  `-snap`/`-flatpak` suffix so it matches any installation type. Browser-installed PWAs
  (`--app-id=`) are skipped and named, since their URL only exists in the browser profile.

## Dependencies

Only `python3` and `PySide6`. Both are already present on Bazzite/Kinoite. On Ubuntu,
PySide6 is split into modules — `python3-pyside6.qtcore`, `.qtgui` and `.qtwidgets` are
needed. No third-party packages, no build step, no virtualenv — a deliberate choice, so
the program can run directly on an immutable system without layering.

## Run and test

```bash
./install.sh && genvej                # normal run
python3 genvej.py                     # run directly from the repo
```

There is no test suite, linter or CI in the repo. Testing is done headless without touching
real files — monkeypatch the paths before anything is called:

```bash
QT_QPA_PLATFORM=offscreen python3 -u - <<'PY'
import os, sys, tempfile; from pathlib import Path
sys.path.insert(0, ".")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])          # must be created before QImage is used
import genvej as g
tmp = Path(tempfile.mkdtemp())
g.HOME = tmp                              # desktop_dir(), profile and snap paths
g.APPS_DIR = tmp/".local/share/applications"; g.APPS_DIR.mkdir(parents=True)
g.ICON_ROOT = tmp/".local/share/icons/hicolor"
g.SNAP_BIN = tmp/"snap-bin"
g.refresh_caches = lambda: None
g.kwin_reconfigure = lambda: None           # otherwise the running KWin is notified
g.flatpak_installed = lambda app_id: False  # otherwise `flatpak info` runs per browser
os.environ["XDG_CURRENT_DESKTOP"] = "KDE"   # otherwise the Window group is disabled
brave = g.Browser("brave", "Brave", ["/snap/bin/brave"], None, "brave")  # wm_prefix is required
# ... test save_webapp / find_web_apps / move_to_menu / remove_webapp here
PY
```

`remove_webapp()` and `move_to_menu()` take a list of `Browser` as their second argument. When
building one by hand, `wm_prefix` must be included — without it `wm_class_name()` returns an
empty string, and no window rule is ever written. The screen under `offscreen` is 800×800, so
that is what `WINDOW_AREAS` and `suggest_geometry()` calculate from in a test.

`detect_browsers()` uses `shutil.which` with the real `PATH`. To test it, set
`os.environ["PATH"]` to a directory of fake executables, and put the snap browsers in the
patched `SNAP_BIN`.

`MainWindow` can be instantiated offscreen, so GUI startup, filtering and button states can
be tested without a display. If `detect_browsers()` finds no browser, the constructor opens a
modal warning and the test hangs — unless browser detection itself is under test, set
`g.detect_browsers = lambda: [brave]` before constructing it (or patch
`QtWidgets.QMessageBox.warning`). Run with `python3 -u`, otherwise output is lost when
`timeout` kills the process.
`QIcon.fromTheme()` finds nothing under `offscreen` — not even an icon that is installed
correctly, and regardless of `setThemeName()`. Icon lookups must be tested with the real
platform (`env -u QT_QPA_PLATFORM`); as long as no `show()`/`exec()` is called, nothing is
displayed.

**Screenshots.** After a visible UI change, regenerate `docs/` with
`env -u QT_QPA_PLATFORM python3 data/screenshot.py` and look at the PNGs before committing.
It uses the real platform for the theme icons, but all data is made up in a temporary
directory, so nothing from the user's own browsers or files ends up in the repo. `grab()` on
a window that is never shown does not recompute the height of word-wrapped labels, which is
why the script turns wrapping off in the details pane. The images follow the desktop's
colour scheme at the time they are rendered.

**How to measure a real window.** Everything about window rules below was found by opening a
window and looking. KWin has no command line for this, so it goes through a script over
D-Bus, and `print()` ends up in the journal:

```bash
cat > /tmp/dump.js <<'JS'
workspace.windowList().forEach(function (w) {
  print("MEASURE|" + w.resourceClass + "|" + w.frameGeometry.x + "," + w.frameGeometry.y
        + " " + w.frameGeometry.width + "x" + w.frameGeometry.height
        + "|fullScreen " + w.fullScreen + "|" + w.caption);
});
JS
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript /tmp/dump.js measure1
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start
sleep 1   # without it the lines aren't in the journal yet, and grep finds nothing
journalctl --user -b --since "-10s" | grep -o "MEASURE|.*"
```

The name passed to `loadScript` must be new every time, otherwise the script doesn't run
again. The same approach closes a test window with `w.closeWindow()`; setting
`w.frameGeometry` from outside, however, does nothing to a Chromium app. A browser that is
already running forwards the command to its own process — to test the startup case, a fresh
instance is needed with `--user-data-dir=` somewhere the browser is allowed to write (for a
snap, inside its own home directory).

## Domain knowledge — the things that actually bite

Every point below was found by failing on it. Don't change them without a reason.

**Flatpak browsers symlink their applications directory.**
`~/.var/app/<id>/data/applications` is, on this system, a symlink to
`~/.local/share/applications`. Scanning both naively counts every web app twice, and
deletion fails on the second pass. `scan_dirs()` therefore deduplicates on `Path.resolve()`,
and `find_web_apps()` likewise compares resolved paths before registering a `twin`. `twins`
is still relevant if another browser has a genuine copy.

**Snap browsers live in their own home directory.**
A strict snap runs with `HOME`, `XDG_CONFIG_HOME` and `XDG_DATA_HOME` moved to
`~/snap/<name>/<revision>` (seen in `/proc/<pid>/environ` for Snap Brave). Brave therefore
has its profile in `~/snap/brave/current/.config/BraveSoftware/Brave-Browser` —
`BRAVE_CONFIG_HOME` points to `common/`, but the profile isn't there. An old
`~/.config/BraveSoftware` may well exist alongside it and is then wrong. A browser found in
`/snap/bin` is registered as a Snap with `snap_config_dir()`, never as a system package. The
Chromium snap's profile in `common/chromium` has not been tested.

**Snap Brave cannot put its PWAs in the menu.**
On "Install as app", Chromium calls `xdg-desktop-menu` and `xdg-icon-resource`, but they
don't exist inside the snap — the journal shows `LaunchProcess: failed to execvp: xdg-desktop-menu`.
Neither a menu file nor icons are created. The only shortcut is the one Chromium writes to the
desktop itself, `~/Desktop/brave-<app-id>-<profile>.desktop` in the real home directory, and
its `Icon=brave-<app-id>-<profile>` points to an icon that was never installed. The icons only
exist in the profile under `<profile>/Web Applications/Manifest Resources/<app-id>/Icons/<size>.png`.
The app's name is not stored in plain text in `Preferences` (only
`web_app_install_metrics.<app-id>`), so without the desktop file the name is unknown. They
don't end up in `~/snap/<name>/current/.local/share/applications` either — the wrapper only
creates `.local/share/mimeapps.list` there. Exec gets the revision-bound path from
`CHROME_WRAPPER` — seen as `/snap/brave/678/…` after the snap had been updated to 680.
`resolve_snap_command()` replaces it with `/snap/bin/<name>`, otherwise the browser runs
without a sandbox with the wrong profile and stops working when the revision is removed.

That is why `scan_dirs()` also scans the desktop — `desktop_dir()` reads `XDG_DESKTOP_DIR` in
`user-dirs.dirs`, since the directory name depends on the language. "Add to menu"
(`move_to_menu()`) moves the file to `APPS_DIR` under the same file name, fixes every `Exec=`
line including the Actions groups with `resolve_snap_exec()` — which only replaces the first
word, so field codes and quoting are preserved — and installs the icon from
`Manifest Resources`, unless it already exists in `ICON_ROOT`.

**The Exec line is not just a string.**
`%` must be written as `%%` in `Exec` according to the desktop entry specification —
important because URLs often contain percent-encoding. When reading, field codes (`%U`,
`%f` …) must be removed, and Brave's own flextop files quote every argument individually
(`flatpak 'run' '--command=brave' …`), so `shlex.split` must be used, not `.split()`.
`exec_tokens()` and `build_exec()` are the only place this is handled.

**Two kinds of web apps, two kinds of behavior.**
`--app-id=<id>` means the browser installed the PWA itself; the URL only exists inside the
browser's profile. `--app=<url>` is a manual shortcut. For the former, the program may only
change `Name` and the icon via `patch_desktop()` — Exec and Actions groups must be left
untouched — and removal is only cosmetic: Brave may restore the file, so the user must also
uninstall on `brave://apps`. The confirmation dialog says so.

**Profile names come from the browser.**
`Local State` → `profile.info_cache` gives the directory name plus the name the user gave the
profile ("Default — Personal"). The fallback is to look for directories containing a
`Preferences` file.

**Icons.**
Written as PNG in `~/.local/share/icons/hicolor/<size>/apps/<name>.png`.
No `index.theme` is needed in the user's hicolor directory — this is tested, both Qt and
KDE find the icons without it. On removal, only icons without `/` in the name and only under
`ICON_ROOT` are deleted, never system icons.

**Fetching icons from websites.**
`fetch_icon()` must respect `<base href>` before resolving relative `href`s — iCloud, for
example, sets the base to `/system/icloud.com/<build>/en-us/` and points to `../favicons/…`.
Many SPAs answer with `index.html` on the manifest path instead of a 404, so JSON parsing
of the manifest must fail silently. The last resort is `/favicon.ico`.

**Cache refresh.**
After any change: `update-desktop-database`, `gtk-update-icon-cache` and `kbuildsycoca6`.
Without the last one, the menu entry doesn't show up in KDE.
Verify with `strings -el ~/.cache/ksycoca6* | grep -i <name>` — note `-el`: ksycoca stores
strings as UTF-16, so plain `strings` finds nothing and gives a false negative.

**Wayland and window grouping.**
The program sets its own app id with `QApplication.setDesktopFileName("genvej")` before
`QApplication` is created. For the shortcuts it *generates*, `--class=<icon name>` is still
set, but it has been measured that the flag does **not** reach the app window: an `--app=`
window gets the app id `<browser>-<host>_<path>-<profile>`, regardless of `--class`, and
regardless of whether the shortcut starts the browser itself or the command is forwarded to a
running process. `--class` only sets the app id on a regular browser window from the same
process. That is why `save_webapp()` writes the real app id to `StartupWMClass` — otherwise
the taskbar cannot associate the window with the `.desktop` file, and the window shows the
browser's icon. `wm_class_name()` builds the string, and `chromium_app_name()` mimics
Chromium's `GenerateApplicationNameFromURL`: host + `_` + path, anything outside
`[A-Za-z0-9_.-]` as `_`, without scheme, port, query and fragment. Verified against three
real windows, e.g. `https://outlook.office.com/mail/` → `brave-outlook.office.com__mail_-Default`.
The profile is cleaned the same way — `Profile 1` was measured as
`brave-word.cloud.microsoft__-Profile_1`; with the space, the window lands under Brave.
Files written before either fix are corrected on load by `repair_window_classes()`
(`MainWindow.reload()` and `genvej apply`), which also moves a window rule stored under the
old app id. It only touches `X-Genvej=true` files with `--app=`.
A browser-installed PWA already has the correct `StartupWMClass` in the browser's own file —
`window_class()` prefers it over guessing.

**Window size and placement can only be controlled by KWin.**
Everything below was measured on Wayland with Snap Brave and KWin 6.6.

- `--window-size=W,H` only works when the shortcut actually starts the browser process. If
  the browser is already running, the command line is forwarded to it and the flag is
  ignored — that is the normal case, so the flag is useless here.
- `--window-position` is always ignored. A Wayland client may not position itself.
- A KWin window rule, on the other hand, also works on a window the running browser creates.

`kwinrulesrc` is shared with KDE's own rules editor, so the file is read and written with
`configparser` (`optionxform = str`, KConfig keys are case-sensitive), and `[General]`
`rules`/`count` are updated without touching other rules. The group name is a `uuid5` of the
app id, so the same web app always hits its own group. Four things cost time:

- The method is called `org.kde.KWin.reconfigure`. `reloadConfig` does not exist on KWin 6.
- A rule **only** takes effect on windows opened afterwards. Not even `Force` moves a window
  that is already open, so a test has to close the window and open it again.
- Rule type `1` ("apply initially") does nothing to a Chromium app — the browser sets its
  own geometry. Only `2` (remember) and `3` (force) win. Genvej uses 2 by default and 3 when
  the user ticks "Lock"; with 2, KWin itself writes the user's changes back to the file, and
  the dialog shows them next time.
- `types=1` (normal windows only) has been tested and does not prevent matching.

The window can also open maximized or full screen — `WINDOW_STATES` and `STATE_KEYS`.
Both have been tested with the same rule type: `fullscreen=true`, and `maximizehoriz=true`
plus `maximizevert=true` (both are needed, otherwise only one direction is maximized). A
maximized window reports `maximizable false` on KWin's side, but the rule works anyway —
measured as `0,0 1920x1154` on a 1920×1200 screen with a 46 px panel, and `fullScreen false`,
so it is real maximization and not full screen. The two states are mutually exclusive, and
switching clears the other one's keys from the group. Both use the screen the window lands
on, so `position` is written alongside to choose the screen — measured for full screen on
screen 2, assumed to apply to maximization the same way (not tested with two screens).
`size` is not written together with either of them; the field is disabled in the dialog. The
quick picks in `WINDOW_AREAS` are fractions of `availableGeometry()` for the chosen screen,
and the rule's `size` is the *frame's* size, so quarters tile exactly (measured: 1920×1080 at
1920,1080 on a 3840×2160 screen).

`EditorDialog.window_hint` has a fixed height. The text changes when fields are toggled, and
a wrapped label that grows from one to two lines moves the whole dialog around — including
the icon further up.

**Dimmed text must survive dark themes.** Hint labels go through `mute_label()`, which uses
the palette's placeholder colour. Do not use `palette(mid)` in a stylesheet: in Breeze Dark it
is `#1c1f21` on a `#1c1f22` background, so the text is invisible.

## Conventions

User interface, comments, docstrings and documentation are in English. Code identifiers are
in English. No abbreviated variable names. Exceptions are caught specifically (`OSError`,
`ValueError`, `urllib.error.URLError`) — the program must never crash on a website that
doesn't respond. The code is licensed GPL-3.0-or-later; new source files get an
`SPDX-License-Identifier` line.

## Not done yet

- Firefox support (requires a completely different mechanism than `--app=`)
- Editing categories and Actions/context menus on a web app
- Importing a URL directly from a running browser tab
- Translation (all strings are hardcoded in English)

## Investigated and rejected

**Close-to-tray is not possible for a Chromium PWA.**
An `--app=`/`--app-id=` shortcut is a regular browser window without tray support, and the
close button is handled inside the browser. There is no flag and no setting that does
"close → minimize to tray". It doesn't work from outside either on Wayland: the close event
goes directly to the client, KWin cannot intercept it, and there is no protocol for moving a
foreign window into the system tray — KWin window rules have no close action. On X11,
`kdocker`/`alltray` could do it (they intercept `WM_DELETE_WINDOW`), but they don't work on
Wayland-native windows, and Chromium typically forwards the command to an already running
process, so a wrapper would dock the wrong window. Unverified.

The only real solution is a program that owns the window itself — Electron, Tauri or
QtWebEngine. A QtWebEngine mode in Genvej would cost both the dependency principle
(QtWebEngine isn't on Kinoite by default) and the browser profile: logins, extensions,
passwords, sync. It is not worth the price.

Partially available today: `brave://settings/system` → "Continue running background apps
when Brave is closed" keeps service workers and notifications alive after the window is
closed, but gives neither a window nor an icon per app.
