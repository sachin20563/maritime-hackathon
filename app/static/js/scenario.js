(() => {
  const cfg = window.SCENARIO_CONFIG;
  let latestScenario = null;
  let map = null;
  let routeLayer = null;

  const $ = (id) => document.getElementById(id);

  function money(v) {
    return "$" + Number(v || 0).toLocaleString(undefined, {maximumFractionDigits: 0});
  }

  function number(v, suffix = "") {
    return Number(v || 0).toLocaleString(undefined, {maximumFractionDigits: 1}) + suffix;
  }

  function signed(v, suffix = "") {
    const n = Number(v || 0);
    return (n >= 0 ? "+" : "") + n.toLocaleString(undefined, {maximumFractionDigits: 1}) + suffix;
  }

  function initMap() {
    map = L.map("scenario-map").setView([1.2644, 103.82], 4);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap contributors"
    }).addTo(map);
  }

  function drawRoute(route) {
    if (!map || !route) return;
    if (routeLayer) routeLayer.clearLayers();

    const layer = L.layerGroup().addTo(map);
    routeLayer = layer;

    const points = [
      ["Origin", route.coordinates.origin],
      ["Bunker", route.coordinates.bunkering],
      ["Scenario bunker", route.coordinates.scenario_bunkering],
      ["Destination", route.coordinates.destination],
    ].filter(([, p]) => p && typeof p.lat === "number" && typeof p.lng === "number");

    const latlngs = points.map(([, p]) => [p.lat, p.lng]);

    points.forEach(([label, p]) => {
      L.marker([p.lat, p.lng]).bindPopup(`<strong>${label}</strong>`).addTo(layer);
    });

    if (latlngs.length >= 2) {
      L.polyline(latlngs, {weight: 4}).addTo(layer);
      map.fitBounds(latlngs, {padding: [30, 30]});
    }
  }

  function renderComparison(result) {
    const m = result.metrics;
    const rows = [
      ["Bunker price", money(m.bunker_price.baseline) + "/t", money(m.bunker_price.scenario) + "/t", signed(m.bunker_price.scenario - m.bunker_price.baseline, "/t")],
      ["Projected bunker cost", money(m.bunker_cost.baseline), money(m.bunker_cost.scenario), signed(m.bunker_cost.scenario - m.bunker_cost.baseline)],
      ["Fuel consumption", number(m.fuel_consumption.baseline, " t"), number(m.fuel_consumption.scenario, " t"), signed(m.fuel_consumption.scenario - m.fuel_consumption.baseline, " t")],
      ["Arrival fuel", number(m.arrival_fuel.baseline, " t"), number(m.arrival_fuel.scenario, " t"), signed(m.arrival_fuel.scenario - m.arrival_fuel.baseline, " t")],
      ["Reserve margin", number(m.reserve_margin.baseline, " t"), number(m.reserve_margin.scenario, " t"), signed(m.reserve_margin.scenario - m.reserve_margin.baseline, " t")],
      ["Voyage duration", number(m.voyage_duration.baseline, " days"), number(m.voyage_duration.scenario, " days"), signed(m.voyage_duration.scenario - m.voyage_duration.baseline, " days")],
      ["Emissions", number(m.emissions.baseline, " tCO₂e"), number(m.emissions.scenario, " tCO₂e"), signed(m.emissions.scenario - m.emissions.baseline, " tCO₂e")],
      ["Bunker requirement", number(m.bunker_quantity.baseline, " t"), number(m.bunker_quantity.scenario, " t"), signed(m.bunker_quantity.scenario - m.bunker_quantity.baseline, " t")],
    ];

    $("comparison-body").innerHTML = rows.map(r =>
      `<tr><td><strong>${r[0]}</strong></td><td>${r[1]}</td><td>${r[2]}</td><td>${r[3]}</td></tr>`
    ).join("");

    $("risk-badge").textContent = `${result.risk.scenario} risk`;
    $("risk-badge").className = "badge " + (
      result.risk.scenario === "High" ? "text-bg-danger" :
      result.risk.scenario === "Medium" ? "text-bg-warning" : "text-bg-success"
    );

    $("risk-title").textContent = `${result.risk.scenario} · score ${result.risk.score}`;
    $("risk-method").textContent = result.risk.method;
    $("risk-reasons").innerHTML = (result.risk.reasons.length
      ? result.risk.reasons
      : ["No additional risk drivers detected."]
    ).map(x => `<li>${x}</li>`).join("");

    drawRoute(result.route);
    $("ai-button").disabled = false;
    $("ai-output").textContent = "Scenario calculated. Ask Gemini to explain the trade-offs.";
  }

  async function loadIntelligence() {
    try {
      const res = await fetch(cfg.intelligenceUrl);
      const data = await res.json();

      if (data.weather && data.weather.available) {
        $("weather-value").textContent = data.weather_severity.level;
        $("weather-detail").textContent =
          `${data.weather.description || "Current conditions"} · wind ${data.weather.wind_speed_mps ?? "—"} m/s`;
      } else {
        $("weather-value").textContent = "Unavailable";
        $("weather-detail").textContent = data.weather?.error || "Configure OpenWeather";
      }

      if (data.oil && data.oil.available) {
        $("oil-value").textContent = data.oil.formatted || `$${data.oil.price}`;
        $("oil-detail").textContent = "Live Brent market signal";
      } else {
        $("oil-value").textContent = "Unavailable";
        $("oil-detail").textContent = data.oil?.error || "Configure OilPriceAPI";
      }

      if (data.schedule && data.schedule.available) {
        const schedules = data.schedule.data?.schedules || [];
        $("schedule-value").textContent = `${schedules.length} option${schedules.length === 1 ? "" : "s"}`;
        $("schedule-detail").textContent = `Live ${data.schedule.mode || "schedule"} schedule`;
      } else {
        $("schedule-value").textContent = "Unavailable";
        $("schedule-detail").textContent = data.schedule?.error || "Configure Schedule API";
      }

      if (data.news && data.news.available) {
        $("news-value").textContent = `${data.news.total_results ?? data.news.articles.length} signals`;
        $("news-detail").textContent = "Latest route / disruption articles";
      } else {
        $("schedule-value").textContent = "Unavailable";
      $("news-value").textContent = "Unavailable";
        $("news-detail").textContent = data.news?.error || "Configure NewsAPI";
      }
    } catch (e) {
      $("weather-value").textContent = "Unavailable";
      $("oil-value").textContent = "Unavailable";
      $("schedule-value").textContent = "Unavailable";
      $("news-value").textContent = "Unavailable";
    }
  }

  async function runScenario(event) {
    event.preventDefault();
    const form = new FormData(event.target);
    const payload = Object.fromEntries(form.entries());

    try {
      const response = await fetch(cfg.scenarioUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });

      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Scenario failed");

      latestScenario = result;
      renderComparison(result);
    } catch (error) {
      $("ai-output").textContent = error.message;
    }
  }

  async function explainWithAI() {
    if (!latestScenario) return;

    $("ai-output").innerHTML = "<div class='spinner-border spinner-border-sm'></div> Gemini is explaining the scenario…";

    const payload = {
      vessel: latestScenario.vessel,
      scenario_inputs: latestScenario.inputs,
      baseline: latestScenario.baseline,
      scenario: latestScenario.scenario,
      metrics: latestScenario.metrics,
      risk: latestScenario.risk
    };

    try {
      const response = await fetch(cfg.aiUrl, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
      });

      const result = await response.json();
      if (!response.ok || !result.available) throw new Error(result.error || "AI unavailable");

      const a = result.analysis;
      $("ai-output").innerHTML = `
        <div class="mb-3"><strong>What changed?</strong><p class="mb-0">${a.what_changed || "—"}</p></div>
        <div class="mb-3"><strong>Cost drivers</strong><p class="mb-0">${Array.isArray(a.cost_drivers) ? a.cost_drivers.join("<br>") : (a.cost_drivers || "—")}</p></div>
        <div class="mb-3"><strong>Fuel drivers</strong><p class="mb-0">${Array.isArray(a.fuel_drivers) ? a.fuel_drivers.join("<br>") : (a.fuel_drivers || "—")}</p></div>
        <div class="mb-3"><strong>Risk drivers</strong><p class="mb-0">${Array.isArray(a.risk_drivers) ? a.risk_drivers.join("<br>") : (a.risk_drivers || "—")}</p></div>
        <div class="mb-3"><strong>Sustainability trade-offs</strong><p class="mb-0">${Array.isArray(a.sustainability_tradeoffs) ? a.sustainability_tradeoffs.join("<br>") : (a.sustainability_tradeoffs || "—")}</p></div>
        <div><strong>Planner considerations</strong><p class="mb-0">${Array.isArray(a.planner_considerations) ? a.planner_considerations.join("<br>") : (a.planner_considerations || "—")}</p></div>
        <hr><small class="text-muted">AI provides explanation only. Final operational decisions remain with the planner.</small>
      `;
    } catch (error) {
      $("ai-output").textContent = error.message;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    loadIntelligence();
    $("scenario-form").addEventListener("submit", runScenario);
    $("ai-button").addEventListener("click", explainWithAI);
  });
})();