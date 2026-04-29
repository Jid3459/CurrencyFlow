# CurrencyFlow - Team Demo Guide

> A self-contained playbook for anyone presenting the project to the professor.
> Read top-to-bottom once before the demo. During the demo, jump to **The Demo Script** section.

---

## 1. What CurrencyFlow Is (in plain English)

**The product:** A live currency exchange & conversion dashboard. Users can:
- Convert any amount between any two currencies
- Compare a conversion against multiple targets at once (e.g., 100 USD into EUR + GBP + JPY simultaneously)
- Pin currency pairs to a watchlist with live rates
- Get an "is this a good time to convert?" verdict (compared to the 30-day average)
- Set rate alerts ("notify me when USD → EUR goes above 0.95") that fire automatically
- See top movers, popular pairs, and a historical trend chart (Chart.js)

**The point of the project:** This is a **DevOps mini-project**. The currency dashboard is the *vehicle*; the real subject is the **automated software delivery pipeline** wrapped around it. Every required technology - Git, Docker, Jenkins, SonarQube, Prometheus, Grafana - plays a clear role and they all talk to each other.

**One-line elevator pitch for the professor:**
> "When I push code to GitHub, Jenkins automatically tests it, scans it with SonarQube, builds a fresh Docker image, redeploys the running app, and updates live metrics in Grafana - all without me clicking anything."

---

## 2. The Tech Stack at a Glance

| Tech | Role | Where it runs |
|------|------|---------------|
| **Git + GitHub** | Source of truth for code. Jenkins watches it. | github.com/Jid3459/CurrencyFlow |
| **Docker** | Every service (app + tools) runs as a container. Portable, reproducible. | Local Docker Desktop |
| **Docker Hub** | Public registry where the built app image is published. | hub.docker.com/r/jid345/currencyflow |
| **Flask + gunicorn** | The Python web app. Serves the dashboard + JSON API. | Container `currencyflow-app`, port 5000 |
| **Frankfurter API** | Free upstream currency data (European Central Bank). No API key. | api.frankfurter.app |
| **Jenkins** | CI/CD orchestrator. Polls GitHub every minute and runs the pipeline. | Container `currencyflow-jenkins`, port 8080 |
| **SonarQube** | Code quality + coverage scanner. Has a Quality Gate that pass/fails the build. | Container `currencyflow-sonarqube`, port 9000 |
| **Prometheus** | Time-series database. Scrapes `/metrics` from the app every 15s. | Container `currencyflow-prometheus`, port 9090 |
| **Grafana** | Visualises Prometheus metrics in a dashboard. | Container `currencyflow-grafana`, port 3000 |

---

## 3. The Architecture (how it all connects)

```
                                 ┌───────────────────────────┐
                                 │       Developer (you)     │
                                 │      `git push origin`    │
                                 └────────────┬──────────────┘
                                              │
                                              ▼
                                 ┌───────────────────────────┐
                                 │      GitHub (remote)      │
                                 │  Jid3459/CurrencyFlow     │
                                 └────────────┬──────────────┘
                                              │  (Jenkins polls every minute)
                                              ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │                            Jenkins Pipeline                            │
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
                                    │   8-panel dashboard (live)        │
                                    └───────────────────────────────────┘
```

**Three independent loops are happening at once:**

1. **The CI/CD loop** (Jenkins ↔ Git ↔ SonarQube ↔ Docker)
   Triggered by `git push`. Runs once per push, takes ~5-10 minutes.

2. **The observability loop** (App ↔ Prometheus ↔ Grafana)
   Always running. Prometheus scrapes the app's `/metrics` every 15 seconds; Grafana refreshes panels every 5 seconds.

3. **The user loop** (Browser ↔ App ↔ Frankfurter API)
   Runs when a user actually clicks anything. Cached responses keep this loop fast.

---

## 4. The Project Files (what lives where, and why)

```
CurrencyFlow/
├── app.py                        # Flask backend - all 11 API endpoints + background alerts thread
├── requirements.txt              # Production Python dependencies
├── requirements-dev.txt          # Test dependencies (pytest, responses, coverage)
├── Dockerfile                    # Recipe for the app's Docker image
├── .dockerignore                 # Keeps venv/, .git/ out of the image
├── docker-compose.yml            # Orchestrates ALL services (app + tools)
├── Jenkinsfile                   # Pipeline-as-code: 6 stages
├── sonar-project.properties      # SonarQube scan config
├── pytest.ini                    # Pytest config (coverage settings)
├── .gitignore                    # Files Git ignores (venv/, coverage.xml, etc.)
├── DEMO_GUIDE.md                 # ← this document
│
├── templates/
│   └── index.html                # The dashboard HTML structure
│
├── static/
│   ├── style.css                 # Dark theme, polished styling
│   └── app.js                    # Frontend logic (calls /api/*, renders chart)
│
├── tests/
│   ├── conftest.py               # Disables alerts background thread during tests
│   └── test_app.py               # 33 unit tests, ~92% coverage
│
├── jenkins/
│   └── Dockerfile                # Custom Jenkins image (Python + Docker CLI + sonar-scanner)
│
├── prometheus/
│   └── prometheus.yml            # Tells Prometheus to scrape app:5000/metrics
│
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── prometheus.yml    # Auto-wires Grafana to Prometheus on first boot
        └── dashboards/
            ├── dashboards.yml    # Provider config
            └── currencyflow-overview.json  # 8-panel auto-loaded dashboard
```

**Why these specific choices:**

- **Flask + Python**: Simple, well-understood, tons of docs. Keeps the *app* small so the *DevOps tooling* shines.
- **Frankfurter API**: Free, no API key, includes historical data. No secrets to manage.
- **In-memory state** (cache, watchlist, alerts): Demo-friendly. For production you'd swap for Redis/Postgres.
- **gunicorn `--workers 1 --threads 8`**: Multiple workers would give each its own copy of the in-memory state. One worker with threads keeps state shared cleanly.
- **Provisioned Grafana dashboard**: Looks professional ("comes up green from `docker compose up`"); demo-proof.
- **SonarQube Quality Gate**: Pass/fail verdict your professor can see at a glance.

---

## 5. Pre-Flight Checklist (do these once, before the demo)

### 5.1 Required tools on the machine
- **Docker Desktop** running (whale icon solid in system tray)
- **Git** installed
- **A browser** with these tabs ready (close everything else to free RAM):

| Tab | URL |
|-----|-----|
| 1 | http://localhost:5000 - the app |
| 2 | http://localhost:8080 - Jenkins |
| 3 | http://localhost:9000 - SonarQube |
| 4 | http://localhost:9090 - Prometheus |
| 5 | http://localhost:3000 - Grafana |
| 6 | https://github.com/Jid3459/CurrencyFlow - GitHub repo |

### 5.2 Required RAM headroom
This stack uses **~3 GB** of RAM total. On an 8 GB machine, **close**:
- All non-essential browser tabs
- VS Code instances if not actively editing
- Slack, Spotify, Teams - anything heavy

If WSL2 is configured (file `~/.wslconfig`), it's capped at 3 GB by default - that's enough.

### 5.3 Credentials you'll need
| Service | Username | Password |
|---------|----------|----------|
| Jenkins | `admin` | the password you set during first-run wizard |
| SonarQube | `admin` | `admin123` (or whatever was set) |
| Grafana | `admin` | the new password set on first login |

> If anyone asks: passwords are local-only and don't matter outside this machine.

---

## 6. Starting Everything (one command)

Open a terminal in the project folder (`C:\Users\jidne\Desktop\CurrencyFlow` on Jidnesh's machine) and run **one** of these:

### 6.1 Bring up the FULL stack (recommended for the demo)
```powershell
docker compose --profile quality --profile ci up -d
```

This starts all 5 containers: `app`, `prometheus`, `grafana`, `sonarqube`, `jenkins`.

**First start takes 90-120 seconds** because:
- SonarQube boots its embedded Elasticsearch
- Jenkins initialises its plugins
- Both have heavy startup costs

**Subsequent starts take ~20 seconds.**

### 6.2 Bring up just app + monitoring (lighter, no CI/quality demo)
```powershell
docker compose up -d
```

### 6.3 Verify everything is running
```powershell
docker compose ps
```

You should see 5 containers all `Up` and `healthy` (or `running`).

### 6.4 Stop everything when done
```powershell
docker compose --profile quality --profile ci down
```

(Add `-v` if you want to also delete persisted Jenkins/SonarQube/Grafana data.)

---

## 7. URL Reference Card (what to show, where)

| URL | Service | What you'll see | When in the demo to use it |
|-----|---------|-----------------|----------------------------|
| http://localhost:5000 | **The app** | The currency dashboard | Demo opening + after every Jenkins build |
| http://localhost:5000/health | App health check | `{"status":"ok"}` | If asked "is the container actually running?" |
| http://localhost:5000/metrics | App's Prometheus metrics | Plain-text metrics dump | To prove the metrics endpoint exists |
| https://github.com/Jid3459/CurrencyFlow | GitHub repo | Code, commits, Jenkinsfile, Dockerfile, etc. | "Here's the source of truth Jenkins is watching" |
| https://hub.docker.com/r/jid345/currencyflow | Docker Hub | Published image with tags | "Anyone in the world can run my app with one command" |
| http://localhost:8080/job/CurrencyFlow/ | **Jenkins** project | Build history, stage view | The CI/CD demo - **the big moment** |
| http://localhost:8080/job/CurrencyFlow/scmPollLog/ | Jenkins SCM polling log | Lines like `SCM changes detected. Triggering #N` | Smoking-gun proof of automatic triggers |
| http://localhost:9000/dashboard?id=currencyflow | **SonarQube** | Quality Gate, bugs, coverage % | Right after a build to show "scan passed" |
| http://localhost:9090 | Prometheus | Query box for raw metrics | Quick "yes, metrics are flowing" check |
| http://localhost:9090/targets | Prometheus targets | Two targets, both `UP` | Proof that scraping is healthy |
| http://localhost:3000 | **Grafana** | The 8-panel dashboard | Closing flourish - "now I can see all of it live" |

> **The bold rows are the four headline tabs.** If you only have 2 minutes for the demo, show those four.

---

## 8. The Demo Script (read this in order)

> Total time: ~5-7 minutes. Practice once before the real thing.

### Step 1 - "Here's the app" (1 minute)
**Tab:** http://localhost:5000

Talking points (point at the screen as you go):
1. *"This is CurrencyFlow. It's a live currency exchange and conversion dashboard."*
2. Type `100` → from `USD` → to `EUR` → click **Convert**.
   *"The conversion calls a free public API and returns ~85 EUR for 100 USD."*
3. Look at the **insight badge** that appears.
   *"This compares today's rate to the 30-day average and tells me if it's a good time to convert."*
4. Click the **★ Watch** button.
   *"That pinned the pair to my watchlist at the top with a live rate."*
5. Scroll down to **Rate Alerts**.
   *"I can set a rule like 'tell me when USD-EUR goes above 0.95'. A background thread polls every 60 seconds and triggers it automatically."*
6. Scroll down to the **Historical Trend** chart.
   *"Real ECB historical data, last 30 days."*

**Now pivot to the DevOps story.**

### Step 2 - "Here's the source of truth" (30 seconds)
**Tab:** https://github.com/Jid3459/CurrencyFlow

Talking points:
1. *"The whole project lives in this GitHub repo - app code, Dockerfile, Jenkinsfile, Grafana dashboards, SonarQube config, even this demo guide."*
2. Click the **commits** link briefly.
   *"You can see the project history - I built this in roughly seven steps."*

### Step 3 - "Watch the magic - I push code and don't touch anything else" (the headline moment, 90 seconds)

In your terminal, make one tiny change. Easiest:

```powershell
# Append a comment to app.py just to make a real change
"# Demo touch $(Get-Date -Format yyyy-MM-ddTHH-mm-ss)" | Out-File -Append app.py
git add app.py
git commit -m "demo: trigger CI from professor session"
git push
```

Then say:
> *"I've just pushed a commit. I'm not going to click on Jenkins. I'm going to wait."*

**Tab:** http://localhost:8080/job/CurrencyFlow/scmPollLog/

Refresh the page after ~30-60 seconds. Read the line aloud:
```
[poll] Latest remote head revision is: <new-hash> - triggering build #N
```

Say:
> *"Jenkins polls GitHub once every minute. It just noticed my push and automatically triggered a new build - no human in the loop."*

**Tab:** http://localhost:8080/job/CurrencyFlow/

Refresh. Show the new build row appearing in the Stage View, with stages turning green one by one:

| Stage | Says what |
|-------|-----------|
| Checkout | "Pulled the new commit from GitHub" |
| Install dependencies | "Set up Python and pip-installed everything" |
| Run tests | "Ran 33 unit tests; all green" |
| SonarQube scan | "Sent code + coverage report to SonarQube" |
| Build Docker image | "Re-built the app image" |
| Deploy | "Replaced the running container with the new image" |

> SonarQube takes ~6 minutes on this machine due to RAM constraints. Either let it finish in the background, or skip ahead to step 4 and come back.

### Step 4 - "Here's the code-quality verdict" (45 seconds)
**Tab:** http://localhost:9000/dashboard?id=currencyflow

Talking points:
1. Point at the **Quality Gate: Passed** badge.
   *"SonarQube scans every build for bugs, security issues, and code smells. It also checks test coverage. The Quality Gate is a pass/fail verdict - we're passing."*
2. Point at **Coverage 92%**.
   *"Of 320 lines of Python, 92% are exercised by tests."*
3. Click **Activity** in the top nav.
   *"Every Jenkins build adds a row here. You can see the history of code-quality over time."*

### Step 5 - "Here's what the running app is doing right now" (1 minute)
**Tab:** http://localhost:5000

Click **Convert** a few times in front of the professor.

**Tab:** http://localhost:3000 (Grafana)

Open the **CurrencyFlow Overview** dashboard. Talking points:
1. Point at **Total Conversions** - it just ticked up.
2. Point at **Cache Hit Rate** - "This shows how often we serve from the in-memory cache instead of hitting the upstream API."
3. Point at **Top Currency Pairs** - "USD → EUR is winning because that's what I just converted."
4. Point at **Upstream API latency** chart - "I can prove my cache works: latency drops over time as the cache fills up."

Say:
> *"Prometheus scrapes my app's /metrics endpoint every 15 seconds. Grafana queries Prometheus and refreshes panels every 5 seconds. So this is genuinely live."*

### Step 6 - "Bonus: prove the deploy actually replaced the container"
Open a new terminal:
```powershell
docker ps --format "table {{.Names}}\t{{.Status}}"
```

Show that `currencyflow-app` says `Up <small number> minutes` - that's the new container Jenkins just deployed.

### Step 7 - Closing line
> *"That's the whole CI/CD loop: code → push → tests → scan → build → deploy → metrics. Six tools, all automated, with no human in the loop after `git push`."*

---

## 9. Component Deep Dive (where, what, why)

### 9.1 Git + GitHub
- **What:** Source control. Every change is a commit; every commit can be examined and reverted.
- **Where:** github.com/Jid3459/CurrencyFlow (`main` branch)
- **Why it's first:** Without Git, there's no history and no way for Jenkins to know "what changed."

### 9.2 Docker
- **What:** Packages an app + its dependencies into a portable image.
- **Where:** `Dockerfile` (app), `jenkins/Dockerfile` (custom Jenkins), `docker-compose.yml` (orchestration)
- **Why we use it:** The whole stack runs the same way on Jidnesh's laptop, on Jenkins, and (in theory) on any cloud VM. No "works on my machine" excuses.

### 9.3 Docker Hub
- **What:** Public image registry.
- **Where:** hub.docker.com/r/jid345/currencyflow
- **Why we use it:** Anyone with Docker can pull and run our app:
  ```bash
  docker run -p 5000:5000 jid345/currencyflow:latest
  ```

### 9.4 Flask + gunicorn (the app itself)
- **What:** Python web framework (Flask) running under a production WSGI server (gunicorn).
- **Where:** `app.py` (~700 lines), serving from container `currencyflow-app:5000`
- **Why this stack:** Flask is the simplest Python web framework. gunicorn handles concurrency properly (Flask's dev server is single-threaded and prints scary warnings).
- **Endpoints exposed:**
  - `/` - the dashboard HTML
  - `/health` - container health check
  - `/metrics` - Prometheus metrics
  - `/api/currencies`, `/api/rates`, `/api/convert`, `/api/history`, `/api/movers`, `/api/recent-conversions`, `/api/stats` - JSON API
  - `/api/watchlist` (GET/POST/DELETE) - pinned pairs
  - `/api/insight` - "good time to convert?" verdict
  - `/api/alerts` (GET/POST/DELETE) - rate alerts

### 9.5 Jenkins
- **What:** CI/CD server. Watches GitHub, runs the `Jenkinsfile` pipeline on every change.
- **Where:** Container `currencyflow-jenkins`, http://localhost:8080
- **Why we use it:** Automation. We never want to manually run tests + scan + build + deploy. Jenkins makes mistakes impossible to forget.
- **The pipeline (in `Jenkinsfile`):**
  | Stage | What it does |
  |-------|--------------|
  | Checkout | `git pull` the latest code |
  | Install dependencies | `pip install -r requirements-dev.txt` in a fresh venv |
  | Run tests | `pytest` with coverage. Fails the build on any failed test. |
  | SonarQube scan | `sonar-scanner` sends code + coverage to SonarQube |
  | Build Docker image | `docker build -t currencyflow:N .` |
  | Deploy | `docker rm -f currencyflow-app` then `docker run` the new image |

- **How it knows when to build:** Polls GitHub every minute (`* * * * *` schedule). When the latest remote commit hash differs from the last built hash, it triggers.

### 9.6 SonarQube
- **What:** Static code analyser + Quality Gate.
- **Where:** Container `currencyflow-sonarqube`, http://localhost:9000
- **Why we use it:** Catches problems no test could - security smells, duplicated code, complex functions, low coverage on new code. The **Quality Gate** is a single pass/fail verdict.
- **What it scans:**
  - Python source code (`app.py`, `tests/`)
  - JavaScript (`static/app.js`)
  - HTML/CSS (`templates/`, `static/style.css`)
  - Coverage report (`coverage.xml` produced by pytest)
- **The Quality Gate (default "Sonar Way"):**
  - 0 new bugs
  - 0 new security issues
  - ≥ 80% coverage on new code (we exclude static/ and templates/ since we have no JS test runner)
  - 0 duplications above 3%

### 9.7 Prometheus
- **What:** Time-series database. Pulls metrics from configured "targets" on a schedule and stores them.
- **Where:** Container `currencyflow-prometheus`, http://localhost:9090
- **Why we use it:** It's the de-facto standard for app observability. Open-source, battle-tested, simple data model.
- **What it scrapes:**
  | Target | Endpoint | Interval |
  |--------|----------|----------|
  | The app | `http://app:5000/metrics` | 15s |
  | Itself | `http://localhost:9090/metrics` | 15s |
- **Custom metrics our app exposes:**
  - `currencyflow_http_requests_total{method,endpoint,status}` - count of HTTP requests
  - `currencyflow_http_request_duration_seconds` - histogram of latency
  - `currencyflow_conversions_total{from_currency,to_currency}` - currency conversions performed
  - `currencyflow_cache_hits_total` / `cache_misses_total` - in-memory cache effectiveness
  - `currencyflow_upstream_request_duration_seconds` - latency of calls to Frankfurter
  - `currencyflow_alerts_triggered_total{from_currency,to_currency,op}` - rate alerts that fired

### 9.8 Grafana
- **What:** Dashboard tool. Queries Prometheus (via PromQL) and draws panels.
- **Where:** Container `currencyflow-grafana`, http://localhost:3000
- **Why we use it:** Prometheus has a query UI but Grafana makes the data presentable for humans.
- **Our dashboard ("CurrencyFlow Overview", auto-provisioned):**
  | Row | Panels |
  |-----|--------|
  | 1 (stats strip) | Request Rate · Total Conversions · Cache Hit Rate · Errors |
  | 2 (charts) | Requests/sec by endpoint · Cache hits vs misses |
  | 3 (charts) | Top Currency Pairs · Upstream API latency (p50/p95/p99) |
- Auto-refreshes every 5 seconds.

---

## 10. Common Demo-Day Issues + Fixes

### 10.1 "Localhost:5000 doesn't load"
1. Check Docker Desktop is running (whale icon, system tray, must be solid).
2. Run `docker compose ps` - is `currencyflow-app` listed and `healthy`?
3. If not, run `docker compose up -d app`
4. If that fails because of an orphan container, run `docker rm -f currencyflow-app` then retry.

### 10.2 "Jenkins won't let me in"
1. The first-run wizard generates a one-time admin password. We've already done that.
2. If for some reason the admin user is gone, get the initial password again:
   ```powershell
   docker exec currencyflow-jenkins cat /var/jenkins_home/secrets/initialAdminPassword
   ```

### 10.3 "Build is taking forever"
- This machine has 8 GB of RAM. SonarQube alone needs ~2 GB. With everything running, the SonarQube scan stage can take 5-7 minutes.
- **Workaround:** If demoing on a smaller machine, stop SonarQube before the build, then restart it after - the scan stage will fail but tests + build + deploy still work.
- **Better:** Demo on a machine with 16 GB RAM if possible.

### 10.4 "SonarQube Quality Gate says Failed"
- Click into it. The "New Code" tab compares against a baseline date.
- Common failures: new untested code, new code smells.
- We've already cleaned up the major ones. If a fresh failure appears, click the failing condition to see exact files/lines.

### 10.5 "Grafana shows 'No data' on a panel"
- Hit the app a few times (convert, refresh) to generate metrics.
- Or: set the time range (top-right) to "Last 5 minutes" - the app might have only just started.

### 10.6 "Polling didn't trigger a build"
- Polling runs once a minute. Wait the full minute.
- Check the polling log at http://localhost:8080/job/CurrencyFlow/scmPollLog/ - it should show recent attempts.
- If nothing's there, the SCM trigger might be off. Project → Configure → Triggers → Poll SCM should be checked, schedule `* * * * *`.

---

## 11. The "Did Everything Run" Checklist

Run this script in PowerShell to verify every component is healthy in 10 seconds:

```powershell
Write-Host "=== Containers ==="
docker compose ps

Write-Host "`n=== App health ==="
(Invoke-WebRequest http://localhost:5000/health -UseBasicParsing).Content

Write-Host "`n=== Prometheus targets ==="
(Invoke-WebRequest http://localhost:9090/api/v1/targets -UseBasicParsing).Content `
    | ConvertFrom-Json `
    | ForEach-Object { $_.data.activeTargets } `
    | Select-Object -ExpandProperty health

Write-Host "`n=== SonarQube status ==="
(Invoke-WebRequest http://localhost:9000/api/system/status -UseBasicParsing).Content

Write-Host "`n=== Jenkins UI ==="
(Invoke-WebRequest http://localhost:8080 -UseBasicParsing).StatusCode
```

If everything prints without errors and health/status fields are `ok` / `UP` / 200, you're cleared for the demo.

---

## 12. One-Pager Cheat Sheet (print this if needed)

| What you say | URL to open | What's on screen |
|--------------|-------------|------------------|
| "Here's the app" | localhost:5000 | Dashboard - convert, watchlist, alerts, chart |
| "It's all in Git" | github.com/Jid3459/CurrencyFlow | Source code |
| "I push and don't touch anything" | (terminal) `git push` | Commit lands |
| "Jenkins notices on its own" | localhost:8080/job/CurrencyFlow/scmPollLog/ | "SCM changes detected. Triggering #N" |
| "Watch the pipeline run" | localhost:8080/job/CurrencyFlow/ | Stage View, stages turn green |
| "Code quality is graded" | localhost:9000/dashboard?id=currencyflow | Quality Gate: Passed, 92% coverage |
| "Live metrics flow" | localhost:3000 (CurrencyFlow Overview) | 8-panel dashboard, auto-refreshing |
| "Container is the new one" | (terminal) `docker ps` | `currencyflow-app` recently started |

---

*Last updated: 2026-04-29. Project repo: https://github.com/Jid3459/CurrencyFlow*
