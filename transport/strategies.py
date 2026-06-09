from __future__ import annotations

from abc import ABC, abstractmethod
import math

from schemas.models import UserRequest
from services.location_resolver import resolve_location
from transport.models import TransportOption
from transport.providers import TransportProviderAdapter


class TransportStrategy(ABC):
    @abstractmethod
    def get_options(self, request: UserRequest) -> list[TransportOption]:
        raise NotImplementedError


class FlightStrategy(TransportStrategy):
    def __init__(self, provider: TransportProviderAdapter):
        self.provider = provider

    def get_options(self, request: UserRequest) -> list[TransportOption]:
        options = self.provider.search(request)
        for option in options:
            provider_reason = option.reason.strip()
            strategy_reason = "Flight selected for long-distance route."
            option.reason = f"{strategy_reason} {provider_reason}".strip() if provider_reason else strategy_reason
        return options


class TrainStrategy(TransportStrategy):
    def __init__(self, provider: TransportProviderAdapter):
        self.provider = provider

    def get_options(self, request: UserRequest) -> list[TransportOption]:
        options = self.provider.search(request)
        for option in options:
            provider_reason = option.reason.strip()
            strategy_reason = "Train selected for medium-distance route."
            option.reason = f"{strategy_reason} {provider_reason}".strip() if provider_reason else strategy_reason
        return options


class BusStrategy(TransportStrategy):
    def __init__(self, provider: TransportProviderAdapter):
        self.provider = provider

    def get_options(self, request: UserRequest) -> list[TransportOption]:
        options = self.provider.search(request)
        for option in options:
            provider_reason = option.reason.strip()
            strategy_reason = "Bus selected for short-distance route."
            option.reason = f"{strategy_reason} {provider_reason}".strip() if provider_reason else strategy_reason
        return options


class MixedTransportStrategy(TransportStrategy):
    def __init__(self, providers: list[TransportProviderAdapter]):
        self.providers = providers

    @staticmethod
    def _location_variants(location: str) -> list[str]:
        resolved = resolve_location(location)
        values = [
            resolved.canonical_name,
            resolved.iata or "",
            resolved.nearest_airport_hub or "",
            resolved.nearest_train_hub or "",
            resolved.nearest_bus_hub or "",
        ]
        seen: set[str] = set()
        variants: list[str] = []
        for value in values:
            value = (value or "").strip()
            key = value.lower()
            if value and key not in seen:
                seen.add(key)
                variants.append(value)
        return variants

    @staticmethod
    def _candidate_hubs(request: UserRequest) -> list[str]:
        origin = resolve_location(request.origin)
        destination = resolve_location(request.destination)
        connector_hubs = [
            "Ho Chi Minh",
            "Ha Noi",
            "Da Nang",
            "Nha Trang",
            "Hai Phong",
            "Hue",
            "Pleiku",
            "Quy Nhon",
            "Vinh",
            "Can Tho",
        ]
        candidates = [
            destination.nearest_airport_hub or "",
            destination.nearest_train_hub or "",
            destination.nearest_bus_hub or "",
            origin.nearest_airport_hub or "",
            origin.nearest_train_hub or "",
            origin.nearest_bus_hub or "",
            *connector_hubs,
        ]
        banned = {
            origin.canonical_name.lower(),
            destination.canonical_name.lower(),
            (request.origin or "").strip().lower(),
            (request.destination or "").strip().lower(),
        }
        seen: set[str] = set()
        hubs: list[str] = []
        for candidate in candidates:
            candidate = (candidate or "").strip()
            key = candidate.lower()
            if candidate and key not in seen and key not in banned:
                seen.add(key)
                hubs.append(candidate)
        return hubs

    @staticmethod
    def _duration_to_minutes(duration: str) -> int:
        if not duration:
            return 99999
        total = 0
        lowered = duration.lower()
        if "h" in lowered:
            try:
                hours = int(lowered.split("h")[0].strip())
                total += hours * 60
                rest = lowered.split("h", 1)[1]
                if "m" in rest:
                    mins_text = rest.split("m")[0].strip()
                    if mins_text.isdigit():
                        total += int(mins_text)
            except Exception:
                return 99999
        return total or 99999

    @staticmethod
    def _geo_distance_km(request: UserRequest) -> float | None:
        origin = resolve_location(request.origin)
        destination = resolve_location(request.destination)
        if origin.lat is None or origin.lon is None or destination.lat is None or destination.lon is None:
            return None
        radius_km = 6371.0
        dlat = math.radians(destination.lat - origin.lat)
        dlon = math.radians(destination.lon - origin.lon)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(origin.lat))
            * math.cos(math.radians(destination.lat))
            * math.sin(dlon / 2) ** 2
        )
        return 2 * radius_km * math.asin(math.sqrt(a))

    def _connecting_options(self, request: UserRequest) -> list[TransportOption]:
        providers = [
            provider
            for provider in self.providers
            if provider.__class__.__name__ in {"SerpApiFlightAdapter", "TrainProviderAdapter", "BusProviderAdapter"}
        ]
        if len(providers) < 2:
            return []
        if not any(provider.__class__.__name__ == "SerpApiFlightAdapter" for provider in providers):
            return []

        options: list[TransportOption] = []
        seen: set[tuple[str, str, str, str, int]] = set()
        destination_variants = {value.lower() for value in self._location_variants(request.destination)}

        for hub in self._candidate_hubs(request):
            hub_variants = {value.lower() for value in self._location_variants(hub)}
            first_leg_request = request.model_copy(update={"destination": hub})
            second_leg_request = request.model_copy(update={"origin": hub})

            first_legs: list[TransportOption] = []
            second_legs: list[TransportOption] = []
            for provider in providers:
                first_legs.extend(provider.search(first_leg_request)[:3])
                second_legs.extend(provider.search(second_leg_request)[:3])

            if not first_legs or not second_legs:
                continue

            for first_leg in first_legs[:6]:
                first_arrival = (first_leg.arrival or "").lower()
                if not any(variant in first_arrival for variant in hub_variants):
                    continue
                for second_leg in second_legs[:6]:
                    second_departure = (second_leg.departure or "").lower()
                    second_arrival = (second_leg.arrival or "").lower()
                    if not any(variant in second_departure for variant in hub_variants):
                        continue
                    if not any(variant in second_arrival for variant in destination_variants):
                        continue

                    total_price = int(first_leg.price or 0) + int(second_leg.price or 0)
                    if total_price <= 0:
                        continue
                    signature = (
                        first_leg.provider,
                        second_leg.provider,
                        first_leg.operator,
                        second_leg.operator,
                        total_price,
                    )
                    if signature in seen:
                        continue
                    seen.add(signature)
                    reason = (
                        f"Ket hop du lieu live vi tuyen truc tiep chua co ket qua: "
                        f"{first_leg.provider} cho chang {request.origin} -> {hub}, "
                        f"{second_leg.provider} cho chang {hub} -> {request.destination}."
                    )
                    options.append(
                        TransportOption(
                            mode="mixed",
                            provider=f"{first_leg.provider} + {second_leg.provider}",
                            operator=f"{first_leg.operator} + {second_leg.operator}",
                            departure=request.origin,
                            arrival=f"{request.destination} via {hub}",
                            price=total_price,
                            duration=second_leg.duration or first_leg.duration,
                            score=0.0,
                            reason=reason,
                            uses_nearest_hub=True,
                            destination_hub=hub,
                        )
                    )
        return options[:8]

    @staticmethod
    def _score_option(option: TransportOption, request: UserRequest) -> tuple[float, str, str]:
        budget = max(request.budget, 1)
        price_ratio = option.price / budget if option.price > 0 else 1
        duration_minutes = MixedTransportStrategy._duration_to_minutes(option.duration)

        affordability = 5.0
        if price_ratio <= 0.12:
            affordability = 5.0
        elif price_ratio <= 0.2:
            affordability = 4.5
        elif price_ratio <= 0.3:
            affordability = 3.8
        elif price_ratio <= 0.45:
            affordability = 2.8
        else:
            affordability = 1.2

        speed = 2.5
        if duration_minutes <= 90:
            speed = 5.0
        elif duration_minutes <= 180:
            speed = 4.3
        elif duration_minutes <= 360:
            speed = 3.5
        elif duration_minutes <= 720:
            speed = 2.5
        else:
            speed = 1.5

        distance_fit = 3.5
        if option.mode == "bus":
            distance_fit = 4.8 if duration_minutes <= 240 else 2.0
        elif option.mode == "train":
            distance_fit = 4.5 if 180 <= duration_minutes <= 1200 else 3.2
        elif option.mode == "flight":
            distance_fit = 4.8 if duration_minutes <= 240 else 4.2
        elif option.mode == "mixed":
            distance_fit = 4.0 if duration_minutes <= 720 else 3.0

        total_score = round(affordability * 0.45 + speed * 0.25 + distance_fit * 0.30, 2)

        if price_ratio <= 0.15:
            tag = "Tiet kiem"
            reason = "Chi phi rat tot so voi ngan sach."
        elif duration_minutes <= 120 and option.mode == "flight":
            tag = "Nhanh nhat"
            reason = "Tiet kiem thoi gian di chuyen dang ke."
        elif price_ratio <= 0.3 and duration_minutes <= 480:
            tag = "Can bang"
            reason = "Can bang kha tot giua chi phi va thoi gian."
        else:
            tag = "Phu hop tuyen"
            reason = "Phu hop voi loai hanh trinh hien tai."

        return total_score, tag, reason

    def get_options(self, request: UserRequest) -> list[TransportOption]:
        road_results: list[TransportOption] = []
        public_providers: list[TransportProviderAdapter] = []
        for provider in self.providers:
            if provider.__class__.__name__ == 'CarRouteProviderAdapter':
                road_results.extend(provider.search(request))
            else:
                public_providers.append(provider)

        results: list[TransportOption] = []
        for provider in public_providers:
            results.extend(provider.search(request))
        if not results:
            if any(provider.__class__.__name__ == "SerpApiFlightAdapter" for provider in public_providers):
                results.extend(self._connecting_options(request))
        if not results:
            results.extend(road_results)

        scored: list[TransportOption] = []
        for option in results:
            score, tag, reason = self._score_option(option, request)
            provider_reason = option.reason.strip()
            option.score = score
            option.tag = tag
            option.reason = f"{reason} {provider_reason}".strip() if provider_reason else reason
            scored.append(option)

        nearby_distance = self._geo_distance_km(request)
        if nearby_distance is not None and nearby_distance <= 300 and any(option.mode == "bus" for option in scored):
            scored.sort(
                key=lambda option: (
                    0 if option.mode == "bus" else 1,
                    option.price if option.price > 0 else 10**9,
                    self._duration_to_minutes(option.duration),
                    -option.score,
                )
            )
        else:
            scored.sort(key=lambda option: (-option.score, option.price if option.price > 0 else 10**9))
        if scored:
            scored[0].tag = "De xuat chinh"
            provider_reason = scored[0].reason.strip()
            if nearby_distance is not None and nearby_distance <= 300 and scored[0].mode == "bus":
                primary_reason = "Phuong an xe khach gia tot cho diem den gan, uu tien tiet kiem chi phi di chuyen."
            else:
                primary_reason = "Phuong an phu hop nhat dua tren chi phi, thoi gian va muc phu hop ngan sach."
            scored[0].reason = f"{primary_reason} {provider_reason}".strip() if provider_reason else primary_reason
        return scored[:8]
