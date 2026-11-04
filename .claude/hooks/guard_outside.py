#!/usr/bin/env python3
"""PreToolUse-хук (Write|Edit): запис лише в межах кореня проєкту.

Дозволено: файли під коренем (CLAUDE_PROJECT_DIR або cwd), тимчасові файли сесії
(/private/tmp/claude-501, /tmp/claude*, /private/tmp/claude*) і пам'ять Claude Code
(~/.claude/projects/). Усе інше, а також будь-що в .git/, відхиляється.
Рішення приймається ЛИШЕ за realpath після NFC-нормалізації: символьне посилання
проєкт/x → ~/.ssh чи → .git розв'язується і не проходить; .git порівнюється без регістру.
Будь-який невалідний вхід → вихід 0 (хук не має блокувати сесію сам по собі).
"""
import json
import os
import sys
import unicodedata

EXTRA_ALLOWED = (
    "/private/tmp/claude-501/",
    "/tmp/claude",
    "/private/tmp/claude",
    os.path.join(os.path.expanduser("~"), ".claude", "projects") + os.sep,
)


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def canon(path):
    """Абсолютний шлях з NFC і розв'язаними символьними посиланнями (realpath)."""
    return os.path.realpath(os.path.abspath(nfc(path)))


def under(path, prefix):
    """True, якщо path лежить під prefix (prefix без кінцевого / — звичайний префікс, як /tmp/claude*)."""
    if prefix.endswith(os.sep):
        return path == prefix.rstrip(os.sep) or path.startswith(prefix)
    return path.startswith(prefix)


def allowed_outside(path):
    """Шлях у дозволених теках поза проєктом (сирий префікс або його realpath — /tmp → /private/tmp)."""
    for pfx in EXTRA_ALLOWED:
        tail = os.sep if pfx.endswith(os.sep) else ""
        if under(path, pfx) or under(path, canon(pfx) + tail):
            return True
    return False


def in_git_dir(path, root):
    """Шлях у .git/ кореня: за realpath самого .git або за відносним шляхом без урахування регістру."""
    git_dir = canon(os.path.join(root, ".git"))
    if path == git_dir or path.startswith(git_dir + os.sep):
        return True
    rel = os.path.relpath(path, root).replace(os.sep, "/").lower()
    return rel == ".git" or rel.startswith(".git/")


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}, ensure_ascii=False))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") not in ("Write", "Edit"):
        return 0
    raw = (data.get("tool_input") or {}).get("file_path") or ""
    if not raw:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    root = canon(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    # Відносний шлях рахуємо від cwd сесії, як це робить сам інструмент; далі — лише realpath
    path = canon(nfc(raw) if os.path.isabs(raw) else os.path.join(cwd, nfc(raw)))

    if under(path, root + os.sep):
        if in_git_dir(path, root):
            deny(f"Запис у .git/ заборонено ({os.path.relpath(path, root)}). "
                 "Git-метадані змінюються лише командами git.")
        return 0
    if allowed_outside(path):
        return 0
    deny(f"Запис поза коренем проєкту заборонено: {raw} → {path}. Дозволено лише файли в {root}, "
         "тимчасові файли сесії (/private/tmp/claude-501) і пам'ять у ~/.claude/projects/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
