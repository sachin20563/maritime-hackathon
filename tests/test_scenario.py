"""Regression checks for Scenario Analysis and the Person 1 handoff contract."""

import unittest
from unittest.mock import patch

from app import create_app
from app.fleet_dashboard import load_vessels


class ScenarioAnalysisTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.vessel_id = "PIL-KOTA-EAGLE"

    def test_voyage_context_contract_is_unchanged(self):
        response = self.client.get(f"/api/vessels/{self.vessel_id}/voyage-context")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.get_json()),
            {"vessel", "voyage", "fuel_status", "bunkering", "sustainability", "base_risk"},
        )

    def test_uncontrolled_factors_are_optional(self):
        response = self.client.post(
            f"/api/vessels/{self.vessel_id}/scenario",
            json={"controlled_factors": {"bunker_type": "LNG"}, "uncontrolled_factors": {}},
        )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue(all(not factor["enabled"] for factor in result["uncontrolled_factors"].values()))
        self.assertEqual(result["map"]["baseline_route"], result["map"]["simulated_route"])

    def test_selected_factors_change_outputs_without_mutating_baseline_api(self):
        original = self.client.get(f"/api/vessels/{self.vessel_id}/voyage-context").get_json()
        response = self.client.post(
            f"/api/vessels/{self.vessel_id}/scenario",
            json={
                "controlled_factors": {
                    "fuel_supply": "Moderate",
                    "bunker_type": "LNG",
                    "cargo_weight_tonnes": 98_000,
                    "consider_sustainability": True,
                },
                "uncontrolled_factors": {
                    "weather": {"enabled": True, "severity": "Severe"},
                    "port_congestion": {"enabled": True, "level": "High"},
                    "geopolitical": {"enabled": True, "risk_level": "High"},
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertNotEqual(result["map"]["baseline_route"], result["map"]["simulated_route"])
        self.assertGreater(len(result["map"]["baseline_route"]), 6)
        self.assertTrue(any("Indian Ocean" in point["name"] for point in result["map"]["baseline_route"]))
        self.assertEqual(result["map"]["geopolitical_alerts"][0]["region"], "Red Sea")
        self.assertEqual(result["map"]["port_alerts"][0]["level"], "High")
        self.assertIn("Increased waiting time", result["map"]["port_alerts"][0]["impact"])
        self.assertEqual(len(result["map"]["port_alerts"][0]["ship_positions"]), 13)
        self.assertGreater(result["changes"]["voyage_time"]["difference"], 0)
        self.assertIn("compliance", result)
        self.assertEqual(original, self.client.get(f"/api/vessels/{self.vessel_id}/voyage-context").get_json())

    def test_impossible_fuel_falls_back_to_vessel_plan(self):
        response = self.client.post(
            f"/api/vessels/{self.vessel_id}/scenario",
            json={"controlled_factors": {"bunker_type": "Hydrogen"}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["controlled_factors"]["bunker_type"], "LNG")

    def test_all_vessel_pages_render(self):
        for vessel in load_vessels():
            with self.subTest(vessel=vessel["vessel_id"]):
                self.assertEqual(self.client.get(f'/vessels/{vessel["vessel_id"]}').status_code, 200)
                self.assertEqual(self.client.get(f'/vessels/{vessel["vessel_id"]}/scenario').status_code, 200)

    def test_portfolio_contract_supports_insights_page(self):
        response = self.client.get("/api/portfolio")
        self.assertEqual(response.status_code, 200)
        portfolio = response.get_json()
        expected = {
            "fleet_size", "high_risk_vessels", "total_projected_bunker_cost",
            "total_emissions_tco2e", "risk_counts", "highest_cost_exposure",
            "lowest_reserves", "vessels",
        }
        self.assertTrue(expected.issubset(portfolio))
        self.assertEqual(portfolio["fleet_size"], len(portfolio["vessels"]))
        self.assertEqual(sum(portfolio["risk_counts"].values()), portfolio["fleet_size"])
        required_row_fields = {
            "vessel_id", "vessel_name", "route", "risk",
            "reserve_margin_tonnes", "projected_bunker_cost", "next_bunkering_port",
        }
        self.assertTrue(required_row_fields.issubset(portfolio["vessels"][0]))

    @patch("app.scenario_routes.get_news")
    @patch("app.scenario_routes.get_oil_price")
    def test_live_intelligence_uses_prototype_weather_without_schedule(self, oil, news):
        oil.return_value = {"available": False, "error": "test"}
        news.return_value = {"available": True, "articles": [], "total_results": 0}
        response = self.client.get(f"/api/vessels/{self.vessel_id}/live-intelligence")
        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertNotIn("schedule", result)
        self.assertTrue(result["weather"]["mocked"])
        self.assertEqual(result["weather_severity"]["level"], "Moderate")


if __name__ == "__main__":
    unittest.main()
