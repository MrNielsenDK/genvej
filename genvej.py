#!/usr/bin/env python3
"""Genvej — opret, rediger og fjern web-apps (PWA'er) på skrivebordet.

Finder både de PWA'er browseren selv har installeret og dem der er lavet
manuelt med --app=, og kan fjerne begge dele igen.
"""

from __future__ import annotations

import configparser
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

HOME = Path.home()
APPS_DIR = HOME / ".local/share/applications"
ICON_ROOT = HOME / ".local/share/icons/hicolor"
ICON_SIZES = (32, 48, 64, 128, 256)
MARKER = "X-Genvej"
FIELD_CODES = {"%U", "%u", "%F", "%f", "%i", "%c", "%k", "%d", "%D", "%n", "%N", "%v", "%m"}
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------
# .desktop-håndtering
# --------------------------------------------------------------------------

def parse_desktop(path: Path) -> dict | None:
    """Læs [Desktop Entry]-gruppen. Actions-grupper ignoreres."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    data, group = {}, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            continue
        if group != "Desktop Entry" or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data.setdefault(key.strip(), value.strip())
    return data or None


def exec_tokens(exec_line: str) -> list[str]:
    """Split en Exec-linje til argv, uden field codes og med %% pakket ud."""
    line = exec_line.replace("%%", "\x00")
    try:
        tokens = shlex.split(line)
    except ValueError:
        tokens = line.split()
    return [t.replace("\x00", "%") for t in tokens if t not in FIELD_CODES]


def build_exec(tokens: list[str]) -> str:
    """Byg en Exec-linje. % skal escapes som %% jf. specifikationen."""
    return " ".join(shlex.quote(t) for t in tokens).replace("%", "%%")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "webapp"


# --------------------------------------------------------------------------
# Browsere og profiler
# --------------------------------------------------------------------------

@dataclass
class Browser:
    ident: str
    label: str
    argv: list[str]
    config_dir: Path | None
    wm_prefix: str = ""

    def profiles(self) -> list[tuple[str, str]]:
        """[(mappenavn, visningsnavn)] læst af browserens Local State."""
        if not self.config_dir or not self.config_dir.is_dir():
            return [("Default", "Default")]
        found: list[tuple[str, str]] = []
        state = self.config_dir / "Local State"
        if state.is_file():
            try:
                cache = json.loads(state.read_text(encoding="utf-8", errors="replace"))
                cache = cache.get("profile", {}).get("info_cache", {})
                for dirname, info in cache.items():
                    pretty = (info or {}).get("name") or dirname
                    label = dirname if pretty == dirname else f"{dirname} — {pretty}"
                    found.append((dirname, label))
            except (OSError, ValueError):
                pass
        if not found:
            for child in sorted(self.config_dir.iterdir()):
                if (child / "Preferences").is_file():
                    found.append((child.name, child.name))
        return found or [("Default", "Default")]


# (ident, label, binærnavn, flatpak-id, flatpak-kommando, konfigsti under $HOME,
#  flatpak-konfigsti, præfiks i vinduets app-id)
BROWSER_TABLE = [
    ("brave", "Brave", "brave-browser", "com.brave.Browser", "brave",
     ".config/BraveSoftware/Brave-Browser",
     ".var/app/com.brave.Browser/config/BraveSoftware/Brave-Browser", "brave"),
    ("chrome", "Google Chrome", "google-chrome-stable", "com.google.Chrome", "google-chrome",
     ".config/google-chrome", ".var/app/com.google.Chrome/config/google-chrome", "chrome"),
    ("chromium", "Chromium", "chromium-browser", "org.chromium.Chromium", "chromium",
     ".config/chromium", ".var/app/org.chromium.Chromium/config/chromium", "chromium"),
    ("edge", "Microsoft Edge", "microsoft-edge", "com.microsoft.Edge", "microsoft-edge",
     ".config/microsoft-edge", ".var/app/com.microsoft.Edge/config/microsoft-edge", "msedge"),
    ("vivaldi", "Vivaldi", "vivaldi-stable", "com.vivaldi.Vivaldi", "vivaldi",
     ".config/vivaldi", ".var/app/com.vivaldi.Vivaldi/config/vivaldi", "vivaldi"),
]
ALT_BINARIES = {"brave": ["brave-browser", "brave"],
                "chromium": ["chromium", "chromium-browser"],
                "chrome": ["google-chrome-stable", "google-chrome"]}
SNAP_BIN = Path("/snap/bin")


def flatpak_installed(app_id: str) -> bool:
    try:
        return subprocess.run(["flatpak", "info", app_id],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def snap_config_dir(snap_name: str, native_cfg: str) -> Path:
    """Profilmappen for en browser installeret som snap.

    En snap ser ~/snap/<navn>/<revision> som $HOME, så Brave har profilen under
    current/.config. Chromium-snappen skulle bruge common/ via CHROME_CONFIG_HOME
    (ikke afprøvet). Den første der findes vinder.
    """
    user_dir = HOME / "snap" / snap_name
    candidates = [user_dir / "current" / native_cfg,
                  user_dir / "common" / Path(native_cfg).relative_to(".config")]
    return next((path for path in candidates if path.is_dir()), candidates[0])


def detect_browsers() -> list[Browser]:
    found: list[Browser] = []
    for ident, label, binary, app_id, command, native_cfg, flat_cfg, wm in BROWSER_TABLE:
        native = snap = ""
        for candidate in ALT_BINARIES.get(ident, [binary]):
            path = shutil.which(candidate)
            if not path:
                continue
            if Path(path).parent == SNAP_BIN:
                snap = snap or path
            else:
                native = native or path
        if native:
            found.append(Browser(ident, label, [native], HOME / native_cfg, wm))
        if snap:
            found.append(Browser(f"{ident}-snap", f"{label} (Snap)", [snap],
                                 snap_config_dir(Path(snap).name, native_cfg), wm))
        if flatpak_installed(app_id):
            found.append(Browser(f"{ident}-flatpak", f"{label} (Flatpak)",
                                 ["flatpak", "run", f"--command={command}", app_id],
                                 HOME / flat_cfg, wm))
    return found


# --------------------------------------------------------------------------
# Fundne web-apps
# --------------------------------------------------------------------------

@dataclass
class WebApp:
    path: Path
    name: str
    icon: str
    url: str
    app_id: str
    profile: str
    argv_prefix: list[str]
    managed: bool
    twins: list[Path] = field(default_factory=list)
    exec_line: str = ""
    wm_class: str = ""

    @property
    def browser_installed(self) -> bool:
        return bool(self.app_id)

    @property
    def kind(self) -> str:
        if self.browser_installed:
            return "Installeret af browseren"
        return "Oprettet med Genvej" if self.managed else "Oprettet manuelt"

    @property
    def on_desktop(self) -> bool:
        return self.path.parent.resolve() == desktop_dir().resolve()

    def find_browser(self, browsers: list[Browser]) -> Browser | None:
        return next((browser for browser in browsers if browser.argv == self.argv_prefix), None)

    def browser_label(self, browsers: list[Browser]) -> str:
        browser = self.find_browser(browsers)
        if browser:
            return browser.label
        return Path(self.argv_prefix[-1]).name if self.argv_prefix else "ukendt"


def resolve_snap_command(tokens: list[str]) -> list[str]:
    """Erstat en snaps interne sti med dens launcher i /snap/bin.

    Snap-Brave sætter CHROME_WRAPPER til /snap/brave/<revision>/opt/…, som Chromium
    bruger i Exec på de PWA'er den installerer. Startet udefra kører den uden snappens
    sandkasse og med den forkerte profil, og den holder op med at virke når revisionen
    fjernes.
    """
    if tokens:
        parts = Path(tokens[0]).parts
        if len(parts) > 3 and parts[:2] == ("/", "snap") and parts[2] != "bin":
            launcher = SNAP_BIN / parts[2]
            if launcher.exists():
                return [str(launcher), *tokens[1:]]
    return tokens


def resolve_snap_exec(exec_value: str) -> str:
    """Som resolve_snap_command, men på en rå Exec-værdi.

    Kun første ord skiftes ud, så field codes som %U og citeringen bevares.
    """
    head, separator, rest = exec_value.partition(" ")
    launcher = resolve_snap_command([head])[0]
    return exec_value if launcher == head else f"{build_exec([launcher])}{separator}{rest}"


def desktop_dir() -> Path:
    """Skrivebordet fra user-dirs.dirs — mappenavnet afhænger af sproget."""
    try:
        text = (HOME / ".config/user-dirs.dirs").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    match = re.search(r'^XDG_DESKTOP_DIR="?([^"\n]+)"?', text, re.MULTILINE)
    return Path(match.group(1).replace("$HOME", str(HOME))) if match else HOME / "Desktop"


def scan_dirs() -> list[Path]:
    """Mapper der kan indeholde web-apps, uden dubletter.

    Flatpak-browsere symlinker typisk deres data/applications til
    ~/.local/share/applications, så der skal sammenlignes på resolved sti.
    Skrivebordet er med, fordi Snap-Brave kun kan lægge sine PWA'er dér.
    """
    candidates = [APPS_DIR, *sorted((HOME / ".var/app").glob("*/data/applications")),
                  desktop_dir()]
    dirs, seen = [], set()
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        key = candidate.resolve()
        if key in seen:
            continue
        seen.add(key)
        dirs.append(candidate)
    return dirs


def find_web_apps() -> list[WebApp]:
    by_basename: dict[str, WebApp] = {}
    for directory in scan_dirs():
        for path in sorted(directory.glob("*.desktop")):
            entry = parse_desktop(path)
            if not entry or "Exec" not in entry:
                continue
            tokens = resolve_snap_command(exec_tokens(entry["Exec"]))
            url = app_id = profile = ""
            split_at = len(tokens)
            for index, token in enumerate(tokens):
                if token.startswith("--app="):
                    url = token[6:]
                elif token.startswith("--app-id="):
                    app_id = token[9:]
                elif token.startswith("--profile-directory="):
                    profile = token[20:]
                if token.startswith(("--app=", "--app-id=", "--profile-directory=", "--class=")):
                    split_at = min(split_at, index)
            if not url and not app_id:
                continue
            if path.name in by_basename:
                known = by_basename[path.name]
                if path.resolve() != known.path.resolve():
                    known.twins.append(path)
                continue
            by_basename[path.name] = WebApp(
                path=path,
                name=entry.get("Name", path.stem),
                icon=entry.get("Icon", ""),
                url=url,
                app_id=app_id,
                profile=profile or "Default",
                argv_prefix=tokens[:split_at],
                managed=entry.get(MARKER, "").lower() == "true",
                exec_line=entry["Exec"],
                wm_class=entry.get("StartupWMClass", ""),
            )
    return sorted(by_basename.values(), key=lambda a: a.name.lower())


# --------------------------------------------------------------------------
# Ikoner
# --------------------------------------------------------------------------

class LinkScraper(HTMLParser):
    """Opsamler <base href> og alle <link rel=...icon...>/manifest."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.base = ""
        self.icons: list[tuple[int, str]] = []
        self.manifest = ""

    def handle_starttag(self, tag, attrs):
        attrib = {k.lower(): (v or "") for k, v in attrs}
        if tag == "base" and attrib.get("href") and not self.base:
            self.base = attrib["href"]
        elif tag == "link":
            rel = attrib.get("rel", "").lower()
            href = attrib.get("href", "")
            if not href:
                return
            if "manifest" in rel and not self.manifest:
                self.manifest = href
            elif "icon" in rel:
                size = 0
                match = re.search(r"(\d+)x(\d+)", attrib.get("sizes", ""))
                if match:
                    size = int(match.group(1))
                elif "apple-touch" in rel:
                    size = 180
                self.icons.append((size, href))


def http_get(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(8 * 1024 * 1024)


def fetch_icon(page_url: str) -> QtGui.QImage:
    """Hent det største tilgængelige ikon for et websted."""
    candidates: list[tuple[int, str]] = []
    base = page_url
    try:
        html = http_get(page_url).decode("utf-8", errors="replace")
        scraper = LinkScraper()
        scraper.feed(html)
        if scraper.base:
            base = urllib.parse.urljoin(page_url, scraper.base)
        candidates = [(size, urllib.parse.urljoin(base, href)) for size, href in scraper.icons]
        if scraper.manifest:
            manifest_url = urllib.parse.urljoin(base, scraper.manifest)
            try:
                manifest = json.loads(http_get(manifest_url).decode("utf-8", errors="replace"))
                for icon in manifest.get("icons", []):
                    src = icon.get("src")
                    if not src:
                        continue
                    match = re.search(r"(\d+)x(\d+)", icon.get("sizes", ""))
                    candidates.append((int(match.group(1)) if match else 0,
                                       urllib.parse.urljoin(manifest_url, src)))
            except (OSError, ValueError, urllib.error.URLError):
                pass  # mange SPA'er svarer med index.html på manifest-stien
    except (OSError, ValueError, urllib.error.URLError):
        pass

    parts = urllib.parse.urlsplit(page_url)
    candidates.append((0, urllib.parse.urlunsplit((parts.scheme, parts.netloc, "/favicon.ico", "", ""))))

    for _, url in sorted(candidates, key=lambda c: -c[0]):
        try:
            image = QtGui.QImage.fromData(http_get(url, timeout=15))
        except (OSError, ValueError, urllib.error.URLError):
            continue
        if not image.isNull() and image.width() >= 16:
            return image
    return QtGui.QImage()


def install_icon(image: QtGui.QImage, icon_name: str) -> None:
    """Skriv ikonet i alle relevante størrelser i brugerens hicolor-tema."""
    source = image.convertToFormat(QtGui.QImage.Format_RGBA8888)
    for size in ICON_SIZES:
        if size > 256 or (size > source.width() and size > 256):
            continue
        target_dir = ICON_ROOT / f"{size}x{size}" / "apps"
        target_dir.mkdir(parents=True, exist_ok=True)
        scaled = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.save(str(target_dir / f"{icon_name}.png"), "PNG")


def remove_icons(icon_name: str) -> int:
    """Fjern kun ikoner der ligger i brugerens eget hicolor-tema."""
    if not icon_name or "/" in icon_name:
        return 0
    removed = 0
    for path in ICON_ROOT.glob(f"*/apps/{icon_name}.png"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def load_icon(icon_name: str) -> QtGui.QIcon:
    if not icon_name:
        return QtGui.QIcon.fromTheme("applications-internet")
    if icon_name.startswith("/"):
        return QtGui.QIcon(icon_name)
    icon = QtGui.QIcon.fromTheme(icon_name)
    return icon if not icon.isNull() else QtGui.QIcon.fromTheme("applications-internet")


def browser_pwa_icon(browser: Browser, profile: str, app_id: str) -> QtGui.QImage:
    """Det største ikon browseren selv har gemt for en PWA i profilen."""
    if not browser.config_dir:
        return QtGui.QImage()
    icons = browser.config_dir / profile / "Web Applications/Manifest Resources" / app_id / "Icons"
    by_size = sorted((int(path.stem), path) for path in icons.glob("*.png") if path.stem.isdigit())
    for _, path in reversed(by_size):
        image = QtGui.QImage(str(path))
        if not image.isNull():
            return image
    return QtGui.QImage()


def refresh_caches() -> None:
    for command in (["update-desktop-database", str(APPS_DIR)],
                    ["gtk-update-icon-cache", "-f", "-t", str(ICON_ROOT)],
                    ["kbuildsycoca6", "--noincremental"]):
        if not shutil.which(command[0]):
            continue
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


# --------------------------------------------------------------------------
# Vinduesregler (KWin)
# --------------------------------------------------------------------------

# KWin skriver hver egenskab som en værdi plus en regeltype. "Husk" sætter
# geometrien når vinduet åbnes og lader brugeren ændre den bagefter, "Fastlås"
# holder den fast. "Anvend ved åbning" (1) er afprøvet og gør intet ved en
# Chromium-app — browseren sætter selv sin geometri, og kun 2 og 3 vinder over den.
REMEMBER = 2
FORCE = 3
EXACT_MATCH = 1  # wmclassmatch: nøjagtigt match, ikke understreng eller regulært udtryk
NORMAL_WINDOW = 1  # types-masken, så reglen ikke rammer pop-op-vinduer og dialoger

# Hvordan vinduet åbner. Maksimeret og fuldskærm sætter selv størrelsen, så kun
# placeringen skrives ved siden af — den bestemmer hvilken skærm vinduet lander på.
WINDOW_STATES = [("Normal", ""), ("Maksimeret", "maximized"), ("Fuldskærm", "fullscreen")]
STATE_KEYS = {"fullscreen": ("fullscreen",), "maximized": ("maximizehoriz", "maximizevert")}

# Hurtigvalg i dialogen: (etiket, (venstre, top, bredde, højde) som andele af
# skærmens brugbare område, altså uden proceslinje og paneler).
WINDOW_AREAS = [
    ("Hele skærmen", (0, 0, 1, 1)),
    ("Venstre halvdel", (0, 0, 1 / 2, 1)),
    ("Højre halvdel", (1 / 2, 0, 1 / 2, 1)),
    ("Øverste halvdel", (0, 0, 1, 1 / 2)),
    ("Nederste halvdel", (0, 1 / 2, 1, 1 / 2)),
    ("Øverste venstre fjerdedel", (0, 0, 1 / 2, 1 / 2)),
    ("Øverste højre fjerdedel", (1 / 2, 0, 1 / 2, 1 / 2)),
    ("Nederste venstre fjerdedel", (0, 1 / 2, 1 / 2, 1 / 2)),
    ("Nederste højre fjerdedel", (1 / 2, 1 / 2, 1 / 2, 1 / 2)),
    ("Midten, to tredjedele", (1 / 6, 1 / 6, 2 / 3, 2 / 3)),
]


def kwin_rules_file() -> Path:
    return HOME / ".config/kwinrulesrc"


def kwin_available() -> bool:
    """Vinduesregler findes kun i KDE's vindueshåndtering."""
    return "kde" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()


def chromium_app_name(url: str, app_id: str) -> str:
    """Det appnavn Chromium danner ud fra en web-app.

    For en browserinstalleret PWA er det app-id'et, for --app= er det vært plus
    sti — skema, portnummer, query og fragment indgår ikke.
    """
    if app_id:
        return app_id
    parts = urllib.parse.urlsplit(url)
    return f"{parts.hostname or ''}_{parts.path or '/'}"


def wm_class_name(browser: Browser | None, url: str, app_id: str, profile: str) -> str:
    """Vinduets app-id: <præfiks>-<appnavn>-<profil>, alt uden for [A-Za-z0-9_.-] som _.

    Målt på Brave: --app=https://outlook.office.com/mail/ giver app-id'et
    brave-outlook.office.com__mail_-Default. --class= slår ikke igennem på selve
    app-vinduet, så det er den her streng en vinduesregel skal matche.
    """
    if not browser or not browser.wm_prefix:
        return ""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", chromium_app_name(url, app_id))
    return f"{browser.wm_prefix}-{name}-{profile}"


def window_class(app: WebApp, browsers: list[Browser]) -> str:
    """App-id'et for en fundet web-apps vindue.

    Browserens egne genveje har det allerede i StartupWMClass. For resten udledes
    det, for Genvejs ældre filer skrev ikonnavnet der, og det matcher intet vindue.
    """
    if app.browser_installed and app.wm_class:
        return app.wm_class
    return wm_class_name(app.find_browser(browsers), app.url, app.app_id, app.profile)


def rule_group(wm_class: str) -> str:
    """Fast gruppenavn pr. app-id — KWin navngiver selv sine regelgrupper med UUID'er."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"genvej:{wm_class}"))


def load_kwin_rules() -> configparser.RawConfigParser:
    """Læs kwinrulesrc. Filen deles med KDE's egen regeleditor og andres regler."""
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str  # KConfig-nøgler er versalfølsomme
    path = kwin_rules_file()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return parser
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise ValueError(f"{path} kunne ikke læses: {error}") from error
    return parser


def save_kwin_rules(parser: configparser.RawConfigParser) -> None:
    path = kwin_rules_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    parser.write(buffer, space_around_delimiters=False)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def list_rule(parser: configparser.RawConfigParser, group: str, listed: bool) -> None:
    """Hold [General] rules/count i sync uden at røre de regler andre har lavet."""
    if not parser.has_section("General"):
        parser.add_section("General")
    names = [name for name in parser["General"].get("rules", "").split(",") if name]
    if listed and group not in names:
        names.append(group)
    if not listed and group in names:
        names.remove(group)
    parser["General"]["rules"] = ",".join(names)
    parser["General"]["count"] = str(len(names))


def read_window_rule(wm_class: str) -> dict:
    """Reglens "size" og "position" som talpar, plus "state" og "lock"."""
    if not wm_class:
        return {}
    try:
        parser = load_kwin_rules()
    except (OSError, ValueError):
        return {}
    group = rule_group(wm_class)
    if not parser.has_section(group):
        return {}
    found = {}
    for key in ("size", "position"):
        pair = parser[group].get(key, "").split(",")
        if len(pair) == 2 and all(part.strip().lstrip("-").isdigit() for part in pair):
            found[key] = (int(pair[0]), int(pair[1]))
    for state, keys in STATE_KEYS.items():
        if all(parser[group].get(key) == "true" for key in keys):
            found["state"] = state
            break
    if found:
        found["lock"] = any(parser[group].get(f"{key}rule") == str(FORCE)
                            for key in ("size", "position", "fullscreen", "maximizehoriz"))
    return found


def write_window_rule(wm_class: str, name: str,
                      size: tuple[int, int] | None,
                      position: tuple[int, int] | None,
                      lock: bool = False, state: str = "") -> None:
    """Skriv — eller fjern, hvis intet er sat — reglen for ét app-id."""
    if not wm_class:
        return
    parser = load_kwin_rules()
    group = rule_group(wm_class)
    if not size and not position and not state:
        if not parser.has_section(group):
            return
        parser.remove_section(group)
        list_rule(parser, group, False)
    else:
        if not parser.has_section(group):
            parser.add_section(group)
        parser[group]["Description"] = f"Genvej: {name}"
        parser[group]["wmclass"] = wm_class
        parser[group]["wmclasscomplete"] = "false"
        parser[group]["wmclassmatch"] = str(EXACT_MATCH)
        parser[group]["types"] = str(NORMAL_WINDOW)
        mode = str(FORCE if lock else REMEMBER)
        for key, value in (("size", size), ("position", position)):
            if value:
                parser[group][key] = f"{value[0]},{value[1]}"
                parser[group][f"{key}rule"] = mode
            else:
                parser.remove_option(group, key)
                parser.remove_option(group, f"{key}rule")
        for key in (key for keys in STATE_KEYS.values() for key in keys):
            parser.remove_option(group, key)
            parser.remove_option(group, f"{key}rule")
        for key in STATE_KEYS.get(state, ()):
            parser[group][key] = "true"
            parser[group][f"{key}rule"] = mode
        list_rule(parser, group, True)
    save_kwin_rules(parser)
    kwin_reconfigure()


def remove_window_rule(wm_class: str) -> None:
    write_window_rule(wm_class, "", None, None)


def kwin_reconfigure() -> None:
    """Bed KWin læse kwinrulesrc igen.

    Metoden hedder reconfigure — reloadConfig findes ikke på KWin 6. Reglen slår
    kun igennem på vinduer der åbnes bagefter; et vindue der allerede står der
    bliver hvor det er. Uden qdbus eller dbus-send virker reglen først næste gang
    der logges ind.
    """
    for tool in ("qdbus6", "qdbus-qt6", "qdbus"):
        if shutil.which(tool):
            command = [tool, "org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure"]
            break
    else:
        if not shutil.which("dbus-send"):
            return
        command = ["dbus-send", "--session", "--type=method_call", "--dest=org.kde.KWin",
                   "/KWin", "org.kde.KWin.reconfigure"]
    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=15)
    except (OSError, subprocess.SubprocessError):
        pass


# --------------------------------------------------------------------------
# Redigeringsdialog
# --------------------------------------------------------------------------

class IconFetcher(QtCore.QThread):
    done = Signal(QtGui.QImage)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        self.done.emit(fetch_icon(self.url))


class EditorDialog(QtWidgets.QDialog):
    def __init__(self, browsers: list[Browser], app: WebApp | None = None, parent=None):
        super().__init__(parent)
        self.browsers = browsers
        self.app = app
        self.image: QtGui.QImage | None = None
        self.fetcher: IconFetcher | None = None
        self.existing_class = ""  # app-id'et før redigeringen, så en gammel regel kan ryddes
        self.setWindowTitle("Rediger web-app" if app else "Ny web-app")
        self.setMinimumWidth(520)

        self.name_edit = QtWidgets.QLineEdit()
        self.url_edit = QtWidgets.QLineEdit()
        self.url_edit.setPlaceholderText("https://eksempel.dk/sti")
        self.browser_box = QtWidgets.QComboBox()
        self.profile_box = QtWidgets.QComboBox()
        for browser in browsers:
            self.browser_box.addItem(browser.label, browser)
        self.browser_box.currentIndexChanged.connect(self.reload_profiles)

        self.icon_label = QtWidgets.QLabel()
        self.icon_label.setFixedSize(72, 72)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.fetch_button = QtWidgets.QPushButton("Hent fra webstedet")
        self.file_button = QtWidgets.QPushButton("Vælg fil…")
        self.fetch_button.clicked.connect(self.fetch)
        self.file_button.clicked.connect(self.choose_file)

        icon_row = QtWidgets.QHBoxLayout()
        icon_row.addWidget(self.icon_label)
        icon_buttons = QtWidgets.QVBoxLayout()
        icon_buttons.addWidget(self.fetch_button)
        icon_buttons.addWidget(self.file_button)
        icon_buttons.addStretch()
        icon_row.addLayout(icon_buttons)
        icon_row.addStretch()

        form = QtWidgets.QFormLayout()
        form.addRow("Navn:", self.name_edit)
        form.addRow("Adresse:", self.url_edit)
        form.addRow("Browser:", self.browser_box)
        form.addRow("Profil:", self.profile_box)
        form.addRow("Ikon:", icon_row)

        self.window_group = self.build_window_group()

        self.hint = QtWidgets.QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: palette(mid);")

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Save).setText("Gem")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("Annullér")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.window_group)
        layout.addWidget(self.hint)
        layout.addWidget(buttons)

        self.reload_profiles()
        if app:
            self.load_existing(app)
        else:
            self.update_preview(QtGui.QIcon.fromTheme("applications-internet").pixmap(64, 64))

    def build_window_group(self) -> QtWidgets.QGroupBox:
        """Størrelse og placering af appens vindue, håndhævet af en KWin-regel.

        Browseren kan ikke selv: --window-size gælder kun når genvejen rent faktisk
        starter browseren, og --window-position ignoreres på Wayland.
        """
        group = QtWidgets.QGroupBox("Vindue")
        self.screen_box = QtWidgets.QComboBox()
        primary = QtGui.QGuiApplication.primaryScreen()
        for number, screen in enumerate(QtGui.QGuiApplication.screens(), start=1):
            area = screen.availableGeometry()
            label = f"Skærm {number} — {area.width()}×{area.height()}"
            self.screen_box.addItem(label + (" (primær)" if screen is primary else ""), area)
        self.area_box = QtWidgets.QComboBox()
        self.area_box.addItem("Vælg område…", None)
        for label, fractions in WINDOW_AREAS:
            self.area_box.addItem(label, fractions)
        self.area_box.activated.connect(self.area_chosen)

        self.size_check = QtWidgets.QCheckBox("Fast størrelse")
        self.position_check = QtWidgets.QCheckBox("Fast placering")
        self.state_box = QtWidgets.QComboBox()
        for label, state in WINDOW_STATES:
            self.state_box.addItem(label, state)
        self.state_box.currentIndexChanged.connect(self.window_fields_toggled)
        self.lock_check = QtWidgets.QCheckBox("Fastlås — vinduet kan ikke ændres bagefter")
        self.width_spin = QtWidgets.QSpinBox()
        self.height_spin = QtWidgets.QSpinBox()
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(200, 20000)
            spin.setSingleStep(10)
            spin.setSuffix(" px")
        self.x_spin = QtWidgets.QSpinBox()
        self.y_spin = QtWidgets.QSpinBox()
        for spin in (self.x_spin, self.y_spin):
            spin.setRange(-20000, 20000)
            spin.setSingleStep(10)
            spin.setSuffix(" px")

        picker = QtWidgets.QHBoxLayout()
        picker.addWidget(QtWidgets.QLabel("Skærm:"))
        picker.addWidget(self.screen_box, 1)
        picker.addWidget(QtWidgets.QLabel("Placer i:"))
        picker.addWidget(self.area_box, 1)

        grid = QtWidgets.QGridLayout(group)
        grid.addLayout(picker, 0, 0, 1, 5)
        grid.addWidget(self.size_check, 1, 0)
        grid.addWidget(QtWidgets.QLabel("Bredde:"), 1, 1)
        grid.addWidget(self.width_spin, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Højde:"), 1, 3)
        grid.addWidget(self.height_spin, 1, 4)
        grid.addWidget(self.position_check, 2, 0)
        grid.addWidget(QtWidgets.QLabel("X:"), 2, 1)
        grid.addWidget(self.x_spin, 2, 2)
        grid.addWidget(QtWidgets.QLabel("Y:"), 2, 3)
        grid.addWidget(self.y_spin, 2, 4)
        state_row = QtWidgets.QHBoxLayout()
        state_row.addWidget(QtWidgets.QLabel("Åbn som:"))
        state_row.addWidget(self.state_box)
        state_row.addStretch()
        grid.addLayout(state_row, 3, 0, 1, 5)
        grid.addWidget(self.lock_check, 4, 0, 1, 5)
        grid.setColumnStretch(5, 1)

        # Fast højde: teksten skifter når felterne slås til og fra, og en label der
        # vokser fra én til to linjer flytter rundt på alt andet i dialogen.
        self.window_hint = QtWidgets.QLabel()
        self.window_hint.setWordWrap(True)
        self.window_hint.setAlignment(Qt.AlignTop)
        self.window_hint.setFixedHeight(2 * self.window_hint.fontMetrics().lineSpacing())
        self.window_hint.setStyleSheet("color: palette(mid);")
        grid.addWidget(self.window_hint, 5, 0, 1, 6)

        for check in (self.size_check, self.position_check, self.lock_check):
            check.toggled.connect(self.window_fields_toggled)
        self.suggest_geometry()
        self.window_fields_toggled()
        if not kwin_available():
            group.setEnabled(False)
            self.window_hint.setText("Kræver KDE's vindueshåndtering (KWin). "
                                     "Andre skriveborde har ingen tilsvarende regler.")
        return group

    def screen_area(self) -> QtCore.QRect:
        """Det brugbare område på den valgte skærm — uden paneler og proceslinje."""
        return self.screen_box.currentData() or QtCore.QRect(0, 0, 1920, 1080)

    def suggest_geometry(self):
        """Udgangspunktet: to tredjedele af skærmen, centreret."""
        self.set_area(*WINDOW_AREAS[-1][1])

    def set_area(self, left: float, top: float, width: float, height: float):
        """Udfyld felterne med en andel af den valgte skærm."""
        area = self.screen_area()
        self.width_spin.setValue(max(200, round(area.width() * width)))
        self.height_spin.setValue(max(200, round(area.height() * height)))
        self.x_spin.setValue(area.x() + round(area.width() * left))
        self.y_spin.setValue(area.y() + round(area.height() * top))

    def area_chosen(self, index: int):
        """Hurtigvalget fylder felterne ud og slår dem til. Selv står det på "Vælg område…"."""
        fractions = self.area_box.itemData(index)
        self.area_box.setCurrentIndex(0)
        if not fractions:
            return
        self.set_area(*fractions)
        self.position_check.setChecked(True)
        if not self.state_box.currentData():
            self.size_check.setChecked(True)

    def window_fields_toggled(self, *_):
        state = self.state_box.currentData()
        self.size_check.setEnabled(not state)
        for spin in (self.width_spin, self.height_spin):
            spin.setEnabled(self.size_check.isChecked() and not state)
        for spin in (self.x_spin, self.y_spin):
            spin.setEnabled(self.position_check.isChecked())
        chosen = bool(state) or self.position_check.isChecked() or self.size_check.isChecked()
        self.lock_check.setEnabled(chosen)
        if not kwin_available():
            return
        if state:
            word = "Fuldskærm" if state == "fullscreen" else "Et maksimeret vindue"
            self.window_hint.setText(
                f"{word} fylder den skærm vinduet åbner på. Sæt en placering for at "
                "bestemme hvilken.")
        elif not chosen:
            self.window_hint.setText(
                "Uden dette bestemmer browseren og KWin selv størrelse og placering.")
        elif self.lock_check.isChecked():
            self.window_hint.setText(
                "Slår igennem næste gang appen åbnes. Vinduet kan hverken flyttes "
                "eller skaleres bagefter.")
        else:
            self.window_hint.setText(
                "Slår igennem næste gang appen åbnes. Vinduet kan stadig flyttes og "
                "skaleres, og KWin husker det du selv gør.")

    def load_window_rule(self, app: WebApp):
        self.existing_class = window_class(app, self.browsers)
        rule = read_window_rule(self.existing_class)
        if rule.get("size"):
            self.size_check.setChecked(True)
            self.width_spin.setValue(rule["size"][0])
            self.height_spin.setValue(rule["size"][1])
        if rule.get("position"):
            self.position_check.setChecked(True)
            self.x_spin.setValue(rule["position"][0])
            self.y_spin.setValue(rule["position"][1])
        self.state_box.setCurrentIndex(max(0, self.state_box.findData(rule.get("state", ""))))
        self.lock_check.setChecked(bool(rule.get("lock")))
        if not self.existing_class:
            self.window_group.setEnabled(False)
            self.window_hint.setText("Browseren bag denne genvej kunne ikke genkendes, "
                                     "så vinduets app-id er ukendt.")

    def load_existing(self, app: WebApp):
        self.name_edit.setText(app.name)
        self.url_edit.setText(app.url)
        for index in range(self.browser_box.count()):
            if self.browser_box.itemData(index).argv == app.argv_prefix:
                self.browser_box.setCurrentIndex(index)
                break
        self.reload_profiles()
        for index in range(self.profile_box.count()):
            if self.profile_box.itemData(index) == app.profile:
                self.profile_box.setCurrentIndex(index)
                break
        self.update_preview(load_icon(app.icon).pixmap(64, 64))
        self.load_window_rule(app)
        if app.browser_installed:
            self.url_edit.setEnabled(False)
            self.url_edit.setPlaceholderText("styres af browserens app-id")
            self.hint.setText("Denne er installeret af browseren selv. Adressen ligger i "
                              "browserens app-id og kan ikke redigeres her.")

    def reload_profiles(self):
        browser = self.browser_box.currentData()
        self.profile_box.clear()
        if browser:
            for dirname, label in browser.profiles():
                self.profile_box.addItem(label, dirname)

    def update_preview(self, pixmap: QtGui.QPixmap):
        self.icon_label.setPixmap(pixmap)

    def fetch(self):
        url = self.normalised_url()
        if not url:
            QtWidgets.QMessageBox.warning(self, "Mangler adresse",
                                          "Udfyld adressen først.")
            return
        self.fetch_button.setEnabled(False)
        self.fetch_button.setText("Henter…")
        self.fetcher = IconFetcher(url, self)
        self.fetcher.done.connect(self.icon_fetched)
        self.fetcher.start()

    def icon_fetched(self, image: QtGui.QImage):
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText("Hent fra webstedet")
        if image.isNull():
            QtWidgets.QMessageBox.information(
                self, "Intet ikon fundet",
                "Kunne ikke finde et brugbart ikon på webstedet. Vælg en fil i stedet.")
            return
        self.image = image
        self.update_preview(QtGui.QPixmap.fromImage(image).scaled(
            64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def choose_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Vælg ikon", str(HOME), "Billeder (*.png *.jpg *.jpeg *.svg *.webp *.ico)")
        if not path:
            return
        image = QtGui.QImage(path)
        if image.isNull():
            QtWidgets.QMessageBox.warning(self, "Ugyldigt billede",
                                          "Filen kunne ikke indlæses som billede.")
            return
        self.image = image
        self.update_preview(QtGui.QPixmap.fromImage(image).scaled(
            64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def normalised_url(self) -> str:
        url = self.url_edit.text().strip()
        if url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            url = "https://" + url
        return url

    def accept(self):
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Mangler navn", "Giv web-appen et navn.")
            return
        if self.url_edit.isEnabled() and not self.normalised_url():
            QtWidgets.QMessageBox.warning(self, "Mangler adresse", "Udfyld adressen.")
            return
        super().accept()

    def result_values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "url": self.normalised_url(),
            "browser": self.browser_box.currentData(),
            "profile": self.profile_box.currentData() or "Default",
            "image": self.image,
            "size": ((self.width_spin.value(), self.height_spin.value())
                     if self.size_check.isChecked() and not self.state_box.currentData()
                     else None),
            "position": ((self.x_spin.value(), self.y_spin.value())
                         if self.position_check.isChecked() else None),
            "state": self.state_box.currentData(),
            "lock": self.lock_check.isChecked(),
            "old_wm_class": self.existing_class,
        }


# --------------------------------------------------------------------------
# Skrivning og fjernelse
# --------------------------------------------------------------------------

def unique_desktop_path(slug: str) -> Path:
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    path = APPS_DIR / f"{slug}.desktop"
    counter = 2
    while path.exists():
        path = APPS_DIR / f"{slug}-{counter}.desktop"
        counter += 1
    return path


def patch_desktop(path: Path, updates: dict[str, str]) -> None:
    """Ret enkeltnøgler i [Desktop Entry] uden at røre Actions-grupperne."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    group, seen = None, set()
    output = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if group == "Desktop Entry":
                output.extend(f"{k}={v}" for k, v in updates.items() if k not in seen)
                seen.update(updates)
            group = stripped[1:-1]
            output.append(line)
            continue
        if group == "Desktop Entry" and "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                if key in seen:
                    continue
                seen.add(key)
                output.append(f"{key}={updates[key]}")
                continue
        output.append(line)
    if group == "Desktop Entry":
        output.extend(f"{k}={v}" for k, v in updates.items() if k not in seen)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def apply_window_rule(values: dict, wm_class: str) -> None:
    """Læg vinduesreglen på det nye app-id og ryd den gamle hvis den er flyttet."""
    old_class = values.get("old_wm_class", "")
    if old_class and old_class != wm_class:
        remove_window_rule(old_class)
    write_window_rule(wm_class, values["name"], values.get("size"), values.get("position"),
                      values.get("lock", False), values.get("state", ""))


def save_webapp(values: dict, existing: WebApp | None) -> tuple[Path, str]:
    """Opret eller opdatér en web-app. Returnerer (sti, ikonnavn)."""
    browser: Browser = values["browser"]
    name, url, profile = values["name"], values["url"], values["profile"]

    if existing and existing.browser_installed:
        # Browserens egen PWA: rør kun navn og ikon, lad Exec og Actions være.
        icon_name = existing.icon or slugify(name)
        if values["image"] is not None and not icon_name.startswith("/"):
            install_icon(values["image"], icon_name)
        for target in [existing.path, *existing.twins]:
            patch_desktop(target, {"Name": name})
        refresh_caches()
        apply_window_rule(values, existing.wm_class
                          or wm_class_name(browser, url, existing.app_id, profile))
        return existing.path, icon_name

    if existing:
        path = existing.path
        icon_name = existing.icon if existing.icon and not existing.icon.startswith("/") \
            else slugify(name)
    else:
        slug = slugify(name)
        path = unique_desktop_path(slug)
        icon_name = path.stem

    if values["image"] is not None:
        install_icon(values["image"], icon_name)

    tokens = [*browser.argv,
              f"--profile-directory={profile}",
              f"--class={icon_name}",
              f"--app={url}"]
    # StartupWMClass skal være det app-id browseren giver vinduet, ikke ikonnavnet —
    # ellers finder proceslinjen ikke frem til denne fil og viser browserens ikon.
    wm_class = wm_class_name(browser, url, "", profile)

    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.5",
        f"Name={name}",
        f"Comment={url}",
        f"Exec={build_exec(tokens)}",
        f"Icon={icon_name}",
        "Terminal=false",
        "StartupNotify=true",
        f"StartupWMClass={wm_class or icon_name}",
        "Categories=Network;",
        f"{MARKER}=true",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o644)
    refresh_caches()
    apply_window_rule(values, wm_class)
    return path, icon_name


def remove_webapp(app: WebApp, browsers: list[Browser], drop_icon: bool = True) -> list[str]:
    removed = []
    for target in [app.path, *app.twins]:
        try:
            target.unlink()
            removed.append(str(target))
        except OSError as error:
            removed.append(f"kunne ikke fjerne {target}: {error}")
    if drop_icon and app.icon and not app.icon.startswith("/"):
        count = remove_icons(app.icon)
        if count:
            removed.append(f"{count} ikonfil(er)")
    wm_class = window_class(app, browsers)
    if read_window_rule(wm_class):
        try:
            remove_window_rule(wm_class)
            removed.append("vinduesreglen")
        except (OSError, ValueError) as error:
            removed.append(f"kunne ikke fjerne vinduesreglen: {error}")
    refresh_caches()
    return removed


def move_to_menu(app: WebApp, browsers: list[Browser]) -> Path:
    """Flyt en web-app fra skrivebordet ind i programmenuen.

    Snap-Brave kan ikke selv oprette menupunkt og ikoner — xdg-desktop-menu findes ikke i
    snappen — så den eneste genvej ligger på skrivebordet. Filnavnet bevares, alle
    Exec-linjer peges på /snap/bin, og ikonet hentes fra browserens profil.
    """
    target = APPS_DIR / app.path.name
    if target.exists():
        raise FileExistsError(f"{target} findes allerede")
    lines = app.path.read_text(encoding="utf-8", errors="replace").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("Exec="):
            lines[index] = "Exec=" + resolve_snap_exec(line[len("Exec="):])
    browser = app.find_browser(browsers)
    if (app.app_id and browser and app.icon and "/" not in app.icon
            and not any(ICON_ROOT.glob(f"*/apps/{app.icon}.png"))):
        image = browser_pwa_icon(browser, app.profile, app.app_id)
        if not image.isNull():
            install_icon(image, app.icon)
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target.chmod(0o644)
    app.path.unlink()
    refresh_caches()
    return target


# --------------------------------------------------------------------------
# Hovedvindue
# --------------------------------------------------------------------------

def window_summary(app: WebApp, browsers: list[Browser]) -> str:
    """Vinduesreglen skrevet ud, til detaljeruden."""
    rule = read_window_rule(window_class(app, browsers))
    parts = []
    if rule.get("state"):
        parts.append({"fullscreen": "fuldskærm", "maximized": "maksimeret"}[rule["state"]])
    if rule.get("size"):
        parts.append("{}×{}".format(*rule["size"]))
    if rule.get("position"):
        parts.append("ved {},{}".format(*rule["position"]))
    if rule.get("lock"):
        parts.append("(fastlåst)")
    return " ".join(parts) if parts else "browseren bestemmer"

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Genvej")
        self.resize(880, 560)
        self.browsers = detect_browsers()
        self.apps: list[WebApp] = []

        toolbar = self.addToolBar("Handlinger")
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.setMovable(False)

        def add_action(text, icon, slot, shortcut=None):
            action = QtGui.QAction(QtGui.QIcon.fromTheme(icon), text, self)
            action.triggered.connect(slot)
            if shortcut:
                action.setShortcut(shortcut)
            toolbar.addAction(action)
            return action

        self.new_action = add_action("Ny", "list-add", self.create, "Ctrl+N")
        self.edit_action = add_action("Rediger", "document-edit", self.edit, "F2")
        self.remove_action = add_action("Fjern", "edit-delete", self.remove, "Delete")
        self.open_action = add_action("Åbn", "system-run", self.launch, "Ctrl+O")
        self.menu_action = add_action("Læg i menu", "application-menu", self.add_to_menu)
        toolbar.addSeparator()
        self.browser_action = add_action("Browserens apps", "internet-web-browser",
                                         self.open_browser_apps)
        add_action("Opdater", "view-refresh", self.reload, "F5")

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("Søg…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(240)
        self.filter_edit.textChanged.connect(self.apply_filter)
        toolbar.addWidget(self.filter_edit)

        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setIconSize(QtCore.QSize(32, 32))
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.currentItemChanged.connect(self.selection_changed)
        self.list_widget.itemDoubleClicked.connect(self.launch)

        self.detail = QtWidgets.QFormLayout()
        self.detail.setLabelAlignment(Qt.AlignRight)
        self.detail_fields = {}
        for key, label in (("kind", "Type"), ("url", "Adresse"), ("browser", "Browser"),
                           ("profile", "Profil"), ("window", "Vindue"), ("path", "Fil")):
            value = QtWidgets.QLabel()
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            self.detail_fields[key] = value
            self.detail.addRow(f"{label}:", value)

        detail_widget = QtWidgets.QWidget()
        detail_box = QtWidgets.QVBoxLayout(detail_widget)
        self.detail_title = QtWidgets.QLabel()
        font = self.detail_title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        self.detail_title.setFont(font)
        self.detail_title.setWordWrap(True)
        detail_box.addWidget(self.detail_title)
        detail_box.addLayout(self.detail)
        detail_box.addStretch()

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.list_widget)
        splitter.addWidget(detail_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.statusBar()

        if not self.browsers:
            QtWidgets.QMessageBox.warning(
                self, "Ingen browser fundet",
                "Fandt ingen Chromium-baseret browser. Installér f.eks. Brave, "
                "Chromium eller Chrome for at kunne oprette web-apps.")
        self.reload()

    # -- data ------------------------------------------------------------
    def reload(self):
        current = self.current_app()
        remembered = str(current.path) if current else None
        self.apps = find_web_apps()
        self.apply_filter()
        if remembered:
            for row in range(self.list_widget.count()):
                item = self.list_widget.item(row)
                if str(item.data(Qt.UserRole).path) == remembered:
                    self.list_widget.setCurrentItem(item)
                    break
        managed = sum(1 for a in self.apps if not a.browser_installed)
        self.statusBar().showMessage(
            f"{len(self.apps)} web-app(s): {len(self.apps) - managed} installeret af "
            f"browseren, {managed} oprettet manuelt")

    def apply_filter(self):
        needle = self.filter_edit.text().strip().lower()
        self.list_widget.clear()
        for app in self.apps:
            if needle and needle not in f"{app.name} {app.url}".lower():
                continue
            item = QtWidgets.QListWidgetItem(load_icon(app.icon), app.name)
            item.setData(Qt.UserRole, app)
            if app.browser_installed:
                item.setToolTip("Installeret af browseren")
            self.list_widget.addItem(item)
        if self.list_widget.count() and not self.list_widget.currentItem():
            self.list_widget.setCurrentRow(0)
        self.selection_changed()

    def current_app(self) -> WebApp | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.UserRole) if item else None

    def selection_changed(self, *_):
        app = self.current_app()
        for value in self.detail_fields.values():
            value.setText("")
        self.detail_title.setText(app.name if app else "Ingen valgt")
        for action in (self.edit_action, self.remove_action, self.open_action):
            action.setEnabled(app is not None)
        self.browser_action.setEnabled(bool(app and app.browser_installed))
        self.menu_action.setEnabled(bool(app and app.on_desktop))
        if not app:
            return
        self.detail_fields["kind"].setText(
            f"{app.kind} — kun på skrivebordet" if app.on_desktop else app.kind)
        self.detail_fields["url"].setText(app.url or f"app-id {app.app_id}")
        self.detail_fields["browser"].setText(app.browser_label(self.browsers))
        self.detail_fields["profile"].setText(app.profile)
        self.detail_fields["window"].setText(window_summary(app, self.browsers))
        self.detail_fields["path"].setText(str(app.path))

    # -- handlinger ------------------------------------------------------
    def create(self):
        if not self.browsers:
            return
        dialog = EditorDialog(self.browsers, None, self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            path, _ = save_webapp(dialog.result_values(), None)
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self, "Kunne ikke gemme", str(error))
            self.reload()
            return
        self.reload()
        self.statusBar().showMessage(f"Oprettet: {path}", 8000)

    def edit(self):
        app = self.current_app()
        if not app or not self.browsers:
            return
        dialog = EditorDialog(self.browsers, app, self)
        if dialog.exec() != QtWidgets.QDialog.Accepted:
            return
        try:
            save_webapp(dialog.result_values(), app)
        except (OSError, ValueError) as error:
            QtWidgets.QMessageBox.warning(self, "Kunne ikke gemme", str(error))
            self.reload()
            return
        self.reload()
        self.statusBar().showMessage(f"Opdateret: {app.name}", 8000)

    def remove(self):
        app = self.current_app()
        if not app:
            return
        files = [app.path, *app.twins]
        text = (f"Fjern <b>{app.name}</b>?<br><br>Sletter:<br>"
                + "<br>".join(f"<code>{p}</code>" for p in files))
        if app.icon and not app.icon.startswith("/"):
            text += f"<br>samt ikonet <code>{app.icon}</code> i dit eget ikontema."
        if read_window_rule(window_class(app, self.browsers)):
            text += "<br>samt vinduesreglen i <code>kwinrulesrc</code>."
        if app.browser_installed:
            text += ("<br><br><b>Bemærk:</b> denne er installeret af browseren. "
                     "Genvejen forsvinder nu, men appen er stadig registreret inde i "
                     "browseren og kan blive gendannet. Afinstallér den også på "
                     "browserens app-side for at fjerne den helt.")
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Fjern web-app")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setTextFormat(Qt.RichText)
        box.setText(text)
        yes = box.addButton("Fjern", QtWidgets.QMessageBox.AcceptRole)
        box.addButton("Annullér", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not yes:
            return
        removed = remove_webapp(app, self.browsers)
        self.reload()
        self.statusBar().showMessage("Fjernet: " + ", ".join(removed), 10000)

    def add_to_menu(self):
        app = self.current_app()
        if not app or not app.on_desktop:
            return
        try:
            path = move_to_menu(app, self.browsers)
        except OSError as error:
            QtWidgets.QMessageBox.warning(self, "Kunne ikke lægge i menuen", str(error))
            return
        self.reload()
        self.statusBar().showMessage(f"Lagt i menuen: {path}", 8000)

    def launch(self):
        app = self.current_app()
        if not app:
            return
        try:
            subprocess.Popen(resolve_snap_command(exec_tokens(app.exec_line)),
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.statusBar().showMessage(f"Startede {app.name}", 5000)
        except OSError as error:
            QtWidgets.QMessageBox.warning(self, "Kunne ikke starte", str(error))

    def open_browser_apps(self):
        app = self.current_app()
        if not app or not app.argv_prefix:
            return
        scheme = "chrome"
        joined = " ".join(app.argv_prefix).lower()
        for name in ("brave", "vivaldi", "edge"):
            if name in joined:
                scheme = name if name != "edge" else "edge"
                break
        try:
            subprocess.Popen([*app.argv_prefix, f"--profile-directory={app.profile}",
                              f"{scheme}://apps"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            QtWidgets.QMessageBox.warning(self, "Kunne ikke åbne browseren", str(error))


def main():
    QtWidgets.QApplication.setDesktopFileName("genvej")
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Genvej")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
