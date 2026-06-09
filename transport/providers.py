from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from functools import lru_cache
import random
import string
import unicodedata
import uuid

import httpx

from schemas.models import UserRequest
from services.bus_area_service import resolve_bus_area_id
from services.location_resolver import resolve_location
from services.live_travel_service import CITY_AIRPORT_CODES, fetch_live_flights
from services.train_station_service import resolve_train_station_code
from transport.models import TransportOption


CITY_ALIASES = {
    "Ho Chi Minh": ["ho chi minh", "hồ chí minh", "sai gon", "sài gòn", "saigon"],
    "Da Nang": ["da nang", "đà nẵng"],
    "Hue": ["hue", "huế"],
    "Ha Noi": ["ha noi", "hà nội", "hanoi"],
    "Da Lat": ["da lat", "đà lạt", "dalat"],
    "Can Tho": ["can tho", "cần thơ"],
    "Vung Tau": ["vung tau", "vũng tàu"],
    "Hoi An": ["hoi an", "hội an"],
    "Ninh Binh": ["ninh binh", "ninh bình"],
    "Ha Long": ["ha long", "hạ long", "halong"],
    "Sa Pa": ["sa pa", "sapa"],
    "Lao Cai": ["lao cai", "lào cai"],
    "Ben Tre": ["ben tre", "bến tre"],
    "Tam Dao": ["tam dao", "tam đảo"],
    "Ba Na Hills": ["ba na", "bà nà", "ba na hills", "bà nà hills"],
    "Mang Den": ["mang den", "măng đen"],
    "Con Dao": ["con dao", "côn đảo"],
}


class TransportProviderAdapter(ABC):
    @abstractmethod
    def search(self, request: UserRequest) -> list[TransportOption]:
        raise NotImplementedError


class SerpApiFlightAdapter(TransportProviderAdapter):
    ESTIMATED_DOMESTIC_FLIGHTS = {
        ("HAN", "SGN"): ("Vietnam Airlines / Vietjet / Bamboo", 1_800_000, "2h 10m"),
        ("SGN", "HAN"): ("Vietnam Airlines / Vietjet / Bamboo", 1_800_000, "2h 10m"),
        ("HAN", "DAD"): ("Vietnam Airlines / Vietjet / Bamboo", 1_200_000, "1h 20m"),
        ("DAD", "HAN"): ("Vietnam Airlines / Vietjet / Bamboo", 1_200_000, "1h 20m"),
        ("SGN", "DAD"): ("Vietnam Airlines / Vietjet / Bamboo", 1_150_000, "1h 20m"),
        ("DAD", "SGN"): ("Vietnam Airlines / Vietjet / Bamboo", 1_150_000, "1h 20m"),
        ("HAN", "DLI"): ("Vietnam Airlines / Vietjet / Bamboo", 1_700_000, "1h 50m"),
        ("DLI", "HAN"): ("Vietnam Airlines / Vietjet / Bamboo", 1_700_000, "1h 50m"),
        ("SGN", "DLI"): ("Vietnam Airlines / Vietjet / Bamboo", 900_000, "0h 55m"),
        ("DLI", "SGN"): ("Vietnam Airlines / Vietjet / Bamboo", 900_000, "0h 55m"),
        ("HAN", "CXR"): ("Vietnam Airlines / Vietjet / Bamboo", 1_650_000, "1h 55m"),
        ("CXR", "HAN"): ("Vietnam Airlines / Vietjet / Bamboo", 1_650_000, "1h 55m"),
        ("SGN", "CXR"): ("Vietnam Airlines / Vietjet / Bamboo", 850_000, "1h 05m"),
        ("CXR", "SGN"): ("Vietnam Airlines / Vietjet / Bamboo", 850_000, "1h 05m"),
    }

    @classmethod
    def _estimated_search(cls, origin_code: str, destination_code: str) -> list[TransportOption]:
        route = cls.ESTIMATED_DOMESTIC_FLIGHTS.get((origin_code, destination_code))
        if not route:
            return []
        operator, price, duration = route
        return [
            TransportOption(
                mode="flight",
                provider="Estimated domestic flight fallback",
                operator=operator,
                departure=origin_code,
                arrival=destination_code,
                price=price,
                duration=duration,
                score=3.6,
                reason="SerpAPI flight quota is unavailable, so this is an estimated domestic flight option for planning.",
                price_verified=False,
                fare_label="Gia ve may bay tham khao",
            )
        ]

    def search(self, request: UserRequest) -> list[TransportOption]:
        destination_resolved = resolve_location(request.destination)
        origin_resolved = resolve_location(request.origin)
        destination_for_flights = destination_resolved.canonical_name
        origin_for_flights = origin_resolved.iata or request.origin
        flights = fetch_live_flights(
            destination=destination_for_flights,
            adults=request.travelers,
            max_price=request.budget,
            origin=origin_for_flights,
            departure_date=request.departure_date or None,
        )
        if not flights:
            origin_code = origin_resolved.iata or CITY_AIRPORT_CODES.get(origin_resolved.canonical_name) or origin_for_flights
            destination_code = destination_resolved.iata or CITY_AIRPORT_CODES.get(destination_resolved.canonical_name)
            if origin_code and destination_code:
                return self._estimated_search(origin_code, destination_code)
        results: list[TransportOption] = []
        for item in flights:
            uses_nearest_hub = False
            reason = "Kết quả chuyến bay từ SerpAPI"
            results.append(
                TransportOption(
                    mode="flight",
                    provider="SerpAPI Google Flights",
                    operator=item.get("airline", "Unknown"),
                    departure=item.get("departure", request.origin),
                    arrival=item.get("arrival", request.destination),
                    price=item.get("price", 0),
                    duration="",
                    score=0.0,
                    reason=reason,
                    uses_nearest_hub=uses_nearest_hub,
                    origin_hub=origin_for_flights if uses_nearest_hub else None,
                    destination_hub=destination_for_flights if uses_nearest_hub else None,
                )
            )
        return results


class TrainProviderAdapter(TransportProviderAdapter):
    TRAIN_RULES = {
        ("Ha Noi", "Da Nang"): [("SE3", 950000, "15h 30m")],
        ("Da Nang", "Ha Noi"): [("SE4", 950000, "15h 10m")],
        ("Ho Chi Minh", "Da Nang"): [("SE7", 1050000, "17h 40m")],
        ("Da Nang", "Ho Chi Minh"): [("SE8", 1050000, "17h 20m")],
        ("Ha Noi", "Hue"): [("SE1", 780000, "13h 20m")],
        ("Hue", "Ha Noi"): [("SE2", 780000, "13h 00m")],
    }

    def _station_code(self, location: str) -> str | None:
        return resolve_train_station_code(location)

    @staticmethod
    def _minutes_to_duration(total_minutes: int | None) -> str:
        if not total_minutes:
            return ""
        hours = int(total_minutes) // 60
        mins = int(total_minutes) % 60
        return f"{hours}h {mins:02d}m"

    def _load_train_price(self, tau_id: int, ma_ga_di: str) -> tuple[int, str, bool]:
        try:
            detail = httpx.get(
                "https://k.vnticketonline.vn/api/GTGV/LoadOneTau",
                params={"tauId": tau_id, "maGaDi": ma_ga_di},
                timeout=10,
                headers={"User-Agent": "travel-planner-a2a/1.0"},
            ).json()
            bang_gia = detail.get("BangGiaVes") or []
            soft_seat_prices = []
            sleeper_prices = []
            fallback_prices = []

            for seat in bang_gia:
                gia = seat.get("GiaVe")
                ten_loai = (seat.get("TenLoaiCho") or seat.get("LoaiCho") or "").strip()
                if gia is None:
                    continue
                try:
                    gia_vnd = int(float(gia) * 1000)
                except Exception:
                    continue
                seat_slug = ten_loai.lower()
                if "ghế phụ" in seat_slug or "ghe phu" in seat_slug:
                    continue
                if "ngồi mềm" in seat_slug or "ngoi mem" in seat_slug:
                    soft_seat_prices.append((gia_vnd, ten_loai))
                elif "giường" in seat_slug or "giuong" in seat_slug:
                    sleeper_prices.append((gia_vnd, ten_loai))
                else:
                    fallback_prices.append((gia_vnd, ten_loai))

            if soft_seat_prices:
                soft_seat_prices.sort(key=lambda x: x[0])
                return soft_seat_prices[0][0], f"Giá ghế mềm thấp nhất: {soft_seat_prices[0][1]}", False
            if sleeper_prices:
                sleeper_prices.sort(key=lambda x: x[0])
                return sleeper_prices[0][0], f"Giá giường nằm thấp nhất: {sleeper_prices[0][1]}", False
            if fallback_prices:
                fallback_prices.sort(key=lambda x: x[0])
                return fallback_prices[0][0], f"Giá tham khảo: {fallback_prices[0][1]}", False
            return 0, "", False
        except Exception:
            return 0, "", False

    def _live_search(self, request: UserRequest) -> list[TransportOption]:
        origin_resolved = resolve_location(request.origin)
        destination_resolved = resolve_location(request.destination)
        origin_city = origin_resolved.canonical_name
        destination_city = destination_resolved.canonical_name
        ma_ga_di = self._station_code(origin_city)
        ma_ga_den = self._station_code(destination_city)
        if not ma_ga_di or not ma_ga_den:
            return []

        ngay_di = request.departure_date or (date.today() + timedelta(days=7)).isoformat()
        url = "https://k.vnticketonline.vn/api/GTGV/LoadDmTau"
        params = {"ngayDi": ngay_di, "maGaDi": ma_ga_di, "maGaDen": ma_ga_den}
        try:
            with httpx.Client(timeout=10, headers={"User-Agent": "travel-planner-a2a/1.0"}) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, list):
                return []

            results: list[TransportOption] = []
            for item in data[:8]:
                tau_id = item.get("Id") or item.get("TauId")
                train_name = item.get("MacTau") or item.get("TenTau") or "Train"
                departure_time = item.get("GioDi") or ""
                arrival_time = item.get("GioDen") or ""
                duration = self._minutes_to_duration(item.get("Duration"))
                price, fare_label, price_verified = self._load_train_price(int(tau_id), ma_ga_di) if tau_id else (0, "", False)
                reason = "Kết quả tàu từ API tương thích DSVN."
                if origin_city != origin_resolved.canonical_name or destination_city != destination_resolved.canonical_name:
                    reason += f" Dùng ga trung chuyển phù hợp: {origin_city} -> {destination_city}."
                if fare_label:
                    reason += f" {fare_label}."
                if not price_verified:
                    reason += " Giá tàu chỉ mang tính tham khảo, chưa phải giá bán cuối cùng."
                uses_nearest_hub = origin_city != origin_resolved.canonical_name or destination_city != destination_resolved.canonical_name
                results.append(
                    TransportOption(
                        mode="train",
                        provider="DSVN API",
                        operator=str(train_name),
                        departure=f"{origin_city} {departure_time}".strip(),
                        arrival=f"{destination_city} {arrival_time}".strip(),
                        price=price,
                        duration=duration,
                        score=4.3,
                        reason=reason,
                        uses_nearest_hub=uses_nearest_hub,
                        origin_hub=origin_city if uses_nearest_hub else None,
                        destination_hub=destination_city if uses_nearest_hub else None,
                        price_verified=price_verified,
                        fare_label=fare_label,
                    )
                )
            return results
        except Exception:
            return []

    def search(self, request: UserRequest) -> list[TransportOption]:
        live_results = self._live_search(request)
        if live_results:
            return live_results
        return []


class CarRouteProviderAdapter(TransportProviderAdapter):
    @staticmethod
    def _minutes_to_duration(total_minutes: int | None) -> str:
        if not total_minutes:
            return ""
        hours = int(total_minutes) // 60
        mins = int(total_minutes) % 60
        return f"{hours}h {mins:02d}m"

    @staticmethod
    def _estimate_price(distance_km: float, duration_minutes: float) -> int:
        base_fare = 150000
        distance_component = int(distance_km * 11000)
        time_component = int(max(duration_minutes - 60, 0) * 1200)
        return max(base_fare, distance_component + time_component)

    def search(self, request: UserRequest) -> list[TransportOption]:
        origin = resolve_location(request.origin)
        destination = resolve_location(request.destination)
        if origin.lat is None or origin.lon is None or destination.lat is None or destination.lon is None:
            return []

        coords = f"{origin.lon},{origin.lat};{destination.lon},{destination.lat}"
        url = f"https://router.project-osrm.org/route/v1/driving/{coords}"
        params = {"overview": "false", "alternatives": "false", "steps": "false"}
        try:
            response = httpx.get(url, params=params, timeout=20, headers={"User-Agent": "travel-planner-a2a/1.0"})
            response.raise_for_status()
            data = response.json()
            routes = data.get('routes') or []
            if not routes:
                return []
            route = routes[0]
            distance_km = float(route.get('distance') or 0) / 1000
            duration_minutes = float(route.get('duration') or 0) / 60
            price = self._estimate_price(distance_km, duration_minutes)
            reason = (
                f"Live road route tu OSRM cho chang {origin.canonical_name} -> {destination.canonical_name}. "
                f"Quang duong uoc tinh {distance_km:.0f} km."
            )
            return [
                TransportOption(
                    mode='car',
                    provider='OSRM road routing',
                    operator='Road transfer',
                    departure=origin.canonical_name,
                    arrival=destination.canonical_name,
                    price=price,
                    duration=self._minutes_to_duration(int(duration_minutes)),
                    score=0.0,
                    reason=reason,
                )
            ]
        except Exception:
            return []


class BusProviderAdapter(TransportProviderAdapter):
    BUS_RULES = {
        ("Ho Chi Minh", "Vung Tau"): [("Phuong Trang", 180000, "2h 20m")],
        ("Vung Tau", "Ho Chi Minh"): [("Phuong Trang", 180000, "2h 20m")],
        ("Ho Chi Minh", "Can Tho"): [("Phuong Trang", 165000, "3h 30m")],
        ("Can Tho", "Ho Chi Minh"): [("Phuong Trang", 165000, "3h 30m")],
        ("Da Nang", "Hue"): [("The Sinh Tourist", 140000, "2h 45m")],
        ("Hue", "Da Nang"): [("The Sinh Tourist", 140000, "2h 45m")],
        ("Da Nang", "Hoi An"): [("Local Shuttle", 120000, "1h 00m")],
        ("Hoi An", "Da Nang"): [("Local Shuttle", 120000, "1h 00m")],
    }

    def _guest_headers(self) -> dict:
        token = self._guest_token()
        rid = 'FE_NEXTJS_' + str(uuid.uuid4()) + '_' + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(6))
        return {
            'Authorization': f'bearer {token}',
            'Accept-Language': 'vi-VN',
            'origin-request-product': 'FE_NEXTJS',
            'origin-request-id': rid,
            'User-Agent': 'travel-planner-a2a/1.0',
        }

    @staticmethod
    @lru_cache(maxsize=1)
    def _guest_token() -> str:
        try:
            return httpx.post('https://vexere.com/getToken', timeout=6).json().get('access_token', '')
        except Exception:
            return ''

    @staticmethod
    def _minutes_to_duration(total_minutes: int | None) -> str:
        if not total_minutes:
            return ""
        hours = int(total_minutes) // 60
        mins = int(total_minutes) % 60
        return f"{hours}h {mins:02d}m"

    @staticmethod
    def _display_time(value: str) -> str:
        if not value:
            return ""
        text = str(value).strip()
        try:
            return datetime.fromisoformat(text).strftime("%H:%M")
        except Exception:
            return text[:5] if len(text) >= 5 and text[2:3] == ":" else text

    def _aliases(self, city: str) -> list[str]:
        resolved = resolve_location(city)
        canonical = resolved.canonical_name
        return CITY_ALIASES.get(canonical, [canonical.lower()])

    def _matches_city(self, haystack: str, city: str) -> bool:
        def slug(value: str) -> str:
            text = (value or '').lower().replace('đ', 'd').replace('Ä‘', 'd')
            text = unicodedata.normalize('NFD', text)
            return ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')

        text = slug(haystack)
        return any(slug(alias) in text for alias in self._aliases(city))

    def _resolve_area_id(self, location: str) -> str | None:
        return resolve_bus_area_id(location)

    def _live_search(self, request: UserRequest) -> list[TransportOption]:
        origin_resolved = resolve_location(request.origin)
        destination_resolved = resolve_location(request.destination)
        origin_city = origin_resolved.canonical_name
        destination_city = destination_resolved.canonical_name
        from_id = self._resolve_area_id(origin_city)
        to_id = self._resolve_area_id(destination_city)
        if not from_id or not to_id:
            return []

        headers = self._guest_headers()
        params = {
            'filter[from]': from_id,
            'filter[to]': to_id,
            'filter[date]': request.departure_date or (date.today() + timedelta(days=7)).isoformat(),
            'page': 1,
            'pagesize': 20,
        }
        try:
            data = httpx.get('https://internal-vroute-cmc.vexere.com/v2/route', params=params, headers=headers, timeout=7).json()
            items = data.get('data') or []
            results: list[TransportOption] = []
            for item in items:
                route = item.get('route') or {}
                route_name = route.get('name') or ''
                route_from = ((route.get('from') or {}).get('city_name') or '')
                route_to = ((route.get('to') or {}).get('city_name') or '')
                route_haystack = ' | '.join([route_name, route_from, route_to])
                if not self._matches_city(route_haystack, origin_city):
                    continue
                if not self._matches_city(route_haystack, destination_city):
                    continue

                company = (item.get('company') or {}).get('name') or route.get('company_name') or 'Bus operator'
                schedules = route.get('schedules') or []
                schedule = schedules[0] if schedules else {}
                departure_time = self._display_time(route.get('departure_time') or (f"{schedule.get('hour')}:{schedule.get('minute')}" if schedule.get('hour') is not None and schedule.get('minute') is not None else ''))
                arrival_time = self._display_time(schedule.get('arrival_time') or '')
                duration_minutes = route.get('duration') or 0
                duration = self._minutes_to_duration(duration_minutes)
                fare = schedule.get('fare') or {}
                price = fare.get('original') or route.get('min_price') or item.get('price') or 0
                try:
                    price = int(float(price))
                except Exception:
                    price = 0
                vehicle_type = schedule.get('vehicle_type') or schedule.get('seat_template_name') or ''
                available_seats = schedule.get('available_seats')
                reason = 'Kết quả xe khách từ luồng tra cứu Vexere.'
                if origin_city != origin_resolved.canonical_name or destination_city != destination_resolved.canonical_name:
                    reason += f' Dùng bến trung chuyển phù hợp: {origin_city} -> {destination_city}.'
                if vehicle_type:
                    reason += f' Loại xe: {vehicle_type}.'
                if available_seats is not None:
                    reason += f' Số ghế còn lại: {available_seats}.'
                uses_nearest_hub = origin_city != origin_resolved.canonical_name or destination_city != destination_resolved.canonical_name
                results.append(
                    TransportOption(
                        mode='bus',
                        provider='Vexere public route API',
                        operator=str(company),
                        departure=f'{origin_city} {departure_time}'.strip(),
                        arrival=f'{destination_city} {arrival_time}'.strip(),
                        price=price,
                        duration=duration,
                        score=4.0,
                        reason=reason,
                        uses_nearest_hub=uses_nearest_hub,
                        origin_hub=origin_city if uses_nearest_hub else None,
                        destination_hub=destination_city if uses_nearest_hub else None,
                    )
                )
            results.sort(key=lambda option: (option.price if option.price > 0 else 10**9, option.duration or ""))
            return results[:8]
        except Exception:
            return []

    def search(self, request: UserRequest) -> list[TransportOption]:
        live_results = self._live_search(request)
        if live_results:
            return live_results
        return []
