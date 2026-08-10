"""Flask routes for Scenario Analysis and AI Portfolio Insights."""

from flask import Blueprint, jsonify, render_template, request

from app.scenario_engine import build_portfolio_snapshot, run_scenario
from app.services.external_apis import (
    ExternalAPIError,
    get_gemini_explanation,
    get_news,
    get_oil_price,
    get_schedule_context,
    get_weather,
    weather_severity,
)
from app.fleet_dashboard import find_vessel


scenario_bp = Blueprint("scenario", __name__)


@scenario_bp.get("/vessels/<vessel_id>/scenario")
def scenario_page(vessel_id):
    vessel = find_vessel(vessel_id)
    if vessel is None:
        return "Vessel not found", 404

    return render_template(
        "scenario_analysis/scenario.html",
        vessel=vessel,
    )


@scenario_bp.post("/api/vessels/<vessel_id>/scenario")
def scenario_api(vessel_id):
    vessel = find_vessel(vessel_id)
    if vessel is None:
        return jsonify({"error": "Vessel not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        result = run_scenario(vessel_id, data)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@scenario_bp.get("/api/vessels/<vessel_id>/live-intelligence")
def live_intelligence(vessel_id):
    vessel = find_vessel(vessel_id)
    if vessel is None:
        return jsonify({"error": "Vessel not found"}), 404

    # The repository's prototype data may not contain IMO, so schedule lookup
    # remains optional and configurable.
    weather = {}
    weather_level = {}
    try:
        # Singapore is the default bunker location for many prototype voyages.
        from app.scenario_engine import PORT_COORDINATES
        port_name = vessel["next_bunkering_port"]
        coords = PORT_COORDINATES.get(port_name)
        if coords:
            weather = get_weather(coords["lat"], coords["lng"])
            weather_level = weather_severity(weather)
    except ExternalAPIError as exc:
        weather = {"available": False, "error": str(exc)}
        weather_level = {"level": "Unknown", "score": 0, "reasons": []}

    try:
        oil = get_oil_price()
    except ExternalAPIError as exc:
        oil = {"available": False, "error": str(exc)}

    query = (
        f'"{vessel["origin"]}" OR "{vessel["destination"]}" OR '
        f'"{vessel["next_bunkering_port"]}" shipping port disruption'
    )
    try:
        news = get_news(query)
    except ExternalAPIError as exc:
        news = {"available": False, "error": str(exc), "articles": []}

    from app.scenario_engine import get_port_unlocode
    schedule = get_schedule_context(
        vessel,
        get_port_unlocode(vessel["origin"]),
        get_port_unlocode(vessel["destination"]),
        get_port_unlocode(vessel["next_bunkering_port"]),
    )

    return jsonify({
        "weather": weather,
        "weather_severity": weather_level,
        "oil": oil,
        "news": news,
        "schedule": schedule,
    })


@scenario_bp.post("/api/vessels/<vessel_id>/ai-explanation")
def ai_explanation(vessel_id):
    if find_vessel(vessel_id) is None:
        return jsonify({"error": "Vessel not found"}), 404

    data = request.get_json(silent=True) or {}
    try:
        result = get_gemini_explanation(data)
        return jsonify(result)
    except ExternalAPIError as exc:
        return jsonify({"available": False, "error": str(exc)}), 503


@scenario_bp.post("/api/portfolio/ai-explanation")
def portfolio_ai_explanation():
    data = request.get_json(silent=True) or {}
    try:
        result = get_gemini_explanation({
            "analysis_type": "fleet_portfolio",
            "portfolio": data,
        })
        return jsonify(result)
    except ExternalAPIError as exc:
        return jsonify({"available": False, "error": str(exc)}), 503


@scenario_bp.get("/ai-insights")
def portfolio_page():
    return render_template("ai_insights/portfolio.html")


@scenario_bp.get("/api/portfolio")
def portfolio_api():
    return jsonify(build_portfolio_snapshot())

app/services/__init__.py

"""External intelligence connectors for the maritime scenario platform."""

app/services/external_apis.py

"""External API adapters for the maritime decision-support prototype."""

import json
import os
from datetime import date
from typing import Any

import requests

REQUEST_TIMEOUT = int(os.getenv("API_TIMEOUT_SECONDS", "10"))


class ExternalAPIError(RuntimeError):
    pass


def _request(method: str, url: str, **kwargs) -> dict[str, Any]:
    try:
        response = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise ExternalAPIError(f"External API request failed: {exc}") from exc


def get_weather(lat: float, lon: float) -> dict[str, Any]:
    key = os.getenv("OPENWEATHER_API_KEY")
    if not key:
        return {"available": False, "error": "OPENWEATHER_API_KEY is not configured"}

    data = _request(
        "GET",
        "https://api.openweathermap.org/data/2.5/weather",
        params={"lat": lat, "lon": lon, "appid": key, "units": "metric"},
    )
    weather = (data.get("weather") or [{}])[0]
    return {
        "available": True,
        "temperature_c": data.get("main", {}).get("temp"),
        "feels_like_c": data.get("main", {}).get("feels_like"),
        "wind_speed_mps": data.get("wind", {}).get("speed"),
        "wind_gust_mps": data.get("wind", {}).get("gust"),
        "weather": weather.get("main"),
        "description": weather.get("description"),
        "rain_1h_mm": data.get("rain", {}).get("1h", 0),
        "clouds_pct": data.get("clouds", {}).get("all"),
        "observed_at": data.get("dt"),
        "source": "OpenWeather",
    }


def weather_severity(weather: dict[str, Any]) -> dict[str, Any]:
    if not weather.get("available"):
        return {"level": "Unknown", "score": 0, "reasons": ["Live weather unavailable"]}

    wind = float(weather.get("wind_speed_mps") or 0)
    gust = float(weather.get("wind_gust_mps") or 0)
    rain = float(weather.get("rain_1h_mm") or 0)
    description = str(weather.get("description") or "").lower()

    score = 0
    reasons = []
    if wind >= 17 or gust >= 22:
        score += 3
        reasons.append("Strong wind")
    elif wind >= 12 or gust >= 16:
        score += 2
        reasons.append("Elevated wind")
    elif wind >= 8:
        score += 1
        reasons.append("Moderate wind")

    if rain >= 10:
        score += 2
        reasons.append("Heavy rainfall")
    elif rain >= 3:
        score += 1
        reasons.append("Rainfall")

    if any(word in description for word in ("storm", "thunder", "squall", "tropical")):
        score += 3
        reasons.append("Severe weather description")

    level = "Severe" if score >= 5 else "Moderate" if score >= 3 else "Mild" if score >= 1 else "None"
    return {"level": level, "score": score, "reasons": reasons}


def get_oil_price() -> dict[str, Any]:
    key = os.getenv("OILPRICEAPI_KEY")
    if not key:
        return {"available": False, "error": "OILPRICEAPI_KEY is not configured"}

    data = _request(
        "GET",
        "https://api.oilpriceapi.com/v1/prices/latest",
        params={"by_code": "BRENT_CRUDE_USD"},
        headers={"Authorization": f"Token {key}"},
    )
    payload = data.get("data", data)
    return {
        "available": True,
        "code": payload.get("code", "BRENT_CRUDE_USD"),
        "price": payload.get("price"),
        "formatted": payload.get("formatted"),
        "created_at": payload.get("created_at"),
        "source": payload.get("source", "OilPriceAPI"),
    }


def get_news(query: str, page_size: int = 8) -> dict[str, Any]:
    key = os.getenv("NEWS_API_KEY")
    if not key:
        return {"available": False, "error": "NEWS_API_KEY is not configured", "articles": []}

    data = _request(
        "GET",
        "https://newsapi.org/v2/everything",
        params={
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max(1, min(page_size, 20)),
        },
        headers={"X-Api-Key": key},
    )

    articles = []
    for article in data.get("articles", []):
        articles.append({
            "title": article.get("title"),
            "description": article.get("description"),
            "url": article.get("url"),
            "source": (article.get("source") or {}).get("name"),
            "published_at": article.get("publishedAt"),
        })

    return {
        "available": True,
        "total_results": data.get("totalResults", len(articles)),
        "articles": articles,
        "source": "NewsAPI",
    }


SCHEDULE_BASE_URL = os.getenv("SCHEDULE_API_BASE_URL", "https://schedules.searates.com/api/v2").rstrip("/")


def _schedule_headers() -> dict[str, str]:
    key = os.getenv("SCHEDULE_API_KEY")
    return {"X-API-KEY": key} if key else {}


def get_schedule_by_points(origin: str, destination: str, cargo_type: str = "GC", weeks: int = 3) -> dict[str, Any]:
    """Ship Schedules API 2.0 /schedules/by-points."""
    key = os.getenv("SCHEDULE_API_KEY")
    if not key:
        return {"available": False, "error": "SCHEDULE_API_KEY is not configured"}

    params = {
        "cargo_type": cargo_type,
        "origin": origin,
        "destination": destination,
        "from_date": date.today().isoformat(),
        "weeks": max(1, min(int(weeks), 6)),
        "sort": "DEP",
        "direct_only": "false",
        "multimodal": "true",
    }
    return _request(
        "GET",
        f"{SCHEDULE_BASE_URL}/schedules/by-points",
        params=params,
        headers=_schedule_headers(),
    )


def get_schedule_by_vessel(imo: str, voyages: str | None = None) -> dict[str, Any]:
    """Ship Schedules API 2.0 /schedules/by-vessel."""
    key = os.getenv("SCHEDULE_API_KEY")
    if not key:
        return {"available": False, "error": "SCHEDULE_API_KEY is not configured"}
    params = {"imo": int(imo)}
    if voyages:
        params["voyages"] = voyages
    return _request(
        "GET",
        f"{SCHEDULE_BASE_URL}/schedules/by-vessel",
        params=params,
        headers=_schedule_headers(),
    )


def get_schedule_by_port(locode: str, weeks: int = 3) -> dict[str, Any]:
    """Ship Schedules API 2.0 /schedules/by-port."""
    key = os.getenv("SCHEDULE_API_KEY")
    if not key:
        return {"available": False, "error": "SCHEDULE_API_KEY is not configured"}
    params = {
        "locode": locode,
        "from_date": date.today().isoformat(),
        "weeks": max(1, min(int(weeks), 6)),
    }
    return _request(
        "GET",
        f"{SCHEDULE_BASE_URL}/schedules/by-port",
        params=params,
        headers=_schedule_headers(),
    )


def get_schedule_context(vessel: dict[str, Any], origin_code: str | None, destination_code: str | None, bunker_code: str | None) -> dict[str, Any]:
    """Prefer vessel schedule when IMO is known; otherwise use by-points, then by-port."""
    imo = vessel.get("imo")
    if imo:
        try:
            result = get_schedule_by_vessel(str(imo))
            return {"mode": "vessel", **result}
        except ExternalAPIError as exc:
            vessel_error = str(exc)
    else:
        vessel_error = "No IMO is present in this prototype vessel record"

    if origin_code and destination_code:
        try:
            result = get_schedule_by_points(origin_code, destination_code)
            return {"mode": "points", **result, "fallback_reason": vessel_error}
        except ExternalAPIError as exc:
            points_error = str(exc)
    else:
        points_error = "Origin/destination UNLOCODE not mapped"

    if bunker_code:
        try:
            result = get_schedule_by_port(bunker_code)
            return {"mode": "port", **result, "fallback_reason": points_error}
        except ExternalAPIError as exc:
            port_error = str(exc)
    else:
        port_error = "Bunkering port UNLOCODE not mapped"

    return {
        "available": False,
        "mode": "none",
        "error": port_error,
        "fallback_reason": vessel_error,
    }


def get_gemini_explanation(payload: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"available": False, "error": "GEMINI_API_KEY is not configured"}

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    system = """
You are the explainability layer inside a maritime bunkering decision-support platform.
You are NOT the decision maker.
Only use values supplied in the structured payload. Never invent values.
Do not make the final operational decision. Distinguish live API signals from prototype assumptions.
Return valid JSON with exactly these keys:
what_changed, cost_drivers, fuel_drivers, risk_drivers, sustainability_tradeoffs, planner_considerations.
Each value may be a short string or an array of short strings.
"""

    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{
            "role": "user",
            "parts": [{"text": "Explain this structured data:\n" + json.dumps(payload, ensure_ascii=False, indent=2)}],
        }],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }

    data = _request(
        "POST",
        url,
        params={"key": key},
        headers={"Content-Type": "application/json"},
        json=body,
    )

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ExternalAPIError("Gemini returned an unexpected response format") from exc

    return {"available": True, "analysis": parsed, "source": "Gemini"}