"""Tests for external API normalisation without making network requests."""

import os
import unittest
from unittest.mock import patch

from app.services.external_apis import get_gemini_explanation, get_news


class ExternalAPITests(unittest.TestCase):
    @patch.dict(os.environ, {"NEWS_API_KEY": "test-key"})
    @patch("app.services.external_apis._request")
    def test_news_only_returns_route_relevant_maritime_disruptions(self, request):
        request.return_value = {
            "totalResults": 3,
            "articles": [
                {"title": "Singapore port congestion delays container vessels", "description": "Shipping queues increased.", "url": "https://example.com/1", "publishedAt": "2026-08-10T00:00:00Z", "source": {"name": "Maritime Test"}},
                {"title": "Singapore restaurant guide", "description": "New dining venues open.", "url": "https://example.com/2", "publishedAt": "2026-08-11T00:00:00Z", "source": {"name": "Travel Test"}},
                {"title": "Port closure delays shipping", "description": "A distant terminal is affected.", "url": "https://example.com/3", "publishedAt": "2026-08-11T00:00:00Z", "source": {"name": "Other Test"}},
            ],
        }
        result = get_news('("Singapore") AND shipping AND disruption', route_terms=["Singapore"])
        self.assertTrue(result["available"])
        self.assertEqual(result["total_results"], 1)
        self.assertEqual(result["articles"][0]["source"], "Maritime Test")
        self.assertTrue(result["articles"][0]["relevance_score"] >= 60)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-3.6-flash"})
    @patch("app.services.external_apis._request")
    def test_gemini_interactions_response_is_normalised(self, request):
        request.return_value = {
            "steps": [{
                "type": "model_output",
                "content": [{"type": "text", "text": '{"what_changed":"Time increased","cost_drivers":[],"fuel_drivers":[],"risk_drivers":[],"sustainability_tradeoffs":[],"planner_considerations":["Review trade-offs"]}'}],
            }]
        }
        result = get_gemini_explanation({"changes": {"voyage_time": {"difference": 1.2}}})
        self.assertTrue(result["available"])
        self.assertEqual(result["model"], "gemini-3.6-flash")
        self.assertEqual(result["analysis"]["what_changed"], "Time increased")


if __name__ == "__main__":
    unittest.main()
