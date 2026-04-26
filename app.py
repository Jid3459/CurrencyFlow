"""
CurrencyFlow - Live Currency Exchange & Conversion Dashboard.

Backend Flask service. Fetches data from the free Frankfurter API
(https://www.frankfurter.app), exposes a clean JSON API for the frontend,
and serves the dashboard page.

Features:
  - Latest rates, conversion (single or multi-target), historical trend
  - Top Movers: biggest currency movers vs. a base over a window
  - Recent Conversions log (in-memory ring buffer) + popular pairs
  - In-memory TTL cache for upstream calls with hit/miss counters
  - Watchlist of pinned currency pairs (in-memory, single tenant)
  - "Best time to convert" insight (current rate vs 30-day average)
  - Rate Alerts: background poller triggers alerts when thresholds cross
  - /api/stats exposes cache + log counters (used by the frontend)
  - /metrics exposes Prometheus-formatted metrics for scraping
"""

import os
import threading
import time
import uuid
from collections import Counter, deque
from datetime import date, timedelta

import requests
from flask import Flask, Response, g, jsonify, render_template, request
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter as PromCounter,
    Histogram,
    generate_latest,
)

app = Flask(__name__)

# Frankfurter is a free, no-key public API for ECB exchange rates.
FRANKFURTER_BASE_URL = "https://api.frankfurter.app"

# Network call timeout (seconds). Keeps the app responsive if upstream is slow.
HTTP_TIMEOUT = 10

# Cache TTL for upstream responses (seconds).
CACHE_TTL_SECONDS = 60

# Maximum recent conversions retained in memory.
RECENT_CONVERSIONS_MAX = 100

# Background alert checker poll interval (seconds).
ALERTS_POLL_SECONDS = 60


# ---------------------------------------------------------------------------
# Prometheus metrics.
# ---------------------------------------------------------------------------
HTTP_REQUESTS = PromCounter(
    "currencyflow_http_requests_total",
    "Total HTTP requests served by CurrencyFlow.",
    ["method", "endpoint", "status"],
)

HTTP_LATENCY = Histogram(
    "currencyflow_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["endpoint"],
)

CONVERSIONS = PromCounter(
    "currencyflow_conversions_total",
    "Total currency conversions performed.",
    ["from_currency", "to_currency"],
)

CACHE_HITS = PromCounter(
    "currencyflow_cache_hits_total",
    "Number of times a cached upstream response was served.",
)

CACHE_MISSES = PromCounter(
    "currencyflow_cache_misses_total",
    "Number of times the cache missed and we fetched from upstream.",
)

UPSTREAM_LATENCY = Histogram(
    "currencyflow_upstream_request_duration_seconds",
    "Latency of calls to the Frankfurter upstream API.",
)

ALERTS_TRIGGERED = PromCounter(
    "currencyflow_alerts_triggered_total",
    "Total rate alerts that have triggered since startup.",
    ["from_currency", "to_currency", "op"],
)


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
                CACHE_HITS.inc()
                return entry[0]
            self.misses += 1
            CACHE_MISSES.inc()

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

# Watchlist of (from, to) tuples and rate alerts. In-memory, single tenant.
# Both rely on gunicorn running with --workers 1 --threads N to keep one
# shared memory space; multi-worker setups would split this state.
watchlist: set = set()
watchlist_lock = threading.Lock()

alerts: dict = {}  # alert_id -> alert dict
alerts_lock = threading.Lock()


def _fetch_json(path: str, params: dict | None = None) -> dict:
    """Call Frankfurter and return JSON. Raises on HTTP errors."""
    start = time.time()
    try:
        response = requests.get(
            f"{FRANKFURTER_BASE_URL}{path}",
            params=params or {},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    finally:
        UPSTREAM_LATENCY.observe(time.time() - start)


# ---------------------------------------------------------------------------
# HTTP middleware - record latency + count for every request.
# ---------------------------------------------------------------------------
@app.before_request
def _start_timer():
    g.start_time = time.time()


@app.after_request
def _record_metrics(response):
    endpoint = request.url_rule.rule if request.url_rule else request.path
    elapsed = time.time() - getattr(g, "start_time", time.time())
    HTTP_LATENCY.labels(endpoint=endpoint).observe(elapsed)
    HTTP_REQUESTS.labels(
        method=request.method,
        endpoint=endpoint,
        status=str(response.status_code),
    ).inc()
    return response


# ---------------------------------------------------------------------------
# Page route + health + metrics
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify(status="ok"), 200


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# JSON API endpoints
# ---------------------------------------------------------------------------
@app.route("/api/currencies")
def list_currencies():
    """Return the list of currencies supported by Frankfurter."""
    data = cache.get_or_fetch("currencies", lambda: _fetch_json("/currencies"))
    return jsonify(data)


@app.route("/api/rates")
def latest_rates():
    """Return the latest rates for a base currency. Query: ?base=USD"""
    base = request.args.get("base", "USD").upper()
    data = cache.get_or_fetch(
        f"latest:{base}",
        lambda: _fetch_json("/latest", {"from": base}),
    )
    return jsonify(data)


@app.route("/api/convert")
def convert():
    """Convert an amount from one currency to one or many target currencies."""
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
            CONVERSIONS.labels(
                from_currency=from_currency, to_currency=r["to"]
            ).inc()

    return jsonify(
        from_currency=from_currency,
        amount=amount,
        results=results,
        date=api_date,
    )


@app.route("/api/history")
def history():
    """Return historical exchange rates between two currencies."""
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
    """Return the biggest currency movers against a base over a window."""
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
        recent=list(reversed(items[-25:])),
        popular=popular,
        total=len(items),
    )


@app.route("/api/stats")
def stats():
    """Internal stats - cache + conversion + watchlist + alerts counters."""
    with conversions_lock:
        conv_count = len(recent_conversions)
    with watchlist_lock:
        watchlist_size = len(watchlist)
    with alerts_lock:
        active = sum(1 for a in alerts.values() if not a["triggered_at"])
        triggered = sum(1 for a in alerts.values() if a["triggered_at"])
    return jsonify(
        cache=cache.stats(),
        conversions_logged=conv_count,
        watchlist_size=watchlist_size,
        alerts_active=active,
        alerts_triggered=triggered,
    )


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
def _watchlist_payload() -> list[dict]:
    """Return current watchlist with live rates merged in."""
    with watchlist_lock:
        pairs = sorted(watchlist)

    items = []
    for from_c, to_c in pairs:
        try:
            data = cache.get_or_fetch(
                f"latest:{from_c}:{to_c}",
                lambda fc=from_c, tc=to_c: _fetch_json(
                    "/latest", {"from": fc, "to": tc}
                ),
            )
            rate = data.get("rates", {}).get(to_c)
            items.append({
                "from": from_c,
                "to": to_c,
                "rate": rate,
                "date": data.get("date"),
            })
        except requests.RequestException:
            items.append({"from": from_c, "to": to_c, "error": "rate unavailable"})
    return items


@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    return jsonify(items=_watchlist_payload())


@app.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    payload = request.get_json(silent=True) or request.form or request.args
    from_c = (payload.get("from") or "").upper()
    to_c = (payload.get("to") or "").upper()

    if not from_c or not to_c:
        return jsonify(error="'from' and 'to' are required"), 400
    if from_c == to_c:
        return jsonify(error="'from' and 'to' must differ"), 400

    with watchlist_lock:
        watchlist.add((from_c, to_c))
        size = len(watchlist)
    return jsonify(ok=True, size=size, pair=f"{from_c}->{to_c}"), 201


@app.route("/api/watchlist/<from_c>/<to_c>", methods=["DELETE"])
def remove_from_watchlist(from_c, to_c):
    from_c, to_c = from_c.upper(), to_c.upper()
    with watchlist_lock:
        existed = (from_c, to_c) in watchlist
        watchlist.discard((from_c, to_c))
        size = len(watchlist)
    return jsonify(ok=existed, size=size)


# ---------------------------------------------------------------------------
# "Best time to convert" insight
# ---------------------------------------------------------------------------
@app.route("/api/insight")
def insight():
    """
    Compare current rate against the 30-day average and tell the user
    whether now looks like a relatively good time to convert.
    Query: ?from=USD&to=EUR
    """
    from_c = request.args.get("from", "USD").upper()
    to_c = request.args.get("to", "EUR").upper()

    if from_c == to_c:
        return jsonify(error="'from' and 'to' must differ"), 400

    latest = cache.get_or_fetch(
        f"latest:{from_c}:{to_c}",
        lambda: _fetch_json("/latest", {"from": from_c, "to": to_c}),
    )
    current = latest.get("rates", {}).get(to_c)

    end = date.today()
    start = end - timedelta(days=30)
    history_data = cache.get_or_fetch(
        f"history:{from_c}:{to_c}:30",
        lambda: _fetch_json(
            f"/{start.isoformat()}..{end.isoformat()}",
            {"from": from_c, "to": to_c},
        ),
    )
    points = [
        r[to_c] for r in history_data.get("rates", {}).values() if to_c in r
    ]

    if not points or current is None:
        return jsonify(
            from_currency=from_c,
            to_currency=to_c,
            message="Not enough history yet to make a recommendation.",
        )

    avg_30d = sum(points) / len(points)
    pct_vs_avg = ((current - avg_30d) / avg_30d) * 100 if avg_30d else 0.0

    if pct_vs_avg > 1.0:
        verdict = "good"
        message = (
            f"Rate is {pct_vs_avg:.1f}% above the 30-day average - "
            f"a relatively good time to convert {from_c} to {to_c}."
        )
    elif pct_vs_avg < -1.0:
        verdict = "wait"
        message = (
            f"Rate is {abs(pct_vs_avg):.1f}% below the 30-day average - "
            f"you might want to wait if you can."
        )
    else:
        verdict = "neutral"
        message = "Rate is close to the 30-day average."

    return jsonify(
        from_currency=from_c,
        to_currency=to_c,
        current=current,
        avg_30d=round(avg_30d, 6),
        min_30d=min(points),
        max_30d=max(points),
        pct_vs_avg=round(pct_vs_avg, 2),
        verdict=verdict,
        message=message,
    )


# ---------------------------------------------------------------------------
# Rate alerts
# ---------------------------------------------------------------------------
@app.route("/api/alerts", methods=["GET"])
def list_alerts():
    with alerts_lock:
        items = sorted(alerts.values(), key=lambda a: a["created_at"], reverse=True)
    return jsonify(alerts=items, total=len(items))


@app.route("/api/alerts", methods=["POST"])
def create_alert():
    payload = request.get_json(silent=True) or {}
    from_c = (payload.get("from") or "").upper()
    to_c = (payload.get("to") or "").upper()
    op = (payload.get("op") or "above").lower()

    try:
        threshold = float(payload.get("threshold"))
    except (TypeError, ValueError):
        return jsonify(error="'threshold' must be a number"), 400

    if not from_c or not to_c:
        return jsonify(error="'from' and 'to' are required"), 400
    if from_c == to_c:
        return jsonify(error="'from' and 'to' must differ"), 400
    if op not in ("above", "below"):
        return jsonify(error="'op' must be 'above' or 'below'"), 400

    alert_id = uuid.uuid4().hex[:8]
    new_alert = {
        "id": alert_id,
        "from": from_c,
        "to": to_c,
        "op": op,
        "threshold": threshold,
        "created_at": time.time(),
        "triggered_at": None,
        "last_rate": None,
    }
    with alerts_lock:
        alerts[alert_id] = new_alert
    return jsonify(alert=new_alert), 201


@app.route("/api/alerts/<alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    with alerts_lock:
        existed = alerts.pop(alert_id, None) is not None
    return jsonify(ok=existed)


def _check_alerts_once():
    """Single pass over pending alerts. Pulled out for testability."""
    with alerts_lock:
        pending = [a for a in alerts.values() if not a["triggered_at"]]

    if not pending:
        return

    # Group by 'from' currency to minimize upstream calls.
    grouped: dict[str, set] = {}
    for a in pending:
        grouped.setdefault(a["from"], set()).add(a["to"])

    for from_c, to_set in grouped.items():
        to_list = ",".join(sorted(to_set))
        try:
            data = cache.get_or_fetch(
                f"latest:{from_c}:{to_list}",
                lambda fc=from_c, tl=to_list: _fetch_json(
                    "/latest", {"from": fc, "to": tl}
                ),
            )
        except requests.RequestException:
            continue  # transient network blip; retry on next cycle

        rates = data.get("rates", {})
        with alerts_lock:
            for a in alerts.values():
                if a["triggered_at"] or a["from"] != from_c:
                    continue
                current = rates.get(a["to"])
                if current is None:
                    continue
                a["last_rate"] = current
                triggered = (
                    (a["op"] == "above" and current >= a["threshold"])
                    or (a["op"] == "below" and current <= a["threshold"])
                )
                if triggered:
                    a["triggered_at"] = time.time()
                    ALERTS_TRIGGERED.labels(
                        from_currency=a["from"],
                        to_currency=a["to"],
                        op=a["op"],
                    ).inc()


def _alerts_loop():
    """Long-running background loop. Runs in a daemon thread."""
    while True:
        try:
            _check_alerts_once()
        except Exception:
            # Never let an exception kill the daemon.
            pass
        time.sleep(ALERTS_POLL_SECONDS)


def _start_alerts_thread():
    t = threading.Thread(target=_alerts_loop, name="alerts-checker", daemon=True)
    t.start()


# Start the alerts background thread when the module is imported under
# gunicorn / `python app.py`. Disabled in tests via env var so that the
# poller doesn't make real HTTP calls during pytest runs.
if os.environ.get("DISABLE_BACKGROUND_TASKS") != "1":
    _start_alerts_thread()


# ---------------------------------------------------------------------------
# Entry point for local development
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
