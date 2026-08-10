import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get(
        "SECRET_KEY",
        "dev-only-change-me"
    )

    JSON_SORT_KEYS = False

    OPENWEATHER_API_KEY = os.environ.get(
        "OPENWEATHER_API_KEY"
    )

    NEWS_API_KEY = os.environ.get(
        "NEWS_API_KEY"
    )

    GEMINI_API_KEY = os.environ.get(
        "GEMINI_API_KEY"
    )

    OILPRICEAPI_KEY = os.environ.get(
        "OILPRICEAPI_KEY"
    )

    SCHEDULE_API_BASE_URL = os.environ.get(
        "SCHEDULE_API_BASE_URL",
        "http://localhost:8000"
    )