# Genvej

Lav websteder om til rigtige skrivebordsapps — og ryd op i dem igen.

Genvej er et lille Qt6-program til Linux, der samler alle dine web-apps ét sted:
både dem du selv laver ud fra en URL, og dem din browser har installeret som PWA'er.
Andre værktøjer kan kun se deres egne genveje; Genvej finder dem alle sammen, fordi
den læser `.desktop`-filerne direkte.

## Hvad den kan

- Opret en web-app ud fra en adresse — vælg browser, profil og ikon
- Hent ikonet automatisk fra webstedet (favicon, apple-touch-icon eller manifest)
- Se alle eksisterende web-apps, uanset hvem der har lavet dem
- Omdøb og skift ikon, også på browserens egne PWA'er
- Fjern en web-app helt, inklusive dens ikonfiler
- Åbn browserens app-side i den rigtige profil, når en PWA skal afinstalleres helt

## Installation

```bash
git clone <repo> genvej && cd genvej
./install.sh
```

Kræver `python3` og `PySide6`. På Fedora, Bazzite og andre atomic-varianter er begge
med i forvejen; ellers `sudo dnf install python3-pyside6`.

Afinstallation med `./uninstall.sh`. Dine web-apps bliver liggende.

## Understøttede browsere

Alle Chromium-baserede — Brave, Chrome, Chromium, Edge og Vivaldi, både som
systempakke og Flatpak. Firefox understøttes ikke, da den ikke har et tilsvarende
`--app=`-tilstand.
