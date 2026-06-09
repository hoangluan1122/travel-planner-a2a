from __future__ import annotations

from schemas.models import UserRequest
from transport.factory import TransportStrategyFactory
from transport.models import TransportResult
from transport.validator import TransportValidator


class TransportAgent:
    name = "transport-agent"

    def __init__(self):
        self.strategy_factory = TransportStrategyFactory()
        self.validator = TransportValidator()

    def run(self, request: UserRequest) -> TransportResult:
        strategy = self.strategy_factory.create(request)
        raw_options = strategy.get_options(request)
        options, dropped_notes = self.validator.filter_options(raw_options, request.origin, request.destination)
        strategy_name = strategy.__class__.__name__
        notes = [
            f"Strategy selected: {strategy_name}",
            f"Transport options returned before validation: {len(raw_options)}",
            f"Transport options kept after validation: {len(options)}",
        ]
        notes.extend(getattr(strategy, "notes", []))
        notes.extend(dropped_notes)
        for option in options[:5]:
            notes.append(f"{option.mode}:{option.operator}:{option.departure}->{option.arrival}:{option.price}")
        return TransportResult(
            selected_strategy=strategy_name,
            options=options,
            notes=notes,
        )
