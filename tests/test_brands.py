"""Нормалізація брендів за config/brands.yml."""

from __future__ import annotations

from serp_scout.brands import BrandLexicon


def test_normalize_variants(settings) -> None:
    lex = BrandLexicon.from_config(settings.brands)
    assert lex.normalize("Jackpot City") == "JackpotCity"
    assert lex.normalize("jackpotcity casino") == "JackpotCity"
    assert lex.normalize("BET 365") == "bet365"
    assert lex.normalize("Leo Vegas") == "LeoVegas"
    assert lex.normalize("  Some New Brand ") == "Some New Brand"
    assert lex.normalize("") == ""


def test_find_in_text(settings) -> None:
    lex = BrandLexicon.from_config(settings.brands)
    found = lex.find_in_text("Play at Bet365, LeoVegas or Jackpot City. Bonus C$888 at 888 casino.")
    assert found == ["bet365", "LeoVegas", "JackpotCity", "888casino"]
    assert lex.find_in_text("Call 888-555 for help") == []  # «888» саме по собі не бренд


def test_merge_dedups_llm_and_text(settings) -> None:
    lex = BrandLexicon.from_config(settings.brands)
    merged = lex.merge(["Jackpot City", "Spin Casino", "jackpotcity"], "Betway and JackpotCity reviewed")
    assert merged == ["JackpotCity", "Spin Casino", "Betway"]


def test_unknown_brands_fold_casino_suffix_and_case(settings) -> None:
    lex = BrandLexicon.from_config(settings.brands)
    assert lex.normalize("Barz Casino") == "Barz"
    assert lex.normalize("BetVictor Online Casino") == "BetVictor"
    assert lex.normalize("Casino Days") == "Casino Days"  # відомий бренд зі словом Casino лишається
    assert lex.normalize("24Casino") == "24Casino"
    merged = lex.merge(["Beazt", "Beazt Casino", "BLUFFBET", "Bluffbet"], "")
    assert merged == ["Beazt", "BLUFFBET"]
