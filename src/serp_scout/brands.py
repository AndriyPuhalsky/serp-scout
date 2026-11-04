"""Нормалізація казино-брендів за `config/brands.yml`: пошук у тексті + зведення назв від LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def _fold(name: str) -> str:
    """Канонічне порівняння: нижній регістр, без пунктуації й зайвих пробілів."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


@dataclass
class BrandLexicon:
    """Канонічні назви → варіанти написання; індекс для швидкого зведення."""

    canonical: dict[str, list[str]]
    _index: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _patterns: list[tuple[str, re.Pattern[str]]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        for canon, variants in self.canonical.items():
            self._index[_fold(canon)] = canon
            for variant in variants:
                self._index[_fold(variant)] = canon
                # Варіанти з самих цифр («888») не шукаємо в тексті — забагато хибних збігів
                if variant.strip().isdigit():
                    continue
                escaped = re.escape(variant.strip()).replace(r"\ ", r"\s*")
                self._patterns.append(
                    (canon, re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE))
                )

    @classmethod
    def from_config(cls, brands: dict[str, list[str]]) -> BrandLexicon:
        """Будує лексикон із секції `brands` конфігу (`Settings.brands`)."""
        return cls(canonical={k: list(v) for k, v in brands.items()})

    def normalize(self, name: str) -> str:
        """Зводить назву від LLM до канонічної; невідомий бренд повертається очищеним як є."""
        folded = _fold(name)
        if not folded:
            return ""
        if folded in self._index:
            return self._index[folded]
        cleaned = " ".join(name.split()).strip()
        for suffix in (" online casino", " casino", " sportsbook"):
            if not folded.endswith(suffix):
                continue
            base = folded[: -len(suffix)]
            if base in self._index:
                return self._index[base]
            # Невідомий бренд: «Barz Casino» і «Barz» — одне й те саме, суфікс відкидаємо
            if base and cleaned.lower().endswith(suffix.strip()):
                cleaned = cleaned[: -len(suffix.strip())].rstrip()
            break
        return cleaned

    def find_in_text(self, text: str) -> list[str]:
        """Канонічні бренди, варіанти яких зустрічаються в тексті (порядок — за першим входженням)."""
        found: dict[str, int] = {}
        for canon, pattern in self._patterns:
            match = pattern.search(text)
            if match and (canon not in found or match.start() < found[canon]):
                found[canon] = match.start()
        return [canon for canon, _ in sorted(found.items(), key=lambda kv: kv[1])]

    def merge(self, llm_names: list[str], text: str = "") -> list[str]:
        """Об'єднує бренди від LLM (нормалізовані) з детермінованими знахідками в тексті, без дублів."""
        result: list[str] = []
        seen: set[str] = set()
        for name in [*(self.normalize(n) for n in llm_names), *self.find_in_text(text)]:
            key = _fold(name)
            if name and key not in seen:
                seen.add(key)
                result.append(name)
        return result
