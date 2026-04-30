# CurrencyFlow

> Live currency exchange dashboard with a complete CI/CD pipeline - built as a DevOps mini-project.

A real-time currency conversion app wrapped in a fully automated software delivery pipeline. Push code, walk away, and watch tests run, code get scanned, a new image build, and the live app redeploy itself - no clicks in between.

[![Docker Hub](https://img.shields.io/badge/docker%20hub-jid345%2Fcurrencyflow-2496ed?logo=docker&logoColor=white)](https://hub.docker.com/r/jid345/currencyflow)
[![Python](https://img.shields.io/badge/python-3.13-3776ab?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/flask-3.0-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/tests-33%20passing-34d3a6)](./tests)
[![Coverage](https://img.shields.io/badge/coverage-92%25-34d3a6)](./tests)

---

## Table of Contents

- [What It Does](#what-it-does)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Features](#features)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [The CI/CD Pipeline](#the-cicd-pipeline)
- [API Reference](#api-reference)
- [Observability](#observability)
- [Contributing](#contributing)

---

## What It Does

CurrencyFlow is a single-page web app for tracking and converting currencies in real time. Beyond the basics, it offers:

- **Multi-target conversion** - convert 100 USD into EUR, GBP, and JPY simultaneously
- **Pinned watchlist** - keep an eye on the pairs that matter to you
- **"Best time to convert" insight** - compares the current rate against the 30-day average and gives you a verdict (good / wait / neutral)
- **Rate alerts** - set thresholds like "USD → EUR goes above 0.95" and a background poller fires the alert automatically
- **Top movers** - see which currencies have moved the most against a base over a configurable window
- **Historical trend chart** - 7 to 180 days of ECB-sourced data, rendered with Chart.js
- **Live observability** - every action feeds Prometheus metrics that Grafana visualises in real time

Data comes from the free [Frankfurter API](https://www.frankfurter.app) (European Central Bank rates, no API key needed).

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | Vanilla HTML / CSS / JS + [Chart.js](https://www.chartjs.org/) | No build step, fast page loads, easy to read |
| Web framework | [Flask](https://flask.palletsprojects.com/) 3.0 + [gunicorn](https://gunicorn.org/) | Minimal overhead; gunicorn for production-grade concurrency |
| Language | Python 3.13 | Tooling support, type hints |
| External data | [Frankfurter API](https://www.frankfurter.app) | Free, no API key, ECB-sourced |
| Containerisation | [Docker](https://www.docker.com/) + [docker-compose](https://docs.docker.com/compose/) | Reproducible environments, one-command stack |
| CI/CD | [Jenkins](https://www.jenkins.io/) (with Pipeline-as-Code) | Industry standard, polls GitHub for changes |
| Code quality | [SonarQube](https://www.sonarsource.com/products/sonarqube/) Community 10.7 | Bugs, security, coverage, complexity, all enforced via a Quality Gate |
| Metrics | [Prometheus](https://prometheus.io/) 2.55 | Pull-based time-series database |
| Visualisation | [Grafana](https://grafana.com/) 11.4 | Auto-provisioned 8-panel dashboard |
| Source control | Git + GitHub | Single source of truth |
| Image registry | [Docker Hub](https://hub.docker.com/r/jid345/currencyflow) | Public image, runnable anywhere |
| Testing | [pytest](https://pytest.org/) + [responses](https://github.com/getsentry/responses) | Mocked external API for deterministic tests |

---

## Architecture

```
                                 ┌───────────────────────────┐
                                 │       Developer (you)     │
                                 │      `git push origin`    │
                                 └────────────┬──────────────┘
                                              │
                                              ▼
                                 ┌───────────────────────────┐
                                 │       GitHub (remote)     │
                                 └────────────┬──────────────┘
                                              │  (Jenkins polls every minute)
                                              ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │                          Jenkins Pipeline                              │
   │  Checkout -> Tests -> SonarQube -> Build image -> Deploy container    │
   └─────────────────┬────────────────────────────┬────────────────────────┘
                     │                            │
              (Quality Gate)                 (rebuilds + restarts)
                     ▼                            ▼
   ┌────────────────────────────┐   ┌───────────────────────────────────┐
   │       SonarQube            │   │          App container            │
   │  scans code, coverage,     │   │   Flask + gunicorn on port 5000   │
   │  bugs, vulnerabilities     │   │   Exposes /metrics endpoint       │
   └────────────────────────────┘   └────────────────┬──────────────────┘
                                                     │  (Prometheus scrapes /metrics every 15s)
                                                     ▼
                                    ┌───────────────────────────────────┐
                                    │            Prometheus             │
                                    │   Stores time-series metrics      │
                                    └────────────────┬──────────────────┘
                                                     │  (Grafana queries via PromQL)
                                                     ▼
                                    ┌───────────────────────────────────┐
                                    │             Grafana               │
                                    │   8-panel live dashboard          │
                                    └───────────────────────────────────┘
```

Three loops run independently:
- **CI/CD loop** (Jenkins ↔ Git ↔ SonarQube ↔ Docker) - triggered by `git push`, runs once per push.
- **Observability loop** (App ↔ Prometheus ↔ Grafana) - always running, scrapes every 15s.
- **User loop** (Browser ↔ App ↔ Frankfurter) - on-demand when users interact.

---

## Features

### Frontend
- Polished dark theme with Inter typography and a custom SVG mark
- Responsive layout that holds up from mobile to desktop
- Multi-currency conversion with comparison checkboxes
- Pinned watchlist with live rate refresh
- Historical Chart.js trend with smart x-axis tick limiting (no rotated label spaghetti)
- Header stats strip: cache hit rate, conversions, watchlist size, alerts active/triggered
- Auto-refreshing panels (5s for stats, 15s for alerts, 60s for watchlist)

### Backend
- 11 JSON endpoints, all instrumented for Prometheus
- TTL cache (60s default) wraps every upstream call - dramatic latency reduction at scale
- Background daemon thread polls upstream every 60s to evaluate rate alerts
- Recent conversions ring buffer (in-memory, last 100) with popular-pairs aggregation
- Health check endpoint for Docker / load balancer probes
- 33 unit tests with HTTP mocking via `responses`, ~92% line coverage

---

## Quick Start

### Prerequisites
- Docker Desktop (with WSL2 backend on Windows)
- Git
- Optional: Python 3.13 if you want to run the app directly without Docker

### Run with Docker (recommended)

Pull and run the published image:

```bash
docker run -d -p 5000:5000 jid345/currencyflow:latest
```

Open http://localhost:5000.

### Run the full stack (app + monitoring + CI tooling)

```bash
git clone https://github.com/Jid3459/CurrencyFlow.git
cd CurrencyFlow
docker compose --profile quality --profile ci up -d
```

This brings up 5 containers:

| Service | URL | Default credentials |
|---------|-----|---------------------|
| App | http://localhost:5000 | (none) |
| Prometheus | http://localhost:9090 | (none) |
| Grafana | http://localhost:3000 | admin / admin (forced reset on first login) |
| SonarQube | http://localhost:9000 | admin / admin (forced reset on first login) |
| Jenkins | http://localhost:8080 | First-run wizard, password from container logs |

Get the Jenkins initial admin password:

```bash
docker exec currencyflow-jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

### Lightweight (just app + monitoring, ~700 MB RAM)

```bash
docker compose up -d
```

Skips Jenkins and SonarQube.

### Run locally with Python (development)

```bash
python -m venv venv
.\venv\Scripts\activate            # Windows
# source venv/bin/activate         # macOS/Linux
pip install -r requirements-dev.txt
python app.py
```

App runs at http://localhost:5000 with Flask's dev server (auto-reload on changes).

---

## Project Structure

```
CurrencyFlow/
├── app.py                        # Flask backend - all endpoints + alerts thread
├── requirements.txt              # Production dependencies
├── requirements-dev.txt          # Test dependencies (extends requirements.txt)
├── Dockerfile                    # Recipe for the app image
├── .dockerignore
├── docker-compose.yml            # Orchestrates ALL services
├── Jenkinsfile                   # Pipeline-as-code (6 stages)
├── sonar-project.properties      # SonarQube scanner config
├── pytest.ini                    # Pytest + coverage config
│
├── templates/
│   └── index.html                # Dashboard structure
│
├── static/
│   ├── style.css                 # Polished dark theme
│   └── app.js                    # Frontend logic (vanilla JS)
│
├── tests/
│   ├── conftest.py               # Disables alert thread during tests
│   └── test_app.py               # 33 unit tests, ~92% coverage
│
├── jenkins/
│   └── Dockerfile                # Custom Jenkins image (Python + Docker CLI + sonar-scanner)
│
├── prometheus/
│   └── prometheus.yml            # Scrape config
│
├── grafana/
│   └── provisioning/
│       ├── datasources/          # Prometheus datasource (auto-loaded)
│       └── dashboards/           # 8-panel CurrencyFlow Overview (auto-loaded)
│
├── DEMO_GUIDE.md                 # Step-by-step demo playbook for the team
└── README.md                     # ← you are here
```

---

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Output:
```
================================ test session starts =================================
collected 33 items

tests/test_app.py ............................. [ 88%]
tests/test_app.py ....                            [100%]

---------- coverage: platform win32, python 3.13.2-final-0 ----------
Name     Stmts   Miss  Cover
----------------------------
app.py     320     27    92%
----------------------------
TOTAL      320     27    92%

================================ 33 passed in 5.31s =================================
```

The tests **mock all calls to Frankfurter** via the `responses` library, so they're fast, deterministic, and run offline. Coverage XML is emitted to `coverage.xml` for SonarQube to pick up.

---

## The CI/CD Pipeline

Jenkins polls GitHub every 60 seconds. On a new commit to `main`, the pipeline runs (`Jenkinsfile`):

| Stage | Tool | What it does | Fails the build on... |
|-------|------|--------------|------------------------|
| Checkout | Git | Pulls the latest commit | Network or auth failure |
| Install dependencies | pip | Creates a venv, installs `requirements-dev.txt` | Version conflicts |
| Run tests | pytest + coverage | Executes 33 unit tests, emits `coverage.xml` | Any test failing |
| SonarQube scan | sonar-scanner | Sends source + coverage to SonarQube | (warning only - Quality Gate is informational) |
| Build Docker image | Docker | `docker build -t currencyflow:N .` | Dockerfile syntax / missing files |
| Deploy | Docker | `docker rm -f` + `docker run` to replace the container | Port conflicts, network issues |

Default options:
- `disableConcurrentBuilds()` - prevents two builds racing on Deploy
- 15-minute timeout
- Build retention: 10 most recent

To configure your own Jenkins instance, see [DEMO_GUIDE.md](./DEMO_GUIDE.md#section-7).

---

## API Reference

All endpoints return JSON. Examples assume the app is running at `http://localhost:5000`.

### Health & metrics
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness probe |
| GET | `/metrics` | Prometheus scrape endpoint (text format) |

### Currency data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/currencies` | All supported currency codes |
| GET | `/api/rates?base=USD` | Latest rates for a base currency |
| GET | `/api/convert?from=USD&to=EUR,GBP&amount=100` | Convert to one or many targets |
| GET | `/api/history?from=USD&to=EUR&days=30` | Historical rates between two currencies |
| GET | `/api/movers?base=USD&days=7` | Biggest currency movers vs. a base |
| GET | `/api/insight?from=USD&to=EUR` | "Good time to convert?" verdict |
| GET | `/api/recent-conversions` | Recent log + popular pair counts |
| GET | `/api/stats` | Internal counters (cache, conversions, watchlist, alerts) |

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist with live rates |
| POST | `/api/watchlist` | Body: `{"from":"USD","to":"EUR"}` |
| DELETE | `/api/watchlist/USD/EUR` | Remove a pair |

### Rate alerts
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/alerts` | All alerts (active + triggered) |
| POST | `/api/alerts` | Body: `{"from":"USD","to":"EUR","op":"above","threshold":0.95}` |
| DELETE | `/api/alerts/{id}` | Remove an alert |

### Example
```bash
curl 'http://localhost:5000/api/convert?from=USD&to=EUR,GBP&amount=100'
```
```json
{
  "amount": 100.0,
  "date": "2026-04-24",
  "from_currency": "USD",
  "results": [
    {"to": "EUR", "rate": 0.85383, "converted": 85.383},
    {"to": "GBP", "rate": 0.74115, "converted": 74.115}
  ]
}
```

---

## Observability

### Custom Prometheus metrics

| Metric | Type | Labels |
|--------|------|--------|
| `currencyflow_http_requests_total` | Counter | method, endpoint, status |
| `currencyflow_http_request_duration_seconds` | Histogram | endpoint |
| `currencyflow_conversions_total` | Counter | from_currency, to_currency |
| `currencyflow_cache_hits_total` | Counter | - |
| `currencyflow_cache_misses_total` | Counter | - |
| `currencyflow_upstream_request_duration_seconds` | Histogram | - |
| `currencyflow_alerts_triggered_total` | Counter | from_currency, to_currency, op |

### Grafana dashboard

The `CurrencyFlow Overview` dashboard auto-loads on first Grafana boot. It contains 8 panels:

| Row | Panels |
|-----|--------|
| 1 (KPIs) | Request Rate · Total Conversions · Cache Hit Rate · Errors (5xx, last 5m) |
| 2 (charts) | Requests/sec by endpoint · Cache hits vs misses |
| 3 (charts) | Top Currency Pairs · Upstream API latency (p50, p95, p99) |

Refresh interval: 5 seconds. Default time range: last 30 minutes.

---

## Contributing

This started as a college DevOps mini-project, but contributions are welcome. The pipeline already enforces:

- All tests must pass (`pytest`)
- New code must respect SonarQube rules (cognitive complexity ≤ 15, no nested ternaries, no duplicated string literals)
- New Python code should keep coverage ≥ 80% on changed lines

Open a PR against `main`. Jenkins will run the same pipeline on your branch (if a matching project is configured).

---

## Acknowledgements

- [Frankfurter](https://www.frankfurter.app) for the free, no-key currency API
- The Jenkins, Prometheus, Grafana, SonarQube, and Docker communities
- Built as part of an academic mini-project to demonstrate end-to-end DevOps tooling

---

## License

This is an academic project. Code is provided as-is for educational reference.
