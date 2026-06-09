from __future__ import annotations

import unicodedata

from services.location_resolver import resolve_location


def slugify_location(value: str) -> str:
    text = (value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = " ".join(text.split())
    return text


def canonicalize_location(value: str) -> str:
    return resolve_location(value).canonical_name


def location_to_iata(value: str) -> str | None:
    return resolve_location(value).iata
