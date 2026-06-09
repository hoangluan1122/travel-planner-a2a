from __future__ import annotations

import json

from schemas.models import UserRequest
from transport.providers import BusProviderAdapter, SerpApiFlightAdapter, TrainProviderAdapter
from services.live_travel_service import fetch_live_hotels, fetch_live_attractions

PROBE_CASES = [
    UserRequest(destination='Nam Dinh', origin='HAN', days=2, budget=4_000_000, interests=['food'], travelers=2),
    UserRequest(destination='Da Lat', origin='HAN', days=3, budget=8_000_000, interests=['nature'], travelers=2),
    UserRequest(destination='Ho Chi Minh', origin='HAN', days=3, budget=8_000_000, interests=['history'], travelers=2),
]


def main() -> None:
    flight = SerpApiFlightAdapter()
    train = TrainProviderAdapter()
    bus = BusProviderAdapter()
    rows = []
    for req in PROBE_CASES:
        flight_rows = flight.search(req)
        train_rows = train.search(req)
        bus_rows = bus.search(req)
        hotels = fetch_live_hotels(req.destination, req.budget)
        attractions = fetch_live_attractions(req.destination, req.interests, {})
        rows.append({
            'destination': req.destination,
            'flight_count': len(flight_rows),
            'train_count': len(train_rows),
            'bus_count': len(bus_rows),
            'hotel_count': len(hotels),
            'attraction_count': len(attractions),
            'flight_nearest_hub': any(x.uses_nearest_hub for x in flight_rows),
            'train_nearest_hub': any(x.uses_nearest_hub for x in train_rows),
            'bus_nearest_hub': any(x.uses_nearest_hub for x in bus_rows),
            'flight_titles': [f'{x.departure}->{x.arrival}' for x in flight_rows[:3]],
            'train_titles': [f'{x.departure}->{x.arrival}' for x in train_rows[:3]],
            'bus_titles': [f'{x.departure}->{x.arrival}' for x in bus_rows[:3]],
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
