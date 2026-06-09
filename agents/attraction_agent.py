from __future__ import annotations

import re
import unicodedata
from typing import Literal, TypedDict

from agents.weather_agent import WeatherAgent
from schemas.models import AgentResult, Recommendation, UserRequest
from services.live_travel_service import fetch_activity_attractions, fetch_curated_activity_attractions
from services.location_service import canonicalize_location

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # keeps the app runnable before dependencies are installed
    END = START = None
    StateGraph = None


class AttractionState(TypedDict):
    request: UserRequest
    weather: AgentResult
    hotel_context: dict
    destination: str
    interests: list[str]
    activity_intents: list[str]
    strategy: str
    live_places: list[dict]
    curated_places: list[dict]
    scored_places: list[dict]
    recommendations: list[Recommendation]
    notes: list[str]
    issues: list[str]
    debug: dict


class AttractionAgent:
    name = "attraction-agent"

    def __init__(self, weather_agent: WeatherAgent | None = None):
        self.weather_agent = weather_agent or WeatherAgent()
        self.graph = self._build_graph() if StateGraph is not None else None

    def run(
        self,
        request: UserRequest,
        weather: AgentResult | None = None,
        hotel_context: dict | None = None,
    ) -> AgentResult:
        weather = weather or self.weather_agent.run(request)
        initial_state: AttractionState = {
            "request": request,
            "weather": weather,
            "hotel_context": hotel_context or {},
            "destination": canonicalize_location(request.destination),
            "interests": [item.lower() for item in request.interests],
            "activity_intents": [],
            "strategy": "general",
            "live_places": [],
            "curated_places": [],
            "scored_places": [],
            "recommendations": [],
            "notes": list(weather.notes),
            "issues": [],
            "debug": {
                "request_destination": request.destination,
                "canonical_destination": canonicalize_location(request.destination),
                "hotel_context": hotel_context or {},
            },
        }

        if self.graph is not None:
            state = self.graph.invoke(initial_state)
        else:
            state = self._detect_activity_intent(initial_state)
            state = {**initial_state, **state}
            state = {**state, **self._resolve_hotel_context(state)}
            state = {**state, **self._choose_search_strategy(state)}
            state = {**state, **self._fetch_live_places(state)}
            if self._needs_curated_fallback(state) == "curated":
                state = {**state, **self._fetch_curated_places(state)}
            state = {**state, **self._score_and_filter_places(state)}
            state = {**state, **self._build_agent_payload(state)}

        recommendations = state["recommendations"]
        source = self._source_label(state)
        status = "ok" if recommendations else "empty"
        summary = (
            f"Attractions ranked by {state['strategy']} strategy with hotel and weather context."
            if recommendations
            else "No attraction data matched the requested activity."
        )
        notes = state["notes"]
        if not recommendations:
            notes = notes + ["No attraction result matched the requested activity from live or curated providers."]

        return AgentResult(
            agent=self.name,
            summary=summary,
            recommendations=recommendations,
            notes=notes,
            source=source,
            status=status,
            extra={"debug": state["debug"]},
        )

    def _build_graph(self):
        graph = StateGraph(AttractionState)
        graph.add_node("detect_activity_intent", self._detect_activity_intent)
        graph.add_node("resolve_hotel_context", self._resolve_hotel_context)
        graph.add_node("choose_search_strategy", self._choose_search_strategy)
        graph.add_node("fetch_live_places", self._fetch_live_places)
        graph.add_node("fetch_curated_places", self._fetch_curated_places)
        graph.add_node("score_and_filter_places", self._score_and_filter_places)
        graph.add_node("build_agent_payload", self._build_agent_payload)
        graph.add_edge(START, "detect_activity_intent")
        graph.add_edge("detect_activity_intent", "resolve_hotel_context")
        graph.add_edge("resolve_hotel_context", "choose_search_strategy")
        graph.add_edge("choose_search_strategy", "fetch_live_places")
        graph.add_conditional_edges(
            "fetch_live_places",
            self._needs_curated_fallback,
            {"curated": "fetch_curated_places", "score": "score_and_filter_places"},
        )
        graph.add_edge("fetch_curated_places", "score_and_filter_places")
        graph.add_edge("score_and_filter_places", "build_agent_payload")
        graph.add_edge("build_agent_payload", END)
        return graph.compile()

    def _detect_activity_intent(self, state: AttractionState) -> dict:
        interests = set(state["interests"])
        intents: list[str] = []
        if {"swimming", "beach"} & interests:
            intents.extend(["swimming", "beach"])
        if {"food", "coffee"} & interests:
            intents.append("food")
        if {"history", "culture"} & interests:
            intents.append("culture")
        if {"nature", "photo"} & interests:
            intents.append("nature")
        if {"shopping"} & interests:
            intents.append("shopping")
        if not intents:
            intents.append("general")
        return {
            "activity_intents": sorted(set(intents)),
            "debug": {**state["debug"], "activity_intents": sorted(set(intents))},
        }

    def _resolve_hotel_context(self, state: AttractionState) -> dict:
        context = dict(state.get("hotel_context") or {})
        if context.get("name") or context.get("area"):
            context.setdefault("confidence", "medium")
            return {"hotel_context": context, "debug": {**state["debug"], "hotel_context": context}}
        return {
            "hotel_context": {},
            "issues": state["issues"] + ["Hotel context unavailable; attraction distance scoring uses destination center only."],
            "debug": {**state["debug"], "hotel_context": {}},
        }

    def _choose_search_strategy(self, state: AttractionState) -> dict:
        strategy = "beach_swimming" if {"swimming", "beach"} & set(state["activity_intents"]) else "general"
        return {"strategy": strategy, "debug": {**state["debug"], "strategy": strategy}}

    def _fetch_live_places(self, state: AttractionState) -> dict:
        places = fetch_activity_attractions(
            state["destination"],
            strategy=state["strategy"],
            hotel_context=state["hotel_context"],
            limit=12,
        )
        return {
            "live_places": places,
            "debug": {
                **state["debug"],
                "live_count": len(places),
                "live_preview": places[:5],
            },
        }

    def _needs_curated_fallback(self, state: AttractionState) -> Literal["curated", "score"]:
        if state["strategy"] != "beach_swimming":
            return "score"
        relevant = [place for place in state["live_places"] if self._activity_match_score(place, state["activity_intents"]) >= 0.7]
        return "curated" if len(relevant) < 3 else "score"

    def _fetch_curated_places(self, state: AttractionState) -> dict:
        curated = fetch_curated_activity_attractions(state["destination"], strategy=state["strategy"], limit=8)
        return {
            "curated_places": curated,
            "notes": state["notes"] + ["Curated destination attractions were added because live activity-specific results were limited."],
            "debug": {
                **state["debug"],
                "curated_count": len(curated),
                "curated_preview": curated[:5],
            },
        }

    def _score_and_filter_places(self, state: AttractionState) -> dict:
        raw_places = state["live_places"] + state["curated_places"]
        scored: list[dict] = []
        filtered_out: list[dict] = []
        rainy = self._is_rainy(state["weather"].summary)

        for place in raw_places:
            activity_score = self._activity_match_score(place, state["activity_intents"])
            if state["strategy"] == "beach_swimming" and activity_score < 0.35:
                filtered_out.append({"name": place.get("name"), "tags": place.get("interest_tags", [])})
                continue
            interest_score = self._interest_score(place, state["interests"])
            distance_score, distance_method = self._distance_score(place, state["hotel_context"])
            weather_score = self._weather_score(place, rainy)
            source_score = self._source_score(place)
            score = round(
                activity_score * 3.5
                + interest_score * 2.0
                + distance_score * 2.0
                + weather_score * 1.5
                + source_score * 1.0,
                2,
            )
            scored.append(
                {
                    **place,
                    "score": score,
                    "activity_score": activity_score,
                    "interest_score": interest_score,
                    "distance_score": distance_score,
                    "weather_score": weather_score,
                    "source_score": source_score,
                    "distance_method": distance_method,
                }
            )

        scored.sort(key=lambda item: (-item["score"], item.get("cost", 0)))
        return {
            "scored_places": scored,
            "debug": {
                **state["debug"],
                "raw_count": len(raw_places),
                "filtered_out": filtered_out[:8],
                "distance_method": scored[0]["distance_method"] if scored else "none",
            },
        }

    def _build_agent_payload(self, state: AttractionState) -> dict:
        rainy = self._is_rainy(state["weather"].summary)
        recommendations: list[Recommendation] = []
        for place in state["scored_places"][:6]:
            tags = place.get("interest_tags", [])
            area = place.get("area") or state["hotel_context"].get("area") or state["destination"]
            source = place.get("source", "Unknown")
            distance = place.get("distance_to_hotel_km")
            distance_text = f" | Distance to stay: {distance} km" if distance is not None else ""
            details = f"Type: {place.get('type', 'outdoor')} | Area: {area} | Tags: {', '.join(tags)} | Source: {source}{distance_text}"
            reason_parts = [
                f"Activity fit for {', '.join(state['activity_intents'])}",
                f"near stay area: {state['hotel_context'].get('area', 'destination center')}",
                f"weather checked: {state['weather'].summary}",
            ]
            if rainy and place.get("type") == "outdoor":
                reason_parts.append("outdoor weather risk noted")
            if place.get("suitability"):
                reason_parts.append(place["suitability"])
            recommendations.append(
                Recommendation(
                    title=place.get("name", "Attraction"),
                    details=details,
                    price=int(place.get("cost") or 0),
                    score=float(place["score"]),
                    reason="; ".join(reason_parts),
                    image_url=place.get("photo_url") or "",
                )
            )

        return {
            "recommendations": recommendations,
            "notes": state["notes"] + [
                f"Attraction search strategy: {state['strategy']}.",
                f"Hotel context confidence: {state['hotel_context'].get('confidence', 'none')}.",
            ],
            "debug": {
                **state["debug"],
                "final_count": len(recommendations),
                "final_titles": [item.title for item in recommendations],
                "scored_preview": state["scored_places"][:5],
            },
        }

    @staticmethod
    def _activity_match_score(place: dict, intents: list[str]) -> float:
        tags = {str(tag).lower() for tag in place.get("interest_tags", [])}
        name = AttractionAgent._text_slug(place.get("name", ""))
        if {"swimming", "beach"} & set(intents):
            if {"swimming", "beach", "water_park"} & tags:
                return 1.0
            if any(term in name for term in ("beach", "bai", "bay", "dao", "island", "water park")):
                return 0.85
            if {"bay", "islet", "nature"} & tags:
                return 0.55
            if {"museum", "temple", "pagoda", "historic", "culture"} & tags:
                return 0.0
            return 0.25
        return 1.0

    @staticmethod
    def _interest_score(place: dict, interests: list[str]) -> float:
        tags = {str(tag).lower() for tag in place.get("interest_tags", [])}
        if not interests:
            return 0.5
        matched = len(set(interests) & tags)
        return min(matched / max(len(set(interests)), 1), 1.0)

    @staticmethod
    def _distance_score(place: dict, hotel_context: dict) -> tuple[float, str]:
        distance = place.get("distance_to_hotel_km")
        if distance is not None:
            if distance <= 3:
                return 1.0, "lat_lon"
            if distance <= 8:
                return 0.75, "lat_lon"
            if distance <= 18:
                return 0.45, "lat_lon"
            return 0.2, "lat_lon"

        hotel_area = AttractionAgent._text_slug(hotel_context.get("area", ""))
        place_area = AttractionAgent._text_slug(place.get("area", ""))
        name = AttractionAgent._text_slug(place.get("name", ""))
        if hotel_area and (hotel_area in place_area or hotel_area in name):
            return 0.9, "area_match"
        if hotel_area:
            area_terms = set(re.findall(r"[a-z0-9]+", hotel_area))
            place_terms = set(re.findall(r"[a-z0-9]+", f"{place_area} {name}"))
            if area_terms & place_terms:
                return 0.65, "area_token_match"
        return 0.45, "destination_center"

    @staticmethod
    def _weather_score(place: dict, rainy: bool) -> float:
        if not rainy:
            return 0.8
        tags = {str(tag).lower() for tag in place.get("interest_tags", [])}
        if place.get("type") == "indoor":
            return 1.0
        if "water_park" in tags:
            return 0.45
        return 0.2

    @staticmethod
    def _source_score(place: dict) -> float:
        source = str(place.get("source", "")).lower()
        if "curated" in source:
            return 0.85
        if "geoapify" in source or "openstreetmap" in source:
            return 0.75
        if "wikipedia" in source:
            return 0.55
        return 0.5

    @staticmethod
    def _is_rainy(summary: str) -> bool:
        text = AttractionAgent._text_slug(summary)
        return any(term in text for term in ("rain", "mua", "storm", "bao"))

    @staticmethod
    def _text_slug(value: str) -> str:
        text = (value or "").strip().lower().replace("đ", "d")
        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        return " ".join(text.split())

    @staticmethod
    def _source_label(state: AttractionState) -> str:
        sources = []
        for place in state["scored_places"]:
            source = place.get("source")
            if source and source not in sources:
                sources.append(source)
        return " + ".join(sources[:3]) if sources else "No attraction data"
