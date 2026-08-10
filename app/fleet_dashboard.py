"""Fleet dashboard data loading, calculations, filtering, and handoff contract."""

import json
from datetime import datetime, timezone
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "vessels.json"
PORT_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "ports.json"

# IMO MEPC.395(82), Appendix 4 tank-to-wake CO2 conversion factors (tCO2/t fuel).
# Biofuel uses a deliberately conservative prototype factor; IMO MEPC.1/Circ.905
# states that a supplier-supported factor should be used for actual reporting.
EMISSION_FACTORS = {"VLSFO": 3.151, "LNG": 2.750, "Biofuel Blend": 2.050}
LOWER_CALORIFIC_VALUES_MJ_KG = {"VLSFO": 41.2, "LNG": 48.0, "Biofuel Blend": 40.5}
PROTOTYPE_FUEL_PRICES = {"VLSFO": 620.0, "LNG": 760.0, "Biofuel Blend": 820.0}
FUEL_AVAILABILITY = {"VLSFO": "High", "LNG": "Medium", "Biofuel Blend": "Limited"}
EMISSIONS_SOURCE_URL = (
    "https://wwwcdn.imo.org/localresources/en/KnowledgeCentre/"
    "IndexofIMOResolutions/MEPCDocuments/MEPC.395%2882%29.pdf"
)


def load_vessels(data_file=DATA_FILE):
    """Load prototype vessel records from JSON."""
    with Path(data_file).open(encoding="utf-8") as file:
        return json.load(file)


def load_ports(data_file=PORT_DATA_FILE):
    with Path(data_file).open(encoding="utf-8") as file:
        return json.load(file)


def port_fuel_context(port_name):
    port = next((p for p in load_ports() if p["port_name"] == port_name), None)
    return port or {
        "port_name": port_name,
        "supported_fuels": [],
        "evidence": "No official port source is configured.",
        "activity_indicator": "Not assessed",
        "inventory_status": "Not connected",
        "supplier_count": None,
        "last_verified": None,
        "source_name": None,
        "source_url": None,
        "api_name": None,
        "api_url": None,
    }


def _bounded_float(value, default, minimum=0, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number < minimum or (maximum is not None and number > maximum):
        return default
    return number


def apply_planner_assumptions(vessel, values=None):
    """Return an in-memory copy with validated planner inputs; never alter JSON."""
    values = values or {}
    adjusted = dict(vessel)
    adjusted["projected_bunker_quantity_tonnes"] = _bounded_float(
        values.get("bunker_quantity"), vessel["projected_bunker_quantity_tonnes"], maximum=20_000
    )
    adjusted["bunker_price_per_tonne"] = _bounded_float(
        values.get("fuel_price"), vessel["bunker_price_per_tonne"], maximum=10_000
    )
    adjusted["estimated_consumption_tpd"] = _bounded_float(
        values.get("consumption_tpd"), vessel["estimated_consumption_tpd"], maximum=500
    )
    adjusted["minimum_reserve_tonnes"] = _bounded_float(
        values.get("minimum_reserve"), vessel["minimum_reserve_tonnes"], maximum=20_000
    )
    compatibility = fuel_compatibility(adjusted)
    requested_fuel = values.get("selected_fuel", "LNG" if adjusted["lng_dual_fuel"] else "VLSFO")
    adjusted["selected_fuel"] = requested_fuel if compatibility.get(requested_fuel) in {"Compatible", "Potentially Compatible"} else ("LNG" if adjusted["lng_dual_fuel"] else "VLSFO")
    return adjusted


def current_fuel_percentage(vessel):
    capacity = vessel["tank_capacity_tonnes"]
    return round(vessel["current_fuel_tonnes"] / capacity * 100, 1) if capacity else 0.0


def reserve_margin(vessel):
    return round(calculate_projected_fuel(vessel) - vessel["minimum_reserve_tonnes"], 1)


def projected_bunker_cost(vessel):
    return round(vessel["projected_bunker_quantity_tonnes"] * vessel["bunker_price_per_tonne"], 2)


def voyage_days(vessel):
    departure = datetime.fromisoformat(vessel["departure_date"])
    arrival = datetime.fromisoformat(vessel["eta"])
    return max((arrival - departure).days, 0)


def estimated_voyage_consumption(vessel):
    return round(voyage_days(vessel) * vessel["estimated_consumption_tpd"], 1)


def calculate_projected_fuel(vessel):
    """Fuel after planned bunkering and estimated voyage consumption."""
    return round(
        vessel["current_fuel_tonnes"]
        + vessel["projected_bunker_quantity_tonnes"]
        - estimated_voyage_consumption(vessel),
        1,
    )


def tank_utilisation_after_bunkering(vessel):
    capacity = vessel["tank_capacity_tonnes"]
    level = vessel["current_fuel_tonnes"] + vessel["projected_bunker_quantity_tonnes"]
    return round(level / capacity * 100, 1) if capacity else 0.0


def check_tank_capacity(vessel):
    return vessel["current_fuel_tonnes"] + vessel["projected_bunker_quantity_tonnes"] <= vessel["tank_capacity_tonnes"]


def reserve_assessment(vessel):
    margin = reserve_margin(vessel)
    minimum = vessel["minimum_reserve_tonnes"]
    if margin <= minimum * 0.2:
        return "Review"
    if margin <= minimum * 0.6:
        return "Monitor"
    return "Healthy"


def fuel_compatibility(vessel):
    compatibility = {
        "VLSFO": "Compatible",
        "LNG": "Compatible" if vessel["lng_dual_fuel"] else "Not Supported",
        "Biofuel Blend": "Not Assessed",
    }
    if vessel["vessel_class"] == "O Class":
        compatibility["Biofuel Blend"] = "Potentially Compatible"
    return compatibility


def calculate_emissions(fuel_consumed_tonnes, fuel_type):
    return round(fuel_consumed_tonnes * EMISSION_FACTORS[fuel_type], 1)


def alternative_fuel_comparison(vessel):
    """Compare compatible fuels on equal prototype energy demand."""
    supported = [fuel for fuel, status in fuel_compatibility(vessel).items() if status != "Not Supported" and status != "Not Assessed"]
    baseline_consumption = estimated_voyage_consumption(vessel)
    baseline_energy = baseline_consumption * LOWER_CALORIFIC_VALUES_MJ_KG["VLSFO"]
    results = []
    selected_fuel = vessel.get("selected_fuel", "LNG" if vessel["lng_dual_fuel"] else "VLSFO")
    selected_required = baseline_energy / LOWER_CALORIFIC_VALUES_MJ_KG[selected_fuel]
    selected_price = vessel["bunker_price_per_tonne"]
    selected_cost = selected_required * selected_price
    selected_emissions = calculate_emissions(selected_required, selected_fuel)
    for fuel in supported:
        required = round(baseline_energy / LOWER_CALORIFIC_VALUES_MJ_KG[fuel], 1)
        price = selected_price if fuel == selected_fuel else PROTOTYPE_FUEL_PRICES[fuel]
        cost = round(required * price, 2)
        emissions = calculate_emissions(required, fuel)
        results.append({
            "fuel": fuel,
            "compatibility": fuel_compatibility(vessel)[fuel],
            "estimated_fuel_tonnes": required,
            "estimated_bunker_cost": cost,
            "estimated_emissions_tco2": emissions,
            "cost_difference": round(cost - selected_cost, 2),
            "emissions_difference_percentage": round((emissions - selected_emissions) / selected_emissions * 100, 1),
            "is_selected": fuel == selected_fuel,
            "availability": FUEL_AVAILABILITY[fuel],
            "trade_off": {
                "VLSFO": "Higher availability",
                "LNG": "Lower tank-to-wake CO₂ factor; greater infrastructure dependency",
                "Biofuel Blend": "Potential lower emissions; supplier verification required",
            }[fuel],
        })
    return results


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
        projected_fuel_on_arrival_tonnes=calculate_projected_fuel(vessel),
        estimated_voyage_consumption_tonnes=estimated_voyage_consumption(vessel),
        reserve_margin_tonnes=reserve_margin(vessel),
        projected_bunker_cost=projected_bunker_cost(vessel),
        low_fuel_reserve=is_low_fuel_reserve(vessel),
        upcoming_bunkering=requires_upcoming_bunkering(vessel),
        status=attention_status(vessel),
        attention_reasons=attention_reasons(vessel),
        estimated_emissions_tco2e=calculate_emissions(estimated_voyage_consumption(vessel), "LNG" if vessel["lng_dual_fuel"] else "VLSFO"),
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
            "estimated_voyage_consumption_tonnes": v["estimated_voyage_consumption_tonnes"],
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
            "tank_utilisation_after_bunkering_percentage": tank_utilisation_after_bunkering(v),
            "tank_capacity_check": "Pass" if check_tank_capacity(v) else "Review",
            "reserve_assessment": reserve_assessment(v),
        },
        "bunkering": {
            "next_port": v["next_bunkering_port"],
            "price_per_tonne": v["bunker_price_per_tonne"],
            "projected_quantity_tonnes": v["projected_bunker_quantity_tonnes"],
            "projected_cost": v["projected_bunker_cost"],
            "upcoming_requirement": v["upcoming_bunkering"],
            "planned_fuel": v.get("selected_fuel", "LNG" if v["lng_dual_fuel"] else "VLSFO"),
            "fuel_compatibility": fuel_compatibility(v),
            "fuel_availability": FUEL_AVAILABILITY[v.get("selected_fuel", "LNG" if v["lng_dual_fuel"] else "VLSFO")],
        },
        "sustainability": {
            "indicator": v["sustainability_indicator"],
            "estimated_emissions_tco2e": calculate_emissions(v["estimated_voyage_consumption_tonnes"], v.get("selected_fuel", "LNG" if v["lng_dual_fuel"] else "VLSFO")),
            "emission_factor": EMISSION_FACTORS[v.get("selected_fuel", "LNG" if v["lng_dual_fuel"] else "VLSFO")],
            "emissions_source_url": EMISSIONS_SOURCE_URL,
        },
        "base_risk": {"level": v["risk_level"], "attention_status": v["status"]},
    }


def fleet_sustainability_context(selected_vessel):
    fleet = [enrich_vessel(v) for v in load_vessels()]
    selected = enrich_vessel(selected_vessel)
    selected_fuel = selected_vessel.get("selected_fuel", "LNG" if selected_vessel["lng_dual_fuel"] else "VLSFO")
    selected["estimated_emissions_tco2e"] = calculate_emissions(selected["estimated_voyage_consumption_tonnes"], selected_fuel)
    average_emissions = sum(v["estimated_emissions_tco2e"] for v in fleet) / len(fleet)
    average_consumption = sum(v["estimated_voyage_consumption_tonnes"] for v in fleet) / len(fleet)
    average_margin = sum(v["reserve_margin_tonnes"] for v in fleet) / len(fleet)
    total_emissions = sum(v["estimated_emissions_tco2e"] for v in fleet)
    emissions_delta = (selected["estimated_emissions_tco2e"] - average_emissions) / average_emissions * 100
    class_fleet = [v for v in fleet if v["vessel_class"] == selected["vessel_class"]]
    selected_emissions_per_teu_day = selected["estimated_emissions_tco2e"] / selected["nominal_teu"] / max(voyage_days(selected), 1)
    class_emissions_per_teu_day = sum(v["estimated_emissions_tco2e"] / v["nominal_teu"] / max(voyage_days(v), 1) for v in class_fleet) / len(class_fleet)
    return {
        "average_emissions_tco2e": round(average_emissions, 1),
        "average_consumption_tonnes": round(average_consumption, 1),
        "average_reserve_margin_tonnes": round(average_margin, 1),
        "lng_dual_fuel_vessels": sum(v["lng_dual_fuel"] for v in fleet),
        "fleet_size": len(fleet),
        "selected_emissions_share_percentage": round(selected["estimated_emissions_tco2e"] / total_emissions * 100, 1),
        "emissions_difference_percentage": round(abs(emissions_delta), 1),
        "emissions_relative_position": "above" if emissions_delta > 0 else "below",
        "fuel_mix": {fuel: sum(v["fuel_type"] == fuel for v in fleet) for fuel in sorted({v["fuel_type"] for v in fleet})},
        "class_name": selected["vessel_class"],
        "class_vessel_count": len(class_fleet),
        "class_average_consumption_tpd": round(sum(v["estimated_consumption_tpd"] for v in class_fleet) / len(class_fleet), 1),
        "selected_consumption_tpd": selected["estimated_consumption_tpd"],
        "class_average_emissions_per_teu_day": round(class_emissions_per_teu_day, 4),
        "selected_emissions_per_teu_day": round(selected_emissions_per_teu_day, 4),
        "selected_reserve_margin_percentage": round(selected["reserve_margin_tonnes"] / selected["minimum_reserve_tonnes"] * 100, 1) if selected["minimum_reserve_tonnes"] else 0,
    }


def assessment_insights(vessel, fleet_context):
    v = enrich_vessel(vessel)
    minimum = v["minimum_reserve_tonnes"]
    reserve_percent = round(v["reserve_margin_tonnes"] / minimum * 100, 1) if minimum else 0
    reserve_position = "above" if reserve_percent >= 0 else "below"
    insights = [
        f"Projected arrival fuel is {abs(reserve_percent)}% {reserve_position} "
        "the configured minimum reserve."
    ]
    if v["lng_dual_fuel"]:
        insights.append("This vessel supports LNG dual-fuel operation, so a VLSFO/LNG trade-off can be assessed.")
    insights.append(
        f"Simulated voyage emissions are {fleet_context['emissions_difference_percentage']}% "
        f"{fleet_context['emissions_relative_position']} the prototype fleet average."
    )
    return insights


def build_assessment_context(vessel, planner_values=None):
    adjusted = apply_planner_assumptions(vessel, planner_values)
    voyage_context = build_voyage_context(adjusted)
    fleet_context = fleet_sustainability_context(adjusted)
    return {
        "voyage_context": voyage_context,
        "alternatives": alternative_fuel_comparison(adjusted),
        "fleet_context": fleet_context,
        "insights": assessment_insights(adjusted, fleet_context),
        "port_context": port_fuel_context(adjusted["next_bunkering_port"]),
        "planner_inputs": {
            "bunker_quantity": adjusted["projected_bunker_quantity_tonnes"],
            "fuel_price": adjusted["bunker_price_per_tonne"],
            "consumption_tpd": adjusted["estimated_consumption_tpd"],
            "minimum_reserve": adjusted["minimum_reserve_tonnes"],
            "selected_fuel": adjusted["selected_fuel"],
        },
        "baseline_inputs": {
            "bunker_quantity": vessel["projected_bunker_quantity_tonnes"],
            "fuel_price": vessel["bunker_price_per_tonne"],
            "consumption_tpd": vessel["estimated_consumption_tpd"],
            "minimum_reserve": vessel["minimum_reserve_tonnes"],
        },
        "assumptions": {
            "fuel_prices": PROTOTYPE_FUEL_PRICES,
            "emission_factors": EMISSION_FACTORS,
            "emissions_source_url": EMISSIONS_SOURCE_URL,
        },
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
