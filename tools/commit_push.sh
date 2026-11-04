#!/usr/bin/env bash
# Коміт і push результатів щоденного прогону: data/serp.sqlite, data/costs.jsonl, data/export, site/data.
# Викликається з .github/workflows/daily.yml; працює й локально (тоді ідентичність git не чіпаємо).
#
# Змінні оточення (усі необов'язкові):
#   BRANCH        — гілка призначення, типово main
#   COMMIT_SUFFIX — хвіст повідомлення коміту, типово порожній.
#                   УВАГА: «[skip ci]» тут НЕ ставимо навмисно — Netlify пропускає деплой, якщо в повідомленні
#                   є «[skip ci]» або «[skip netlify]», а push у main і є тригером деплою сайту. Для GitHub
#                   тег не потрібен: daily.yml не слухає push. Якщо колись з'явиться workflow на push і його
#                   треба глушити — задати COMMIT_SUFFIX=" [skip ci]" свідомо й перевірити деплой.
set -euo pipefail

BRANCH="${BRANCH:-main}"
COMMIT_SUFFIX="${COMMIT_SUFFIX:-}"
ATTEMPTS=3
PAUSE_SEC=5

cd "$(git rev-parse --show-toplevel)"

# У GitHub Actions комітимо від бота; локально лишаємо налаштування користувача.
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  git config user.name "github-actions[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
fi

# Додаємо лише ті шляхи, що існують (на першому прогоні export чи site/data можуть бути ще порожні).
# data/costs.jsonl — у git з 3807fb4, прогін дописує в нього рядки: без нього тут лишалась незастейджена
# зміна і `git pull --rebase` відмовлявся (інцидент run 41829818030).
TO_ADD=()
for path in data/serp.sqlite data/costs.jsonl data/export site/data; do
  if [ -e "$path" ]; then
    TO_ADD+=("$path")
  fi
done
if [ "${#TO_ADD[@]}" -eq 0 ]; then
  echo "Нічого комітити: жодного з шляхів data/serp.sqlite, data/costs.jsonl, data/export, site/data не існує"
  exit 0
fi
git add -- "${TO_ADD[@]}"

if git diff --cached --quiet; then
  echo "Нічого комітити: дані не змінилися"
  exit 0
fi

MESSAGE="Щоденний прогін $(date -u +%F)${COMMIT_SUFFIX}"
git commit -m "$MESSAGE"
echo "Коміт: $MESSAGE"

# Push із rebase: поки прогін тривав, у main міг з'явитися ручний коміт — підтягуємо його й пробуємо ще.
# Rebase потребує повної історії (у daily.yml checkout з fetch-depth: 0).
# --autostash: будь-який незакомічений залишок (новий файл, що його прогін почав змінювати, а TO_ADD ще не знає)
# ховається на час rebase і повертається після, замість «cannot pull with rebase: You have unstaged changes».
for attempt in $(seq 1 "$ATTEMPTS"); do
  echo "Push у $BRANCH, спроба $attempt/$ATTEMPTS"
  if git pull --rebase --autostash origin "$BRANCH" && git push origin "HEAD:$BRANCH"; then
    echo "Запушено в $BRANCH"
    exit 0
  fi
  # Невдалий rebase лишає репозиторій у стані конфлікту — відкотити перед новою спробою.
  if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; then
    git rebase --abort || true
  fi
  if [ "$attempt" -lt "$ATTEMPTS" ]; then
    sleep "$PAUSE_SEC"
  fi
done

echo "Не вдалося запушити в $BRANCH за $ATTEMPTS спроби — див. docs/06_RUNBOOK.md «Інциденти»" >&2
exit 1
