/*
 * CurrencyFlow frontend logic.
 * Talks to the Flask backend at /api/* and renders the dashboard.
 */

// ---------- Config ----------
const COMPARE_CURRENCIES = ["EUR", "GBP", "JPY", "INR", "CAD", "AUD", "CHF", "CNY"];

// ---------- Helpers ----------
const $ = (id) => document.getElementById(id);

async function fetchJSON(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
        let detail = "";
        try { detail = (await res.json()).error || ""; } catch (_) { /* ignore */ }
        throw new Error(detail || `Request failed: ${res.status}`);
    }
    return res.json();
}

function postJSON(url, body) {
    return fetchJSON(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
}

function deleteRequest(url) {
    return fetchJSON(url, { method: "DELETE" });
}

function fillSelect(selectEl, currencies, defaultValue) {
    selectEl.innerHTML = "";
    Object.entries(currencies)
        .sort(([a], [b]) => a.localeCompare(b))
        .forEach(([code, name]) => {
            const opt = document.createElement("option");
            opt.value = code;
            opt.textContent = `${code} - ${name}`;
            if (code === defaultValue) opt.selected = true;
            selectEl.appendChild(opt);
        });
}

function fmt(n, digits = 2) {
    return Number(n).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

function timeAgo(unix) {
    const seconds = Math.floor(Date.now() / 1000 - unix);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

// ---------- State ----------
let historyChart = null;

// ---------- Stats strip ----------
async function refreshStats() {
    try {
        const data = await fetchJSON("/api/stats");
        $("stats-strip").innerHTML = `
            <span class="stat-pill">Cache hit rate <strong>${data.cache.hit_rate_pct}%</strong></span>
            <span class="stat-pill">Conversions <strong>${data.conversions_logged}</strong></span>
            <span class="stat-pill">Watchlist <strong>${data.watchlist_size}</strong></span>
            <span class="stat-pill">Alerts active <strong>${data.alerts_active}</strong></span>
            <span class="stat-pill">Alerts triggered <strong>${data.alerts_triggered}</strong></span>
        `;
    } catch (err) {
        // Silent.
    }
}

// ---------- Watchlist ----------
async function loadWatchlist() {
    const listEl = $("watchlist-list");
    try {
        const data = await fetchJSON("/api/watchlist");
        const items = data.items || [];
        if (!items.length) {
            listEl.innerHTML = `<span class="subtitle">Your watchlist is empty. Convert a currency below and click the star to pin it.</span>`;
            return;
        }
        listEl.innerHTML = "";
        items.forEach((it) => {
            const cell = document.createElement("div");
            cell.className = "watch-cell";
            const rateText = it.error
                ? `<span class="error">${it.error}</span>`
                : `${fmt(it.rate, 4)}`;
            cell.innerHTML = `
                <div class="watch-pair">${it.from} -> ${it.to}</div>
                <div class="watch-rate">${rateText}</div>
                <button class="watch-remove" title="Remove from watchlist" data-from="${it.from}" data-to="${it.to}">&times;</button>
            `;
            listEl.appendChild(cell);
        });
        listEl.querySelectorAll(".watch-remove").forEach((btn) =>
            btn.addEventListener("click", async (e) => {
                const f = e.currentTarget.dataset.from;
                const t = e.currentTarget.dataset.to;
                await deleteRequest(`/api/watchlist/${f}/${t}`);
                loadWatchlist();
                refreshStats();
            })
        );
    } catch (err) {
        listEl.innerHTML = `<span class="error">Failed to load watchlist: ${err.message}</span>`;
    }
}

async function handleAddToWatchlist() {
    const from = $("from-currency").value;
    const to = $("to-currency").value;
    if (from === to) {
        flashWatchButton("Pick different currencies", true);
        return;
    }
    try {
        await postJSON("/api/watchlist", { from, to });
        flashWatchButton(`Added ${from} -> ${to}`);
        loadWatchlist();
        refreshStats();
    } catch (err) {
        flashWatchButton(err.message, true);
    }
}

function flashWatchButton(msg, isError = false) {
    const btn = $("watch-button");
    const original = btn.innerHTML;
    btn.innerHTML = msg;
    btn.classList.toggle("error-flash", isError);
    btn.classList.toggle("success-flash", !isError);
    setTimeout(() => {
        btn.innerHTML = original;
        btn.classList.remove("error-flash", "success-flash");
    }, 1800);
}

// ---------- Live rates table ----------
async function loadRates(base) {
    const tableEl = $("rates-table");
    tableEl.innerHTML = "Loading rates&hellip;";
    try {
        const data = await fetchJSON(`/api/rates?base=${encodeURIComponent(base)}`);
        const rates = data.rates || {};
        tableEl.innerHTML = "";
        Object.entries(rates)
            .sort(([a], [b]) => a.localeCompare(b))
            .forEach(([code, value]) => {
                const cell = document.createElement("div");
                cell.className = "rate-cell";
                cell.innerHTML = `<div class="currency">${code}</div><div class="value">${fmt(value, 4)}</div>`;
                tableEl.appendChild(cell);
            });
    } catch (err) {
        tableEl.innerHTML = `<span class="error">Failed to load rates: ${err.message}</span>`;
    }
}

// ---------- Conversion form ----------
function buildCompareCheckboxes() {
    const container = $("compare-checkboxes");
    container.innerHTML = "";
    COMPARE_CURRENCIES.forEach((code) => {
        const label = document.createElement("label");
        label.innerHTML = `<input type="checkbox" value="${code}"><span>${code}</span>`;
        container.appendChild(label);
    });
}

function getComparedTargets() {
    return Array.from(
        document.querySelectorAll("#compare-checkboxes input:checked")
    ).map((el) => el.value);
}

async function loadInsight(from, to) {
    const badge = $("insight-badge");
    if (from === to) {
        badge.innerHTML = "";
        return;
    }
    try {
        const data = await fetchJSON(`/api/insight?from=${from}&to=${to}`);
        if (!data.message) {
            badge.innerHTML = "";
            return;
        }
        const cls = data.verdict === "good" ? "insight-good"
            : data.verdict === "wait" ? "insight-wait"
            : "insight-neutral";
        badge.className = `insight-badge ${cls}`;
        badge.innerHTML = `<strong>Insight:</strong> ${data.message}`;
    } catch (_) {
        badge.innerHTML = "";
    }
}

async function handleConvert(event) {
    event.preventDefault();
    const amount = $("amount").value;
    const from = $("from-currency").value;
    const primaryTo = $("to-currency").value;
    const compared = getComparedTargets().filter((c) => c !== primaryTo);
    const toList = [primaryTo, ...compared].join(",");

    const resultEl = $("convert-result");
    resultEl.innerHTML = "Converting&hellip;";

    try {
        const data = await fetchJSON(
            `/api/convert?from=${from}&to=${encodeURIComponent(toList)}&amount=${encodeURIComponent(amount)}`
        );

        const primary = data.results.find((r) => r.to === primaryTo);
        const others = data.results.filter((r) => r.to !== primaryTo);

        let html = "";
        if (primary && primary.error == null) {
            html += `
                <div class="primary">
                    ${fmt(data.amount)} ${data.from_currency}
                    =
                    <strong>${fmt(primary.converted)} ${primary.to}</strong>
                    <span class="subtitle">(rate: ${fmt(primary.rate, 6)}${data.date ? ` &middot; ${data.date}` : ""})</span>
                </div>
            `;
        }
        if (others.length) {
            html += `<div class="secondary">`;
            others.forEach((r) => {
                if (r.error) {
                    html += `<span>${r.to}: <span class="error">${r.error}</span></span>`;
                } else {
                    html += `<span>${r.to}: <strong>${fmt(r.converted)}</strong></span>`;
                }
            });
            html += `</div>`;
        }
        resultEl.innerHTML = html;

        loadInsight(from, primaryTo);
        loadRecent();
        refreshStats();
    } catch (err) {
        resultEl.innerHTML = `<span class="error">Conversion failed: ${err.message}</span>`;
    }
}

// ---------- Top Movers ----------
async function loadMovers() {
    const base = $("movers-base").value;
    const days = $("movers-days").value;
    const listEl = $("movers-list");
    listEl.innerHTML = "Loading&hellip;";
    try {
        const data = await fetchJSON(
            `/api/movers?base=${encodeURIComponent(base)}&days=${encodeURIComponent(days)}`
        );
        const movers = data.movers || [];
        if (!movers.length) {
            listEl.innerHTML = `<span class="subtitle">No data.</span>`;
            return;
        }
        listEl.innerHTML = "";
        movers.forEach((m) => {
            const cls = m.change_pct > 0 ? "change-up"
                : m.change_pct < 0 ? "change-down" : "change-flat";
            const sign = m.change_pct > 0 ? "+" : "";
            const cell = document.createElement("div");
            cell.className = "mover-cell";
            cell.innerHTML = `
                <span class="currency">${m.currency}</span>
                <span class="${cls}">${sign}${fmt(m.change_pct, 2)}%</span>
            `;
            listEl.appendChild(cell);
        });
    } catch (err) {
        listEl.innerHTML = `<span class="error">Failed to load movers: ${err.message}</span>`;
    }
}

// ---------- Popular pairs / recent conversions ----------
async function loadRecent() {
    try {
        const data = await fetchJSON("/api/recent-conversions");

        const popularEl = $("popular-list");
        if (!data.popular.length) {
            popularEl.innerHTML = `<span class="subtitle">No conversions yet. Try converting above.</span>`;
        } else {
            popularEl.innerHTML = data.popular
                .map((p) => `<span class="popular-pill">${p.pair.replace("->", " &rarr; ")}<span class="count">${p.count}</span></span>`)
                .join("");
        }

        const recentEl = $("recent-list");
        if (!data.recent.length) {
            recentEl.innerHTML = `<span class="subtitle">No recent conversions.</span>`;
        } else {
            recentEl.innerHTML = data.recent
                .map((r) => `
                    <div class="recent-row">
                        <span>${fmt(r.amount)} ${r.from} &rarr; ${fmt(r.converted)} ${r.to}</span>
                        <span class="subtitle">rate ${fmt(r.rate, 4)}</span>
                    </div>
                `)
                .join("");
        }
    } catch (err) { /* silent */ }
}

// ---------- Rate Alerts ----------
async function handleCreateAlert(event) {
    event.preventDefault();
    const body = {
        from: $("alert-from").value,
        to: $("alert-to").value,
        op: $("alert-op").value,
        threshold: parseFloat($("alert-threshold").value),
    };
    try {
        await postJSON("/api/alerts", body);
        $("alert-threshold").value = "";
        loadAlerts();
        refreshStats();
    } catch (err) {
        alert(`Could not create alert: ${err.message}`);
    }
}

async function loadAlerts() {
    const listEl = $("alerts-list");
    try {
        const data = await fetchJSON("/api/alerts");
        const items = data.alerts || [];
        if (!items.length) {
            listEl.innerHTML = `<span class="subtitle">No active alerts.</span>`;
            return;
        }
        listEl.innerHTML = "";
        items.forEach((a) => {
            const triggered = !!a.triggered_at;
            const cls = triggered ? "alert-row triggered" : "alert-row";
            const status = triggered
                ? `<span class="alert-status triggered">Triggered ${timeAgo(a.triggered_at)} at rate ${fmt(a.last_rate, 4)}</span>`
                : `<span class="alert-status active">Watching${a.last_rate != null ? ` &middot; last seen ${fmt(a.last_rate, 4)}` : ""}</span>`;
            const cell = document.createElement("div");
            cell.className = cls;
            cell.innerHTML = `
                <div class="alert-rule">
                    <strong>${a.from} &rarr; ${a.to}</strong>
                    ${a.op} ${fmt(a.threshold, 4)}
                </div>
                ${status}
                <button class="alert-remove" data-id="${a.id}" title="Delete alert">&times;</button>
            `;
            listEl.appendChild(cell);
        });
        listEl.querySelectorAll(".alert-remove").forEach((btn) =>
            btn.addEventListener("click", async (e) => {
                await deleteRequest(`/api/alerts/${e.currentTarget.dataset.id}`);
                loadAlerts();
                refreshStats();
            })
        );
    } catch (err) {
        listEl.innerHTML = `<span class="error">Failed to load alerts: ${err.message}</span>`;
    }
}

// ---------- Historical trend chart ----------
async function loadHistory() {
    const from = $("hist-from").value;
    const to = $("hist-to").value;
    const days = $("hist-days").value;

    try {
        const data = await fetchJSON(
            `/api/history?from=${from}&to=${to}&days=${days}`
        );
        const points = Object.entries(data.rates || {})
            .map(([day, rates]) => ({ x: day, y: rates[to] }))
            .filter((p) => p.y !== undefined)
            .sort((a, b) => a.x.localeCompare(b.x));

        const labels = points.map((p) => p.x);
        const values = points.map((p) => p.y);

        const ctx = $("history-chart").getContext("2d");
        if (historyChart) historyChart.destroy();

        // Build a gradient fill so the chart has some visual weight without
        // being heavy. Recreated each render so it tracks the current canvas size.
        const canvasHeight = ctx.canvas.height || 320;
        const gradient = ctx.createLinearGradient(0, 0, 0, canvasHeight);
        gradient.addColorStop(0, "rgba(124, 92, 255, 0.35)");
        gradient.addColorStop(1, "rgba(124, 92, 255, 0.00)");

        historyChart = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: `${from} -> ${to}`,
                    data: values,
                    borderColor: "#9077ff",
                    backgroundColor: gradient,
                    borderWidth: 2,
                    tension: 0.3,
                    fill: true,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: "#9077ff",
                    pointHoverBorderColor: "#ffffff",
                    pointHoverBorderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                plugins: {
                    legend: {
                        labels: {
                            color: "#e6ebf6",
                            font: { family: "Inter, sans-serif", size: 12, weight: "500" },
                            boxWidth: 12,
                            boxHeight: 12,
                            usePointStyle: true,
                            pointStyle: "circle",
                        },
                    },
                    tooltip: {
                        backgroundColor: "rgba(15, 21, 48, 0.95)",
                        borderColor: "#232b52",
                        borderWidth: 1,
                        titleColor: "#e6ebf6",
                        bodyColor: "#e6ebf6",
                        titleFont: { family: "Inter, sans-serif", weight: "600" },
                        bodyFont: { family: "Inter, sans-serif" },
                        padding: 10,
                        cornerRadius: 8,
                        displayColors: false,
                    },
                },
                scales: {
                    x: {
                        ticks: {
                            color: "#7a85a8",
                            font: { family: "Inter, sans-serif", size: 11 },
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 8,
                        },
                        grid: { color: "rgba(35, 43, 82, 0.5)", drawTicks: false },
                        border: { display: false },
                    },
                    y: {
                        ticks: {
                            color: "#7a85a8",
                            font: { family: "Inter, sans-serif", size: 11 },
                            padding: 6,
                        },
                        grid: { color: "rgba(35, 43, 82, 0.5)", drawTicks: false },
                        border: { display: false },
                    },
                },
            },
        });
    } catch (err) {
        console.error("Failed to load history", err);
    }
}

// ---------- Init ----------
async function init() {
    try {
        const currencies = await fetchJSON("/api/currencies");

        fillSelect($("from-currency"), currencies, "USD");
        fillSelect($("to-currency"), currencies, "EUR");
        fillSelect($("base-currency"), currencies, "USD");
        fillSelect($("movers-base"), currencies, "USD");
        fillSelect($("hist-from"), currencies, "USD");
        fillSelect($("hist-to"), currencies, "EUR");
        fillSelect($("alert-from"), currencies, "USD");
        fillSelect($("alert-to"), currencies, "EUR");

        buildCompareCheckboxes();

        // Wire events.
        $("convert-form").addEventListener("submit", handleConvert);
        $("watch-button").addEventListener("click", handleAddToWatchlist);
        $("base-currency").addEventListener("change", (e) => loadRates(e.target.value));
        $("movers-base").addEventListener("change", loadMovers);
        $("movers-days").addEventListener("change", loadMovers);
        $("alert-form").addEventListener("submit", handleCreateAlert);
        ["hist-from", "hist-to", "hist-days"].forEach((id) =>
            $(id).addEventListener("change", loadHistory)
        );

        // First load.
        await Promise.all([
            loadWatchlist(),
            loadRates("USD"),
            loadHistory(),
            loadMovers(),
            loadRecent(),
            loadAlerts(),
            refreshStats(),
        ]);

        // Auto-refresh.
        setInterval(refreshStats, 5000);
        setInterval(loadAlerts, 15000);     // surface triggered alerts within ~15s
        setInterval(loadWatchlist, 60000);  // refresh watchlist rates each minute
    } catch (err) {
        console.error("Initialization failed", err);
        document.body.insertAdjacentHTML(
            "afterbegin",
            `<div class="card error" style="margin:1rem;">Failed to initialize: ${err.message}</div>`
        );
    }
}

document.addEventListener("DOMContentLoaded", init);
