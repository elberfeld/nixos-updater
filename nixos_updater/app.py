"""Tray-Anwendung im Stil des Linux-Mint-Update-Managers."""

import shlex
import sys
import threading
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject, QProcess, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import git
from .config import APP_NAME, Config, autostart_enabled, set_autostart

SERVER_NAME = f"{APP_NAME}-instance"


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #


@dataclass
class Status:
    state: str  # "unknown" | "checking" | "uptodate" | "available" | "error" | "updating"
    commits: list[git.Commit] = field(default_factory=list)
    message: str = ""
    upstream: str = ""
    dirty: bool = False


def theme_icon(names: list[str], fallback: QStyle.StandardPixmap) -> QIcon:
    for name in names:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
    return QApplication.style().standardIcon(fallback)


_ICON_STYLE = {
    "uptodate": ("#2e9e5b", "✓"),
    "available": ("#e08a1e", "↓"),
    "error": ("#d33a3a", "!"),
    "checking": ("#3a7bd5", "⟳"),
    "updating": ("#3a7bd5", "⟳"),
}


def status_icon(state: str, count: int = 0) -> QIcon:
    """Selbst gezeichnetes Icon, damit das Tray unabhängig vom Icon-Theme etwas anzeigt."""
    color, glyph = _ICON_STYLE.get(state, ("#808080", "?"))
    icon = QIcon()
    for size in (22, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(color))
        p.setPen(QPen(QColor("white"), max(1.0, size / 22)))
        m = size * 0.06
        p.drawEllipse(int(m), int(m), int(size - 2 * m), int(size - 2 * m))
        p.setPen(QColor("white"))
        text = str(count) if state == "available" and 0 < count < 100 else glyph
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(size * (0.5 if len(text) > 1 else 0.62)))
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        icon.addPixmap(pm)
    return icon


def status_text(st: Status) -> str:
    n = len(st.commits)
    return {
        "unknown": "Status unbekannt",
        "checking": "Suche nach Updates …",
        "uptodate": "System ist aktuell",
        "available": f"{n} neue{'r' if n == 1 else ''} Commit{'' if n == 1 else 's'} verfügbar",
        "updating": "Update läuft …",
        "error": f"Fehler: {st.message}",
    }[st.state]


# --------------------------------------------------------------------------- #
# Hintergrundprüfung
# --------------------------------------------------------------------------- #


class Checker(QObject):
    finished = pyqtSignal(object)  # Status

    def __init__(self):
        super().__init__()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(self, cfg: Config) -> bool:
        if self._running:
            return False
        self._running = True
        repo = cfg.repo_path
        threading.Thread(target=self._run, args=(repo,), daemon=True).start()
        return True

    def _run(self, repo):
        try:
            git.validate_repo(repo)
            git.run_git(repo, "fetch", "--quiet", timeout=120)
            commits = git.pending_commits(repo)
            st = Status(
                "available" if commits else "uptodate",
                commits=commits,
                upstream=git.upstream_name(repo),
                dirty=git.is_dirty(repo),
            )
        except git.GitError as e:
            st = Status("error", message=str(e).splitlines()[-1] if str(e) else "unbekannt")
        except Exception as e:  # noqa: BLE001 – Thread darf nie still sterben
            st = Status("error", message=repr(e))
        self._running = False
        self.finished.emit(st)


# --------------------------------------------------------------------------- #
# Einstellungen
# --------------------------------------------------------------------------- #


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen – NixOS Updater")
        self.setMinimumWidth(520)
        self.cfg = cfg

        self.repo_edit = QLineEdit(cfg.repo_dir)
        browse = QPushButton(theme_icon(["document-open-folder"], QStyle.StandardPixmap.SP_DirOpenIcon), "")
        browse.clicked.connect(self._browse)
        repo_row = QHBoxLayout()
        repo_row.addWidget(self.repo_edit)
        repo_row.addWidget(browse)

        self.term_edit = QLineEdit(cfg.terminal)
        self.term_edit.setPlaceholderText("z. B. konsole -e, kitty, alacritty -e, foot")
        self.term_edit.setToolTip(
            "Terminal-Kommando. Das Update-Skript wird als „bash -c …“ angehängt."
        )
        self.cmd_edit = QLineEdit(cfg.update_command)
        self.cmd_edit.setToolTip("Wird im Repository-Verzeichnis ausgeführt.")

        self.interval = QSpinBox()
        self.interval.setRange(0, 24 * 60)
        self.interval.setSuffix(" min")
        self.interval.setSpecialValueText("nur manuell")
        self.interval.setValue(cfg.check_interval_minutes)

        self.notify = QCheckBox("Benachrichtigen, wenn neue Commits verfügbar sind")
        self.notify.setChecked(cfg.notify)
        self.autostart = QCheckBox("Beim Anmelden automatisch starten")
        self.autostart.setChecked(autostart_enabled())

        form = QFormLayout()
        form.addRow("Konfigurations-Verzeichnis:", repo_row)
        form.addRow("Terminal-Emulator:", self.term_edit)
        form.addRow("Update-Kommando:", self.cmd_edit)
        form.addRow("Prüfintervall:", self.interval)
        form.addRow("", self.notify)
        form.addRow("", self.autostart)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self):
        start = str(Config(repo_dir=self.repo_edit.text()).repo_path)
        d = QFileDialog.getExistingDirectory(self, "Konfigurations-Verzeichnis wählen", start)
        if d:
            self.repo_edit.setText(d)

    def _defaults(self):
        d = Config()
        self.repo_edit.setText(d.repo_dir)
        self.term_edit.setText(d.terminal)
        self.cmd_edit.setText(d.update_command)
        self.interval.setValue(d.check_interval_minutes)
        self.notify.setChecked(d.notify)

    def accept(self):
        if not self.term_edit.text().strip() or not self.cmd_edit.text().strip():
            QMessageBox.warning(self, "Einstellungen", "Terminal und Update-Kommando dürfen nicht leer sein.")
            return
        try:
            shlex.split(self.term_edit.text())
        except ValueError as e:
            QMessageBox.warning(self, "Einstellungen", f"Terminal-Kommando ungültig: {e}")
            return
        self.cfg.repo_dir = self.repo_edit.text().strip()
        self.cfg.terminal = self.term_edit.text().strip()
        self.cfg.update_command = self.cmd_edit.text().strip()
        self.cfg.check_interval_minutes = self.interval.value()
        self.cfg.notify = self.notify.isChecked()
        try:
            self.cfg.save()
            set_autostart(self.autostart.isChecked())
        except OSError as e:
            QMessageBox.critical(self, "Einstellungen", f"Speichern fehlgeschlagen: {e}")
            return
        super().accept()


# --------------------------------------------------------------------------- #
# Hauptfenster
# --------------------------------------------------------------------------- #


class MainWindow(QMainWindow):
    def __init__(self, controller: "Controller"):
        super().__init__()
        self.ctl = controller
        self.setWindowTitle("NixOS Updater")
        self.setWindowIcon(theme_icon(["system-software-update"], QStyle.StandardPixmap.SP_ComputerIcon))
        self.resize(900, 600)

        tb = QToolBar()
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        tb.addAction(controller.act_check)
        tb.addAction(controller.act_update)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(controller.act_settings)

        self.status_icon = QLabel()
        self.status_label = QLabel()
        f = self.status_label.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        f.setBold(True)
        self.status_label.setFont(f)
        self.sub_label = QLabel()
        self.sub_label.setWordWrap(True)
        self.sub_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head_text = QVBoxLayout()
        head_text.addWidget(self.status_label)
        head_text.addWidget(self.sub_label)
        head = QHBoxLayout()
        head.addWidget(self.status_icon)
        head.addLayout(head_text, 1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Commit", "Datum", "Autor", "Beschreibung"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        for i in range(3):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tree.currentItemChanged.connect(self._show_details)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.details.setPlaceholderText("Commit auswählen, um Details anzuzeigen.")

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tree)
        split.addWidget(self.details)
        split.setSizes([330, 220])

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(head)
        lay.addWidget(split, 1)
        self.setCentralWidget(central)

    def update_status(self, st: Status):
        self.status_icon.setPixmap(status_icon(st.state).pixmap(48, 48))
        self.status_label.setText(status_text(st))
        sub = [f"Verzeichnis: {self.ctl.cfg.repo_path}"]
        if st.upstream:
            sub.append(f"Upstream: {st.upstream}")
        if st.dirty:
            sub.append("⚠ Arbeitsverzeichnis enthält lokale Änderungen")
        self.sub_label.setText("   ·   ".join(sub))

        if st.state in ("checking", "updating"):
            return  # Liste während der Prüfung stehen lassen
        selected = self.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) if self.tree.currentItem() else None
        self.tree.clear()
        self.details.clear()
        for c in st.commits:
            item = QTreeWidgetItem([c.short_hash, c.date, c.author, c.subject])
            item.setData(0, Qt.ItemDataRole.UserRole, c.hash)
            item.setToolTip(3, c.subject)
            self.tree.addTopLevelItem(item)
            if c.hash == selected:
                self.tree.setCurrentItem(item)

    def _show_details(self, item, _prev):
        if item is None:
            self.details.clear()
            return
        try:
            text = git.commit_details(self.ctl.cfg.repo_path, item.data(0, Qt.ItemDataRole.UserRole))
        except git.GitError as e:
            text = f"Fehler: {e}"
        self.details.setPlainText(text)

    def closeEvent(self, ev):
        # Schließen minimiert nur ins Tray
        ev.ignore()
        self.hide()


# --------------------------------------------------------------------------- #
# Controller (Tray, Timer, Update-Prozess)
# --------------------------------------------------------------------------- #


class Controller(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.cfg = Config.load()
        self.status = Status("unknown")
        self.update_proc: QProcess | None = None
        self._notified_head: str | None = None

        self.checker = Checker()
        self.checker.finished.connect(self._on_checked)

        SP = QStyle.StandardPixmap
        self.act_show = QAction("Fenster anzeigen", self)
        self.act_show.triggered.connect(self.show_window)
        self.act_check = QAction(theme_icon(["view-refresh"], SP.SP_BrowserReload), "Nach Updates suchen", self)
        self.act_check.triggered.connect(self.check)
        self.act_update = QAction(
            theme_icon(["system-software-update", "update-high"], SP.SP_ArrowUp), "Update installieren", self
        )
        self.act_update.triggered.connect(self.run_update)
        self.act_settings = QAction(theme_icon(["configure", "settings-configure"], SP.SP_FileDialogDetailedView), "Einstellungen", self)
        self.act_settings.triggered.connect(self.open_settings)
        self.act_quit = QAction(theme_icon(["application-exit"], SP.SP_DialogCloseButton), "Beenden", self)
        self.act_quit.triggered.connect(app.quit)

        self.window = MainWindow(self)

        menu = QMenu()
        menu.addAction(self.act_show)
        menu.addSeparator()
        menu.addAction(self.act_check)
        menu.addAction(self.act_update)
        menu.addSeparator()
        menu.addAction(self.act_settings)
        menu.addAction(self.act_quit)
        self.menu = menu

        self.tray = QSystemTrayIcon(self)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.messageClicked.connect(self.show_window)
        self.tray.show()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self._apply_interval()

        self._set_status(self.status)
        QTimer.singleShot(3000, self.check)

    # -- Status --------------------------------------------------------------

    def _set_status(self, st: Status):
        self.status = st
        text = status_text(st)
        self.tray.setIcon(status_icon(st.state, len(st.commits)))
        tip = f"NixOS Updater\n{text}"
        if st.state == "available":
            tip += "\n\n" + "\n".join(f"• {c.subject}" for c in st.commits[:8])
            if len(st.commits) > 8:
                tip += f"\n… und {len(st.commits) - 8} weitere"
        self.tray.setToolTip(tip)
        busy = st.state in ("checking", "updating")
        self.act_check.setEnabled(not busy)
        self.act_update.setEnabled(not busy and st.state != "error")
        self.window.update_status(st)

    def check(self):
        if self.status.state == "updating" or self.checker.running:
            return
        prev = self.status
        self._set_status(Status("checking", commits=prev.commits, upstream=prev.upstream, dirty=prev.dirty))
        self.checker.start(self.cfg)

    def _on_checked(self, st: Status):
        if self.status.state == "updating":
            return
        self._set_status(st)
        if st.state == "available" and self.cfg.notify:
            head = st.commits[0].hash
            if head != self._notified_head and not self.window.isVisible():
                self._notified_head = head
                n = len(st.commits)
                self.tray.showMessage(
                    "NixOS-Updates verfügbar",
                    f"{n} neue{'r' if n == 1 else ''} Commit{'' if n == 1 else 's'}:\n{st.commits[0].subject}",
                    status_icon("available"),
                    10000,
                )

    def _apply_interval(self):
        if self.cfg.check_interval_minutes > 0:
            self.timer.start(self.cfg.check_interval_minutes * 60 * 1000)
        else:
            self.timer.stop()

    # -- Aktionen ------------------------------------------------------------

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.window.isVisible() and self.window.isActiveWindow():
                self.window.hide()
            else:
                self.show_window()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.check()

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def open_settings(self):
        old_repo = self.cfg.repo_dir
        dlg = SettingsDialog(self.cfg, self.window if self.window.isVisible() else None)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_interval()
            if self.cfg.repo_dir != old_repo:
                self.status = Status("unknown")
            self.check()

    def run_update(self):
        if self.update_proc is not None:
            return
        repo = self.cfg.repo_path
        if not repo.is_dir():
            QMessageBox.critical(None, "NixOS Updater", f"Verzeichnis existiert nicht:\n{repo}")
            return
        if self.status.state == "uptodate":
            ans = QMessageBox.question(
                self.window if self.window.isVisible() else None,
                "NixOS Updater",
                "Es sind keine neuen Commits vorhanden.\nUpdate trotzdem ausführen?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        script = (
            f"cd {shlex.quote(str(repo))} || exit 1\n"
            f"printf '\\e[1m» %s\\e[0m\\n\\n' {shlex.quote(self.cfg.update_command)}\n"
            f"{self.cfg.update_command}\n"
            "rc=$?\n"
            "echo\n"
            "if [ $rc -eq 0 ]; then printf '\\e[1;32m✔ Update erfolgreich abgeschlossen\\e[0m\\n';\n"
            "else printf '\\e[1;31m✘ Update fehlgeschlagen (Exit-Code %s)\\e[0m\\n' $rc; fi\n"
            "read -rp 'Enter drücken zum Schließen …' _\n"
            "exit $rc\n"
        )
        try:
            argv = shlex.split(self.cfg.terminal) + ["bash", "-c", script]
        except ValueError as e:
            QMessageBox.critical(None, "NixOS Updater", f"Terminal-Kommando ungültig: {e}")
            return

        proc = QProcess(self)
        proc.setProgram(argv[0])
        proc.setArguments(argv[1:])
        proc.setWorkingDirectory(str(repo))
        proc.finished.connect(self._on_update_finished)
        proc.errorOccurred.connect(self._on_update_error)
        self.update_proc = proc
        self._set_status(Status("updating", commits=self.status.commits, upstream=self.status.upstream))
        proc.start()

    def _on_update_error(self, err):
        if err == QProcess.ProcessError.FailedToStart:
            QMessageBox.critical(
                None,
                "NixOS Updater",
                f"Terminal konnte nicht gestartet werden:\n{self.cfg.terminal}\n\n"
                "Bitte in den Einstellungen prüfen.",
            )
            self._on_update_finished()

    def _on_update_finished(self, *_):
        if self.update_proc is None:
            return
        self.update_proc.deleteLater()
        self.update_proc = None
        self.status = Status("unknown")
        self.check()


# --------------------------------------------------------------------------- #
# Einstieg
# --------------------------------------------------------------------------- #


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName("NixOS Updater")
    app.setDesktopFileName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    # Nur eine Instanz: zweiter Start öffnet das Fenster der laufenden Instanz
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(500):
        sock.write(b"show")
        sock.waitForBytesWritten(500)
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print(f"{APP_NAME}: Kein System-Tray verfügbar, zeige nur das Fenster")

    ctl = Controller(app)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), ctl.show_window()))
    if "--show" in sys.argv or not QSystemTrayIcon.isSystemTrayAvailable():
        ctl.show_window()
    return app.exec()
