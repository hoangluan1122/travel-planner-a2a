from __future__ import annotations

import json
import random
import string
import unicodedata
import uuid
from functools import lru_cache
from pathlib import Path

import httpx

from services.location_resolver import load_registry, resolve_location


CACHE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'bus_areas_live.json'
AREAS_V2_URL = 'https://internal-vroute-cmc.vexere.com/v2/area'
AREAS_V3_URL = 'https://internal-vroute-cmc.vexere.com/v3/area'
DEFAULT_HEADERS = {
    'Accept-Language': 'vi-VN',
    'User-Agent': 'travel-planner-a2a/1.0',
}

LIVE_BUS_AREA_OVERRIDES = {
    'Da Lat': '457',
    'Lam Dong': '457',
    'Vung Tau': '76',
    'Ba Ria Vung Tau': '76',
    'Can Tho': '13',
    'Ninh Binh': '42',
    'Tam Dao': '752',
    'Ha Long': '49',
    'Quang Ninh': '49',
}

MANUAL_BUS_HUB_BRIDGE = {
    'Nam Dinh': 'Ha Noi',
    'Ninh Binh': 'Ha Noi',
    'Hai Phong': 'Hai Phong',
    'Ha Long': 'Hai Phong',
    'Quang Ninh': 'Hai Phong',
    'Ha Giang': 'Ha Noi',
    'Cao Bang': 'Ha Noi',
    'Lao Cai': 'Ha Noi',
    'Sa Pa': 'Ha Noi',
    'Tam Dao': 'Ha Noi',
    'Bac Ninh': 'Ha Noi',
    'Hai Duong': 'Ha Noi',
    'Thai Binh': 'Ha Noi',
    'Thanh Hoa': 'Ha Noi',
    'Nghe An': 'Ha Noi',
    'Da Lat': 'Da Lat',
    'Lam Dong': 'Da Lat',
    'Nha Trang': 'Da Lat',
    'Khanh Hoa': 'Da Lat',
    'Quy Nhon': 'Hoi An',
    'Binh Dinh': 'Hoi An',
    'Mang Den': 'Hoi An',
    'Quang Nam': 'Hoi An',
    'Hue': 'Hue',
    'Quang Tri': 'Hue',
    'Da Nang': 'Da Nang',
    'Hoi An': 'Hoi An',
    'Ho Chi Minh': 'Ho Chi Minh',
    'Ben Tre': 'Ho Chi Minh',
    'Vung Tau': 'Vung Tau',
    'Ba Ria Vung Tau': 'Vung Tau',
    'Can Tho': 'Can Tho',
    'Kien Giang': 'Can Tho',
    'Phu Quoc': 'Can Tho',
    'Con Dao': 'Can Tho',
}


def _slugify(value: str) -> str:
    text = (value or '').strip().lower().replace('đ', 'd')
    text = unicodedata.normalize('NFD', text)
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    text = ' '.join(text.split())
    return text


def _guest_headers() -> dict:
    token = _guest_token()
    rid = 'FE_NEXTJS_' + str(uuid.uuid4()) + '_' + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(6))
    headers = {
        **DEFAULT_HEADERS,
        'origin-request-product': 'FE_NEXTJS',
        'origin-request-id': rid,
    }
    if token:
        headers['Authorization'] = f'bearer {token}'
    return headers


@lru_cache(maxsize=1)
def _guest_token() -> str:
    try:
        return httpx.post('https://vexere.com/getToken', timeout=6).json().get('access_token', '')
    except Exception:
        return ''


def _extract_items(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ('data', 'result', 'areas', 'items'):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def sync_bus_areas() -> list[dict]:
    merged: list[dict] = []
    for url in (AREAS_V2_URL, AREAS_V3_URL):
        try:
            payload = httpx.get(url, headers=_guest_headers(), params={'q': 'ha noi'}, timeout=25).json()
            merged.extend(_extract_items(payload))
        except Exception:
            continue

    normalized = []
    seen = set()
    for item in merged:
        area_id = str(item.get('id') or item.get('Id') or item.get('area_id') or '').strip()
        name = (item.get('name') or item.get('Name') or item.get('display_name') or '').strip()
        if not area_id or not name:
            continue
        slug = _slugify(name)
        key = (area_id, slug)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            'id': area_id,
            'name': name,
            'slug': slug,
            'province': item.get('province') or item.get('province_name') or '',
            'kind': item.get('type') or item.get('area_type') or item.get('level') or '',
        })

    CACHE_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding='utf-8')
    load_bus_areas.cache_clear()
    return normalized


@lru_cache(maxsize=1)
def load_bus_areas() -> list[dict]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return sync_bus_areas()


def _registry_lookup(name: str):
    slug = _slugify(name)
    for record in load_registry():
        if _slugify(record.name) == slug:
            return record
    return None


def _candidate_names(location: str) -> list[str]:
    resolved = resolve_location(location)
    record = _registry_lookup(resolved.canonical_name)
    manual_bridge = MANUAL_BUS_HUB_BRIDGE.get(resolved.canonical_name, '')
    names = [
        resolved.canonical_name,
        manual_bridge,
        resolved.nearest_bus_hub or '',
        resolved.nearest_train_hub or '',
        resolved.nearest_airport_hub or '',
        location,
    ]
    if record:
        names.extend(record.aliases)
    seen = set()
    out: list[str] = []
    for value in names:
        slug = _slugify(value)
        if slug and slug not in seen:
            seen.add(slug)
            out.append(value)
    return out


def _area_matches(item: dict, candidate_slug: str) -> bool:
    values = [
        item.get('name') or '',
        item.get('english_name') or '',
        item.get('full_name') or '',
        item.get('full_english_name') or '',
        item.get('city_name') or '',
        item.get('city_english_name') or '',
        item.get('state_name') or '',
        item.get('state_english_name') or '',
        item.get('code') or '',
    ]
    aliases = item.get('alias') or item.get('merged_areas') or []
    if isinstance(aliases, list):
        values.extend(str(alias) for alias in aliases)
    item_slugs = {_slugify(str(value)) for value in values if _slugify(str(value))}
    if candidate_slug in item_slugs:
        return True
    return any(candidate_slug and (candidate_slug in slug or slug in candidate_slug) for slug in item_slugs)


@lru_cache(maxsize=256)
def _live_resolve_bus_area_id(candidate_slug: str) -> str | None:
    if not candidate_slug:
        return None
    try:
        payload = httpx.get(
            AREAS_V2_URL,
            headers=_guest_headers(),
            params={'q': candidate_slug},
            timeout=6,
        ).json()
    except Exception:
        return None

    items = _extract_items(payload)
    if not items:
        return None

    for item in items:
        area_id = str(item.get('id') or item.get('Id') or item.get('area_id') or '').strip()
        if area_id and _area_matches(item, candidate_slug):
            return area_id

    first = items[0]
    return str(first.get('id') or first.get('Id') or first.get('area_id') or '').strip() or None


def _live_lookup(location: str) -> str | None:
    for name in _candidate_names(location):
        area_id = _live_resolve_bus_area_id(_slugify(name))
        if area_id:
            return area_id
    return None


def resolve_bus_area_id(location: str) -> str | None:
    resolved = resolve_location(location)
    if resolved.canonical_name in LIVE_BUS_AREA_OVERRIDES:
        return LIVE_BUS_AREA_OVERRIDES[resolved.canonical_name]
    live_area_id = _live_lookup(location)
    if live_area_id:
        return live_area_id
    if resolved.bus_area_id:
        return resolved.bus_area_id

    areas = load_bus_areas()
    if not areas:
        return None

    candidate_names = _candidate_names(location)
    candidate_slugs = [_slugify(x) for x in candidate_names if _slugify(x)]

    for slug in candidate_slugs:
        for item in areas:
            if item.get('slug') == slug:
                return item.get('id')

    for slug in candidate_slugs:
        for item in areas:
            area_slug = item.get('slug', '')
            province_slug = _slugify(item.get('province', ''))
            if slug and (slug in area_slug or area_slug in slug):
                return item.get('id')
            if province_slug and (slug == province_slug or slug in province_slug or province_slug in slug):
                return item.get('id')

    return None
