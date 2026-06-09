from __future__ import annotations

import unittest

import agents.hotel_agent as hotel_module
from agents.hotel_agent import HotelAgent
from schemas.models import UserRequest
from services.request_parser import parse_user_request


def fake_hotel(total_price: int = 1_200_000) -> dict:
    return {
        "name": "Ha Long Pearl",
        "area": "Bai Chay",
        "rating": 4.4,
        "review_count": 1200,
        "price_per_night": total_price,
        "total_price": total_price,
        "currency": "VND",
        "room_label": "Deluxe room",
        "included_taxes": True,
        "free_cancellation": True,
        "no_prepayment": False,
        "source": "SerpAPI Google Hotels",
        "amenities": ["booking", "hotel"],
        "price_source": "Google Hotels live rate",
        "distance_km": 2.5,
    }


class HotelAgentTests(unittest.TestCase):
    def setUp(self):
        self.original_fetch = hotel_module.fetch_live_hotels

    def tearDown(self):
        hotel_module.fetch_live_hotels = self.original_fetch

    def test_room_plan_uses_two_adults_per_room_for_legacy_travelers(self):
        agent = HotelAgent()
        cases = [(1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (10, 5)]
        for travelers, expected_rooms in cases:
            request = UserRequest(destination="Ha Long", origin="HAN", days=3, budget=8000000, travelers=travelers)
            room_plan = agent._plan_room_allocation({"request": request, "debug": {}})["room_plan"]
            self.assertEqual(room_plan["rooms"], expected_rooms)
            self.assertEqual(room_plan["adults"], travelers)
            self.assertEqual(room_plan["children"], 0)
            self.assertEqual(room_plan["travelers"], travelers)

    def test_parser_extracts_adults_children_and_default_child_ages(self):
        request = parse_user_request("toi muon di Ha Long 2 ngay ngan sach 8000000 4 nguoi lon 2 tre em")
        self.assertEqual(request.adults, 4)
        self.assertEqual(request.children, 2)
        self.assertEqual(request.child_ages, [7, 7])
        self.assertEqual(request.travelers, 6)

    def test_parser_extracts_child_ages(self):
        request = parse_user_request("toi muon di Ha Long 2 ngay ngan sach 8000000 4 nguoi lon 2 tre em 5 va 8 tuoi")
        self.assertEqual(request.adults, 4)
        self.assertEqual(request.children, 2)
        self.assertEqual(request.child_ages, [5, 8])
        self.assertEqual(request.travelers, 6)

    def test_legacy_four_travelers_searches_two_adult_rooms(self):
        calls = []

        def fake_fetch(destination, limit=8, checkin_date=None, checkout_date=None, adults=2, rooms=1, children=0, child_ages=None):
            calls.append({"adults": adults, "children": children, "child_ages": child_ages, "rooms": rooms})
            return [fake_hotel(total_price=601374)]

        hotel_module.fetch_live_hotels = fake_fetch
        request = UserRequest(destination="Ha Long", origin="HAN", days=2, budget=8000000, travelers=4)

        result = HotelAgent().run(request)

        self.assertEqual(calls[0], {"adults": 4, "children": 0, "child_ages": [], "rooms": 2})
        self.assertEqual(result.extra["room_plan"]["rooms"], 2)
        self.assertEqual(result.extra["room_plan"]["travelers"], 4)
        self.assertIn("Khach: 4 nguoi lon, 0 tre em", result.recommendations[0].details)
        self.assertIn("Phong: 2 phong; Phong 1: 2 adults + 0 children; Phong 2: 2 adults + 0 children", result.recommendations[0].details)
        self.assertEqual(result.recommendations[0].price, 601374)
        self.assertEqual(result.extra["hotel_candidates"][0]["pricing_breakdown"]["nightly_room_price"], 300687)

    def test_four_travelers_two_nights_displays_room_price_formula(self):
        def fake_fetch(destination, limit=8, checkin_date=None, checkout_date=None, adults=2, rooms=1, children=0, child_ages=None):
            return [fake_hotel(total_price=1200000)]

        hotel_module.fetch_live_hotels = fake_fetch
        request = UserRequest(destination="Ha Long", origin="HAN", days=3, budget=8000000, travelers=4)

        result = HotelAgent().run(request)

        self.assertEqual(result.recommendations[0].price, 1200000)
        self.assertIn("300.000", result.recommendations[0].details)
        self.assertIn("1.200.000 VND", result.recommendations[0].details)
        self.assertEqual(result.extra["hotel_candidates"][0]["pricing_breakdown"]["nightly_room_price"], 300000)

    def test_four_adults_two_children_searches_two_rooms_with_child_ages(self):
        calls = []

        def fake_fetch(destination, limit=8, checkin_date=None, checkout_date=None, adults=2, rooms=1, children=0, child_ages=None):
            calls.append({"adults": adults, "children": children, "child_ages": child_ages, "rooms": rooms})
            return [fake_hotel(total_price=1800000)]

        hotel_module.fetch_live_hotels = fake_fetch
        request = UserRequest(destination="Ha Long", origin="HAN", days=2, budget=12000000, adults=4, children=2)

        result = HotelAgent().run(request)

        self.assertEqual(request.travelers, 6)
        self.assertEqual(calls[0], {"adults": 4, "children": 2, "child_ages": [7, 7], "rooms": 2})
        self.assertEqual(result.extra["room_plan"]["allocation"], [{"adults": 2, "children": 1}, {"adults": 2, "children": 1}])
        self.assertIn("Khach: 4 nguoi lon, 2 tre em", result.recommendations[0].details)
        self.assertIn("Tuoi tre em: 7, 7", result.recommendations[0].details)
        self.assertIn("Phong 1: 2 adults + 1 child; Phong 2: 2 adults + 1 child", result.recommendations[0].details)


if __name__ == "__main__":
    unittest.main()
