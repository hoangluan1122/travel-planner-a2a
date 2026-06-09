from __future__ import annotations

import unittest

import agents.attraction_agent as attraction_module
from agents.attraction_agent import AttractionAgent
from schemas.models import AgentResult, UserRequest
from services.request_parser import parse_user_request


class AttractionAgentTests(unittest.TestCase):
    def setUp(self):
        self.original_live = attraction_module.fetch_activity_attractions
        self.original_curated = attraction_module.fetch_curated_activity_attractions
        self.weather = AgentResult(agent="weather", summary="Sunny", recommendations=[])

    def tearDown(self):
        attraction_module.fetch_activity_attractions = self.original_live
        attraction_module.fetch_curated_activity_attractions = self.original_curated

    def test_parser_detects_swimming_interest(self):
        request = parse_user_request("toi muon di Ha Long 3 ngay ngan sach 8000000 thich tam bien")
        self.assertIn("beach", request.interests)
        self.assertIn("swimming", request.interests)

    def test_beach_strategy_filters_irrelevant_places(self):
        attraction_module.fetch_activity_attractions = lambda destination, strategy, hotel_context=None, limit=12: [
            {"name": "Ha Long Museum", "type": "indoor", "interest_tags": ["museum", "history", "culture"], "cost": 100000, "source": "Mock", "area": "Hon Gai"},
            {"name": "Tuan Chau Beach", "type": "outdoor", "interest_tags": ["beach", "swimming"], "cost": 0, "source": "Mock", "area": "Tuan Chau"},
            {"name": "Bai Chay Beach", "type": "outdoor", "interest_tags": ["beach", "swimming"], "cost": 0, "source": "Mock", "area": "Bai Chay"},
        ]
        attraction_module.fetch_curated_activity_attractions = lambda destination, strategy="general", limit=10: []
        request = UserRequest(destination="Ha Long", origin="HAN", days=3, budget=8000000, interests=["beach", "swimming"], travelers=2)

        result = AttractionAgent().run(request, weather=self.weather, hotel_context={"area": "Bai Chay", "confidence": "medium"})

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.recommendations[0].title, "Bai Chay Beach")
        self.assertNotIn("Ha Long Museum", [item.title for item in result.recommendations])
        self.assertEqual(result.extra["debug"]["strategy"], "beach_swimming")

    def test_curated_fallback_when_live_results_are_not_relevant(self):
        attraction_module.fetch_activity_attractions = lambda destination, strategy, hotel_context=None, limit=12: [
            {"name": "Random Monument", "type": "outdoor", "interest_tags": ["historic", "culture"], "cost": 0, "source": "Mock", "area": "Hon Gai"},
        ]
        attraction_module.fetch_curated_activity_attractions = lambda destination, strategy="general", limit=10: [
            {"name": "Bai Chay Beach", "type": "outdoor", "interest_tags": ["beach", "swimming"], "cost": 0, "source": "Curated Ha Long attractions", "area": "Bai Chay"},
            {"name": "Tuan Chau Beach", "type": "outdoor", "interest_tags": ["beach", "swimming"], "cost": 0, "source": "Curated Ha Long attractions", "area": "Tuan Chau"},
        ]
        request = UserRequest(destination="Ha Long", origin="HAN", days=3, budget=8000000, interests=["swimming"], travelers=2)

        result = AttractionAgent().run(request, weather=self.weather, hotel_context={"area": "Tuan Chau", "confidence": "medium"})

        self.assertEqual([item.title for item in result.recommendations[:2]], ["Tuan Chau Beach", "Bai Chay Beach"])
        self.assertEqual(result.extra["debug"]["curated_count"], 2)


if __name__ == "__main__":
    unittest.main()
