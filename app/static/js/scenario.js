(() => {
    "use strict";

    /*
     * ============================================================
     * VECXUS
     * Voyage Scenario & Dynamic Risk Analysis
     * AI-Assisted Decision Support
     * ============================================================
     *
     * This frontend:
     *
     * 1. Loads live API intelligence
     * 2. Runs scenario calculations
     * 3. Displays baseline vs scenario
     * 4. Displays dynamic risk
     * 5. Displays the route on Leaflet/OpenStreetMap
     * 6. Sends structured results to Gemini
     *
     * API keys are NEVER stored in this file.
     * All API calls go through Flask.
     */

    const cfg = window.SCENARIO_CONFIG || {};

    let latestScenario = null;
    let latestLiveIntelligence = null;

    let map = null;
    let routeLayer = null;


    // ============================================================
    // DOM HELPERS
    // ============================================================

    const $ = (id) => document.getElementById(id);


    function setText(id, value) {
        const element = $(id);

        if (element) {
            element.textContent = value ?? "—";
        }
    }


    function setButtonLoading(button, loading, text = "Loading…") {

        if (!button) {
            return;
        }

        if (loading) {

            button.dataset.originalText =
                button.textContent;

            button.disabled = true;
            button.textContent = text;

        } else {

            button.disabled = false;

            if (button.dataset.originalText) {
                button.textContent =
                    button.dataset.originalText;
            }
        }
    }


    function showError(message) {

        const output = $("ai-output");

        if (output) {
            output.textContent = message;
            output.className = "mt-3 alert alert-warning";
        }

        console.error("[Scenario]", message);
    }


    // ============================================================
    // FORMATTERS
    // ============================================================

    function number(value, suffix = "") {

        const n = Number(value);

        if (!Number.isFinite(n)) {
            return "—";
        }

        return (
            n.toLocaleString(undefined, {
                maximumFractionDigits: 1
            }) + suffix
        );
    }


    function money(value) {

        const n = Number(value);

        if (!Number.isFinite(n)) {
            return "—";
        }

        return (
            "$" +
            n.toLocaleString(undefined, {
                maximumFractionDigits: 0
            })
        );
    }


    function signed(value, suffix = "") {

        const n = Number(value);

        if (!Number.isFinite(n)) {
            return "—";
        }

        return (
            (n >= 0 ? "+" : "") +
            n.toLocaleString(undefined, {
                maximumFractionDigits: 1
            }) +
            suffix
        );
    }


    function escapeHTML(value) {

        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }


    // ============================================================
    // API FETCH HELPER
    // ============================================================

    async function fetchJSON(
        url,
        options = {}
    ) {

        const response = await fetch(
            url,
            {
                cache: "no-store",
                ...options
            }
        );

        let data = {};

        try {
            data = await response.json();
        } catch (error) {

            throw new Error(
                `Server returned HTTP ${response.status} without valid JSON.`
            );
        }

        if (!response.ok) {

            throw new Error(
                data.error ||
                `Request failed with HTTP ${response.status}.`
            );
        }

        return data;
    }


    // ============================================================
    // MAP
    // ============================================================

    function initMap() {

        const mapElement = $("scenario-map");

        if (!mapElement) {
            return;
        }

        if (typeof L === "undefined") {

            console.error(
                "Leaflet is not loaded."
            );

            return;
        }

        map = L.map(
            "scenario-map"
        ).setView(
            [1.2644, 103.82],
            4
        );

        L.tileLayer(
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                attribution:
                    "© OpenStreetMap contributors",
                maxZoom: 18
            }
        ).addTo(map);
    }


    function drawRoute(route) {

        if (!map || !route) {
            return;
        }

        if (routeLayer) {
            routeLayer.clearLayers();
        }

        routeLayer =
            L.layerGroup().addTo(map);


        const points = [

            [
                "Origin",
                route.coordinates?.origin
            ],

            [
                "Current bunker",
                route.coordinates?.bunkering
            ],

            [
                "Scenario bunker",
                route.coordinates?.scenario_bunkering
            ],

            [
                "Destination",
                route.coordinates?.destination
            ]

        ].filter(
            ([, point]) =>
                point &&
                Number.isFinite(Number(point.lat)) &&
                Number.isFinite(Number(point.lng))
        );


        const latLngs =
            points.map(
                ([, point]) => [
                    Number(point.lat),
                    Number(point.lng)
                ]
            );


        points.forEach(
            ([label, point]) => {

                L.marker([
                    Number(point.lat),
                    Number(point.lng)
                ])
                    .bindPopup(
                        `<strong>${escapeHTML(label)}</strong>`
                    )
                    .addTo(routeLayer);
            }
        );


        if (latLngs.length >= 2) {

            L.polyline(
                latLngs,
                {
                    weight: 4
                }
            ).addTo(routeLayer);

            map.fitBounds(
                latLngs,
                {
                    padding: [
                        30,
                        30
                    ]
                }
            );
        }
    }


    // ============================================================
    // API STATUS CARDS
    // ============================================================

    function updateAPIStatus(live) {

        if (!live) {
            return;
        }

        const status =
            live.api_status || {};


        // --------------------------------------------------------
        // WEATHER
        // --------------------------------------------------------

        if (
            live.weather &&
            live.weather.available
        ) {

            const severity =
                live.weather_severity || {};

            setText(
                "weather-value",
                severity.level ||
                "Available"
            );

            setText(
                "weather-detail",
                `${live.weather.description || "Current conditions"} · ` +
                `wind ${live.weather.wind_speed_mps ?? "—"} m/s`
            );

        } else {

            setText(
                "weather-value",
                "Unavailable"
            );

            setText(
                "weather-detail",
                live.weather?.error ||
                "OpenWeather unavailable"
            );
        }


        // --------------------------------------------------------
        // OIL
        // --------------------------------------------------------

        if (
            live.oil &&
            live.oil.available
        ) {

            const price =
                live.oil.formatted ||
                (
                    live.oil.price != null
                        ? `$${Number(live.oil.price).toFixed(2)}`
                        : "Live"
                );

            setText(
                "oil-value",
                price
            );

            setText(
                "oil-detail",
                live.oil.created_at
                    ? `Updated ${live.oil.created_at}`
                    : "Live Brent market signal"
            );

        } else {

            setText(
                "oil-value",
                "Unavailable"
            );

            setText(
                "oil-detail",
                live.oil?.error ||
                "OilPriceAPI unavailable"
            );
        }


        // --------------------------------------------------------
        // SCHEDULE
        // --------------------------------------------------------

        if (
            live.schedule &&
            live.schedule.available
        ) {

            const scheduleSignal =
                live.schedule_signal || {};

            const count =
                scheduleSignal.options ??
                0;

            setText(
                "schedule-value",
                `${count} option${count === 1 ? "" : "s"}`
            );

            setText(
                "schedule-detail",
                `Live ${live.schedule.mode || "schedule"} schedule`
            );

        } else {

            setText(
                "schedule-value",
                "Unavailable"
            );

            setText(
                "schedule-detail",
                live.schedule?.error ||
                "Schedule API unavailable"
            );
        }


        // --------------------------------------------------------
        // NEWS
        // --------------------------------------------------------

        if (
            live.news &&
            live.news.available
        ) {

            const count =
                live.news.total_results ??
                live.news.articles?.length ??
                0;

            const disruption =
                live.disruption_signal || {};

            setText(
                "news-value",
                `${count} signal${count === 1 ? "" : "s"}`
            );

            setText(
                "news-detail",
                `Disruption signal: ${
                    disruption.level || "Unknown"
                }`
            );

        } else {

            setText(
                "news-value",
                "Unavailable"
            );

            setText(
                "news-detail",
                live.news?.error ||
                "NewsAPI unavailable"
            );
        }


        // --------------------------------------------------------
        // Console diagnostics
        // --------------------------------------------------------

        console.table({
            "OpenWeather":
                status.weather
                    ? "OK"
                    : "Unavailable",

            "OilPriceAPI":
                status.oil
                    ? "OK"
                    : "Unavailable",

            "Schedule API":
                status.schedule
                    ? "OK"
                    : "Unavailable",

            "NewsAPI":
                status.news
                    ? "OK"
                    : "Unavailable"
        });
    }


    // ============================================================
    // LOAD LIVE INTELLIGENCE
    // ============================================================

    async function loadIntelligence() {

        if (!cfg.intelligenceUrl) {

            console.error(
                "SCENARIO_CONFIG.intelligenceUrl is missing."
            );

            return;
        }

        try {

            const live =
                await fetchJSON(
                    cfg.intelligenceUrl
                );

            latestLiveIntelligence =
                live;

            updateAPIStatus(
                live
            );

            console.log(
                "[Scenario] Live intelligence loaded:",
                live
            );

        } catch (error) {

            console.error(
                "[Scenario] Live intelligence failed:",
                error
            );

            setText(
                "weather-value",
                "Unavailable"
            );

            setText(
                "oil-value",
                "Unavailable"
            );

            setText(
                "schedule-value",
                "Unavailable"
            );

            setText(
                "news-value",
                "Unavailable"
            );

            setText(
                "weather-detail",
                error.message
            );
        }
    }


    // ============================================================
    // RENDER SCENARIO COMPARISON
    // ============================================================

    function renderComparison(result) {

        if (!result) {
            return;
        }

        const metrics =
            result.metrics || {};


        const rows = [

            [
                "Bunker price",
                money(
                    metrics.bunker_price?.baseline
                ) + "/t",

                money(
                    metrics.bunker_price?.scenario
                ) + "/t",

                signed(
                    Number(
                        metrics.bunker_price?.scenario
                    ) -
                    Number(
                        metrics.bunker_price?.baseline
                    ),
                    "/t"
                )
            ],

            [
                "Projected bunker cost",
                money(
                    metrics.bunker_cost?.baseline
                ),

                money(
                    metrics.bunker_cost?.scenario
                ),

                signed(
                    Number(
                        metrics.bunker_cost?.scenario
                    ) -
                    Number(
                        metrics.bunker_cost?.baseline
                    )
                )
            ],

            [
                "Fuel consumption",
                number(
                    metrics.fuel_consumption?.baseline,
                    " t"
                ),

                number(
                    metrics.fuel_consumption?.scenario,
                    " t"
                ),

                signed(
                    Number(
                        metrics.fuel_consumption?.scenario
                    ) -
                    Number(
                        metrics.fuel_consumption?.baseline
                    ),
                    " t"
                )
            ],

            [
                "Voyage consumption",
                number(
                    metrics.voyage_consumption?.baseline,
                    " t"
                ),

                number(
                    metrics.voyage_consumption?.scenario,
                    " t"
                ),

                signed(
                    Number(
                        metrics.voyage_consumption?.scenario
                    ) -
                    Number(
                        metrics.voyage_consumption?.baseline
                    ),
                    " t"
                )
            ],

            [
                "Arrival fuel",
                number(
                    metrics.arrival_fuel?.baseline,
                    " t"
                ),

                number(
                    metrics.arrival_fuel?.scenario,
                    " t"
                ),

                signed(
                    Number(
                        metrics.arrival_fuel?.scenario
                    ) -
                    Number(
                        metrics.arrival_fuel?.baseline
                    ),
                    " t"
                )
            ],

            [
                "Reserve margin",
                number(
                    metrics.reserve_margin?.baseline,
                    " t"
                ),

                number(
                    metrics.reserve_margin?.scenario,
                    " t"
                ),

                signed(
                    Number(
                        metrics.reserve_margin?.scenario
                    ) -
                    Number(
                        metrics.reserve_margin?.baseline
                    ),
                    " t"
                )
            ],

            [
                "Voyage duration",
                number(
                    metrics.voyage_duration?.baseline,
                    " days"
                ),

                number(
                    metrics.voyage_duration?.scenario,
                    " days"
                ),

                signed(
                    Number(
                        metrics.voyage_duration?.scenario
                    ) -
                    Number(
                        metrics.voyage_duration?.baseline
                    ),
                    " days"
                )
            ],

            [
                "Emissions",
                number(
                    metrics.emissions?.baseline,
                    " tCO₂e"
                ),

                number(
                    metrics.emissions?.scenario,
                    " tCO₂e"
                ),

                signed(
                    Number(
                        metrics.emissions?.scenario
                    ) -
                    Number(
                        metrics.emissions?.baseline
                    ),
                    " tCO₂e"
                )
            ],

            [
                "Bunker requirement",
                number(
                    metrics.bunker_quantity?.baseline,
                    " t"
                ),

                number(
                    metrics.bunker_quantity?.scenario,
                    " t"
                ),

                signed(
                    Number(
                        metrics.bunker_quantity?.scenario
                    ) -
                    Number(
                        metrics.bunker_quantity?.baseline
                    ),
                    " t"
                )
            ]
        ];


        const body =
            $("comparison-body");

        if (body) {

            body.innerHTML =
                rows.map(
                    row => `
                        <tr>
                            <td>
                                <strong>
                                    ${escapeHTML(row[0])}
                                </strong>
                            </td>

                            <td>
                                ${escapeHTML(row[1])}
                            </td>

                            <td>
                                ${escapeHTML(row[2])}
                            </td>

                            <td>
                                ${escapeHTML(row[3])}
                            </td>
                        </tr>
                    `
                ).join("");
        }


        // ========================================================
        // RISK
        // ========================================================

        const risk =
            result.risk || {};

        const riskLevel =
            risk.scenario ||
            "Unknown";

        const riskBadge =
            $("risk-badge");

        if (riskBadge) {

            riskBadge.textContent =
                `${riskLevel} risk`;

            riskBadge.className =
                "badge " +
                (
                    riskLevel === "High"
                        ? "text-bg-danger"

                        : riskLevel === "Medium"
                            ? "text-bg-warning"

                            : riskLevel === "Low"
                                ? "text-bg-success"

                                : "text-bg-secondary"
                );
        }


        setText(
            "risk-title",
            `${riskLevel} · score ${risk.score ?? "—"}`
        );


        setText(
            "risk-method",
            risk.method ||
            "Transparent rule-based scenario score."
        );


        const reasons =
            $("risk-reasons");

        if (reasons) {

            const list =
                risk.reasons?.length
                    ? risk.reasons
                    : [
                        "No additional risk drivers detected."
                    ];

            reasons.innerHTML =
                list.map(
                    reason =>
                        `<li>${escapeHTML(reason)}</li>`
                ).join("");
        }


        // ========================================================
        // ROUTE
        // ========================================================

        drawRoute(
            result.route
        );


        // ========================================================
        // ENABLE AI
        // ========================================================

        const aiButton =
            $("ai-button");

        if (aiButton) {

            aiButton.disabled =
                false;
        }


        const aiOutput =
            $("ai-output");

        if (aiOutput) {

            aiOutput.className =
                "mt-3 text-muted";

            aiOutput.textContent =
                "Scenario calculated. Gemini can now explain the trade-offs.";
        }
    }


    // ============================================================
    // RUN SCENARIO
    // ============================================================

    async function runScenario(event) {

        event.preventDefault();

        const form =
            event.currentTarget;

        const payload =
            Object.fromEntries(
                new FormData(form).entries()
            );


        // --------------------------------------------------------
        // Convert numeric values properly
        // --------------------------------------------------------

        payload.delay_days =
            Number(
                payload.delay_days || 0
            );

        payload.fuel_price_change_pct =
            Number(
                payload.fuel_price_change_pct || 0
            );


        // --------------------------------------------------------
        // Tell backend that this scenario is connected to
        // live intelligence.
        // --------------------------------------------------------

        payload.live_intelligence =
            latestLiveIntelligence || null;


        const button =
            form.querySelector(
                "button[type='submit']"
            );


        setButtonLoading(
            button,
            true,
            "Calculating…"
        );


        try {

            const result =
                await fetchJSON(
                    cfg.scenarioUrl,
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify(payload)
                    }
                );


            latestScenario =
                result;


            // If the scenario API refreshed live
            // intelligence, use that version.

            if (
                result.live_intelligence
            ) {

                latestLiveIntelligence =
                    result.live_intelligence;

                updateAPIStatus(
                    latestLiveIntelligence
                );
            }


            renderComparison(
                result
            );


            console.log(
                "[Scenario] Calculation result:",
                result
            );

        } catch (error) {

            showError(
                error.message
            );

        } finally {

            setButtonLoading(
                button,
                false
            );
        }
    }


    // ============================================================
    // GEMINI SCENARIO EXPLANATION
    // ============================================================

    async function explainWithAI() {

        if (!latestScenario) {

            showError(
                "Run a scenario before asking Gemini to explain it."
            );

            return;
        }


        if (!cfg.aiUrl) {

            showError(
                "Gemini endpoint is not configured."
            );

            return;
        }


        const button =
            $("ai-button");

        const output =
            $("ai-output");


        setButtonLoading(
            button,
            true,
            "Gemini is analysing…"
        );


        if (output) {

            output.className =
                "mt-3";

            output.innerHTML = `
                <div class="alert alert-light border">
                    Gemini is analysing the scenario trade-offs…
                </div>
            `;
        }


        const payload = {

            vessel:
                latestScenario.vessel,

            scenario_inputs:
                latestScenario.inputs,

            baseline:
                latestScenario.baseline,

            scenario:
                latestScenario.scenario,

            metrics:
                latestScenario.metrics,

            risk:
                latestScenario.risk,

            live_intelligence:
                latestScenario.live_intelligence ||
                latestLiveIntelligence
        };


        try {

            const result =
                await fetchJSON(
                    cfg.aiUrl,
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify(payload)
                    }
                );


            if (!result.available) {

                throw new Error(
                    result.error ||
                    "Gemini is unavailable."
                );
            }


            const analysis =
                result.analysis || {};


            renderAIAnalysis(
                analysis
            );


        } catch (error) {

            if (output) {

                output.className =
                    "mt-3 alert alert-warning";

                output.textContent =
                    error.message;
            }

            console.error(
                "[Gemini]",
                error
            );

        } finally {

            setButtonLoading(
                button,
                false
            );
        }
    }


    // ============================================================
    // GEMINI OUTPUT
    // ============================================================

    function renderAIAnalysis(
        analysis
    ) {

        const output =
            $("ai-output");

        if (!output) {
            return;
        }


        const sections = [

            [
                "What changed?",
                analysis.what_changed
            ],

            [
                "Cost drivers",
                analysis.cost_drivers
            ],

            [
                "Fuel drivers",
                analysis.fuel_drivers
            ],

            [
                "Risk drivers",
                analysis.risk_drivers
            ],

            [
                "Sustainability trade-offs",
                analysis.sustainability_tradeoffs
            ],

            [
                "Planner considerations",
                analysis.planner_considerations
            ]
        ];


        output.className =
            "mt-3";


        output.innerHTML =
            sections
                .map(
                    ([title, value]) => {

                        if (
                            value === undefined ||
                            value === null ||
                            value === ""
                        ) {
                            return "";
                        }


                        const content =
                            Array.isArray(value)
                                ? `
                                    <ul class="mb-0">
                                        ${
                                            value
                                                .map(
                                                    item =>
                                                        `<li>${escapeHTML(item)}</li>`
                                                )
                                                .join("")
                                        }
                                    </ul>
                                  `
                                : `
                                    <p class="mb-0">
                                        ${escapeHTML(value)}
                                    </p>
                                  `;


                        return `
                            <div class="mb-3">
                                <strong>
                                    ${escapeHTML(title)}
                                </strong>

                                <div class="mt-1">
                                    ${content}
                                </div>
                            </div>
                        `;
                    }
                )
                .join("") +
            `
                <hr>

                <small class="text-muted">
                    Gemini explains the structured scenario results.
                    It does not make the final operational decision.
                </small>
            `;
    }


    // ============================================================
    // INITIALISATION
    // ============================================================

    function validateConfig() {

        const required = [
            "vesselId",
            "scenarioUrl",
            "intelligenceUrl",
            "aiUrl"
        ];


        const missing =
            required.filter(
                key => !cfg[key]
            );


        if (missing.length) {

            console.error(
                "[Scenario] Missing configuration:",
                missing
            );

            return false;
        }


        return true;
    }


    function initialise() {

        console.log(
            "[Scenario] Initialising…"
        );


        if (!validateConfig()) {

            showError(
                "Scenario configuration is incomplete. Check scenario.html."
            );

            return;
        }


        initMap();


        const form =
            $("scenario-form");


        if (form) {

            form.addEventListener(
                "submit",
                runScenario
            );
        }


        const aiButton =
            $("ai-button");


        if (aiButton) {

            aiButton.addEventListener(
                "click",
                explainWithAI
            );
        }


        // --------------------------------------------------------
        // Load live APIs immediately
        // --------------------------------------------------------

        loadIntelligence();


        // --------------------------------------------------------
        // Refresh live intelligence periodically.
        //
        // 5 minutes is deliberately used instead of repeatedly
        // hammering external services.
        // --------------------------------------------------------

        setInterval(
            loadIntelligence,
            5 * 60 * 1000
        );


        // --------------------------------------------------------
        // Leaflet needs a size recalculation after the page
        // finishes rendering.
        // --------------------------------------------------------

        setTimeout(
            () => {

                if (map) {
                    map.invalidateSize();
                }

            },
            300
        );


        console.log(
            "[Scenario] Ready."
        );
    }


    // ============================================================
    // START
    // ============================================================

    if (
        document.readyState ===
        "loading"
    ) {

        document.addEventListener(
            "DOMContentLoaded",
            initialise
        );

    } else {

        initialise();
    }

})();