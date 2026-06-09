from __future__ import annotations

from datetime import date, timedelta

from schemas.models import AgentResult, Recommendation, UserRequest
from services.live_travel_service import fetch_live_hotels
from services.location_service import canonicalize_location


class HotelAgent:
    name = "hotel-agent"

    def run(self, request: UserRequest) -> AgentResult:
        destination = canonicalize_location(request.destination)
        nights = max(request.days - 1, 1)
        checkin_date = request.departure_date or None
        checkout_date = None
        if checkin_date:
            try:
                checkout_date = (date.fromisoformat(checkin_date) + timedelta(days=nights)).isoformat()
            except ValueError:
                checkout_date = None
        else:
            checkin = date.today() + timedelta(days=14)
            checkin_date = checkin.isoformat()
            checkout_date = (checkin + timedelta(days=nights)).isoformat()
        hotels = fetch_live_hotels(
            destination,
            checkin_date=checkin_date,
            checkout_date=checkout_date,
            adults=request.travelers,
            rooms=1,
        )

        if not hotels:
            return AgentResult(
                agent=self.name,
                summary="No stable hotel discovery data available.",
                recommendations=[],
                notes=["No live hotel discovery result returned from the current providers."],
                source="No stable hotel data",
                status="empty",
            )

        source = hotels[0].get("source", "Unknown")
        booking_price_sources = {"SerpAPI Google Hotels", "RapidAPI booking-com15"}
        has_booking_prices = source in booking_price_sources
        if has_booking_prices:
            notes = [
                f"Hotel booking price source active: {source}.",
                "Prices are returned for the selected dates and should still be verified before payment.",
            ]
        else:
            notes = [
                f"Hotel discovery source active: {source}.",
                "No booking-grade hotel price was returned, so any price-like data is treated as unavailable.",
            ]
        results = []
        for h in hotels:
            nightly_price = h.get("price_per_night", 0)
            total_stay_price = h.get("total_price") or (nightly_price * nights if h.get("source") in booking_price_sources else 0)
            rating = h.get("rating", 0) or 0
            review_count = h.get('review_count') or 0
            interest_bonus = 1 if any(i.lower() in [a.lower() for a in h.get("amenities", [])] for i in request.interests) else 0
            score = round((rating * 1.15) + min(review_count / 500, 2.0) + interest_bonus, 2)

            currency = h.get('currency') or 'VND'
            review_word = h.get('review_word') or ''
            room_label = h.get('room_label') or ''
            detail_parts = [
                f"Area: {h['area']}",
                f"Rating: {rating} {review_word} ({review_count})",
            ]
            if room_label:
                detail_parts.append(f"Room: {room_label}")
            if h.get("distance_km") is not None:
                detail_parts.append(f"Distance: {h['distance_km']} km from destination center")
            if h.get('included_taxes'):
                detail_parts.append('Includes taxes and fees')
            if h.get('free_cancellation'):
                detail_parts.append('Free cancellation')
            if h.get('no_prepayment'):
                detail_parts.append('No prepayment needed')
            if h.get("source") in booking_price_sources:
                if h.get("total_price"):
                    night_label = "night" if nights == 1 else "nights"
                    detail_parts.append(f"{total_stay_price:,} {currency} total for {nights} {night_label}")
                    if nightly_price:
                        detail_parts.append(f"{nightly_price:,} {currency}/night")
                elif nightly_price:
                    night_label = "night" if nights == 1 else "nights"
                    detail_parts.append(f"{nightly_price:,} {currency}/night x {nights} {night_label}")
                if h.get("price_source"):
                    detail_parts.append(f"Price source: {h['price_source']}")
            else:
                detail_parts.append("Booking price: unavailable from live hotel provider")
            detail_parts.append(f"Source: {h['source']}")
            results.append(Recommendation(
                title=h["name"],
                details=' | '.join(detail_parts),
                price=total_stay_price,
                score=score,
                reason=(
                    "Uses live hotel booking prices returned for the selected dates. Verify final taxes and fees on the booking site before payment."
                    if h.get("source") in booking_price_sources
                    else "Map/place discovery result. Booking-grade price was unavailable from the current hotel providers."
                ),
                image_url=h.get("photo_url") or "",
            ))

        results.sort(key=lambda x: (-x.score, x.price if x.price > 0 else 10**12))
        final_results = results[:4]
        if has_booking_prices:
            notes.append("Hotel shortlist is using live booking-price results for this run.")
        else:
            notes.append("Hotel shortlist does not claim booking-grade live pricing for this run.")
        return AgentResult(
            agent=self.name,
            summary=f"Found {len(final_results)} live hotel options.",
            recommendations=final_results,
            notes=notes,
            source=source,
            status="ok" if final_results else "empty",
        )
