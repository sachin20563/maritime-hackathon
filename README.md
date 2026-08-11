# Vecxus

A lightweight Flask and Bootstrap starter for Vector Nexus: a data-driven vessel bunkering
decision support tool. It intentionally contains no optimisation or data model so
team members can build those features independently.

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
flask --app run.py run --debug
```

Open `http://127.0.0.1:5000`.

## Structure

```text
app/
├── __init__.py            # Application factory and routes
├── fleet_dashboard.py     # Fleet dashboard data and Python logic
├── static/css|js/         # Front-end assets
└── templates/
    ├── base.html          # Shared page shell
    ├── home/
    │   └── home.html      # Homepage
    ├── fleet_dashboard/
    │   ├── fleet_dashboard.html # Fleet overview page
    │   └── vessel_detail.html   # Vessel drill-down page
    └── partials/          # Navbar and footer
config.py                  # Environment-aware configuration
run.py                     # Local entry point
```

Suggested feature branches or blueprints include fuel market data, vessel and
voyage modelling, bunkering optimisation, and scenario testing. Add each feature
as its own blueprint under `app/`, then register it in `create_app()`.

## Route examples

Routes are kept directly in `app/__init__.py` while the prototype is small. The
starter includes:

- `/` — homepage rendered from a Jinja template
- `/fleet-dashboard` — fleet and bunkering overview dashboard
- `/api/example` — example JSON API route
- `/scenarios` — vessel selection for Voyage Scenario Analysis
- `/vessels/<vessel_id>/scenario` — controlled/uncontrolled scenario workspace
- `POST /api/vessels/<vessel_id>/scenario` — deterministic initial-versus-simulated comparison

Scenario route distance, alert overlays, cargo sensitivity and the per-day
operational cost are transparent prototype assumptions, not navigational or live
PIL data. The scenario engine deep-copies the stable voyage-context object and
does not modify `data/vessels.json`. Gemini may explain returned structured
values, while a deterministic explanation remains available without API keys.
- `/health` — service health check

For now, add a decorated route in `create_app()` and give each page its own
template folder. Keep shared elements such as the navbar and footer in `partials/`.
If the application grows substantially, routes can later be split into blueprints.
