"""Git-Abfragen: ausstehende Commits zwischen HEAD und Upstream."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


class GitError(Exception):
    pass


@dataclass
class Commit:
    hash: str
    short_hash: str
    author: str
    date: str
    subject: str


def git_env() -> dict:
    env = dict(os.environ)
    # Niemals interaktiv nach Credentials fragen – wir laufen im Hintergrund
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"
    return env


def run_git(repo: Path, *args: str, timeout: int = 30) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            env=git_env(),
            timeout=timeout,
        )
    except FileNotFoundError:
        raise GitError("git wurde nicht gefunden")
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]}: Zeitüberschreitung")
    if res.returncode != 0:
        raise GitError(res.stderr.strip() or f"git {args[0]} fehlgeschlagen")
    return res.stdout


def validate_repo(repo: Path) -> None:
    if not repo.is_dir():
        raise GitError(f"Verzeichnis existiert nicht: {repo}")
    run_git(repo, "rev-parse", "--git-dir")
    try:
        run_git(repo, "rev-parse", "--abbrev-ref", "@{upstream}")
    except GitError:
        raise GitError("Aktueller Branch hat keinen Upstream-Branch")


def pending_commits(repo: Path) -> list[Commit]:
    fmt = FIELD_SEP.join(["%H", "%h", "%an", "%ad", "%s"]) + RECORD_SEP
    out = run_git(
        repo, "log", "HEAD..@{upstream}", f"--format={fmt}", "--date=format:%Y-%m-%d %H:%M"
    )
    commits = []
    for record in out.split(RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) == 5:
            commits.append(Commit(*parts))
    return commits


def commit_details(repo: Path, commit: str) -> str:
    return run_git(repo, "show", "--stat", "--format=fuller", "--no-color", commit)


def is_dirty(repo: Path) -> bool:
    return bool(run_git(repo, "status", "--porcelain", "--untracked-files=no").strip())


def upstream_name(repo: Path) -> str:
    return run_git(repo, "rev-parse", "--abbrev-ref", "@{upstream}").strip()
