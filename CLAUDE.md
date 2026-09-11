# Genvej

Qt6-skrivebordsprogram til at oprette, redigere og fjerne web-apps (PWA'er) på Linux.
Det kan både lave nye genveje ud fra en URL og administrere de PWA'er en Chromium-baseret
browser selv har installeret — det sidste er grunden til at projektet findes, for
alternativerne på Flathub (`dev.heppen.webapps`, `net.codelogistics.webapps`,
`org.pvermeer.WebAppHub`) kan kun se deres egne.

## Filer

| Sti | Rolle |
| --- | --- |
| `genvej.py` | Hele programmet — logik og GUI i ét modul |
| `data/make_icon.py` | Tegner programikonet med QPainter, ingen billedfiler i repoet |
| `data/genvej.desktop` | Menupunkt |
| `install.sh` / `uninstall.sh` | Installation i `~/.local`, uden root |

Installeret ligger koden i `~/.local/share/genvej/genvej.py`. Kør altid `./install.sh`
efter en ændring — programmet køres fra den installerede kopi, ikke fra repoet.

## Afhængigheder

Kun `python3` og `PySide6`. Begge findes allerede på Bazzite/Kinoite. På Ubuntu er
PySide6 delt op i moduler — der skal bruges `python3-pyside6.qtcore`, `.qtgui` og
`.qtwidgets`. Ingen tredjepartspakker, intet byggetrin, ingen virtualenv — det er et bevidst valg, så
programmet kan køre direkte på et immutable system uden layering.

## Kør og test

```bash
./install.sh && genvej                # normal kørsel
python3 genvej.py                     # kør direkte fra repoet
```

Headless test uden at røre rigtige filer — monkeypatch stierne før noget kaldes:

```python
QT_QPA_PLATFORM=offscreen python3 - <<'PY'
import sys, tempfile; from pathlib import Path
sys.path.insert(0, ".")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])          # skal oprettes før QImage bruges
import genvej as g
tmp = Path(tempfile.mkdtemp())
g.APPS_DIR = tmp/"applications"; g.APPS_DIR.mkdir()
g.ICON_ROOT = tmp/"icons/hicolor"
g.scan_dirs = lambda: [g.APPS_DIR]
g.refresh_caches = lambda: None
# ... test save_webapp / find_web_apps / remove_webapp her
PY
```

`MainWindow` kan instantieres offscreen, så GUI-opstart, filtrering og
knap-tilstande kan testes uden skærm. Finder `detect_browsers()` ingen browser, åbner
konstruktøren en modal advarsel og testen hænger — patch `QtWidgets.QMessageBox.warning`
først. Kør med `python3 -u`, ellers går output tabt når `timeout` slår processen ihjel.
`QIcon.fromTheme()` finder intet under `offscreen` — heller ikke et ikon der ligger rigtigt,
og uanset `setThemeName()`. Ikonopslag skal testes med den rigtige platform
(`env -u QT_QPA_PLATFORM`); så længe intet `show()`/`exec()` kaldes, vises der ikke noget.

## Domæneviden — det der faktisk driller

Punkterne herunder er alle fundet ved at fejle på dem. Lav dem ikke om uden grund.

**Flatpak-browsere symlinker deres app-mappe.**
`~/.var/app/<id>/data/applications` er på dette system et symlink til
`~/.local/share/applications`. Scanner man begge naivt, tælles hver web-app to gange,
og sletning fejler på anden runde. `scan_dirs()` deduplikerer derfor på `Path.resolve()`,
og `find_web_apps()` sammenligner ligeledes resolved stier før den registrerer en
`twin`. `twins` er stadig relevant hvis en anden browser har en ægte kopi.

**Snap-browsere lever i deres egen hjemmemappe.**
En strict snap kører med `HOME`, `XDG_CONFIG_HOME` og `XDG_DATA_HOME` flyttet til
`~/snap/<navn>/<revision>` (set i `/proc/<pid>/environ` på Snap-Brave). Brave har derfor
profilen i `~/snap/brave/current/.config/BraveSoftware/Brave-Browser` — `BRAVE_CONFIG_HOME`
peger på `common/`, men profilen ligger ikke der. En gammel `~/.config/BraveSoftware` kan
godt findes ved siden af og er da forkert. En browser fundet i `/snap/bin` registreres
som Snap med `snap_config_dir()`, aldrig som systempakke. Chromium-snappens profil i
`common/chromium` er ikke afprøvet. Uverificeret, men udledt af miljøet: browserens egne
PWA'er havner i `~/snap/<navn>/current/.local/share/applications` og `…/icons`, som
KDE-menuen ikke læser, og Exec får den interne `/snap/brave/<revision>/…`-sti fra
`CHROME_WRAPPER`. `resolve_snap_command()` skifter den ud med `/snap/bin/<navn>` — ellers
kører browseren uden sandkasse og med den forkerte profil.

**Exec-linjen er ikke bare en streng.**
`%` skal skrives som `%%` i `Exec` jf. desktop entry-specifikationen — vigtigt fordi
URL'er ofte indeholder procentkodning. Ved læsning skal field codes (`%U`, `%f` …)
fjernes, og Braves egne flextop-filer citerer hvert argument enkeltvis
(`flatpak 'run' '--command=brave' …`), så der skal bruges `shlex.split`, ikke `.split()`.
`exec_tokens()` og `build_exec()` er det eneste sted det håndteres.

**To slags web-apps, to slags adfærd.**
`--app-id=<id>` betyder at browseren selv har installeret PWA'en; URL'en findes kun
inde i browserens profil. `--app=<url>` er en manuel genvej. For den første må
programmet kun rette `Name` og ikon via `patch_desktop()` — Exec og Actions-grupper
skal stå urørt — og en fjernelse er kun kosmetisk: Brave kan gendanne filen, så
brugeren skal også afinstallere på `brave://apps`. Det står i bekræftelsesdialogen.

**Profilnavne kommer fra browseren.**
`Local State` → `profile.info_cache` giver mappenavn plus det navn brugeren har givet
profilen ("Default — Personal"). Fallback er at lede efter mapper med en `Preferences`-fil.

**Ikoner.**
Skrives som PNG i `~/.local/share/icons/hicolor/<størrelse>/apps/<navn>.png`.
Der er ikke brug for en `index.theme` i brugerens hicolor-mappe — det er testet, både
Qt og KDE finder ikonerne uden. Ved fjernelse slettes kun ikoner uden `/` i navnet og
kun under `ICON_ROOT`, aldrig systemikoner.

**Ikonhentning fra websteder.**
`fetch_icon()` skal respektere `<base href>` før relative `href`'er opløses — iCloud
sætter f.eks. base til `/system/icloud.com/<build>/en-us/` og peger på `../favicons/…`.
Mange SPA'er svarer med `index.html` på manifest-stien i stedet for 404, så
JSON-parsing af manifestet skal fejle stille. Sidste udvej er `/favicon.ico`.

**Cache-opdatering.**
Efter enhver ændring: `update-desktop-database`, `gtk-update-icon-cache` og
`kbuildsycoca6`. Uden den sidste dukker menupunktet ikke op i KDE.
Verificér med `strings -el ~/.cache/ksycoca6* | grep -i <navn>` — bemærk `-el`,
ksycoca gemmer strenge som UTF-16, så almindelig `strings` finder ingenting og giver
et falsk negativ.

**Wayland og vinduesgruppering.**
Programmet sætter selv sit app-id med `QApplication.setDesktopFileName("genvej")` før
`QApplication` oprettes. For de genveje der *genereres*, sættes `--class=<ikonnavn>` og
`StartupWMClass` til samme værdi. Uverificeret detalje: når browseren allerede kører,
sendes kommandoen videre til den eksisterende proces, og det er uafklaret om `--class`
slår igennem der. Hvis et vindue viser browserens ikon i stedet for appens, er en
KWin-vinduesregel løsningen.

## Konventioner

Brugerflade, kommentarer og docstrings er på dansk. Kode-identifikatorer er på engelsk.
Ingen forkortede variabelnavne. Undtagelser fanges specifikt (`OSError`, `ValueError`,
`urllib.error.URLError`) — programmet må aldrig gå ned på et websted der ikke svarer.

## Ikke lavet endnu

- Understøttelse af Firefox (kræver en helt anden mekanisme end `--app=`)
- Redigering af kategorier og Actions/genvejsmenuer på en web-app
- Import af en URL direkte fra en kørende browserfane
- Oversættelse (alle strenge er hardcodede på dansk)

## Undersøgt og fravalgt

**Luk-til-systembakke kan ikke lade sig gøre for en Chromium-PWA.**
En `--app=`/`--app-id=`-genvej er et almindeligt browservindue uden tray-understøttelse,
og krydset håndteres inde i browseren. Der er intet flag og ingen indstilling der laver
"luk → minimér til bakken". Udefra går det heller ikke på Wayland: close-hændelsen går
direkte til klienten, KWin kan ikke opsnappe den, og der findes ingen protokol til at
flytte et fremmed vindue ind i systembakken — KWin-vinduesregler har ingen luk-handling.
På X11 kunne `kdocker`/`alltray` gøre det (de opsnapper `WM_DELETE_WINDOW`), men de virker
ikke på Wayland-native vinduer, og Chromium sender typisk kommandoen videre til en
allerede kørende proces, så en wrapper ville dokke det forkerte vindue. Uverificeret.

Eneste rigtige løsning er et program der selv ejer vinduet — Electron, Tauri eller
QtWebEngine. En QtWebEngine-tilstand i Genvej ville koste både afhængighedsprincippet
(QtWebEngine ligger ikke på Kinoite som standard) og browserprofilen: logins, udvidelser,
adgangskoder, synk. Det er prisen ikke værd.

Delvist i dag: `brave://settings/system` → "Fortsæt med at køre baggrundsapps når Brave
lukkes" holder service workers og notifikationer i live efter vinduet lukkes, men giver
hverken vindue eller ikon per app.
