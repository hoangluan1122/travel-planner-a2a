from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agents.root_agent import RootTravelPlannerAgent
from services.image_service import build_image_context
from services.live_travel_service import fetch_live_attractions, fetch_live_flights_with_debug, fetch_live_hotels, reverse_geocode_to_origin
from services.request_parser import parse_user_request


def read_secret(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value

    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def normalize_lang(lang: str | None) -> str:
    if (lang or "").lower().startswith("en"):
        return "en"
    return "vi"


app = FastAPI(title="Travel Planner Web")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class PlanTextRequest(BaseModel):
    user_text: str
    origin: str | None = None
    lang: str | None = 'vi'
    departure_date: str | None = None


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, lang: str = Query("vi")):
    lang = normalize_lang(lang)
    image_context = build_image_context(None)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "result": None,
            "parsed": None,
            "user_text": "",
            "origin_value": "",
            "error": None,
            "provider_status": None,
            "lang": lang,
            **image_context,
        },
    )


@app.get("/plan", response_class=HTMLResponse)
async def plan_page(request: Request, lang: str = Query("vi")):
    return await home(request, lang)


@app.post("/plan", response_class=HTMLResponse)
def plan(request: Request, user_text: str = Form(...), origin: str = Form(""), departure_date: str = Form(""), lang: str = Form("vi")):
    lang = normalize_lang(lang)
    user_text_with_date = f"{user_text} Departure {departure_date}".strip() if departure_date else user_text
    try:
        parsed = parse_user_request(user_text_with_date, origin=origin or None)
        parsed.lang = lang
        planner = RootTravelPlannerAgent()
        result = planner.run(parsed)
        image_context = build_image_context(result)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "user_text": user_text,
                "origin_value": origin,
                "parsed": parsed,
                "result": result,
                "error": None,
                "provider_status": result.provider_status,
                "lang": lang,
                **image_context,
            },
        )
    except Exception as ex:
        image_context = build_image_context(None)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "user_text": user_text,
                "origin_value": origin,
                "parsed": None,
                "result": None,
                "error": str(ex),
                "provider_status": None,
                "lang": lang,
                **image_context,
            },
            status_code=500,
        )


@app.post("/api/plan")
def api_plan(payload: PlanTextRequest):
    user_text_with_date = f"{payload.user_text} Departure {payload.departure_date}".strip() if payload.departure_date else payload.user_text
    parsed = parse_user_request(user_text_with_date, origin=payload.origin)
    parsed.lang = payload.lang if hasattr(payload, 'lang') and payload.lang else parsed.lang
    planner = RootTravelPlannerAgent()
    result = planner.run(parsed)
    return {
        "parsed_request": parsed.model_dump(),
        "travel_plan": result.model_dump(),
        "images": build_image_context(result),
    }


@app.get("/api/debug-plan")
def debug_plan(user_text: str, origin: str | None = None):
    parsed = parse_user_request(user_text, origin=origin)
    planner = RootTravelPlannerAgent()
    result = planner.run(parsed)
    return {
        "parsed_request": parsed.model_dump(),
        "estimated_cost": result.estimated_cost,
        "cost_breakdown": (result.provider_status.get("cost") or {}).get("breakdown"),
        "provider_status": result.provider_status,
        "transport_titles": [item.title for item in result.transport_options],
        "hotel_titles": [item.title for item in result.hotels],
        "attraction_titles": [item.title for item in result.attractions],
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "openweather": bool(read_secret("OPENWEATHER_API_KEY")),
        "serpapi": bool(read_secret("SERPAPI_KEY")),
        "origin_iata": bool(read_secret("ORIGIN_IATA")),
    }


@app.get("/api/providers-status")
def providers_status(destination: str = "Da Nang", travelers: int = 2, budget: int = 8000000, origin: str | None = None):
    hotels = fetch_live_hotels(destination)
    attractions = fetch_live_attractions(destination)
    flights, flight_debug = fetch_live_flights_with_debug(destination, adults=travelers, max_price=budget, origin=origin)

    return {
        "destination": destination,
        "origin": origin,
        "weather_key_present": bool(read_secret("OPENWEATHER_API_KEY")),
        "serpapi_key_present": bool(read_secret("SERPAPI_KEY")),
        "origin_iata_present": bool(read_secret("ORIGIN_IATA")),
        "hotels_count": len(hotels),
        "attractions_count": len(attractions),
        "flights_count": len(flights),
        "hotels_preview": hotels[:2],
        "attractions_preview": attractions[:2],
        "flights_preview": flights[:2],
        "flight_debug": flight_debug,
    }


@app.get("/api/reverse-origin")
def reverse_origin(lat: float, lon: float):
    return reverse_geocode_to_origin(lat, lon)
