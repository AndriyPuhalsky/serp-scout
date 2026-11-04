"""Тести хуків харнесу (.claude/hooks/*.py) і скриптів tools/ на синтетичних даних.

Кожен хук запускається як окремий процес із JSON на stdin і CLAUDE_PROJECT_DIR, що вказує
на тимчасову копію мінімального проєкту (хуки й tools/ копіюються з реального) — так само,
як його запускає Claude Code. Змінні TELEGRAM_*/TG_* з оточення вирізаються, а TG_DRY_RUN=1
ставиться типово, щоб тести ніколи нічого не надсилали.
"""

import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK_NAMES = [
    "session_context.py",
    "guard_secrets.py",
    "guard_generated.py",
    "guard_outside.py",
    "post_edit_tests.py",
    "docs_lint.py",
    "journal_reminder.py",
    "notify_stop.py",
    "notify_attention.py",
]

# Секрети для тестів збираються конкатенацією, щоб guard_secrets не вважав цей файл витоком
ANTHROPIC_KEY = "sk-ant-" + "A" * 30
TELEGRAM_TOKEN = "12345678:" + "B" * 35
HEX64 = "a" * 64

MIN_DOCS = {
    "CLAUDE.md": "# serp-scout\n\n## Поточна ітерація\n\n▶ І1 — SERP + сховище\n\n## Правила\n\nтекст\n",
    "docs/04_РІШЕННЯ.md": (
        "# 04\n\n| № | Дата | Рішення |\n|---|---|---|\n"
        "| Р-001 | 2026-11-03 | a |\n| Р-002 | 2026-11-03 | b |\n"
    ),
    "docs/05_КАРТА_ІТЕРАЦІЙ.md": (
        "# 05\n\n## ✅ І0 — Харнес\n\n- [x] a\n\n"
        "## ▶ І1 — SERP + сховище\n\n- [x] b\n- [ ] c\n\n"
        "## ⬜ І2 — LLM\n\n- [ ] d\n"
    ),
    "ЖУРНАЛ_ПОДІЙ.md": (
        "# Журнал\n\n```\n### #NNN — РРРР-ММ-ДД — Назва\n```\n\n"
        "### #001 — 2026-11-03 — Старт\n**Тип:** інше\n\n"
        "### #002 — 2026-11-03 — Далі\n**Тип:** зміна\n"
    ),
    ".claude/settings.json": '{"permissions": {}}\n',
    ".claude/agents/demo-agent.md": "---\nname: demo-agent\ndescription: тест\n---\n\nтекст\n",
    ".claude/skills/demo/SKILL.md": "---\nname: demo\ndescription: тест\n---\n\nтекст\n",
}


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def make_project(d):
    for rel, text in MIN_DOCS.items():
        write(d, rel, text)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(
        os.path.join(ROOT, ".claude", "hooks"), os.path.join(d, ".claude", "hooks"), ignore=ignore
    )
    shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(d, "tools"), ignore=ignore)


def age_all(root, seconds=600):
    """Робить усі файли проєкту «старими», щоб журнал був не старіший за них."""
    old = time.time() - seconds
    for dirpath, _, files in os.walk(root):
        for f in files:
            os.utime(os.path.join(dirpath, f), (old, old))


def clean_env(root, extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TELEGRAM_", "TG_"))}
    env["CLAUDE_PROJECT_DIR"] = root
    env["TG_DRY_RUN"] = "1"
    env.update(extra or {})
    return env


@dataclass
class Result:
    code: int
    decision: dict | None
    out: str
    err: str


def run_hook(name, payload, root, env_extra=None):
    """Запускає копію хука з тимчасового проєкту; payload — словник або сирий рядок для stdin."""
    data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    r = subprocess.run(
        [sys.executable, os.path.join(root, ".claude", "hooks", name)],
        input=data,
        capture_output=True,
        text=True,
        env=clean_env(root, env_extra),
        cwd=root,
        timeout=120,
    )
    decision = None
    if r.stdout.strip():
        try:
            decision = json.loads(r.stdout)["hookSpecificOutput"]
        except (ValueError, KeyError, TypeError):
            decision = None
    return Result(r.returncode, decision, r.stdout, r.stderr)


def run_tool(name, args, root, env_extra=None):
    r = subprocess.run(
        [sys.executable, os.path.join(root, "tools", name), *args],
        capture_output=True,
        text=True,
        env=clean_env(root, env_extra),
        cwd=root,
        timeout=60,
    )
    return Result(r.returncode, None, r.stdout, r.stderr)


def write_payload(root, rel, content="x"):
    path = rel if os.path.isabs(rel) else os.path.join(root, rel)
    return {
        "tool_name": "Write",
        "session_id": "s1",
        "cwd": root,
        "hook_event_name": "PreToolUse",
        "tool_input": {"file_path": path, "content": content},
    }


def bash_payload(root, command):
    return {
        "tool_name": "Bash",
        "cwd": root,
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": command},
    }


def today_kyiv():
    from zoneinfo import ZoneInfo

    return dt.datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d")


@pytest.fixture
def proj(tmp_path):
    root = str(tmp_path)
    make_project(root)
    return root


# --- guard_secrets ------------------------------------------------------------------------------------


class TestGuardSecrets:
    def test_denies_anthropic_key(self, proj):
        r = run_hook("guard_secrets.py", write_payload(proj, "docs/x.md", f"key = {ANTHROPIC_KEY}"), proj)
        assert r.code == 0
        assert r.decision["permissionDecision"] == "deny"
        assert "Anthropic" in r.decision["permissionDecisionReason"]
        assert ANTHROPIC_KEY not in r.out

    def test_denies_telegram_token(self, proj):
        r = run_hook("guard_secrets.py", write_payload(proj, "src/x.py", f"TOKEN = '{TELEGRAM_TOKEN}'"), proj)
        assert r.decision["permissionDecision"] == "deny"
        assert "Telegram" in r.decision["permissionDecisionReason"]

    def test_denies_serpapi_hex_with_context(self, proj):
        r = run_hook("guard_secrets.py", write_payload(proj, "docs/x.md", f"SERPAPI_KEY={HEX64}\n"), proj)
        assert r.decision["permissionDecision"] == "deny"
        assert "SerpApi" in r.decision["permissionDecisionReason"]

    def test_allows_hex_with_sha256_or_without_context(self, proj):
        lock = f'[[package]]\nname = "serpapi"\nsdist = {{ hash = "sha256:{HEX64}" }}\n'
        assert run_hook("guard_secrets.py", write_payload(proj, "uv.lock", lock), proj).decision is None
        plain = write_payload(proj, "docs/x.md", f"digest {HEX64}")
        assert run_hook("guard_secrets.py", plain, proj).decision is None

    @pytest.mark.parametrize("rel", [".env", ".env.local", ".env.example"])
    def test_allows_env_files(self, proj, rel):
        r = run_hook("guard_secrets.py", write_payload(proj, rel, f"ANTHROPIC_API_KEY={ANTHROPIC_KEY}"), proj)
        assert (r.code, r.decision) == (0, None)

    def test_allows_plain_text_and_edit_without_secret(self, proj):
        note = write_payload(proj, "docs/x.md", "ANTHROPIC_API_KEY=... у .env")
        assert run_hook("guard_secrets.py", note, proj).decision is None
        edit = {
            "tool_name": "Edit",
            "cwd": proj,
            "tool_input": {"file_path": os.path.join(proj, "a.py"), "old_string": "x", "new_string": "y = 1"},
        }
        assert run_hook("guard_secrets.py", edit, proj).decision is None
        edit["tool_input"]["new_string"] = f"y = '{ANTHROPIC_KEY}'"
        assert run_hook("guard_secrets.py", edit, proj).decision["permissionDecision"] == "deny"

    def test_git_commit_checks_staged_lines_and_ignores_uv_lock(self, proj):
        subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@t",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "init",
            ],
            cwd=proj,
            check=True,
        )
        write(proj, "uv.lock", f'name = "serpapi"\nhash = "sha256:{HEX64}"\n')
        subprocess.run(["git", "add", "uv.lock"], cwd=proj, check=True)
        assert run_hook("guard_secrets.py", bash_payload(proj, "git commit -m x"), proj).decision is None
        write(proj, "notes.md", f"ключ: {ANTHROPIC_KEY}\n")
        subprocess.run(["git", "add", "notes.md"], cwd=proj, check=True)
        r = run_hook("guard_secrets.py", bash_payload(proj, "git commit -m x"), proj)
        assert r.decision["permissionDecision"] == "deny"
        assert "Anthropic" in r.decision["permissionDecisionReason"]
        assert run_hook("guard_secrets.py", bash_payload(proj, "git status"), proj).decision is None


# --- guard_generated ----------------------------------------------------------------------------------


class TestGuardGenerated:
    @pytest.mark.parametrize(
        "rel",
        [
            "site/data/report.json",
            "data/export/positions.csv",
            "data/serp.sqlite",
            "docs/10_ВАРТІСТЬ.md",
            "data/costs.jsonl",
        ],
    )
    def test_denies_generated_files(self, proj, rel):
        r = run_hook("guard_generated.py", write_payload(proj, rel), proj)
        assert r.code == 0
        assert r.decision["permissionDecision"] == "deny"
        assert "генерує" in r.decision["permissionDecisionReason"]

    @pytest.mark.parametrize(
        "rel",
        ["src/x.py", "site/js/app.js", "docs/09_ВІДЕО.md", "data/raw/2026-11-04/a.json", "site/index.html"],
    )
    def test_allows_source_files(self, proj, rel):
        r = run_hook("guard_generated.py", write_payload(proj, rel), proj)
        assert (r.code, r.decision) == (0, None)


# --- guard_outside ------------------------------------------------------------------------------------


class TestGuardOutside:
    def test_denies_outside_root(self, proj):
        r = run_hook("guard_outside.py", write_payload(proj, "/etc/x"), proj)
        assert r.code == 0
        assert r.decision["permissionDecision"] == "deny"
        assert "поза коренем" in r.decision["permissionDecisionReason"]
        parent = write_payload(proj, os.path.join(proj, "..", "other.txt"))
        assert run_hook("guard_outside.py", parent, proj).decision["permissionDecision"] == "deny"

    @pytest.mark.parametrize(
        "path",
        [
            "/private/tmp/claude-501/x/y.txt",
            "/tmp/claude/z.txt",
            os.path.expanduser("~/.claude/projects/x/memory/MEMORY.md"),
        ],
    )
    def test_allows_scratchpad_and_memory(self, proj, path):
        assert run_hook("guard_outside.py", write_payload(proj, path), proj).decision is None

    def test_allows_inside_root_including_relative(self, proj):
        inside = write_payload(proj, "src/serp_scout/cli.py")
        assert run_hook("guard_outside.py", inside, proj).decision is None
        payload = write_payload(proj, "x")
        payload["tool_input"]["file_path"] = "docs/новий.md"
        assert run_hook("guard_outside.py", payload, proj).decision is None

    def test_denies_git_dir(self, proj):
        r = run_hook("guard_outside.py", write_payload(proj, ".git/config"), proj)
        assert r.decision["permissionDecision"] == "deny"
        assert ".git" in r.decision["permissionDecisionReason"]


# --- journal_reminder ---------------------------------------------------------------------------------


class TestJournalReminder:
    def test_blocks_when_files_newer_than_journal(self, proj):
        age_all(proj)
        assert run_hook("journal_reminder.py", {"cwd": proj}, proj).code == 0
        with open(os.path.join(proj, "docs", "04_РІШЕННЯ.md"), "a", encoding="utf-8") as f:
            f.write("зміна\n")
        r = run_hook("journal_reminder.py", {"cwd": proj}, proj)
        assert r.code == 2
        assert "04_РІШЕННЯ.md" in r.err
        assert run_hook("journal_reminder.py", {"cwd": proj, "stop_hook_active": True}, proj).code == 0

    def test_skips_data_dirs_and_skip_files(self, proj):
        age_all(proj)
        for rel in (
            "data/raw/x.json",
            "site/data/report.json",
            ".venv/lib/x.py",
            ".claude/.state/m",
            "uv.lock",
            ".claude/settings.local.json",
        ):
            write(proj, rel, "x")
        assert run_hook("journal_reminder.py", {"cwd": proj}, proj).code == 0

    def test_requires_journal_file(self, proj):
        os.remove(os.path.join(proj, "ЖУРНАЛ_ПОДІЙ.md"))
        r = run_hook("journal_reminder.py", {"cwd": proj}, proj)
        assert r.code == 2
        assert "ЖУРНАЛ_ПОДІЙ.md" in r.err


# --- session_context ----------------------------------------------------------------------------------


class TestSessionContext:
    def test_context_has_deadline_iteration_env_names_and_journal(self, proj):
        write(proj, ".env", "SERPAPI_KEY=abc123xyz\nTELEGRAM_CHAT_ID=\n# коментар\nEXTRA_VAR='q'\n")
        write(proj, "data/costs.jsonl", '{"cost_usd": 0.1}\nпоганий рядок\n{"cost_usd": 0.023}\n')
        os.makedirs(os.path.join(proj, "data", "raw", today_kyiv()))
        r = run_hook("session_context.py", {"cwd": proj, "hook_event_name": "SessionStart"}, proj)
        assert r.code == 0
        ctx = r.decision["additionalContext"]
        assert r.decision["hookEventName"] == "SessionStart"
        assert "дедлайн" in ctx.lower() and ("лишилось" in ctx or "минув" in ctx)
        assert "▶ І1 — SERP + сховище" in ctx
        assert "1/2 зроблено" in ctx
        assert "SERPAPI_KEY: задано" in ctx
        assert "TELEGRAM_CHAT_ID: порожньо" in ctx
        assert "ANTHROPIC_API_KEY: не задано" in ctx
        assert "EXTRA_VAR" in ctx
        assert "abc123xyz" not in ctx and "'q'" not in ctx
        assert "$0.1230 за 2 записів" in ctx
        assert "снапшот" in ctx.lower() and ": є." in ctx
        assert "#002 — 2026-11-03 — Далі" in ctx

    def test_missing_env_and_section_are_reported_not_fatal(self, proj):
        write(proj, "CLAUDE.md", "# serp-scout\n\n## Правила\n\nтекст\n")
        r = run_hook("session_context.py", {"cwd": proj}, proj)
        ctx = r.decision["additionalContext"]
        assert r.code == 0
        assert ".env відсутній" in ctx
        assert "(розділ «Поточна ітерація» не знайдено)" in ctx
        assert "немає." in ctx  # снапшоту сьогодні немає
        assert "costs.jsonl відсутній" in ctx

    def test_snapshot_from_sqlite_runs(self, proj):
        db = os.path.join(proj, "data", "serp.sqlite")
        os.makedirs(os.path.dirname(db))
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE other (x)")
        con.commit()
        con.close()
        ctx = run_hook("session_context.py", {"cwd": proj}, proj).decision["additionalContext"]
        assert "снапшот SERP" in ctx and ": немає." in ctx  # таблиці runs ще немає — не падаємо
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, run_date TEXT)")
        con.execute("INSERT INTO runs (run_date) VALUES (?)", (today_kyiv() + "T09:00:00",))
        con.commit()
        con.close()
        ctx = run_hook("session_context.py", {"cwd": proj}, proj).decision["additionalContext"]
        assert f"({today_kyiv()}): є." in ctx


# --- tools/docs_lint.py -------------------------------------------------------------------------------


class TestDocsLintTool:
    def test_clean_project_passes(self, proj):
        r = run_tool("docs_lint.py", ["--check", "--root", proj], proj)
        assert r.code == 0
        assert "✓ документи узгоджені" in r.out
        assert "✗" not in r.out

    def test_two_current_iterations_fail(self, proj):
        write(proj, "docs/05_КАРТА_ІТЕРАЦІЙ.md", "# 05\n\n## ▶ І1 — a\n\n- [ ] x\n\n## ▶ І2 — b\n\n- [ ] y\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 1
        assert "✗ помилка" in r.out and "рівно один" in r.out

    def test_iteration_mismatch_fail(self, proj):
        write(proj, "CLAUDE.md", "# x\n\n## Поточна ітерація\n\n▶ І3 — Надійність\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 1
        assert "І3" in r.out and "І1" in r.out

    def test_duplicate_decision_fail(self, proj):
        with open(os.path.join(proj, "docs", "04_РІШЕННЯ.md"), "a", encoding="utf-8") as f:
            f.write("| Р-001 | 2026-11-04 | дубль |\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 1
        assert "Р-001" in r.out

    def test_readme_limits(self, proj):
        write(proj, "README.md", " ".join(["слово"] * 700) + "\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 1 and "700 слів" in r.out
        write(proj, "README.md", " ".join(["слово"] * 600) + "\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 0 and "⚠ попередження" in r.out and "600 слів" in r.out
        write(proj, "README.md", "\n".join(["рядок"] * 130) + "\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 1 and "130 рядків" in r.out

    def test_frontmatter_required(self, proj):
        write(proj, ".claude/agents/broken.md", "# без frontmatter\n")
        write(proj, ".claude/skills/noname/SKILL.md", "---\ndescription: лише опис\n---\n\nтекст\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 1
        assert "broken.md: немає YAML-frontmatter" in r.out
        assert "noname/SKILL.md: у frontmatter немає name" in r.out

    def test_missing_optional_files_are_warnings(self, proj):
        for rel in ("docs/04_РІШЕННЯ.md", "ЖУРНАЛ_ПОДІЙ.md", ".claude/settings.json"):
            os.remove(os.path.join(proj, rel))
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 0
        assert r.out.count("⚠ попередження") >= 3
        os.remove(os.path.join(proj, "CLAUDE.md"))
        assert run_tool("docs_lint.py", ["--root", proj], proj).code == 1

    def test_journal_numbering(self, proj):
        with open(os.path.join(proj, "ЖУРНАЛ_ПОДІЙ.md"), "a", encoding="utf-8") as f:
            f.write("\n### #002 — 2026-11-04 — Дубль\n")
        r = run_tool("docs_lint.py", ["--root", proj], proj)
        assert r.code == 1 and "#002" in r.out


# --- docs_lint hook -----------------------------------------------------------------------------------


class TestDocsLintHook:
    def test_denies_commit_when_docs_broken(self, proj):
        write(proj, "CLAUDE.md", "# x\n\n## Поточна ітерація\n\n▶ І5 — Інше\n")
        r = run_hook("docs_lint.py", bash_payload(proj, "git commit -m x"), proj)
        assert r.code == 0
        assert r.decision["permissionDecision"] == "deny"
        assert "І5" in r.decision["permissionDecisionReason"]

    def test_passes_clean_docs_and_ignores_other_commands(self, proj):
        assert run_hook("docs_lint.py", bash_payload(proj, "git commit -m x"), proj).decision is None
        write(proj, "CLAUDE.md", "# x\n\n## Поточна ітерація\n\n▶ І5 — Інше\n")
        assert run_hook("docs_lint.py", bash_payload(proj, "git status"), proj).decision is None
        heredoc = "cat > x.md <<'EOF'\n  run: git commit -m '[skip ci]'\nEOF\n"
        assert run_hook("docs_lint.py", bash_payload(proj, heredoc), proj).decision is None
        assert run_hook("docs_lint.py", bash_payload(proj, "uv run pytest && git commit -m x"), proj).decision


# --- post_edit_tests ----------------------------------------------------------------------------------


class TestPostEditTests:
    def test_ignores_unrelated_paths(self, proj):
        write(proj, "pyproject.toml", "[project]\nname = 'x'\nversion = '0'\n")
        payload = {
            "tool_name": "Write",
            "cwd": proj,
            "hook_event_name": "PostToolUse",
            "tool_input": {"file_path": os.path.join(proj, "docs", "x.md")},
            "tool_response": {},
        }
        r = run_hook("post_edit_tests.py", payload, proj)
        assert (r.code, r.err) == (0, "")
        payload["tool_input"]["file_path"] = os.path.join(proj, "site", "js", "app.js")
        assert run_hook("post_edit_tests.py", payload, proj).code == 0  # JS-тестів немає — пропуск

    def test_skips_everything_without_pyproject(self, proj):
        payload = {
            "tool_name": "Write",
            "cwd": proj,
            "tool_input": {"file_path": os.path.join(proj, "src", "serp_scout", "cli.py")},
        }
        r = run_hook("post_edit_tests.py", payload, proj)
        assert (r.code, r.err) == (0, "")


# --- tools/notify_telegram.py -------------------------------------------------------------------------


class TestNotifyTelegram:
    def test_dry_run_masks_escapes_and_prefixes(self, proj):
        text = f"тест <b> & токен {TELEGRAM_TOKEN} ключ {ANTHROPIC_KEY} SERPAPI_KEY={HEX64}"
        r = run_tool("notify_telegram.py", ["--dry-run", "--dev", text], proj)
        assert r.code == 0
        assert "[dry-run]" in r.out and "<b>🛠 serp-scout</b>" in r.out
        assert "&lt;b&gt; &amp;" in r.out
        for secret in (TELEGRAM_TOKEN, ANTHROPIC_KEY, HEX64):
            assert secret not in r.out
        assert r.out.count("***") == 3

    def test_dry_run_truncates_to_telegram_limit(self, proj):
        r = run_tool("notify_telegram.py", ["--dry-run", "--status", "ok", "--text", "слово " * 2000], proj)
        body = r.out.split("\n", 1)[1]
        assert len(body.encode("utf-16-le")) // 2 <= 4096
        assert body.startswith("<b>✅ Прогін serp-scout</b>") and body.rstrip().endswith("…")

    def test_without_credentials_exits_zero(self, proj):
        r = run_tool("notify_telegram.py", ["--dev", "x"], proj)
        assert r.code == 0
        assert "не налаштовано" in r.err and "TELEGRAM_BOT_TOKEN" in r.err

    def test_status_fail_from_text_file(self, proj):
        log = write(proj, "run.log", "Збій: SerpApi 429\n")
        r = run_tool("notify_telegram.py", ["--dry-run", "--status", "fail", "--text-file", log], proj)
        assert r.code == 0
        assert "<b>❌ Прогін serp-scout</b>\nЗбій: SerpApi 429" in r.out

    def test_bad_args_exit_zero(self, proj):
        r = run_tool("notify_telegram.py", [], proj)
        assert r.code == 0 and "notify_telegram" in r.err


# --- notify_stop / notify_attention -------------------------------------------------------------------


class TestNotifyStop:
    def test_disabled_by_tg_dev(self, proj):
        payload = {"cwd": proj, "last_assistant_message": "x"}
        r = run_hook("notify_stop.py", payload, proj, {"TG_DEV": "0"})
        assert (r.code, r.out) == (0, "")
        write(proj, ".env", "TG_DEV=0\n")
        r = run_hook("notify_stop.py", payload, proj)
        assert (r.code, r.out) == (0, "")

    def test_dry_run_prints_masked_text(self, proj):
        payload = {
            "cwd": proj,
            "stop_hook_active": False,
            "last_assistant_message": f"Готово, ключ {ANTHROPIC_KEY} збережено",
        }
        r = run_hook("notify_stop.py", payload, proj)
        assert r.code == 0
        assert "⏹ Сесія serp-scout: Готово, ключ *** збережено" in r.out
        assert ANTHROPIC_KEY not in r.out
        assert "(без тексту)" in run_hook("notify_stop.py", {"cwd": proj}, proj).out
        assert run_hook("notify_stop.py", dict(payload, stop_hook_active=True), proj).out == ""


class TestNotifyAttention:
    def test_disabled_by_tg_dev(self, proj):
        r = run_hook("notify_attention.py", {"cwd": proj, "message": "x"}, proj, {"TG_DEV": "0"})
        assert (r.code, r.out) == (0, "")

    def test_dry_run_prints_type_and_message(self, proj):
        payload = {
            "cwd": proj,
            "notification_type": "permission_prompt",
            "message": "Claude needs your permission",
        }
        r = run_hook("notify_attention.py", payload, proj)
        assert r.code == 0
        assert "⏸ Claude чекає на вас (permission_prompt): Claude needs your permission" in r.out


# --- стійкість до будь-якого входу --------------------------------------------------------------------


class TestRobustness:
    @pytest.mark.parametrize("name", HOOK_NAMES)
    def test_invalid_json_exits_zero(self, proj, name):
        assert run_hook(name, "це не json", proj).code == 0

    @pytest.mark.parametrize("name", HOOK_NAMES)
    def test_empty_object_exits_zero(self, proj, name):
        assert run_hook(name, {}, proj).code == 0
