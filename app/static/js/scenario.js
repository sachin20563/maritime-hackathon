(() => {
  "use strict";

  const cfg = window.SCENARIO_CONFIG || {};
  const $ = (id) => document.getElementById(id);
  let latestScenario = null;
  let latestLiveIntelligence = null;
  let map = null;
  let scenarioLayers = null;
  let geopoliticalControl = null;

  const escapeHTML = (value) => String(value ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  const setText = (id, value) => { if ($(id)) $(id).textContent = value ?? "—"; };
  const numeric = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const number = (value, suffix = "") => numeric(value) === null ? "—" : `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`;
  const money = (value) => numeric(value) === null ? "—" : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const signed = (value, suffix = "") => numeric(value) === null ? String(value ?? "—") : `${Number(value) >= 0 ? "+" : ""}${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}${suffix}`;
  const safeExternalURL = (value) => {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (error) { return null; }
  };
  const articleDate = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  };

  async function fetchJSON(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed with HTTP ${response.status}.`);
    return data;
  }

  function setButtonLoading(button, loading, loadingText = "Calculating…") {
    if (!button) return;
    if (loading) {
      button.dataset.original = button.innerHTML;
      button.disabled = true;
      button.textContent = loadingText;
    } else {
      button.disabled = false;
      if (button.dataset.original) button.innerHTML = button.dataset.original;
    }
  }

  function initMap() {
    if (!$('scenario-map') || typeof L === "undefined") return;
    map = L.map("scenario-map", { zoomControl: true, preferCanvas: true, minZoom: 2 }).setView([8, 102], 3);
    map.createPane("weatherPane");
    map.getPane("weatherPane").style.zIndex = 390;
    const fallback = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap contributors", maxZoom: 18, className: "fallback-map-tiles"
    }).addTo(map);
    const ocean = L.tileLayer("https://services.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}", {
      attribution: "Tiles © Esri · GEBCO · NOAA", maxZoom: 16, className: "ocean-map-tiles"
    }).addTo(map);
    L.tileLayer("https://services.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}", {
      attribution: "", maxZoom: 16, pane: "shadowPane"
    }).addTo(map);
    ocean.once("load", () => fallback.setOpacity(0));
    scenarioLayers = L.layerGroup().addTo(map);
    if (cfg.initialRoute?.length) drawMap({ baseline_route: cfg.initialRoute, simulated_route: cfg.initialRoute, weather_alerts: [], geopolitical_alerts: [], port_alerts: [] }, true);
  }

  function latLngs(points) {
    return (points || []).filter(p => numeric(p.lat) !== null && numeric(p.lng) !== null).map(p => [Number(p.lat), Number(p.lng)]);
  }

  function smoothRoute(points, iterations = 2) {
    let route = points.slice();
    for (let pass = 0; pass < iterations; pass += 1) {
      if (route.length < 3) return route;
      const smoothed = [route[0]];
      for (let index = 0; index < route.length - 1; index += 1) {
        const first = route[index];
        const second = route[index + 1];
        smoothed.push([
          first[0] * .72 + second[0] * .28,
          first[1] * .72 + second[1] * .28
        ]);
        smoothed.push([
          first[0] * .28 + second[0] * .72,
          first[1] * .28 + second[1] * .72
        ]);
      }
      smoothed.push(route[route.length - 1]);
      route = smoothed;
    }
    return route;
  }

  function radarShape(lat, lng, latRadius, lngRadius, phase = 0, vertices = 26) {
    return Array.from({ length: vertices }, (_, index) => {
      const angle = (Math.PI * 2 * index) / vertices;
      const irregularity = 1 + .16 * Math.sin(index * 2.7 + phase) + .09 * Math.cos(index * 4.3 - phase);
      return [
        lat + Math.sin(angle) * latRadius * irregularity,
        lng + Math.cos(angle) * lngRadius * irregularity
      ];
    });
  }

  function addRadarCluster(alert, latOffset, lngOffset, scale, phase) {
    const centerLat = alert.lat + latOffset;
    const centerLng = alert.lng + lngOffset;
    const severe = alert.severity === "Severe";
    const bands = [
      { scale: 1, color: "#20b85a", opacity: .34 },
      { scale: .73, color: "#d5df27", opacity: .42 },
      { scale: .48, color: "#f4a51c", opacity: .50 },
      ...(severe ? [
        { scale: .29, color: "#e33131", opacity: .58 },
        { scale: .13, color: "#a41475", opacity: .64 }
      ] : [{ scale: .23, color: "#e85b2a", opacity: .52 }])
    ];
    bands.forEach((band, index) => {
      L.polygon(
        radarShape(centerLat, centerLng, 5.4 * scale * band.scale, 7.5 * scale * band.scale, phase + index),
        { stroke: false, fillColor: band.color, fillOpacity: band.opacity, className: "weather-radar-band", interactive: false, pane: "weatherPane" }
      ).addTo(scenarioLayers);
    });
  }

  function routePopup(label, point) {
    return `<div class="map-popup"><span>${escapeHTML(label)}</span><strong>${escapeHTML(point.name)}</strong><small>${point.prototype ? "Prototype maritime waypoint" : "Voyage route location"}</small></div>`;
  }

  function operationalMarker(point) {
    const role = point.role || "route";
    const labels = { origin: "Origin", bunker: "Bunker Port", destination: "Destination", route: "Route Point" };
    const icons = { origin: "bi-geo-alt-fill", bunker: "bi-fuel-pump-fill", destination: "bi-flag-fill", route: "bi-circle-fill" };
    const icon = L.divIcon({
      className: `operational-marker ${role}`,
      html: `<span><i class="bi ${icons[role]}"></i></span>`,
      iconSize: [34, 42], iconAnchor: [17, 38]
    });
    const marker = L.marker([point.lat, point.lng], { icon, title: `${labels[role]}: ${point.name}` });
    const directions = { origin: "left", bunker: "top", destination: "right", route: "top" };
    const offsets = { origin: [-18, 0], bunker: [0, -30], destination: [18, 0], route: [0, -20] };
    marker.bindTooltip(`<div class="port-map-label ${role}"><span>${labels[role]}</span><strong>${escapeHTML(point.name)}</strong></div>`, {
      permanent: role !== "route", direction: directions[role], offset: offsets[role], className: "port-label-tooltip"
    });
    marker.bindPopup(routePopup(labels[role], point));
    return marker;
  }

  function drawMap(mapData, initialOnly = false) {
    if (!map || !mapData) return;
    scenarioLayers.clearLayers();
    if (geopoliticalControl) {
      map.removeControl(geopoliticalControl);
      geopoliticalControl = null;
    }
    const baseline = latLngs(mapData.baseline_route);
    const simulated = latLngs(mapData.simulated_route);
    const baselineDisplay = smoothRoute(baseline);
    const simulatedDisplay = smoothRoute(simulated);
    if (baseline.length > 1) {
      L.polyline(baselineDisplay, { color: "#fff", weight: 7, opacity: .82, smoothFactor: 1.5 }).addTo(scenarioLayers);
      L.polyline(baselineDisplay, { color: "#176fe5", weight: 3.5, opacity: .92, smoothFactor: 1.5 }).bindTooltip("Initial Route", { sticky: true, className: "route-name-tooltip" }).addTo(scenarioLayers);
    }
    if (!initialOnly && simulated.length > 1) {
      L.polyline(simulatedDisplay, { color: "#fff", weight: 7, opacity: .78, dashArray: "11 8", smoothFactor: 1.5 }).addTo(scenarioLayers);
      L.polyline(simulatedDisplay, { color: "#e32335", weight: 3.5, opacity: .95, dashArray: "11 8", smoothFactor: 1.5 }).bindTooltip("Suggested Scenario Route", { sticky: true, className: "route-name-tooltip suggested" }).addTo(scenarioLayers);
    }

    const unique = new Map();
    [...(mapData.baseline_route || []), ...(mapData.simulated_route || [])].forEach(point => {
      if (!point || point.prototype) return;
      unique.set(`${point.lat}-${point.lng}`, point);
    });
    [...unique.values()].forEach(point => operationalMarker(point).addTo(scenarioLayers));
    if (baseline.length > 1) {
      const vesselLat = baseline[0][0] + (baseline[1][0] - baseline[0][0]) * .38;
      const vesselLng = baseline[0][1] + (baseline[1][1] - baseline[0][1]) * .38;
      const vesselIcon = L.divIcon({ className: "vessel-map-marker", html: '<span><i class="bi bi-ship"></i></span>', iconSize: [34, 34], iconAnchor: [17, 17] });
      L.marker([vesselLat, vesselLng], { icon: vesselIcon, interactive: false }).addTo(scenarioLayers);
    }

    (mapData.weather_alerts || []).forEach(alert => {
      addRadarCluster(alert, 0, 0, 1, .4);
      addRadarCluster(alert, 6.2, -8.5, .56, 1.8);
      addRadarCluster(alert, -5.6, 9.2, .43, 3.1);
      addRadarCluster(alert, 3.6, 12.5, .28, 4.6);
      const weatherIcon = L.divIcon({ className: "weather-map-marker", html: '<span><i class="bi bi-cloud-lightning-rain-fill"></i></span>', iconSize: [28, 28], iconAnchor: [14, 14] });
      L.marker([alert.lat, alert.lng], { icon: weatherIcon })
        .bindTooltip(`<div class="weather-map-label"><span>SIMULATED WEATHER</span><strong>${escapeHTML(alert.severity)} conditions</strong></div>`, { direction: "bottom", offset: [0, 15], className: "weather-label-tooltip" })
        .bindPopup(`<div class="map-popup alert"><span>SIMULATED WEATHER</span><strong>${escapeHTML(alert.name)}</strong><small>Severity: ${escapeHTML(alert.severity)}</small><p>Potential for increased consumption, delay and route exposure.</p></div>`).addTo(scenarioLayers);
    });
    (mapData.geopolitical_alerts || []).forEach(alert => {
      const impacts = (alert.impact || []).map(item => `<li><i class="bi bi-dot"></i>${escapeHTML(item)}</li>`).join("");
      const icon = L.divIcon({ className: "geo-alert-marker", html: '<i class="bi bi-exclamation-triangle-fill"></i>', iconSize: [30, 30], iconAnchor: [15, 15] });
      L.marker([alert.lat, alert.lng], { title: alert.name, icon })
        .bindTooltip(`${escapeHTML(alert.region)} · ${escapeHTML(alert.risk_level)} risk`, { direction: "top", offset: [0, -12], className: "geo-marker-tooltip" })
        .bindPopup(`<div class="map-popup alert"><span>SIMULATED GEOPOLITICAL ALERT</span><strong>${escapeHTML(alert.region)} · ${escapeHTML(alert.risk_level)}</strong><p>${escapeHTML(alert.name)}</p><ul>${impacts}</ul></div>`)
        .addTo(scenarioLayers);

      if (!geopoliticalControl) {
        const AlertControl = L.Control.extend({
          options: { position: "topright" },
          onAdd() {
            const card = L.DomUtil.create("aside", "geo-operations-card");
            card.innerHTML = `<div class="geo-card-header"><span class="geo-card-icon"><i class="bi bi-shield-exclamation"></i></span><div><small>GEOPOLITICAL ALERT</small><strong>${escapeHTML(alert.region)}</strong></div><span class="geo-risk-pill">${escapeHTML(alert.risk_level)}</span></div><div class="geo-card-body"><p>${escapeHTML(alert.name)}</p><span class="geo-impact-label">Potential operational impact</span><ul>${impacts}</ul></div><div class="geo-card-footer"><span><i class="bi bi-database-check"></i> Simulated prototype signal</span><button type="button" aria-label="Locate alert"><i class="bi bi-crosshair"></i></button></div>`;
            L.DomEvent.disableClickPropagation(card);
            card.querySelector("button").addEventListener("click", () => map.flyTo([alert.lat, alert.lng], Math.max(map.getZoom(), 4)));
            return card;
          }
        });
        geopoliticalControl = new AlertControl();
        geopoliticalControl.addTo(map);
      }
    });
    (mapData.port_alerts || []).forEach(alert => {
      const shipCount = { Low: 4, Moderate: 8, High: 13 }[alert.level] || 6;
      const headings = [-18, 12, -8, 20, 34, -26, 8, -16, 18, -4, 27, -22, 12];
      const positions = alert.ship_positions || [];
      positions.slice(0, shipCount).forEach(([shipLat, shipLng], index) => {
        const rotation = headings[index % headings.length];
        const delayed = index % 3 === 0;
        const shipSvg = `<svg viewBox="0 0 18 38" aria-hidden="true"><path class="ship-hull" d="M9 1.5 15.5 8v19.5L12 36.5H6L2.5 27.5V8z"/><path class="ship-deck" d="M5.3 10h7.4v13H5.3z"/><path class="ship-bridge" d="M6.2 6.5h5.6v5H6.2z"/><path class="ship-wake" d="M5.5 37h7M7.2 34.2h3.6"/></svg>`;
        const size = index % 4 === 0 ? 29 : 24;
        const shipIcon = L.divIcon({ className: `congestion-ship ${delayed ? "delayed" : ""}`, html: `<span style="--ship-heading:${rotation}deg">${shipSvg}</span>`, iconSize: [size, size + 8], iconAnchor: [size / 2, (size + 8) / 2] });
        L.marker([shipLat, shipLng], { icon: shipIcon, title: "Simulated vessel queue" }).addTo(scenarioLayers);
      });
      const impact = (alert.impact || []).map(item => `<li>${escapeHTML(item)}</li>`).join("");
      const anchorIcon = L.divIcon({ className: "congestion-anchor", html: '<span><i class="bi bi-anchor"></i></span>', iconSize: [30, 34], iconAnchor: [15, 28] });
      L.marker([alert.lat, alert.lng], { icon: anchorIcon })
        .bindTooltip(`<div class="congestion-map-label"><span>PORT CONGESTION · SIMULATED</span><strong>${escapeHTML(alert.name)}</strong><em>${escapeHTML(alert.level)} · ${shipCount} vessels shown</em></div>`, { permanent: true, direction: "bottom", offset: [0, 17], className: "congestion-label-tooltip" })
        .bindPopup(`<div class="map-popup alert"><span>SIMULATED PORT CONGESTION</span><strong>${escapeHTML(alert.name)} · ${escapeHTML(alert.level)}</strong><p>Potential impact:</p><ul>${impact}</ul></div>`).addTo(scenarioLayers);
    });
    const bounds = [...baseline, ...simulated];
    if (bounds.length > 1) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 5 });
  }

  function updateLive(live) {
    if (live.weather?.available) {
      setText("weather-value", live.weather_severity?.level || "Available");
      setText("weather-detail", `${live.weather.description || "Prototype conditions"} · ${live.weather.wind_speed_knots ?? "—"} kn · simulated`);
    } else { setText("weather-value", "Moderate"); setText("weather-detail", "Overcast · 14 kn winds · simulated"); }
    if (live.oil?.available) {
      setText("oil-value", live.oil.formatted || (live.oil.price != null ? `$${Number(live.oil.price).toFixed(2)}` : "Available"));
      setText("oil-detail", "Live market context");
    } else { setText("oil-value", "Unavailable"); setText("oil-detail", live.oil?.error || "OilPriceAPI unavailable"); }
    if (live.news?.available) {
      const articles = live.news.articles || [];
      const lead = articles[0];
      setText("news-value", articles.length ? `${articles.length} relevant disruption${articles.length === 1 ? "" : "s"}` : "No relevant disruptions");
      setText("news-detail", lead ? `${lead.title} · ${lead.source || "NewsAPI"}` : "No route-relevant maritime articles in the last 30 days");
      renderNewsBrief(articles);
    } else {
      setText("news-value", "Unavailable"); setText("news-detail", live.news?.error || "NewsAPI unavailable");
      renderNewsBrief([]);
    }
  }

  function renderNewsBrief(articles) {
    const toggle = $("news-toggle");
    const list = $("news-article-list");
    if (!toggle || !list) return;
    toggle.disabled = articles.length === 0;
    toggle.firstChild.textContent = articles.length ? `View ${articles.length} article${articles.length === 1 ? "" : "s"} ` : "No articles available ";
    list.innerHTML = articles.map((article, index) => {
      const url = safeExternalURL(article.url);
      const description = article.description || "Open the publisher article for the full report.";
      const matches = (article.matched_disruption_terms || []).slice(0, 3).map(term => `<span>${escapeHTML(term)}</span>`).join("");
      return `<article class="news-article"><div class="news-article-rank">${String(index + 1).padStart(2, "0")}</div><div class="news-article-copy"><div class="news-article-meta"><span>${escapeHTML(article.source || "News source")}</span><time>${escapeHTML(articleDate(article.published_at))}</time>${article.relevance_score ? `<em>${escapeHTML(article.relevance_score)}% relevance</em>` : ""}</div><h3>${escapeHTML(article.title || "Untitled article")}</h3><p>${escapeHTML(description)}</p><div class="news-article-actions"><div class="news-tags">${matches}</div>${url ? `<a href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">Read article <i class="bi bi-box-arrow-up-right"></i></a>` : `<span class="news-link-unavailable">Link unavailable</span>`}</div></div></article>`;
    }).join("");
  }

  function setNewsExpanded(expanded) {
    const panel = $("news-expanded");
    const toggle = $("news-toggle");
    if (!panel || !toggle) return;
    panel.hidden = !expanded;
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.classList.toggle("active", expanded);
    const icon = toggle.querySelector("i");
    if (icon) icon.className = expanded ? "bi bi-chevron-up" : "bi bi-chevron-down";
    if (expanded) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function loadIntelligence() {
    const button = $("refresh-live");
    setButtonLoading(button, true, "Refreshing…");
    try { latestLiveIntelligence = await fetchJSON(cfg.intelligenceUrl); updateLive(latestLiveIntelligence); }
    catch (error) {
      ["oil", "news"].forEach(key => setText(`${key}-value`, "Unavailable"));
      setText("live-summary", `Live context unavailable: ${error.message}`);
    } finally { setButtonLoading(button, false); }
  }

  function factorValue(name, selectId, valueKey) {
    const toggle = document.querySelector(`.factor-toggle[data-factor="${name}"]`);
    return { enabled: Boolean(toggle?.checked), [valueKey]: toggle?.checked ? $(selectId).value : "Not Considered" };
  }

  function buildPayload(form) {
    const formData = new FormData(form);
    return {
      controlled_factors: {
        fuel_supply: formData.get("fuel_supply"),
        bunker_type: formData.get("bunker_type"),
        origin_port: formData.get("origin_port"),
        destination_port: formData.get("destination_port"),
        estimated_departure: formData.get("estimated_departure"),
        cargo_weight_tonnes: Number(formData.get("cargo_weight_tonnes") || 0),
        consider_sustainability: $("consider-sustainability").checked
      },
      uncontrolled_factors: {
        weather: factorValue("weather", "weather-severity", "severity"),
        port_congestion: factorValue("congestion", "congestion-level", "level"),
        geopolitical: factorValue("geopolitical", "geopolitical-level", "risk_level")
      },
      live_intelligence: latestLiveIntelligence
    };
  }

  function renderMetricRows(metrics) {
    const definitions = [
      ["Bunker price", "bunker_price", money, money], ["Bunker cost", "bunker_cost", money, money],
      ["Total voyage cost", "total_voyage_cost", money, money], ["Voyage time", "voyage_time", v => number(v, " days"), v => signed(v, " days")],
      ["Fuel consumption", "fuel_consumption", v => number(v, " t"), v => signed(v, " t")], ["Projected arrival reserve", "arrival_reserve", v => number(v, " t"), v => signed(v, " t")],
      ["Estimated emissions", "estimated_emissions", v => number(v, " tCO₂e"), v => signed(v, " tCO₂e")], ["Operational risk", "operational_risk", String, String],
      ["Route distance", "route_distance", v => number(v, " nm"), v => signed(v, " nm")], ["Bunkering port", "bunkering_port", String, String]
    ];
    $("comparison-body").innerHTML = definitions.map(([label, key, formatter, deltaFormatter]) => {
      const metric = metrics[key] || {};
      return `<tr><td><strong>${escapeHTML(label)}</strong></td><td>${escapeHTML(formatter(metric.baseline))}</td><td class="scenario-value">${escapeHTML(formatter(metric.simulated))}</td><td>${escapeHTML(deltaFormatter(metric.difference))}</td></tr>`;
    }).join("");
  }

  function renderTradeoffs(result) {
    $("tradeoff-list").innerHTML = result.tradeoffs.map(item => `<article class="tradeoff-item ${escapeHTML(item.tone)}"><span class="tradeoff-symbol"><i class="bi bi-arrow-left-right"></i></span><div><strong>${escapeHTML(item.title)}</strong><p>${escapeHTML(item.detail)}</p></div></article>`).join("");
    const titles = result.tradeoffs.slice(0, 2).map(item => item.title);
    $("tradeoff-banner").innerHTML = `<i class="bi bi-signpost-split"></i><div><strong>${escapeHTML(titles.join(" · "))}</strong><span>${escapeHTML(result.decision_support.planner_note)}</span></div>`;
  }

  function renderCompliance(compliance) {
    setText("compliance-status", compliance.status);
    setText("compliance-fuel", `Fuel: ${compliance.fuel}`);
    setText("compliance-copy", compliance.explanation);
    $("compliance-status").className = `compliance-badge ${compliance.tone}`;
  }

  function renderRuleBasedSupport(result) {
    const items = result.tradeoffs.map(item => `<li><strong>${escapeHTML(item.title)}:</strong> ${escapeHTML(item.detail)}</li>`).join("");
    $("ai-output").className = "ai-output structured-support";
    $("ai-output").innerHTML = `<div class="support-summary"><span><i class="bi bi-stars"></i></span><div><strong>Structured scenario explanation</strong><p>${escapeHTML(result.decision_support.summary)}</p></div></div><ul>${items}</ul><p class="planner-guardrail">${escapeHTML(result.decision_support.planner_note)} The system does not select a route.</p>`;
  }

  function renderResult(result) {
    const metrics = result.changes;
    setText("kpi-cost", money(metrics.total_voyage_cost.simulated)); setText("kpi-cost-change", `${money(Math.abs(metrics.total_voyage_cost.difference))} ${metrics.total_voyage_cost.difference >= 0 ? "increase" : "decrease"}`);
    setText("kpi-fuel", number(metrics.fuel_consumption.simulated, " t")); setText("kpi-fuel-change", signed(metrics.fuel_consumption.difference, " t"));
    setText("kpi-time", number(metrics.voyage_time.simulated, " days")); setText("kpi-time-change", signed(metrics.voyage_time.difference, " days"));
    setText("kpi-reserve", number(metrics.arrival_reserve.simulated, " t")); setText("kpi-reserve-change", signed(metrics.arrival_reserve.difference, " t"));
    const risk = result.risk.scenario; setText("risk-badge", `${risk} operational risk`); $("risk-badge").className = `risk-badge ${risk.toLowerCase()}`;
    renderMetricRows(metrics); renderTradeoffs(result); renderCompliance(result.compliance); renderRuleBasedSupport(result); drawMap(result.map);
    $("assumption-list").innerHTML = Object.values(result.assumptions).map(value => `<li>${escapeHTML(value)}</li>`).join("");
    $("ai-button").disabled = false;
  }

  async function runScenario(event) {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button[type='submit']");
    setButtonLoading(button, true, "Running simulation…");
    try {
      latestScenario = await fetchJSON(cfg.scenarioUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload(event.currentTarget)) });
      renderResult(latestScenario);
      $("comparison-section").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      $("tradeoff-banner").innerHTML = `<i class="bi bi-exclamation-triangle"></i><div><strong>Simulation could not be completed</strong><span>${escapeHTML(error.message)}</span></div>`;
    } finally { setButtonLoading(button, false); }
  }

  function renderGemini(analysis) {
    const sections = [["What changed", analysis.what_changed], ["Cost trade-off", analysis.cost_drivers], ["Risk trade-off", analysis.risk_drivers], ["Sustainability trade-off", analysis.sustainability_tradeoffs], ["Planner considerations", analysis.planner_considerations]];
    $("ai-output").innerHTML = sections.filter(([, value]) => value).map(([title, value]) => `<section class="ai-section"><strong>${escapeHTML(title)}</strong>${Array.isArray(value) ? `<ul>${value.map(v => `<li>${escapeHTML(v)}</li>`).join("")}</ul>` : `<p>${escapeHTML(value)}</p>`}</section>`).join("") + `<p class="planner-guardrail">Gemini explains structured scenario values only and does not make the final operational decision.</p>`;
  }

  async function explainWithAI() {
    if (!latestScenario) return;
    const button = $("ai-button"); setButtonLoading(button, true, "Explaining…");
    try {
      const result = await fetchJSON(cfg.aiUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ vessel: latestScenario.vessel, controlled_factors: latestScenario.controlled_factors, uncontrolled_factors: latestScenario.uncontrolled_factors, baseline: latestScenario.baseline, simulated: latestScenario.simulated, changes: latestScenario.changes, tradeoffs: latestScenario.tradeoffs, compliance: latestScenario.compliance }) });
      if (!result.available) throw new Error(result.error || "Gemini is unavailable.");
      renderGemini(result.analysis || {});
    } catch (error) {
      renderRuleBasedSupport(latestScenario);
      const note = document.createElement("p"); note.className = "ai-fallback-note"; note.textContent = `Gemini unavailable: ${error.message}. Showing deterministic explanation.`; $("ai-output").prepend(note);
    } finally { setButtonLoading(button, false); }
  }

  function initialiseFactors() {
    document.querySelectorAll(".factor-toggle").forEach(toggle => toggle.addEventListener("change", () => {
      const select = toggle.closest(".factor-card").querySelector(".factor-select"); select.disabled = !toggle.checked;
      toggle.closest(".factor-card").classList.toggle("active", toggle.checked);
      setText("factor-count", document.querySelectorAll(".factor-toggle:checked").length);
    }));
  }

  function initialise() {
    initMap(); initialiseFactors();
    $("scenario-form")?.addEventListener("submit", runScenario);
    $("ai-button")?.addEventListener("click", explainWithAI);
    $("refresh-live")?.addEventListener("click", loadIntelligence);
    $("news-toggle")?.addEventListener("click", () => setNewsExpanded($("news-toggle").getAttribute("aria-expanded") !== "true"));
    $("news-close")?.addEventListener("click", () => setNewsExpanded(false));
    loadIntelligence();
    setTimeout(() => map?.invalidateSize(), 250);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialise); else initialise();
})();
