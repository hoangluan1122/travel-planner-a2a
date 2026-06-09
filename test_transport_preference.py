import unittest

from schemas.models import Recommendation, UserRequest
from services.request_parser import parse_user_request
from services.travel_advisor import TravelAdvisor
from transport.factory import TransportStrategyFactory
from transport.models import TransportOption
from transport.strategies import MixedTransportStrategy


class FakeTrainProvider:
    def search(self, request):
        return [
            TransportOption(
                mode="train",
                provider="DSVN API",
                operator="SE1",
                departure="Ha Noi 19:30",
                arrival="Ho Chi Minh 05:45",
                price=1200000,
                duration="34h 15m",
                reason="Ket qua tau live tu DSVN.",
                price_verified=False,
                fare_label="Gia tham khao",
            )
        ]


class FakeFlightProvider:
    def search(self, request):
        return [
            TransportOption(
                mode="flight",
                provider="SerpAPI Google Flights",
                operator="VN123",
                departure="HAN 08:00",
                arrival="SGN 10:10",
                price=1600000,
                duration="2h 10m",
                reason="Ket qua chuyen bay live tu SerpAPI.",
            )
        ]


class FakeEmptyTrainProvider:
    def search(self, request):
        return []


class TransportPreferenceTests(unittest.TestCase):
    def _request(self, preferred_transport="train"):
        return UserRequest(
            origin="Ha Noi",
            destination="Ho Chi Minh",
            departure_date="2026-06-18",
            preferred_transport=preferred_transport,
            days=2,
            budget=12000000,
            travelers=1,
            adults=1,
            children=0,
            interests=[],
        )

    def test_parser_detects_train_preference_from_ui_text(self):
        parsed = parse_user_request(
            "Toi muon di Sai Gon, 2 ngay, ngan sach 12 trieu, uu tien phuong tien tau hoa.",
            origin="Ha Noi",
        )

        self.assertEqual(parsed.preferred_transport, "train")

    def test_parser_keeps_destination_after_from_to_train_sentence(self):
        parsed = parse_user_request(
            "Toi muon di bang tau hoa tu Ha Noi toi Sai Gon, 2 ngay, ngan sach 12 trieu.",
            origin="Ha Noi",
        )

        self.assertEqual(parsed.origin, "HAN")
        self.assertEqual(parsed.destination, "Ho Chi Minh")
        self.assertEqual(parsed.preferred_transport, "train")

    def test_mixed_strategy_promotes_live_train_when_train_is_preferred(self):
        strategy = MixedTransportStrategy([FakeTrainProvider(), FakeFlightProvider()])

        options = strategy.get_options(self._request())

        self.assertGreaterEqual(len(options), 2)
        self.assertEqual(options[0].mode, "train")
        self.assertEqual(options[0].tag, "De xuat chinh")
        self.assertIn("Preferred transport honored", " ".join(strategy.notes))

    def test_mixed_strategy_allows_flight_only_when_no_live_train(self):
        strategy = MixedTransportStrategy([FakeEmptyTrainProvider(), FakeFlightProvider()])

        options = strategy.get_options(self._request())

        self.assertEqual(options[0].mode, "flight")
        self.assertIn("khong co du lieu tau live du tin cay", " ".join(strategy.notes))

    def test_advisor_keeps_train_before_flight_when_train_is_preferred(self):
        advisor = TravelAdvisor()
        train = Recommendation(
            title="[De xuat chinh] SE1 Ha Noi -> Ho Chi Minh",
            details="Tau hoa | Nguon: DSVN API | 34h 15m | gia tham khao",
            price=1200000,
            score=5.0,
            reason="Uu tien tau hoa theo yeu cau cua khach.",
        )
        flight = Recommendation(
            title="VN123 HAN -> SGN",
            details="Flight | Nguon: SerpAPI Google Flights | 2h 10m",
            price=1600000,
            score=7.0,
            reason="Ket qua chuyen bay live.",
        )

        advised = advisor.advise_transport(self._request(), [flight, train])

        self.assertIn("SE1", advised[0].title)
        self.assertIn("Tau hoa", advised[0].details)

    def test_factory_uses_train_first_when_train_is_preferred(self):
        strategy = TransportStrategyFactory.create(self._request())

        provider_names = [provider.__class__.__name__ for provider in strategy.providers]
        self.assertEqual(provider_names[0], "TrainProviderAdapter")
        self.assertIn("SerpApiFlightAdapter", provider_names)


if __name__ == "__main__":
    unittest.main()
