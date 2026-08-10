"""External API adapters for the maritime decision-support prototype."""

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

# Explicitly load .env from the project root.
# This prevents problems when Flask is launched from VS Code,
# PowerShell, or another working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=False)


# ============================================================
# CONFIG
# ============================================================

REQUEST_TIMEOUT = int(
    os.getenv("API_TIMEOUT_SECONDS", "15")
)


class ExternalAPIError(RuntimeError):
    """Raised when an external API cannot be reached or returns an error."""


def _env(*names: str) -> str | None:
    """
    Return the first configured environment variable.

    Supports multiple names so the application remains tolerant
    of slightly different .env naming conventions.
    """

    for name in names:

        value = os.getenv(name)

        if value is not None:

            value = value.strip()

            # Remove accidental surrounding quotes.
            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in ("'", '"')
            ):
                value = value[1:-1].strip()

            if value:
                return value

    return None


def _request(
    method: str,
    url: str,
    **kwargs
) -> dict[str, Any]:

    try:

        response = requests.request(
            method,
            url,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )

    except requests.RequestException as exc:

        raise ExternalAPIError(
            f"Network error while calling external API: {exc}"
        ) from exc


    # Try to extract the API's actual error message.
    try:
        body = response.json()
    except ValueError:
        body = None


    if not response.ok:

        if isinstance(body, dict):

            message = (
                body.get("message")
                or body.get("error")
                or body.get("detail")
            )

            if isinstance(body.get("error"), dict):

                message = (
                    body["error"].get("message")
                    or body["error"].get("status")
                    or message
                )

        else:

            message = None


        if not message:

            message = response.text[:500]


        raise ExternalAPIError(
            f"API returned HTTP {response.status_code}: {message}"
        )


    if not isinstance(body, dict):

        raise ExternalAPIError(
            "API returned an unexpected response format."
        )


    return body


# ============================================================
# OPENWEATHER
# ============================================================

def get_weather(
    lat: float,
    lon: float
) -> dict[str, Any]:

    key = _env(
        "OPENWEATHER_API_KEY",
        "OPENWEATHER_KEY",
        "OPENWEATHER"
    )

    if not key:

        return {
            "available": False,
            "error": (
                "OpenWeather API key is not configured. "
                "Expected OPENWEATHER_API_KEY in .env"
            )
        }


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


    weather_list = data.get("weather") or [{}]

    weather = weather_list[0]


    main = data.get("main") or {}
    wind = data.get("wind") or {}
    rain = data.get("rain") or {}
    clouds = data.get("clouds") or {}


    return {

        "available": True,

        "temperature_c":
            main.get("temp"),

        "feels_like_c":
            main.get("feels_like"),

        "humidity_pct":
            main.get("humidity"),

        "pressure_hpa":
            main.get("pressure"),

        "wind_speed_mps":
            wind.get("speed"),

        "wind_gust_mps":
            wind.get("gust"),

        "wind_direction_deg":
            wind.get("deg"),

        "weather":
            weather.get("main"),

        "description":
            weather.get("description"),

        "weather_id":
            weather.get("id"),

        "icon":
            weather.get("icon"),

        "rain_1h_mm":
            rain.get("1h", 0),

        "clouds_pct":
            clouds.get("all"),

        "observed_at":
            data.get("dt"),

        "location":
            data.get("name"),

        "source":
            "OpenWeather",

    }


# ============================================================
# WEATHER RISK
# ============================================================

def weather_severity(
    weather: dict[str, Any]
) -> dict[str, Any]:

    if not weather.get("available"):

        return {
            "level": "Unknown",
            "score": 0,
            "reasons": [
                "Live weather unavailable"
            ],
        }


    wind = float(
        weather.get("wind_speed_mps") or 0
    )

    gust = float(
        weather.get("wind_gust_mps") or 0
    )

    rain = float(
        weather.get("rain_1h_mm") or 0
    )

    description = str(
        weather.get("description") or ""
    ).lower()


    score = 0

    reasons = []


    # Wind
    if wind >= 17 or gust >= 22:

        score += 3

        reasons.append(
            "Strong wind conditions"
        )

    elif wind >= 12 or gust >= 16:

        score += 2

        reasons.append(
            "Elevated wind conditions"
        )

    elif wind >= 8:

        score += 1

        reasons.append(
            "Moderate wind conditions"
        )


    # Rain
    if rain >= 10:

        score += 2

        reasons.append(
            "Heavy rainfall"
        )

    elif rain >= 3:

        score += 1

        reasons.append(
            "Rainfall present"
        )


    # Severe weather wording
    severe_words = (
        "storm",
        "thunder",
        "squall",
        "tropical",
        "hurricane",
        "typhoon",
    )

    if any(
        word in description
        for word in severe_words
    ):

        score += 3

        reasons.append(
            "Severe weather signal"
        )


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


# ============================================================
# OIL PRICE API
# ============================================================

def get_oil_price() -> dict[str, Any]:

    key = _env(
        "OILPRICEAPI_KEY",
        "OIL_PRICE_API_KEY",
        "OILPRICE_API_KEY"
    )

    if not key:

        return {

            "available": False,

            "error": (
                "OilPriceAPI key is not configured. "
                "Expected OILPRICEAPI_KEY in .env"
            )

        }


    data = _request(

        "GET",

        "https://api.oilpriceapi.com/v1/prices/latest",

        params={
            "by_code":
                "BRENT_CRUDE_USD"
        },

        headers={
            "Authorization":
                f"Token {key}"
        },

    )


    payload = data.get(
        "data",
        data
    )


    return {

        "available": True,

        "code":
            payload.get(
                "code",
                "BRENT_CRUDE_USD"
            ),

        "price":
            payload.get("price"),

        "formatted":
            payload.get("formatted"),

        "currency":
            payload.get(
                "currency",
                "USD"
            ),

        "created_at":
            payload.get("created_at"),

        "source":
            payload.get(
                "source",
                "OilPriceAPI"
            ),

    }


# ============================================================
# NEWS API
# ============================================================

def get_news(
    query: str,
    page_size: int = 8
) -> dict[str, Any]:

    key = _env(
        "NEWS_API_KEY",
        "NEWSAPI_API_KEY",
        "NEWSAPI_KEY"
    )

    if not key:

        return {

            "available": False,

            "error": (
                "NewsAPI key is not configured. "
                "Expected NEWS_API_KEY in .env"
            ),

            "articles": [],

        }


    # NewsAPI has a maximum query length.
    query = str(query)[:450]


    data = _request(

        "GET",

        "https://newsapi.org/v2/everything",

        params={

            "q": query,

            "language": "en",

            "sortBy": "publishedAt",

            "pageSize":
                max(
                    1,
                    min(
                        int(page_size),
                        20
                    )
                ),

        },

        headers={

            "X-Api-Key":
                key

        },

    )


    articles = []


    for article in (
        data.get("articles") or []
    ):

        source = (
            article.get("source")
            or {}
        )


        articles.append({

            "title":
                article.get("title"),

            "description":
                article.get(
                    "description"
                ),

            "url":
                article.get("url"),

            "source":
                source.get("name"),

            "published_at":
                article.get(
                    "publishedAt"
                ),

        })


    return {

        "available": True,

        "total_results":
            data.get(
                "totalResults",
                len(articles)
            ),

        "articles":
            articles,

        "source":
            "NewsAPI",

    }


# ============================================================
# GEMINI
# ============================================================

def get_gemini_explanation(
    payload: dict[str, Any]
) -> dict[str, Any]:

    key = _env(
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY"
    )

    if not key:

        return {

            "available": False,

            "error": (
                "Gemini API key is not configured. "
                "Expected GEMINI_API_KEY in .env"
            )

        }


    model = _env(
        "GEMINI_MODEL"
    ) or "gemini-2.5-flash"


    url = (
        "https://generativelanguage.googleapis.com/"
        f"v1beta/models/{model}:generateContent"
    )


    system_instruction = """
You are the explainability layer of a maritime
bunkering and voyage decision-support platform.

Your role is to EXPLAIN structured calculations.

You are NOT the decision maker.

STRICT RULES:

1. Only use values provided in the supplied structured data.
2. Never invent prices, fuel consumption, distances,
   delays, risks or emissions.
3. Do not recalculate or override deterministic backend
   calculations.
4. Explain why the baseline and scenario differ.
5. Clearly distinguish live API information from
   prototype assumptions.
6. The planner makes the final operational decision.
7. Keep the explanation concise and useful to a planner.

Return JSON with exactly these fields:

{
  "what_changed": "...",
  "cost_drivers": [],
  "fuel_drivers": [],
  "risk_drivers": [],
  "sustainability_tradeoffs": [],
  "planner_considerations": []
}
"""


    user_prompt = (
        "Explain the following structured maritime "
        "scenario data.\n\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=str
        )
    )


    body = {

        "system_instruction": {

            "parts": [

                {
                    "text":
                        system_instruction
                }

            ]

        },

        "contents": [

            {

                "role": "user",

                "parts": [

                    {
                        "text":
                            user_prompt
                    }

                ]

            }

        ],

        "generationConfig": {

            "temperature": 0.2,

            "maxOutputTokens": 1200,

            "responseMimeType":
                "application/json",

        },

    }


    try:

        data = _request(
            "POST",
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": key,
            },
            json=body,
        )

    except ExternalAPIError:

        # Re-raise so the Flask route can display
        # the actual API error.
        raise


    try:

        text = (
            data["candidates"][0]
            ["content"]["parts"][0]
            ["text"]
        )

    except (
        KeyError,
        IndexError,
        TypeError
    ) as exc:

        raise ExternalAPIError(
            "Gemini returned an unexpected response."
        ) from exc


    try:

        analysis = json.loads(text)

    except json.JSONDecodeError:

        # Gemini occasionally wraps JSON in markdown.
        cleaned = text.strip()

        if cleaned.startswith(
            "```json"
        ):

            cleaned = cleaned[
                7:
            ]

        elif cleaned.startswith(
            "```"
        ):

            cleaned = cleaned[
                3:
            ]


        if cleaned.endswith(
            "```"
        ):

            cleaned = cleaned[
                :-3
            ]


        try:

            analysis = json.loads(
                cleaned.strip()
            )

        except json.JSONDecodeError as exc:

            raise ExternalAPIError(
                "Gemini returned invalid JSON."
            ) from exc


    return {

        "available": True,

        "model":
            model,

        "analysis":
            analysis,

        "source":
            "Gemini",

    }


# ============================================================
# OPTIONAL SCHEDULE API
# ============================================================

SCHEDULE_BASE_URL = _env(
    "SCHEDULE_API_BASE_URL"
) or (
    "https://schedules.searates.com/api/v2"
)


def _schedule_headers():

    key = _env(
        "SCHEDULE_API_KEY"
    )

    if not key:

        return {}

    return {
        "X-API-KEY": key
    }


def get_schedule_by_points(
    origin: str,
    destination: str,
    cargo_type: str = "GC",
    weeks: int = 3
) -> dict[str, Any]:

    key = _env(
        "SCHEDULE_API_KEY"
    )

    if not key:

        return {

            "available": False,

            "error":
                "SCHEDULE_API_KEY is not configured",

        }


    return _request(

        "GET",

        f"{SCHEDULE_BASE_URL}/schedules/by-points",

        params={

            "cargo_type":
                cargo_type,

            "origin":
                origin,

            "destination":
                destination,

            "from_date":
                date.today().isoformat(),

            "weeks":
                max(
                    1,
                    min(
                        int(weeks),
                        6
                    )
                ),

            "sort":
                "DEP",

            "direct_only":
                "false",

            "multimodal":
                "true",

        },

        headers:
            _schedule_headers(),

    )


def get_schedule_by_vessel(
    imo: str,
    voyages: str | None = None
) -> dict[str, Any]:

    key = _env(
        "SCHEDULE_API_KEY"
    )

    if not key:

        return {

            "available": False,

            "error":
                "SCHEDULE_API_KEY is not configured",

        }


    params = {
        "imo": int(imo)
    }


    if voyages:

        params["voyages"] = voyages


    return _request(

        "GET",

        f"{SCHEDULE_BASE_URL}/schedules/by-vessel",

        params=params,

        headers=
            _schedule_headers(),

    )


def get_schedule_by_port(
    locode: str,
    weeks: int = 3
) -> dict[str, Any]:

    key = _env(
        "SCHEDULE_API_KEY"
    )

    if not key:

        return {

            "available": False,

            "error":
                "SCHEDULE_API_KEY is not configured",

        }


    return _request(

        "GET",

        f"{SCHEDULE_BASE_URL}/schedules/by-port",

        params={

            "locode":
                locode,

            "from_date":
                date.today().isoformat(),

            "weeks":
                max(
                    1,
                    min(
                        int(weeks),
                        6
                    )
                ),

        },

        headers=
            _schedule_headers(),

    )


def get_schedule_context(
    vessel: dict[str, Any],
    origin_code: str | None,
    destination_code: str | None,
    bunker_code: str | None
) -> dict[str, Any]:

    """
    Try schedule sources in this order:

    1. Vessel IMO
    2. Origin → destination
    3. Bunkering port

    This prevents the entire intelligence panel from failing
    just because one schedule lookup method is unavailable.
    """


    imo = (
        vessel.get("imo")
        or vessel.get("imo_number")
        or vessel.get("IMO")
    )


    errors = []


    # --------------------------------------------------------
    # VESSEL
    # --------------------------------------------------------

    if imo:

        try:

            result = get_schedule_by_vessel(
                str(imo)
            )

            return {
                "available": True,
                "mode": "vessel",
                **result,
            }

        except (
            ExternalAPIError
        ) as exc:

            errors.append(
                f"Vessel lookup: {exc}"
            )


    else:

        errors.append(
            "No IMO available for vessel lookup"
        )


    # --------------------------------------------------------
    # PORT TO PORT
    # --------------------------------------------------------

    if (
        origin_code
        and destination_code
    ):

        try:

            result = get_schedule_by_points(
                origin_code,
                destination_code
            )

            return {
                "available": True,
                "mode": "points",
                "fallback_reason":
                    errors,
                **result,
            }

        except (
            ExternalAPIError
        ) as exc:

            errors.append(
                f"Port-to-port lookup: {exc}"
            )


    # --------------------------------------------------------
    # BUNKER PORT
    # --------------------------------------------------------

    if bunker_code:

        try:

            result = get_schedule_by_port(
                bunker_code
            )

            return {
                "available": True,
                "mode": "port",
                "fallback_reason":
                    errors,
                **result,
            }

        except (
            ExternalAPIError
        ) as exc:

            errors.append(
                f"Port lookup: {exc}"
            )


    return {

        "available": False,

        "mode": "none",

        "error":
            errors[-1]
            if errors
            else "No schedule source available",

        "details":
            errors,

    }


# ============================================================
# API CONFIGURATION DIAGNOSTICS
# ============================================================

def get_api_status() -> dict[str, Any]:

    """
    Safe diagnostic function.

    IMPORTANT:
    This NEVER returns the actual API keys.
    It only tells us whether the application can see them.
    """

    return {

        "dotenv_file":
            str(ENV_FILE),

        "dotenv_exists":
            ENV_FILE.exists(),

        "openweather":
            bool(
                _env(
                    "OPENWEATHER_API_KEY",
                    "OPENWEATHER_KEY",
                    "OPENWEATHER"
                )
            ),

        "news":
            bool(
                _env(
                    "NEWS_API_KEY",
                    "NEWSAPI_API_KEY",
                    "NEWSAPI_KEY"
                )
            ),

        "oil":
            bool(
                _env(
                    "OILPRICEAPI_KEY",
                    "OIL_PRICE_API_KEY",
                    "OILPRICE_API_KEY"
                )
            ),

        "gemini":
            bool(
                _env(
                    "GEMINI_API_KEY",
                    "GOOGLE_API_KEY"
                )
            ),

        "schedule":
            bool(
                _env(
                    "SCHEDULE_API_KEY"
                )
            ),

        "gemini_model":
            _env(
                "GEMINI_MODEL"
            ) or "gemini-2.5-flash",

    }