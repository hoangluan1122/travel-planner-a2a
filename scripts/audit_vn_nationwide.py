from __future__ import annotations

import json
from pathlib import Path

from agents.hotel_agent import HotelAgent
from agents.root_agent import RootTravelPlannerAgent
from schemas.models import UserRequest
from services.location_resolver import load_registry, resolve_location
from services.live_travel_service import fetch_live_hotels

ORIGIN = "Ha Noi"
DEPARTURE_DATE = "2026-05-10"
DAYS = 3
BUDGET = 8_000_000
TRAVELERS = 2
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "vn_nationwide_audit.json"


def build_request(destination: str) -> UserRequest:
    return UserRequest(
        destination=destination,
        origin=ORIGIN,
        lang="vi",
        departure_date=DEPARTURE_DATE,
        days=DAYS,
        budget=BUDGET,
        travelers=TRAVELERS,
        interests=["photo", "food"],
    )


def main() -> None:
    records = []
    root = RootTravelPlannerAgent()
    hotel_agent = HotelAgent()

    for record in load_registry():
        req = build_request(record.name)
        resolved = resolve_location(record.name)

        raw_hotels = fetch_live_hotels(
            record.name,
            limit=5,
            checkin_date=DEPARTURE_DATE,
            checkout_date="2026-05-12",
            adults=TRAVELERS,
            rooms=1,
        )
        hotel_result = hotel_agent.run(req)
        plan = root.run(req)

        records.append(
            {
                "destination": record.name,
                "kind": record.kind,
                "resolved": {
                    "canonical_name": resolved.canonical_name,
                    "iata": resolved.iata,
                    "nearest_airport_hub": resolved.nearest_airport_hub,
                    "nearest_train_hub": resolved.nearest_train_hub,
                    "nearest_bus_hub": resolved.nearest_bus_hub,
                },
                "hotel": {
                    "raw_count": len(raw_hotels),
                    "raw_preview": [
                        {
                            "name": h.get("name"),
                            "price_per_night": h.get("price_per_night"),
                            "currency": h.get("currency"),
                            "source": h.get("source"),
                        }
                        for h in raw_hotels[:3]
                    ],
                    "status": hotel_result.status,
                    "notes": hotel_result.notes,
                    "shortlist_count": len(hotel_result.recommendations),
                    "shortlist_preview": [
                        {
                            "title": h.title,
                            "price": h.price,
                            "details": h.details,
                        }
                        for h in hotel_result.recommendations[:3]
                    ],
                },
                "transport": {
                    "status": (plan.provider_status.get("transport") or {}).get("status"),
                    "count": len(plan.transport_options),
                    "titles": [item.title for item in plan.transport_options[:5]],
                },
                "attractions": {
                    "status": (plan.provider_status.get("attractions") or {}).get("status"),
                    "count": len(plan.attractions),
                },
                "summary": {
                    "hotel_ok": hotel_result.status == "ok" and len(hotel_result.recommendations) > 0,
                    "transport_ok": len(plan.transport_options) > 0,
                    "full_case_ok": hotel_result.status == "ok" and len(hotel_result.recommendations) > 0 and len(plan.transport_options) > 0,
                },
            }
        )
        print(f"AUDITED {record.name}: hotel_raw={len(raw_hotels)} hotel_shortlist={len(hotel_result.recommendations)} transport={len(plan.transport_options)}")

    totals = {
        "total_locations": len(records),
        "hotel_ok": sum(1 for r in records if r["summary"]["hotel_ok"]),
        "transport_ok": sum(1 for r in records if r["summary"]["transport_ok"]),
        "full_case_ok": sum(1 for r in records if r["summary"]["full_case_ok"]),
    }

    OUTPUT_PATH.write_text(json.dumps({"totals": totals, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    print(f"Saved audit to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
