from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

from schemas.models import AgentResult, Recommendation, UserRequest, WeatherForecastDay
from services.location_resolver import resolve_location
from services.location_service import canonicalize_location


class WeatherAgent:
    name = "weather-agent"

    def run(self, request: UserRequest) -> AgentResult:
        real = self._try_real_weather(request)
        if real is not None:
            return real
        return AgentResult(
            agent=self.name,
            summary="No live weather data available.",
            recommendations=[],
            notes=["OpenWeather API key missing or request failed."],
            source="OpenWeather",
            status="empty",
            extra={"forecast": []},
        )

    def _load_env_api_key(self) -> str | None:
        api_key = os.getenv("OPENWEATHER_API_KEY")
        if api_key:
            return api_key.strip().strip("\ufeff").strip('"').strip("'")

        env_path = Path(__file__).resolve().parent.parent / ".env"
        if not env_path.exists():
            return None

        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENWEATHER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\ufeff").strip('"').strip("'")
        return None

    def _build_forecast(self, destination: str, api_key: str, lat: float | None = None, lon: float | None = None) -> list[dict]:
        forecast_url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            "appid": api_key,
            "units": "metric",
            "lang": "vi",
        }
        if lat is not None and lon is not None:
            params["lat"] = lat
            params["lon"] = lon
        else:
            params["q"] = destination
        with httpx.Client(timeout=8) as client:
            response = client.get(forecast_url, params=params)
            response.raise_for_status()
            data = response.json()

        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in data.get("list", []):
            dt_txt = item.get("dt_txt", "")
            if not dt_txt:
                continue
            date_key = dt_txt.split(" ")[0]
            grouped[date_key].append(item)

        forecast_days: list[dict] = []
        weekday_vi = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
        for date_key, items in list(grouped.items())[:5]:
            temps_min = [x.get("main", {}).get("temp_min", 0) for x in items]
            temps_max = [x.get("main", {}).get("temp_max", 0) for x in items]
            humidities = [x.get("main", {}).get("humidity", 0) for x in items]
            midday = min(items, key=lambda x: abs(int(x.get("dt_txt", "2000-01-01 12:00:00").split(" ")[1].split(":")[0]) - 12))
            weather = (midday.get("weather") or [{}])[0]
            dt = datetime.strptime(date_key, "%Y-%m-%d")
            forecast_days.append(
                WeatherForecastDay(
                    date=date_key,
                    day_label=weekday_vi[dt.weekday()],
                    icon=weather.get("icon", ""),
                    description=weather.get("description", "Không có mô tả"),
                    temp_min=round(min(temps_min), 1) if temps_min else 0,
                    temp_max=round(max(temps_max), 1) if temps_max else 0,
                    humidity=round(sum(humidities) / len(humidities)) if humidities else 0,
                ).model_dump()
            )
        return forecast_days

    def _try_real_weather(self, request: UserRequest) -> AgentResult | None:
        api_key = self._load_env_api_key()
        if not api_key:
            return None

        resolved_destination = resolve_location(request.destination)
        destination = canonicalize_location(request.destination)
        weather_url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "appid": api_key,
            "units": "metric",
            "lang": "vi",
        }
        if resolved_destination.lat is not None and resolved_destination.lon is not None:
            params["lat"] = resolved_destination.lat
            params["lon"] = resolved_destination.lon
        else:
            params["q"] = destination
        try:
            with httpx.Client(timeout=6) as client:
                response = client.get(weather_url, params=params)
                response.raise_for_status()
                data = response.json()

            weather = data.get("weather", [{}])[0]
            weather_main = weather.get("main", "Unknown")
            weather_desc = weather.get("description", "không có mô tả")
            icon = weather.get("icon", "")
            main = data.get("main", {})
            temp = main.get("temp")
            feels_like = main.get("feels_like")
            humidity = main.get("humidity")
            wind = data.get("wind", {}).get("speed")
            clouds = data.get("clouds", {}).get("all")

            summary = f"Thời tiết: {weather_desc}. Nhiệt độ khoảng {temp}°C, cảm giác như {feels_like}°C."
            notes = []
            if humidity is not None:
                notes.append(f"Độ ẩm: {humidity}%")
            if wind is not None:
                notes.append(f"Tốc độ gió: {wind} m/s")
            if clouds is not None:
                notes.append(f"Mây che phủ: {clouds}%")

            forecast = self._build_forecast(destination, api_key, resolved_destination.lat, resolved_destination.lon)

            return AgentResult(
                agent=self.name,
                summary=summary,
                recommendations=[
                    Recommendation(
                        title="Live weather",
                        details=summary,
                        reason="Used for planning attractions and trip timing.",
                    )
                ],
                notes=notes,
                source="OpenWeather",
                status="ok",
                extra={
                    "current": {
                        "icon": icon,
                        "description": weather_desc,
                        "temp": temp,
                        "feels_like": feels_like,
                        "humidity": humidity,
                        "wind": wind,
                        "clouds": clouds,
                    },
                    "forecast": forecast,
                },
            )
        except Exception as exc:
            return AgentResult(
                agent=self.name,
                summary="No live weather data available.",
                recommendations=[],
                notes=[f"OpenWeather error: {exc}"],
                source="OpenWeather",
                status="empty",
                extra={"forecast": []},
            )
