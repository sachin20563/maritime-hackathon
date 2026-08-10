"""
External API adapters for the Maritime Decision Support Platform.

Supported integrations:
1. OpenWeather
2. OilPriceAPI
3. NewsAPI
4. Schedule API
5. Google Gemini

The module is deliberately defensive:
- Missing API keys do not crash Flask.
- API failures return a structured "available: False" response.
- Different API response shapes are normalised where possible.
- Gemini is used only as an explainability layer.
- No API is allowed to make the final operational decision.
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------------------------

# Make this module work even if it is imported outside the Flask application.
load_dotenv()


REQUEST_TIMEOUT = int(os.getenv("API_TIMEOUT_SECONDS", "12"))


class ExternalAPIError(RuntimeError):
    """Raised when an external API cannot be reached or returns an error."""


# ---------------------------------------------------------------------------
# GENERIC HTTP HELPER
# ---------------------------------------------------------------------------

def _request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:

    try:
        response = requests.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            json=json_body,
            timeout=REQUEST_TIMEOUT,
        )

    except requests.Timeout as exc:
        raise ExternalAPIError(
            f"Request timed out after {REQUEST_TIMEOUT}s"
        ) from exc

    except requests.ConnectionError as exc:
        raise ExternalAPIError(
            f"Could not connect to external API: {url}"
        ) from exc

    except requests.RequestException as exc:
        raise ExternalAPIError(
            f"External API request failed: {exc}"
        ) from exc

    # Give a useful error instead of just "400 Bad Request".
    if not response.ok:
        try:
            error_body = response.json()
        except ValueError:
            error_body = response.text[:500]

        raise ExternalAPIError(
            f"API returned HTTP {response.status_code}: {error_body}"
        )

    try:
        return response.json()

    except ValueError as exc:
        raise ExternalAPIError(
            "External API returned a non-JSON response"
        ) from exc


# ---------------------------------------------------------------------------
# ENVIRONMENT VARIABLE HELPER
# ---------------------------------------------------------------------------

def _env(*names: str) -> str | None:
    """
    Return the first configured environment variable.

    This allows the application to work with either the original names
    or slightly different names that may already exist in .env.
    """

    for name in names:
        value = os.getenv(name)

        if value:
            value = value.strip()

            if value and value.lower() not in {
                "replace-me",
                "your-api-key",
                "your_key_here",
                "none",
                "null",
            }:
                return value

    return None


# ===========================================================================
# 1. OPENWEATHER
# ===========================================================================

def get_weather(lat: float, lon: float) -> dict[str, Any]:
    """
    Retrieve current weather for a coordinate.

    Returns a normalised structure used by scenario.js.
    """

    key = _env(
        "OPENWEATHER_API_KEY",
        "OPENWEATHER_KEY",
        "WEATHER_API_KEY",
    )

    if not key:
        return {
            "available": False,
            "error": "OpenWeather API key is not configured",
            "source": "OpenWeather",
        }

    try:
        data = _request(
            "GET",
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat": lat,
                "lon": lon,
                "appid": key,
                "units": "metric",
            },
        )

    except ExternalAPIError as exc:
        return {
            "available": False,
            "error": str(exc),
            "source": "OpenWeather",
        }

    weather = (data.get("weather") or [{}])[0]
    main = data.get("main") or {}
    wind = data.get("wind") or {}
    rain = data.get("rain") or {}
    clouds = data.get("clouds") or {}
    sys_data = data.get("sys") or {}

    return {
        "available": True,

        "location": data.get("name"),

        "latitude": lat,
        "longitude": lon,

        "temperature_c": main.get("temp"),
        "feels_like_c": main.get("feels_like"),
        "temperature_min_c": main.get("temp_min"),
        "temperature_max_c": main.get("temp_max"),

        "pressure_hpa": main.get("pressure"),
        "humidity_pct": main.get("humidity"),

        "wind_speed_mps": wind.get("speed"),
        "wind_gust_mps": wind.get("gust"),
        "wind_direction_deg": wind.get("deg"),

        "weather": weather.get("main"),
        "description": weather.get("description"),

        "rain_1h_mm": rain.get("1h", 0),
        "rain_3h_mm": rain.get("3h", 0),

        "clouds_pct": clouds.get("all"),

        "sunrise": sys_data.get("sunrise"),
        "sunset": sys_data.get("sunset"),

        "observed_at": data.get("dt"),

        "source": "OpenWeather",
    }


def weather_severity(weather: dict[str, Any]) -> dict[str, Any]:
    """
    Convert weather data into a transparent risk signal.

    This is deliberately rule-based rather than AI-generated.
    """

    if not weather or not weather.get("available"):
        return {
            "level": "Unknown",
            "score": 0,
            "reasons": ["Live weather unavailable"],
        }

    wind = float(weather.get("wind_speed_mps") or 0)
    gust = float(weather.get("wind_gust_mps") or 0)
    rain = float(weather.get("rain_1h_mm") or 0)

    description = str(
        weather.get("description") or ""
    ).lower()

    score = 0
    reasons: list[str] = []

    # Wind
    if wind >= 17 or gust >= 22:
        score += 3
        reasons.append("Strong wind conditions")

    elif wind >= 12 or gust >= 16:
        score += 2
        reasons.append("Elevated wind conditions")

    elif wind >= 8:
        score += 1
        reasons.append("Moderate wind conditions")

    # Rain
    if rain >= 10:
        score += 2
        reasons.append("Heavy rainfall")

    elif rain >= 3:
        score += 1
        reasons.append("Rainfall detected")

    # Weather description
    severe_terms = (
        "storm",
        "thunder",
        "squall",
        "tropical",
        "hurricane",
        "typhoon",
    )

    if any(term in description for term in severe_terms):
        score += 3
        reasons.append("Severe weather description")

    if score >= 5:
        level = "Severe"

    elif score >= 3:
        level = "Moderate"

    elif score >= 1:
        level = "Mild"

    else:
        level = "None"

    return {
        "level": level,
        "score": score,
        "reasons": reasons,
    }


# ===========================================================================
# 2. OILPRICEAPI
# ===========================================================================

def get_oil_price() -> dict[str, Any]:
    """
    Retrieve the latest Brent crude price.

    OilPriceAPI is used as the live market signal.
    """

    key = _env(
        "OILPRICEAPI_KEY",
        "OIL_PRICE_API_KEY",
        "OIL_API_KEY",
    )

    if not key:
        return {
            "available": False,
            "error": "OilPriceAPI key is not configured",
            "source": "OilPriceAPI",
        }

    url = "https://api.oilpriceapi.com/v1/prices/latest"

    try:
        data = _request(
            "GET",
            url,
            params={
                "by_code": "BRENT_CRUDE_USD",
            },
            headers={
                "Authorization": f"Token {key}",
                "Accept": "application/json",
            },
        )

    except ExternalAPIError as exc:
        return {
            "available": False,
            "error": str(exc),
            "source": "OilPriceAPI",
        }

    payload = data.get("data", data)

    if not isinstance(payload, dict):
        payload = {}

    price = payload.get("price")

    formatted = payload.get("formatted")

    if formatted is None and price is not None:
        try:
            formatted = f"${float(price):,.2f}"
        except (TypeError, ValueError):
            formatted = str(price)

    return {
        "available": True,

        "code": payload.get(
            "code",
            "BRENT_CRUDE_USD",
        ),

        "price": price,

        "formatted": formatted,

        "created_at": payload.get("created_at"),

        "source": payload.get(
            "source",
            "OilPriceAPI",
        ),
    }


# ===========================================================================
# 3. NEWS API
# ===========================================================================

def get_news(
    query: str,
    page_size: int = 8,
) -> dict[str, Any]:
    """
    Retrieve recent maritime / port disruption news.

    NewsAPI is used as a disruption-intelligence signal.
    """

    key = _env(
        "NEWS_API_KEY",
        "NEWSAPI_KEY",
        "NEWS_API_TOKEN",
    )

    if not key:
        return {
            "available": False,
            "error": "NewsAPI key is not configured",
            "articles": [],
            "total_results": 0,
            "source": "NewsAPI",
        }

    page_size = max(
        1,
        min(int(page_size), 20),
    )

    try:
        data = _request(
            "GET",
            "https://newsapi.org/v2/everything",
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": page_size,
            },
            headers={
                "X-Api-Key": key,
                "Accept": "application/json",
            },
        )

    except ExternalAPIError as exc:
        return {
            "available": False,
            "error": str(exc),
            "articles": [],
            "total_results": 0,
            "source": "NewsAPI",
        }

    articles: list[dict[str, Any]] = []

    for article in data.get("articles", []):
        if not isinstance(article, dict):
            continue

        source = article.get("source") or {}

        articles.append(
            {
                "title": article.get("title"),
                "description": article.get("description"),
                "url": article.get("url"),
                "source": source.get("name"),
                "published_at": article.get("publishedAt"),
                "author": article.get("author"),
                "image_url": article.get("urlToImage"),
            }
        )

    return {
        "available": True,
        "total_results": data.get(
            "totalResults",
            len(articles),
        ),
        "articles": articles,
        "source": "NewsAPI",
    }


# ===========================================================================
# 4. SCHEDULE API
# ===========================================================================

"""
The schedule integration supports the API structure used by the project.

Supported logical operations:

    GET /schedules/port-to-port?from=USNYC&to=NLRTM

    GET /schedules/vessel?imo=9234567

    GET /schedules/port?code=SGSIN

The actual host is configurable using:

    SCHEDULE_API_BASE_URL

For example:

    SCHEDULE_API_BASE_URL=http://localhost:8000

or whatever schedule API host your team is using.
"""


SCHEDULE_BASE_URL = (
    _env(
        "SCHEDULE_API_BASE_URL",
        "SCHEDULE_API_URL",
    )
    or ""
).rstrip("/")


def _schedule_headers() -> dict[str, str]:
    """
    Build schedule API authentication headers.

    Supports both common API-key header names.
    """

    key = _env(
        "SCHEDULE_API_KEY",
        "SCHEDULE_API_TOKEN",
    )

    headers = {
        "Accept": "application/json",
    }

    if key:
        headers["X-API-KEY"] = key
        headers["Authorization"] = f"Bearer {key}"

    return headers


def _schedule_url(path: str) -> str:
    if not SCHEDULE_BASE_URL:
        raise ExternalAPIError(
            "SCHEDULE_API_BASE_URL is not configured"
        )

    return f"{SCHEDULE_BASE_URL}/{path.lstrip('/')}"


def get_schedule_port_to_port(
    origin: str,
    destination: str,
) -> dict[str, Any]:
    """
    Get schedules between two ports.

    Expected endpoint:

        /schedules/port-to-port?from=USNYC&to=NLRTM
    """

    if not origin or not destination:
        return {
            "available": False,
            "error": "Origin and destination UNLOCODE are required",
        }

    key = _env(
        "SCHEDULE_API_KEY",
        "SCHEDULE_API_TOKEN",
    )

    if not key:
        return {
            "available": False,
            "error": "Schedule API key is not configured",
        }

    try:
        data = _request(
            "GET",
            _schedule_url(
                "/schedules/port-to-port"
            ),
            params={
                "from": origin,
                "to": destination,
            },
            headers=_schedule_headers(),
        )

        return {
            "available": True,
            "mode": "port-to-port",
            "data": data,
            "source": "Schedule API",
        }

    except ExternalAPIError as exc:
        return {
            "available": False,
            "mode": "port-to-port",
            "error": str(exc),
            "source": "Schedule API",
        }


def get_schedule_by_vessel(
    imo: str,
) -> dict[str, Any]:
    """
    Get schedules for a specific vessel.

    Expected endpoint:

        /schedules/vessel?imo=9234567
    """

    key = _env(
        "SCHEDULE_API_KEY",
        "SCHEDULE_API_TOKEN",
    )

    if not key:
        return {
            "available": False,
            "error": "Schedule API key is not configured",
        }

    if not imo:
        return {
            "available": False,
            "error": "Vessel IMO is not available",
        }

    try:
        data = _request(
            "GET",
            _schedule_url(
                "/schedules/vessel"
            ),
            params={
                "imo": str(imo),
            },
            headers=_schedule_headers(),
        )

        return {
            "available": True,
            "mode": "vessel",
            "data": data,
            "source": "Schedule API",
        }

    except (ExternalAPIError, ValueError) as exc:
        return {
            "available": False,
            "mode": "vessel",
            "error": str(exc),
            "source": "Schedule API",
        }


def get_schedule_by_port(
    locode: str,
) -> dict[str, Any]:
    """
    Get schedules involving a port.

    Expected endpoint:

        /schedules/port?code=SGSIN
    """

    key = _env(
        "SCHEDULE_API_KEY",
        "SCHEDULE_API_TOKEN",
    )

    if not key:
        return {
            "available": False,
            "error": "Schedule API key is not configured",
        }

    if not locode:
        return {
            "available": False,
            "error": "Port UNLOCODE is not available",
        }

    try:
        data = _request(
            "GET",
            _schedule_url(
                "/schedules/port"
            ),
            params={
                "code": locode,
            },
            headers=_schedule_headers(),
        )

        return {
            "available": True,
            "mode": "port",
            "data": data,
            "source": "Schedule API",
        }

    except ExternalAPIError as exc:
        return {
            "available": False,
            "mode": "port",
            "error": str(exc),
            "source": "Schedule API",
        }


def get_schedule_context(
    vessel: dict[str, Any],
    origin_code: str | None,
    destination_code: str | None,
    bunker_code: str | None,
) -> dict[str, Any]:
    """
    Get the most relevant schedule information.

    Priority:

    1. Vessel schedule if IMO exists
    2. Port-to-port schedule
    3. Bunkering port schedule
    4. Structured unavailable response

    This prevents one failed schedule lookup from breaking
    the entire Scenario Analysis page.
    """

    errors: list[str] = []

    # -------------------------------------------------------
    # 1. Vessel schedule
    # -------------------------------------------------------

    imo = vessel.get("imo")

    if imo:
        result = get_schedule_by_vessel(
            str(imo)
        )

        if result.get("available"):
            return result

        if result.get("error"):
            errors.append(
                f"Vessel schedule: {result['error']}"
            )

    else:
        errors.append(
            "Vessel schedule: no IMO available"
        )

    # -------------------------------------------------------
    # 2. Port-to-port
    # -------------------------------------------------------

    if origin_code and destination_code:

        result = get_schedule_port_to_port(
            origin_code,
            destination_code,
        )

        if result.get("available"):
            result["fallback_reason"] = (
                errors[-1] if errors else None
            )

            return result

        if result.get("error"):
            errors.append(
                f"Port-to-port schedule: {result['error']}"
            )

    else:
        errors.append(
            "Port-to-port schedule: origin/destination "
            "UNLOCODE not mapped"
        )

    # -------------------------------------------------------
    # 3. Bunkering port
    # -------------------------------------------------------

    if bunker_code:

        result = get_schedule_by_port(
            bunker_code
        )

        if result.get("available"):
            result["fallback_reason"] = (
                errors[-1] if errors else None
            )

            return result

        if result.get("error"):
            errors.append(
                f"Bunker-port schedule: {result['error']}"
            )

    else:
        errors.append(
            "Bunker-port schedule: UNLOCODE not mapped"
        )

    # -------------------------------------------------------
    # 4. Nothing available
    # -------------------------------------------------------

    return {
        "available": False,
        "mode": "none",
        "error": (
            errors[-1]
            if errors
            else "Schedule API unavailable"
        ),
        "fallback_reason": (
            errors[0]
            if errors
            else None
        ),
        "source": "Schedule API",
    }


# ===========================================================================
# 5. GEMINI
# ===========================================================================

def get_gemini_explanation(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Send structured scenario/fleet information to Gemini.

    Gemini is explicitly restricted to:
    - explaining
    - comparing
    - summarising
    - identifying trade-offs

    Gemini must NOT:
    - invent calculations
    - invent live data
    - make the final operational decision
    """

    key = _env(
        "GEMINI_API_KEY",
        "GOOGLE_GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )

    if not key:
        return {
            "available": False,
            "error": "Gemini API key is not configured",
        }

    model = os.getenv(
        "GEMINI_MODEL",
        "gemini-2.5-flash",
    ).strip()

    url = (
        "https://generativelanguage.googleapis.com"
        f"/v1beta/models/{model}:generateContent"
    )

    system_instruction = """
You are the explainability layer of a maritime
bunkering and voyage decision-support platform.

You are NOT the final decision maker.

Your job is to explain structured information
provided by the platform.

STRICT RULES:

1. Only use values contained in the supplied payload.
2. Never invent prices, distances, fuel quantities,
   delays, weather conditions or risk values.
3. Do not create calculations that are not already
   supplied by the platform.
4. Clearly distinguish live API information from
   deterministic prototype assumptions.
5. Explain trade-offs rather than issuing commands.
6. The planner remains responsible for the final decision.
7. If information is unavailable, explicitly say so.
8. Do not claim that an option is definitely optimal.

Return valid JSON with exactly these keys:

what_changed
cost_drivers
fuel_drivers
risk_drivers
sustainability_tradeoffs
planner_considerations

Each value can be:
- a short string
- or an array of short strings.
"""

    try:
        payload_text = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    except (TypeError, ValueError) as exc:
        raise ExternalAPIError(
            f"Could not serialise Gemini payload: {exc}"
        ) from exc

    body = {
        "system_instruction": {
            "parts": [
                {
                    "text": system_instruction
                }
            ]
        },

        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Explain the following structured "
                            "maritime scenario data:\n\n"
                            + payload_text
                        )
                    }
                ],
            }
        ],

        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    try:
        data = _request(
            "POST",
            url,
            params={
                "key": key,
            },
            headers={
                "Content-Type": "application/json",
            },
            json_body=body,
        )

    except ExternalAPIError as exc:
        return {
            "available": False,
            "error": str(exc),
            "source": "Gemini",
        }

    # -------------------------------------------------------
    # Gemini response parsing
    # -------------------------------------------------------

    try:

        candidates = data.get(
            "candidates",
            [],
        )

        if not candidates:
            raise ValueError(
                "Gemini returned no candidates"
            )

        content = candidates[0].get(
            "content",
            {},
        )

        parts = content.get(
            "parts",
            [],
        )

        if not parts:
            raise ValueError(
                "Gemini returned no content parts"
            )

        text = parts[0].get(
            "text",
            "",
        )

        if not text:
            raise ValueError(
                "Gemini returned empty text"
            )

        # Gemini may occasionally wrap JSON in markdown.
        cleaned = text.strip()

        if cleaned.startswith("```json"):
            cleaned = cleaned[
                len("```json"):
            ].strip()

        if cleaned.endswith("```"):
            cleaned = cleaned[
                :-3
            ].strip()

        parsed = json.loads(cleaned)

    except (
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:

        raise ExternalAPIError(
            "Gemini returned an unexpected response format"
        ) from exc

    # -------------------------------------------------------
    # Ensure expected keys always exist
    # -------------------------------------------------------

    expected_keys = [
        "what_changed",
        "cost_drivers",
        "fuel_drivers",
        "risk_drivers",
        "sustainability_tradeoffs",
        "planner_considerations",
    ]

    normalised = {}

    for key_name in expected_keys:
        normalised[key_name] = parsed.get(
            key_name,
            [],
        )

    return {
        "available": True,
        "analysis": normalised,
        "source": "Gemini",
        "model": model,
    }


# ===========================================================================
# HEALTH / DEBUG HELPERS
# ===========================================================================

def get_api_status() -> dict[str, Any]:
    """
    Returns configuration status for all integrations.

    This does NOT make external API calls.

    Useful for:

        /api/integrations/status
    """

    return {
        "openweather": {
            "configured": bool(
                _env(
                    "OPENWEATHER_API_KEY",
                    "OPENWEATHER_KEY",
                    "WEATHER_API_KEY",
                )
            ),
        },

        "oilpriceapi": {
            "configured": bool(
                _env(
                    "OILPRICEAPI_KEY",
                    "OIL_PRICE_API_KEY",
                    "OIL_API_KEY",
                )
            ),
        },

        "newsapi": {
            "configured": bool(
                _env(
                    "NEWS_API_KEY",
                    "NEWSAPI_KEY",
                    "NEWS_API_TOKEN",
                )
            ),
        },

        "gemini": {
            "configured": bool(
                _env(
                    "GEMINI_API_KEY",
                    "GOOGLE_GEMINI_API_KEY",
                    "GOOGLE_API_KEY",
                )
            ),

            "model": os.getenv(
                "GEMINI_MODEL",
                "gemini-2.5-flash",
            ),
        },

        "schedule": {
            "configured": bool(
                _env(
                    "SCHEDULE_API_KEY",
                    "SCHEDULE_API_TOKEN",
                )
            ),

            "base_url_configured": bool(
                SCHEDULE_BASE_URL
            ),
        },
    }