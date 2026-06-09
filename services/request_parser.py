from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

from schemas.models import UserRequest
from services.location_resolver import load_registry, resolve_location
from services.location_service import canonicalize_location, location_to_iata, slugify_location



INTEREST_MAP = {
    "cà phê": "coffee",
    "ca phe": "coffee",
    "coffee": "coffee",
    "uống cà phê": "coffee",
    "uong ca phe": "coffee",
    "chụp hình": "photo",
    "chụp ảnh": "photo",
    "chup hinh": "photo",
    "chup anh": "photo",
    "nhiếp ảnh": "photo",
    "photo": "photo",
    "đồ ăn": "food",
    "ẩm thực": "food",
    "do an": "food",
    "food": "food",
    "biển": "beach",
    "bien": "beach",
    "beach": "beach",
    "tam bien": "swimming",
    "bai tam": "swimming",
    "boi": "swimming",
    "choi nuoc": "swimming",
    "di bien": "beach",
    "swimming": "swimming",
    "lịch sử": "history",
    "lich su": "history",
    "history": "history",
    "thiên nhiên": "nature",
    "thien nhien": "nature",
    "nature": "nature",
    "nghỉ dưỡng": "relax",
    "resort": "relax",
    "shopping": "shopping",
    "mua sắm": "shopping",
    "culture": "culture",
    "văn hóa": "culture",
}


def _extract_departure_date(lowered: str) -> str:
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", lowered)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

    match = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", lowered)
    if match:
        d, m, y = match.groups()
        year = int(y) if y else datetime.now().year
        return f"{year:04d}-{int(m):02d}-{int(d):02d}"

    return ""


def _extract_days(lowered: str) -> int:
    normalized = _ascii_fold(lowered).lower()
    for pattern in [r"(\d+)\s*ngay", r"trong\s*(\d+)\s*ngay", r"(\d+)\s*days?"]:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            return int(match.group(1))
    patterns = [r"(\d+)\s*ngày", r"(\d+)\s*days?", r"trong\s*(\d+)\s*ngày"]
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 3


def _ascii_fold(text: str) -> str:
    text = (text or "").replace("đ", "d").replace("Đ", "D")
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def _ascii_fold(text: str) -> str:
    text = (text or "").translate(str.maketrans({"\u0111": "d", "\u0110": "D"}))
    text = text.replace("Ä‘", "d").replace("Ä", "D")
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def _budget_was_mentioned(text: str) -> bool:
    normalized = _ascii_fold(text).lower()
    return bool(re.search(
        r"(?:ngan\s*sach|budget|chi\s*phi|so\s*tien|tam|khoang|toi\s*da|max|\d+[\.,]?\d*\s*(?:tr|trieu|million|mil|m)\b)",
        normalized,
        re.IGNORECASE,
    ))


def _extract_budget(lowered: str) -> int:
    budget = 8_000_000
    normalized = _ascii_fold(lowered).lower()

    match = re.search(
        r"(?:ngan\s*sach|budget|chi\s*phi|so\s*tien|tam|khoang|toi\s*da|max)[^\d]{0,24}(\d+[\.,]?\d*)\s*(?:tr|trieu|million|mil|m)\b",
        normalized,
        re.IGNORECASE,
    )
    if match:
        return int(float(match.group(1).replace(",", ".")) * 1_000_000)

    match = re.search(r"(\d+[\.,]?\d*)\s*(?:tr|trieu|million|mil)\b", normalized, re.IGNORECASE)
    if match:
        return int(float(match.group(1).replace(",", ".")) * 1_000_000)
    match = re.search(r"(\d+[\.,]?\d*)\s*triệu", lowered, re.IGNORECASE)
    if match:
        return int(float(match.group(1).replace(",", ".")) * 1_000_000)

    match = re.search(r"(\d+[\.,]?\d*)\s*million", lowered, re.IGNORECASE)
    if match:
        return int(float(match.group(1).replace(",", ".")) * 1_000_000)

    match = re.search(r"(?:ngân sách|budget|số tiền)\s*(\d[\d\.,]*)", lowered, re.IGNORECASE)
    if match:
        raw = re.sub(r"[^\d]", "", match.group(1))
        if raw:
            if int(raw) < 1_000 and _budget_was_mentioned(lowered):
                return int(raw) * 1_000_000
            return int(raw)

    match = re.search(r"(?:ngan\s*sach|budget|chi\s*phi|so\s*tien)[^\d]{0,24}(\d[\d\.,]*)", normalized, re.IGNORECASE)
    if match:
        raw = re.sub(r"[^\d]", "", match.group(1))
        if raw:
            if int(raw) < 1_000:
                return int(raw) * 1_000_000
            return int(raw)

    return budget


def _extract_destination(lowered: str) -> str:
    normalized = _ascii_fold(lowered).lower()
    route_match = re.search(
        r"(?:tu|from)\s+[a-z0-9\s]+?\s+(?:toi|toi|den|to)\s+([a-z0-9\s]+?)(?:\s+\d+\s*(?:ngay|days?)|\s+voi|\s+ngan\s*sach|\s+budget|,|$)",
        normalized,
        re.IGNORECASE,
    )
    if route_match:
        candidate = route_match.group(1).strip()
        if candidate:
            return resolve_location(candidate).canonical_name

    marker_matches: list[tuple[int, int, str]] = []
    for record in load_registry():
        for name in [record.name, *record.aliases]:
            slug = _ascii_fold(name).lower()
            if not slug:
                continue
            match = re.search(
                rf"(?:di|den|du lich|tham quan|visit|to)\s+{re.escape(slug)}(?![a-z0-9])",
                normalized,
                re.IGNORECASE,
            )
            if match:
                marker_matches.append((match.start(), len(slug), record.name))
                break
    if marker_matches:
        marker_matches.sort(key=lambda item: (item[0], -item[1]))
        return marker_matches[0][2]

    for pattern in [
        r"(?:di|den|du lich|tham quan|visit|to)\s+([a-z0-9\s]+?)(?:\s+\d+\s*(?:ngay|days?)|\s+voi|\s+ngan\s*sach|\s+budget|,|$)",
        r"(?:o)\s+([a-z0-9\s]+?)(?:\s+\d+\s*(?:ngay|days?)|\s+voi|\s+ngan\s*sach|\s+budget|,|$)",
    ]:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return resolve_location(candidate).canonical_name

    known_matches: list[tuple[int, str]] = []
    for record in load_registry():
        for name in [record.name, *record.aliases]:
            slug = _ascii_fold(name).lower()
            if slug and re.search(rf"(?<![a-z0-9]){re.escape(slug)}(?![a-z0-9])", normalized):
                known_matches.append((len(slug), record.name))
                break
    if known_matches:
        known_matches.sort(reverse=True)
        return known_matches[0][1]
    patterns = [
        r"(?:đi|toi|tới|đến|den|du lịch|du lich|tham quan|visit|to)\s+([a-zà-ỹ\s]+?)(?:\s+\d+\s*(?:ngày|days?)|\s*,|$)",
        r"(?:ở|o)\s+([a-zà-ỹ\s]+?)(?:\s+\d+\s*(?:ngày|days?)|\s*,|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return resolve_location(candidate).canonical_name

    resolved_full_text = resolve_location(lowered.strip())
    return resolved_full_text.canonical_name


def _extract_origin_from_text(lowered: str) -> str:
    normalized = _ascii_fold(lowered).lower()
    origin_match = re.search(r"(?:xuat\s*phat\s*tu|khoi\s*hanh\s*tu|tu|from)\s+([a-z0-9\s]+?)(?:\s*(?:,|di|toi|i want|muon)|$)", normalized, re.IGNORECASE)
    if origin_match:
        resolved = resolve_location(origin_match.group(1).strip())
        return resolved.iata or resolved.canonical_name
    origin_match = re.search(r"(?:xuất phát từ|khoi hanh tu|from)\s+([a-zà-ỹ\s]+?)(?:\s*(?:,|đi|toi|i want|muốn)|$)", lowered, re.IGNORECASE)
    if origin_match:
        resolved = resolve_location(origin_match.group(1).strip())
        return resolved.iata or resolved.canonical_name
    return "SGN"


def _extract_travelers(lowered: str) -> int:
    normalized = _ascii_fold(lowered).lower()
    match = re.search(r"(\d+)\s*(nguoi|person|people)", normalized, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s*(người|nguoi|person|people)", lowered, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return 1


def _extract_guest_profile(lowered: str) -> dict:
    normalized = _ascii_fold(lowered).lower()
    adults = 0
    children = 0

    adult_match = re.search(r"(\d+)\s*(?:nguoi\s*lon|adult|adults)", normalized, re.IGNORECASE)
    if adult_match:
        adults = int(adult_match.group(1))

    child_match = re.search(r"(\d+)\s*(?:tre\s*em|em\s*be|be|child|children|kid|kids)", normalized, re.IGNORECASE)
    if child_match:
        children = int(child_match.group(1))

    travelers = _extract_travelers(lowered)
    if adults <= 0 and children <= 0:
        adults = travelers
    elif adults <= 0:
        adults = max(travelers - children, 1)

    child_ages: list[int] = []
    if children > 0:
        child_segment = ""
        segment_match = re.search(r"(?:tre\s*em|em\s*be|child|children|kid|kids)(.*)", normalized, re.IGNORECASE)
        if segment_match:
            child_segment = segment_match.group(1)
        age_segment_match = re.search(r"(?:tuoi\s*tre\s*em|child\s*ages?|children\s*ages?)(.*)", normalized, re.IGNORECASE)
        if age_segment_match:
            child_segment = age_segment_match.group(1)
        child_ages = [int(value) for value in re.findall(r"\b(\d{1,2})\b", child_segment)]
        child_ages = [age for age in child_ages if 0 <= age <= 17]
        if child_ages and child_ages[0] == children and len(child_ages) > children:
            child_ages = child_ages[1:]
        if len(child_ages) < children:
            child_ages.extend([7] * (children - len(child_ages)))
        child_ages = child_ages[:children]

    return {
        "adults": max(adults, 1),
        "children": max(children, 0),
        "child_ages": child_ages,
        "travelers": max(adults, 1) + max(children, 0),
    }


def _extract_preferred_transport(lowered: str) -> str:
    normalized = _ascii_fold(lowered).lower()
    transport_patterns = [
        ("flight", ("may bay", "flight", "plane", "bay")),
        ("train", ("tau hoa", "tau lua", "train", "rail")),
        ("bus", ("xe khach", "xe bus", "bus", "limousine")),
        ("car", ("oto", "o to", "xe rieng", "car", "private car")),
    ]
    preference_markers = (
        "muon di bang",
        "uu tien",
        "thich di",
        "phuong tien",
        "transport",
        "prefer",
        "di bang",
        "bang",
        "chon",
    )
    flexible_markers = ("linh hoat", "tu van", "mixed", "flexible")
    if any(marker in normalized for marker in flexible_markers):
        return ""
    for mode, keywords in transport_patterns:
        if any(keyword in normalized for keyword in keywords):
            if any(marker in normalized for marker in preference_markers):
                return mode
    return ""


def _extract_interests(lowered: str) -> list[str]:
    normalized = _ascii_fold(lowered).lower()
    interests: list[str] = []
    for key, value in INTEREST_MAP.items():
        key_normalized = _ascii_fold(key).lower()
        if (key in lowered or key_normalized in normalized) and value not in interests:
            interests.append(value)
    return interests


def _normalize_origin(origin: str | None) -> str:
    if not origin:
        return "SGN"
    cleaned = origin.strip()
    if not cleaned:
        return "SGN"
    if "(" in cleaned and ")" in cleaned:
        inside = cleaned.split("(")[-1].split(")")[0].strip().upper()
        if len(inside) == 3:
            return inside
    resolved = resolve_location(cleaned)
    if resolved.iata:
        return resolved.iata
    mapped = location_to_iata(cleaned)
    if mapped:
        return mapped
    if len(cleaned) == 3 and cleaned.isalpha():
        return cleaned.upper()
    return resolved.canonical_name


def _detect_lang(user_text: str) -> str:
    lowered = user_text.strip().lower()
    vi_markers = [
        "tôi", "toi", "muốn", "muon", "ngày", "ngay", "đi", "di ", "du lịch", "du lich",
        "ngân sách", "ngan sach", "người", "nguoi", "khởi hành", "khoi hanh", "từ", "tu ",
    ]
    if re.search(r"[à-ỹđ]", lowered) or any(marker in lowered for marker in vi_markers):
        return "vi"
    return "en"


def _fallback_parse(user_text: str, origin: str | None = None) -> UserRequest:
    lowered = user_text.strip().lower()
    resolved_origin = _normalize_origin(origin) if origin else _extract_origin_from_text(lowered)
    guest_profile = _extract_guest_profile(lowered)
    return UserRequest(
        destination=resolve_location(_extract_destination(lowered)).canonical_name,
        origin=resolved_origin,
        lang=_detect_lang(user_text),
        departure_date=_extract_departure_date(lowered),
        preferred_transport=_extract_preferred_transport(lowered),
        days=_extract_days(lowered),
        budget=_extract_budget(lowered),
        interests=_extract_interests(lowered),
        travelers=guest_profile["travelers"],
        adults=guest_profile["adults"],
        children=guest_profile["children"],
        child_ages=guest_profile["child_ages"],
    )


def parse_user_request(user_text: str, origin: str | None = None) -> UserRequest:
    deterministic = _fallback_parse(user_text, origin=origin)
    if _detect_lang(user_text) == "vi" and deterministic.destination:
        return deterministic

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return deterministic

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt = f"""Extract a structured travel request from this user input.
Return JSON only with keys: destination, origin, departure_date, preferred_transport, days, budget, interests, travelers, adults, children, child_ages, lang.
- destination: short city/place name string
- origin: airport code or departure city if present, otherwise SGN
- departure_date: YYYY-MM-DD if present, otherwise empty string
- preferred_transport: one of flight, train, bus, car, mixed, or empty string
- days: integer
- budget: integer VND
- interests: array of short English tags like coffee, photo, food, beach, history, nature, culture, relax, shopping
- travelers: integer total guests
- adults: integer adult guests
- children: integer child guests
- child_ages: array of child ages, use 7 for each child when age is not stated
- lang: "vi" or "en" based on the user's input language

User input:
{user_text}
"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You extract travel planning fields and output strict JSON only. Never add markdown fences."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        content = (response.choices[0].message.content or "").strip()
        content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data: dict[str, Any] = json.loads(content)
        origin_raw = origin or str(data.get("origin") or "SGN").strip()
        origin_normalized = _normalize_origin(origin_raw)
        destination_resolved = resolve_location(str(data.get("destination") or deterministic.destination or "Da Nang").strip())
        lang = str(data.get("lang") or "").strip().lower()
        if lang not in {"vi", "en"}:
            lang = _detect_lang(user_text)
        parsed_budget = int(data.get("budget") or 8_000_000)
        if _budget_was_mentioned(user_text):
            parsed_budget = _extract_budget(user_text.strip().lower())
        adults = int(data.get("adults") or deterministic.adults)
        children = int(data.get("children") or deterministic.children)
        child_ages = [int(x) for x in (data.get("child_ages") or deterministic.child_ages or []) if str(x).strip().isdigit()]
        if len(child_ages) < children:
            child_ages.extend([7] * (children - len(child_ages)))
        return UserRequest(
            destination=deterministic.destination or destination_resolved.canonical_name,
            origin=origin_normalized,
            lang=lang,
            departure_date=str(data.get("departure_date") or "").strip(),
            preferred_transport=deterministic.preferred_transport or str(data.get("preferred_transport") or "").strip().lower(),
            days=deterministic.days,
            budget=parsed_budget,
            interests=[str(x).strip() for x in (data.get("interests") or []) if str(x).strip()],
            travelers=adults + children,
            adults=adults,
            children=children,
            child_ages=child_ages[:children],
        )
    except Exception:
        return _fallback_parse(user_text, origin=origin)
