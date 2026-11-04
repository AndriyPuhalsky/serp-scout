#!/usr/bin/env python3
"""PreToolUse-хук: не дає записати у файл або закомітити щось схоже на ключ чи токен.

Write/Edit — перевіряє новий вміст (крім .env, .env.local, .env.example).
Bash з `git commit` — перевіряє додані рядки в індексі та робочій копії
(без uv.lock, *.sqlite і data/ — там хеші й дані, а не секрети).
Секрети живуть лише в .env і GitHub Secrets (CLAUDE.md, правило 3).
Невалідний вхід → вихід 0.
"""
import json
import os
import re
import subprocess
import sys

# (назва, регулярний вираз) — перевіряються на всьому тексті
PATTERNS = [
    ("ключ Anthropic", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("токен Telegram-бота", r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    ("токен Netlify", r"\bnfp_[A-Za-z0-9]{30,}\b"),
    ("токен GitHub", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    ("приватний ключ", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
# Ключ SerpApi — 64 hex, але лише в рядку з контекстом ключа і без sha256
# (інакше uv.lock і хеші дають хибні спрацювання)
HEX64_RE = re.compile(r"\b[0-9a-f]{64}\b")
HEX64_CONTEXT = ("serpapi", "api_key")
HEX64_EXCLUDE = ("sha256",)

ALLOWED_FILES = {".env", ".env.local", ".env.example"}
# Файли, чиї додані рядки в diff не перевіряються
DIFF_IGNORE_RE = re.compile(r"(^|/)uv\.lock$|\.sqlite$|^data/")

HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?^\1\s*$", re.S | re.M)
COMMIT_RE = re.compile(r"(?:^|[;&|]\s*|\$\(\s*)git\s+commit\b", re.M)


def is_git_commit(command):
    """True лише для команди git commit, а не для тексту «git commit» усередині heredoc чи лапок."""
    return bool(COMMIT_RE.search(HEREDOC_RE.sub("", command or "")))


def serpapi_hits(text):
    """Рядки з 64-hex поруч зі словом serpapi/api_key і без sha256."""
    for line in (text or "").splitlines():
        low = line.lower()
        if not HEX64_RE.search(low):
            continue
        if any(c in low for c in HEX64_CONTEXT) and not any(x in low for x in HEX64_EXCLUDE):
            return True
    return False


def find(text):
    """Назви знайдених типів секретів (без значень)."""
    text = text or ""
    hits = [name for name, rx in PATTERNS if re.search(rx, text)]
    if serpapi_hits(text):
        hits.append("ключ SerpApi")
    return hits


def mask(text):
    """Замінює все схоже на секрет на ***; використовується також у Telegram-сповіщеннях."""
    out = text or ""
    for _, rx in PATTERNS:
        out = re.sub(rx, "***", out)
    lines = []
    for line in out.splitlines(keepends=True):
        lines.append(HEX64_RE.sub("***", line) if serpapi_hits(line) else line)
    return "".join(lines)


def added_lines(root):
    """Додані рядки з `git diff --cached -U0` і `git diff -U0`, крім файлів із DIFF_IGNORE_RE."""
    out = []
    for args in (["git", "diff", "--cached", "-U0", "--no-color"], ["git", "diff", "-U0", "--no-color"]):
        try:
            r = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=15, errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            continue
        skip = False
        for line in r.stdout.splitlines():
            if line.startswith("+++ "):
                path = line[4:].strip()
                path = path[2:] if path.startswith("b/") else path
                skip = bool(DIFF_IGNORE_RE.search(path))
            elif line.startswith("+") and not skip:
                out.append(line[1:])
    return "\n".join(out)


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
    if not isinstance(data, dict):
        return 0
    tool = data.get("tool_name")
    ti = data.get("tool_input") or {}
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()

    if tool in ("Write", "Edit"):
        path = ti.get("file_path") or ""
        if os.path.basename(path) in ALLOWED_FILES:
            return 0
        hits = find(ti.get("content") or ti.get("new_string"))
        if hits:
            deny(f"У тексті для {os.path.basename(path) or 'файлу'} схоже на: {', '.join(hits)}. "
                 "Секрети зберігаються лише в .env або GitHub Secrets — заміни значення на назву змінної.")
    elif tool == "Bash" and is_git_commit(ti.get("command")):
        hits = find(added_lines(root))
        if hits:
            deny(f"У змінах для коміту схоже на: {', '.join(hits)}. "
                 "Прибери секрет зі змін (git diff) перед комітом.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
