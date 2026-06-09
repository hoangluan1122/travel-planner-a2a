from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import httpx

from schemas.models import TravelPlan


PEXELS_URL = "https://api.pexels.com/v1/search"
WIKIMEDIA_COMMONS_URL = "https://commons.wikimedia.org/w/api.php"
FALLBACK_DESTINATION = "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1600&q=80"
FALLBACK_HOTEL = "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1200&q=80"
FALLBACK_ATTRACTION = "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1200&q=80"

DESTINATION_QUERY_HINTS = {
    "Da Nang": "Da Nang Vietnam beach skyline dragon bridge",
    "Da Lat": "Da Lat Vietnam mountain lake pine forest travel",
    "Ha Noi": "Ha Noi Vietnam old quarter hoan kiem travel",
    "Ho Chi Minh": "Ho Chi Minh City Vietnam skyline travel",
    "Hue": "Hue Vietnam imperial city travel",
    "Hoi An": "Hoi An Vietnam ancient town lantern travel",
    "Nha Trang": "Nha Trang Vietnam beach skyline travel",
    "Can Tho": "Can Tho Vietnam riverside floating market travel",
    "Vung Tau": "Vung Tau Vietnam beach coastal city travel",
}

HOTEL_AREA_HINTS = {
    "Da Nang": [
        "luxury hotel room Da Nang beach resort",
        "boutique hotel interior Da Nang",
        "modern hotel bedroom Da Nang Vietnam",
    ],
    "Da Lat": [
        "cozy hotel room Da Lat mountain view",
        "boutique stay Da Lat interior",
        "pine hill hotel Da Lat room",
    ],
    "Ha Noi": [
        "boutique hotel room Ha Noi old quarter",
        "luxury hotel Hanoi interior",
        "elegant hotel suite Hanoi",
    ],
}

ATTRACTION_TYPE_HINTS = {
    "beach": "beach coast tropical travel",
    "viewpoint": "mountain viewpoint panorama travel",
    "nature": "nature landscape travel",
    "history": "historic architecture travel",
    "culture": "cultural landmark travel",
    "museum": "museum architecture travel",
}

ATTRACTION_QUERY_HINTS = {
    "Đèo Hải Vân": "Hai Van Pass Da Nang Vietnam mountain road viewpoint",
    "Hai Van Pass": "Hai Van Pass Da Nang Vietnam mountain road viewpoint",
    "Mũi Đà Nẵng": "Da Nang peninsula coastline Son Tra Vietnam scenic cape",
    "Ban Co Peak": "Ban Co Peak Son Tra Da Nang Vietnam viewpoint",
    "Núi Sơn Trà": "Son Tra mountain Da Nang Vietnam forest viewpoint",
    "Thủy Sơn": "Marble Mountains Thuy Son Da Nang Vietnam cave temple",
    "Động Âm Phủ": "Am Phu Cave Marble Mountains Da Nang Vietnam cave temple",
    "Tam Dao Belvedere Resort": "Tam Dao resort mountain view Vietnam",
    "Tam Đảo": "Tam Dao Vinh Phuc Vietnam mountain town clouds",
    "Nhà thờ đá Tam Đảo": "Tam Dao stone church Vietnam mountain town",
    "Thác Bạc": "Thac Bac Tam Dao Vietnam waterfall forest",
    "Cầu Mây Tam Đảo": "Cau May Tam Dao Vietnam cloud bridge mountain view",
    "Thị trấn Tam Đảo": "Tam Dao town Vinh Phuc Vietnam mountain town",
    "Hồ Xuân Hương": "Xuan Huong Lake Da Lat Vietnam lakeside",
    "Langbiang": "Langbiang Da Lat Vietnam mountain viewpoint",
    "Ga Đà Lạt": "Da Lat Railway Station Vietnam yellow colonial architecture",
}


def _load_pexels_key() -> str | None:
    key = os.getenv("PEXELS_API_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("PEXELS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _load_serpapi_key() -> str | None:
    key = os.getenv("SERPAPI_KEY")
    if key:
        return key
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("SERPAPI_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


@lru_cache(maxsize=256)
def _pexels_search(query: str, fallback: str, per_page: int = 1) -> str:
    api_key = _load_pexels_key()
    if not api_key:
        return fallback
    headers = {"Authorization": api_key}
    params = {
        "query": query,
        "per_page": per_page,
        "orientation": "landscape",
        "size": "large",
    }
    try:
        with httpx.Client(timeout=5, headers=headers) as client:
            response = client.get(PEXELS_URL, params=params)
            response.raise_for_status()
            data = response.json()
        photos = data.get("photos", [])
        if not photos:
            return fallback
        src = photos[0].get("src", {})
        return src.get("landscape") or src.get("large") or src.get("medium") or fallback
    except Exception:
        return fallback


def _is_usable_image_url(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return lowered.startswith(("http://", "https://")) and not lowered.endswith(".svg")


@lru_cache(maxsize=256)
def _wikimedia_image_search(query: str, fallback: str) -> str:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": 6,
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": 1000,
        "format": "json",
        "origin": "*",
    }
    try:
        with httpx.Client(timeout=4, headers={"User-Agent": "TravelPlannerA2A/1.0 (local travel planning app; contact: dev@example.com)"}) as client:
            response = client.get(WIKIMEDIA_COMMONS_URL, params=params)
            response.raise_for_status()
            pages = (response.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            mime = info.get("mime") or ""
            url = info.get("thumburl") or info.get("url")
            if mime.startswith("image/") and _is_usable_image_url(url):
                return url
    except Exception:
        return fallback
    return fallback


@lru_cache(maxsize=256)
def _serpapi_image_search(query: str, fallback: str) -> str:
    api_key = _load_serpapi_key()
    if not api_key:
        return fallback
    params = {
        "engine": "google_images",
        "q": query,
        "gl": "vn",
        "hl": "vi",
        "ijn": "0",
        "api_key": api_key,
    }
    try:
        with httpx.Client(timeout=6, headers={"User-Agent": "travel-planner-a2a/1.0"}) as client:
            response = client.get("https://serpapi.com/search.json", params=params)
            response.raise_for_status()
            images = response.json().get("images_results") or []
        for item in images[:6]:
            url = item.get("original") or item.get("thumbnail")
            if _is_usable_image_url(url):
                return url
    except Exception:
        return fallback
    return fallback


def get_destination_image(destination: str) -> str:
    destination = (destination or "travel destination").strip()
    query = DESTINATION_QUERY_HINTS.get(destination, f"{destination} Vietnam travel landscape skyline")
    return _pexels_search(query, FALLBACK_DESTINATION)


def get_hotel_image(hotel_name: str, destination: str) -> str:
    destination = (destination or "travel").strip()
    original_name = (hotel_name or "hotel").strip()
    hotel_name = original_name.lower()

    serp_image = _serpapi_image_search(f"{original_name} {destination} hotel", FALLBACK_HOTEL)
    if serp_image != FALLBACK_HOTEL:
        return serp_image

    exact_query = f"{original_name} {destination} hotel exterior"
    exact_image = _pexels_search(exact_query, FALLBACK_HOTEL)
    if exact_image != FALLBACK_HOTEL:
        return exact_image

    city_hints = HOTEL_AREA_HINTS.get(destination, [])
    if any(word in hotel_name for word in ["beach", "sea", "coast", "resort"]):
        query = f"beach resort hotel room {destination}"
        return _pexels_search(query, FALLBACK_HOTEL)
    if any(word in hotel_name for word in ["boutique", "central", "old quarter", "comfort"]):
        query = f"boutique hotel room interior {destination}"
        return _pexels_search(query, FALLBACK_HOTEL)
    if city_hints:
        return _pexels_search(city_hints[0], FALLBACK_HOTEL)
    query = f"luxury hotel room interior {destination}"
    return _pexels_search(query, FALLBACK_HOTEL)


def get_attraction_image(attraction_name: str, destination: str) -> str:
    attraction_name = (attraction_name or "attraction").strip()
    destination = (destination or "travel").strip()

    direct_image = _wikimedia_image_search(f"{attraction_name} {destination} Vietnam", FALLBACK_ATTRACTION)
    if direct_image != FALLBACK_ATTRACTION:
        return direct_image

    serp_image = _serpapi_image_search(f"{attraction_name} {destination} Vietnam", FALLBACK_ATTRACTION)
    if serp_image != FALLBACK_ATTRACTION:
        return serp_image

    exact_query = ATTRACTION_QUERY_HINTS.get(attraction_name)
    if exact_query:
        image = _wikimedia_image_search(exact_query, FALLBACK_ATTRACTION)
        if image != FALLBACK_ATTRACTION:
            return image
        return _pexels_search(exact_query, FALLBACK_ATTRACTION)

    lower = attraction_name.lower()
    hint = "landmark travel"
    for key, value in ATTRACTION_TYPE_HINTS.items():
        if key in lower:
            hint = value
            break

    contextual_query = f"{attraction_name} {destination} Vietnam {hint}"
    image = _pexels_search(contextual_query, FALLBACK_ATTRACTION)
    if image != FALLBACK_ATTRACTION:
        return image

    fallback_query = f"{destination} Vietnam {hint}"
    return _pexels_search(fallback_query, FALLBACK_ATTRACTION)


def build_image_context(result: TravelPlan | None) -> dict:
    if not result:
        return {
            "destination_hero_image": FALLBACK_DESTINATION,
            "hotel_images": {},
            "attraction_images": {},
            "fallback_destination_image": FALLBACK_DESTINATION,
            "fallback_hotel_image": FALLBACK_HOTEL,
            "fallback_attraction_image": FALLBACK_ATTRACTION,
        }

    hotel_items = result.hotels
    attraction_items = result.attractions

    with ThreadPoolExecutor(max_workers=6) as executor:
        hero_future = executor.submit(get_destination_image, result.destination)
        hotel_futures = {
            hotel.title: executor.submit(get_hotel_image, hotel.title, result.destination)
            for hotel in hotel_items
            if not _is_usable_image_url(getattr(hotel, "image_url", ""))
        }
        attraction_futures = {
            item.title: executor.submit(get_attraction_image, item.title, result.destination)
            for item in attraction_items
            if not _is_usable_image_url(getattr(item, "image_url", ""))
        }

        try:
            destination_hero_image = hero_future.result(timeout=6)
        except Exception:
            destination_hero_image = FALLBACK_DESTINATION

        hotel_images = {
            hotel.title: hotel.image_url
            for hotel in hotel_items
            if _is_usable_image_url(getattr(hotel, "image_url", ""))
        }
        for title, future in hotel_futures.items():
            try:
                hotel_images[title] = future.result(timeout=4)
            except Exception:
                hotel_images[title] = FALLBACK_HOTEL

        attraction_images = {
            item.title: item.image_url
            for item in attraction_items
            if _is_usable_image_url(getattr(item, "image_url", ""))
        }
        for title, future in attraction_futures.items():
            try:
                attraction_images[title] = future.result(timeout=4)
            except Exception:
                attraction_images[title] = FALLBACK_ATTRACTION

    return {
        "destination_hero_image": destination_hero_image,
        "hotel_images": hotel_images,
        "attraction_images": attraction_images,
        "fallback_destination_image": FALLBACK_DESTINATION,
        "fallback_hotel_image": FALLBACK_HOTEL,
        "fallback_attraction_image": FALLBACK_ATTRACTION,
    }
