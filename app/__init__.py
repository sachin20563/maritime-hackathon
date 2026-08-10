from flask import Flask, jsonify, render_template, abort, request
from dotenv import load_dotenv
from config import Config
from app.workspace import get_workspace_context

load_dotenv()  # Load environment variables from .env file

from app.scenario_routes import scenario_bp
from app.fleet_dashboard import (
    build_assessment_context,
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
    @app.get("/workspace")
    def workspace():
        context = get_workspace_context()
        return render_template("workspace/workspace.html", **context)

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
        assessment = build_assessment_context(vessel, request.args)
        return render_template("fleet_dashboard/vessel_detail.html", **assessment)

    @app.get("/api/vessels/<vessel_id>/voyage-context")
    def voyage_context_api(vessel_id):
        vessel = find_vessel(vessel_id)
        if vessel is None:
            abort(404)
        return jsonify(build_voyage_context(vessel))

    @app.get("/api/example")
    def example_api():
        return jsonify({
            "message": "Example Vecxus API response",
            "data": {"port": "Singapore", "fuel_price": 625.50},
        })

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
