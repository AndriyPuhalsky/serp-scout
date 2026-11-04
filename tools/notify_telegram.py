#!/usr/bin/env python3
"""Повідомлення в Telegram: події розробки (хуки) і підсумок щоденного прогону. Лише stdlib.

  python3 tools/notify_telegram.py --dev "харнес готовий"                 — префікс «🛠 serp-scout»
  python3 tools/notify_telegram.py --status ok   --text "10 ключів, 97 URL" — «✅ Прогін serp-scout»
  python3 tools/notify_telegram.py --status fail --text-file run.log        — «❌ Прогін serp-scout»
  --dry-run   — надрукувати, що було б надіслано, без мережі (токен не потрібен)
  --text-file — узяти текст із файлу (замість --text або значення --dev)

TELEGRAM_BOT_TOKEN і TELEGRAM_CHAT_ID беруться з оточення, а якщо їх там немає — з .env у корені
проєкту (тека над tools/). Значення ніколи не друкуються: ні в логах, ні в помилках, ні в dry-run.
Текст: секрети маскуються (***), HTML-екранування & < >, обрізання до 4096 UTF-16-одиниць.
Повтори: до 3 спроб на 429 (поважаємо retry_after, не більше 30 с), 5xx і мережеві збої.
Код виходу завжди 0 — сповіщення не має валити ні прогін, ні хук.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.telegram.org"
TIMEOUT = 20
MAX_TEXT = 4096
ATTEMPTS = 3
RETRY_AFTER_CAP = 30
PREFIXES = {
    "dev": "🛠 serp-scout",
    "ok": "✅ Прогін serp-scout",
    "fail": "❌ Прогін serp-scout",
}

# Усе, що схоже на ключі й токени, → *** (до екранування й обрізання)
SECRET_PATTERNS = [
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_-]+"), "bot***"),                        # URL Bot API з токеном
    (re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"), "***"),                      # токен Telegram
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"), "***"),                          # ключ Anthropic
    (re.compile(r"\bnfp_[A-Za-z0-9]{30,}\b"), "***"),                            # токен Netlify
    (re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}"), "***"),       # токени GitHub
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "***"),
    (re.compile(r"(?i)\b(bearer)\s+\S+"), r"\1 ***"),                             # Authorization: Bearer …
    # NAME=значення для token/api_key/password/secret
    (re.compile(r"(?i)\b(token|authorization|api[_-]?key|password|passwd|secret)(\s*[:=]\s*)\S+"),
     r"\1\2***"),
    (re.compile(r"\b[0-9a-fA-F]{32,}\b"), "***"),                                 # довгі hex (SerpApi — 64)
]


def mask_secrets(text):
    out = str(text)
    for rx, repl in SECRET_PATTERNS:
        out = rx.sub(repl, out)
    return out


def escape(text):
    """Екранування для parse_mode=HTML: & — першим."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tg_len(text):
    """Довжина так, як її рахує Telegram (UTF-16 code units)."""
    return len(text.encode("utf-16-le")) // 2


def truncate(text, limit=MAX_TEXT):
    """Обрізає до limit UTF-16-одиниць, не розриваючи HTML-сутності (&amp; …)."""
    if tg_len(text) <= limit:
        return text
    tail = "…"
    budget = limit - tg_len(tail)
    out = text
    while tg_len(out) > budget:
        out = out[: max(0, len(out) - max(1, tg_len(out) - budget))]
    amp = out.rfind("&")
    if amp != -1 and ";" not in out[amp:]:
        out = out[:amp]
    return out.rstrip() + tail


def build_message(kind, text):
    """Готовий HTML: <b>префікс</b> і текст з маскуванням, екрануванням і лімітом довжини."""
    head = f"<b>{escape(PREFIXES[kind])}</b>"
    body = escape(mask_secrets(text or "").strip())
    return truncate(f"{head}\n{body}" if body else head)


def read_env_file(path):
    """{NAME: value} з .env; коментарі й порожні рядки пропускаються, лапки знімаються."""
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def credentials(environ=None, root=ROOT_DIR):
    """(token, chat_id) з оточення або .env; відсутні — порожні рядки."""
    environ = os.environ if environ is None else environ
    token = (environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat:
        env = read_env_file(os.path.join(root, ".env"))
        token = token or (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
        chat = chat or (env.get("TELEGRAM_CHAT_ID") or "").strip()
    return token, chat


def _description(raw):
    """Тіло помилки Bot API → (description, retry_after або None)."""
    try:
        data = json.loads(raw.decode("utf-8"))
        params = data.get("parameters") or {}
        return str(data.get("description", "")), params.get("retry_after")
    except (ValueError, AttributeError):
        return "", None


def send(token, chat_id, html, opener=urllib.request.urlopen, sleep=time.sleep, log=None):
    """sendMessage з повторами (429 — за retry_after ≤ 30 с; 5xx і мережа — 3 с). True — доставлено.
    Токен і chat_id в лог не потрапляють."""
    log = log or (lambda msg: sys.stderr.write(msg + "\n"))
    payload = json.dumps({"chat_id": chat_id, "text": html, "parse_mode": "HTML",
                          "link_preview_options": {"is_disabled": True}}).encode("utf-8")
    for attempt in range(1, ATTEMPTS + 1):
        req = urllib.request.Request(f"{API}/bot{token}/sendMessage", data=payload, method="POST",
                                     headers={"Content-Type": "application/json"})
        wait = None
        try:
            with opener(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return True
            log(f"Telegram відповів ok=false: {mask_secrets(str(data.get('description', '')))}")
            return False
        except urllib.error.HTTPError as e:
            desc, retry_after = _description(e.read() or b"")
            e.close()
            log(f"Telegram HTTP {e.code}: {mask_secrets(desc)}")
            if e.code == 429:
                try:
                    wait = min(int(retry_after or 5), RETRY_AFTER_CAP)
                except (TypeError, ValueError):
                    wait = 5
            elif e.code >= 500:
                wait = 3
            else:
                return False  # 400/401/403 — повтор не допоможе
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            log(f"Telegram недоступний: {mask_secrets(str(getattr(e, 'reason', None) or type(e).__name__))}")
            wait = 3
        except ValueError:
            log("Telegram: відповідь не JSON")
            return False
        if attempt < ATTEMPTS and wait is not None:
            sleep(wait)
    return False


class _Parser(argparse.ArgumentParser):
    """Помилка аргументів → повідомлення в stderr, але код виходу 0 (сповіщення не валить прогін)."""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"notify_telegram: {message}\n")
        raise SystemExit(0)


def parse_args(argv):
    ap = _Parser(description="Повідомлення в Telegram: події розробки або підсумок прогону serp-scout")
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--dev", metavar="ТЕКСТ", help="подія розробки (префікс «🛠 serp-scout»)")
    what.add_argument("--status", choices=("ok", "fail"), help="підсумок щоденного прогону")
    ap.add_argument("--text", default=None, help="текст для --status")
    ap.add_argument("--text-file", default=None, help="узяти текст із файлу")
    ap.add_argument("--dry-run", action="store_true", help="лише надрукувати, без мережі")
    return ap.parse_args(argv)


def message_text(args):
    if args.text_file:
        try:
            with open(args.text_file, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError as e:
            return f"(не вдалося прочитати {args.text_file}: {type(e).__name__})"
    if args.dev is not None:
        return args.dev
    return args.text or ""


def main(argv=None, opener=urllib.request.urlopen, sleep=time.sleep, environ=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    kind = "dev" if args.dev is not None else args.status
    html = build_message(kind, message_text(args))
    token, chat = credentials(environ)
    if args.dry_run:
        state = "налаштовано" if token and chat else "не налаштовано"
        print(f"[dry-run] Telegram {state}; повідомлення ({tg_len(html)} симв.):\n{html}")
        return 0
    if not token or not chat:
        sys.stderr.write("Telegram не налаштовано (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) — "
                         "повідомлення пропущено\n")
        return 0
    if send(token, chat, html, opener=opener, sleep=sleep):
        print("Повідомлення в Telegram надіслано")
    else:
        sys.stderr.write("Повідомлення в Telegram НЕ надіслано (прогін не зупиняємо)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
