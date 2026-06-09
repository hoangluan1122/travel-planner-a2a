from __future__ import annotations

import json
import math
import unicodedata
from functools import lru_cache
from pathlib import Path

import httpx
from pydantic import BaseModel, Field


class LocationRecord(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    iata: str | None = None
    train_station_code: str | None = None
    bus_area_id: str | None = None
    nearest_airport_hub: str | None = None
    nearest_train_hub: str | None = None
    nearest_bus_hub: str | None = None
    lat: float | None = None
    lon: float | None = None
    kind: str = "city"

    @property
    def all_aliases(self) -> list[str]:
        values = [self.name, *self.aliases]
        seen = set()
        out = []
        for value in values:
            slug = _slugify(value)
            if slug and slug not in seen:
                seen.add(slug)
                out.append(slug)
        return out


class ResolvedLocation(BaseModel):
    input_value: str
    canonical_name: str
    normalized_slug: str
    iata: str | None = None
    train_station_code: str | None = None
    bus_area_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    kind: str = "city"
    matched_by: str = "unknown"
    nearest_known_place: str | None = None
    nearest_airport_hub: str | None = None
    nearest_train_hub: str | None = None
    nearest_bus_hub: str | None = None


REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "vn_locations.json"

AIRPORT_WEIGHT_BY_KIND = {
    'city': 1.0,
    'province': 1.05,
    'town': 1.08,
    'landmark': 1.15,
    'island': 0.92,
}
TRAIN_WEIGHT_BY_KIND = {
    'city': 1.0,
    'province': 1.0,
    'town': 1.05,
    'landmark': 1.1,
    'island': 1.5,
}
BUS_WEIGHT_BY_KIND = {
    'city': 1.0,
    'province': 0.98,
    'town': 0.96,
    'landmark': 0.95,
    'island': 1.3,
}


def _slugify(value: str) -> str:
    text = (value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = " ".join(text.split())
    return text


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@lru_cache(maxsize=1)
def load_registry() -> list[LocationRecord]:
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return [LocationRecord(**item) for item in raw]


def _nearest_hub(lat: float | None, lon: float | None, predicate, weights: dict[str, float]) -> str | None:
    if lat is None or lon is None:
        return None
    best: tuple[float, LocationRecord] | None = None
    for record in load_registry():
        if record.lat is None or record.lon is None or not predicate(record):
            continue
        dist = _distance_km(lat, lon, record.lat, record.lon)
        score = dist * weights.get(record.kind, 1.0)
        if best is None or score < best[0]:
            best = (score, record)
    return best[1].name if best else None


def _enrich(record: LocationRecord, raw: str, slug: str, matched_by: str, nearest_known_place: str | None = None, lat: float | None = None, lon: float | None = None) -> ResolvedLocation:
    resolved_lat = lat if lat is not None else record.lat
    resolved_lon = lon if lon is not None else record.lon
    return ResolvedLocation(
        input_value=raw,
        canonical_name=record.name,
        normalized_slug=slug,
        iata=record.iata,
        train_station_code=record.train_station_code,
        bus_area_id=record.bus_area_id,
        lat=resolved_lat,
        lon=resolved_lon,
        kind=record.kind,
        matched_by=matched_by,
        nearest_known_place=nearest_known_place,
        nearest_airport_hub=record.nearest_airport_hub or _nearest_hub(resolved_lat, resolved_lon, lambda r: bool(r.iata), AIRPORT_WEIGHT_BY_KIND),
        nearest_train_hub=record.nearest_train_hub or _nearest_hub(resolved_lat, resolved_lon, lambda r: bool(r.train_station_code), TRAIN_WEIGHT_BY_KIND),
        nearest_bus_hub=record.nearest_bus_hub or _nearest_hub(resolved_lat, resolved_lon, lambda r: bool(r.bus_area_id), BUS_WEIGHT_BY_KIND),
    )


def _search_registry(raw: str, slug: str) -> ResolvedLocation | None:
    registry = load_registry()
    for record in registry:
        if slug == _slugify(record.name):
            return _enrich(record, raw, slug, "canonical")
    for record in registry:
        if record.iata and slug == record.iata.lower():
            return _enrich(record, raw, slug, "iata")
    for record in registry:
        if slug in record.all_aliases:
            return _enrich(record, raw, slug, "alias")
    for record in registry:
        record_slug = _slugify(record.name)
        if slug and (slug in record_slug or record_slug in slug):
            return _enrich(record, raw, slug, "fuzzy")
    return None


def _geocode_live(value: str) -> tuple[str, float, float] | None:
    query = value.strip()
    if not query:
        return None
    overrides = {
        'ho chi minh': 'Ho Chi Minh City, Vietnam',
        'ha noi': 'Hanoi, Vietnam',
        'da nang': 'Da Nang, Vietnam',
        'hue': 'Hue, Vietnam',
        'ninh binh': 'Ninh Binh, Vietnam',
        'ba na': 'Ba Na Hills, Da Nang, Vietnam',
        'mang den': 'Mang Den, Kon Tum, Vietnam',
        'tam dao': 'Tam Dao, Vinh Phuc, Vietnam',
        'con dao': 'Con Dao, Ba Ria Vung Tau, Vietnam',
    }
    query = overrides.get(_slugify(query), query)
    params = {'q': query, 'format': 'jsonv2', 'limit': 1, 'countrycodes': 'vn'}
    headers = {'User-Agent': 'travel-planner-a2a/1.0'}
    try:
        response = httpx.get('https://nominatim.openstreetmap.org/search', params=params, headers=headers, timeout=20)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return None
        item = rows[0]
        return item.get('display_name', query), float(item['lat']), float(item['lon'])
    except Exception:
        return None


def _nearest_registry_place(lat: float, lon: float) -> LocationRecord | None:
    best: tuple[float, LocationRecord] | None = None
    for record in load_registry():
        if record.lat is None or record.lon is None:
            continue
        dist = _distance_km(lat, lon, record.lat, record.lon)
        if best is None or dist < best[0]:
            best = (dist, record)
    return best[1] if best else None


def resolve_location(value: str | None) -> ResolvedLocation:
    raw = (value or "").strip()
    if not raw:
        default = load_registry()[2] if len(load_registry()) > 2 else LocationRecord(name='Da Nang')
        return _enrich(default, "", "da nang", "default")

    slug = _slugify(raw)
    direct = _search_registry(raw, slug)
    if direct:
        return direct

    geocoded = _geocode_live(raw)
    if geocoded:
        display_name, lat, lon = geocoded
        nearest = _nearest_registry_place(lat, lon)
        if nearest:
            return _enrich(nearest, raw, slug, "geocode-nearest", nearest.name, lat, lon)
        fallback = LocationRecord(name=display_name.split(',')[0].strip().title(), lat=lat, lon=lon)
        return _enrich(fallback, raw, slug, "geocode-only", None, lat, lon)

    fallback = LocationRecord(name=raw.strip().title())
    return _enrich(fallback, raw, slug, "passthrough")
