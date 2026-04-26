"""
Unit tests for CurrencyFlow.

We mock all calls to Frankfurter using `responses` so tests are fast,
deterministic, and run offline. SonarQube reads the coverage report
produced by `pytest --cov`.
"""

import re

import pytest
import responses

import app as app_module
from app import (
    FRANKFURTER_BASE_URL,
    _check_alerts_once,
    alerts,
    app,
    cache,
    recent_conversions,
    watchlist,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """Reset module-level state between tests so they don't leak."""
    cache._store.clear()
    cache.hits = 0
    cache.misses = 0
    recent_conversions.clear()
    watchlist.clear()
    alerts.clear()
    yield


@pytest.fixture
def mocked_frankfurter():
    """Stub the upstream Frankfurter API for the duration of a test."""
    # assert_all_requests_are_fired=False so individual tests don't need to
    # call every registered route. Regexes are anchored at the start only;
    # URLs may carry query strings (?from=USD&to=EUR) that we don't constrain.
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            f"{FRANKFURTER_BASE_URL}/currencies",
            json={"USD": "US Dollar", "EUR": "Euro", "GBP": "British Pound"},
            status=200,
        )
        rsps.add(
            responses.GET,
            f"{FRANKFURTER_BASE_URL}/latest",
            json={
                "amount": 1.0,
                "base": "USD",
                "date": "2026-04-24",
                "rates": {"EUR": 0.85, "GBP": 0.74, "JPY": 159.4},
            },
            status=200,
        )
        # Range path "/YYYY-MM-DD..YYYY-MM-DD" - register BEFORE the single-date
        # pattern so it wins precedence (responses tries patterns in order).
        rsps.add(
            responses.GET,
            re.compile(
                rf"{re.escape(FRANKFURTER_BASE_URL)}/\d{{4}}-\d{{2}}-\d{{2}}\.\.\d{{4}}-\d{{2}}-\d{{2}}"
            ),
            json={
                "amount": 1.0,
                "base": "USD",
                "start_date": "2026-03-25",
                "end_date": "2026-04-24",
                "rates": {
                    "2026-04-23": {"EUR": 0.84},
                    "2026-04-24": {"EUR": 0.85},
                },
            },
            status=200,
        )
        # Single-date path "/YYYY-MM-DD" (used by /api/movers).
        rsps.add(
            responses.GET,
            re.compile(rf"{re.escape(FRANKFURTER_BASE_URL)}/\d{{4}}-\d{{2}}-\d{{2}}(?!\.)"),
            json={
                "amount": 1.0,
                "base": "USD",
                "date": "2026-04-17",
                "rates": {"EUR": 0.87, "GBP": 0.76, "JPY": 161.0},
            },
            status=200,
        )
        yield rsps


# ---------------------------------------------------------------------------
# Health + index
# ---------------------------------------------------------------------------
def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_index_returns_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"CurrencyFlow" in response.data


def test_metrics_endpoint_returns_prometheus_format(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.data.decode()
    assert "currencyflow_http_requests_total" in body
    assert "currencyflow_cache_hits_total" in body


# ---------------------------------------------------------------------------
# /api/currencies + /api/rates
# ---------------------------------------------------------------------------
def test_currencies(client, mocked_frankfurter):
    response = client.get("/api/currencies")
    assert response.status_code == 200
    assert "USD" in response.json
    assert "EUR" in response.json


def test_latest_rates(client, mocked_frankfurter):
    response = client.get("/api/rates?base=USD")
    assert response.status_code == 200
    assert response.json["base"] == "USD"
    assert response.json["rates"]["EUR"] == 0.85


# ---------------------------------------------------------------------------
# /api/convert
# ---------------------------------------------------------------------------
def test_convert_single_target(client, mocked_frankfurter):
    response = client.get("/api/convert?from=USD&to=EUR&amount=100")
    assert response.status_code == 200
    payload = response.json
    assert payload["from_currency"] == "USD"
    assert payload["amount"] == 100.0
    assert payload["results"][0]["to"] == "EUR"
    assert payload["results"][0]["converted"] == pytest.approx(85.0)


def test_convert_multi_target(client, mocked_frankfurter):
    response = client.get("/api/convert?from=USD&to=EUR,GBP,JPY&amount=10")
    assert response.status_code == 200
    targets = {r["to"]: r for r in response.json["results"]}
    assert targets["EUR"]["converted"] == pytest.approx(8.5)
    assert targets["GBP"]["converted"] == pytest.approx(7.4)
    assert targets["JPY"]["converted"] == pytest.approx(1594.0)


def test_convert_same_currency_short_circuits(client, mocked_frankfurter):
    response = client.get("/api/convert?from=USD&to=USD&amount=42")
    assert response.status_code == 200
    result = response.json["results"][0]
    assert result["to"] == "USD"
    assert result["converted"] == 42.0
    assert result["rate"] == 1.0


def test_convert_invalid_amount_returns_400(client, mocked_frankfurter):
    response = client.get("/api/convert?from=USD&to=EUR&amount=abc")
    assert response.status_code == 400
    assert "amount must be a number" in response.json["error"]


def test_convert_logs_to_recent(client, mocked_frankfurter):
    client.get("/api/convert?from=USD&to=EUR&amount=10")
    assert len(recent_conversions) == 1
    last = recent_conversions[-1]
    assert last["from"] == "USD"
    assert last["to"] == "EUR"


# ---------------------------------------------------------------------------
# /api/movers
# ---------------------------------------------------------------------------
def test_movers_returns_sorted_changes(client, mocked_frankfurter):
    response = client.get("/api/movers?base=USD&days=7")
    assert response.status_code == 200
    payload = response.json
    assert payload["base"] == "USD"
    assert payload["days"] == 7
    assert isinstance(payload["movers"], list)
    if payload["movers"]:
        assert "currency" in payload["movers"][0]
        assert "change_pct" in payload["movers"][0]


def test_movers_invalid_days_returns_400(client, mocked_frankfurter):
    response = client.get("/api/movers?base=USD&days=notanumber")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# /api/history
# ---------------------------------------------------------------------------
def test_history(client, mocked_frankfurter):
    response = client.get("/api/history?from=USD&to=EUR&days=30")
    assert response.status_code == 200
    assert "rates" in response.json


def test_history_clamps_days_to_safe_range(client, mocked_frankfurter):
    # Year 9999 would blow up; we expect days to be clamped (1..365).
    response = client.get("/api/history?from=USD&to=EUR&days=99999")
    assert response.status_code == 200


def test_history_invalid_days_returns_400(client, mocked_frankfurter):
    response = client.get("/api/history?from=USD&to=EUR&days=abc")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# /api/stats + /api/recent-conversions
# ---------------------------------------------------------------------------
def test_stats_starts_clean(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    assert response.json["cache"]["hits"] == 0
    assert response.json["cache"]["misses"] == 0


def test_recent_conversions_aggregates_popular(client, mocked_frankfurter):
    # Two USD->EUR + one USD->GBP -> popular should sort EUR first.
    client.get("/api/convert?from=USD&to=EUR&amount=1")
    client.get("/api/convert?from=USD&to=EUR&amount=2")
    client.get("/api/convert?from=USD&to=GBP&amount=3")

    response = client.get("/api/recent-conversions")
    assert response.status_code == 200
    popular = response.json["popular"]
    assert popular[0]["pair"] == "USD->EUR"
    assert popular[0]["count"] == 2


# ---------------------------------------------------------------------------
# TTL cache behavior
# ---------------------------------------------------------------------------
def test_cache_returns_cached_value_on_repeat_call():
    calls = []

    def fetch():
        calls.append(1)
        return {"value": len(calls)}

    first = cache.get_or_fetch("k", fetch)
    second = cache.get_or_fetch("k", fetch)

    assert first == second == {"value": 1}
    assert len(calls) == 1
    assert cache.hits == 1
    assert cache.misses == 1


def test_cache_stats_reports_hit_rate():
    cache.get_or_fetch("a", lambda: 1)  # miss
    cache.get_or_fetch("a", lambda: 1)  # hit
    cache.get_or_fetch("a", lambda: 1)  # hit

    stats = cache.stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_rate_pct"] == pytest.approx(66.67, abs=0.1)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
def test_watchlist_add_and_list(client, mocked_frankfurter):
    add = client.post("/api/watchlist", json={"from": "USD", "to": "EUR"})
    assert add.status_code == 201
    assert add.json["size"] == 1
    assert add.json["pair"] == "USD->EUR"

    listing = client.get("/api/watchlist")
    assert listing.status_code == 200
    items = listing.json["items"]
    assert len(items) == 1
    assert items[0]["from"] == "USD"
    assert items[0]["to"] == "EUR"
    assert items[0]["rate"] == 0.85


def test_watchlist_rejects_same_currency(client):
    response = client.post("/api/watchlist", json={"from": "USD", "to": "USD"})
    assert response.status_code == 400


def test_watchlist_rejects_missing_fields(client):
    response = client.post("/api/watchlist", json={"from": "USD"})
    assert response.status_code == 400


def test_watchlist_remove(client, mocked_frankfurter):
    client.post("/api/watchlist", json={"from": "USD", "to": "EUR"})
    response = client.delete("/api/watchlist/USD/EUR")
    assert response.status_code == 200
    assert response.json["ok"] is True
    assert response.json["size"] == 0


def test_watchlist_remove_nonexistent_returns_ok_false(client):
    response = client.delete("/api/watchlist/USD/JPY")
    assert response.status_code == 200
    assert response.json["ok"] is False


# ---------------------------------------------------------------------------
# /api/insight
# ---------------------------------------------------------------------------
def test_insight_returns_verdict(client, mocked_frankfurter):
    response = client.get("/api/insight?from=USD&to=EUR")
    assert response.status_code == 200
    payload = response.json
    assert payload["from_currency"] == "USD"
    assert payload["to_currency"] == "EUR"
    assert payload["current"] == 0.85
    assert "verdict" in payload
    assert payload["verdict"] in ("good", "wait", "neutral")


def test_insight_rejects_same_currency(client):
    response = client.get("/api/insight?from=USD&to=USD")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# /api/alerts CRUD
# ---------------------------------------------------------------------------
def test_alerts_create_and_list(client):
    create = client.post(
        "/api/alerts",
        json={"from": "USD", "to": "EUR", "op": "above", "threshold": 0.95},
    )
    assert create.status_code == 201
    alert = create.json["alert"]
    assert alert["from"] == "USD"
    assert alert["op"] == "above"
    assert alert["threshold"] == 0.95
    assert alert["triggered_at"] is None

    listing = client.get("/api/alerts")
    assert listing.status_code == 200
    assert listing.json["total"] == 1


def test_alerts_create_validates_threshold(client):
    response = client.post(
        "/api/alerts",
        json={"from": "USD", "to": "EUR", "op": "above", "threshold": "abc"},
    )
    assert response.status_code == 400


def test_alerts_create_validates_op(client):
    response = client.post(
        "/api/alerts",
        json={"from": "USD", "to": "EUR", "op": "sideways", "threshold": 1},
    )
    assert response.status_code == 400


def test_alerts_delete(client):
    create = client.post(
        "/api/alerts",
        json={"from": "USD", "to": "EUR", "op": "above", "threshold": 0.95},
    )
    alert_id = create.json["alert"]["id"]

    delete = client.delete(f"/api/alerts/{alert_id}")
    assert delete.status_code == 200
    assert delete.json["ok"] is True

    listing = client.get("/api/alerts")
    assert listing.json["total"] == 0


# ---------------------------------------------------------------------------
# Background alerts checker
# ---------------------------------------------------------------------------
def test_check_alerts_triggers_when_above_threshold(client, mocked_frankfurter):
    # Mocked rate is USD->EUR = 0.85. Threshold is 0.80, op=above => triggers.
    client.post(
        "/api/alerts",
        json={"from": "USD", "to": "EUR", "op": "above", "threshold": 0.80},
    )

    _check_alerts_once()

    listing = client.get("/api/alerts")
    triggered = listing.json["alerts"][0]
    assert triggered["triggered_at"] is not None
    assert triggered["last_rate"] == 0.85


def test_check_alerts_does_not_trigger_when_below_threshold(client, mocked_frankfurter):
    # Mocked rate is USD->EUR = 0.85. Threshold is 0.90, op=above => doesn't trigger.
    client.post(
        "/api/alerts",
        json={"from": "USD", "to": "EUR", "op": "above", "threshold": 0.90},
    )

    _check_alerts_once()

    listing = client.get("/api/alerts")
    a = listing.json["alerts"][0]
    assert a["triggered_at"] is None
    assert a["last_rate"] == 0.85  # we observed it, just didn't trigger


def test_check_alerts_below_op(client, mocked_frankfurter):
    # Mocked rate is 0.85. Threshold 0.90, op=below => triggers.
    client.post(
        "/api/alerts",
        json={"from": "USD", "to": "EUR", "op": "below", "threshold": 0.90},
    )

    _check_alerts_once()

    listing = client.get("/api/alerts")
    assert listing.json["alerts"][0]["triggered_at"] is not None
