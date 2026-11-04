"""Провайдери SERP: живий SerpApi і офлайн-фікстури в тому ж форматі."""

from serp_scout.providers.base import SerpError, SerpHit, SerpProvider, hits_from_serpapi

__all__ = ["SerpError", "SerpHit", "SerpProvider", "hits_from_serpapi"]
