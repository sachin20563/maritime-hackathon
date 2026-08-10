from flask import (
    Flask,
    jsonify,
    render_template,
    abort,
    request,
)

from dotenv import load_dotenv

from config import Config


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# CREATE APPLICATION
# ============================================================

def create_app(config_class=Config):
    """
    Create and configure the VECXUS Flask application.
    """

    app = Flask(__name__)

    app.config.from_object(
        config_class
    )


    # ========================================================
    # IMPORT BLUEPRINTS
    # ========================================================

    from app.scenario_routes import (
        scenario_bp
    )


    # ========================================================
    # REGISTER BLUEPRINTS
    # ========================================================

    app.register_blueprint(
        scenario_bp
    )


    # ========================================================
    # HOME
    # ========================================================

    @app.get("/")
    def index():

        return render_template(
            "home/home.html"
        )


    # ========================================================
    # FLEET DASHBOARD
    # ========================================================

    @app.get("/fleet-dashboard")
    def fleet_dashboard():

        from app.fleet_dashboard import (
            get_fleet_dashboard_context
        )

        filters = {
            key: request.args.get(
                key,
                ""
            )
            for key in (
                "search",
                "fuel_type",
                "status",
                "risk_level",
                "next_bunkering_port",
                "route",
            )
        }

        context = get_fleet_dashboard_context(
            filters
        )

        return render_template(
            "fleet_dashboard/fleet_dashboard.html",
            **context
        )


    # ========================================================
    # VESSEL DETAIL
    # ========================================================

    @app.get(
        "/vessels/<vessel_id>"
    )
    def vessel_detail(vessel_id):

        from app.fleet_dashboard import (
            find_vessel,
            build_assessment_context,
        )

        vessel = find_vessel(
            vessel_id
        )

        if vessel is None:
            abort(404)

        assessment = build_assessment_context(
            vessel,
            request.args
        )

        return render_template(
            "fleet_dashboard/vessel_detail.html",
            **assessment
        )


    # ========================================================
    # VOYAGE CONTEXT API
    # ========================================================

    @app.get(
        "/api/vessels/<vessel_id>/voyage-context"
    )
    def voyage_context_api(vessel_id):

        from app.fleet_dashboard import (
            find_vessel,
            build_voyage_context,
        )

        vessel = find_vessel(
            vessel_id
        )

        if vessel is None:
            abort(404)

        return jsonify(
            build_voyage_context(
                vessel
            )
        )


    # ========================================================
    # EXAMPLE API
    # ========================================================

    @app.get("/api/example")
    def example_api():

        return jsonify({

            "message":
                "Maritime Decision Support API",

            "data": {

                "port":
                    "Singapore",

                "fuel_price":
                    625.50,

            },

        })


    # ========================================================
    # HEALTH CHECK
    # ========================================================

    @app.get("/health")
    def health():

        return jsonify({
            "status": "ok"
        })


    return app