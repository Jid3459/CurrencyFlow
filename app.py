"""
CurrencyFlow — Live Currency Exchange & Conversion Dashboard.

Backend Flask service. Fetches data from the free Frankfurter API
(https://www.frankfurter.app), exposes a clean JSON API for the frontend,
and serves the dashboard page.

Features:
  - Latest rates, conversion (single or multi-target), historical trend
  - Top Movers: biggest currency movers vs. a base over a window
  - Recent Conversions log (in-memory ring buffer) + popular pairs
  - In-memory TTL cache for upstream calls with hit/miss counters
  - /api/stats exposes cache + log metrics (will feed Prometheus in Step 3)
"""

import threading
import time
from collections import Counter, deque
from datetime import date, timedelta

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Frankfurter is a free, no-key public API for ECB exchange rates.
FRANKFURTER_BASE_URL = "https://api.frankfurter.app"

# Network call timeout (seconds). Keeps the app responsive if upstream is slow.
HTTP_TIMEOUT = 10

# Cache TTL for upstream responses (seconds). ECB data updates once a day, so
# 60s is a safe balance between freshness and reducing upstream load.
CACHE_TTL_SECONDS = 60

# Maximum recent conversions retained in memory.
RECENT_CONVERSIONS_MAX = 100


# ---------------------------------------------------------------------------
# Thread-safe TTL cache for upstream responses.
# ---------------------------------------------------------------------------
class TTLCache:
    """Tiny in-memory cache with per-entry expiry and hit/miss counters."""

    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._store: dict = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get_or_fetch(self, key: str, fetch_fn):
        """Return cached value if fresh, else call fetch_fn() and cache result."""
        now = time.time()
        with self._lock:
            entry = self._store.get(key)
            if entry and entry[1] > now:
                self.hits += 1
                return entry[0]
            self.misses += 1

        # Fetch outside the lock so other requests aren't blocked on network IO.
        value = fetch_fn()
        with self._lock:
            self._store[key] = (value, now + self.ttl)
        return value

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total else 0.0
            return {
                "hits": self.hits,
                "misses": self.misses,
                "size": len(self._store),
                "hit_rate_pct": round(hit_rate, 2),
            }


cache = TTLCache(CACHE_TTL_SECONDS)

# Ring buffer of recent conversions, plus a lock so concurrent requests are safe.
recent_conversions: deque = deque(maxlen=RECENT_CONVERSIONS_MAX)
conversions_lock = threading.Lock()


def _fetch_json(path: str, params: dict | None = None) -> dict:
    """Call Frankfurter and return JSON. Raises on HTTP errors."""
    response = requests.get(
        f"{FRANKFURTER_BASE_URL}{path}",
        params=params or {},
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Page route — serves the dashboard HTML
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """Render the main dashboard page."""
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Health check — useful for Docker, Jenkins, monitoring later on
# ---------------------------------------------------------------------------
@app.route("/health")
def health():
    return jsonify(status="ok"), 200


# ---------------------------------------------------------------------------
# JSON API endpoints (consumed by the frontend)
# ---------------------------------------------------------------------------
@app.route("/api/currencies")
def list_currencies():
    """Return the list of currencies supported by Frankfurter."""
    data = cache.get_or_fetch("currencies", lambda: _fetch_json("/currencies"))
    return jsonify(data)


@app.route("/api/rates")
def latest_rates():
    """
    Return the latest rates for a base currency.
    Query params: ?base=USD  (default USD)
    """
    base = request.args.get("base", "USD").upper()
    data = cache.get_or_fetch(
        f"latest:{base}",
        lambda: _fetch_json("/latest", {"from": base}),
    )
    return jsonify(data)


@app.route("/api/convert")
def convert():
    """
    Convert an amount from one currency to one or many target currencies.
    Query params:
      from   = source currency (default USD)
      to     = comma-separated target currencies (default EUR)
      amount = numeric amount (default 1)
    """
    from_currency = request.args.get("from", "USD").upper()
    to_param = request.args.get("to", "EUR")
    amount_raw = request.args.get("amount", "1")

    try:
        amount = float(amount_raw)
    except ValueError:
        return jsonify(error="amount must be a number"), 400

    targets = [c.strip().upper() for c in to_param.split(",") if c.strip()]
    if not targets:
        return jsonify(error="at least one target currency required"), 400

    # Anything other than the source currency must be fetched from upstream.
    fetch_targets = sorted({c for c in targets if c != from_currency})

    upstream_rates: dict = {}
    api_date = None
    if fetch_targets:
        cache_key = f"latest:{from_currency}:{','.join(fetch_targets)}"
        data = cache.get_or_fetch(
            cache_key,
            lambda: _fetch_json(
                "/latest",
                {"from": from_currency, "to": ",".join(fetch_targets)},
            ),
        )
        upstream_rates = data.get("rates", {})
        api_date = data.get("date")

    results = []
    for to_c in targets:
        if to_c == from_currency:
            results.append({"to": to_c, "rate": 1.0, "converted": amount})
            continue
        rate = upstream_rates.get(to_c)
        if rate is None:
            results.append({"to": to_c, "error": "rate unavailable"})
            continue
        results.append({"to": to_c, "rate": rate, "converted": rate * amount})

    # Log each successful conversion to the recent buffer.
    timestamp = time.time()
    with conversions_lock:
        for r in results:
            if "error" in r or r["to"] == from_currency:
                continue
            recent_conversions.append({
                "from": from_currency,
                "to": r["to"],
                "amount": amount,
                "converted": r["converted"],
                "rate": r["rate"],
                "timestamp": timestamp,
            })

    return jsonify(
        from_currency=from_currency,
        amount=amount,
        results=results,
        date=api_date,
    )


@app.route("/api/history")
def history():
    """
    Return historical exchange rates between two currencies.
    Query params: ?from=USD&to=EUR&days=30  (default 30)
    """
    from_currency = request.args.get("from", "USD").upper()
    to_currency = request.args.get("to", "EUR").upper()
    days_raw = request.args.get("days", "30")

    try:
        days = max(1, min(365, int(days_raw)))
    except ValueError:
        return jsonify(error="days must be an integer"), 400

    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    range_path = f"/{start_date.isoformat()}..{end_date.isoformat()}"

    data = cache.get_or_fetch(
        f"history:{from_currency}:{to_currency}:{days}",
        lambda: _fetch_json(range_path, {"from": from_currency, "to": to_currency}),
    )
    return jsonify(data)


@app.route("/api/movers")
def movers():
    """
    Return the biggest currency movers against a base over a window.
    Query params: ?base=USD&days=7  (default USD, 7 days)
    """
    base = request.args.get("base", "USD").upper()
    days_raw = request.args.get("days", "7")

    try:
        days = max(1, min(90, int(days_raw)))
    except ValueError:
        return jsonify(error="days must be an integer"), 400

    today_data = cache.get_or_fetch(
        f"latest:{base}",
        lambda: _fetch_json("/latest", {"from": base}),
    )
    past_iso = (date.today() - timedelta(days=days)).isoformat()
    past_data = cache.get_or_fetch(
        f"date:{past_iso}:{base}",
        lambda: _fetch_json(f"/{past_iso}", {"from": base}),
    )

    today_rates = today_data.get("rates", {})
    past_rates = past_data.get("rates", {})

    movers_list = []
    for code, today_rate in today_rates.items():
        past_rate = past_rates.get(code)
        if past_rate in (None, 0):
            continue
        # Positive % means the foreign currency strengthened vs the base.
        # (rate today < rate past => 1 base buys less foreign => foreign got stronger)
        change_pct = ((past_rate - today_rate) / past_rate) * 100
        movers_list.append({
            "currency": code,
            "rate_today": today_rate,
            "rate_past": past_rate,
            "change_pct": round(change_pct, 4),
        })

    movers_list.sort(key=lambda m: abs(m["change_pct"]), reverse=True)

    return jsonify(
        base=base,
        days=days,
        as_of=today_data.get("date"),
        compared_to=past_data.get("date"),
        movers=movers_list[:10],
    )


@app.route("/api/recent-conversions")
def recent_conversions_endpoint():
    """Return the recent conversions log + most popular pairs."""
    with conversions_lock:
        items = list(recent_conversions)

    pair_counts = Counter(f"{i['from']}->{i['to']}" for i in items)
    popular = [
        {"pair": pair, "count": count}
        for pair, count in pair_counts.most_common(10)
    ]

    return jsonify(
        recent=list(reversed(items[-25:])),  # most recent first
        popular=popular,
        total=len(items),
    )


@app.route("/api/stats")
def stats():
    """
    Internal stats endpoint — exposes cache + conversion counters.
    This is the precursor to /metrics (Prometheus) in Step 3.
    """
    with conversions_lock:
        conv_count = len(recent_conversions)
    return jsonify(
        cache=cache.stats(),
        conversions_logged=conv_count,
    )


# ---------------------------------------------------------------------------
# Entry point for local development
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
