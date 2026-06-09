from __future__ import annotations

from agents.weather_agent import WeatherAgent
from schemas.models import AgentResult, Recommendation, UserRequest
from services.live_travel_service import fetch_live_attractions
from services.location_service import canonicalize_location


class AttractionAgent:
    name = "attraction-agent"

    def __init__(self, weather_agent: WeatherAgent | None = None):
        self.weather_agent = weather_agent or WeatherAgent()

    def run(self, request: UserRequest, weather: AgentResult | None = None) -> AgentResult:
        weather = weather or self.weather_agent.run(request)
        destination = canonicalize_location(request.destination)
        attractions = fetch_live_attractions(destination)
        debug = {
            "request_destination": request.destination,
            "canonical_destination": destination,
            "service_count": len(attractions),
            "service_preview": attractions[:5],
        }

        if not attractions:
            return AgentResult(
                agent=self.name,
                summary="No live attraction data available.",
                recommendations=[],
                notes=weather.notes + ["No live attraction result returned from providers."],
                source="No live data",
                status="empty",
                extra={"debug": debug},
            )

        source = attractions[0].get("source", "Unknown")
        notes = weather.notes + [f"Live attraction source active: {source}."]

        results = []
        for a in attractions:
            interest_overlap = len(set(i.lower() for i in request.interests) & set(tag.lower() for tag in a["interest_tags"]))
            weather_penalty = 0
            lowered_weather = weather.summary.lower()
            if ("rain" in lowered_weather or "mưa" in lowered_weather) and a["type"] == "outdoor":
                weather_penalty = 1.5
            score = round(3 + interest_overlap * 2 - weather_penalty, 2)
            results.append(Recommendation(
                title=a["name"],
                details=f"Type: {a['type']} | Tags: {', '.join(a['interest_tags'])} | Source: {a['source']}",
                price=a["cost"],
                score=score,
                reason=f"Matched interests and adjusted by weather: {weather.summary}",
                image_url=a.get("photo_url") or "",
            ))
        results.sort(key=lambda x: (-x.score, x.price))
        debug["final_count"] = len(results[:6])
        debug["final_titles"] = [item.title for item in results[:6]]
        return AgentResult(
            agent=self.name,
            summary="Live attractions ranked with help from weather context.",
            recommendations=results[:6],
            notes=notes,
            source=source,
            status="ok",
            extra={"debug": debug},
        )
