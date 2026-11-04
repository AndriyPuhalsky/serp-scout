#!/usr/bin/env python3
"""Stop-хук: журнал подій обов'язковий (CLAUDE.md, правило 2).

Якщо в проєкті є файли, змінені пізніше за ЖУРНАЛ_ПОДІЙ.md (+ запас GRACE_SECONDS),
повертає код 2 — Claude має додати запис у журнал перед завершенням. Повторно в тій
самій зупинці не спрацьовує (stop_hook_active), тож зациклення немає.
Невалідний вхід → вихід 0.
"""
import json
import os
import sys
import unicodedata

JOURNAL = "ЖУРНАЛ_ПОДІЙ.md"
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".ruff_cache", ".pytest_cache",
             ".state", "data", "dist"}
SKIP_REL_DIRS = {"site/data"}
SKIP_FILES = {JOURNAL, ".DS_Store", "settings.local.json", "uv.lock"}
GRACE_SECONDS = 90


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0  # невалідний вхід — не наша подія, не блокуємо
    if not isinstance(data, dict):
        data = {}
    if data.get("stop_hook_active"):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    journal = os.path.join(root, JOURNAL)
    if not os.path.exists(journal):
        sys.stderr.write(f"Немає {JOURNAL} у корені проєкту — створи його й додай перший запис.\n")
        return 2
    since = os.path.getmtime(journal) + GRACE_SECONDS
    changed = []
    for dirpath, dirs, files in os.walk(root):
        rel_dir = nfc(os.path.relpath(dirpath, root)).replace(os.sep, "/")
        dirs[:] = [d for d in dirs if nfc(d) not in SKIP_DIRS
                   and (d if rel_dir == "." else f"{rel_dir}/{d}") not in SKIP_REL_DIRS]
        for f in files:
            if nfc(f) in SKIP_FILES:
                continue
            p = os.path.join(dirpath, f)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > since:
                changed.append((m, nfc(os.path.relpath(p, root))))
    if not changed:
        return 0
    changed.sort(reverse=True)
    names = ", ".join(n for _, n in changed[:6]) + (" …" if len(changed) > 6 else "")
    sys.stderr.write(
        f"Файли змінено після останнього запису в {JOURNAL}: {names}. "
        "Додай запис у журнал (формат — на початку файлу, або /log), потім завершуй.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
