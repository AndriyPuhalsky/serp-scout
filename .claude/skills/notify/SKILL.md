---
name: notify
description: Надіслати ручне повідомлення в Telegram через tools/notify_telegram.py --dev.
disable-model-invocation: true
argument-hint: <текст>
allowed-tools: Bash(python3 tools/notify_telegram.py*)
---

`python3 tools/notify_telegram.py --dev "$ARGUMENTS"`. Якщо скрипт пише «Telegram не налаштовано» — скажи Андрієві, які змінні додати в `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`), значення не питай у чаті.
