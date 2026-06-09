from __future__ import annotations

from schemas.models import AgentResult, Recommendation, UserRequest
from services.live_travel_service import fetch_live_flights
from services.location_service import canonicalize_location


class FlightAgent:
    name = "flight-agent"

    def run(self, request: UserRequest) -> AgentResult:
        destination = canonicalize_location(request.destination)
        flights = fetch_live_flights(
            destination,
            adults=request.travelers,
            max_price=request.budget,
            origin=request.origin,
        )

        if not flights:
            return AgentResult(
                agent=self.name,
                summary="No live flight data available.",
                recommendations=[],
                notes=["No flight result returned for this query."],
                source="SerpAPI Google Flights",
                status="empty",
            )

        scored = []
        for f in flights:
            price_score = max(0, 100 - (f["price"] / max(request.budget, 1)) * 100)
            score = round(price_score / 20, 2)
            scored.append(Recommendation(
                title=f"{f['airline']} {f['departure']} -> {f['arrival']}",
                details=f"Flight from {request.origin} to {request.destination} via {f['source']}",
                price=f["price"],
                score=score,
                reason="Lower price gets higher score.",
            ))
        scored.sort(key=lambda x: (-x.score, x.price))
        return AgentResult(
            agent=self.name,
            summary=f"Found {len(scored)} live flight options.",
            recommendations=scored[:3],
            notes=["Flight source active."],
            source="SerpAPI Google Flights",
            status="ok",
        )
