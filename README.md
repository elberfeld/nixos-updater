# NixOS Updater

Kleines Tray-Tool (im Stil des Linux-Mint-Update-Managers) für NixOS-Konfigurationen,
die in einem Git-Repository liegen. „Update verfügbar“ heißt: Der Upstream-Branch hat
Commits, die lokal noch nicht gepullt sind.

- Tray-Icon zeigt den Status (aktuell / Updates verfügbar / Fehler / läuft)
- Fenster listet die offenen Commits (`git log HEAD..@{upstream}`) mit Details
- „Update installieren“ öffnet ein Terminal und führt das Update-Kommando im Repo aus
- Prüft periodisch per `git fetch` (Intervall einstellbar), optional mit Benachrichtigung

Bedienung Tray-Icon: Linksklick = Fenster ein/aus, Mittelklick = jetzt prüfen,
Rechtsklick = Menü.

## Einstellungen

Über das Fenster bzw. Tray-Menü → *Einstellungen*, gespeichert in
`~/.config/nixos-updater/config.json`:

| Schlüssel                | Default                         |
|--------------------------|---------------------------------|
| `repo_dir`               | `~/nixos-config`                |
| `terminal`               | `konsole -e`                    |
| `update_command`         | `git pull && nh os switch .`    |
| `check_interval_minutes` | `60` (0 = nur manuell)          |
| `notify`                 | `true`                          |

An `terminal` wird `bash -c <skript>` angehängt, z. B. `konsole -e`, `kitty`,
`alacritty -e`, `foot`, `wezterm start --`, `gnome-terminal --`. Das Terminal bleibt
nach dem Update offen, bis Enter gedrückt wird; danach wird automatisch neu geprüft.

Die Checkbox „Beim Anmelden automatisch starten“ legt
`~/.config/autostart/nixos-updater.desktop` an.

## Bauen / Starten

```sh
nix run .                 # direkt starten
nix run . -- --show       # mit geöffnetem Fenster starten
```

Einbinden in die NixOS-Konfiguration (Flake):

```nix
inputs.nixos-updater.url = "github:<user>/nixos-updater";
# ...
environment.systemPackages = [ inputs.nixos-updater.packages.${pkgs.system}.default ];
```

Entwicklung: `nix develop` und dann `python -m nixos_updater`.

## Lizenz

GPL-3.0-or-later, siehe [LICENSE](LICENSE).
