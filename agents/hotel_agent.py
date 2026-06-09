from __future__ import annotations

import math
from datetime import date, timedelta
from typing import TypedDict

from schemas.models import AgentResult, Recommendation, UserRequest
from services.live_travel_service import fetch_live_hotels
from services.location_service import canonicalize_location

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # keeps the app runnable before dependencies are installed
    END = START = None
    StateGraph = None


BOOKING_PRICE_SOURCES = {"SerpAPI Google Hotels", "RapidAPI booking-com15"}


class HotelState(TypedDict):
    request: UserRequest
    destination: str
    nights: int
    checkin_date: str
    checkout_date: str
    room_plan: dict
    raw_hotels: list[dict]
    recommendations: list[Recommendation]
    notes: list[str]
    source: str
    status: str
    debug: dict


class HotelAgent:
    name = "hotel-agent"

    def __init__(self):
        self.graph = self._build_graph() if StateGraph is not None else None

    def run(self, request: UserRequest) -> AgentResult:
        initial_state: HotelState = {
            "request": request,
            "destination": canonicalize_location(request.destination),
            "nights": max(request.days - 1, 1),
            "checkin_date": "",
            "checkout_date": "",
            "room_plan": {},
            "raw_hotels": [],
            "recommendations": [],
            "notes": [],
            "source": "No stable hotel data",
            "status": "empty",
            "debug": {
                "request_destination": request.destination,
                "canonical_destination": canonicalize_location(request.destination),
                "travelers": request.travelers,
                "adults": request.adults,
                "children": request.children,
                "child_ages": request.child_ages,
            },
        }

        if self.graph is not None:
            state = self.graph.invoke(initial_state)
        else:
            state = self._resolve_stay_dates(initial_state)
            state = {**initial_state, **state}
            state = {**state, **self._plan_room_allocation(state)}
            state = {**state, **self._fetch_hotel_candidates(state)}
            state = {**state, **self._score_hotels(state)}
            state = {**state, **self._build_recommendations(state)}

        recommendations = state["recommendations"]
        if not recommendations:
            return AgentResult(
                agent=self.name,
                summary="No stable hotel discovery data available.",
                recommendations=[],
                notes=state["notes"] + ["No live hotel discovery result returned from the current providers."],
                source=state["source"],
                status="empty",
                extra={
                    "hotel_candidates": [],
                    "room_plan": state["room_plan"],
                    "debug": state["debug"],
                },
            )

        return AgentResult(
            agent=self.name,
            summary=f"Found {len(recommendations)} live hotel options for {state['room_plan']['label']}.",
            recommendations=recommendations,
            notes=state["notes"],
            source=state["source"],
            status=state["status"],
            extra={
                "hotel_candidates": state["raw_hotels"][:4],
                "room_plan": state["room_plan"],
                "debug": state["debug"],
            },
        )

    def _build_graph(self):
        graph = StateGraph(HotelState)
        graph.add_node("resolve_stay_dates", self._resolve_stay_dates)
        graph.add_node("plan_room_allocation", self._plan_room_allocation)
        graph.add_node("fetch_hotel_candidates", self._fetch_hotel_candidates)
        graph.add_node("score_hotels", self._score_hotels)
        graph.add_node("build_recommendations", self._build_recommendations)
        graph.add_edge(START, "resolve_stay_dates")
        graph.add_edge("resolve_stay_dates", "plan_room_allocation")
        graph.add_edge("plan_room_allocation", "fetch_hotel_candidates")
        graph.add_edge("fetch_hotel_candidates", "score_hotels")
        graph.add_edge("score_hotels", "build_recommendations")
        graph.add_edge("build_recommendations", END)
        return graph.compile()

    def _resolve_stay_dates(self, state: HotelState) -> dict:
        nights = max(state["request"].days - 1, 1)
        checkin_date = state["request"].departure_date or None
        checkout_date = None
        if checkin_date:
            try:
                checkout_date = (date.fromisoformat(checkin_date) + timedelta(days=nights)).isoformat()
            except ValueError:
                checkin_date = None
        if not checkin_date:
            checkin = date.today() + timedelta(days=14)
            checkin_date = checkin.isoformat()
            checkout_date = (checkin + timedelta(days=nights)).isoformat()
        return {
            "nights": nights,
            "checkin_date": checkin_date,
            "checkout_date": checkout_date,
            "debug": {
                **state["debug"],
                "nights": nights,
                "checkin_date": checkin_date,
                "checkout_date": checkout_date,
            },
        }

    def _plan_room_allocation(self, state: HotelState) -> dict:
        request = state["request"]
        adults = max(int(request.adults or request.travelers or 1), 1)
        children = max(int(request.children or 0), 0)
        child_ages = list(request.child_ages or [])
        if len(child_ages) < children:
            child_ages.extend([7] * (children - len(child_ages)))
        child_ages = child_ages[:children]
        travelers = adults + children
        adults_per_room = 2
        rooms_for_adults = math.ceil(adults / adults_per_room)
        rooms_for_children = min(children, adults) if children else 1
        rooms = max(rooms_for_adults, rooms_for_children, 1)
        rooms = min(rooms, adults)
        allocation = self._allocate_rooms(adults=adults, children=children, rooms=rooms)
        room_plan = {
            "travelers": travelers,
            "adults": adults,
            "children": children,
            "child_ages": child_ages,
            "rooms": rooms,
            "adults_per_room": adults_per_room,
            "allocation": allocation,
            "label": f"{rooms} room{'s' if rooms != 1 else ''} for {adults} adult{'s' if adults != 1 else ''} and {children} child{'ren' if children != 1 else ''}",
        }
        return {
            "room_plan": room_plan,
            "debug": {**state["debug"], "room_plan": room_plan},
        }

    def _fetch_hotel_candidates(self, state: HotelState) -> dict:
        room_plan = state["room_plan"]
        hotels = fetch_live_hotels(
            state["destination"],
            checkin_date=state["checkin_date"],
            checkout_date=state["checkout_date"],
            adults=room_plan["adults"],
            rooms=room_plan["rooms"],
            children=room_plan["children"],
            child_ages=room_plan["child_ages"],
        )
        enriched = [
            {
                **hotel,
                "search_adults": room_plan["adults"],
                "search_children": room_plan["children"],
                "search_child_ages": room_plan["child_ages"],
                "search_rooms": room_plan["rooms"],
                "adults_per_room": room_plan["adults_per_room"],
                "room_allocation": room_plan["allocation"],
            }
            for hotel in hotels
        ]
        source = enriched[0].get("source", "Unknown") if enriched else "No stable hotel data"
        notes = [
            f"Hotel search used {room_plan['rooms']} room{'s' if room_plan['rooms'] != 1 else ''} for {room_plan['adults']} adult{'s' if room_plan['adults'] != 1 else ''} and {room_plan['children']} child{'ren' if room_plan['children'] != 1 else ''}.",
        ]
        if source in BOOKING_PRICE_SOURCES:
            notes.extend(
                [
                    f"Hotel booking price source active: {source}.",
                    "Prices are returned for the selected dates and room count and should still be verified before payment.",
                ]
            )
        elif enriched:
            notes.extend(
                [
                    f"Hotel discovery source active: {source}.",
                    "No booking-grade hotel price was returned, so any price-like data is treated as unavailable.",
                ]
            )
        return {
            "raw_hotels": enriched,
            "source": source,
            "notes": notes,
            "debug": {
                **state["debug"],
                "provider_source": source,
                "raw_hotel_count": len(enriched),
                "raw_hotel_preview": enriched[:3],
            },
        }

    def _score_hotels(self, state: HotelState) -> dict:
        scored_hotels: list[dict] = []
        request = state["request"]
        room_plan = state["room_plan"]
        for hotel in state["raw_hotels"]:
            nightly_price = hotel.get("price_per_night", 0)
            total_stay_price = hotel.get("total_price") or (
                nightly_price * state["nights"] if hotel.get("source") in BOOKING_PRICE_SOURCES else 0
            )
            pricing_breakdown = self._build_pricing_breakdown(
                total_stay_price=total_stay_price,
                nightly_price=nightly_price,
                nights=state["nights"],
                room_plan=room_plan,
                source=hotel.get("source", ""),
            )
            rating = hotel.get("rating", 0) or 0
            review_count = hotel.get("review_count") or 0
            amenities = [str(item).lower() for item in hotel.get("amenities", [])]
            interest_bonus = 1 if any(item.lower() in amenities for item in request.interests) else 0
            group_fit_bonus = 0.4 if room_plan["rooms"] > 1 and hotel.get("source") in BOOKING_PRICE_SOURCES else 0
            distance_bonus = 0
            if hotel.get("distance_km") is not None:
                distance = float(hotel["distance_km"])
                if distance <= 3:
                    distance_bonus = 0.5
                elif distance <= 8:
                    distance_bonus = 0.25
            price_penalty = 0
            if total_stay_price and request.budget:
                lodging_share = total_stay_price / request.budget
                if lodging_share > 0.55:
                    price_penalty = min((lodging_share - 0.55) * 2, 1.2)
            score = round(
                (float(rating) * 1.15)
                + min(float(review_count) / 500, 2.0)
                + interest_bonus
                + group_fit_bonus
                + distance_bonus
                - price_penalty,
                2,
            )
            scored_hotels.append(
                {
                    **hotel,
                    "total_stay_price": total_stay_price,
                    "pricing_breakdown": pricing_breakdown,
                    "score": score,
                    "score_factors": {
                        "rating": rating,
                        "review_count": review_count,
                        "interest_bonus": interest_bonus,
                        "group_fit_bonus": group_fit_bonus,
                        "distance_bonus": distance_bonus,
                        "price_penalty": round(price_penalty, 2),
                    },
                }
            )
        scored_hotels.sort(key=lambda item: (-item["score"], item.get("total_stay_price") or 10**12))
        return {
            "raw_hotels": scored_hotels,
            "debug": {
                **state["debug"],
                "scored_hotel_count": len(scored_hotels),
                "scored_hotel_preview": scored_hotels[:3],
            },
        }

    def _build_recommendations(self, state: HotelState) -> dict:
        has_booking_prices = state["source"] in BOOKING_PRICE_SOURCES
        room_plan = state["room_plan"]
        recommendations: list[Recommendation] = []
        for hotel in state["raw_hotels"][:4]:
            total_stay_price = int(hotel.get("total_stay_price") or 0)
            pricing = hotel.get("pricing_breakdown") or {}
            rating = hotel.get("rating", 0) or 0
            review_count = hotel.get("review_count") or 0
            currency = hotel.get("currency") or "VND"
            review_word = hotel.get("review_word") or ""
            room_label = hotel.get("room_label") or ""
            detail_parts = [
                f"Area: {hotel['area']}",
                f"Khach: {room_plan['adults']} nguoi lon, {room_plan['children']} tre em",
                f"Tuoi tre em: {', '.join(str(age) for age in room_plan['child_ages']) if room_plan['child_ages'] else 'khong co'}",
                f"Phong: {room_plan['rooms']} phong; {self._allocation_label(room_plan['allocation'])}",
                f"Rating: {rating} {review_word} ({review_count})",
            ]
            if room_label:
                detail_parts.append(f"Room: {room_label}")
            if hotel.get("distance_km") is not None:
                detail_parts.append(f"Distance: {hotel['distance_km']} km from destination center")
            if hotel.get("included_taxes"):
                detail_parts.append("Includes taxes and fees")
            if hotel.get("free_cancellation"):
                detail_parts.append("Free cancellation")
            if hotel.get("no_prepayment"):
                detail_parts.append("No prepayment needed")
            if hotel.get("source") in BOOKING_PRICE_SOURCES:
                if total_stay_price:
                    detail_parts.append(
                        "Giá: "
                        f"{self._format_vnd(pricing.get('nightly_room_price', 0))} {currency}/đêm/phòng "
                        f"x {room_plan['rooms']} phòng x {state['nights']} đêm = "
                        f"{self._format_vnd(total_stay_price)} {currency}"
                    )
                    detail_parts.append(f"Tổng mỗi đêm: {self._format_vnd(pricing.get('nightly_total_price', 0))} {currency}/đêm")
                if hotel.get("price_source"):
                    detail_parts.append(f"Price source: {hotel['price_source']}")
            else:
                detail_parts.append("Booking price: unavailable from live hotel provider")
            detail_parts.append(f"Source: {hotel['source']}")
            recommendations.append(
                Recommendation(
                    title=hotel["name"],
                    details=" | ".join(detail_parts),
                    price=total_stay_price,
                    score=float(hotel["score"]),
                    reason=(
                        f"Tổng lưu trú dùng giá live cho {room_plan['rooms']} phòng, {room_plan['adults']} người lớn, {room_plan['children']} trẻ em, {state['nights']} đêm. Giá mỗi phòng/đêm được suy ra từ tổng live provider trả về."
                        if hotel.get("source") in BOOKING_PRICE_SOURCES
                        else f"Map/place discovery result for {room_plan['label']}. Booking-grade price was unavailable from the current hotel providers."
                    ),
                    image_url=hotel.get("photo_url") or "",
                )
            )

        notes = list(state["notes"])
        if recommendations and has_booking_prices:
            notes.append("Hotel shortlist is using live booking-price results for this room configuration.")
        elif recommendations:
            notes.append("Hotel shortlist does not claim booking-grade live pricing for this room configuration.")

        return {
            "recommendations": recommendations,
            "notes": notes,
            "status": "ok" if recommendations else "empty",
            "debug": {
                **state["debug"],
                "final_count": len(recommendations),
                "final_titles": [item.title for item in recommendations],
            },
        }

    @staticmethod
    def _build_pricing_breakdown(total_stay_price: int, nightly_price: int, nights: int, room_plan: dict, source: str) -> dict:
        nights = max(int(nights or 1), 1)
        rooms = max(int(room_plan.get("rooms") or 1), 1)
        total_lodging_price = int(total_stay_price or 0)
        if total_lodging_price <= 0 and nightly_price > 0:
            total_lodging_price = int(nightly_price) * nights * rooms
        nightly_total_price = int(round(total_lodging_price / nights)) if total_lodging_price else 0
        nightly_room_price = int(round(total_lodging_price / nights / rooms)) if total_lodging_price else 0
        return {
            "nightly_room_price": nightly_room_price,
            "nightly_total_price": nightly_total_price,
            "rooms": rooms,
            "nights": nights,
            "travelers": int(room_plan.get("travelers") or 1),
            "adults": int(room_plan.get("adults") or 1),
            "children": int(room_plan.get("children") or 0),
            "child_ages": list(room_plan.get("child_ages") or []),
            "total_lodging_price": total_lodging_price,
            "price_basis": "provider_total_divided_by_rooms_and_nights" if source in BOOKING_PRICE_SOURCES else "unverified_discovery_price",
        }

    @staticmethod
    def _format_vnd(value: int | float) -> str:
        return f"{int(round(float(value or 0))):,}".replace(",", ".")

    @staticmethod
    def _allocate_rooms(adults: int, children: int, rooms: int) -> list[dict]:
        allocation = [{"adults": 1, "children": 0} for _ in range(max(rooms, 1))]
        remaining_adults = max(adults - len(allocation), 0)
        index = 0
        while remaining_adults > 0:
            if allocation[index]["adults"] < 2:
                allocation[index]["adults"] += 1
                remaining_adults -= 1
            index = (index + 1) % len(allocation)

        for child_index in range(children):
            allocation[child_index % len(allocation)]["children"] += 1
        return allocation

    @staticmethod
    def _allocation_label(allocation: list[dict]) -> str:
        parts = []
        for index, room in enumerate(allocation, start=1):
            adult_label = "adult" if room["adults"] == 1 else "adults"
            child_label = "child" if room["children"] == 1 else "children"
            parts.append(f"Phong {index}: {room['adults']} {adult_label} + {room['children']} {child_label}")
        return "; ".join(parts)
