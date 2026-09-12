# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Genvej

Qt6-skrivebordsprogram til at oprette, redigere og fjerne web-apps (PWA'er) på Linux.
Det kan både lave nye genveje ud fra en URL og administrere de PWA'er en Chromium-baseret
browser selv har installeret — det sidste er grunden til at projektet findes, for
alternativerne på Flathub (`dev.heppen.webapps`, `net.codelogistics.webapps`,
`org.pvermeer.WebAppHub`) kan kun se deres egne.

## Filer

| Sti | Rolle |
| --- | --- |
| `genvej.py` | Hele programmet — logik og GUI i ét modul |
| `data/make_icon.py` | Tegner programikonet med QPainter, ingen billedfiler i repoet. Tager ikonroden som argument og køres offscreen af `install.sh` |
| `data/genvej.desktop` | Menupunkt |
| `install.sh` / `uninstall.sh` | Installation i `~/.local`, uden root |

Installeret ligger koden i `~/.local/share/genvej/genvej.py`. Kør altid `./install.sh`
efter en ændring — programmet køres fra den installerede kopi, ikke fra repoet.

## Opbygning

`genvej.py` er delt i sektioner: .desktop-håndtering, browsere og profiler, fundne
web-apps, ikoner, vinduesregler, redigeringsdialog, skrivning og fjernelse, hovedvindue.

- **Ingen egen database.** Web-apps udledes ved hver `reload()` af `.desktop`-filerne:
  `scan_dirs()` → `find_web_apps()` → `WebApp`. En fil er en web-app hvis `Exec` indeholder
  `--app=` eller `--app-id=`; Genvejs egne filer har desuden `X-Genvej=true` (`managed`).
- **Browseren genkendes på argv.** `detect_browsers()` bygger ét `Browser`-objekt pr.
  installationsform (systempakke, `-snap`, `-flatpak`) ud fra `BROWSER_TABLE` og
  `ALT_BINARIES`. `WebApp.argv_prefix` er Exec-ordene før første `--app`/`--app-id`/
  `--profile-directory`/`--class`, og en web-app hører til den browser hvis `argv` er lig
  med den (`find_browser()`, `EditorDialog.load_existing()`). Ændres måden argv skrives
  eller læses på, skal begge sider følge med.
- **Alle skrivninger** går gennem `save_webapp()`, `patch_desktop()`, `remove_webapp()` og
  `move_to_menu()` og slutter med `refresh_caches()`. Vinduesgeometri er den ene undtagelse
  fra "ingen egen database": den ligger i KWins `kwinrulesrc`, som `write_window_rule()` og
  `remove_window_rule()` ejer én gruppe ad gangen i.
- **Stierne er modulglobaler** (`HOME`, `APPS_DIR`, `ICON_ROOT`, `SNAP_BIN`), som læses når
  funktionerne kaldes — det er det der gør monkeypatching i test mulig. Bind dem ikke som
  standardargumenter eller ved import. `kwin_rules_file()` er ikke en global, men afledes af
  `HOME` ved kaldet og følger derfor med af sig selv.
- Ikonhentning fra websteder kører i `IconFetcher` (QThread), så dialogen ikke fryser.

## Afhængigheder

Kun `python3` og `PySide6`. Begge findes allerede på Bazzite/Kinoite. På Ubuntu er
PySide6 delt op i moduler — der skal bruges `python3-pyside6.qtcore`, `.qtgui` og
`.qtwidgets`. Ingen tredjepartspakker, intet byggetrin, ingen virtualenv — det er et
bevidst valg, så programmet kan køre direkte på et immutable system uden layering.

## Kør og test

```bash
./install.sh && genvej                # normal kørsel
python3 genvej.py                     # kør direkte fra repoet
```

Der er ingen testsuite, linter eller CI i repoet. Test sker headless uden at røre rigtige
filer — monkeypatch stierne før noget kaldes:

```bash
QT_QPA_PLATFORM=offscreen python3 -u - <<'PY'
import os, sys, tempfile; from pathlib import Path
sys.path.insert(0, ".")
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])          # skal oprettes før QImage bruges
import genvej as g
tmp = Path(tempfile.mkdtemp())
g.HOME = tmp                              # desktop_dir(), profil- og snap-stier
g.APPS_DIR = tmp/".local/share/applications"; g.APPS_DIR.mkdir(parents=True)
g.ICON_ROOT = tmp/".local/share/icons/hicolor"
g.SNAP_BIN = tmp/"snap-bin"
g.refresh_caches = lambda: None
g.kwin_reconfigure = lambda: None           # ellers får den kørende KWin besked
g.flatpak_installed = lambda app_id: False  # ellers køres `flatpak info` pr. browser
os.environ["XDG_CURRENT_DESKTOP"] = "KDE"   # ellers er Vindue-gruppen slået fra
brave = g.Browser("brave", "Brave", ["/snap/bin/brave"], None, "brave")  # wm_prefix skal med
# ... test save_webapp / find_web_apps / move_to_menu / remove_webapp her
PY
```

`remove_webapp()` og `move_to_menu()` tager en liste af `Browser` som andet argument. Bygger
man en i hånden, skal `wm_prefix` med — uden den giver `wm_class_name()` tom streng, og så
skrives der aldrig en vinduesregel. Skærmen under `offscreen` er 800×800, så det er den
`WINDOW_AREAS` og `suggest_geometry()` regner ud fra i en test.

`detect_browsers()` bruger `shutil.which` med den rigtige `PATH`. Skal den testes, så sæt
`os.environ["PATH"]` til en mappe med falske eksekverbare filer, og læg snap-browserne i
den patchede `SNAP_BIN`.

`MainWindow` kan instantieres offscreen, så GUI-opstart, filtrering og
knap-tilstande kan testes uden skærm. Finder `detect_browsers()` ingen browser, åbner
konstruktøren en modal advarsel og testen hænger — patch `QtWidgets.QMessageBox.warning`
først. Kør med `python3 -u`, ellers går output tabt når `timeout` slår processen ihjel.
`QIcon.fromTheme()` finder intet under `offscreen` — heller ikke et ikon der ligger rigtigt,
og uanset `setThemeName()`. Ikonopslag skal testes med den rigtige platform
(`env -u QT_QPA_PLATFORM`); så længe intet `show()`/`exec()` kaldes, vises der ikke noget.

**Sådan måles et rigtigt vindue.** Alt om vinduesregler herunder er fundet ved at åbne et
vindue og se efter. KWin har ingen kommandolinje til det, så det går gennem et script over
D-Bus, og `print()` lander i journalen:

```bash
cat > /tmp/dump.js <<'JS'
workspace.windowList().forEach(function (w) {
  print("MÅL|" + w.resourceClass + "|" + w.frameGeometry.x + "," + w.frameGeometry.y
        + " " + w.frameGeometry.width + "x" + w.frameGeometry.height
        + "|fullScreen " + w.fullScreen + "|" + w.caption);
});
JS
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript /tmp/dump.js maal1
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start
sleep 1   # uden den er linjerne ikke i journalen endnu, og grep finder ingenting
journalctl --user -b --since "-10s" | grep -o "MÅL|.*"
```

Navnet til `loadScript` skal være nyt hver gang, ellers køres scriptet ikke igen. Samme
fremgangsmåde lukker et testvindue med `w.closeWindow()`; at sætte `w.frameGeometry` udefra
gør derimod ingenting på en Chromium-app. En browser der allerede kører sender kommandoen
videre til sin egen proces — vil man teste opstartstilfældet, skal der en frisk instans til
med `--user-data-dir=` et sted browseren må skrive (for en snap inde i dens egen hjemmemappe).

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
`common/chromium` er ikke afprøvet.

**Snap-Brave kan ikke lægge sine PWA'er i menuen.**
Ved "Installer som app" kalder Chromium `xdg-desktop-menu` og `xdg-icon-resource`, men de
findes ikke i snappen — journalen viser `LaunchProcess: failed to execvp: xdg-desktop-menu`.
Der kommer hverken menufil eller ikoner. Den eneste genvej er den Chromium selv skriver på
skrivebordet, `~/Desktop/brave-<app-id>-<profil>.desktop` i den rigtige hjemmemappe, og dens
`Icon=brave-<app-id>-<profil>` peger på et ikon der aldrig blev installeret. Ikonerne findes
kun i profilen under `<profil>/Web Applications/Manifest Resources/<app-id>/Icons/<str>.png`.
Appens navn står ikke i klartekst i `Preferences` (kun `web_app_install_metrics.<app-id>`),
så uden skrivebordsfilen kendes navnet ikke. De havner heller ikke i
`~/snap/<navn>/current/.local/share/applications` — wrapperen opretter kun
`.local/share/mimeapps.list` der. Exec får den revisionsbundne sti fra `CHROME_WRAPPER` —
set som `/snap/brave/678/…` efter snappen var opdateret til 680. `resolve_snap_command()`
skifter den ud med `/snap/bin/<navn>`, ellers kører browseren uden sandkasse med den
forkerte profil og holder op med at virke når revisionen fjernes.

Derfor scanner `scan_dirs()` også skrivebordet — `desktop_dir()` læser `XDG_DESKTOP_DIR` i
`user-dirs.dirs`, da mappenavnet er sprogafhængigt. "Læg i menu" (`move_to_menu()`) flytter
filen til `APPS_DIR` under samme filnavn, retter hver `Exec=`-linje inklusive
Actions-grupperne med `resolve_snap_exec()` — der kun skifter første ord, så field codes og
citering bevares — og installerer ikonet fra `Manifest Resources`, medmindre det allerede
findes i `ICON_ROOT`.

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
`QApplication` oprettes. For de genveje der *genereres*, sættes stadig `--class=<ikonnavn>`,
men det er målt at flaget **ikke** når frem til app-vinduet: et `--app=`-vindue får app-id
`<browser>-<vært>_<sti>-<profil>`, uanset `--class`, og uanset om genvejen selv starter
browseren eller kommandoen sendes videre til en kørende proces. `--class` sætter kun app-id
på et almindeligt browservindue fra samme proces. Derfor skriver `save_webapp()` det rigtige
app-id i `StartupWMClass` — ellers kan proceslinjen ikke koble vinduet til `.desktop`-filen,
og vinduet viser browserens ikon. `wm_class_name()` danner strengen, og
`chromium_app_name()` efterligner Chromiums `GenerateApplicationNameFromURL`: vært + `_` +
sti, alt uden for `[A-Za-z0-9_.-]` som `_`, uden skema, port, query og fragment. Verificeret
mod tre rigtige vinduer, f.eks. `https://outlook.office.com/mail/` →
`brave-outlook.office.com__mail_-Default`. En browserinstalleret PWA har allerede det rigtige
`StartupWMClass` i browserens egen fil — `window_class()` foretrækker det frem for at gætte.

**Vinduesstørrelse og -placering kan kun styres af KWin.**
Alt herunder er målt på Wayland med Snap-Brave og KWin 6.6.

- `--window-size=B,H` virker kun når genvejen faktisk starter browserprocessen. Kører
  browseren allerede, sendes kommandolinjen videre til den, og flaget ignoreres — det er
  det normale tilfælde, så flaget er ubrugeligt her.
- `--window-position` ignoreres altid. En Wayland-klient må ikke placere sig selv.
- En KWin-vinduesregel virker derimod også på et vindue den kørende browser laver.

`kwinrulesrc` deles med KDE's egen regeleditor, så filen læses og skrives med
`configparser` (`optionxform = str`, KConfig-nøgler er versalfølsomme), og `[General]`
`rules`/`count` opdateres uden at røre andres regler. Gruppenavnet er en `uuid5` af app-id'et,
så den samme web-app altid rammer sin egen gruppe. Fire ting kostede tid:

- Metoden hedder `org.kde.KWin.reconfigure`. `reloadConfig` findes ikke på KWin 6.
- En regel slår **kun** igennem på vinduer der åbnes bagefter. Heller ikke `Force` rykker et
  vindue der allerede står der, så en test skal lukke vinduet og åbne det igen.
- Regeltypen `1` ("anvend ved åbning") gør ingenting mod en Chromium-app — browseren sætter
  selv sin geometri. Kun `2` (husk) og `3` (fastlås) vinder. Genvej bruger 2 som standard og
  3 når brugeren krydser "Fastlås" af; med 2 skriver KWin selv brugerens ændringer tilbage i
  filen, og dialogen viser dem næste gang.
- `types=1` (kun almindelige vinduer) er afprøvet og forhindrer ikke match.

Vinduet kan også åbne maksimeret eller i fuldskærm — `WINDOW_STATES` og `STATE_KEYS`.
Begge er afprøvet med samme regeltype: `fullscreen=true`, og `maximizehoriz=true` plus
`maximizevert=true` (begge skal med, ellers maksimeres kun den ene led). Et maksimeret
vindue melder `maximizable false` på KWins side, men reglen virker alligevel — målt til
`0,0 1920x1154` på en 1920×1200-skærm med et 46 px panel, og `fullScreen false`, så det
er rigtig maksimering og ikke fuldskærm. De to tilstande udelukker hinanden, og et skift
rydder den andens nøgler ud af gruppen. Begge bruger den skærm vinduet lander på, så
`position` skrives ved siden af for at vælge skærmen — målt for fuldskærm på skærm 2,
antaget at gælde maksimering på samme måde (ikke afprøvet med to skærme). `size` skrives
ikke sammen med nogen af dem; feltet er slået fra i dialogen. Hurtigvalgene i `WINDOW_AREAS` er andele af `availableGeometry()` for
den valgte skærm, og reglens `size` er *rammens* størrelse, så fjerdedele fliser præcist
(målt: 1920×1080 ved 1920,1080 på en 3840×2160-skærm).

`EditorDialog.window_hint` har fast højde. Teksten skifter når felterne slås til og fra, og
en ombrudt label der vokser fra én til to linjer flytter rundt på hele dialogen — også
ikonet længere oppe.

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
