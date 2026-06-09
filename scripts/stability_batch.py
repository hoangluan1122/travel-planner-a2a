from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.root_agent import RootTravelPlannerAgent
from services.request_parser import parse_user_request

CASES = [
    ("Da Lat", 4, 8_000_000, "2026-05-10"),
    ("Da Nang", 3, 7_000_000, "2026-05-10"),
    ("Nha Trang", 3, 8_000_000, "2026-05-10"),
    ("Ha Long", 3, 7_000_000, "2026-05-10"),
    ("Phu Quoc", 3, 10_000_000, "2026-05-10"),
    ("Hue", 3, 7_000_000, "2026-05-10"),
    ("Hoi An", 3, 7_000_000, "2026-05-10"),
]

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "stability_batch_latest.json"


def run_case(dest: str, days: int, budget: int, departure_date: str) -> dict:
    req = parse_user_request(f"Tôi muốn đi {dest} {days} ngày với ngân sách {budget}", origin="Ha Noi")
    req.lang = "vi"
    req.departure_date = departure_date
    req.days = days
    req.budget = budget
    result = RootTravelPlannerAgent().run(req)
    return {
        "destination": dest,
        "days": days,
        "budget": budget,
        "departure_date": departure_date,
        "provider_status": result.provider_status,
        "transport_count": len(result.transport_options),
        "hotel_count": len(result.hotels),
        "attraction_count": len(result.attractions),
        "transport_titles": [x.title for x in result.transport_options[:5]],
        "hotel_titles": [x.title for x in result.hotels[:5]],
        "attraction_titles": [x.title for x in result.attractions[:5]],
        "estimated_cost": result.estimated_cost,
    }


def main() -> None:
    rows = []
    for dest, days, budget, departure_date in CASES:
        row = run_case(dest, days, budget, departure_date)
        rows.append(row)
        print(f"{dest}: transport={row['transport_count']} hotel={row['hotel_count']} attractions={row['attraction_count']}")

    summary = {
        "total_cases": len(rows),
        "transport_ok": sum(1 for r in rows if r["transport_count"] > 0),
        "hotel_ok": sum(1 for r in rows if r["hotel_count"] > 0),
        "attraction_ok": sum(1 for r in rows if r["attraction_count"] > 0),
        "full_case_ok": sum(1 for r in rows if r["transport_count"] > 0 and r["hotel_count"] > 0 and r["attraction_count"] > 0),
    }

    OUTPUT.write_text(json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved to {OUTPUT}")


if __name__ == "__main__":
    main()
