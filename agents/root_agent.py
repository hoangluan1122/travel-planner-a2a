from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from agents.attraction_agent import AttractionAgent
from agents.hotel_agent import HotelAgent
from agents.weather_agent import WeatherAgent
from schemas.models import DailyPlan, Recommendation, TravelPlan, UserRequest
from services.location_resolver import resolve_location
from services.travel_advisor import TravelAdvisor
from transport.agent import TransportAgent

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


class RootTravelPlannerAgent:
    name = "root-travel-planner-agent"

    def __init__(self):
        self.weather_agent = WeatherAgent()
        self.transport_agent = TransportAgent()
        self.hotel_agent = HotelAgent()
        self.attraction_agent = AttractionAgent(self.weather_agent)
        self.advisor = TravelAdvisor()

    def run(self, request: UserRequest) -> TravelPlan:
        with ThreadPoolExecutor(max_workers=4) as executor:
            weather_future = executor.submit(self.weather_agent.run, request)
            transport_future = executor.submit(self.transport_agent.run, request)
            hotels_future = executor.submit(self.hotel_agent.run, request)
            attractions_future = executor.submit(
                lambda: self.attraction_agent.run(request, weather=weather_future.result())
            )

            weather = weather_future.result()
            transport = transport_future.result()
            hotels = hotels_future.result()
            attractions = attractions_future.result()

        origin_label = resolve_location(request.origin).canonical_name
        destination_label = resolve_location(request.destination).canonical_name

        transport_recommendations = []
        is_vi = (request.lang or "vi").lower() == "vi"
        mode_labels = {
            "flight": "Máy bay" if is_vi else "Flight",
            "train": "Tàu hỏa" if is_vi else "Train",
            "bus": "Xe khách" if is_vi else "Bus",
            "mixed": "Nối chặng" if is_vi else "Mixed route",
        }
        for item in transport.options:
            route_title = f"{item.operator} {item.departure} -> {item.arrival}"
            if item.tag:
                route_title = f"[{item.tag}] {route_title}"

            details = f"{mode_labels.get(item.mode, item.mode.title())} | Nguồn: {item.provider}" if is_vi else f"{item.mode.title()} via {item.provider}"
            if item.duration:
                details += f" | {item.duration}"
            if item.mode == "train" and not getattr(item, "price_verified", True):
                details += " | giá tham khảo" if is_vi else " | fare unverified"
            if item.fare_label:
                details += f" | {item.fare_label}"

            transport_recommendations.append(
                Recommendation(
                    title=route_title,
                    details=details,
                    price=item.price,
                    score=item.score,
                    reason=item.reason,
                )
            )

        transport_recommendations = self.advisor.advise_transport(request, transport_recommendations)
        hotel_recommendations = self.advisor.advise_hotels(request, hotels.recommendations)
        attraction_recommendations = self.advisor.advise_attractions(request, attractions.recommendations, weather.summary)

        estimated_cost, cost_breakdown = self._estimate_trip_cost(
            request=request,
            transport=transport_recommendations,
            hotels=hotel_recommendations,
            attractions=attraction_recommendations,
        )

        daily_itinerary = self._build_daily_itinerary(
            request=request,
            weather_summary=weather.summary,
            attractions=attraction_recommendations,
            hotel_name=hotel_recommendations[0].title if hotel_recommendations else "your selected hotel",
        )

        advisor_summary, advisor_status = self.advisor.build_advisor_summary(
            request=request,
            transport=transport_recommendations,
            hotels=hotel_recommendations,
            attractions=attraction_recommendations,
            estimated_cost=estimated_cost,
        )

        if is_vi:
            recommendation_lines = [
                f"Tuyến đi: {origin_label} đến {destination_label} trong {request.days} ngày.",
                weather.summary,
            ]
            if transport_recommendations:
                recommendation_lines.append(f"Di chuyển gợi ý: {transport_recommendations[0].title} ({transport_recommendations[0].price:,} VND)")
            else:
                recommendation_lines.append("Chưa có gợi ý di chuyển phù hợp từ dữ liệu hiện tại.")

            if hotel_recommendations:
                recommendation_lines.append(f"Lưu trú gợi ý: {hotel_recommendations[0].title} ({hotel_recommendations[0].price:,} VND tổng lưu trú)")
            else:
                recommendation_lines.append("Chưa có gợi ý lưu trú phù hợp từ dữ liệu hiện tại.")

            if attraction_recommendations:
                names = ", ".join(a.title for a in attraction_recommendations[:3])
                recommendation_lines.append(f"Điểm tham quan nổi bật: {names}")
            else:
                recommendation_lines.append("Chưa có gợi ý điểm tham quan phù hợp từ dữ liệu hiện tại.")

            if estimated_cost > 0:
                if estimated_cost > request.budget:
                    recommendation_lines.append("Chi phí ước tính đang vượt ngân sách, nên cân nhắc phương án tiết kiệm hơn.")
                else:
                    recommendation_lines.append("Chi phí ước tính vẫn nằm trong ngân sách.")
            else:
                recommendation_lines.append("Chi phí ước tính còn hạn chế vì một số dữ liệu chưa sẵn sàng.")
        else:
            recommendation_lines = [
                f"Route: {origin_label} to {destination_label} for {request.days} days.",
                f"Weather outlook: {weather.summary}",
            ]
            if transport_recommendations:
                recommendation_lines.append(f"Suggested transport: {transport_recommendations[0].title} ({transport_recommendations[0].price:,} VND)")
            else:
                recommendation_lines.append("Transport suggestions are currently unavailable from live providers.")

            if hotel_recommendations:
                recommendation_lines.append(f"Suggested hotel: {hotel_recommendations[0].title} ({hotel_recommendations[0].price:,} VND total)")
            else:
                recommendation_lines.append("Hotel suggestions are currently unavailable from live providers.")

            if attraction_recommendations:
                names = ", ".join(a.title for a in attraction_recommendations[:3])
                recommendation_lines.append(f"Recommended attractions: {names}")
            else:
                recommendation_lines.append("Attraction suggestions are currently unavailable from live providers.")

            if estimated_cost > 0:
                if estimated_cost > request.budget:
                    recommendation_lines.append("Estimated cost is above your budget, so lower-cost options should be considered.")
                else:
                    recommendation_lines.append("Estimated cost is still within budget.")
                recommendation_lines.append(
                    f"Cost breakdown: transport {cost_breakdown['transport']:,} VND, "
                    f"lodging {cost_breakdown['lodging']:,} VND, attractions {cost_breakdown['attractions']:,} VND, "
                    f"meals/local travel {cost_breakdown['daily_allowance']:,} VND, "
                    f"experience adjustment {cost_breakdown['experience_adjustment']:,} VND."
                )
            else:
                recommendation_lines.append("Estimated cost is limited because some live data is currently unavailable.")

        if is_vi and estimated_cost > 0:
            recommendation_lines.append(
                f"Cơ cấu chi phí: di chuyển {cost_breakdown['transport']:,} VND, "
                f"lưu trú {cost_breakdown['lodging']:,} VND, tham quan {cost_breakdown['attractions']:,} VND, "
                f"ăn uống/nội đô {cost_breakdown['daily_allowance']:,} VND, "
                f"nâng trải nghiệm {cost_breakdown['experience_adjustment']:,} VND, dự phòng {cost_breakdown['contingency']:,} VND."
            )

        recommendation_lines.insert(0, advisor_summary)

        final_recommendation = self._build_final_summary(
            request=request,
            weather_summary=weather.summary,
            estimated_cost=estimated_cost,
            fallback_summary="\n".join(recommendation_lines),
            transport=transport_recommendations,
            hotels=hotel_recommendations,
            attractions=attraction_recommendations,
        )

        transport_live_state = "ok" if transport_recommendations else "empty"

        transport_source_label = {
            "MixedTransportStrategy": "Multi-provider transport search",
            "FlightStrategy": "Flight search",
            "TrainStrategy": "Train search",
            "BusStrategy": "Bus search",
        }.get(transport.selected_strategy, transport.selected_strategy)

        provider_status = {
            "weather": {
                "status": weather.status,
                "source": weather.source,
                "notes": weather.notes,
                "count": 1 if weather.status == "ok" else 0,
            },
            "transport": {
                "status": transport_live_state,
                "source": transport_source_label,
                "notes": transport.notes,
                "count": len(transport_recommendations),
            },
            "hotels": {
                "status": hotels.status,
                "source": hotels.source,
                "notes": hotels.notes,
                "count": len(hotel_recommendations),
            },
            "attractions": {
                "status": attractions.status,
                "source": attractions.source,
                "notes": attractions.notes,
                "count": len(attraction_recommendations),
            },
            "advisor": {
                "status": "ok",
                "source": "TravelAdvisor policy",
                "notes": [advisor_status["selection_method"]],
                "count": len([value for value in advisor_status["primary_picks"].values() if value]),
                "profile": advisor_status["profile"],
                "missing_signals": advisor_status["missing_signals"],
                "budget_gap": advisor_status["budget_gap"],
                "primary_picks": advisor_status["primary_picks"],
                "agent_reviews": advisor_status["agent_reviews"],
            },
            "cost": {
                "status": "ok",
                "source": "Live prices + calculated trip allowance",
                "notes": cost_breakdown["notes"],
                "count": len([value for key, value in cost_breakdown.items() if key not in {"notes", "method"} and isinstance(value, int) and value > 0]),
                "breakdown": cost_breakdown,
            },
            "debug": {
                "request": request.model_dump(),
                "resolved_origin": resolve_location(request.origin).model_dump(),
                "resolved_destination": resolve_location(request.destination).model_dump(),
                "transport_count": len(transport_recommendations),
                "transport_titles": [item.title for item in transport_recommendations[:5]],
                "transport_notes": transport.notes,
                "hotel_count": len(hotel_recommendations),
                "hotel_titles": [item.title for item in hotel_recommendations[:5]],
                "attraction_count": len(attraction_recommendations),
                "attraction_titles": [item.title for item in attraction_recommendations[:5]],
                "attraction_debug": attractions.extra.get("debug", {}),
            },
        }

        return TravelPlan(
            destination=destination_label,
            origin=origin_label,
            days=request.days,
            weather_summary=weather.summary,
            weather_extra=weather.extra,
            transport_options=transport_recommendations,
            hotels=hotel_recommendations,
            attractions=attraction_recommendations,
            daily_itinerary=daily_itinerary,
            estimated_cost=estimated_cost,
            final_recommendation=final_recommendation,
            provider_status=provider_status,
        )

    def _estimate_trip_cost(self, request: UserRequest, transport, hotels, attractions) -> tuple[int, dict]:
        notes: list[str] = []
        travelers = max(int(request.travelers or 1), 1)
        days = max(int(request.days or 1), 1)
        nights = max(days - 1, 1)
        target_budget = max(int(request.budget or 0), 0)
        target_gap = 2_000_000

        attraction_cost = sum(max(int(item.price or 0), 0) for item in attractions[:days]) * travelers
        daily_allowance = self._daily_allowance_per_person(request.budget, days, travelers) * days * travelers
        fallback_lodging = self._fallback_lodging_per_night(request.budget, travelers) * nights
        selected_transport, selected_hotel, selected_total = self._select_budget_fit_combo(
            request=request,
            transport=transport,
            hotels=hotels,
            base_attractions=attraction_cost,
            base_daily_allowance=daily_allowance,
            fallback_lodging=fallback_lodging,
        )

        if selected_transport > 0 and selected_transport < len(transport):
            transport.insert(0, transport.pop(selected_transport))
        if selected_hotel > 0 and selected_hotel < len(hotels):
            hotels.insert(0, hotels.pop(selected_hotel))

        one_way_transport = int(transport[0].price or 0) if transport else 0
        transport_cost = one_way_transport * travelers * 2 if one_way_transport > 0 else 0
        if one_way_transport > 0:
            notes.append("Transport is estimated as round trip: selected one-way option x travelers x 2.")
        else:
            notes.append("Transport live price is unavailable, so transport cost is not included.")

        lodging_cost = int(hotels[0].price or 0) if hotels else 0
        if lodging_cost > 0:
            notes.append("Lodging uses the selected live total stay price.")
        else:
            lodging_cost = fallback_lodging
            notes.append("Lodging live price is unavailable, so a budget-based lodging estimate is used.")

        if attraction_cost > 0:
            notes.append("Attraction cost uses the first planned attraction prices multiplied by travelers.")
        else:
            notes.append("Attractions are currently free or have no live ticket price.")

        notes.append("Meals and local travel allowance is calculated from the trip budget tier.")

        subtotal = transport_cost + lodging_cost + attraction_cost + daily_allowance
        contingency = int(round(subtotal * 0.08)) if subtotal > 0 else 0
        total_before_alignment = subtotal + contingency
        experience_adjustment = 0
        if target_budget > 0 and total_before_alignment < target_budget - target_gap:
            experience_adjustment = (target_budget - target_gap) - total_before_alignment
            notes.append("Budget-fit suggestion adds an experience upgrade allowance so the estimate stays within 2,000,000 VND of the requested budget.")
        elif target_budget > 0 and total_before_alignment > target_budget + target_gap:
            notes.append("Even the best available live-price combo is still more than 2,000,000 VND above the requested budget.")
        elif target_budget > 0:
            notes.append("Selected live-price combo is already within 2,000,000 VND of the requested budget.")

        total = total_before_alignment + experience_adjustment
        notes.append("An 8% contingency is added for fees, taxis, and small price changes.")

        breakdown = {
            "transport": transport_cost,
            "lodging": lodging_cost,
            "attractions": attraction_cost,
            "daily_allowance": daily_allowance,
            "contingency": contingency,
            "experience_adjustment": experience_adjustment,
            "target_budget": target_budget,
            "budget_gap": total - target_budget if target_budget else 0,
            "total": total,
            "method": "budget_fit_combo + round_trip_transport + total_lodging + attraction_tickets + daily_allowance + 8_percent_contingency + optional_experience_adjustment",
            "notes": notes,
        }
        return total, breakdown

    def _select_budget_fit_combo(self, request: UserRequest, transport, hotels, base_attractions: int, base_daily_allowance: int, fallback_lodging: int) -> tuple[int, int, int]:
        travelers = max(int(request.travelers or 1), 1)
        target_budget = max(int(request.budget or 0), 0)
        target_gap = 2_000_000
        transport_candidates = [(idx, int(item.price or 0) * travelers * 2) for idx, item in enumerate(transport) if int(item.price or 0) > 0]
        hotel_candidates = [(idx, int(item.price or 0)) for idx, item in enumerate(hotels) if int(item.price or 0) > 0]

        if not transport_candidates:
            transport_candidates = [(0, 0)]
        if not hotel_candidates:
            hotel_candidates = [(0, fallback_lodging)]

        candidates = []
        preferred_transport = (request.preferred_transport or "").strip().lower()
        has_preferred_transport = bool(preferred_transport) and any(
            self._transport_matches_preference(item, preferred_transport)
            for item in transport
        )
        for transport_idx, transport_cost in transport_candidates:
            for hotel_idx, lodging_cost in hotel_candidates:
                subtotal = transport_cost + lodging_cost + base_attractions + base_daily_allowance
                total = subtotal + int(round(subtotal * 0.08))
                gap = abs(total - target_budget) if target_budget else total
                in_range = target_budget > 0 and gap <= target_gap
                under_budget = not target_budget or total <= target_budget
                preferred_mismatch = (
                    has_preferred_transport
                    and transport_idx < len(transport)
                    and not self._transport_matches_preference(transport[transport_idx], preferred_transport)
                )
                candidates.append((preferred_mismatch, not in_range, not under_budget, gap, total, transport_idx, hotel_idx))

        candidates.sort()
        _, _, _, _, total, transport_idx, hotel_idx = candidates[0]
        return transport_idx, hotel_idx, total

    @staticmethod
    def _transport_matches_preference(option: Recommendation, preferred_transport: str) -> bool:
        text = f"{option.title} {option.details} {option.reason}".lower()
        aliases = {
            "flight": ("flight", "máy bay", "may bay"),
            "train": ("train", "tàu hỏa", "tàu hoả", "tau hoa"),
            "bus": ("bus", "xe khách", "xe khach"),
            "car": ("car", "ô tô", "o to", "oto", "road transfer"),
            "mixed": ("mixed", "nối chặng", "noi chang"),
        }
        return any(alias in text for alias in aliases.get(preferred_transport, (preferred_transport,)))

    @staticmethod
    def _daily_allowance_per_person(budget: int, days: int, travelers: int) -> int:
        per_person_budget = max(int(budget or 0), 1) / max(days, 1) / max(travelers, 1)
        if per_person_budget <= 700_000:
            return 250_000
        if per_person_budget <= 1_500_000:
            return 350_000
        if per_person_budget <= 3_000_000:
            return 500_000
        return 750_000

    @staticmethod
    def _fallback_lodging_per_night(budget: int, travelers: int) -> int:
        per_person_budget = max(int(budget or 0), 1) / max(travelers, 1)
        if per_person_budget <= 5_000_000:
            return 550_000
        if per_person_budget <= 12_000_000:
            return 850_000
        if per_person_budget <= 25_000_000:
            return 1_400_000
        return 2_200_000

    def _build_daily_itinerary(self, request: UserRequest, weather_summary: str, attractions, hotel_name: str) -> list[DailyPlan]:
        itinerary: list[DailyPlan] = []
        selected = attractions[: max(request.days, 1)]
        destination_label = resolve_location(request.destination).canonical_name
        is_vi = (request.lang or 'vi').lower() == 'vi'
        day_label = 'Ngày' if is_vi else 'Day'
        fallback_evening = f'Nghỉ đêm tại {hotel_name}.' if is_vi else f'Overnight stay at {hotel_name}.'

        if not selected:
            for day in range(1, request.days + 1):
                itinerary.append(
                    DailyPlan(
                        day=day,
                        title=f"{day_label} {day} - {destination_label}",
                        morning=(f"Bắt đầu ngày mới với bữa sáng và khám phá nhẹ quanh {destination_label}." if is_vi else f"Start the day with breakfast and a relaxed exploration around {destination_label}."),
                        afternoon=("Tiếp tục tham quan các khu vực trung tâm, quán cà phê hoặc điểm địa phương tùy theo dữ liệu live hiện có." if is_vi else "Visit key central areas, cafes, or local spots depending on live availability."),
                        evening=(f"{fallback_evening}" if is_vi else f"Return to {hotel_name} and prepare for the next day."),
                        estimated_cost=-1,
                    )
                )
            return itinerary

        for day in range(1, request.days + 1):
            attraction = selected[(day - 1) % len(selected)]
            itinerary.append(
                DailyPlan(
                    day=day,
                    title=f"{day_label} {day} - {attraction.title}",
                    morning=(f"Buổi sáng bắt đầu với {attraction.title}. Bối cảnh thời tiết: {weather_summary}" if is_vi else f"Start with {attraction.title}. Weather context: {weather_summary}"),
                    afternoon=(f"Buổi chiều tiếp tục khám phá các khu vực lân cận và hoạt động phù hợp quanh {attraction.title}." if is_vi else f"Continue exploring nearby areas and complementary activities around {attraction.title}."),
                    evening=(f"Buổi tối dùng bữa và nghỉ đêm tại {hotel_name}." if is_vi else f"Dinner and overnight stay at {hotel_name}."),
                    estimated_cost=attraction.price if attraction.price > 0 else -1,
                )
            )
        return itinerary

    def _build_final_summary(
        self,
        request: UserRequest,
        weather_summary: str,
        estimated_cost: int,
        fallback_summary: str,
        transport,
        hotels,
        attractions,
    ) -> str:
        if (request.lang or "vi").lower() == "vi":
            return fallback_summary

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or OpenAI is None:
            return fallback_summary

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        client = OpenAI(api_key=api_key)
        payload = {
            "request": request.model_dump(),
            "weather_summary": weather_summary,
            "estimated_cost": estimated_cost,
            "transport": [item.model_dump() for item in transport[:2]],
            "hotels": [item.model_dump() for item in hotels[:2]],
            "attractions": [item.model_dump() for item in attractions[:3]],
        }

        if (request.lang or "vi").lower() == "vi":
            prompt = (
                "Viết tóm tắt kế hoạch du lịch bằng tiếng Việt tự nhiên. "
                "Giữ trong 5-7 dòng ngắn, chỉ plain text. "
                "Nhắc điểm đến, thời tiết, phương án di chuyển chính, nơi lưu trú, điểm tham quan nổi bật, "
                "và ngân sách có phù hợp không.\n\n"
                f"Dữ liệu:\n{json.dumps(payload, ensure_ascii=False)}"
            )
        else:
            prompt = (
                "Write a concise premium travel planner summary in English. "
                "Keep it to 5-7 short lines, plain text only. "
                "Mention destination, weather, top transport option, top stay, top attractions, "
                "and budget fit in a user-friendly style.\n\n"
                f"Data:\n{json.dumps(payload, ensure_ascii=False)}"
            )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a polished AI travel planner assistant."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
            )
            text = response.choices[0].message.content.strip()
            return text or fallback_summary
        except Exception:
            return fallback_summary
