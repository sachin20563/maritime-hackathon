"""Voyage scenario calculation engine.

The engine reuses the repository's existing voyage-context calculations and adds
scenario deltas. It is deliberately deterministic: external APIs provide signals,
while Python performs the operational arithmetic.
"""

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.fleet_dashboard import (
    FUEL_AVAILABILITY,
    build_voyage_context,
    calculate_emissions,
    find_vessel,
)


WEATHER_EFFECTS = {
    "None": {"delay": 0.0, "fuel": 0.00, "risk": 0.0},
    "Mild": {"delay": 0.2, "fuel": 0.04, "risk": 0.5},
    "Moderate": {"delay": 0.6, "fuel": 0.10, "risk": 1.0},
    "Severe": {"delay": 1.3, "fuel": 0.20, "risk": 2.0},
}

CONGESTION_EFFECTS = {
    "None": {"delay": 0.0, "fuel": 0.00, "risk": 0.0},
    "Low": {"delay": 0.2, "fuel": 0.01, "risk": 0.25},
    "Medium": {"delay": 0.6, "fuel": 0.03, "risk": 0.75},
    "High": {"delay": 1.5, "fuel": 0.07, "risk": 1.5},
}

GEO_RISK = {"None": 0.0, "Medium": 1.0, "High": 2.0}
PORT_RISK = {"Open": 0.0, "Reduced": 0.75, "Closed": 1.5}

# Prototype bunker-port prices. These are explicitly labelled assumptions.
BUNKER_PORT_PRICES = {
    "Singapore": 625.0,
    "Shanghai": 608.0,
    "Busan": 612.0,
    "Hong Kong": 618.0,
    "Port Klang": 615.0,
    "Tanjung Pelepas": 618.0,
}

PORT_COORDINATES = {
    "Singapore": {"lat": 1.2644, "lng": 103.8200, "unlocode": "SGSIN"},
    "Shanghai": {"lat": 31.2304, "lng": 121.4737, "unlocode": "CNSHA"},
    "Ningbo": {"lat": 29.8683, "lng": 121.5440, "unlocode": "CNNGB"},
    "Busan": {"lat": 35.1028, "lng": 129.0403, "unlocode": "KRPUS"},
    "Hong Kong": {"lat": 22.3193, "lng": 114.1694, "unlocode": "HKHKG"},
    "Port Klang": {"lat": 3.0000, "lng": 101.4000, "unlocode": "MYPKG"},
    "Tanjung Pelepas": {"lat": 1.3600, "lng": 103.5500, "unlocode": "MYTPP"},
    "Callao": {"lat": -12.0464, "lng": -77.1428, "unlocode": "PECLL"},
    "Manzanillo": {"lat": 19.1136, "lng": -104.3380, "unlocode": "MXZLO"},
    "Guayaquil": {"lat": -2.1894, "lng": -79.8891, "unlocode": "ECGYE"},
    "Tema": {"lat": 5.6698, "lng": 0.0166, "unlocode": "GHTEM"},
    "Lagos": {"lat": 6.4541, "lng": 3.3947, "unlocode": "NGLOS"},
    "Abidjan": {"lat": 5.3167, "lng": -4.0333, "unlocode": "CIABJ"},
    "Santos": {"lat": -23.9608, "lng": -46.3336, "unlocode": "BRSSZ"},
}


def get_port_unlocode(port_name: str) -> str | None:
    mapping = {
        "Singapore": "SGSIN", "Shanghai": "CNSHA", "Ningbo": "CNNGB",
        "Busan": "KRPUS", "Hong Kong": "HKHKG", "Port Klang": "MYPKG",
        "Tanjung Pelepas": "MYTPP", "Callao": "PECLL", "Manzanillo": "MXZLO",
        "Guayaquil": "ECGYE", "Tema": "GHTEM", "Lagos": "NGLOS",
        "Abidjan": "CIABJ", "Santos": "BRSSZ", "Los Angeles": "USLAX",
        "New York": "USNYC", "Rotterdam": "NLRTM",
    }
    return mapping.get(port_name)


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _risk_level(score: float) -> str:
    if score >= 5:
        return "High"
    if score >= 2.5:
        return "Medium"
    return "Low"


def _base_risk_score(level: str) -> float:
    return {"Low": 1.0, "Medium": 2.5, "High": 4.0}.get(level, 2.5)


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _port_options(current_port: str) -> list[dict[str, Any]]:
    preferred = ["Singapore", "Shanghai", "Busan", "Hong Kong", "Port Klang", "Tanjung Pelepas"]
    options = []
    for name in preferred:
        if name == current_port:
            continue
        options.append({
            "name": name,
            "price": BUNKER_PORT_PRICES.get(name, 625.0),
            "coordinates": PORT_COORDINATES.get(name),
        })
    return options


def run_scenario(vessel_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    vessel = find_vessel(vessel_id)
    if vessel is None:
        raise KeyError(vessel_id)

    baseline = deepcopy(build_voyage_context(vessel))

    weather = inputs.get("weather", "None")
    congestion = inputs.get("congestion", "None")
    geopolitical = inputs.get("geopolitical", "None")
    port_status = inputs.get("port_status", "Open")
    fuel_supply = inputs.get("fuel_supply", "Available")

    if weather not in WEATHER_EFFECTS:
        weather = "None"
    if congestion not in CONGESTION_EFFECTS:
        congestion = "None"
    if geopolitical not in GEO_RISK:
        geopolitical = "None"
    if port_status not in PORT_RISK:
        port_status = "Open"
    if fuel_supply not in {"Available", "Constrained"}:
        fuel_supply = "Available"

    delay_days = max(0.0, min(_num(inputs.get("delay_days")), 7.0))
    fuel_price_change_pct = max(-30.0, min(_num(inputs.get("fuel_price_change_pct")), 50.0))

    current_port = baseline["bunkering"]["next_port"]
    alternative_port = inputs.get("alternative_bunkering_port") or current_port
    valid_ports = {p["name"] for p in _port_options(current_port)} | {current_port}
    if alternative_port not in valid_ports:
        alternative_port = current_port

    weather_effect = WEATHER_EFFECTS[weather]
    congestion_effect = CONGESTION_EFFECTS[congestion]

    baseline_duration = max(
        0.1,
        (_parse_date(baseline["voyage"]["eta"]) - _parse_date(baseline["voyage"]["departure_date"])).total_seconds() / 86400,
    )
    consumption_tpd = _num(baseline["voyage"]["estimated_consumption_tpd"])
    current_fuel = _num(baseline["fuel_status"]["current_fuel_tonnes"])
    minimum_reserve = _num(baseline["fuel_status"]["minimum_reserve_tonnes"])
    planned_bunker = _num(baseline["bunkering"]["projected_quantity_tonnes"])
    baseline_price = _num(baseline["bunkering"]["price_per_tonne"])
    fuel_type = baseline["bunkering"]["planned_fuel"]

    route_deviation = 0.6 if port_status == "Closed" and alternative_port != current_port else 0.0

    duration = (
        baseline_duration
        + weather_effect["delay"]
        + congestion_effect["delay"]
        + delay_days
        + route_deviation
    )

    fuel_multiplier = 1 + weather_effect["fuel"] + congestion_effect["fuel"]
    voyage_consumption = max(0.0, consumption_tpd * duration * fuel_multiplier)

    required_bunker = max(
        0.0,
        voyage_consumption + minimum_reserve - current_fuel,
    )
    bunker_quantity = max(planned_bunker, required_bunker)

    scenario_price = baseline_price * (1 + fuel_price_change_pct / 100.0)
    if alternative_port != current_port:
        scenario_price = BUNKER_PORT_PRICES.get(alternative_port, scenario_price)
        scenario_price *= 1 + fuel_price_change_pct / 100.0

    arrival_fuel = current_fuel + bunker_quantity - voyage_consumption
    reserve_margin = arrival_fuel - minimum_reserve
    bunker_cost = bunker_quantity * scenario_price
    emissions = calculate_emissions(voyage_consumption, fuel_type)

    score = _base_risk_score(baseline["base_risk"]["level"])
    reasons = []

    score += weather_effect["risk"]
    if weather != "None":
        reasons.append(f"{weather} weather signal")

    score += congestion_effect["risk"]
    if congestion not in {"None", "Low"}:
        reasons.append(f"{congestion} congestion")

    score += GEO_RISK[geopolitical]
    if geopolitical != "None":
        reasons.append(f"{geopolitical} geopolitical exposure")

    score += PORT_RISK[port_status]
    if port_status != "Open":
        reasons.append(f"Port availability: {port_status}")

    if fuel_supply == "Constrained":
        score += 1
        reasons.append("Fuel supply constrained")

    if reserve_margin < 0:
        score += 2
        reasons.append("Projected arrival below minimum reserve")
    elif reserve_margin < minimum_reserve * 0.5:
        score += 1
        reasons.append("Narrow arrival reserve")

    scenario_risk = _risk_level(score)

    scenario = deepcopy(baseline)
    scenario["voyage"]["voyage_duration_days"] = round(duration, 2)
    scenario["voyage"]["estimated_voyage_consumption_tonnes"] = round(voyage_consumption, 1)
    scenario["fuel_status"]["projected_fuel_on_arrival_tonnes"] = round(arrival_fuel, 1)
    scenario["fuel_status"]["reserve_margin_tonnes"] = round(reserve_margin, 1)
    scenario["fuel_status"]["reserve_assessment"] = (
        "Review" if reserve_margin <= 0 else
        "Monitor" if reserve_margin <= minimum_reserve * 0.6 else
        "Healthy"
    )
    scenario["bunkering"]["next_port"] = alternative_port
    scenario["bunkering"]["price_per_tonne"] = round(scenario_price, 2)
    scenario["bunkering"]["projected_quantity_tonnes"] = round(bunker_quantity, 1)
    scenario["bunkering"]["projected_cost"] = round(bunker_cost, 2)
    scenario["bunkering"]["fuel_availability"] = (
        "Constrained" if fuel_supply == "Constrained"
        else FUEL_AVAILABILITY.get(fuel_type, "Unknown")
    )
    scenario["sustainability"]["estimated_emissions_tco2e"] = emissions
    scenario["risk"] = {
        "level": scenario_risk,
        "score": round(score, 2),
        "reasons": reasons,
    }

    metrics = {
        "bunker_price": {
            "baseline": round(baseline["bunkering"]["price_per_tonne"], 2),
            "scenario": round(scenario_price, 2),
        },
        "bunker_cost": {
            "baseline": round(baseline["bunkering"]["projected_cost"], 2),
            "scenario": round(bunker_cost, 2),
        },
        "fuel_consumption": {
            "baseline": round(baseline["voyage"]["estimated_voyage_consumption_tonnes"], 1),
            "scenario": round(voyage_consumption, 1),
        },
        "arrival_fuel": {
            "baseline": round(baseline["fuel_status"]["projected_fuel_on_arrival_tonnes"], 1),
            "scenario": round(arrival_fuel, 1),
        },
        "reserve_margin": {
            "baseline": round(baseline["fuel_status"]["reserve_margin_tonnes"], 1),
            "scenario": round(reserve_margin, 1),
        },
        "voyage_duration": {
            "baseline": round(baseline_duration, 2),
            "scenario": round(duration, 2),
        },
        "emissions": {
            "baseline": round(baseline["sustainability"]["estimated_emissions_tco2e"], 1),
            "scenario": round(emissions, 1),
        },
        "bunker_quantity": {
            "baseline": round(planned_bunker, 1),
            "scenario": round(bunker_quantity, 1),
        },
    }

    return {
        "vessel_id": vessel_id,
        "vessel": baseline["vessel"],
        "inputs": {
            "weather": weather,
            "congestion": congestion,
            "geopolitical": geopolitical,
            "port_status": port_status,
            "fuel_supply": fuel_supply,
            "delay_days": delay_days,
            "fuel_price_change_pct": fuel_price_change_pct,
            "alternative_bunkering_port": alternative_port,
        },
        "baseline": baseline,
        "scenario": scenario,
        "metrics": metrics,
        "risk": {
            "baseline": baseline["base_risk"]["level"],
            "scenario": scenario_risk,
            "score": round(score, 2),
            "reasons": reasons,
            "method": "Transparent prototype rule-based score; not PIL internal methodology.",
        },
        "route": {
            "origin": baseline["voyage"]["origin"],
            "bunkering_port": current_port,
            "scenario_bunkering_port": alternative_port,
            "destination": baseline["voyage"]["destination"],
            "coordinates": {
                "origin": PORT_COORDINATES.get(baseline["voyage"]["origin"]),
                "bunkering": PORT_COORDINATES.get(current_port),
                "scenario_bunkering": PORT_COORDINATES.get(alternative_port),
                "destination": PORT_COORDINATES.get(baseline["voyage"]["destination"]),
            },
        },
    }


def build_portfolio_snapshot() -> dict[str, Any]:
    """Build fleet-wide structured data for the AI portfolio layer."""
    from app.fleet_dashboard import load_vessels

    rows = []
    for vessel in load_vessels():
        context = build_voyage_context(vessel)
        rows.append({
            "vessel_id": vessel["vessel_id"],
            "vessel_name": vessel["vessel_name"],
            "route": f'{vessel["origin"]} → {vessel["destination"]}',
            "risk": context["base_risk"]["level"],
            "reserve_margin_tonnes": context["fuel_status"]["reserve_margin_tonnes"],
            "projected_bunker_cost": context["bunkering"]["projected_cost"],
            "fuel": context["bunkering"]["planned_fuel"],
            "emissions_tco2e": context["sustainability"]["estimated_emissions_tco2e"],
            "next_bunkering_port": context["bunkering"]["next_port"],
        })

    return {
        "fleet_size": len(rows),
        "risk_counts": {
            level: sum(r["risk"] == level for r in rows)
            for level in ("Low", "Medium", "High")
        },
        "high_risk_vessels": [r for r in rows if r["risk"] == "High"],
        "lowest_reserves": sorted(rows, key=lambda x: x["reserve_margin_tonnes"])[:4],
        "highest_cost_exposure": sorted(
            rows, key=lambda x: x["projected_bunker_cost"], reverse=True
        )[:4],
        "total_projected_bunker_cost": round(
            sum(r["projected_bunker_cost"] for r in rows), 2
        ),
        "total_emissions_tco2e": round(
            sum(r["emissions_tco2e"] for r in rows), 1
        ),
        "vessels": rows,
    }