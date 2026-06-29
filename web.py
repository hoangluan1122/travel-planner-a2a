from __future__ import annotations

import os
import time
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
        return value.strip().strip("\ufeff").strip('"').strip("'")

    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip("\ufeff").strip('"').strip("'")
    return None


def normalize_lang(lang: str | None) -> str:
    if (lang or "").lower().startswith("en"):
        return "en"
    return "vi"


app = FastAPI(title="Travel Planner Web")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

PLAN_CACHE_TTL_SECONDS = 60 * 60
PLAN_CACHE_MAX_ITEMS = 50
v2_plan_cache: OrderedDict[str, dict] = OrderedDict()


class PlanTextRequest(BaseModel):
    user_text: str
    origin: str | None = None
    lang: str | None = 'vi'
    departure_date: str | None = None


def prune_plan_cache() -> None:
    now = time.time()
    expired_ids = [
        plan_id
        for plan_id, payload in v2_plan_cache.items()
        if now - payload.get("created_at", now) > PLAN_CACHE_TTL_SECONDS
    ]
    for plan_id in expired_ids:
        v2_plan_cache.pop(plan_id, None)

    while len(v2_plan_cache) > PLAN_CACHE_MAX_ITEMS:
        v2_plan_cache.popitem(last=False)


def render_home_template(request: Request, template_name: str, lang: str):
    lang = normalize_lang(lang)
    image_context = build_image_context(None)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
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


def build_plan_context(
    request: Request,
    user_text: str,
    origin: str,
    departure_date: str,
    lang: str,
) -> dict:
    lang = normalize_lang(lang)
    user_text_with_date = f"{user_text} Departure {departure_date}".strip() if departure_date else user_text
    parsed = parse_user_request(user_text_with_date, origin=origin or None)
    parsed.lang = lang
    planner = RootTravelPlannerAgent()
    result = planner.run(parsed)
    image_context = build_image_context(result)
    return {
        "request": request,
        "user_text": user_text,
        "origin_value": origin,
        "parsed": parsed,
        "result": result,
        "error": None,
        "provider_status": result.provider_status,
        "lang": lang,
        **image_context,
    }


def render_plan_template(
    request: Request,
    template_name: str,
    user_text: str,
    origin: str,
    departure_date: str,
    lang: str,
):
    try:
        context = build_plan_context(request, user_text, origin, departure_date, lang)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=context,
        )
    except Exception as ex:
        image_context = build_image_context(None)
        return templates.TemplateResponse(
            request=request,
            name=template_name,
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


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, lang: str = Query("vi")):
    return render_home_template(request, "index_v2.html", lang)


@app.get("/v2", response_class=HTMLResponse)
async def home_v2(request: Request, lang: str = Query("vi")):
    return render_home_template(request, "index_v2.html", lang)


@app.get("/plan", response_class=HTMLResponse)
async def plan_page(request: Request, lang: str = Query("vi")):
    return await home(request, lang)


@app.get("/v2/plan", response_class=HTMLResponse)
async def plan_page_v2(request: Request, lang: str = Query("vi")):
    return await home_v2(request, lang)


@app.get("/v2/result/{plan_id}", response_class=HTMLResponse)
def result_v2(request: Request, plan_id: str):
    prune_plan_cache()
    cached = v2_plan_cache.get(plan_id)
    if not cached:
        image_context = build_image_context(None)
        return templates.TemplateResponse(
            request=request,
            name="index_v2.html",
            context={
                "request": request,
                "user_text": "",
                "origin_value": "",
                "parsed": None,
                "result": None,
                "error": "Không tìm thấy kế hoạch này hoặc kế hoạch đã hết hạn. Hãy tạo lại hành trình.",
                "provider_status": None,
                "lang": "vi",
                **image_context,
            },
            status_code=404,
        )

    v2_plan_cache.move_to_end(plan_id)
    context = dict(cached["context"])
    context["request"] = request
    return templates.TemplateResponse(
        request=request,
        name="index_v2.html",
        context=context,
    )


@app.post("/plan", response_class=HTMLResponse)
def plan(request: Request, user_text: str = Form(...), origin: str = Form(""), departure_date: str = Form(""), lang: str = Form("vi")):
    return render_plan_template(request, "index.html", user_text, origin, departure_date, lang)


@app.post("/v2/plan", response_class=HTMLResponse)
def plan_v2(request: Request, user_text: str = Form(...), origin: str = Form(""), departure_date: str = Form(""), lang: str = Form("vi")):
    try:
        context = build_plan_context(request, user_text, origin, departure_date, lang)
        prune_plan_cache()
        plan_id = uuid4().hex
        v2_plan_cache[plan_id] = {
            "created_at": time.time(),
            "context": context,
        }
        return RedirectResponse(
            url=f"/v2/result/{plan_id}",
            status_code=303,
        )
    except Exception as ex:
        image_context = build_image_context(None)
        return templates.TemplateResponse(
            request=request,
            name="index_v2.html",
            context={
                "request": request,
                "user_text": user_text,
                "origin_value": origin,
                "parsed": None,
                "result": None,
                "error": str(ex),
                "provider_status": None,
                "lang": normalize_lang(lang),
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
