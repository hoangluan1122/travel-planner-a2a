from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field


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
