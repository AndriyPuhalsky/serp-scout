#!/usr/bin/env python3
"""Notification-хук (async): Telegram-пінг, коли Claude чекає на Андрія.

Текст «⏸ Claude чекає на вас (<notification_type>): <message>» → tools/notify_telegram.py --dev.
Вимикач: TG_DEV=0 (в оточенні або в .env) — нічого не робити. TG_DRY_RUN=1 — лише надрукувати.
Завжди вихід 0; помилки — мовчки в stderr.
"""
import json
import os
import re
import subprocess
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
TEXT_MAX = 600


def mask(text):
    try:
        sys.path.insert(0, HOOKS_DIR)
        from guard_secrets import mask as guard_mask
        return guard_mask(text)
    except Exception:  # noqa: BLE001
        return re.sub(r"\b[A-Za-z0-9_\-]{32,}\b", "***", text or "")


def env_flag(root, name):
    """Значення змінної з оточення, а якщо немає — з .env у корені (лише ця одна змінна, без друку)."""
    if name in os.environ:
        return os.environ[name].strip()
    try:
        with open(os.path.join(root, ".env"), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = re.match(rf"\s*(?:export\s+)?{name}\s*=\s*(.*)$", line)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def notify(root, text):
    script = os.path.join(root, "tools", "notify_telegram.py")
    if not os.path.isfile(script):
        sys.stderr.write("tools/notify_telegram.py відсутній — сповіщення пропущено.\n")
        return
    cmd = [sys.executable, script, "--dev", text]
    if os.environ.get("TG_DRY_RUN", "").strip() == "1":
        cmd.append("--dry-run")
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.stderr.write(f"notify_telegram не запустився: {type(e).__name__}\n")
        return
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    root = os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd()
    if env_flag(root, "TG_DEV") == "0":
        return 0
    kind = str(data.get("notification_type") or "notification")
    message = data.get("message")
    message = " ".join(message.split()) if isinstance(message, str) and message.strip() else "(без тексту)"
    if len(message) > TEXT_MAX:
        message = message[:TEXT_MAX].rstrip() + "…"
    try:
        notify(root, f"⏸ Claude чекає на вас ({kind}): {mask(message)}")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"notify_attention: {type(e).__name__}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
