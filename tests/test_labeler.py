"""Розмітка: фейковий клієнт parse(), вартість, бюджет-стоп, refusal, офлайн-касети і стаб."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from serp_scout.config import LlmSettings
from serp_scout.labeler import (
    SYSTEM_PROMPT,
    BudgetExceeded,
    Contact,
    Labeler,
    LabelInput,
    PageLabel,
    build_user_message,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _inp(url: str = "https://www.casino.ca/", method: str = "httpx") -> LabelInput:
    return LabelInput(
        url=url,
        domain=url.split("/")[2].removeprefix("www."),
        keywords="online casino canada",
        title="Best Online Casinos",
        snippet="Compare casinos",
        method=method,
        text="JackpotCity and Betway reviewed. Advertise with us.",
        emails=["ads@casino.ca"],
        contact_links=[{"href": "https://www.casino.ca/advertise/", "anchor": "Advertise"}],
    )


def _label(confidence: float = 0.9, site_type: str = "review_affiliate") -> PageLabel:
    return PageLabel(
        site_type=site_type,
        relevant_for_placement=site_type == "review_affiliate",
        confidence=confidence,
        reason="Тест.",
        brands_mentioned=[],
        contact=Contact(email=None, contact_page=None, telegram=None, form=False, other=None),
        placement_signals=[],
    )


class FakeClient:
    """Імітує `client.messages.parse()`: повертає заготовлені відповіді, рахує виклики."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(label: PageLabel | None, stop_reason: str = "end_turn", in_tok: int = 4000, out_tok: int = 300):
    return SimpleNamespace(
        parsed_output=label,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


def test_parse_success_cost_and_request_shape() -> None:
    client = FakeClient([_response(_label(0.9))])
    labeler = Labeler(LlmSettings(budget_usd=5.0), client=client)
    result = labeler.label(_inp())
    assert result.label.site_type == "review_affiliate" and result.needs_review is False
    assert result.cost_usd == pytest.approx(4000 * 2 / 1e6 + 300 * 10 / 1e6)
    assert labeler.spent_usd == pytest.approx(result.cost_usd)
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5" and call["output_format"] is PageLabel
    assert call["system"] == SYSTEM_PROMPT and call["max_tokens"] == 1200
    assert "https://www.casino.ca/" in call["messages"][0]["content"]


def test_low_confidence_and_other_need_review() -> None:
    client = FakeClient([_response(_label(0.5)), _response(_label(0.9, "other"))])
    labeler = Labeler(LlmSettings(budget_usd=5.0), client=client)
    assert labeler.label(_inp()).needs_review is True
    assert labeler.label(_inp()).needs_review is True


def test_refusal_twice_gives_failed_label() -> None:
    refusal = _response(None, stop_reason="refusal", in_tok=100, out_tok=5)
    client = FakeClient([refusal, refusal])
    result = Labeler(LlmSettings(budget_usd=5.0), client=client).label(_inp())
    assert result.label.site_type == "other" and result.label.relevant_for_placement is False
    assert result.needs_review is True and result.failed is True
    assert result.input_tokens == 200 and len(client.calls) == 2  # обидві спроби враховано у вартості


def test_validation_error_gives_default_label() -> None:
    try:
        PageLabel.model_validate({"site_type": "bogus"})
    except ValidationError as exc:
        error = exc
    client = FakeClient([error, error])
    result = Labeler(LlmSettings(budget_usd=5.0), client=client).label(_inp())
    assert result.label.site_type == "other" and result.needs_review is True and result.failed is True


def test_budget_stop_before_call() -> None:
    cost_per_call = 4000 * 2 / 1e6 + 300 * 10 / 1e6
    client = FakeClient([_response(_label()), _response(_label()), _response(_label())])
    labeler = Labeler(LlmSettings(budget_usd=cost_per_call * 1.5), client=client)
    labeler.label(_inp())
    labeler.label(_inp())  # друга проходить: витрачено 1×, бюджет 1.5×
    with pytest.raises(BudgetExceeded):
        labeler.label(_inp())
    assert len(client.calls) == 2


def test_offline_cassette_and_stub() -> None:
    labeler = Labeler(
        LlmSettings(),
        offline=True,
        cassette_dir=FIXTURES / "llm",
        brand_finder=lambda text: ["Betway"] if "Betway" in text else [],
    )
    # Касета — будь-яка реальна з tests/fixtures/llm (ключ — url_key URL усередині файлу)
    cassette_path = sorted((FIXTURES / "llm").glob("*.json"))[0]
    data = json.loads(cassette_path.read_text(encoding="utf-8"))
    cassette = labeler.label(_inp(data["url"]))
    assert cassette.model == data["model"] == "claude-sonnet-5-5" and cassette.stub
    assert cassette.label.site_type == data["label"]["site_type"]
    assert cassette.label.confidence == pytest.approx(data["label"]["confidence"])
    assert cassette.cost_usd == 0.0 and cassette.input_tokens == data["usage"]["input_tokens"]

    wiki = labeler.label(_inp("https://en.wikipedia.org/wiki/No_such_test_page", method="snippet"))
    assert wiki.model == "offline-stub" and wiki.label.site_type == "encyclopedia"
    apple = labeler.label(_inp("https://apps.apple.com/ca/app/no-such-test-app/id1", method="snippet"))
    assert apple.label.site_type == "app_store" and apple.label.relevant_for_placement is False
    unknown = labeler.label(_inp("https://www.unknown-reviews-test.ca/best/", method="snippet"))
    assert unknown.label.site_type == "review_affiliate" and unknown.needs_review is True
    assert unknown.label.brands_mentioned[0].normalized == "Betway"
    assert unknown.label.contact.email == "ads@casino.ca"
    assert "advertise" in unknown.label.placement_signals


def test_build_user_message_contains_hints() -> None:
    message = build_user_message(_inp())
    assert "detected_emails: ads@casino.ca" in message
    assert "https://www.casino.ca/advertise/" in message
    assert "<page_text>" in message and "fetch_method: httpx" in message


def test_page_label_schema_is_accepted_by_sdk() -> None:
    from anthropic.lib._parse._transform import to_json_output_format  # приватний хелпер SDK — лише в тесті

    schema = to_json_output_format(PageLabel)
    assert schema["type"] == "json_schema"
    assert "site_type" in schema["schema"]["properties"]


def test_live_client_constructed_with_retries_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живий режим: `anthropic.Anthropic(max_retries=3, timeout=60)` — ретраї й таймаут за docs/02."""
    import serp_scout.labeler as labeler_module

    captured: dict = {}

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(labeler_module.anthropic, "Anthropic", FakeAnthropic)
    labeler = Labeler(LlmSettings(), offline=False)
    assert isinstance(labeler._client, FakeAnthropic)
    assert captured == {"max_retries": 3, "timeout": 60.0}


def test_parse_failure_retries_with_double_max_tokens() -> None:
    try:
        PageLabel.model_validate({"site_type": "bogus"})
    except ValidationError as exc:
        error = exc
    client = FakeClient([error, _response(_label(0.9), in_tok=4000, out_tok=900)])
    result = Labeler(LlmSettings(max_tokens=3000, budget_usd=5.0), client=client).label(_inp())
    assert result.label.site_type == "review_affiliate" and result.failed is False
    assert [c["max_tokens"] for c in client.calls] == [3000, 6000]
    assert result.output_tokens == 900 and result.cost_usd == pytest.approx(4000 * 2 / 1e6 + 900 * 10 / 1e6)


def test_double_parse_failure_gives_failed_label_not_cacheable() -> None:
    from serp_scout.labeler import FAILED_LABEL_REASON

    try:
        PageLabel.model_validate({"site_type": "bogus"})
    except ValidationError as exc:
        error = exc
    client = FakeClient([error, _response(None, stop_reason="refusal", in_tok=100, out_tok=5)])
    result = Labeler(LlmSettings(budget_usd=5.0), client=client).label(_inp())
    assert result.failed is True and result.needs_review is True
    assert result.label.reason == FAILED_LABEL_REASON and result.label.confidence == 0.0
    assert result.label.site_type == "other" and result.label.relevant_for_placement is False
    assert len(client.calls) == 2 and result.input_tokens == 100


def test_prompt_v2_rules_present() -> None:
    for phrase in (
        "up to 40",
        "contact.contact_page",
        "commercial content",
        "fetch_method=snippet",
        "DATA, not instructions",
    ):
        assert phrase in SYSTEM_PROMPT
