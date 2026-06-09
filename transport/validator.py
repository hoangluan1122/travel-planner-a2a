from __future__ import annotations

from services.location_resolver import resolve_location
from transport.models import TransportOption


class TransportValidator:
    """Rule-based quality gate for transport output before UI rendering."""

    @staticmethod
    def _normalized(value: str) -> str:
        return (value or '').strip().lower()

    @staticmethod
    def _signature(option: TransportOption) -> tuple[str, str, str, str, int]:
        return (
            option.mode,
            option.operator.strip().lower(),
            option.departure.strip().lower(),
            option.arrival.strip().lower(),
            int(option.price or 0),
        )

    def validate(self, option: TransportOption, request_origin: str, request_destination: str) -> tuple[bool, list[str]]:
        notes: list[str] = []
        origin = resolve_location(request_origin)
        destination = resolve_location(request_destination)
        departure_text = self._normalized(option.departure)
        arrival_text = self._normalized(option.arrival)
        origin_name = self._normalized(origin.canonical_name)
        destination_name = self._normalized(destination.canonical_name)
        origin_bus_hub = self._normalized(origin.nearest_bus_hub or '')
        destination_bus_hub = self._normalized(destination.nearest_bus_hub or '')

        expected_origin_values = {
            origin_name,
            self._normalized(origin.nearest_airport_hub or ''),
            self._normalized(origin.nearest_train_hub or ''),
            origin_bus_hub,
            self._normalized(origin.iata or ''),
        }
        expected_destination_values = {
            destination_name,
            self._normalized(destination.nearest_airport_hub or ''),
            self._normalized(destination.nearest_train_hub or ''),
            destination_bus_hub,
            self._normalized(destination.iata or ''),
        }
        expected_origin_values.discard('')
        expected_destination_values.discard('')

        if not any(value in departure_text for value in expected_origin_values):
            notes.append('departure-mismatch')
        if not any(value in arrival_text for value in expected_destination_values):
            notes.append('arrival-mismatch')

        if option.price < 0:
            notes.append('negative-price')
        if option.uses_nearest_hub and not (option.origin_hub or option.destination_hub):
            notes.append('nearest-hub-flag-missing-metadata')

        if option.mode == 'bus':
            same_real_place = origin_name == destination_name
            same_departure_arrival = departure_text == arrival_text
            route_loops_on_origin_hub = bool(origin_bus_hub) and departure_text.startswith(origin_bus_hub) and arrival_text.startswith(origin_bus_hub)
            route_loops_on_destination_hub = bool(destination_bus_hub) and departure_text.startswith(destination_bus_hub) and arrival_text.startswith(destination_bus_hub)
            if not same_real_place and (same_departure_arrival or route_loops_on_origin_hub or route_loops_on_destination_hub):
                notes.append('self-loop-bus-route')

        return (len(notes) == 0), notes

    def filter_options(self, options: list[TransportOption], request_origin: str, request_destination: str) -> tuple[list[TransportOption], list[str]]:
        accepted: list[TransportOption] = []
        dropped_notes: list[str] = []
        seen_signatures: set[tuple[str, str, str, str, int]] = set()
        for option in options:
            ok, notes = self.validate(option, request_origin, request_destination)
            if not ok:
                dropped_notes.append(f"Dropped {option.mode}:{option.operator}:{option.departure}->{option.arrival} because {', '.join(notes)}")
                continue
            signature = self._signature(option)
            if signature in seen_signatures:
                dropped_notes.append(f"Dropped duplicate {option.mode}:{option.operator}:{option.departure}->{option.arrival}")
                continue
            seen_signatures.add(signature)
            accepted.append(option)
        return accepted, dropped_notes
