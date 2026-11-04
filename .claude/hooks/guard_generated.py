#!/usr/bin/env python3
"""PreToolUse-хук (Write|Edit): згенеровані файли руками не правимо (CLAUDE.md, правило 6).

Цифри на сайті, в експорті і в документі про вартість мають походити лише з даних
прогону, тому Write/Edit у такі файли відхиляється з підказкою, що їх генерує.
Невалідний вхід → вихід 0.
"""
import json
import os
import re
import sys
import unicodedata

GENERATED = [
    (r"^site/data/[^/]+\.json$", "`uv run serp-scout build-site`"),
    (r"^data/export/.+", "`uv run serp-scout export`"),
    (r"^data/serp\.sqlite$", "пайплайн (`uv run serp-scout run`)"),
    (r"^docs/10_ВАРТІСТЬ\.md$", "команда /cost"),
    (r"^data/costs\.jsonl$", "пайплайн (облік вартості LLM у модулі costs)"),
]


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("tool_name") not in ("Write", "Edit"):
        return 0
    path = (data.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return 0
    cwd = data.get("cwd") or os.getcwd()
    root = os.path.abspath(nfc(os.environ.get("CLAUDE_PROJECT_DIR") or cwd))
    absolute = nfc(path) if os.path.isabs(path) else os.path.join(cwd, nfc(path))
    rel = os.path.relpath(os.path.abspath(absolute), root).replace(os.sep, "/")
    for rx, generator in GENERATED:
        if re.search(rx, rel):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{rel} генерує {generator}; запусти його замість ручної правки "
                                            "(правило 6: цифри лише з даних прогону).",
            }}, ensure_ascii=False))
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
