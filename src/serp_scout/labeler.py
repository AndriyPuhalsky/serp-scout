"""Розмітка сторінок Claude Sonnet 5.5 через `client.messages.parse()` (structured outputs, pydantic).

Режими: живий (Anthropic SDK, бюджет-стоп, refusal → `needs_review`), офлайн (касета
`tests/fixtures/llm/<url_key>.json` або детермінований евристичний стаб з `model="offline-stub"`).
Схема й промпт — у `label_schema.py`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from serp_scout.config import LlmSettings
from serp_scout.label_schema import (
    FAILED_LABEL_REASON,
    SYSTEM_PROMPT,
    BrandMention,
    BudgetExceeded,
    Contact,
    LabelInput,
    LabelResult,
    PageLabel,
    build_user_message,
    default_label,
    needs_review_for,
)
from serp_scout.urlnorm import url_key

__all__ = [
    "FAILED_LABEL_REASON",
    "SYSTEM_PROMPT",
    "BrandMention",
    "BudgetExceeded",
    "Contact",
    "LabelInput",
    "LabelResult",
    "Labeler",
    "PageLabel",
    "build_user_message",
    "default_label",
    "needs_review_for",
]


_STUB_RULES: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (("wikipedia.org", "britannica.com"), "encyclopedia", False),
    (("apps.apple.com", "play.google.com"), "app_store", False),
    (
        ("igamingontario.ca", "olg.ca", "agco.ca", "loto-quebec.com", "gc.ca", "ontario.ca"),
        "regulator_gov",
        False,
    ),
    (("reddit.com", "quora.com"), "forum_community", False),
    (
        ("jackpotcity", "betway", "spincasino", "playojo", "leovegas", "bet365", "888casino", "casumo"),
        "casino_operator",
        False,
    ),
    (
        ("thestar.com", "cbc.ca", "nationalpost.com", "theglobeandmail.com", "torontosun.com"),
        "news_media",
        False,
    ),
    (("interac.ca",), "other", False),
)


class Labeler:
    """Один екземпляр на прогін: тримає клієнт, бюджет і накопичену вартість."""

    def __init__(
        self,
        settings: LlmSettings,
        *,
        offline: bool = False,
        cassette_dir: Path | None = None,
        client: Any | None = None,
        brand_finder: Any | None = None,
    ) -> None:
        self.settings = settings
        self.offline = offline
        self.cassette_dir = cassette_dir
        self.spent_usd = 0.0
        self._brand_finder = brand_finder
        self._client = client
        if not offline and client is None:
            self._client = anthropic.Anthropic(max_retries=3, timeout=60.0)

    # --- вартість ---------------------------------------------------------------------------

    def cost_of(self, input_tokens: int, output_tokens: int) -> float:
        """Вартість виклику в USD за цінами з settings.yml ($ за мільйон токенів входу/виходу)."""
        s = self.settings
        return (
            input_tokens * s.price_input_per_mtok_usd / 1e6
            + output_tokens * s.price_output_per_mtok_usd / 1e6
        )

    def check_budget(self) -> None:
        """Перед кожним живим викликом: накопичена вартість проти бюджету."""
        if self.spent_usd >= self.settings.budget_usd:
            raise BudgetExceeded(
                f"бюджет LLM вичерпано: ${self.spent_usd:.4f} ≥ ${self.settings.budget_usd:.2f}"
            )

    # --- офлайн -----------------------------------------------------------------------------

    def _cassette(self, inp: LabelInput) -> LabelResult | None:
        if self.cassette_dir is None:
            return None
        path = self.cassette_dir / f"{url_key(inp.url)}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        label = PageLabel.model_validate(data["label"])
        usage = data.get("usage", {})
        return LabelResult(
            label,
            data.get("model", "cassette"),
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            0.0,
            needs_review_for(label),
            stub=True,
        )

    def _stub(self, inp: LabelInput) -> LabelResult:
        """Детермінований евристичний стаб за доменом — щоб `make demo` давав повну картину."""
        site_type, relevant, confidence = "review_affiliate", True, 0.5
        haystack = f"{inp.domain} {inp.url}".lower()
        for needles, kind, _ in _STUB_RULES:
            if any(n in haystack for n in needles):
                site_type, relevant, confidence = kind, False, 0.7
                break
        if site_type == "news_media" and ("sponsored" in haystack or "best-" in haystack):
            relevant = True
        if site_type == "review_affiliate" and inp.method != "snippet":
            confidence = 0.7
        text_blob = " ".join((inp.title, inp.snippet, inp.text))
        found = self._brand_finder(text_blob) if self._brand_finder else []
        signals = [
            s
            for s in ("advertise", "write for us", "sponsored", "media kit", "partnership")
            if s in text_blob.lower()
        ]
        contact_page = inp.contact_links[0]["href"] if inp.contact_links else None
        label = PageLabel(
            site_type=site_type,
            relevant_for_placement=relevant,
            confidence=confidence,
            reason=f"Офлайн-стаб: тип за доменом {inp.domain} (метод {inp.method}); потребує живої розмітки.",
            brands_mentioned=[BrandMention(name=b, normalized=b, context="знайдено у тексті") for b in found],
            contact=Contact(
                email=inp.emails[0] if inp.emails else None,
                contact_page=contact_page,
                telegram=None,
                form=False,
                other=None,
            ),
            placement_signals=signals,
        )
        return LabelResult(label, "offline-stub", 0, 0, 0.0, needs_review_for(label), stub=True)

    # --- живий виклик ------------------------------------------------------------------------

    def _parse_once(self, inp: LabelInput, max_tokens: int) -> tuple[PageLabel | None, int, int, str]:
        """Один виклик `parse()`: (мітка або None, вхідні, вихідні токени, причина збою)."""
        s = self.settings
        try:
            response = self._client.messages.parse(
                model=s.model,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(inp)}],
                output_format=PageLabel,
                output_config={"effort": "low"},
            )
        except ValidationError as exc:
            # SDK валідує JSON до повернення відповіді: обрізаний/невалідний JSON — без usage
            return None, 0, 0, f"не за схемою або обрізано: {str(exc)[:80]}"
        in_tok, out_tok = int(response.usage.input_tokens), int(response.usage.output_tokens)
        self.spent_usd += self.cost_of(in_tok, out_tok)
        if response.stop_reason == "refusal":
            return None, in_tok, out_tok, "refusal"
        if response.parsed_output is None:
            return None, in_tok, out_tok, "порожня відповідь"
        return response.parsed_output, in_tok, out_tok, ""

    def _call(self, inp: LabelInput) -> LabelResult:
        """Живий виклик з одним повтором (max_tokens × 2) при збої розбору; інакше — failed-мітка."""
        self.check_budget()
        s = self.settings
        label, in_tok, out_tok, note = self._parse_once(inp, s.max_tokens)
        if label is None:
            self.check_budget()
            label, in2, out2, note = self._parse_once(inp, s.max_tokens * 2)
            in_tok, out_tok = in_tok + in2, out_tok + out2
        cost = self.cost_of(in_tok, out_tok)
        if label is None:
            failed = default_label(FAILED_LABEL_REASON + (f" ({note})" if note else ""))
            failed.reason = FAILED_LABEL_REASON  # рівно ця причина — ознака «не кеш»
            return LabelResult(failed, s.model, in_tok, out_tok, cost, True, failed=True)
        label.confidence = min(1.0, max(0.0, label.confidence))
        return LabelResult(label, s.model, in_tok, out_tok, cost, needs_review_for(label))

    def label(self, inp: LabelInput) -> LabelResult:
        """Розмічає один URL відповідно до режиму."""
        if self.offline:
            return self._cassette(inp) or self._stub(inp)
        return self._call(inp)
