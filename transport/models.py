from __future__ import annotations

from pydantic import BaseModel, Field


class TransportOption(BaseModel):
    mode: str
    provider: str
    operator: str
    departure: str
    arrival: str
    price: int = 0
    duration: str = ""
    score: float = 0.0
    reason: str = ""
    tag: str = ""
    uses_nearest_hub: bool = False
    origin_hub: str | None = None
    destination_hub: str | None = None
    price_verified: bool = True
    fare_label: str = ""


class TransportResult(BaseModel):
    selected_strategy: str
    options: list[TransportOption] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
