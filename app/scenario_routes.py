"""
Flask routes for:
1. Voyage Scenario & Dynamic Risk Analysis
2. AI-Assisted Decision Support & Portfolio Insights

This file acts as the API orchestration layer.

Important:
- API keys stay on the backend.
- External APIs are never called directly from browser JavaScript.
- External API failures are isolated so one failed service does not break
  the entire scenario page.
- Python/scenario_engine.py remains responsible for deterministic calculations.
- Gemini is used only as an explainability layer.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from flask import Blueprint, jsonify, render_template, request

from app.fleet_dashboard import find_vessel
from app.scenario_engine import (
    PORT_COORDINATES,
    build_portfolio_snapshot,
    get_port_unlocode,
    run_scenario,
)
from app.services.external_apis import (
    ExternalAPIError,
    get_gemini_explanation,
    get_news,
    get_oil_price,
    get_schedule_context,
    get_weather,
    weather_severity,
)


scenario_bp = Blueprint("scenario", __name__)


# ============================================================
# HELPERS
# ============================================================

def _unavailable(message: str, source: str) -> dict[str, Any]:
    """
    Standard response shape for an unavailable external service.
    """
    return {
        "available": False,
        "source": source,
        "error": message,
    }


def _call_safely(function, *args, source: str, **kwargs) -> dict[str, Any]:
    """
    Execute an external API function without allowing one failed API
    to break the complete dashboard.
    """
    try:
        result = function(*args, **kwargs)

        if result is None:
            return _unavailable(
                "API returned no data.",
                source,
            )

        if isinstance(result, dict):
            return result

        return {
            "available": True,
            "source": source,
            "data": result,
        }

    except ExternalAPIError as exc:
        return _unavailable(str(exc), source)

    except Exception as exc:
        return _unavailable(
            f"{source} request failed: {exc}",
            source,
        )


def _get_vessel(vessel_id: str):
    """
    Centralised vessel lookup.
    """
    vessel = find_vessel(vessel_id)

    if vessel is None:
        return None

    return vessel


# ============================================================
# LIVE API ORCHESTRATION
# ============================================================

def _build_live_intelligence(vessel: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch all live intelligence required by the scenario module.

    APIs:
    - OpenWeather
    - OilPriceAPI
    - NewsAPI
    - Schedule API

    Calls are executed concurrently so the page does not wait
    sequentially for four external services.
    """

    origin = vessel.get("origin", "")
    destination = vessel.get("destination", "")
    bunker_port = vessel.get("next_bunkering_port", "")

    # --------------------------------------------------------
    # Weather coordinates
    # --------------------------------------------------------

    coordinates = PORT_COORDINATES.get(bunker_port)

    # --------------------------------------------------------
    # Schedule UN/LOCODEs
    # --------------------------------------------------------

    origin_code = get_port_unlocode(origin)
    destination_code = get_port_unlocode(destination)
    bunker_code = get_port_unlocode(bunker_port)

    # --------------------------------------------------------
    # News query
    # --------------------------------------------------------

    news_query = (
        f'"{origin}" OR '
        f'"{destination}" OR '
        f'"{bunker_port}" '
        f'shipping maritime port disruption congestion delay'
    )

    results: dict[str, Any] = {}

    def weather_task():
        if not coordinates:
            return _unavailable(
                f"No coordinates configured for {bunker_port}.",
                "OpenWeather",
            )

        return _call_safely(
            get_weather,
            coordinates["lat"],
            coordinates["lng"],
            source="OpenWeather",
        )

    def oil_task():
        return _call_safely(
            get_oil_price,
            source="OilPriceAPI",
        )

    def news_task():
        return _call_safely(
            get_news,
            news_query,
            source="NewsAPI",
        )

    def schedule_task():
        try:
            return get_schedule_context(
                vessel,
                origin_code,
                destination_code,
                bunker_code,
            )
        except ExternalAPIError as exc:
            return _unavailable(
                str(exc),
                "Schedule API",
            )
        except Exception as exc:
            return _unavailable(
                f"Schedule API request failed: {exc}",
                "Schedule API",
            )

    tasks = {
        "weather": weather_task,
        "oil": oil_task,
        "news": news_task,
        "schedule": schedule_task,
    }

    # --------------------------------------------------------
    # Parallel external API calls
    # --------------------------------------------------------

    with ThreadPoolExecutor(max_workers=4) as executor:

        future_map = {
            executor.submit(task): name
            for name, task in tasks.items()
        }

        for future in as_completed(future_map):

            name = future_map[future]

            try:
                results[name] = future.result()

            except Exception as exc:
                results[name] = _unavailable(
                    f"{name} service failed: {exc}",
                    name,
                )

    # --------------------------------------------------------
    # Weather severity
    # --------------------------------------------------------

    weather = results.get("weather", {})

    try:
        weather_level = weather_severity(weather)
    except Exception as exc:
        weather_level = {
            "level": "Unknown",
            "score": 0,
            "reasons": [str(exc)],
        }

    # --------------------------------------------------------
    # News disruption signal
    # --------------------------------------------------------

    news = results.get("news", {})

    disruption_signal = _calculate_news_disruption_signal(news)

    # --------------------------------------------------------
    # Schedule signal
    # --------------------------------------------------------

    schedule = results.get("schedule", {})

    schedule_signal = _calculate_schedule_signal(schedule)

    # --------------------------------------------------------
    # Oil signal
    # --------------------------------------------------------

    oil = results.get("oil", {})

    oil_signal = _calculate_oil_signal(oil)

    return {
        "weather": weather,
        "weather_severity": weather_level,

        "oil": oil,
        "oil_signal": oil_signal,

        "news": news,
        "disruption_signal": disruption_signal,

        "schedule": schedule,
        "schedule_signal": schedule_signal,

        "location": {
            "port": bunker_port,
            "coordinates": coordinates,
            "origin": origin,
            "destination": destination,
        },

        "api_status": {
            "weather": bool(weather.get("available")),
            "oil": bool(oil.get("available")),
            "news": bool(news.get("available")),
            "schedule": bool(schedule.get("available")),
        },
    }


def _calculate_news_disruption_signal(news: dict[str, Any]) -> dict[str, Any]:
    """
    Convert NewsAPI results into a simple transparent disruption signal.

    This is NOT an AI-generated risk score.
    It is only a lightweight keyword signal used to support the planner.
    """

    if not news.get("available"):
        return {
            "level": "Unknown",
            "score": 0,
            "reasons": [
                "Live news intelligence unavailable."
            ],
        }

    articles = news.get("articles") or []

    keywords = {
        "closure": 3,
        "closed": 3,
        "strike": 3,
        "war": 3,
        "conflict": 3,
        "attack": 3,
        "blockade": 3,
        "disruption": 2,
        "disrupted": 2,
        "congestion": 2,
        "delay": 2,
        "delays": 2,
        "shortage": 2,
        "port": 1,
        "shipping": 1,
    }

    score = 0
    reasons = []

    for article in articles:

        text = " ".join(
            str(article.get(field) or "")
            for field in ("title", "description")
        ).lower()

        article_score = 0
        article_keywords = []

        for keyword, weight in keywords.items():

            if keyword in text:
                article_score += weight
                article_keywords.append(keyword)

        if article_score > 0:
            score += min(article_score, 5)

            if article.get("title"):
                reasons.append(
                    f"{article['title']}"
                )

    score = min(score, 10)

    if score >= 7:
        level = "High"
    elif score >= 3:
        level = "Medium"
    else:
        level = "Low"

    return {
        "level": level,
        "score": score,
        "article_count": len(articles),
        "reasons": reasons[:5],
    }


def _calculate_schedule_signal(schedule: dict[str, Any]) -> dict[str, Any]:
    """
    Convert schedule information into a simple planner-facing signal.
    """

    if not schedule.get("available"):
        return {
            "level": "Unknown",
            "score": 0,
            "options": 0,
            "reasons": [
                schedule.get(
                    "error",
                    "Schedule information unavailable.",
                )
            ],
        }

    data = schedule.get("data")

    if isinstance(data, dict):
        schedules = data.get("schedules") or []
    elif isinstance(data, list):
        schedules = data
    else:
        schedules = []

    count = len(schedules)

    if count == 0:
        return {
            "level": "Constrained",
            "score": 3,
            "options": 0,
            "reasons": [
                "No schedule options were returned."
            ],
        }

    if count <= 2:
        level = "Limited"
        score = 2
    else:
        level = "Available"
        score = 0

    return {
        "level": level,
        "score": score,
        "options": count,
        "reasons": [],
    }


def _calculate_oil_signal(oil: dict[str, Any]) -> dict[str, Any]:
    """
    Normalise the oil response into a frontend-friendly structure.
    """

    if not oil.get("available"):
        return {
            "level": "Unknown",
            "score": 0,
            "price": None,
        }

    price = oil.get("price")

    try:
        price = float(price)
    except (TypeError, ValueError):
        price = None

    return {
        "level": "Live",
        "score": 0,
        "price": price,
        "currency": oil.get("currency", "USD"),
        "unit": oil.get("unit", "barrel"),
        "updated_at": (
            oil.get("created_at")
            or oil.get("timestamp")
        ),
    }


# ============================================================
# SCENARIO PAGE
# ============================================================

@scenario_bp.get("/vessels/<vessel_id>/scenario")
def scenario_page(vessel_id):
    """
    Render the scenario analysis page for a specific vessel.
    """

    vessel = _get_vessel(vessel_id)

    if vessel is None:
        return "Vessel not found", 404

    return render_template(
        "scenario_analysis/scenario.html",
        vessel=vessel,
    )


# ============================================================
# SCENARIO CALCULATION API
# ============================================================

@scenario_bp.post("/api/vessels/<vessel_id>/scenario")
def scenario_api(vessel_id):
    """
    Run the deterministic scenario engine.

    The frontend sends scenario assumptions.

    Live API data is fetched separately and returned alongside
    the calculation so the planner can see:

    - weather
    - oil market
    - disruption signals
    - schedule availability

    The scenario engine remains deterministic and does not
    allow Gemini to perform the actual arithmetic.
    """

    vessel = _get_vessel(vessel_id)

    if vessel is None:
        return jsonify({
            "available": False,
            "error": "Vessel not found",
        }), 404

    data = request.get_json(silent=True) or {}

    # --------------------------------------------------------
    # Validate scenario inputs
    # --------------------------------------------------------

    allowed_weather = {
        "None",
        "Mild",
        "Moderate",
        "Severe",
    }

    allowed_congestion = {
        "None",
        "Low",
        "Medium",
        "High",
    }

    allowed_geopolitical = {
        "None",
        "Medium",
        "High",
    }

    allowed_port_status = {
        "Open",
        "Reduced",
        "Closed",
    }

    allowed_fuel_supply = {
        "Available",
        "Constrained",
    }

    # Don't allow malformed input to silently create
    # unpredictable calculations.

    if data.get("weather") not in allowed_weather:
        data["weather"] = "None"

    if data.get("congestion") not in allowed_congestion:
        data["congestion"] = "None"

    if data.get("geopolitical") not in allowed_geopolitical:
        data["geopolitical"] = "None"

    if data.get("port_status") not in allowed_port_status:
        data["port_status"] = "Open"

    if data.get("fuel_supply") not in allowed_fuel_supply:
        data["fuel_supply"] = "Available"

    try:
        # ----------------------------------------------------
        # 1. Run deterministic scenario calculation
        # ----------------------------------------------------

        result = run_scenario(
            vessel_id,
            data,
        )

        # ----------------------------------------------------
        # 2. Fetch current live intelligence
        # ----------------------------------------------------

        live = _build_live_intelligence(vessel)

        # ----------------------------------------------------
        # 3. Attach live signals to scenario result
        # ----------------------------------------------------

        result["live_intelligence"] = live

        result["decision_support"] = {
            "message": (
                "Live external signals are provided as decision "
                "support. They do not automatically modify the "
                "voyage plan."
            ),
            "planner_decision_required": True,
        }

        return jsonify(result)

    except KeyError:
        return jsonify({
            "available": False,
            "error": "Unable to find vessel scenario data.",
        }), 404

    except Exception as exc:
        return jsonify({
            "available": False,
            "error": f"Scenario calculation failed: {exc}",
        }), 500


# ============================================================
# LIVE INTELLIGENCE API
# ============================================================

@scenario_bp.get("/api/vessels/<vessel_id>/live-intelligence")
def live_intelligence(vessel_id):
    """
    Return all live intelligence for a vessel.

    Used when the scenario page first loads and when the user
    refreshes live conditions.
    """

    vessel = _get_vessel(vessel_id)

    if vessel is None:
        return jsonify({
            "available": False,
            "error": "Vessel not found",
        }), 404

    try:
        live = _build_live_intelligence(vessel)

        return jsonify({
            "available": True,
            "vessel": {
                "vessel_id": vessel.get("vessel_id"),
                "vessel_name": vessel.get("vessel_name"),
                "origin": vessel.get("origin"),
                "destination": vessel.get("destination"),
                "next_bunkering_port": vessel.get(
                    "next_bunkering_port"
                ),
            },
            **live,
        })

    except Exception as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 500


# ============================================================
# GEMINI — VESSEL SCENARIO EXPLANATION
# ============================================================

@scenario_bp.post("/api/vessels/<vessel_id>/ai-explanation")
def ai_explanation(vessel_id):
    """
    Ask Gemini to explain the scenario trade-offs.

    Gemini receives structured calculations and API signals.
    It does NOT calculate the scenario or make the operational
    decision.
    """

    vessel = _get_vessel(vessel_id)

    if vessel is None:
        return jsonify({
            "available": False,
            "error": "Vessel not found",
        }), 404

    data = request.get_json(silent=True) or {}

    # --------------------------------------------------------
    # Protect the model from receiving an unnecessarily huge
    # payload.
    # --------------------------------------------------------

    payload = {
        "analysis_type": "voyage_scenario",
        "vessel": data.get("vessel"),
        "scenario_inputs": data.get("scenario_inputs"),
        "baseline": data.get("baseline"),
        "scenario": data.get("scenario"),
        "metrics": data.get("metrics"),
        "risk": data.get("risk"),
        "live_intelligence": data.get(
            "live_intelligence"
        ),
    }

    try:
        result = get_gemini_explanation(payload)

        return jsonify(result)

    except ExternalAPIError as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 503

    except Exception as exc:
        return jsonify({
            "available": False,
            "error": f"Gemini request failed: {exc}",
        }), 503


# ============================================================
# AI PORTFOLIO PAGE
# ============================================================

@scenario_bp.get("/ai-insights")
def portfolio_page():
    """
    Fleet-wide AI insights page.
    """

    return render_template(
        "ai_insights/portfolio.html"
    )


# ============================================================
# PORTFOLIO DATA API
# ============================================================

@scenario_bp.get("/api/portfolio")
def portfolio_api():
    """
    Return structured fleet-wide information for the
    AI-assisted portfolio layer.
    """

    try:
        snapshot = build_portfolio_snapshot()

        return jsonify({
            "available": True,
            **snapshot,
        })

    except Exception as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 500


# ============================================================
# AI PORTFOLIO EXPLANATION
# ============================================================

@scenario_bp.post("/api/portfolio/ai-explanation")
def portfolio_ai_explanation():
    """
    Send structured fleet-level information to Gemini.
    """

    data = request.get_json(silent=True) or {}

    payload = {
        "analysis_type": "fleet_portfolio",
        "portfolio": data,
    }

    try:
        result = get_gemini_explanation(payload)

        return jsonify(result)

    except ExternalAPIError as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 503

    except Exception as exc:
        return jsonify({
            "available": False,
            "error": f"Gemini portfolio request failed: {exc}",
        }), 503