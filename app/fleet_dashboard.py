"""Fleet dashboard data loading, calculations, filtering, and handoff contract."""

import json
from datetime import datetime, timezone
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "vessels.json"


def load_vessels(data_file=DATA_FILE):
    """Load prototype vessel records from JSON."""
    with Path(data_file).open(encoding="utf-8") as file:
        return json.load(file)


def current_fuel_percentage(vessel):
    capacity = vessel["tank_capacity_tonnes"]
    return round(vessel["current_fuel_tonnes"] / capacity * 100, 1) if capacity else 0.0


def reserve_margin(vessel):
    return round(vessel["projected_fuel_on_arrival_tonnes"] - vessel["minimum_reserve_tonnes"], 1)


def projected_bunker_cost(vessel):
    return round(vessel["projected_bunker_quantity_tonnes"] * vessel["bunker_price_per_tonne"], 2)


def is_low_fuel_reserve(vessel):
    """Flag arrival fuel within 20% of the required minimum reserve."""
    return reserve_margin(vessel) <= vessel["minimum_reserve_tonnes"] * 0.2


def requires_upcoming_bunkering(vessel):
    """Prototype flag based on need before arrival and declared bunker quantity."""
    return vessel["projected_bunker_quantity_tonnes"] > 0 and (
        is_low_fuel_reserve(vessel) or current_fuel_percentage(vessel) < 35
    )


def attention_status(vessel):
    """Return planner attention level; this is not an operational decision."""
    margin = reserve_margin(vessel)
    cost = projected_bunker_cost(vessel)
    risk = vessel["risk_level"]
    if margin <= vessel["minimum_reserve_tonnes"] * 0.2 or risk == "High" or cost >= 900_000:
        return "Review"
    if margin <= vessel["minimum_reserve_tonnes"] * 0.6 or risk == "Medium" or cost >= 600_000:
        return "Monitor"
    return "Normal"


def attention_reasons(vessel):
    """Explain the strongest deterministic signals behind the attention status."""
    reasons = []
    if is_low_fuel_reserve(vessel):
        reasons.append("Arrival fuel close to minimum reserve")
    if vessel["risk_level"] == "High":
        reasons.append("High operational risk")
    elif vessel["risk_level"] == "Medium":
        reasons.append("Moderate operational risk")
    if projected_bunker_cost(vessel) >= 900_000:
        reasons.append("High projected bunker spend")
    elif reserve_margin(vessel) <= vessel["minimum_reserve_tonnes"] * 0.6:
        reasons.append("Reserve margin narrowing")
    return reasons or ["No immediate attention signals"]


def enrich_vessel(vessel):
    enriched = dict(vessel)
    enriched.update(
        current_fuel_percentage=current_fuel_percentage(vessel),
        reserve_margin_tonnes=reserve_margin(vessel),
        projected_bunker_cost=projected_bunker_cost(vessel),
        low_fuel_reserve=is_low_fuel_reserve(vessel),
        upcoming_bunkering=requires_upcoming_bunkering(vessel),
        status=attention_status(vessel),
        attention_reasons=attention_reasons(vessel),
    )
    return enriched


def filter_vessels(vessels, filters):
    """Apply case-insensitive dashboard filters to enriched records."""
    result = vessels
    search = filters.get("search", "").strip().casefold()
    if search:
        result = [v for v in result if search in v["vessel_name"].casefold()]
    for key in ("fuel_type", "status", "risk_level", "next_bunkering_port", "route"):
        value = filters.get(key, "").strip().casefold()
        if value:
            if key == "route":
                result = [v for v in result if value == f'{v["origin"]} → {v["destination"]}'.casefold()]
            else:
                result = [v for v in result if str(v[key]).casefold() == value]
    return result


def fleet_rollups(vessels):
    return {
        "monitored_vessels": len(vessels),
        "upcoming_bunkering": sum(v["upcoming_bunkering"] for v in vessels),
        "projected_bunker_spend": sum(v["projected_bunker_cost"] for v in vessels),
        "low_fuel_reserve": sum(v["low_fuel_reserve"] for v in vessels),
        "requiring_review": sum(v["status"] == "Review" for v in vessels),
        "estimated_emissions": sum(v["estimated_emissions_tco2e"] for v in vessels),
    }


def build_voyage_context(vessel):
    """Stable input contract for Person 2's future scenario module."""
    v = enrich_vessel(vessel)
    return {
        "vessel": {
            "vessel_id": v["vessel_id"], "vessel_name": v["vessel_name"],
            "vessel_class": v["vessel_class"], "vessel_type": v["vessel_type"],
            "nominal_teu": v["nominal_teu"],
            "dwt": v["dwt"], "year_built": v["year_built"],
            "length_metres": v["length_metres"], "beam_metres": v["beam_metres"],
            "fuel_type": v["fuel_type"], "lng_dual_fuel": v["lng_dual_fuel"],
            "official_source_url": v["official_source_url"],
            "official_source_label": v["official_source_label"],
        },
        "voyage": {
            "origin": v["origin"], "destination": v["destination"],
            "departure_date": v["departure_date"], "eta": v["eta"],
            "estimated_consumption_tpd": v["estimated_consumption_tpd"],
            "published_service": v["published_service"],
        },
        "fuel_status": {
            "tank_capacity_tonnes": v["tank_capacity_tonnes"],
            "current_fuel_tonnes": v["current_fuel_tonnes"],
            "current_fuel_percentage": v["current_fuel_percentage"],
            "minimum_reserve_tonnes": v["minimum_reserve_tonnes"],
            "projected_fuel_on_arrival_tonnes": v["projected_fuel_on_arrival_tonnes"],
            "reserve_margin_tonnes": v["reserve_margin_tonnes"],
            "low_fuel_reserve": v["low_fuel_reserve"],
        },
        "bunkering": {
            "next_port": v["next_bunkering_port"],
            "price_per_tonne": v["bunker_price_per_tonne"],
            "projected_quantity_tonnes": v["projected_bunker_quantity_tonnes"],
            "projected_cost": v["projected_bunker_cost"],
            "upcoming_requirement": v["upcoming_bunkering"],
        },
        "sustainability": {
            "indicator": v["sustainability_indicator"],
            "estimated_emissions_tco2e": v["estimated_emissions_tco2e"],
        },
        "base_risk": {"level": v["risk_level"], "attention_status": v["status"]},
    }


def find_vessel(vessel_id):
    return next((v for v in load_vessels() if v["vessel_id"] == vessel_id), None)


def get_fleet_dashboard_context(filters=None):
    filters = filters or {}
    all_vessels = [enrich_vessel(v) for v in load_vessels()]
    vessels = filter_vessels(all_vessels, filters)
    priority = {"Review": 0, "Monitor": 1, "Normal": 2}
    risk_priority = {"High": 0, "Medium": 1, "Low": 2}
    vessels.sort(key=lambda v: (priority[v["status"]], risk_priority[v["risk_level"]], v["reserve_margin_tonnes"]))
    return {
        "vessels": vessels,
        "kpis": fleet_rollups(vessels),
        "filters": filters,
        "filter_options": {
            "fuel_types": sorted({v["fuel_type"] for v in all_vessels}),
            "statuses": ["Normal", "Monitor", "Review"],
            "risks": ["Low", "Medium", "High"],
            "ports": sorted({v["next_bunkering_port"] for v in all_vessels}),
            "routes": sorted({f'{v["origin"]} → {v["destination"]}' for v in all_vessels}),
        },
        "data_timestamp": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
    }
