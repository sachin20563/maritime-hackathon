"""
Flask routes for Voyage Scenario Analysis
and AI-Assisted Decision Support.
"""

from flask import Blueprint, jsonify, render_template, request

from app.scenario_engine import (
    build_portfolio_snapshot,
    run_scenario,
    scenario_page_context,
)

from app.services.external_apis import (
    ExternalAPIError,
    get_gemini_explanation,
    get_news,
    get_oil_price,
)

from app.fleet_dashboard import (
    find_vessel,
    get_fleet_dashboard_context,
)


scenario_bp = Blueprint("scenario", __name__)


# ============================================================
# VOYAGE SCENARIO LANDING PAGE
# ============================================================

@scenario_bp.get("/scenarios")
def scenarios_page():
    """
    Landing page for Voyage Scenario Analysis.

    Users select a vessel here before opening
    the vessel-specific scenario workspace.
    """

    try:
        context = get_fleet_dashboard_context({})
    except Exception:
        context = {}

    # Most fleet dashboard implementations expose the vessel
    # collection as "vessels".
    vessels = context.get("vessels", [])

    # Defensive fallbacks in case the existing dashboard
    # uses another context key.
    if not vessels:
        vessels = context.get("fleet", [])

    if not vessels:
        vessels = context.get("fleet_vessels", [])

    return render_template(
        "scenario_analysis/scenarios.html",
        vessels=vessels,
    )


# ============================================================
# VESSEL SCENARIO WORKSPACE
# ============================================================

@scenario_bp.get("/vessels/<vessel_id>/scenario")
def scenario_page(vessel_id):
    """
    Opens the scenario workspace for a specific vessel.
    """

    vessel = find_vessel(vessel_id)

    if vessel is None:
        return "Vessel not found", 404

    return render_template(
        "scenario_analysis/scenario.html",
        vessel=vessel,
        **scenario_page_context(vessel),
    )


# ============================================================
# SCENARIO CALCULATION API
# ============================================================

@scenario_bp.post("/api/vessels/<vessel_id>/scenario")
def scenario_api(vessel_id):
    """
    Runs the scenario engine for a vessel.
    """

    vessel = find_vessel(vessel_id)

    if vessel is None:
        return jsonify({
            "error": "Vessel not found"
        }), 404

    data = request.get_json(silent=True) or {}

    try:
        result = run_scenario(
            vessel_id,
            data
        )

        return jsonify(result)

    except Exception as exc:
        return jsonify({
            "error": str(exc)
        }), 400


# ============================================================
# LIVE INTELLIGENCE
# ============================================================

@scenario_bp.get("/api/vessels/<vessel_id>/live-intelligence")
def live_intelligence(vessel_id):
    """
    Collects current external intelligence:

    - OpenWeather
    - OilPriceAPI
    - Schedule API
    - NewsAPI

    The information is returned to the frontend and does
    NOT automatically change the voyage plan.
    """

    vessel = find_vessel(vessel_id)

    if vessel is None:
        return jsonify({
            "error": "Vessel not found"
        }), 404

    # --------------------------------------------------------
    # WEATHER (explicit prototype assumption for the hackathon workspace)
    # --------------------------------------------------------

    weather = {
        "available": True,
        "description": "Overcast maritime conditions",
        "wind_speed_knots": 14,
        "mocked": True,
        "source": "Prototype assumption",
    }
    weather_level = {
        "level": "Moderate",
        "score": 2,
        "reasons": ["Simulated overcast conditions", "Simulated 14-knot winds"],
        "mocked": True,
    }


    # --------------------------------------------------------
    # OIL PRICE
    # --------------------------------------------------------

    oil = {
        "available": False,
        "error": "Oil price data unavailable",
    }

    try:
        oil = get_oil_price()

    except ExternalAPIError as exc:
        oil = {
            "available": False,
            "error": str(exc),
        }

    except Exception as exc:
        oil = {
            "available": False,
            "error": str(exc),
        }


    # --------------------------------------------------------
    # NEWS / DISRUPTION SIGNALS
    # --------------------------------------------------------

    news = {
        "available": False,
        "articles": [],
        "error": "News data unavailable",
    }

    route_terms = [
        vessel.get("origin", ""),
        vessel.get("destination", ""),
        vessel.get("next_bunkering_port", ""),
        "Red Sea",
    ]
    locations = " OR ".join(f'"{term}"' for term in route_terms if term)
    query = (
        f"({locations}) AND "
        "(shipping OR maritime OR vessel OR port OR container) AND "
        "(disruption OR congestion OR closure OR strike OR sanctions OR conflict OR "
        "attack OR piracy OR storm OR typhoon OR delay OR diversion OR shortage)"
    )

    try:
        news = get_news(query, route_terms=route_terms)

    except ExternalAPIError as exc:
        news = {
            "available": False,
            "articles": [],
            "error": str(exc),
        }

    except Exception as exc:
        news = {
            "available": False,
            "articles": [],
            "error": str(exc),
        }


    # --------------------------------------------------------
    # RETURN EVERYTHING
    # --------------------------------------------------------

    return jsonify({
        "weather": weather,
        "weather_severity": weather_level,
        "oil": oil,
        "news": news,
    })


# ============================================================
# GEMINI VESSEL EXPLANATION
# ============================================================

@scenario_bp.post("/api/vessels/<vessel_id>/ai-explanation")
def ai_explanation(vessel_id):
    """
    Uses Gemini to explain scenario differences.

    Gemini explains structured results produced by the
    scenario engine. It does not perform the underlying
    optimisation itself.
    """

    vessel = find_vessel(vessel_id)

    if vessel is None:
        return jsonify({
            "error": "Vessel not found"
        }), 404

    data = request.get_json(silent=True) or {}

    try:
        result = get_gemini_explanation(data)

        return jsonify(result)

    except ExternalAPIError as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 503

    except Exception as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 503


# ============================================================
# PORTFOLIO GEMINI EXPLANATION
# ============================================================

@scenario_bp.post("/api/portfolio/ai-explanation")
def portfolio_ai_explanation():
    """
    Uses Gemini to explain fleet-level portfolio insights.
    """

    data = request.get_json(silent=True) or {}

    try:
        result = get_gemini_explanation({
            "analysis_type": "fleet_portfolio",
            "portfolio": data,
        })

        return jsonify(result)

    except ExternalAPIError as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 503

    except Exception as exc:
        return jsonify({
            "available": False,
            "error": str(exc),
        }), 503


# ============================================================
# AI INSIGHTS PAGE
# ============================================================

@scenario_bp.get("/ai-insights")
def portfolio_page():
    return render_template(
        "ai_insights/portfolio.html"
    )


# ============================================================
# PORTFOLIO API
# ============================================================

@scenario_bp.get("/api/portfolio")
def portfolio_api():
    try:
        return jsonify(
            build_portfolio_snapshot()
        )

    except Exception as exc:
        return jsonify({
            "error": str(exc)
        }), 500
