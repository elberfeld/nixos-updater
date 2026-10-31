"""Laden und Speichern der Einstellungen (JSON unter $XDG_CONFIG_HOME)."""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_NAME = "nixos-updater"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.json"


def autostart_file() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "autostart" / f"{APP_NAME}.desktop"


@dataclass
class Config:
    # Lokales Verzeichnis mit der ausgecheckten NixOS-Konfiguration
    repo_dir: str = "~/nixos-config"
    # Terminal-Emulator inkl. Argument zum Ausführen eines Kommandos.
    # Das auszuführende Kommando wird als `bash -c <script>` angehängt.
    terminal: str = "konsole -e"
    # Kommando, das im Repo-Verzeichnis für das Update ausgeführt wird
    update_command: str = "git pull && nh os switch ."
    # Prüfintervall in Minuten (0 = nur manuell)
    check_interval_minutes: int = 60
    # Desktop-Benachrichtigung bei neuen Updates
    notify: bool = True

    @property
    def repo_path(self) -> Path:
        return Path(os.path.expanduser(self.repo_dir))

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            data = json.loads(config_file().read_text())
        except FileNotFoundError:
            return cfg
        except (OSError, json.JSONDecodeError) as e:
            print(f"{APP_NAME}: Konfiguration nicht lesbar ({e}), nutze Defaults")
            return cfg
        for f in fields(cls):
            if f.name in data:
                setattr(cfg, f.name, type(getattr(cfg, f.name))(data[f.name]))
        return cfg

    def save(self) -> None:
        path = config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")


def autostart_enabled() -> bool:
    return autostart_file().exists()


def set_autostart(enabled: bool) -> None:
    path = autostart_file()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=NixOS Updater\n"
        f"Exec={APP_NAME}\n"
        "Icon=system-software-update\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
