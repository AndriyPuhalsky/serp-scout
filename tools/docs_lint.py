#!/usr/bin/env python3
"""Детерміновані перевірки узгодженості документів serp-scout (хук docs_lint, `make lint`).

Запуск: python3 tools/docs_lint.py [--check] [--root ШЛЯХ]
Код виходу 1 — є помилки. Попередження не блокують.

Перевірки:
  1. CLAUDE.md існує; у розділі «## Поточна ітерація» є рядок «▶ ІN — …» (немає розділу — попередження).
  2. docs/05_КАРТА_ІТЕРАЦІЙ.md: рівно один заголовок «## ▶ ІN — …», і це та сама N, що в CLAUDE.md.
  3. docs/04_РІШЕННЯ.md: номери Р-NNN без дублів (не зростають — попередження).
  4. ЖУРНАЛ_ПОДІЙ.md: номери #NNN без дублів і строго зростають
     (файл поза git — у клоні на GitHub Actions його немає, це лише попередження).
  5. .claude/agents/*.md і .claude/skills/*/SKILL.md: frontmatter між --- з name і description.
  6. .claude/settings.json — валідний JSON.
  7. README.md ≤ 1 сторінка: ≤ 650 слів (попередження від 550) і ≤ 120 рядків.
Файлів, яких ще немає, лінт не вимагає (попередження), крім CLAUDE.md.
"""
import argparse
import glob
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITER_RE = re.compile(r"[ІI](\d+)")
README_WORDS_MAX, README_WORDS_WARN, README_LINES_MAX = 650, 550, 120


def nfc(s):
    return unicodedata.normalize("NFC", s or "")


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return nfc(f.read())
    except OSError:
        return None


def check_iteration(root, errors, warnings):
    """CLAUDE.md «## Поточна ітерація» ↔ docs/05 «## ▶ ІN»."""
    claude = read(os.path.join(root, "CLAUDE.md"))
    if claude is None:
        errors.append("CLAUDE.md відсутній у корені проєкту")
        return
    current = None
    m = re.search(r"(?ms)^## Поточна ітерація\s*\n(.+?)(?=^## |\Z)", claude)
    if not m:
        warnings.append("CLAUDE.md: розділу «## Поточна ітерація» ще немає")
    else:
        line = next((ln for ln in m.group(1).splitlines() if "▶" in ln), None)
        num = ITER_RE.search(line) if line else None
        if not num:
            errors.append("CLAUDE.md: у розділі «Поточна ітерація» немає рядка «▶ ІN — …»")
        else:
            current = num.group(1)
    plan = read(os.path.join(root, "docs", "05_КАРТА_ІТЕРАЦІЙ.md"))
    if plan is None:
        warnings.append("docs/05_КАРТА_ІТЕРАЦІЙ.md ще немає")
        return
    marks = re.findall(r"^##\s*▶\s*(.*)$", plan, re.M)
    if len(marks) != 1:
        errors.append(f"docs/05: заголовків «## ▶ …» має бути рівно один, знайдено {len(marks)}")
        return
    num = ITER_RE.search(marks[0])
    if not num:
        errors.append(f"docs/05: у заголовку «## ▶ {marks[0].strip()}» немає номера ітерації ІN")
    elif current is not None and num.group(1) != current:
        errors.append(f"Ітерація в CLAUDE.md (І{current}) ≠ ▶ у docs/05 (І{num.group(1)})")


def check_decisions(root, errors, warnings):
    text = read(os.path.join(root, "docs", "04_РІШЕННЯ.md"))
    if text is None:
        warnings.append("docs/04_РІШЕННЯ.md ще немає")
        return
    nums = [int(n) for n in re.findall(r"^\|\s*Р-(\d{3})\s*\|", text, re.M)]
    dups = sorted({n for n in nums if nums.count(n) > 1})
    if dups:
        errors.append("docs/04: номери рішень повторюються: " + ", ".join(f"Р-{n:03d}" for n in dups))
    if nums != sorted(nums):
        warnings.append("docs/04: номери Р-NNN ідуть не за зростанням")


def check_journal(root, errors, warnings):
    text = read(os.path.join(root, "ЖУРНАЛ_ПОДІЙ.md"))
    if text is None:
        warnings.append("ЖУРНАЛ_ПОДІЙ.md немає (файл поза git — у клоні це нормально)")
        return
    nums = [int(n) for n in re.findall(r"^### #(\d{3})\s+—", text, re.M)]
    dups = sorted({n for n in nums if nums.count(n) > 1})
    if dups:
        errors.append("ЖУРНАЛ_ПОДІЙ.md: номери записів повторюються: " + ", ".join(f"#{n:03d}" for n in dups))
    for a, b in zip(nums, nums[1:], strict=False):
        if b <= a:
            errors.append(f"ЖУРНАЛ_ПОДІЙ.md: після #{a:03d} іде #{b:03d} — номери мають зростати")
            break


def frontmatter(text):
    m = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    return m.group(1) if m else None


def check_frontmatter(root, errors, warnings):
    agents = sorted(glob.glob(os.path.join(root, ".claude", "agents", "*.md")))
    skills = sorted(glob.glob(os.path.join(root, ".claude", "skills", "*", "SKILL.md")))
    for path in agents + skills:
        rel = nfc(os.path.relpath(path, root))
        fm = frontmatter(read(path) or "")
        if fm is None:
            errors.append(f"{rel}: немає YAML-frontmatter між ---")
            continue
        name = re.search(r"^name:\s*(\S.*)$", fm, re.M)
        if not name:
            errors.append(f"{rel}: у frontmatter немає name")
        if not re.search(r"^description:\s*\S", fm, re.M):
            errors.append(f"{rel}: у frontmatter немає description")
        expected = (os.path.basename(os.path.dirname(path)) if path in skills
                    else os.path.splitext(os.path.basename(path))[0])
        if name and name.group(1).strip().strip("\"'") != nfc(expected):
            warnings.append(f"{rel}: name «{name.group(1).strip()}» ≠ «{expected}» (ім'я файлу/теки)")


def check_settings(root, errors, warnings):
    path = os.path.join(root, ".claude", "settings.json")
    if not os.path.isfile(path):
        warnings.append(".claude/settings.json ще немає")
        return
    try:
        with open(path, encoding="utf-8") as f:
            json.load(f)
    except (OSError, ValueError) as e:
        errors.append(f".claude/settings.json: невалідний JSON ({e})")


def check_readme(root, errors, warnings):
    text = read(os.path.join(root, "README.md"))
    if text is None:
        warnings.append("README.md ще немає")
        return
    words = len(text.split())
    lines = len(text.splitlines())
    if words > README_WORDS_MAX:
        errors.append(f"README.md: {words} слів — більше за ліміт {README_WORDS_MAX} (1 сторінка)")
    elif words > README_WORDS_WARN:
        warnings.append(f"README.md: {words} слів — наближається до ліміту {README_WORDS_MAX}")
    if lines > README_LINES_MAX:
        errors.append(f"README.md: {lines} рядків — більше за ліміт {README_LINES_MAX}")


def run(root):
    errors, warnings = [], []
    checks = (check_iteration, check_decisions, check_journal, check_frontmatter, check_settings,
              check_readme)
    for check in checks:
        check(root, errors, warnings)
    return errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="режим перевірки (типовий; для сумісності з make lint)")
    ap.add_argument("--root", default=ROOT, help="корінь проєкту")
    args = ap.parse_args(argv)
    errors, warnings = run(args.root)
    for w in warnings:
        print(f"⚠ попередження: {w}")
    for e in errors:
        print(f"✗ помилка: {e}")
    if errors:
        print(f"✗ docs_lint: помилок {len(errors)}, попереджень {len(warnings)} — виправ перед комітом")
        return 1
    print(f"✓ документи узгоджені (попереджень: {len(warnings)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
