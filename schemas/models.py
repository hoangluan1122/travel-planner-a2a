from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field, model_validator


class UserRequest(BaseModel):
    destination: str
    origin: str = Field(default="SGN")
    lang: str = Field(default="vi")
    departure_date: str = Field(default="", description="Departure date in YYYY-MM-DD when available")
    preferred_transport: str = Field(default="", description="Preferred transport mode when the user states one")
    days: int = Field(ge=1, le=14)
    budget: int = Field(gt=0, description="Budget in VND")
    interests: List[str] = Field(default_factory=list)
    travelers: int = Field(default=1, ge=1, le=10)
    adults: int = Field(default=1, ge=1, le=10)
    children: int = Field(default=0, ge=0, le=10)
    child_ages: List[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _sync_guest_counts(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        has_adults = values.get("adults") is not None
        has_children = values.get("children") is not None
        travelers = int(values.get("travelers") or 1)
        children = max(int(values.get("children") or 0), 0)
        if has_adults or has_children:
            adults = max(int(values.get("adults") or max(travelers - children, 1)), 1)
            values["adults"] = adults
            values["children"] = children
            values["travelers"] = min(max(adults + children, 1), 10)
        else:
            values["adults"] = max(travelers, 1)
            values["children"] = 0
            values["travelers"] = max(travelers, 1)

        child_ages = [int(age) for age in (values.get("child_ages") or []) if str(age).strip().isdigit()]
        if len(child_ages) < values["children"]:
            child_ages.extend([7] * (values["children"] - len(child_ages)))
        values["child_ages"] = child_ages[: values["children"]]
        return values


class Recommendation(BaseModel):
    title: str
    details: str
    price: int = 0
    score: float = 0.0
    reason: str = ""
    image_url: str = ""


class WeatherForecastDay(BaseModel):
    date: str
    day_label: str
    icon: str = ""
    description: str = ""
    temp_min: float = 0.0
    temp_max: float = 0.0
    humidity: int = 0


class AgentResult(BaseModel):
    agent: str
    summary: str
    recommendations: List[Recommendation] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    source: str = "live"
    status: str = "ok"
    extra: dict = Field(default_factory=dict)


class DailyPlan(BaseModel):
    day: int
    title: str
    morning: str
    afternoon: str
    evening: str
    estimated_cost: int = 0


class TravelPlan(BaseModel):
    destination: str
    origin: str
    days: int
    weather_summary: str
    weather_extra: dict = Field(default_factory=dict)
    transport_options: List[Recommendation]
    hotels: List[Recommendation]
    attractions: List[Recommendation]
    daily_itinerary: List[DailyPlan] = Field(default_factory=list)
    estimated_cost: int
    final_recommendation: str
    provider_status: dict = Field(default_factory=dict)
