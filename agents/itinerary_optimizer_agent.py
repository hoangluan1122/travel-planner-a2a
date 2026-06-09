from __future__ import annotations

from typing import Literal, TypedDict

from schemas.models import DailyPlan, Recommendation, UserRequest
from services.location_resolver import resolve_location

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # keeps the app runnable before dependencies are installed
    END = START = None
    StateGraph = None


class ItineraryState(TypedDict):
    request: UserRequest
    weather_summary: str
    transport_options: list[Recommendation]
    hotel_options: list[Recommendation]
    attraction_options: list[Recommendation]
    scored_attractions: list[Recommendation]
    daily_itinerary: list[DailyPlan]
    total_cost: int
    budget_breakdown: dict
    optimization_score: float
    issues: list[str]
    decisions: list[str]
    revision_count: int


class ItineraryOptimizerAgent:
    name = "itinerary-optimizer-agent"

    def __init__(self):
        self.graph = self._build_graph() if StateGraph is not None else None

    def run(
        self,
        request: UserRequest,
        weather_summary: str,
        transport_options: list[Recommendation],
        hotel_options: list[Recommendation],
        attraction_options: list[Recommendation],
    ) -> dict:
        initial_state: ItineraryState = {
            "request": request,
            "weather_summary": weather_summary,
            "transport_options": transport_options,
            "hotel_options": hotel_options,
            "attraction_options": attraction_options,
            "scored_attractions": [],
            "daily_itinerary": [],
            "total_cost": 0,
            "budget_breakdown": {},
            "optimization_score": 0.0,
            "issues": [],
            "decisions": [],
            "revision_count": 0,
        }
        if self.graph is not None:
            return self.graph.invoke(initial_state)

        state = self._score_candidates(initial_state)
        state = {**initial_state, **state}
        state = {**state, **self._build_itinerary(state)}
        state = {**state, **self._evaluate_itinerary(state)}
        while self._should_revise(state) == "revise":
            state = {**state, **self._revise_itinerary(state)}
            state = {**state, **self._evaluate_itinerary(state)}
        return state

    def _build_graph(self):
        graph = StateGraph(ItineraryState)
        graph.add_node("score_candidates", self._score_candidates)
        graph.add_node("build_itinerary", self._build_itinerary)
        graph.add_node("evaluate_itinerary", self._evaluate_itinerary)
        graph.add_node("revise_itinerary", self._revise_itinerary)
        graph.add_edge(START, "score_candidates")
        graph.add_edge("score_candidates", "build_itinerary")
        graph.add_edge("build_itinerary", "evaluate_itinerary")
        graph.add_conditional_edges(
            "evaluate_itinerary",
            self._should_revise,
            {"revise": "revise_itinerary", "end": END},
        )
        graph.add_edge("revise_itinerary", "evaluate_itinerary")
        return graph.compile()

    def _score_candidates(self, state: ItineraryState) -> dict:
        request = state["request"]
        rainy = self._is_rainy(state["weather_summary"])
        tight_budget = self._budget_tier(request) == "tight"
        interests = {item.lower() for item in request.interests}
        scored: list[Recommendation] = []

        for item in state["attraction_options"]:
            text = self._text(item)
            score = item.score
            matched = [interest for interest in interests if interest and interest in text]
            score += min(len(matched) * 1.2, 3.0)
            if rainy and self._is_outdoor(text):
                score -= 1.8
            if rainy and self._is_indoor(text):
                score += 1.2
            if tight_budget and item.price > 0:
                score -= min(item.price / 250_000, 1.2)
            if item.price <= 0:
                score += 0.4
            if self._is_signature_experience(text):
                score += 0.5

            reason_bits = [
                f"optimizer score {round(score, 2)}",
                "matches interests" if matched else "balanced fit",
            ]
            if rainy and self._is_outdoor(text):
                reason_bits.append("weather risk for outdoor activity")
            if tight_budget:
                reason_bits.append("budget-sensitive ranking")
            scored.append(
                item.model_copy(
                    update={
                        "score": round(score, 2),
                        "reason": f"Itinerary optimizer: {', '.join(reason_bits)}. {item.reason}".strip(),
                    }
                )
            )

        scored.sort(key=lambda option: (-option.score, option.price if option.price > 0 else 0, option.title))
        return {
            "scored_attractions": scored,
            "decisions": state["decisions"]
            + [
                "Scored attractions by user interests, weather risk, ticket price, source score, and signature experience value."
            ],
        }

    def _build_itinerary(self, state: ItineraryState) -> dict:
        request = state["request"]
        destination = resolve_location(request.destination).canonical_name
        hotel_name = state["hotel_options"][0].title if state["hotel_options"] else "selected hotel"
        selected = self._select_unique_attractions(state["scored_attractions"], request.days)
        itinerary: list[DailyPlan] = []
        is_vi = (request.lang or "vi").lower() == "vi"

        if not selected:
            for day in range(1, request.days + 1):
                itinerary.append(
                    DailyPlan(
                        day=day,
                        title=(f"Ngay {day} - {destination}" if is_vi else f"Day {day} - {destination}"),
                        morning=(
                            f"Bat dau nhe quanh {destination}, giu lich linh hoat theo du lieu live."
                            if is_vi
                            else f"Start with a light exploration around {destination}, keeping the day flexible."
                        ),
                        afternoon=(
                            "Chon quan an, ca phe hoac diem trong nha tuy thoi tiet va ngan sach."
                            if is_vi
                            else "Choose food, cafe, or indoor stops based on weather and budget."
                        ),
                        evening=(f"An toi va nghi dem tai {hotel_name}." if is_vi else f"Dinner and overnight at {hotel_name}."),
                        estimated_cost=-1,
                    )
                )
            return {
                "daily_itinerary": itinerary,
                "decisions": state["decisions"] + ["Built fallback itinerary because no attraction candidates were available."],
            }

        for day in range(1, request.days + 1):
            attraction = selected[(day - 1) % len(selected)]
            is_last_day = day == request.days
            title_prefix = "Ngay" if is_vi else "Day"
            morning = (
                f"Uu tien {attraction.title} vao buoi sang de tranh qua tai lich trinh."
                if is_vi
                else f"Prioritize {attraction.title} in the morning to keep the schedule manageable."
            )
            afternoon = (
                f"Kham pha khu vuc lan can, an uong/ca phe dia phuong va giu chi phi trong ngan sach."
                if is_vi
                else "Explore nearby areas, local food or cafes, while keeping the day within budget."
            )
            if is_last_day:
                afternoon = (
                    "Giu buoi chieu nhe de mua sam nho, di chuyen noi do va chuan bi ve."
                    if is_vi
                    else "Keep the afternoon light for small shopping, local transfer, and departure prep."
                )
            itinerary.append(
                DailyPlan(
                    day=day,
                    title=f"{title_prefix} {day} - {attraction.title}",
                    morning=morning,
                    afternoon=afternoon,
                    evening=(f"An toi va nghi dem tai {hotel_name}." if is_vi else f"Dinner and overnight at {hotel_name}."),
                    estimated_cost=attraction.price if attraction.price > 0 else -1,
                )
            )

        return {
            "daily_itinerary": itinerary,
            "decisions": state["decisions"] + ["Built day-by-day itinerary with one primary attraction per day and lighter final day."],
        }

    def _evaluate_itinerary(self, state: ItineraryState) -> dict:
        request = state["request"]
        breakdown = self._build_budget_breakdown(state)
        issues: list[str] = []
        score = 10.0

        if len(state["daily_itinerary"]) != request.days:
            issues.append("itinerary_day_count_mismatch")
            score -= 2.0
        titles = [plan.title.lower() for plan in state["daily_itinerary"]]
        if len(titles) != len(set(titles)) and len(state["scored_attractions"]) >= request.days:
            issues.append("duplicated_attractions")
            score -= 1.3
        if breakdown["budget_gap"] > 0:
            issues.append("over_budget")
            score -= min(3.0, breakdown["budget_gap"] / max(request.budget, 1) * 6)
        if breakdown["attractions"] > request.budget * 0.25:
            issues.append("attraction_tickets_too_high")
            score -= 0.8
        if self._is_rainy(state["weather_summary"]) and self._has_many_outdoor_days(state):
            issues.append("too_many_outdoor_days_for_rain")
            score -= 1.0
        if not state["transport_options"]:
            issues.append("missing_transport_price_signal")
            score -= 0.5
        if not state["hotel_options"]:
            issues.append("missing_lodging_price_signal")
            score -= 0.5

        score = round(max(score, 0.0), 2)
        return {
            "total_cost": breakdown["total"],
            "budget_breakdown": breakdown,
            "optimization_score": score,
            "issues": issues,
            "decisions": state["decisions"] + [f"Evaluated itinerary budget and constraints with score {score}/10."],
        }

    def _should_revise(self, state: ItineraryState) -> Literal["revise", "end"]:
        if state["revision_count"] >= 2:
            return "end"
        if state["optimization_score"] < 8.0:
            return "revise"
        return "end"

    def _revise_itinerary(self, state: ItineraryState) -> dict:
        request = state["request"]
        issues = set(state["issues"])
        candidates = state["scored_attractions"]
        if "over_budget" in issues or "attraction_tickets_too_high" in issues:
            candidates = sorted(candidates, key=lambda item: (item.price if item.price > 0 else 0, -item.score, item.title))
        elif "too_many_outdoor_days_for_rain" in issues:
            candidates = sorted(candidates, key=lambda item: (self._is_outdoor(self._text(item)), -item.score, item.price))
        else:
            candidates = sorted(candidates, key=lambda item: (-item.score, item.price if item.price > 0 else 0, item.title))

        selected = self._select_unique_attractions(candidates, request.days)
        revised_state = {**state, "scored_attractions": selected + [item for item in candidates if item not in selected]}
        built = self._build_itinerary(revised_state)
        return {
            **built,
            "revision_count": state["revision_count"] + 1,
            "decisions": built["decisions"]
            + [f"Revised itinerary for issues: {', '.join(state['issues']) or 'general quality improvement'}."],
        }

    def _build_budget_breakdown(self, state: ItineraryState) -> dict:
        request = state["request"]
        travelers = max(int(request.travelers or 1), 1)
        days = max(int(request.days or 1), 1)
        nights = max(days - 1, 1)
        per_person_day_budget = request.budget / travelers / days

        one_way_transport = int(state["transport_options"][0].price or 0) if state["transport_options"] else 0
        transport = one_way_transport * travelers * 2 if one_way_transport > 0 else 0
        lodging = int(state["hotel_options"][0].price or 0) if state["hotel_options"] else self._fallback_lodging(request) * nights
        attractions = sum(max(int(day.estimated_cost or 0), 0) for day in state["daily_itinerary"]) * travelers
        meals = self._meal_allowance(per_person_day_budget) * days * travelers
        local_transport = self._local_transport_allowance(per_person_day_budget) * days * travelers
        experience = self._experience_allowance(request, per_person_day_budget) * days * travelers
        shopping = self._shopping_allowance(per_person_day_budget) * travelers
        subtotal = transport + lodging + attractions + meals + local_transport + experience + shopping
        contingency = int(round(subtotal * 0.08)) if subtotal > 0 else 0
        total = subtotal + contingency
        return {
            "transport": transport,
            "lodging": lodging,
            "attractions": attractions,
            "meals": meals,
            "local_transport": local_transport,
            "experience": experience,
            "shopping": shopping,
            "contingency": contingency,
            "total": total,
            "target_budget": request.budget,
            "budget_gap": total - request.budget,
            "method": "round_trip_transport_per_traveler + lodging_nights + attraction_tickets_per_traveler + meals + local_transport + experience + shopping + 8_percent_contingency",
        }

    @staticmethod
    def _select_unique_attractions(attractions: list[Recommendation], count: int) -> list[Recommendation]:
        selected: list[Recommendation] = []
        seen: set[str] = set()
        for item in attractions:
            key = item.title.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            selected.append(item)
            if len(selected) >= max(count, 1):
                break
        return selected

    @staticmethod
    def _text(item: Recommendation) -> str:
        return f"{item.title} {item.details} {item.reason}".lower()

    @staticmethod
    def _is_rainy(weather_summary: str) -> bool:
        text = (weather_summary or "").lower()
        return any(token in text for token in ("rain", "storm", "mua", "mưa", "giông", "bao", "bão"))

    @staticmethod
    def _is_outdoor(text: str) -> bool:
        return any(token in text for token in ("outdoor", "beach", "nature", "park", "mountain", "lake", "walk", "bien", "biển"))

    @staticmethod
    def _is_indoor(text: str) -> bool:
        return any(token in text for token in ("indoor", "museum", "gallery", "temple", "pagoda", "cafe", "coffee", "spa", "nha hang"))

    @staticmethod
    def _is_signature_experience(text: str) -> bool:
        return any(token in text for token in ("landmark", "heritage", "old town", "beach", "market", "museum", "di san", "cho "))

    def _has_many_outdoor_days(self, state: ItineraryState) -> bool:
        outdoor_days = 0
        for plan in state["daily_itinerary"]:
            text = f"{plan.title} {plan.morning} {plan.afternoon}".lower()
            if self._is_outdoor(text):
                outdoor_days += 1
        return outdoor_days > max(1, len(state["daily_itinerary"]) // 2)

    @staticmethod
    def _budget_tier(request: UserRequest) -> str:
        per_person_day = request.budget / max(request.travelers, 1) / max(request.days, 1)
        if per_person_day <= 700_000:
            return "tight"
        if per_person_day <= 1_500_000:
            return "balanced"
        if per_person_day <= 3_000_000:
            return "comfortable"
        return "premium"

    @staticmethod
    def _meal_allowance(per_person_day_budget: float) -> int:
        if per_person_day_budget <= 700_000:
            return 220_000
        if per_person_day_budget <= 1_500_000:
            return 350_000
        if per_person_day_budget <= 3_000_000:
            return 550_000
        return 850_000

    @staticmethod
    def _local_transport_allowance(per_person_day_budget: float) -> int:
        if per_person_day_budget <= 700_000:
            return 90_000
        if per_person_day_budget <= 1_500_000:
            return 140_000
        if per_person_day_budget <= 3_000_000:
            return 220_000
        return 350_000

    @staticmethod
    def _experience_allowance(request: UserRequest, per_person_day_budget: float) -> int:
        interests = {item.lower() for item in request.interests}
        base = 120_000
        if per_person_day_budget > 1_500_000:
            base = 250_000
        if per_person_day_budget > 3_000_000:
            base = 450_000
        if {"food", "coffee", "culture", "history", "photo", "beach", "nature"} & interests:
            base += 80_000
        return base

    @staticmethod
    def _shopping_allowance(per_person_day_budget: float) -> int:
        if per_person_day_budget <= 700_000:
            return 100_000
        if per_person_day_budget <= 1_500_000:
            return 250_000
        if per_person_day_budget <= 3_000_000:
            return 500_000
        return 1_000_000

    @staticmethod
    def _fallback_lodging(request: UserRequest) -> int:
        per_person_budget = request.budget / max(request.travelers, 1)
        if per_person_budget <= 5_000_000:
            return 550_000
        if per_person_budget <= 12_000_000:
            return 850_000
        if per_person_budget <= 25_000_000:
            return 1_400_000
        return 2_200_000
