"""Python logic for the workspace page.

Keep calculations and data preparation here instead of putting them directly in
the HTML template or route function. This example data can later be replaced by
database queries, API calls, or an optimisation model.
"""


def get_workspace_context():
    """Return the values needed to render the workspace page."""
    return {
        "page_title": "Plan a bunkering strategy",
        "example_vessels": [
            "MV Example",
            "MV Vector",
            "MV Nexus",
        ],
        "supported_inputs": [
            "Vessel fuel consumption",
            "Bunker fuel prices",
            "Voyage route and schedule",
        ],
    }
