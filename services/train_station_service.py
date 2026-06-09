from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path

from services.location_resolver import resolve_location


TRAIN_STATIONS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'train_stations_live.json'


SPECIAL_CITY_TO_STATION = {
    'Ha Noi': 'HNO',
    'Ho Chi Minh': 'SGO',
    'Da Nang': 'DNA',
    'Hue': 'HUE',
    'Nha Trang': 'NTR',
    'Ninh Binh': 'NBI',
    'Lao Cai': 'LCA',
    'Sa Pa': 'LCA',
}


def _slugify(value: str) -> str:
    text = (value or '').strip().lower().replace('đ', 'd')
    text = unicodedata.normalize('NFD', text)
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    text = ' '.join(text.split())
    return text


@lru_cache(maxsize=1)
def load_train_stations() -> list[dict]:
    if not TRAIN_STATIONS_PATH.exists():
        return []
    return json.loads(TRAIN_STATIONS_PATH.read_text(encoding='utf-8'))


def resolve_train_station_code(location: str) -> str | None:
    resolved = resolve_location(location)
    if resolved.train_station_code:
        return resolved.train_station_code

    canonical = resolved.canonical_name
    if canonical in SPECIAL_CITY_TO_STATION:
        return SPECIAL_CITY_TO_STATION[canonical]

    slug = _slugify(canonical)
    stations = load_train_stations()

    for station in stations:
        if _slugify(station.get('name', '')) == slug:
            return station.get('code')

    for station in stations:
        aliases = station.get('aliases') or []
        if slug in [_slugify(x) for x in aliases]:
            return station.get('code')

    for station in stations:
        station_slug = _slugify(station.get('name', ''))
        if slug and (slug in station_slug or station_slug in slug):
            return station.get('code')

    return None
