from __future__ import annotations

from dataclasses import dataclass

from schemas.models import Recommendation, UserRequest


@dataclass(frozen=True)
class RequestProfile:
    travelers: int
    days: int
    budget: int
    per_person_day_budget: int
    budget_tier: str
    preferred_transport: str
    priorities: list[str]
    missing_signals: list[str]


class TravelAdvisor:
    """Turns provider data into customer-fit advice.

    Provider adapters answer "what exists?". This class answers "what should
    this traveler pick, and why?" using request constraints and trade-offs.
    """

    BOOKING_GRADE_SOURCES = ("SerpAPI Google Hotels", "RapidAPI booking-com15")

    def build_profile(self, request: UserRequest) -> RequestProfile:
        travelers = max(int(request.travelers or 1), 1)
        days = max(int(request.days or 1), 1)
        budget = max(int(request.budget or 0), 0)
        per_person_day_budget = int(budget / travelers / days) if budget else 0

        if per_person_day_budget <= 700_000:
            budget_tier = "tight"
        elif per_person_day_budget <= 1_500_000:
            budget_tier = "balanced"
        elif per_person_day_budget <= 3_000_000:
            budget_tier = "comfortable"
        else:
            budget_tier = "premium"

        priorities = []
        interests = {value.lower() for value in request.interests}
        if {"food", "coffee"} & interests:
            priorities.append("local_food")
        if {"photo", "nature", "beach"} & interests:
            priorities.append("scenic")
        if {"history", "culture"} & interests:
            priorities.append("culture")
        if {"relax", "resort"} & interests:
            priorities.append("comfort")
        if not priorities:
            priorities.append("balanced")

        missing_signals = []
        if not request.departure_date:
            missing_signals.append("departure_date")
        if not request.interests:
            missing_signals.append("interests")
        if not request.origin:
            missing_signals.append("origin")

        preferred_transport = (request.preferred_transport or "").strip().lower()

        return RequestProfile(
            travelers=travelers,
            days=days,
            budget=budget,
            per_person_day_budget=per_person_day_budget,
            budget_tier=budget_tier,
            preferred_transport=preferred_transport,
            priorities=priorities,
            missing_signals=missing_signals,
        )

    def advise_transport(self, request: UserRequest, options: list[Recommendation]) -> list[Recommendation]:
        profile = self.build_profile(request)
        round_trip_per_option_cap = profile.budget * 0.34
        advised = []
        for index, option in enumerate(options):
            round_trip_total = int(option.price or 0) * profile.travelers * 2
            score_delta = self._budget_fit_score(round_trip_total, round_trip_per_option_cap)
            notes = []
            if option.price:
                notes.append(f"round trip group cost about {round_trip_total:,} VND")
            else:
                notes.append("price is not confirmed")
                score_delta -= 0.8

            lower = f"{option.title} {option.details}".lower()
            if "bus" in lower or "xe" in lower:
                if profile.budget_tier in {"tight", "balanced"}:
                    score_delta += 0.5
                    notes.append("good value for the budget")
            if "flight" in lower or "may bay" in lower:
                if profile.days <= 3:
                    score_delta += 0.6
                    notes.append("saves time for a short trip")
            if "fare unverified" in lower or "tham khao" in lower:
                score_delta -= 0.4
                notes.append("fare needs final verification")
            if profile.preferred_transport and self._transport_matches(profile.preferred_transport, lower):
                score_delta += 3.0 if profile.preferred_transport == "train" else 1.4
                notes.append(f"matches requested transport mode: {profile.preferred_transport}")
            elif profile.preferred_transport == "train" and ("flight" in lower or "may bay" in lower or "mÃ¡y bay" in lower):
                score_delta -= 1.2
                notes.append("flight is only a fallback when no reliable live train offer is available")

            advised.append(self._clone_with_advice(option, option.score + score_delta, "Transport advisor", notes))
        sorted_options = self._sort(advised)
        if profile.preferred_transport:
            matching = [
                item for item in sorted_options
                if self._transport_matches(profile.preferred_transport, f"{item.title} {item.details} {item.reason}".lower())
            ]
            if matching:
                others = [item for item in sorted_options if item not in matching]
                return matching + others
        return sorted_options

    def advise_hotels(self, request: UserRequest, hotels: list[Recommendation]) -> list[Recommendation]:
        profile = self.build_profile(request)
        lodging_cap = profile.budget * 0.42
        advised = []
        for index, hotel in enumerate(hotels):
            score_delta = self._budget_fit_score(int(hotel.price or 0), lodging_cap)
            notes = []
            if hotel.price:
                notes.append(f"stay cost uses about {self._percent(hotel.price, profile.budget)} of budget")
            else:
                notes.append("booking-grade price is missing")
                score_delta -= 0.9

            text = f"{hotel.details} {hotel.reason}"
            if any(source in text for source in self.BOOKING_GRADE_SOURCES):
                score_delta += 0.7
                notes.append("live booking price source")
            elif "Booking price: unavailable" in text:
                score_delta -= 0.5
                notes.append("discovery result only, verify price before proposing")

            if "comfort" in profile.priorities and ("resort" in text.lower() or "hotel" in text.lower()):
                score_delta += 0.3
                notes.append("fits comfort-oriented trip")

            advised.append(self._clone_with_advice(hotel, hotel.score + score_delta, "Hotel advisor", notes))
        return self._sort(advised)

    def advise_attractions(self, request: UserRequest, attractions: list[Recommendation], weather_summary: str) -> list[Recommendation]:
        profile = self.build_profile(request)
        interests = {value.lower() for value in request.interests}
        rainy = "rain" in weather_summary.lower() or "mua" in weather_summary.lower()
        advised = []
        for index, attraction in enumerate(attractions):
            text = f"{attraction.title} {attraction.details} {attraction.reason}".lower()
            overlap = sum(1 for interest in interests if interest and interest in text)
            score_delta = min(overlap * 0.8, 2.0)
            notes = []
            if overlap:
                notes.append("matches stated interests")
            if rainy and "outdoor" in text:
                score_delta -= 0.8
                notes.append("outdoor stop is weather-sensitive")
            if attraction.price <= 0:
                score_delta += 0.2
                notes.append("low direct ticket cost")
            if "scenic" in profile.priorities and ("photo" in text or "nature" in text or "beach" in text):
                score_delta += 0.4
                notes.append("good scenic/photo fit")

            advised.append(self._clone_with_advice(attraction, attraction.score + score_delta, "Attraction advisor", notes))
        return self._sort(advised)

    def build_advisor_summary(
        self,
        request: UserRequest,
        transport: list[Recommendation],
        hotels: list[Recommendation],
        attractions: list[Recommendation],
        estimated_cost: int,
    ) -> tuple[str, dict]:
        profile = self.build_profile(request)
        is_vi = (request.lang or "vi").lower() == "vi"
        budget_gap = estimated_cost - profile.budget if profile.budget else 0
        preferred_transport_available = (
            bool(profile.preferred_transport)
            and any(self._transport_matches(profile.preferred_transport, f"{item.title} {item.details} {item.reason}".lower()) for item in transport)
        )

        if is_vi:
            lines = [
                "Goc tu van: he thong da danh gia option theo muc phu hop voi yeu cau, khong chi liet ke du lieu live.",
                f"Ho so khach: {profile.travelers} nguoi, {profile.days} ngay, ngan sach moi nguoi moi ngay khoang {profile.per_person_day_budget:,} VND, nhom {profile.budget_tier}.",
            ]
            if profile.preferred_transport and not preferred_transport_available:
                lines.append(f"Khach uu tien {profile.preferred_transport}, nhung hien chua co option du tin cay tu nguon live nen he thong chon phuong an kha thi gan nhat.")
            if transport:
                lines.append(f"Phuong an nen uu tien: {transport[0].title}.")
            if hotels:
                lines.append(f"Luu tru nen uu tien: {hotels[0].title}.")
            if attractions:
                lines.append(f"Trai nghiem nen xep truoc: {', '.join(item.title for item in attractions[:3])}.")
            if profile.budget:
                lines.append("Danh gia ngan sach: phu hop." if budget_gap <= 0 else f"Danh gia ngan sach: vuot khoang {budget_gap:,} VND, nen doi option re hon hoac tang ngan sach.")
        else:
            lines = [
                "Advisor view: options are ranked by fit to the traveler, not just by live-data availability.",
                f"Traveler profile: {profile.travelers} travelers, {profile.days} days, about {profile.per_person_day_budget:,} VND per person per day, {profile.budget_tier} tier.",
            ]
            if profile.preferred_transport and not preferred_transport_available:
                lines.append(f"The traveler prefers {profile.preferred_transport}, but no reliable live option for that mode is currently available, so the closest feasible option is selected.")
            if transport:
                lines.append(f"Prioritize transport: {transport[0].title}.")
            if hotels:
                lines.append(f"Prioritize stay: {hotels[0].title}.")
            if attractions:
                lines.append(f"Prioritize experiences: {', '.join(item.title for item in attractions[:3])}.")
            if profile.budget:
                lines.append("Budget view: fits." if budget_gap <= 0 else f"Budget view: about {budget_gap:,} VND above budget.")

        status = {
            "profile": profile.__dict__,
            "selection_method": "budget fit + source confidence + interest fit + trip duration trade-offs",
            "missing_signals": profile.missing_signals,
            "budget_gap": budget_gap,
            "primary_picks": {
                "transport": transport[0].title if transport else "",
                "hotel": hotels[0].title if hotels else "",
                "attractions": [item.title for item in attractions[:3]],
            },
            "agent_reviews": self._build_agent_reviews(profile, transport, hotels, attractions, budget_gap),
        }
        return "\n".join(lines), status

    def _build_agent_reviews(
        self,
        profile: RequestProfile,
        transport: list[Recommendation],
        hotels: list[Recommendation],
        attractions: list[Recommendation],
        budget_gap: int,
    ) -> list[dict]:
        return [
            self._agent_review(
                agent="TransportAgent",
                role="Chon cach di phu hop voi thoi gian, ngan sach va phuong tien khach uu tien.",
                pick=transport[0] if transport else None,
                fallback="Chua co phuong an di chuyen du tin cay.",
                extra_reason=(
                    f"Khach uu tien {profile.preferred_transport}, agent uu tien option cung loai khi du lieu live co san."
                    if profile.preferred_transport
                    else "Khach khong khoa phuong tien, agent uu tien can bang chi phi va do kha thi."
                ),
            ),
            self._agent_review(
                agent="HotelAgent",
                role="Loc noi luu tru theo gia tong ky nghi, do tin cay nguon gia va muc thoai mai.",
                pick=hotels[0] if hotels else None,
                fallback="Chua co noi luu tru phu hop du tin cay.",
                extra_reason="Gia booking-grade duoc uu tien hon ket qua chi mang tinh discovery.",
            ),
            self._agent_review(
                agent="AttractionAgent",
                role="Xep trai nghiem theo so ngay, so thich neu co va dieu kien thoi tiet.",
                pick=attractions[0] if attractions else None,
                fallback="Chua co diem trai nghiem phu hop.",
                extra_reason=(
                    "Khach chua nhap so thich, agent chon cac diem co tinh kha thi va chi phi thap."
                    if "interests" in profile.missing_signals
                    else "Cac diem co tag trung voi so thich duoc uu tien."
                ),
            ),
            {
                "agent": "RootAdvisor",
                "role": "Tong hop cac agent con thanh mot goi de xuat co the hanh dong.",
                "pick": "Ngan sach phu hop" if budget_gap <= 0 else "Can can chinh ngan sach",
                "confidence": "high" if budget_gap <= 0 else "medium",
                "reason": (
                    "Tong chi phi uoc tinh nam trong ngan sach khach da nhap."
                    if budget_gap <= 0
                    else f"Tong chi phi uoc tinh vuot ngan sach khoang {budget_gap:,} VND."
                ),
            },
        ]

    @staticmethod
    def _agent_review(agent: str, role: str, pick: Recommendation | None, fallback: str, extra_reason: str) -> dict:
        if pick is None:
            return {
                "agent": agent,
                "role": role,
                "pick": fallback,
                "confidence": "low",
                "reason": "Nguon du lieu hien tai chua du de agent chot option.",
            }

        confidence = "high"
        if pick.price <= 0:
            confidence = "medium"
        if "unavailable" in pick.details.lower() or "unverified" in pick.details.lower() or "tham khao" in pick.details.lower():
            confidence = "medium"

        return {
            "agent": agent,
            "role": role,
            "pick": pick.title,
            "confidence": confidence,
            "reason": extra_reason,
        }

    @staticmethod
    def _budget_fit_score(cost: int, cap: float) -> float:
        if not cost or not cap:
            return 0.0
        ratio = cost / cap
        if ratio <= 0.75:
            return 1.0
        if ratio <= 1.0:
            return 0.6
        if ratio <= 1.25:
            return -0.2
        if ratio <= 1.6:
            return -0.8
        return -1.4

    @staticmethod
    def _transport_matches(mode: str, text: str) -> bool:
        aliases = {
            "flight": ("flight", "may bay", "máy bay"),
            "train": ("train", "tau hoa", "tàu hỏa", "tàu hoả"),
            "bus": ("bus", "xe khach", "xe khách", "limousine"),
            "car": ("car", "oto", "o to", "ô tô", "road transfer"),
            "mixed": ("mixed", "noi chang", "nối chặng"),
        }
        return any(alias in text for alias in aliases.get(mode, (mode,)))

    @staticmethod
    def _percent(value: int, total: int) -> str:
        if not total:
            return "an unknown share"
        return f"{round(value / total * 100)}%"

    @staticmethod
    def _clone_with_advice(option: Recommendation, score: float, label: str, notes: list[str]) -> Recommendation:
        advice = "; ".join(notes) if notes else "reasonable fit based on available data"
        reason = f"{label}: {advice}. {option.reason}".strip()
        details = option.details
        if advice and advice not in details:
            details = f"{details} | Tu van: {advice}"
        return option.model_copy(update={"score": round(score, 2), "reason": reason, "details": details})

    @staticmethod
    def _sort(options: list[Recommendation]) -> list[Recommendation]:
        return sorted(options, key=lambda item: (-item.score, item.price if item.price > 0 else 10**12, item.title))
