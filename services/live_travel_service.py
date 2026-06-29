from __future__ import annotations

import os
import math
import unicodedata
from datetime import date, timedelta
from pathlib import Path

import httpx

from services.location_resolver import resolve_location
from services.location_service import canonicalize_location, location_to_iata


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_URLS = [
    OVERPASS_URL,
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
REVERSE_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
SERPAPI_FLIGHTS_URL = "https://serpapi.com/search.json"
GEOAPIFY_PLACES_URL = "https://api.geoapify.com/v2/places"
RAPIDAPI_BASE_URL = "https://booking-com15.p.rapidapi.com/api/v1"
REQUEST_TIMEOUT_FAST = 8
REQUEST_TIMEOUT_MEDIUM = 12
REQUEST_TIMEOUT_SLOW = 18

CURATED_ACTIVITY_ATTRACTIONS = {
    "da nang": [
        {
            "name": "My Khe Beach",
            "type": "outdoor",
            "interest_tags": ["beach", "swimming", "photo", "relax", "nature"],
            "cost": 0,
            "source": "Curated Da Nang attractions",
            "area": "My Khe",
            "lat": 16.0617,
            "lon": 108.2468,
            "suitability": "Wide public beach suitable for swimming, sunrise walks, and easy cafe access.",
        },
        {
            "name": "Non Nuoc Beach",
            "type": "outdoor",
            "interest_tags": ["beach", "swimming", "resort", "photo", "relax"],
            "cost": 0,
            "source": "Curated Da Nang attractions",
            "area": "Ngu Hanh Son",
            "lat": 16.0008,
            "lon": 108.2682,
            "suitability": "Long beach area near resorts and Marble Mountains, suitable for a lighter schedule.",
        },
        {
            "name": "Son Tra Peninsula",
            "type": "outdoor",
            "interest_tags": ["nature", "photo", "viewpoint", "beach"],
            "cost": 0,
            "source": "Curated Da Nang attractions",
            "area": "Son Tra",
            "lat": 16.1184,
            "lon": 108.2734,
            "suitability": "Scenic coastal drive with viewpoints and nature stops; good when weather is clear.",
        },
        {
            "name": "Marble Mountains",
            "type": "outdoor",
            "interest_tags": ["nature", "photo", "culture", "cave"],
            "cost": 40000,
            "source": "Curated Da Nang attractions",
            "area": "Ngu Hanh Son",
            "lat": 15.9955,
            "lon": 108.2588,
            "suitability": "Signature cave and viewpoint experience close to Non Nuoc Beach.",
        },
        {
            "name": "An Thuong Cafe Quarter",
            "type": "indoor",
            "interest_tags": ["coffee", "cafe", "food", "relax", "photo"],
            "cost": 0,
            "source": "Curated Da Nang attractions",
            "area": "An Thuong",
            "lat": 16.0485,
            "lon": 108.2446,
            "suitability": "Cafe and dining cluster near My Khe, useful for rainy or relaxed time blocks.",
        },
        {
            "name": "Dragon Bridge Riverside",
            "type": "outdoor",
            "interest_tags": ["photo", "culture", "city_walk", "night"],
            "cost": 0,
            "source": "Curated Da Nang attractions",
            "area": "Hai Chau",
            "lat": 16.0611,
            "lon": 108.2278,
            "suitability": "Easy evening city walk and photo stop along the Han River.",
        },
    ],
    "ha long": [
        {
            "name": "Bai Chay Beach",
            "type": "outdoor",
            "interest_tags": ["beach", "swimming", "photo", "relax"],
            "cost": 0,
            "source": "Curated Ha Long attractions",
            "area": "Bai Chay",
            "lat": 20.9537,
            "lon": 107.0415,
            "suitability": "Public beach suitable for swimming and relaxed seaside time.",
        },
        {
            "name": "Tuan Chau Beach",
            "type": "outdoor",
            "interest_tags": ["beach", "swimming", "resort", "relax"],
            "cost": 0,
            "source": "Curated Ha Long attractions",
            "area": "Tuan Chau",
            "lat": 20.9236,
            "lon": 106.9862,
            "suitability": "Beach area close to Tuan Chau hotels and marina services.",
        },
        {
            "name": "Titop Island Beach",
            "type": "outdoor",
            "interest_tags": ["beach", "swimming", "island", "photo", "nature"],
            "cost": 120000,
            "source": "Curated Ha Long attractions",
            "area": "Ha Long Bay",
            "lat": 20.8687,
            "lon": 107.0812,
            "suitability": "Island beach stop often combined with Ha Long Bay boat tours.",
        },
        {
            "name": "Soi Sim Beach",
            "type": "outdoor",
            "interest_tags": ["beach", "swimming", "island", "nature"],
            "cost": 120000,
            "source": "Curated Ha Long attractions",
            "area": "Ha Long Bay",
            "lat": 20.8427,
            "lon": 107.0927,
            "suitability": "Quieter bay beach option for swimming when tour routing allows.",
        },
        {
            "name": "Sun World Ha Long Water Park",
            "type": "outdoor",
            "interest_tags": ["swimming", "water_park", "family", "entertainment"],
            "cost": 350000,
            "source": "Curated Ha Long attractions",
            "area": "Bai Chay",
            "lat": 20.9561,
            "lon": 107.0493,
            "suitability": "Structured water activity option when open and weather is acceptable.",
        },
    ]
}

CITY_AIRPORT_CODES = {
    "Da Nang": "DAD",
    "Da Lat": "DLI",
    "Ha Noi": "HAN",
    "Lao Cai": "HAN",
    "Sa Pa": "HAN",
    "Ho Chi Minh": "SGN",
    "Nha Trang": "CXR",
    "Hue": "HUI",
    "Hoi An": "DAD",
    "Can Tho": "VCA",
    "Vung Tau": "SGN",
    "Ninh Binh": "HAN",
    "Phu Quoc": "PQC",
    "Con Dao": "VCS",
    "Quy Nhon": "UIH",
    "Mang Den": "PXU",
    "Buon Ma Thuot": "BMV",
    "Pleiku": "PXU",
}


def read_secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value.strip().strip("\ufeff").strip('"').strip("'")
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip("\ufeff").strip('"').strip("'")
    return None


def geocode_destination(destination: str) -> tuple[float, float] | None:
    resolved = resolve_location(destination)
    if resolved.lat is not None and resolved.lon is not None:
        return resolved.lat, resolved.lon
    query = canonicalize_location(destination)
    query_overrides = {
        'Ho Chi Minh': 'Ho Chi Minh City, Vietnam',
        'Ha Noi': 'Hanoi, Vietnam',
        'Da Nang': 'Da Nang, Vietnam',
        'Hue': 'Hue, Vietnam',
        'Ninh Binh': 'Ninh Binh, Vietnam',
    }
    query = query_overrides.get(query, query)
    headers = {"User-Agent": "travel-planner-a2a/1.0"}
    params = {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "vn"}
    try:
        with httpx.Client(timeout=15, headers=headers) as client:
            response = client.get(NOMINATIM_URL, params=params)
            response.raise_for_status()
            data = response.json()
        if not data:
            return None
        return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        return None


def reverse_geocode_to_origin(lat: float, lon: float) -> dict:
    headers = {"User-Agent": "travel-planner-a2a/1.0"}
    params = {"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10, "addressdetails": 1}
    try:
        with httpx.Client(timeout=15, headers=headers) as client:
            response = client.get(REVERSE_NOMINATIM_URL, params=params)
            response.raise_for_status()
            data = response.json()
        address = data.get("address", {})
        candidates = [address.get("city"), address.get("municipality"), address.get("state"), address.get("province"), address.get("town"), address.get("county"), address.get("region")]
        for candidate in candidates:
            if not candidate:
                continue
            resolved = resolve_location(candidate)
            if resolved.iata:
                return {"origin_label": resolved.canonical_name, "origin_iata": resolved.iata}
        return {"origin_label": "Unknown location", "origin_iata": "SGN"}
    except Exception:
        return {"origin_label": "Unknown location", "origin_iata": "SGN"}


def _overpass_query(filter_body: str) -> str:
    return f"""
    [out:json][timeout:8];
    (
      {filter_body}
    );
    out center tags 80;
    """


def _fetch_overpass_elements(query: str) -> list[dict]:
    last_error: Exception | None = None
    for url in OVERPASS_URLS[:2]:
        try:
            with httpx.Client(timeout=10, headers={"User-Agent": "travel-planner-a2a/1.0"}) as client:
                response = client.post(url, content=query.encode("utf-8"))
                response.raise_for_status()
                data = response.json()
            elements = data.get("elements", [])
            if elements:
                return elements
        except Exception as ex:
            last_error = ex
            continue
    if last_error:
        return []
    return []


def _safe_rating(tags: dict) -> float:
    stars = tags.get("stars") or tags.get("hotel:stars") or tags.get("rating") or ""
    if str(stars).replace('.', '', 1).isdigit():
        return float(stars)
    tourism = tags.get("tourism", "")
    if tourism == "hotel":
        return 4.0
    if tourism in {"resort", "apartment", "guest_house"}:
        return 3.8
    if tourism in {"hostel", "motel"}:
        return 3.5
    return 3.7


def _safe_price_per_night(tags: dict) -> int:
    tourism = tags.get("tourism", "")
    if tourism == "hotel":
        return 850000
    if tourism == "resort":
        return 1200000
    if tourism in {"apartment", "guest_house"}:
        return 650000
    if tourism in {"hostel", "motel"}:
        return 400000
    return 700000


def _geoapify_places(categories: str, destination: str, radius: int = 12000, limit: int = 10) -> list[dict]:
    api_key = read_secret('GEOAPIFY_API_KEY')
    coords = geocode_destination(destination)
    if not api_key or not coords:
        return []
    lat, lon = coords
    params = {
        'categories': categories,
        'filter': f'circle:{lon},{lat},{radius}',
        'bias': f'proximity:{lon},{lat}',
        'limit': limit,
        'lang': 'vi',
        'apiKey': api_key,
    }
    try:
        response = httpx.get(GEOAPIFY_PLACES_URL, params=params, timeout=REQUEST_TIMEOUT_MEDIUM)
        response.raise_for_status()
        return response.json().get('features', [])
    except Exception:
        return []


def _wikipedia_geo_attractions(destination: str, radius: int = 10000, limit: int = 10) -> list[dict]:
    coords = geocode_destination(destination)
    if not coords:
        return []
    lat, lon = coords
    radius = min(max(int(radius), 10), 10000)
    results: list[dict] = []
    seen: set[str] = set()
    excluded_terms = (
        "hotel",
        "homestay",
        "hostel",
        "resort",
        "airport",
        "bệnh viện",
        "benh vien",
        "quân y",
        "quan y",
        "phường",
        "phuong",
        "xã ",
        "xa ",
        "(thành phố)",
        "(thanh pho)",
    )
    for base_url, lang in (
        ("https://vi.wikipedia.org/w/api.php", "vi"),
        ("https://en.wikipedia.org/w/api.php", "en"),
    ):
        if len(results) >= limit:
            break
        try:
            geo_params = {
                "action": "query",
                "list": "geosearch",
                "gscoord": f"{lat}|{lon}",
                "gsradius": radius,
                "gslimit": limit * 2,
                "format": "json",
                "origin": "*",
            }
            wiki_headers = {"User-Agent": "TravelPlannerA2A/1.0 (local travel planning app; contact: dev@example.com)"}
            geo_response = httpx.get(base_url, params=geo_params, headers=wiki_headers, timeout=REQUEST_TIMEOUT_FAST)
            geo_response.raise_for_status()
            rows = ((geo_response.json() or {}).get("query") or {}).get("geosearch") or []
            page_ids = [str(row.get("pageid")) for row in rows if row.get("pageid")]
            if not page_ids:
                continue
            image_params = {
                "action": "query",
                "pageids": "|".join(page_ids[:20]),
                "prop": "pageimages|pageterms",
                "piprop": "thumbnail",
                "pithumbsize": 900,
                "format": "json",
                "origin": "*",
            }
            image_response = httpx.get(base_url, params=image_params, headers=wiki_headers, timeout=REQUEST_TIMEOUT_FAST)
            image_response.raise_for_status()
            pages = ((image_response.json() or {}).get("query") or {}).get("pages") or {}
            for row in rows:
                if len(results) >= limit:
                    break
                page = pages.get(str(row.get("pageid"))) or {}
                title = (page.get("title") or row.get("title") or "").strip()
                key = title.lower()
                if not title or key in seen or any(term in key for term in excluded_terms):
                    continue
                seen.add(key)
                description = (((page.get("terms") or {}).get("description") or [""])[0] or "").strip()
                thumbnail = (page.get("thumbnail") or {}).get("source") or ""
                interest_tags = ["explore", "photo"]
                if any(word in (description + " " + title).lower() for word in ["đền", "chùa", "palace", "temple", "church", "museum", "historic"]):
                    interest_tags.extend(["history", "culture"])
                if any(word in (description + " " + title).lower() for word in ["lake", "mountain", "waterfall", "valley", "hồ", "núi", "thác", "vườn"]):
                    interest_tags.extend(["nature"])
                results.append({
                    "name": title,
                    "type": "outdoor",
                    "interest_tags": sorted(set(interest_tags)),
                    "cost": 0,
                    "source": f"Wikipedia {lang}",
                    "photo_url": thumbnail,
                })
        except Exception:
            continue
    return results


def _rapidapi_headers() -> dict[str, str] | None:
    api_key = read_secret('RAPIDAPI_KEY')
    api_host = read_secret('RAPIDAPI_HOST') or 'booking-com15.p.rapidapi.com'
    if not api_key:
        return None
    return {
        'x-rapidapi-key': api_key,
        'x-rapidapi-host': api_host,
    }


def _rapidapi_destination_search(destination: str) -> dict | None:
    headers = _rapidapi_headers()
    if not headers:
        return None
    params = {'query': destination, 'locale': 'en-gb'}
    try:
        response = httpx.get(f'{RAPIDAPI_BASE_URL}/hotels/searchDestination', headers=headers, params=params, timeout=REQUEST_TIMEOUT_MEDIUM)
        response.raise_for_status()
        rows = (response.json() or {}).get('data') or []
        if not rows:
            return None
        resolved = canonicalize_location(destination).lower()
        for row in rows:
            label = f"{row.get('label', '')} {row.get('name', '')}".lower()
            if resolved and resolved in label:
                return row
        return rows[0]
    except Exception:
        return None


def _rapidapi_search_hotels(destination: str, limit: int = 8, checkin_date: str | None = None, checkout_date: str | None = None, adults: int = 2, rooms: int = 1, children: int = 0, child_ages: list[int] | None = None) -> list[dict]:
    headers = _rapidapi_headers()
    dest = _rapidapi_destination_search(destination)
    if not headers or not dest:
        return []
    checkin = checkin_date or (date.today() + timedelta(days=14)).isoformat()
    checkout = checkout_date or (date.today() + timedelta(days=15)).isoformat()
    params = {
        'dest_id': dest.get('dest_id'),
        'search_type': str(dest.get('search_type') or dest.get('dest_type') or 'city').upper(),
        'arrival_date': checkin,
        'departure_date': checkout,
        'adults': adults,
        'room_qty': rooms,
        'page_number': 1,
        'units': 'metric',
        'temperature_unit': 'c',
        'languagecode': 'en-us',
        'currency_code': 'VND',
    }
    if children > 0:
        ages = (child_ages or [7] * children)[:children]
        params['children_age'] = ','.join(str(age) for age in ages)
    try:
        response = httpx.get(f'{RAPIDAPI_BASE_URL}/hotels/searchHotels', headers=headers, params=params, timeout=REQUEST_TIMEOUT_SLOW)
        response.raise_for_status()
        hotels = (((response.json() or {}).get('data') or {}).get('hotels') or [])
        results = []
        for item in hotels[:limit]:
            prop = item.get('property') or {}
            price = (((prop.get('priceBreakdown') or {}).get('grossPrice') or {}).get('value') or 0)
            if not prop.get('name'):
                continue
            accessibility_label = item.get('accessibilityLabel', '') or ''
            label_lines = [line.strip(' .\u200e\u202c') for line in accessibility_label.split('\n') if line.strip()]
            area = prop.get('wishlistName') or canonicalize_location(destination)
            room_label = ''
            included_taxes = False
            free_cancellation = False
            no_prepayment = False
            for line in label_lines:
                lower = line.lower()
                if ('from centre' in lower or 'from downtown' in lower or 'beachfront' in lower or 'city centre' in lower or 'suburbs' in lower or 'district' in lower) and area == (prop.get('wishlistName') or canonicalize_location(destination)):
                    area = line
                if 'includes taxes and' in lower or 'includes taxes and fees' in lower or 'includes taxes and charges' in lower:
                    included_taxes = True
                if 'free cancellation' in lower:
                    free_cancellation = True
                if 'no prepayment' in lower:
                    no_prepayment = True
                if ('bed' in lower or 'bathroom' in lower or 'apartment' in lower or 'hotel room' in lower or 'suite' in lower) and not room_label:
                    room_label = line
            results.append({
                'id': prop.get('id'),
                'name': prop.get('name'),
                'area': area,
                'room_label': room_label,
                'included_taxes': included_taxes,
                'free_cancellation': free_cancellation,
                'no_prepayment': no_prepayment,
                'rating': prop.get('reviewScore') or prop.get('propertyClass') or prop.get('accuratePropertyClass') or 0,
                'review_word': prop.get('reviewScoreWord') or '',
                'review_count': prop.get('reviewCount') or 0,
                'price_per_night': int(round(float(price))) if price else 0,
                'currency': ((prop.get('priceBreakdown') or {}).get('grossPrice') or {}).get('currency') or prop.get('currency') or 'VND',
                'checkin_date': prop.get('checkinDate') or checkin,
                'checkout_date': prop.get('checkoutDate') or checkout,
                'photo_url': ((prop.get('photoUrls') or [None])[0]),
                'accessibility_label': accessibility_label,
                'source': 'RapidAPI booking-com15',
                'amenities': ['booking', 'hotel'],
                'search_adults': adults,
                'search_children': children,
                'search_child_ages': (child_ages or [7] * children)[:children],
                'search_rooms': rooms,
            })
        return results
    except Exception:
        return []


def _hotel_price_value(price: dict, *keys: str) -> int:
    for key in keys:
        value = price.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return int(round(float(value)))
    return 0


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _hotel_search_query(destination: str) -> str:
    canonical = canonicalize_location(destination)
    context = {
        "Da Lat": "Da Lat Lam Dong Vietnam hotels",
        "Da Nang": "Da Nang Vietnam hotels",
        "Phu Quoc": "Phu Quoc Vietnam hotels",
        "Nha Trang": "Nha Trang Khanh Hoa Vietnam hotels",
        "Hue": "Hue Vietnam hotels",
        "Hoi An": "Hoi An Quang Nam Vietnam hotels",
        "Ha Noi": "Hanoi Vietnam hotels",
        "Ho Chi Minh": "Ho Chi Minh City Vietnam hotels",
    }
    return context.get(canonical, f"{canonical} Vietnam hotels")


def _serpapi_search_hotels(destination: str, limit: int = 8, checkin_date: str | None = None, checkout_date: str | None = None, adults: int = 2, rooms: int = 1, children: int = 0, child_ages: list[int] | None = None) -> list[dict]:
    serpapi_key = read_secret("SERPAPI_KEY")
    if not serpapi_key:
        return []
    destination_coords = geocode_destination(destination)
    canonical_destination = canonicalize_location(destination)
    max_distance_km = 45 if canonical_destination in {"Da Lat", "Phu Quoc", "Con Dao"} else 30

    checkin = checkin_date or (date.today() + timedelta(days=14)).isoformat()
    checkout = checkout_date or (date.today() + timedelta(days=15)).isoformat()
    try:
        stay_nights = max((date.fromisoformat(checkout) - date.fromisoformat(checkin)).days, 1)
    except ValueError:
        stay_nights = 1

    params = {
        "engine": "google_hotels",
        "q": _hotel_search_query(destination),
        "check_in_date": checkin,
        "check_out_date": checkout,
        "adults": max(1, adults),
        "children": max(0, children),
        "currency": "VND",
        "gl": "vn",
        "hl": "vi",
        "api_key": serpapi_key,
    }
    if rooms and rooms > 1:
        params["rooms"] = rooms
    if children > 0:
        ages = (child_ages or [7] * children)[:children]
        params["children_ages"] = ",".join(str(age) for age in ages)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SLOW) as client:
            response = client.get(SERPAPI_FLIGHTS_URL, params=params)
            response.raise_for_status()
            properties = (response.json() or {}).get("properties") or []
    except Exception:
        return []

    results = []
    for prop in properties:
        name = prop.get("name")
        if not name:
            continue

        distance_from_destination = None
        gps = prop.get("gps_coordinates") or {}
        hotel_lat = gps.get("latitude")
        hotel_lon = gps.get("longitude")
        if destination_coords and hotel_lat is not None and hotel_lon is not None:
            try:
                distance_from_destination = _distance_km(destination_coords[0], destination_coords[1], float(hotel_lat), float(hotel_lon))
            except (TypeError, ValueError):
                distance_from_destination = None
            if distance_from_destination is None or distance_from_destination > max_distance_km:
                continue
        elif destination_coords:
            continue

        nightly_rate = prop.get("rate_per_night") or {}
        total_rate = prop.get("total_rate") or {}
        nightly_price = _hotel_price_value(nightly_rate, "extracted_lowest", "extracted_before_taxes_fees")
        total_price = _hotel_price_value(total_rate, "extracted_lowest", "extracted_before_taxes_fees")
        if not nightly_price and total_price:
            nightly_price = int(round(total_price / stay_nights))
        if not total_price and nightly_price:
            total_price = nightly_price * stay_nights
        if not nightly_price and not total_price:
            continue

        images = prop.get("images") or []
        first_image = images[0] if images else {}
        nearby_places = prop.get("nearby_places") or []
        area = canonicalize_location(destination)
        if nearby_places and nearby_places[0].get("name"):
            area = nearby_places[0]["name"]
        elif prop.get("neighborhood"):
            area = prop["neighborhood"]

        results.append({
            "id": prop.get("property_token"),
            "name": name,
            "area": area,
            "room_label": prop.get("hotel_class") or "",
            "included_taxes": bool(total_rate),
            "free_cancellation": False,
            "no_prepayment": False,
            "rating": prop.get("overall_rating") or prop.get("extracted_hotel_class") or 0,
            "review_word": "",
            "review_count": prop.get("reviews") or 0,
            "price_per_night": nightly_price,
            "total_price": total_price,
            "currency": "VND",
            "checkin_date": checkin,
            "checkout_date": checkout,
            "photo_url": first_image.get("original_image") or prop.get("thumbnail"),
            "booking_link": prop.get("link") or prop.get("serpapi_property_details_link"),
            "source": "SerpAPI Google Hotels",
            "amenities": ["booking", "hotel", "google_hotels"],
            "price_source": "Google Hotels live rate",
            "distance_km": round(distance_from_destination, 1) if distance_from_destination is not None else None,
            "search_adults": adults,
            "search_children": children,
            "search_child_ages": (child_ages or [7] * children)[:children],
            "search_rooms": rooms,
        })
        if len(results) >= limit:
            break
    return results


def fetch_live_hotels(destination: str, limit: int = 8, checkin_date: str | None = None, checkout_date: str | None = None, adults: int = 2, rooms: int = 1, children: int = 0, child_ages: list[int] | None = None) -> list[dict]:
    canonical_destination = canonicalize_location(destination)
    resolved_destination = resolve_location(destination)
    search_radius = 30000 if canonical_destination in {'Da Lat', 'Phu Quoc'} or resolved_destination.kind in {'island', 'town'} else 15000

    serpapi_hotels = _serpapi_search_hotels(canonical_destination, limit, checkin_date, checkout_date, adults, rooms, children, child_ages)
    if serpapi_hotels:
        return serpapi_hotels

    booking_hotels = _rapidapi_search_hotels(canonical_destination, limit, checkin_date, checkout_date, adults, rooms, children, child_ages)
    if booking_hotels:
        return booking_hotels

    geo_queries = [canonical_destination]
    if resolved_destination.nearest_known_place and resolved_destination.nearest_known_place not in geo_queries:
        geo_queries.append(resolved_destination.nearest_known_place)
    if resolved_destination.nearest_bus_hub and resolved_destination.nearest_bus_hub not in geo_queries:
        geo_queries.append(resolved_destination.nearest_bus_hub)

    for query_destination in geo_queries:
        geo_features = _geoapify_places('accommodation.hotel,accommodation.guest_house,accommodation.apartment,accommodation.hostel,accommodation.motel', query_destination, search_radius, limit)
        if geo_features:
            results = []
            for feature in geo_features[:limit]:
                props = feature.get('properties', {})
                name = props.get('name') or props.get('formatted') or 'Hotel'
                area = props.get('suburb') or props.get('district') or props.get('city') or canonical_destination
                results.append({'name': name, 'area': area, 'rating': 4.0, 'price_per_night': 800000, 'amenities': ['wifi', 'breakfast'], 'source': 'Geoapify'})
            return results

    coords = geocode_destination(destination)
    if not coords and resolved_destination.nearest_known_place:
        coords = geocode_destination(resolved_destination.nearest_known_place)
    if not coords and resolved_destination.nearest_bus_hub:
        coords = geocode_destination(resolved_destination.nearest_bus_hub)
    if not coords:
        return []
    lat, lon = coords
    query = _overpass_query(
        f'node["tourism"~"hotel|guest_house|hostel|motel|apartment|resort"](around:{search_radius},{lat},{lon});'
        f'way["tourism"~"hotel|guest_house|hostel|motel|apartment|resort"](around:{search_radius},{lat},{lon});'
        f'relation["tourism"~"hotel|guest_house|hostel|motel|apartment|resort"](around:{search_radius},{lat},{lon});'
    )
    try:
        elements = _fetch_overpass_elements(query)
        if not elements:
            return []
        results = []
        seen = set()
        for item in elements:
            tags = item.get("tags", {})
            name = tags.get("name") or tags.get("official_name") or ""
            key = name.strip().lower()
            if not key or key in seen or len(key) < 3:
                continue
            seen.add(key)
            area = tags.get("addr:suburb") or tags.get("addr:district") or tags.get("addr:city") or canonical_destination
            results.append({'name': name, 'area': area, 'rating': _safe_rating(tags), 'price_per_night': _safe_price_per_night(tags), 'amenities': ['wifi', 'breakfast'], 'source': 'OpenStreetMap'})
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


def _ascii_slug(value: str) -> str:
    text = (value or "").strip().lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return " ".join(text.split())


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _geoapify_feature_to_attraction(feature: dict, strategy: str) -> dict:
    props = feature.get("properties", {})
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
    lon = coords[0] if isinstance(coords, list) and len(coords) >= 2 else None
    lat = coords[1] if isinstance(coords, list) and len(coords) >= 2 else None
    name = props.get("name") or props.get("formatted") or "Attraction"
    category_text = " ".join(props.get("categories", []) or []).lower()
    name_slug = _ascii_slug(name)
    interest_tags = ["explore"]
    place_type = "outdoor"
    cost = 0

    if any(term in category_text for term in ("beach", "bay", "island", "natural")) or any(term in name_slug for term in ("beach", "bai", "bay", "dao", "island")):
        interest_tags.extend(["beach", "swimming", "nature", "photo"])
    if any(term in category_text for term in ("water_park", "swimming_pool")) or any(term in name_slug for term in ("water park", "cong vien nuoc")):
        interest_tags.extend(["swimming", "water_park", "entertainment"])
        cost = 250000
    if "museum" in category_text:
        interest_tags.extend(["history", "culture"])
        place_type = "indoor"
        cost = 100000
    if "park" in category_text and "water_park" not in category_text:
        interest_tags.extend(["nature", "photo"])
    if "tourism" in category_text or "sights" in category_text:
        interest_tags.append("photo")
    if strategy == "beach_swimming" and not {"beach", "swimming"} & set(interest_tags):
        interest_tags.append("low_activity_match")

    return {
        "name": name,
        "type": place_type,
        "interest_tags": sorted(set(interest_tags)),
        "cost": cost,
        "source": "Geoapify",
        "area": props.get("suburb") or props.get("district") or props.get("city") or "",
        "lat": lat,
        "lon": lon,
        "suitability": "",
    }


def _overpass_element_to_attraction(item: dict) -> dict | None:
    tags = item.get("tags", {})
    name = tags.get("name") or tags.get("official_name") or ""
    if not name or len(name.strip()) < 3:
        return None
    tourism = tags.get("tourism", "")
    historic = tags.get("historic", "")
    leisure = tags.get("leisure", "")
    natural = tags.get("natural", "")
    amenity = tags.get("amenity", "")
    category = tourism or historic or leisure or natural or amenity or "attraction"
    name_slug = _ascii_slug(name)
    interest_tags = ["explore", category]
    place_type = "outdoor"
    cost = 0

    if category in {"beach", "bay", "islet", "water", "island"} or any(term in name_slug for term in ("beach", "bai", "bay", "dao", "island")):
        interest_tags.extend(["beach", "swimming", "nature", "photo"])
    if category in {"water_park", "swimming_pool"}:
        interest_tags.extend(["swimming", "water_park", "entertainment"])
        cost = 250000
    if category in {"viewpoint", "park", "garden", "peak", "waterfall", "cave"}:
        interest_tags.extend(["photo", "nature"])
    if category in {"museum", "memorial", "monument", "castle", "artwork", "temple", "pagoda", "historic"}:
        interest_tags.extend(["history", "culture"])
        place_type = "indoor" if category in {"museum", "gallery", "artwork"} else "outdoor"
        cost = 100000 if category in {"museum", "gallery"} else 0

    center = item.get("center") or {}
    return {
        "name": name,
        "type": place_type,
        "interest_tags": sorted(set(interest_tags)),
        "cost": cost,
        "source": "OpenStreetMap",
        "area": tags.get("addr:suburb") or tags.get("addr:district") or tags.get("addr:city") or "",
        "lat": item.get("lat") or center.get("lat"),
        "lon": item.get("lon") or center.get("lon"),
        "suitability": "",
    }


def _dedupe_attractions(items: list[dict]) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = _ascii_slug(item.get("name", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        results.append(item)
    return results


def fetch_curated_activity_attractions(destination: str, strategy: str = "general", limit: int = 10) -> list[dict]:
    slug = _ascii_slug(canonicalize_location(destination))
    curated_key = next((key for key in CURATED_ACTIVITY_ATTRACTIONS if key in slug), "")
    if not curated_key:
        return []
    curated = CURATED_ACTIVITY_ATTRACTIONS[curated_key]
    if strategy == "beach_swimming":
        curated = [item for item in curated if {"beach", "swimming", "water_park"} & set(item.get("interest_tags", []))]
    return [dict(item) for item in curated[:limit]]


def fetch_activity_attractions(destination: str, strategy: str = "general", hotel_context: dict | None = None, limit: int = 12) -> list[dict]:
    canonical_destination = canonicalize_location(destination)
    strategy = strategy or "general"
    if strategy != "beach_swimming":
        return fetch_live_attractions(canonical_destination, limit=limit)

    search_destination = canonical_destination
    if hotel_context and hotel_context.get("area"):
        search_destination = f"{hotel_context['area']}, {canonical_destination}"

    results: list[dict] = []
    geo_categories = "natural.beach,natural.water,leisure.water_park,leisure.swimming_pool,tourism.sights,entertainment"
    for query_destination in (search_destination, canonical_destination):
        geo_features = _geoapify_places(geo_categories, query_destination, 16000, limit)
        results.extend(_geoapify_feature_to_attraction(feature, strategy) for feature in geo_features)
        if len(results) >= limit:
            break

    coords = geocode_destination(search_destination) or geocode_destination(canonical_destination)
    if coords and len(results) < limit:
        lat, lon = coords
        query = _overpass_query(
            f'node["natural"~"beach|bay|water"](around:22000,{lat},{lon});way["natural"~"beach|bay|water"](around:22000,{lat},{lon});relation["natural"~"beach|bay|water"](around:22000,{lat},{lon});'
            f'node["place"~"island|islet"](around:22000,{lat},{lon});way["place"~"island|islet"](around:22000,{lat},{lon});relation["place"~"island|islet"](around:22000,{lat},{lon});'
            f'node["leisure"~"water_park|swimming_pool|beach_resort"](around:22000,{lat},{lon});way["leisure"~"water_park|swimming_pool|beach_resort"](around:22000,{lat},{lon});relation["leisure"~"water_park|swimming_pool|beach_resort"](around:22000,{lat},{lon});'
            f'node["tourism"~"attraction|theme_park"](around:22000,{lat},{lon});way["tourism"~"attraction|theme_park"](around:22000,{lat},{lon});relation["tourism"~"attraction|theme_park"](around:22000,{lat},{lon});'
        )
        for item in _fetch_overpass_elements(query):
            attraction = _overpass_element_to_attraction(item)
            if attraction:
                results.append(attraction)

    deduped = _dedupe_attractions(results)
    hotel_lat = hotel_context.get("lat") if hotel_context else None
    hotel_lon = hotel_context.get("lon") if hotel_context else None
    if hotel_lat is not None and hotel_lon is not None:
        for item in deduped:
            if item.get("lat") is not None and item.get("lon") is not None:
                item["distance_to_hotel_km"] = round(_distance_km(float(hotel_lat), float(hotel_lon), float(item["lat"]), float(item["lon"])), 1)
    return deduped[:limit]


def fetch_live_attractions(destination: str, limit: int = 10) -> list[dict]:
    canonical_destination = canonicalize_location(destination)
    geo_features = _geoapify_places('tourism.sights,entertainment,museum,leisure.park,natural', canonical_destination, 18000, limit)
    if geo_features:
        results = []
        for feature in geo_features[:limit]:
            props = feature.get('properties', {})
            name = props.get('name') or props.get('formatted') or 'Attraction'
            categories = props.get('categories', [])
            category_text = ' '.join(categories).lower()
            interest_tags = ['explore']
            if 'museum' in category_text:
                interest_tags.extend(['history', 'culture'])
            if 'park' in category_text or 'natural' in category_text:
                interest_tags.extend(['nature', 'photo'])
            if 'tourism' in category_text or 'sights' in category_text:
                interest_tags.append('photo')
            results.append({'name': name, 'type': 'indoor' if 'museum' in category_text else 'outdoor', 'interest_tags': sorted(set(interest_tags)), 'cost': 100000 if 'museum' in category_text else 0, 'source': 'Geoapify'})
        return results

    wikipedia_results = _wikipedia_geo_attractions(canonical_destination, 14000, limit)
    if wikipedia_results:
        return wikipedia_results

    coords = geocode_destination(destination)
    if not coords:
        return []
    lat, lon = coords
    radius = 22000 if canonical_destination in {'Da Lat', 'Mang Den', 'Tam Dao'} else 18000
    query = _overpass_query(
        f'node["tourism"](around:{radius},{lat},{lon});way["tourism"](around:{radius},{lat},{lon});relation["tourism"](around:{radius},{lat},{lon});'
        f'node["historic"](around:{radius},{lat},{lon});way["historic"](around:{radius},{lat},{lon});relation["historic"](around:{radius},{lat},{lon});'
        f'node["leisure"](around:{radius},{lat},{lon});way["leisure"](around:{radius},{lat},{lon});relation["leisure"](around:{radius},{lat},{lon});'
        f'node["natural"](around:{radius},{lat},{lon});way["natural"](around:{radius},{lat},{lon});relation["natural"](around:{radius},{lat},{lon});'
        f'node["amenity"~"arts_centre|theatre|cinema|planetarium"](around:{radius},{lat},{lon});way["amenity"~"arts_centre|theatre|cinema|planetarium"](around:{radius},{lat},{lon});relation["amenity"~"arts_centre|theatre|cinema|planetarium"](around:{radius},{lat},{lon});'
    )
    try:
        elements = _fetch_overpass_elements(query)
        results = []
        seen = set()
        lodging_categories = {"hotel", "guest_house", "hostel", "motel", "apartment", "resort", "camp_site", "chalet"}
        excluded_categories = {
            "information",
            "travel_agency",
            "ticket",
            "swimming_pool",
            "sports_centre",
            "pitch",
            "fitness_centre",
        }
        excluded_name_terms = (
            "phòng vé",
            "phong ve",
            "vé máy bay",
            "ve may bay",
            "hotel",
            "homestay",
            "hostel",
            "villa",
            "resort",
        )
        for item in elements:
            tags = item.get("tags", {})
            name = tags.get("name") or tags.get("official_name") or ""
            key = name.strip().lower()
            if not key or key in seen or len(key) < 3:
                continue
            tourism = tags.get("tourism", "")
            historic = tags.get("historic", "")
            leisure = tags.get("leisure", "")
            natural = tags.get("natural", "")
            amenity = tags.get("amenity", "")
            category = tourism or historic or leisure or natural or amenity or "attraction"
            if category in lodging_categories:
                continue
            if category in excluded_categories:
                continue
            if any(term in key for term in excluded_name_terms):
                continue
            if not any([tourism, historic, leisure, natural]):
                continue
            seen.add(key)
            interest_tags = ['explore']
            if category in {'viewpoint', 'beach', 'park', 'garden', 'peak', 'bay', 'waterfall', 'cave', 'islet'}:
                interest_tags.extend(['photo', 'nature'])
            if category in {'museum', 'memorial', 'monument', 'castle', 'artwork', 'temple', 'pagoda', 'historic'}:
                interest_tags.extend(['history', 'culture'])
            results.append({'name': name, 'type': 'indoor' if category in {'museum', 'gallery', 'aquarium', 'artwork', 'temple', 'pagoda', 'monument'} else 'outdoor', 'interest_tags': sorted(set(interest_tags + [category])), 'cost': 100000 if category in {'museum', 'gallery', 'aquarium', 'theme_park', 'water_park'} else 0, 'source': 'OpenStreetMap'})
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []


def fetch_live_flights(destination: str, adults: int, max_price: int | None = None, origin: str | None = None, departure_date: str | None = None) -> list[dict]:
    flights, _ = fetch_live_flights_with_debug(destination, adults, max_price, origin, departure_date)
    return flights


def fetch_live_flights_with_debug(destination: str, adults: int, max_price: int | None = None, origin: str | None = None, departure_date: str | None = None) -> tuple[list[dict], dict]:
    serpapi_key = read_secret("SERPAPI_KEY")
    debug = {'provider': 'SerpAPI Google Flights', 'destination': canonicalize_location(destination), 'origin_input': origin, 'origin_resolved': None, 'departure_date': None, 'params_preview': None, 'http_status': None, 'error': None, 'message': None, 'raw_keys': [], 'raw_preview': None}
    if not serpapi_key:
        debug['error'] = 'SERPAPI_KEY missing'
        return [], debug
    origin_resolved = resolve_location(origin or '')
    destination_resolved = resolve_location(destination)
    origin_code = location_to_iata(origin or '') or origin_resolved.iata or read_secret('ORIGIN_IATA') or 'SGN'
    origin_code = str(origin_code).upper()
    debug['origin_resolved'] = origin_code
    destination_code = destination_resolved.iata or CITY_AIRPORT_CODES.get(destination_resolved.canonical_name)
    if not destination_code:
        debug['error'] = f'No airport mapping for destination: {destination}'
        return [], debug
    outbound_date = departure_date or (date.today() + timedelta(days=14)).isoformat()
    debug['departure_date'] = outbound_date
    params = {'engine': 'google_flights', 'type': '2', 'departure_id': origin_code, 'arrival_id': destination_code, 'outbound_date': outbound_date, 'currency': 'VND', 'hl': 'en', 'adults': max(1, adults), 'api_key': serpapi_key}
    debug['params_preview'] = {**params, 'api_key': '***'}
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SLOW, headers={'User-Agent': 'travel-planner-a2a/1.0'}) as client:
            response = client.get(SERPAPI_FLIGHTS_URL, params=params)
            debug['http_status'] = response.status_code
            data = response.json()
        debug['raw_keys'] = list(data.keys())
        debug['raw_preview'] = {'search_metadata_status': data.get('search_metadata', {}).get('status'), 'search_information': data.get('search_information'), 'error': data.get('error')}
        if response.status_code >= 400:
            debug['error'] = data.get('error') or f'HTTP {response.status_code}'
            return [], debug
        flights = []
        for bucket in ('best_flights', 'other_flights'):
            for item in data.get(bucket, []) or []:
                segments = item.get('flights', [])
                if not segments:
                    continue
                first = segments[0]
                last = segments[-1]
                price = item.get('price') or 0
                if max_price and price and price > max_price:
                    continue
                total_duration = item.get('total_duration') or sum(int(segment.get('duration') or 0) for segment in segments)
                flights.append({
                    'airline': first.get('airline') or first.get('airline_logo', 'Flight'),
                    'departure': first.get('departure_airport', {}).get('id', origin_code),
                    'arrival': last.get('arrival_airport', {}).get('id', destination_code),
                    'departure_time': first.get('departure_airport', {}).get('time', ''),
                    'arrival_time': last.get('arrival_airport', {}).get('time', ''),
                    'duration_minutes': total_duration,
                    'stops': max(len(segments) - 1, 0),
                    'price': int(price) if price else 0,
                })
        unique = []
        seen = set()
        for item in flights:
            key = (item['airline'], item['departure'], item['arrival'], item.get('departure_time'), item.get('arrival_time'), item['price'])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        debug['message'] = f'Returned {len(unique)} flights'
        return unique[:8], debug
    except Exception as ex:
        debug['error'] = str(ex)
        return [], debug
