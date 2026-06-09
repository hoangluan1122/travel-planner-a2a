from __future__ import annotations

import json

from services.request_parser import parse_user_request
from services.location_resolver import resolve_location

CASES = [
    {"origin": "Ha Noi", "text": "Toi muon di Nam Dinh 2 ngay voi ngan sach 4 trieu cho 2 nguoi."},
    {"origin": "Ha Noi", "text": "Toi muon di Hai Phong 2 ngay voi ngan sach 5 trieu."},
    {"origin": "Ha Noi", "text": "Toi muon di Ha Long 3 ngay voi ngan sach 6 trieu cho 2 nguoi."},
    {"origin": "Ha Noi", "text": "Toi muon di Ha Giang 3 ngay voi ngan sach 7 trieu cho 2 nguoi."},
    {"origin": "Ha Noi", "text": "Toi muon di Da Lat 3 ngay voi ngan sach 8 trieu cho 2 nguoi."},
    {"origin": "Ha Noi", "text": "Toi muon di thanh pho Ho Chi Minh 3 ngay voi ngan sach 8 trieu cho 2 nguoi."},
]


def main() -> None:
    rows = []
    for case in CASES:
        parsed = parse_user_request(case["text"], origin=case["origin"])
        destination = resolve_location(parsed.destination)
        rows.append(
            {
                "text": case["text"],
                "origin_input": case["origin"],
                "parsed_origin": parsed.origin,
                "parsed_destination": parsed.destination,
                "resolved_destination": destination.canonical_name,
                "matched_by": destination.matched_by,
                "nearest_airport_hub": destination.nearest_airport_hub,
                "nearest_train_hub": destination.nearest_train_hub,
                "nearest_bus_hub": destination.nearest_bus_hub,
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
