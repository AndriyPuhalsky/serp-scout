#!/usr/bin/env python3
"""PostToolUse-хук (Write|Edit): після правки коду запускає відповідні перевірки.

Шлях → команди (усе через uv, у межах 170 с):
  src/**/*.py, tests/**/*.py (крім test_hooks)  → uv run ruff check --fix <файл>;
                                                   uv run pytest -q -x --ignore=tests/test_hooks.py
                                                   (pytest пропускається, якщо інших test_*.py немає)
  .claude/hooks/*.py, tools/*.py, tests/test_hooks.py → uv run pytest -q tests/test_hooks.py (якщо існує)
  site/js/*.js|mjs, site/tests/*.mjs              → node --test site/tests/*.test.mjs
                                                   (без node або без тестів — пропуск із повідомленням)
Падіння → код 2 і хвіст виводу (3000 символів) у stderr, щоб Claude одразу виправив.
Без pyproject.toml у корені нічого не запускається. Невалідний вхід → вихід 0.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

TOTAL_TIMEOUT = 170
TAIL = 3000


class Runner:
    """Послідовні команди зі спільним бюджетом часу; перша невдача зупиняє решту."""

    def __init__(self, root, rel):
        self.root, self.rel = root, rel
        self.deadline = time.monotonic() + TOTAL_TIMEOUT

    def run(self, cmd, label):
        left = self.deadline - time.monotonic()
        if left <= 1:
            sys.stderr.write(f"Перевірки для {self.rel} не вклались у {TOTAL_TIMEOUT} с "
                             f"({label} не запущено).\n")
            return 2
        try:
            r = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, timeout=left,
                               errors="replace")
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"{label} не завершився за {TOTAL_TIMEOUT} с після зміни {self.rel}.\n")
            return 2
        except OSError as e:
            sys.stderr.write(f"{label} не запустився ({type(e).__name__}) — пропущено.\n")
            return 0
        if r.returncode != 0:
            out = (r.stdout + "\n" + r.stderr).strip()
            sys.stderr.write(f"{label} впав після зміни {self.rel} (код {r.returncode}):\n{out[-TAIL:]}\n")
            return 2
        return 0


def has_other_tests(root):
    """Є хоч один tests/**/test_*.py, крім test_hooks.py."""
    for p in glob.glob(os.path.join(root, "tests", "**", "test_*.py"), recursive=True):
        if os.path.basename(p) != "test_hooks.py":
            return True
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") not in ("Write", "Edit"):
        return 0
    ti = data.get("tool_input") or {}
    path = ti.get("file_path") or (data.get("tool_response") or {}).get("filePath") or ""
    if not path:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    root = os.path.abspath(unicodedata.normalize("NFC", os.environ.get("CLAUDE_PROJECT_DIR") or cwd))
    if not os.path.isfile(os.path.join(root, "pyproject.toml")):
        return 0
    absolute = path if os.path.isabs(path) else os.path.join(cwd, path)
    rel = unicodedata.normalize("NFC", os.path.relpath(os.path.abspath(absolute), root)).replace(os.sep, "/")
    if rel.startswith("../"):
        return 0
    runner = Runner(root, rel)

    if re.match(r"^(src|tests)/.+\.py$", rel) and os.path.basename(rel) != "test_hooks.py":
        if not shutil.which("uv"):
            sys.stderr.write("uv не знайдено — ruff і pytest пропущено.\n")
            return 0
        code = runner.run(["uv", "run", "--frozen", "ruff", "check", "--fix", rel], "ruff")
        if code:
            return code
        if not has_other_tests(root):
            return 0
        return runner.run(["uv", "run", "--frozen", "pytest", "-q", "-x", "--ignore=tests/test_hooks.py"],
                          "pytest")

    if re.match(r"^(\.claude/hooks/[^/]+\.py|tools/[^/]+\.py|tests/test_hooks\.py)$", rel):
        if not os.path.isfile(os.path.join(root, "tests", "test_hooks.py")):
            return 0
        if not shutil.which("uv"):
            sys.stderr.write("uv не знайдено — тести хуків пропущено.\n")
            return 0
        return runner.run(["uv", "run", "--frozen", "pytest", "-q", "tests/test_hooks.py"],
                          "pytest tests/test_hooks.py")

    if re.match(r"^site/(js/[^/]+\.m?js|tests/[^/]+\.mjs)$", rel):
        files = sorted(glob.glob(os.path.join(root, "site", "tests", "*.test.mjs")))
        if not files:
            sys.stderr.write(f"JS-тестів у site/tests ще немає — після зміни {rel} нічого не запущено.\n")
            return 0
        if not shutil.which("node"):
            sys.stderr.write(f"node не знайдено — JS-тести для {rel} пропущено.\n")
            return 0
        return runner.run(["node", "--test", *files], "node --test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
