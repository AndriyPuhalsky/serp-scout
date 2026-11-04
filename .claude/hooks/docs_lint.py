#!/usr/bin/env python3
"""PreToolUse-хук на `git commit`: не дає закомітити неузгоджені документи.

Сама перевірка — tools/docs_lint.py (запускається і з `make lint`). Тут лише обгортка:
помилки → deny зі звітом, попередження не блокують. Інші Bash-команди пропускаються,
як і текст «git commit» усередині heredoc. Невалідний вхід → вихід 0.
"""
import json
import os
import re
import subprocess
import sys

HEREDOC_RE = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?.*?^\1\s*$", re.S | re.M)
# Той самий вираз, що в guard_secrets: шлях до git, глобальні опції (-C ., -c k=v), `command git`
COMMIT_RE = re.compile(
    r"(?:^|[;&|]\s*|\$\(\s*|\bcommand\s+)(?:\S*/)?git(?:\s+-[^\s]+(?:\s+\S+)?)*\s+commit\b", re.M)


def is_git_commit(command):
    """True лише для команди git commit, а не для тексту «git commit» усередині heredoc чи лапок."""
    return bool(COMMIT_RE.search(HEREDOC_RE.sub("", command or "")))


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    if not is_git_commit((data.get("tool_input") or {}).get("command")):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    script = os.path.join(root, "tools", "docs_lint.py")
    if not os.path.isfile(script):
        sys.stderr.write("tools/docs_lint.py відсутній — перевірку документів пропущено.\n")
        return 0
    try:
        r = subprocess.run([sys.executable, script, "--root", root], cwd=root,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"docs_lint не запустився: {e}\n")
        return 0
    if r.returncode == 0:
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": ("Документи неузгоджені (tools/docs_lint.py):\n"
                                     + (r.stdout or r.stderr)[-2000:]),
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
