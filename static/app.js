/*
 * CurrencyFlow frontend logic.
 * Talks to the Flask backend at /api/* and renders the dashboard.
 */

// ---------- Config ----------
const COMPARE_CURRENCIES = ["EUR", "GBP", "JPY", "INR", "CAD", "AUD", "CHF", "CNY"];

// ---------- Helpers ----------
const $ = (id) => document.getElementById(id);

async function fetchJSON(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Request failed: ${res.status}`);
    return res.json();
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

// ---------- State ----------
let historyChart = null;

// ---------- Stats strip ----------
async function refreshStats() {
    try {
        const data = await fetchJSON("/api/stats");
        $("stats-strip").innerHTML = `
            <span class="stat-pill">Cache hit rate <strong>${data.cache.hit_rate_pct}%</strong></span>
            <span class="stat-pill">Cache hits <strong>${data.cache.hits}</strong></span>
            <span class="stat-pill">Cache misses <strong>${data.cache.misses}</strong></span>
            <span class="stat-pill">Conversions <strong>${data.conversions_logged}</strong></span>
        `;
    } catch (err) {
        // Silent - stats strip is optional.
    }
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
                    <span class="subtitle">(rate: ${fmt(primary.rate, 6)}${data.date ? ` · ${data.date}` : ""})</span>
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

        // Refresh dependent panels - conversions feed Popular Pairs, and a fresh
        // /api/convert call moves the cache stats too.
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
                .map((p) => `<span class="popular-pill">${p.pair.replace("->", " → ")}<span class="count">${p.count}</span></span>`)
                .join("");
        }

        const recentEl = $("recent-list");
        if (!data.recent.length) {
            recentEl.innerHTML = `<span class="subtitle">No recent conversions.</span>`;
        } else {
            recentEl.innerHTML = data.recent
                .map((r) => `
                    <div class="recent-row">
                        <span>${fmt(r.amount)} ${r.from} → ${fmt(r.converted)} ${r.to}</span>
                        <span class="subtitle">rate ${fmt(r.rate, 4)}</span>
                    </div>
                `)
                .join("");
        }
    } catch (err) {
        // Silent failure - recent list is non-critical.
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
        historyChart = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: `${from} → ${to}`,
                    data: values,
                    borderColor: "#4f8cff",
                    backgroundColor: "rgba(79, 140, 255, 0.15)",
                    tension: 0.25,
                    fill: true,
                    pointRadius: 2,
                }],
            },
            options: {
                responsive: true,
                plugins: {
                    legend: { labels: { color: "#e6edf6" } },
                },
                scales: {
                    x: { ticks: { color: "#8aa0c2" }, grid: { color: "#2a3550" } },
                    y: { ticks: { color: "#8aa0c2" }, grid: { color: "#2a3550" } },
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

        // Populate every dropdown with sensible defaults.
        fillSelect($("from-currency"), currencies, "USD");
        fillSelect($("to-currency"), currencies, "EUR");
        fillSelect($("base-currency"), currencies, "USD");
        fillSelect($("movers-base"), currencies, "USD");
        fillSelect($("hist-from"), currencies, "USD");
        fillSelect($("hist-to"), currencies, "EUR");

        buildCompareCheckboxes();

        // Wire events.
        $("convert-form").addEventListener("submit", handleConvert);
        $("base-currency").addEventListener("change", (e) => loadRates(e.target.value));
        $("movers-base").addEventListener("change", loadMovers);
        $("movers-days").addEventListener("change", loadMovers);
        ["hist-from", "hist-to", "hist-days"].forEach((id) =>
            $(id).addEventListener("change", loadHistory)
        );

        // First load - run in parallel.
        await Promise.all([
            loadRates("USD"),
            loadHistory(),
            loadMovers(),
            loadRecent(),
            refreshStats(),
        ]);

        // Auto-refresh stats every 5s so cache panel feels alive.
        setInterval(refreshStats, 5000);
    } catch (err) {
        console.error("Initialization failed", err);
        document.body.insertAdjacentHTML(
            "afterbegin",
            `<div class="card error" style="margin:1rem;">Failed to initialize: ${err.message}</div>`
        );
    }
}

document.addEventListener("DOMContentLoaded", init);
