"""Deterministic voyage scenario calculations for planner decision support.

Person 1's voyage-context object is always deep-copied. Scenario inputs never
mutate the vessel dataset and every synthetic value is labelled as a prototype
assumption in the returned payload.
"""

from copy import deepcopy
from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any

from app.fleet_dashboard import (
    EMISSION_FACTORS,
    FUEL_AVAILABILITY,
    PROTOTYPE_FUEL_PRICES,
    build_voyage_context,
    calculate_emissions,
    find_vessel,
    fuel_compatibility,
    load_vessels,
)


WEATHER_EFFECTS = {
    "Not Considered": {"delay": 0.0, "fuel": 0.00, "risk": 0.0, "price": 0.00},
    "Normal": {"delay": 0.0, "fuel": 0.01, "risk": 0.0, "price": 0.00},
    "Moderate": {"delay": 0.6, "fuel": 0.08, "risk": 1.0, "price": 0.02},
    "Severe": {"delay": 1.3, "fuel": 0.16, "risk": 2.0, "price": 0.04},
}
CONGESTION_EFFECTS = {
    "Not Considered": {"delay": 0.0, "fuel": 0.00, "risk": 0.0, "price": 0.00},
    "Low": {"delay": 0.2, "fuel": 0.01, "risk": 0.25, "price": 0.01},
    "Moderate": {"delay": 0.7, "fuel": 0.03, "risk": 0.75, "price": 0.04},
    "High": {"delay": 1.5, "fuel": 0.07, "risk": 1.5, "price": 0.08},
}
GEOPOLITICAL_EFFECTS = {
    "Not Considered": {"delay": 0.0, "fuel": 0.00, "risk": 0.0, "price": 0.00},
    "Medium": {"delay": 0.8, "fuel": 0.04, "risk": 1.0, "price": 0.03},
    "High": {"delay": 1.8, "fuel": 0.09, "risk": 2.0, "price": 0.06},
}
SUPPLY_PRICE_EFFECTS = {"High": -0.01, "Moderate": 0.02, "Limited": 0.08}

PORT_COORDINATES = {
    "Singapore": {"lat": 1.2644, "lng": 103.8200, "unlocode": "SGSIN"},
    "Shanghai": {"lat": 31.2304, "lng": 121.4737, "unlocode": "CNSHA"},
    "Ningbo": {"lat": 29.8683, "lng": 121.5440, "unlocode": "CNNGB"},
    "Qingdao": {"lat": 36.0671, "lng": 120.3826, "unlocode": "CNQDG"},
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
BUNKER_PORTS = ["Singapore", "Shanghai", "Busan", "Hong Kong", "Port Klang", "Tanjung Pelepas"]

# Prototype anchorage positions are intentionally offshore. They provide stable
# map placement for congestion vessels and are not live AIS or berth data.
PORT_ANCHORAGES = {
    "Singapore": [[1.10, 103.72], [1.05, 103.80], [1.12, 103.88], [1.18, 103.72], [1.20, 103.85], [1.08, 103.95], [1.16, 104.00], [1.02, 103.65], [1.00, 103.90], [1.22, 103.92], [1.14, 103.64], [0.98, 103.75], [1.05, 104.02]],
    "Shanghai": [[30.78, 122.18], [30.88, 122.30], [30.98, 122.42], [31.08, 122.54], [31.18, 122.66], [30.72, 122.40], [30.84, 122.54], [30.96, 122.68], [31.10, 122.80], [31.24, 122.72], [30.66, 122.58], [30.80, 122.76], [30.94, 122.88]],
    "Busan": [[34.88, 129.24], [34.84, 129.32], [34.92, 129.38], [34.80, 129.44], [34.90, 129.50], [34.76, 129.54], [34.86, 129.60], [34.72, 129.64], [34.82, 129.70], [34.68, 129.74], [34.78, 129.80], [34.64, 129.84], [34.74, 129.90]],
    "Hong Kong": [[22.08, 114.16], [22.02, 114.22], [21.96, 114.28], [22.10, 114.32], [22.02, 114.38], [21.94, 114.44], [22.08, 114.48], [21.98, 114.54], [21.90, 114.60], [22.04, 114.64], [21.94, 114.70], [21.86, 114.76], [22.00, 114.80]],
    "Port Klang": [[2.94, 101.14], [2.86, 101.08], [3.02, 101.04], [2.78, 101.00], [2.94, 100.96], [3.10, 100.92], [2.84, 100.88], [3.02, 100.84], [2.74, 100.80], [2.92, 100.76], [3.12, 100.72], [2.82, 100.68], [3.00, 100.64]],
    "Tanjung Pelepas": [[1.24, 103.42], [1.18, 103.36], [1.12, 103.30], [1.06, 103.42], [1.00, 103.34], [0.94, 103.26], [1.16, 103.22], [1.08, 103.16], [0.98, 103.10], [1.20, 103.06], [1.10, 103.00], [0.90, 103.18], [0.86, 103.08]],
}


def get_port_unlocode(port_name: str) -> str | None:
    point = PORT_COORDINATES.get(port_name)
    return point.get("unlocode") if point else None


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _choice(value: Any, choices: set[str], default: str) -> str:
    return value if value in choices else default


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


def _distance_nm(points: list[dict[str, float]]) -> float:
    """Great-circle segment total; prototype routing estimate, not navigation data."""
    total_km = 0.0
    for first, second in zip(points, points[1:]):
        lat1, lon1 = radians(first["lat"]), radians(first["lng"])
        lat2, lon2 = radians(second["lat"]), radians(second["lng"])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        total_km += 6371.0088 * 2 * asin(sqrt(value))
    return round(total_km / 1.852, 0)


def _point(name: str) -> dict[str, Any] | None:
    coords = PORT_COORDINATES.get(name)
    return {"name": name, **coords} if coords else None


def _waypoint(name: str, lat: float, lng: float, movable: bool = True) -> dict[str, Any]:
    return {"name": name, "lat": lat, "lng": lng, "prototype": True, "movable": movable}


def _tag_route_roles(points: list[dict[str, Any]], origin: str, bunker: str, destination: str) -> list[dict[str, Any]]:
    for point in points:
        if point["name"] == origin:
            point["role"] = "origin"
        if point["name"] == bunker:
            point["role"] = "bunker"
        if point["name"] == destination:
            point["role"] = "destination"
    return points


def _route_points(origin: str, bunker: str, destination: str, deviation: bool = False) -> list[dict[str, Any]]:
    """Build a display route through water-based prototype corridors.

    These waypoints are deliberately explicit instead of straight port-to-port
    lines. They are visual planning corridors, not safe-navigation instructions.
    """
    origin_point, bunker_point, destination_point = _point(origin), _point(bunker), _point(destination)
    if not origin_point or not destination_point:
        return _tag_route_roles([point for point in (origin_point, bunker_point, destination_point) if point], origin, bunker, destination)

    west_africa_or_atlantic = destination in {"Santos", "Tema", "Lagos", "Abidjan"}
    pacific_america = destination in {"Callao", "Guayaquil", "Manzanillo"}
    asia_destination = destination in {"Singapore", "Shanghai", "Ningbo", "Qingdao", "Busan", "Hong Kong", "Port Klang", "Tanjung Pelepas"}
    northern_bunker = bunker in {"Shanghai", "Ningbo", "Qingdao", "Busan", "Hong Kong"}
    if asia_destination:
        points = [origin_point]
        if bunker_point and bunker != origin:
            points.extend([_waypoint("South China Sea bunker approach", 12.0, 113.0, False), bunker_point])
        if destination != bunker:
            points.extend([_waypoint("South China Sea shipping corridor", 16.0, 116.0), destination_point])
        return _tag_route_roles(points, origin, bunker, destination)

    points = [origin_point]
    if northern_bunker and bunker_point and bunker != origin:
        points.extend([_waypoint("East China Sea approach", 27.0, 126.0, False), bunker_point])

    points.extend([
        _waypoint("South China Sea corridor", 12.0, 113.0, False),
        _waypoint("Malacca approach", 3.8, 106.0, False),
    ])
    if not northern_bunker and bunker_point:
        points.append(bunker_point)
    points.extend([
        _waypoint("Sunda Strait approach", -5.7, 105.9, False),
        _waypoint("Eastern Indian Ocean", -12.0, 92.0),
    ])

    if west_africa_or_atlantic:
        points.extend([
            _waypoint("Central Indian Ocean", -24.0, 67.0),
            _waypoint("Southwest Indian Ocean", -34.0, 42.0),
            _waypoint("Cape of Good Hope corridor", -36.5, 20.0, False),
        ])
        if destination == "Santos":
            points.extend([
                _waypoint("South Atlantic east", -37.0, 5.0),
                _waypoint("South Atlantic central", -32.0, -22.0),
                _waypoint("Brazil offshore approach", -27.0, -40.0, False),
            ])
        else:
            points.extend([
                _waypoint("South Atlantic African corridor", -30.0, 10.0),
                _waypoint("West Africa offshore corridor", -12.0, -1.0, False),
            ])
    elif pacific_america:
        # Longitudes continue beyond 180 so Leaflet draws across the wrapped
        # Pacific instead of placing a false line across Asia and Africa.
        points.extend([
            _waypoint("Timor Sea corridor", -14.0, 124.0, False),
            _waypoint("Western Pacific", -12.0, 150.0),
            _waypoint("International Date Line", -10.0, 180.0),
            _waypoint("Central Pacific", -8.0, 215.0),
            _waypoint("Eastern Pacific", -10.0, 250.0),
        ])
        destination_point = {**destination_point, "lng": destination_point["lng"] + 360}

    if deviation:
        for point in points:
            if point.get("prototype") and point.get("movable"):
                point["lat"] = round(point["lat"] - 3.5, 2)
                point["name"] = f'{point["name"]} · scenario deviation'

    points.append(destination_point)
    deduplicated = []
    for point in points:
        if not deduplicated or (point["lat"], point["lng"]) != (deduplicated[-1]["lat"], deduplicated[-1]["lng"]):
            deduplicated.append(point)
    return _tag_route_roles(deduplicated, origin, bunker, destination)


def _tradeoffs(metrics: dict[str, Any], baseline_risk: str, scenario_risk: str, fuel: str, sustainability: bool) -> list[dict[str, str]]:
    items = []
    cost_delta = metrics["total_voyage_cost"]["difference"]
    time_delta = metrics["voyage_time"]["difference"]
    emissions_delta = metrics["estimated_emissions"]["difference"]
    if cost_delta > 0:
        items.append({"tone": "cost", "title": "Higher expected cost", "detail": f"Prototype voyage cost increases by ${cost_delta:,.0f}."})
    elif cost_delta < 0:
        items.append({"tone": "benefit", "title": "Lower expected cost", "detail": f"Prototype voyage cost decreases by ${abs(cost_delta):,.0f}."})
    if time_delta > 0:
        items.append({"tone": "time", "title": "Longer voyage time", "detail": f"Selected conditions add {time_delta:.1f} days."})
    if scenario_risk != baseline_risk:
        items.append({"tone": "risk", "title": f"Operational risk: {scenario_risk}", "detail": f"Risk changes from {baseline_risk} to {scenario_risk} under selected factors."})
    if sustainability:
        direction = "reduces" if emissions_delta < 0 else "increases"
        items.append({"tone": "sustainability", "title": f"{fuel} sustainability lens", "detail": f"The prototype estimate {direction} emissions by {abs(emissions_delta):,.1f} tCO2e versus the initial route."})
    return items[:4] or [{"tone": "neutral", "title": "No material scenario change", "detail": "Selected factors do not materially change the initial route assumptions."}]


def _compliance(fuel: str) -> dict[str, str]:
    if fuel in {"VLSFO", "LNG"}:
        return {
            "title": "IMO 2020 check",
            "status": "Compliant under prototype assumption",
            "tone": "compliant",
            "fuel": fuel,
            "explanation": f"{fuel} is assumed to meet the prototype's IMO 2020 sulphur requirement. This is informational and not a compliance certificate.",
        }
    return {
        "title": "IMO 2020 check",
        "status": "Requires review",
        "tone": "review",
        "fuel": fuel,
        "explanation": "Supplier documentation and the vessel-specific fuel configuration must be reviewed; the prototype cannot certify compliance.",
    }


def scenario_page_context(vessel: dict[str, Any]) -> dict[str, Any]:
    baseline = build_voyage_context(vessel)
    compatibility = fuel_compatibility(vessel)
    fuels = [
        {"name": name, "status": status, "available": status in {"Compatible", "Potentially Compatible"}}
        for name, status in compatibility.items()
    ]
    return {
        "voyage_context": baseline,
        "fuel_options": fuels,
        "port_options": sorted(PORT_COORDINATES),
        "bunker_ports": BUNKER_PORTS,
        "default_cargo_weight": int(vessel.get("nominal_teu", 0) * 7),
        "initial_route": _route_points(
            baseline["voyage"]["origin"],
            baseline["bunkering"]["next_port"],
            baseline["voyage"]["destination"],
        ),
    }


def run_scenario(vessel_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    vessel = find_vessel(vessel_id)
    if vessel is None:
        raise KeyError(vessel_id)

    source = deepcopy(build_voyage_context(vessel))
    supplied_controlled = inputs.get("controlled_factors") or inputs
    supplied_uncontrolled = inputs.get("uncontrolled_factors") or inputs
    compatibility = fuel_compatibility(vessel)

    primary_fuel = source["vessel"]["fuel_type"]
    requested_fuel = supplied_controlled.get("bunker_type", source["bunkering"]["planned_fuel"])
    compatible = compatibility.get(requested_fuel) in {"Compatible", "Potentially Compatible"}
    bunker_type = requested_fuel if compatible else source["bunkering"]["planned_fuel"]
    origin = _choice(supplied_controlled.get("origin_port"), set(PORT_COORDINATES), source["voyage"]["origin"])
    destination = _choice(supplied_controlled.get("destination_port"), set(PORT_COORDINATES), source["voyage"]["destination"])
    departure = supplied_controlled.get("estimated_departure") or source["voyage"]["departure_date"]
    default_supply = {"Medium": "Moderate"}.get(
        FUEL_AVAILABILITY.get(bunker_type, "Moderate"),
        FUEL_AVAILABILITY.get(bunker_type, "Moderate"),
    )
    fuel_supply = _choice(supplied_controlled.get("fuel_supply"), set(SUPPLY_PRICE_EFFECTS), default_supply)
    cargo_default = float(vessel.get("nominal_teu", 0) * 7)
    cargo_weight = max(0.0, min(_num(supplied_controlled.get("cargo_weight_tonnes"), cargo_default), cargo_default * 1.5 or 200_000))
    sustainability = bool(supplied_controlled.get("consider_sustainability", False))

    weather_data = supplied_uncontrolled.get("weather", {})
    congestion_data = supplied_uncontrolled.get("port_congestion", supplied_uncontrolled.get("congestion", {}))
    geo_data = supplied_uncontrolled.get("geopolitical", {})
    if isinstance(weather_data, str):
        weather_data = {"enabled": weather_data not in {"None", "Not Considered"}, "severity": weather_data}
    if isinstance(congestion_data, str):
        congestion_data = {"enabled": congestion_data not in {"None", "Not Considered"}, "level": congestion_data}
    if isinstance(geo_data, str):
        geo_data = {"enabled": geo_data not in {"None", "Not Considered"}, "risk_level": geo_data}
    weather = _choice(weather_data.get("severity") if weather_data.get("enabled") else "Not Considered", set(WEATHER_EFFECTS), "Not Considered")
    congestion = _choice(congestion_data.get("level") if congestion_data.get("enabled") else "Not Considered", set(CONGESTION_EFFECTS), "Not Considered")
    geopolitical = _choice(geo_data.get("risk_level") if geo_data.get("enabled") else "Not Considered", set(GEOPOLITICAL_EFFECTS), "Not Considered")

    controlled = {
        "fuel_supply": fuel_supply,
        "vessel_type": source["vessel"]["vessel_type"],
        "primary_fuel": primary_fuel,
        "bunker_type": bunker_type,
        "fuel_compatibility": compatibility.get(bunker_type, "Not Assessed"),
        "origin_port": origin,
        "destination_port": destination,
        "estimated_departure": departure,
        "cargo_weight_tonnes": round(cargo_weight, 0),
        "consider_sustainability": sustainability,
    }
    uncontrolled = {
        "weather": {"enabled": weather != "Not Considered", "severity": weather},
        "port_congestion": {"enabled": congestion != "Not Considered", "level": congestion},
        "geopolitical": {"enabled": geopolitical != "Not Considered", "risk_level": geopolitical},
    }

    baseline = deepcopy(source)
    baseline["voyage"].update({"origin": origin, "destination": destination, "departure_date": departure})
    baseline["bunkering"]["planned_fuel"] = bunker_type
    baseline["bunkering"]["fuel_availability"] = fuel_supply
    baseline_duration = max(0.1, (_parse_date(source["voyage"]["eta"]) - _parse_date(source["voyage"]["departure_date"])).total_seconds() / 86400)
    reference_cargo = max(cargo_default, 1)
    cargo_ratio = cargo_weight / reference_cargo
    cargo_multiplier = max(0.90, min(1.12, 1 + (cargo_ratio - 1) * 0.20))
    baseline_consumption = round(_num(source["voyage"]["estimated_consumption_tpd"]) * baseline_duration * cargo_multiplier, 1)
    baseline_price = _num(source["bunkering"]["price_per_tonne"])
    if bunker_type != source["bunkering"]["planned_fuel"]:
        baseline_price = PROTOTYPE_FUEL_PRICES[bunker_type]
    baseline_price = round(baseline_price * (1 + SUPPLY_PRICE_EFFECTS[fuel_supply]), 2)
    current_fuel = _num(source["fuel_status"]["current_fuel_tonnes"])
    minimum_reserve = _num(source["fuel_status"]["minimum_reserve_tonnes"])
    planned_bunker = _num(source["bunkering"]["projected_quantity_tonnes"])
    baseline_quantity = max(planned_bunker, baseline_consumption + minimum_reserve - current_fuel)
    baseline_arrival = current_fuel + baseline_quantity - baseline_consumption
    baseline_bunker_cost = baseline_quantity * baseline_price
    operational_day_cost = 25_000.0
    baseline_total_cost = baseline_bunker_cost + baseline_duration * operational_day_cost
    baseline_emissions = calculate_emissions(baseline_consumption, bunker_type)
    baseline["voyage"].update({"voyage_duration_days": round(baseline_duration, 2), "estimated_voyage_consumption_tonnes": baseline_consumption})
    baseline["fuel_status"].update({"projected_fuel_on_arrival_tonnes": round(baseline_arrival, 1), "reserve_margin_tonnes": round(baseline_arrival - minimum_reserve, 1)})
    baseline["bunkering"].update({"price_per_tonne": baseline_price, "projected_quantity_tonnes": round(baseline_quantity, 1), "projected_cost": round(baseline_bunker_cost, 2)})
    baseline["sustainability"].update({"estimated_emissions_tco2e": baseline_emissions, "emission_factor": EMISSION_FACTORS[bunker_type]})

    weather_effect, congestion_effect, geo_effect = WEATHER_EFFECTS[weather], CONGESTION_EFFECTS[congestion], GEOPOLITICAL_EFFECTS[geopolitical]
    external_active = any((uncontrolled["weather"]["enabled"], uncontrolled["port_congestion"]["enabled"], uncontrolled["geopolitical"]["enabled"]))
    deviation = weather in {"Moderate", "Severe"} or geopolitical in {"Medium", "High"}
    alternative_port = baseline["bunkering"]["next_port"]
    if congestion == "High" or fuel_supply == "Limited":
        alternatives = [p for p in BUNKER_PORTS if p != alternative_port]
        alternative_port = min(alternatives, key=lambda p: PROTOTYPE_FUEL_PRICES[bunker_type] + BUNKER_PORTS.index(p))

    delay = weather_effect["delay"] + congestion_effect["delay"] + geo_effect["delay"]
    duration = baseline_duration + delay
    fuel_multiplier = 1 + weather_effect["fuel"] + congestion_effect["fuel"] + geo_effect["fuel"]
    scenario_consumption = round(baseline_consumption * (duration / baseline_duration) * fuel_multiplier, 1)
    scenario_quantity = max(baseline_quantity, scenario_consumption + minimum_reserve - current_fuel)
    scenario_price = baseline_price * (1 + weather_effect["price"] + congestion_effect["price"] + geo_effect["price"])
    if alternative_port != baseline["bunkering"]["next_port"]:
        scenario_price = PROTOTYPE_FUEL_PRICES[bunker_type] * (1 + congestion_effect["price"] + geo_effect["price"])
    scenario_price = round(scenario_price, 2)
    scenario_arrival = current_fuel + scenario_quantity - scenario_consumption
    scenario_bunker_cost = scenario_quantity * scenario_price
    scenario_total_cost = scenario_bunker_cost + duration * operational_day_cost
    scenario_emissions = calculate_emissions(scenario_consumption, bunker_type)

    score = _base_risk_score(source["base_risk"]["level"])
    score += weather_effect["risk"] + congestion_effect["risk"] + geo_effect["risk"]
    reasons = []
    if weather != "Not Considered": reasons.append(f"{weather} weather included")
    if congestion != "Not Considered": reasons.append(f"{congestion} port congestion included")
    if geopolitical != "Not Considered": reasons.append(f"{geopolitical} geopolitical exposure included")
    if fuel_supply == "Limited": reasons.append("Limited fuel availability")
    if scenario_arrival < minimum_reserve: score += 2; reasons.append("Projected arrival below minimum reserve")
    scenario_risk = _risk_level(score)

    simulated = deepcopy(baseline)
    simulated["voyage"].update({"voyage_duration_days": round(duration, 2), "estimated_voyage_consumption_tonnes": scenario_consumption})
    simulated["fuel_status"].update({"projected_fuel_on_arrival_tonnes": round(scenario_arrival, 1), "reserve_margin_tonnes": round(scenario_arrival - minimum_reserve, 1)})
    simulated["bunkering"].update({"next_port": alternative_port, "price_per_tonne": scenario_price, "projected_quantity_tonnes": round(scenario_quantity, 1), "projected_cost": round(scenario_bunker_cost, 2)})
    simulated["sustainability"]["estimated_emissions_tco2e"] = scenario_emissions
    simulated["risk"] = {"level": scenario_risk, "score": round(score, 2), "reasons": reasons}

    baseline_points = _route_points(origin, baseline["bunkering"]["next_port"], destination)
    simulated_points = _route_points(origin, alternative_port, destination, deviation=deviation)
    baseline_distance = _distance_nm(baseline_points)
    simulated_distance = _distance_nm(simulated_points)

    def metric(base: Any, scenario: Any) -> dict[str, Any]:
        difference = scenario - base if isinstance(base, (int, float)) and isinstance(scenario, (int, float)) else ("Changed" if base != scenario else "No change")
        if isinstance(difference, float): difference = round(difference, 2)
        return {"baseline": base, "simulated": scenario, "difference": difference}

    metrics = {
        "bunker_price": metric(baseline_price, scenario_price),
        "bunker_cost": metric(round(baseline_bunker_cost, 2), round(scenario_bunker_cost, 2)),
        "total_voyage_cost": metric(round(baseline_total_cost, 2), round(scenario_total_cost, 2)),
        "voyage_time": metric(round(baseline_duration, 2), round(duration, 2)),
        "fuel_consumption": metric(baseline_consumption, scenario_consumption),
        "arrival_reserve": metric(round(baseline_arrival, 1), round(scenario_arrival, 1)),
        "estimated_emissions": metric(baseline_emissions, scenario_emissions),
        "operational_risk": metric(source["base_risk"]["level"], scenario_risk),
        "route_distance": metric(baseline_distance, simulated_distance),
        "bunkering_port": metric(baseline["bunkering"]["next_port"], alternative_port),
    }

    alerts = {
        "weather_alerts": ([{"name": f"{weather} weather zone", "severity": weather, "lat": 12.0, "lng": 112.0, "radius_nm": 360, "mocked": True}] if uncontrolled["weather"]["enabled"] else []),
        "geopolitical_alerts": ([{"name": "Red Sea disruption", "region": "Red Sea", "risk_level": geopolitical, "lat": 18.0, "lng": 39.0, "impact": ["Route disruption", "Increased operational exposure", "Possible route deviation", "Additional voyage time"], "mocked": True}] if uncontrolled["geopolitical"]["enabled"] else []),
        "port_alerts": ([{
            "name": baseline["bunkering"]["next_port"],
            "level": congestion,
            "lat": PORT_COORDINATES[baseline["bunkering"]["next_port"]]["lat"],
            "lng": PORT_COORDINATES[baseline["bunkering"]["next_port"]]["lng"],
            "ship_positions": PORT_ANCHORAGES[baseline["bunkering"]["next_port"]],
            "impact": ["Increased waiting time", "Higher local bunker-price pressure", "Reduced berth availability"],
            "mocked": True,
        }] if uncontrolled["port_congestion"]["enabled"] else []),
    }
    tradeoffs = _tradeoffs(metrics, source["base_risk"]["level"], scenario_risk, bunker_type, sustainability)
    compliance = _compliance(bunker_type)

    return {
        "vessel_id": vessel_id,
        "vessel": source["vessel"],
        "controlled_factors": controlled,
        "uncontrolled_factors": uncontrolled,
        "baseline": baseline,
        "simulated": simulated,
        "scenario": simulated,
        "changes": metrics,
        "metrics": metrics,
        "map": {"baseline_route": baseline_points, "simulated_route": simulated_points, **alerts, "prototype": True},
        "route": {"origin": origin, "bunkering_port": baseline["bunkering"]["next_port"], "scenario_bunkering_port": alternative_port, "destination": destination},
        "tradeoffs": tradeoffs,
        "compliance": compliance,
        "risk": {"baseline": source["base_risk"]["level"], "scenario": scenario_risk, "score": round(score, 2), "reasons": reasons, "method": "Transparent prototype rule-based score; not PIL internal methodology."},
        "decision_support": {
            "summary": "The simulated route applies only the external factors selected by the planner." if external_active else "No uncontrolled factors were selected; the suggested route remains aligned with the initial route.",
            "planner_note": "Review the cost, time, fuel, sustainability and risk trade-offs before making an operational decision.",
        },
        "assumptions": {
            "cargo": "Consumption changes by 2% for each 10% variance from a 7-tonne-per-TEU reference load, capped at -10%/+12%.",
            "distance": "Great-circle waypoint estimate; not approved navigational routing.",
            "operational_cost": "$25,000 per voyage day for prototype comparison.",
            "alerts": "Weather, congestion and geopolitical overlays are simulated unless identified as live API data.",
        },
    }


def build_portfolio_snapshot() -> dict[str, Any]:
    vessels = load_vessels()
    rows = []
    for vessel in vessels:
        context = build_voyage_context(vessel)
        rows.append({
            "vessel_id": vessel["vessel_id"],
            "vessel_name": vessel["vessel_name"],
            "route": f'{vessel["origin"]} -> {vessel["destination"]}',
            "risk": vessel["risk_level"],
            "risk_level": vessel["risk_level"],
            "reserve_margin_tonnes": context["fuel_status"]["reserve_margin_tonnes"],
            "projected_bunker_cost": context["bunkering"]["projected_cost"],
            "bunker_cost": context["bunkering"]["projected_cost"],
            "next_bunkering_port": context["bunkering"]["next_port"],
            "estimated_emissions_tco2e": context["sustainability"]["estimated_emissions_tco2e"],
            "emissions": context["sustainability"]["estimated_emissions_tco2e"],
        })

    risk_counts = {
        level: sum(row["risk"] == level for row in rows)
        for level in ("High", "Medium", "Low")
    }
    high_risk = [row for row in rows if row["risk"] == "High"]
    highest_cost = sorted(
        rows,
        key=lambda row: row["projected_bunker_cost"],
        reverse=True,
    )[:3]
    lowest_reserves = sorted(
        rows,
        key=lambda row: row["reserve_margin_tonnes"],
    )[:3]

    return {
        "fleet_size": len(rows),
        "count": len(rows),
        "high_risk_vessels": high_risk,
        "total_projected_bunker_cost": round(
            sum(row["projected_bunker_cost"] for row in rows),
            2,
        ),
        "total_emissions_tco2e": round(
            sum(row["estimated_emissions_tco2e"] for row in rows),
            1,
        ),
        "risk_counts": risk_counts,
        "highest_cost_exposure": highest_cost,
        "lowest_reserves": lowest_reserves,
        "vessels": rows,
        "prototype": True,
    }
