from __future__ import annotations

from schemas.models import UserRequest
from services.location_resolver import _distance_km, resolve_location
from services.location_service import canonicalize_location
from transport.providers import BusProviderAdapter, CarRouteProviderAdapter, SerpApiFlightAdapter, TrainProviderAdapter
from transport.strategies import BusStrategy, FlightStrategy, MixedTransportStrategy, TrainStrategy, TransportStrategy


class TransportStrategyFactory:
    @staticmethod
    def estimate_distance(origin: str, destination: str) -> int:
        origin_city = canonicalize_location(origin)
        destination_city = canonicalize_location(destination)
        origin_resolved = resolve_location(origin)
        destination_resolved = resolve_location(destination)
        if (
            origin_resolved.lat is not None
            and origin_resolved.lon is not None
            and destination_resolved.lat is not None
            and destination_resolved.lon is not None
        ):
            return int(_distance_km(origin_resolved.lat, origin_resolved.lon, destination_resolved.lat, destination_resolved.lon))

        short_routes = {
            ("Ho Chi Minh", "Vung Tau"), ("Vung Tau", "Ho Chi Minh"),
            ("Ho Chi Minh", "Can Tho"), ("Can Tho", "Ho Chi Minh"),
            ("Da Nang", "Hoi An"), ("Hoi An", "Da Nang"),
            ("Da Nang", "Hue"), ("Hue", "Da Nang"),
            ("Ha Noi", "Ninh Binh"), ("Ninh Binh", "Ha Noi"),
            ("Ha Noi", "Ha Long"), ("Ha Long", "Ha Noi"),
            ("Ha Noi", "Tam Dao"), ("Tam Dao", "Ha Noi"),
        }
        medium_routes = {
            ("Ha Noi", "Hue"), ("Hue", "Ha Noi"),
            ("Ha Noi", "Da Nang"), ("Da Nang", "Ha Noi"),
            ("Ho Chi Minh", "Da Nang"), ("Da Nang", "Ho Chi Minh"),
            ("Ha Noi", "Da Lat"), ("Da Lat", "Ha Noi"),
            ("Ho Chi Minh", "Da Lat"), ("Da Lat", "Ho Chi Minh"),
        }

        if (origin_city, destination_city) in short_routes:
            return 120
        if (origin_city, destination_city) in medium_routes:
            return 650
        if origin_city in {"Ha Noi", "Ho Chi Minh"} and destination_city in {"Da Nang", "Ha Noi", "Ho Chi Minh", "Da Lat", "Hue", "Nha Trang", "Phu Quoc", "Con Dao"}:
            return 800
        if destination_city in {"Vung Tau", "Can Tho", "Hoi An", "Ninh Binh"}:
            return 180
        return 400

    @staticmethod
    def create(request: UserRequest) -> TransportStrategy:
        distance = TransportStrategyFactory.estimate_distance(request.origin, request.destination)
        preferred_transport = (request.preferred_transport or "").strip().lower()

        if preferred_transport == "train":
            return MixedTransportStrategy([
                TrainProviderAdapter(),
                BusProviderAdapter(),
                SerpApiFlightAdapter(),
                CarRouteProviderAdapter(),
            ])
        if preferred_transport == "flight":
            return MixedTransportStrategy([
                SerpApiFlightAdapter(),
                TrainProviderAdapter(),
                BusProviderAdapter(),
                CarRouteProviderAdapter(),
            ])

        if distance > 700:
            return MixedTransportStrategy([
                TrainProviderAdapter(),
                SerpApiFlightAdapter(),
                BusProviderAdapter(),
                CarRouteProviderAdapter(),
            ])
        if distance > 250:
            return MixedTransportStrategy([
                TrainProviderAdapter(),
                BusProviderAdapter(),
                SerpApiFlightAdapter(),
                CarRouteProviderAdapter(),
            ])
        return MixedTransportStrategy([
            BusProviderAdapter(),
            TrainProviderAdapter(),
            CarRouteProviderAdapter(),
        ])
