from flask import Flask, jsonify, render_template

from config import Config
from app.workspace import get_workspace_context


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
