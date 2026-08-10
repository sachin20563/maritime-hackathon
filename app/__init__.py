from flask import Flask, abort, jsonify, render_template, request

from config import Config
from app.fleet_dashboard import (
    build_voyage_context,
    find_vessel,
    get_fleet_dashboard_context,
)

def create_app(config_class=Config):
    """Create and configure the Vecxus Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Page route: renders templates/home/home.html.
    @app.get("/")
    def index():
        return render_template("home/home.html")

    # Second page route: a starting point for the future decision dashboard.
    @app.get("/fleet-dashboard")
    def fleet_dashboard():
        filters = {
            key: request.args.get(key, "")
            for key in (
                "search",
                "fuel_type",
                "status",
                "risk_level",
                "next_bunkering_port",
                "route",
            )
        }
        context = get_fleet_dashboard_context(filters)
        return render_template("fleet_dashboard/fleet_dashboard.html", **context)

    @app.get("/vessels/<vessel_id>")
    def vessel_detail(vessel_id):
        vessel = find_vessel(vessel_id)
        if vessel is None:
            abort(404)
        return render_template(
            "fleet_dashboard/vessel_detail.html",
            voyage_context=build_voyage_context(vessel),
        )

    @app.get("/api/vessels/<vessel_id>/voyage-context")
    def voyage_context_api(vessel_id):
        vessel = find_vessel(vessel_id)
        if vessel is None:
            abort(404)
        return jsonify(build_voyage_context(vessel))

    # Example JSON route for JavaScript, models, or external data consumers.
    @app.get("/api/example")
    def example_api():
        return jsonify(
            {
                "message": "Example Vecxus API response",
                "data": {"port": "Singapore", "fuel_price": 625.50},
            }
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
