from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict
import threading
import time
import asyncio

import pandas as pd
from flask import Flask, jsonify, render_template_string, request, send_file, url_for, session, redirect, flash
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os


app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # Change this in production!


CSV_PATH = os.path.join(os.path.dirname(__file__), "missing_children_dataset_10000.csv")
VIDEO_PATH = os.path.join(os.path.dirname(__file__), "model", "result.mp4")
USERS_DB_PATH = os.path.join(os.path.dirname(__file__), "users.json")

# Simple user database
def load_users():
    if os.path.exists(USERS_DB_PATH):
        with open(USERS_DB_PATH, 'r') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_DB_PATH, 'w') as f:
        json.dump(users, f, indent=2)

def register_user(email, password, name, phone, child_name, child_age):
    users = load_users()
    if email in users:
        return False, "Email already registered"
    
    users[email] = {
        'password_hash': generate_password_hash(password),
        'name': name,
        'phone': phone,
        'child_name': child_name,
        'child_age': child_age,
        'device_id': f"TT{len(users)+1:04d}",  # Generate device ID
        'registered_date': time.strftime("%Y-%m-%d %H:%M:%S")
    }
    save_users(users)
    return True, "Registration successful"

def authenticate_user(email, password):
    users = load_users()
    if email in users and check_password_hash(users[email]['password_hash'], password):
        return True, users[email]
    return False, None

def login_required(f):
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def admin_required(f):
    def decorated_function(*args, **kwargs):
        if 'admin_email' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

def authenticate_admin(email, password):
    # Simple admin credentials (in production, use proper database)
    admin_credentials = {
        'admin@tinytraces.com': 'admin123',
        'organizer@tinytraces.com': 'org123',
        'support@tinytraces.com': 'support123'
    }
    
    if email in admin_credentials and admin_credentials[email] == password:
        return True, {
            'email': email,
            'role': 'admin' if 'admin' in email else 'organizer',
            'name': 'Admin User' if 'admin' in email else 'Organizer User'
        }
    return False, None

# ---------------- BLE/RSSI MONITOR (Background) ----------------
RSSI_STATE: Dict[str, Any] = {
    "enabled": False,
    "status": "unknown",  # safe | warning | unknown
    "latest_rssi": None,
    "average_rssi": None,
    "window_size": 10,
    "threshold": -80,
    "last_update": None,
    "error": None,
}


def start_ble_monitor_background() -> None:
    try:
        from rssi_analyzer import RSSIAnalyzer, MissingChildIdentification  # type: ignore
        from ble_scanner import RSSIStream  # type: ignore
    except Exception as e:  # optional: environment may lack BLE
        RSSI_STATE.update({
            "enabled": False,
            "status": "unknown",
            "error": f"BLE modules not available: {e}",
        })
        return

    analyzer = RSSIAnalyzer(threshold=RSSI_STATE["threshold"], window_size=RSSI_STATE["window_size"])  # type: ignore
    stream = RSSIStream()  # type: ignore

    def subscriber(rssi: int) -> None:
        try:
            analyzer.analyze(rssi)
            RSSI_STATE.update({
                "status": "safe",
                "latest_rssi": rssi,
                "average_rssi": (sum(analyzer.rssi_history) / len(analyzer.rssi_history)) if analyzer.rssi_history else None,
                "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "error": None,
            })
        except MissingChildIdentification:
            RSSI_STATE.update({
                "status": "warning",
                "latest_rssi": rssi,
                "average_rssi": (sum(analyzer.rssi_history) / len(analyzer.rssi_history)) if analyzer.rssi_history else None,
                "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "error": None,
            })
        except Exception as e:
            RSSI_STATE.update({"status": "unknown", "error": str(e)})

    stream.subscribe(subscriber)

    async def run_loop():
        try:
            RSSI_STATE.update({"enabled": True})
            await stream.start_stream()
        except Exception as e:
            RSSI_STATE.update({"enabled": False, "status": "unknown", "error": str(e)})

    def thread_target():
        try:
            asyncio.run(run_loop())
        except Exception as e:
            RSSI_STATE.update({"enabled": False, "status": "unknown", "error": str(e)})

    t = threading.Thread(target=thread_target, name="BLEMonitorThread", daemon=True)
    t.start()


def _safe_parse_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def load_dataframe(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Parse dates
    if "missing_date" in df.columns:
        df["missing_date"] = _safe_parse_date(df["missing_date"])
    if "recovery_date" in df.columns:
        df["recovery_date"] = _safe_parse_date(df["recovery_date"])
    if "date_of_birth" in df.columns:
        df["date_of_birth"] = _safe_parse_date(df["date_of_birth"])

    # Derivations
    if "missing_date" in df.columns:
        df["missing_year_month"] = df["missing_date"].dt.to_period("M").astype(str)
        df["missing_year"] = df["missing_date"].dt.year

    # Age at missing: prefer provided, else compute from DOB
    if "missing_age" in df.columns:
        df["missing_age"] = pd.to_numeric(df["missing_age"], errors="coerce")
    if {"date_of_birth", "missing_date"}.issubset(df.columns):
        computed_age = (df["missing_date"] - df["date_of_birth"]).dt.days / 365.25
        df["missing_age_computed"] = computed_age
        if "missing_age" in df.columns:
            df["age_at_missing"] = df["missing_age"].fillna(df["missing_age_computed"])  # type: ignore
        else:
            df["age_at_missing"] = df["missing_age_computed"]

    # Recovery duration for found cases
    if {"recovery_status", "missing_date", "recovery_date"}.issubset(df.columns):
        delta_days = (df["recovery_date"] - df["missing_date"]).dt.days
        df["time_to_recovery_days"] = delta_days.where(df["recovery_status"].str.lower() == "found")

    # Cast numeric measures
    for col in ["height_cm", "weight_kg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# Global in-memory cache
_DF: pd.DataFrame | None = None


def get_df() -> pd.DataFrame:
    global _DF
    if _DF is None:
        _DF = load_dataframe(CSV_PATH)
    return _DF


def top_k(series: pd.Series, k: int = 10) -> Dict[str, int]:
    vc = series.dropna().astype(str).value_counts().head(k)
    return {str(idx): int(val) for idx, val in vc.items()}


def histogram(series: pd.Series, bins: int = 10, range_min: float | None = None, range_max: float | None = None) -> Dict[str, Any]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {"bins": [], "counts": []}
    if range_min is None:
        range_min = float(s.min())
    if range_max is None:
        range_max = float(s.max())
    counts, edges = pd.cut(s, bins=bins, retbins=True, include_lowest=True, right=False)
    counts = counts.value_counts().sort_index()
    labels = [f"{round(edges[i], 1)}–{round(edges[i+1], 1)}" for i in range(len(edges)-1)]
    return {"bins": labels, "counts": [int(x) for x in counts.tolist()]}


def build_stats() -> Dict[str, Any]:
    df = get_df()
    total = len(df)

    by_status = top_k(df["recovery_status"]) if "recovery_status" in df.columns else {}
    by_gender = top_k(df["gender"]) if "gender" in df.columns else {}
    by_race = top_k(df["race"]) if "race" in df.columns else {}
    by_circumstance = top_k(df["circumstance"]) if "circumstance" in df.columns else {}
    by_reporter = top_k(df["reporter_type"]) if "reporter_type" in df.columns else {}
    by_city = top_k(df["missing_city"]) if "missing_city" in df.columns else {}
    by_state = top_k(df["missing_state"]) if "missing_state" in df.columns else {}

    # Trends: monthly counts
    monthly_trend: Dict[str, int] = {}
    if "missing_year_month" in df.columns:
        monthly_trend = {k: int(v) for k, v in df["missing_year_month"].value_counts().sort_index().items()}

    age_hist = histogram(df.get("age_at_missing", df.get("missing_age", pd.Series(dtype=float))))
    height_hist = histogram(df.get("height_cm", pd.Series(dtype=float)))
    weight_hist = histogram(df.get("weight_kg", pd.Series(dtype=float)))
    recovery_time_hist = histogram(df.get("time_to_recovery_days", pd.Series(dtype=float)))

    # Recovery rate
    found_count = int(df.get("recovery_status", pd.Series(dtype=str)).str.lower().eq("found").sum()) if "recovery_status" in df.columns else 0
    recovery_rate = (found_count / total) * 100.0 if total else 0.0

    # Median/mean recovery time (days)
    median_recovery_days = None
    mean_recovery_days = None
    if "time_to_recovery_days" in df.columns:
        r = pd.to_numeric(df["time_to_recovery_days"], errors="coerce").dropna()
        if not r.empty:
            median_recovery_days = float(r.median())
            mean_recovery_days = float(r.mean())

    still_missing_count = int(df.get("recovery_status", pd.Series(dtype=str)).str.lower().eq("still missing").sum()) if "recovery_status" in df.columns else 0

    return {
        "totals": {
            "records": total,
            "recovery_rate_pct": round(recovery_rate, 2),
            "found_count": found_count,
            "still_missing_count": still_missing_count,
        },
        "categorical": {
            "recovery_status": by_status,
            "gender": by_gender,
            "race": by_race,
            "circumstance": by_circumstance,
            "reporter_type": by_reporter,
            "top_missing_cities": by_city,
            "top_missing_states": by_state,
        },
        "distributions": {
            "age_at_missing": age_hist,
            "height_cm": height_hist,
            "weight_kg": weight_hist,
            "time_to_recovery_days": recovery_time_hist,
        },
        "trends": {
            "monthly_missing_counts": monthly_trend,
        },
        "recovery_time": {
            "median_days": median_recovery_days,
            "mean_days": mean_recovery_days,
        },
        "schema_preview": list(df.columns),
    }


@app.route("/api/stats")
def api_stats():
    stats = build_stats()
    return jsonify(stats)


@app.route("/api/rssi")
def api_rssi():
    return jsonify(RSSI_STATE)


_ALERT_LOG: list[Dict[str, Any]] = []


@app.route("/api/alert", methods=["POST"])
def api_alert():
    payload = request.get_json(silent=True) or {}
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": payload.get("source", "web"),
        "note": payload.get("note", ""),
        "rssi": RSSI_STATE.get("latest_rssi"),
        "avg_rssi": RSSI_STATE.get("average_rssi"),
        "status": RSSI_STATE.get("status"),
    }
    _ALERT_LOG.append(entry)
    return jsonify({"ok": True, "logged": entry}), 201

def get_navbar_html():
    """Generate navbar HTML based on current session state"""
    user_email = session.get('user_email')
    user_name = session.get('user_name')
    
    if user_email:
        navbar_right = f'''
        <ul class="navbar-nav">
          <li class="nav-item dropdown">
            <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">
              {user_name}
            </a>
            <ul class="dropdown-menu">
              <li><a class="dropdown-item" href="/parent-dashboard">My Dashboard</a></li>
              <li><hr class="dropdown-divider"></li>
              <li><a class="dropdown-item" href="/logout">Logout</a></li>
            </ul>
          </li>
        </ul>'''
    else:
        navbar_right = '''
        <ul class="navbar-nav">
          <li class="nav-item"><a class="nav-link" href="/login">Login</a></li>
          <li class="nav-item"><a class="nav-link" href="/register">Register</a></li>
        </ul>'''
    
    return f'''
    <nav class="navbar navbar-expand-lg bg-body-tertiary mb-3">
      <div class="container-fluid">
        <a class="navbar-brand" href="/">Tiny Traces</a>
        <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#nav">
          <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="nav">
          <ul class="navbar-nav me-auto mb-2 mb-lg-0">
            <li class="nav-item"><a class="nav-link" href="/">Alerts</a></li>
            <li class="nav-item"><a class="nav-link" href="/insights">Insights</a></li>
            <li class="nav-item"><a class="nav-link" href="/cctv">CCTV</a></li>
            <li class="nav-item"><a class="nav-link" href="/admin-login">Admin</a></li>
          </ul>
          {navbar_right}
        </div>
      </div>
    </nav>'''


HOME_HTML = """
<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>Alerts - Tiny Traces</title>
    <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
    <script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js\"></script>
    <style>
      body { padding: 20px; }
      .card { margin-bottom: 16px; }
    </style>
  </head>
  <body>
    <div class=\"container-fluid\">
      {{ navbar|safe }}

      <div class=\"p-4 p-md-5 mb-3 bg-light border rounded-3\">
        <div class=\"container-fluid py-2\">
          <h1 class=\"display-6 fw-bold\">Tiny Traces</h1>
          <p class=\"col-md-8 fs-6\">Live safety signals and critical KPIs. Use Insights for deep analysis, or CCTV for camera-based verification near last seen locations.</p>
          <a class=\"btn btn-primary btn-sm me-2\" href=\"/insights\">Open Insights</a>
          <a class=\"btn btn-outline-secondary btn-sm\" href=\"/cctv\">Open CCTV</a>
        </div>
      </div>

      <div id=\"rssi-banner\" class=\"alert d-none\" role=\"alert\"></div>

      <div class=\"row\">
        <div class=\"col-lg-4\">
          <div class=\"card\"> <div class=\"card-body\">
            <h6 class=\"card-title\">At-a-glance</h6>
            <div><span class=\"text-muted\">Records:</span> <span id=\"kpi-records\">--</span></div>
            <div><span class=\"text-muted\">Recovery rate:</span> <span id=\"kpi-recovery\">--</span></div>
            <div><span class=\"text-muted\">Still missing:</span> <span id=\"kpi-still\">--</span></div>
          </div></div>
          <div class=\"card\"> <div class=\"card-body\">
            <h6 class=\"card-title\">Actions</h6>
            <a class=\"btn btn-primary me-2\" href=\"/insights\">Open Insights</a>
            <a class=\"btn btn-outline-secondary\" href=\"/cctv\">Open CCTV</a>
          </div></div>
        </div>
        <div class=\"col-lg-8\">
          <div class=\"card\"> <div class=\"card-body\">
            <h6 class=\"card-title\">Recent Alerts</h6>
            <div id=\"alerts\" class=\"small text-muted\">No alerts yet.</div>
          </div></div>
          <div class=\"card mt-3\"><div class=\"card-body\">
            <h6 class=\"card-title\">Top Locations</h6>
            <div class=\"row\">
              <div class=\"col-md-6\">
                <div class=\"small text-muted\">Top States</div>
                <ul id=\"top-states\" class=\"mb-0\"></ul>
              </div>
              <div class=\"col-md-6\">
                <div class=\"small text-muted\">Top Cities</div>
                <ul id=\"top-cities\" class=\"mb-0\"></ul>
              </div>
            </div>
          </div></div>
        </div>
      </div>
    </div>

    <script>
      async function pollRSSI() {
        try {
          const res = await fetch('/api/rssi');
          const data = await res.json();
          const banner = document.getElementById('rssi-banner');
          if (data.status === 'warning') {
            banner.className = 'alert alert-danger';
            banner.innerHTML = `🚨 Possible out-of-range detected. Latest RSSI: ${data.latest_rssi} dBm (avg ${Math.round((data.average_rssi ?? 0) * 10) / 10}). <button id=\"notifyBtn\" class=\"btn btn-sm btn-light ms-2\">Notify Response Team</button>`;
            banner.classList.remove('d-none');
            const btn = document.getElementById('notifyBtn');
            if (btn) {
              btn.onclick = async () => {
                await fetch('/api/alert', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source: 'dashboard', note: 'RSSI warning triggered'})});
                btn.textContent = 'Notified';
                btn.disabled = true;
              };
            }
          } else if (data.status === 'safe') {
            banner.className = 'alert alert-success';
            banner.textContent = `✅ Safe zone. Latest RSSI: ${data.latest_rssi} dBm (avg ${Math.round((data.average_rssi ?? 0) * 10) / 10}).`;
            banner.classList.remove('d-none');
          } else {
            banner.className = 'alert alert-secondary';
            banner.textContent = 'BLE/RSSI monitoring not active or initializing...';
            banner.classList.remove('d-none');
          }
        } catch {}
      }

      async function loadKpis() {
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('kpi-records').textContent = data.totals.records;
        document.getElementById('kpi-recovery').textContent = `${data.totals.recovery_rate_pct}% (${data.totals.found_count})`;
        document.getElementById('kpi-still').textContent = data.totals.still_missing_count;

        // Top locations
        const states = Object.entries(data.categorical.top_missing_states || {}).slice(0, 5);
        const cities = Object.entries(data.categorical.top_missing_cities || {}).slice(0, 5);
        const statesUl = document.getElementById('top-states');
        const citiesUl = document.getElementById('top-cities');
        statesUl.innerHTML = states.map(([k,v]) => `<li>${k}: <strong>${v}</strong></li>`).join('');
        citiesUl.innerHTML = cities.map(([k,v]) => `<li>${k}: <strong>${v}</strong></li>`).join('');
      }

      async function loadAlerts() {
        // Simple render of last 5 alert logs if any (not persisted between runs)
        const container = document.getElementById('alerts');
        container.textContent = 'Waiting for alerts...';
      }

      loadKpis();
      loadAlerts();
      pollRSSI();
      setInterval(pollRSSI, 3000);
    </script>
  </body>
  </html>
"""


INSIGHTS_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Tiny Traces - Insights</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
      body { padding: 20px; }
      .card { margin-bottom: 16px; }
      canvas { max-height: 300px; }
      .pill { font-size: 0.9rem; }
      .pill + .pill { margin-left: 8px; }
      .grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }
    </style>
  </head>
  <body>
    <div class="container-fluid">
      {{ navbar|safe }}
      <div class="d-flex align-items-center mb-3">
        <h2 class="me-3 mb-0">Missing Children Dashboard</h2>
        <span class="badge text-bg-secondary pill" id="records-pill"></span>
        <span class="badge text-bg-success pill" id="recovery-pill"></span>
      </div>

      <div id="rssi-banner" class="alert d-none" role="alert"></div>

      <div class="row">
        <div class="col-lg-7">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Monthly Missing Trend</h5>
              <canvas id="trendChart"></canvas>
            </div>
          </div>
        </div>
        <div class="col-lg-5">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Recovery Time (days)</h5>
              <div class="small text-muted" id="recovery-stats"></div>
              <canvas id="recoveryChart"></canvas>
            </div>
          </div>
        </div>
      </div>

      <div class="row">
        <div class="col-lg-6">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Age at Missing</h5>
              <canvas id="ageChart"></canvas>
            </div>
          </div>
        </div>
        <div class="col-lg-6">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Height and Weight</h5>
              <div class="grid-2">
                <canvas id="heightChart"></canvas>
                <canvas id="weightChart"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="row">
        <div class="col-lg-6">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Breakdown by Category</h5>
              <div class="grid-2">
                <canvas id="statusChart"></canvas>
                <canvas id="genderChart"></canvas>
              </div>
              <div class="grid-2 mt-3">
                <canvas id="raceChart"></canvas>
                <canvas id="circumstanceChart"></canvas>
              </div>
            </div>
          </div>
        </div>
        <div class="col-lg-6">
          <div class="card">
            <div class="card-body">
              <h5 class="card-title">Top Locations & Reporters</h5>
              <div class="grid-2">
                <canvas id="cityChart"></canvas>
                <canvas id="stateChart"></canvas>
              </div>
              <div class="mt-3">
                <canvas id="reporterChart"></canvas>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card mt-3">
        <div class="card-body">
          <h6 class="card-title">Schema Preview</h6>
          <code id="schema"></code>
        </div>
      </div>
    </div>

    <script>
      async function pollRSSI() {
        try {
          const res = await fetch('/api/rssi');
          const data = await res.json();
          const banner = document.getElementById('rssi-banner');
          if (data.status === 'warning') {
            banner.className = 'alert alert-danger';
            banner.innerHTML = `🚨 Possible out-of-range detected. Latest RSSI: ${data.latest_rssi} dBm (avg ${Math.round((data.average_rssi ?? 0) * 10) / 10}). <button id=\"notifyBtn\" class=\"btn btn-sm btn-light ms-2\">Notify Response Team</button>`;
            banner.classList.remove('d-none');
            const btn = document.getElementById('notifyBtn');
            if (btn) {
              btn.onclick = async () => {
                await fetch('/api/alert', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source: 'dashboard', note: 'RSSI warning triggered'})});
                btn.textContent = 'Notified';
                btn.disabled = true;
              };
            }
          } else if (data.status === 'safe') {
            banner.className = 'alert alert-success';
            banner.textContent = `✅ Safe zone. Latest RSSI: ${data.latest_rssi} dBm (avg ${Math.round((data.average_rssi ?? 0) * 10) / 10}).`;
            banner.classList.remove('d-none');
          } else {
            banner.className = 'alert alert-secondary';
            banner.textContent = 'BLE/RSSI monitoring not active or initializing...';
            banner.classList.remove('d-none');
          }
        } catch {}
      }

      async function loadStats() {
        const res = await fetch('/api/stats');
        const data = await res.json();

        // Header pills
        document.getElementById('records-pill').textContent = `${data.totals.records} records`;
        document.getElementById('recovery-pill').textContent = `${data.totals.recovery_rate_pct}% recovered (${data.totals.found_count})`;

        // Schema
        document.getElementById('schema').textContent = data.schema_preview.join(', ');

        // Trend
        const trendLabels = Object.keys(data.trends.monthly_missing_counts || {});
        const trendValues = Object.values(data.trends.monthly_missing_counts || {});
        new Chart(document.getElementById('trendChart'), {
          type: 'line',
          data: { labels: trendLabels, datasets: [{ label: 'Missing', data: trendValues, borderColor: '#0d6efd', tension: 0.2 }] },
          options: { scales: { x: { ticks: { autoSkip: true, maxTicksLimit: 12 } } } }
        });

        // Recovery time
        const rec = data.distributions.time_to_recovery_days;
        const med = data.recovery_time.median_days ?? 'N/A';
        const mean = data.recovery_time.mean_days ?? 'N/A';
        document.getElementById('recovery-stats').textContent = `Median: ${med}, Mean: ${mean}`;
        new Chart(document.getElementById('recoveryChart'), {
          type: 'bar',
          data: { labels: rec.bins, datasets: [{ label: 'Days', data: rec.counts, backgroundColor: '#198754' }] },
        });

        // Age, Height, Weight
        const age = data.distributions.age_at_missing;
        new Chart(document.getElementById('ageChart'), { type: 'bar', data: { labels: age.bins, datasets: [{ label: 'Age', data: age.counts, backgroundColor: '#6f42c1' }] } });
        const h = data.distributions.height_cm;
        new Chart(document.getElementById('heightChart'), { type: 'bar', data: { labels: h.bins, datasets: [{ label: 'Height (cm)', data: h.counts, backgroundColor: '#fd7e14' }] } });
        const w = data.distributions.weight_kg;
        new Chart(document.getElementById('weightChart'), { type: 'bar', data: { labels: w.bins, datasets: [{ label: 'Weight (kg)', data: w.counts, backgroundColor: '#20c997' }] } });

        function pieChart(elId, obj, title, color) {
          const labels = Object.keys(obj || {});
          const values = Object.values(obj || {});
          new Chart(document.getElementById(elId), {
            type: 'doughnut',
            data: { labels, datasets: [{ data: values, backgroundColor: color || ['#0d6efd', '#6c757d', '#198754', '#dc3545', '#fd7e14', '#20c997', '#6f42c1'] }] },
            options: { plugins: { legend: { position: 'bottom' }, title: { display: false, text: title } } }
          });
        }

        pieChart('statusChart', data.categorical.recovery_status, 'Status');
        pieChart('genderChart', data.categorical.gender, 'Gender');
        pieChart('raceChart', data.categorical.race, 'Race');
        pieChart('circumstanceChart', data.categorical.circumstance, 'Circumstance');
        pieChart('cityChart', data.categorical.top_missing_cities, 'Top Cities');
        pieChart('stateChart', data.categorical.top_missing_states, 'Top States');
        pieChart('reporterChart', data.categorical.reporter_type, 'Reporter');
      }

      loadStats();
      pollRSSI();
      setInterval(pollRSSI, 3000);
    </script>
  </body>
  </html>
"""


@app.route("/")
def dashboard():
    return render_template_string(HOME_HTML.replace("{{ navbar|safe }}", get_navbar_html()))


@app.route("/insights")
def insights():
    return render_template_string(INSIGHTS_HTML.replace("{{ navbar|safe }}", get_navbar_html()))


# ---------------- CCTV DEMO PAGE ----------------

CCTV_HTML = """
<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>CCTV Recognition Demo</title>
    <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
    <style>
      body { padding: 20px; }
      .card { margin-bottom: 16px; }
      video { width: 100%; max-height: 480px; background: #000; }
    </style>
  </head>
  <body>
    <div class=\"container\">
      <div class=\"d-flex align-items-center mb-3\">
        <h3 class=\"me-3 mb-0\">CCTV Recognition Demo</h3>
        <a class=\"btn btn-outline-secondary btn-sm\" href=\"{{ url_for('dashboard') }}\">← Back to Alerts</a>
      </div>

      <div class=\"alert alert-info\">This page showcases a demo video of camera-based recognition using a YOLOv8 model. Use the filters to focus on a last known location. The video is a precomputed example, representing how an incident could be verified near the selected area.</div>

      <form method=\"get\" class=\"row g-2 mb-3\">
        <div class=\"col-sm-4\">
          <label class=\"form-label\">Missing State</label>
          <select name=\"state\" class=\"form-select\">
            <option value=\"\">All</option>
            {% for s in states %}
              <option value=\"{{ s }}\" {% if s == state %}selected{% endif %}>{{ s }}</option>
            {% endfor %}
          </select>
        </div>
        <div class=\"col-sm-4\">
          <label class=\"form-label\">Missing City</label>
          <select name=\"city\" class=\"form-select\">
            <option value=\"\">All</option>
            {% for c in cities %}
              <option value=\"{{ c }}\" {% if c == city %}selected{% endif %}>{{ c }}</option>
            {% endfor %}
          </select>
        </div>
        <div class=\"col-sm-4 d-flex align-items-end\">
          <button class=\"btn btn-primary w-100\" type=\"submit\">Apply Filter</button>
        </div>
      </form>

      <div class=\"row\">
        <div class=\"col-lg-7\">
          <div class=\"card\">
            <div class=\"card-body\">
              <h5 class=\"card-title\">Detection Demo Video</h5>
              {% if video_available %}
                <video controls src=\"{{ url_for('serve_demo_video') }}\"></video>
              {% else %}
                <div class=\"alert alert-warning\">Demo video not found at {{ video_path }}</div>
              {% endif %}
              <div class=\"small text-muted mt-2\">Model file present: <strong>{{ model_present }}</strong> ({{ model_path }})</div>
            </div>
          </div>
        </div>
        <div class=\"col-lg-5\">
          <div class=\"card\">
            <div class=\"card-body\">
              <h5 class=\"card-title\">Recent Incidents Near Selection</h5>
              {% if incidents %}
                <ul class=\"list-group\">
                  {% for inc in incidents %}
                    <li class=\"list-group-item\">
                      <div class=\"fw-semibold\">Case {{ inc.case_id }} — {{ inc.first_name }} {{ inc.last_name }}</div>
                      <div class=\"small text-muted\">Missing: {{ inc.missing_city }}, {{ inc.missing_state }} on {{ inc.missing_date.strftime('%Y-%m-%d') if inc.missing_date else 'N/A' }}</div>
                      <div class=\"small\">Last seen: {{ inc.last_seen_location }}</div>
                    </li>
                  {% endfor %}
                </ul>
              {% else %}
                <div class=\"text-muted\">No recent incidents for the current filter.</div>
              {% endif %}
            </div>
          </div>
        </div>
      </div>

      <div class=\"card\">
        <div class=\"card-body\">
          <h6>How this maps to real-time recognition</h6>
          <ol class=\"mb-0\">
            <li>Use last known location (city/state) to prioritize nearby cameras.</li>
            <li>Run the YOLOv8 detector on incoming frames and alert on matches.</li>
            <li>Confirm with human-in-the-loop and dispatch response.</li>
          </ol>
        </div>
      </div>
    </div>
  </body>
  </html>
"""


@app.route("/cctv")
def cctv_page():
    df = get_df()
    # Build filter options
    states = sorted(df.get("missing_state", pd.Series(dtype=str)).dropna().unique().tolist())
    cities = sorted(df.get("missing_city", pd.Series(dtype=str)).dropna().unique().tolist())

    # Read filters
    state = request.args.get("state", "")
    city = request.args.get("city", "")

    filtered = df.copy()
    if state:
        filtered = filtered[filtered.get("missing_state", pd.Series(dtype=str)) == state]
    if city:
        filtered = filtered[filtered.get("missing_city", pd.Series(dtype=str)) == city]

    # Sort by most recent missing_date
    if "missing_date" in filtered.columns:
        filtered = filtered.sort_values("missing_date", ascending=False)

    # Prepare a few items
    cols = [
        "case_id", "first_name", "last_name", "missing_city", "missing_state", "missing_date", "last_seen_location"
    ]
    display = filtered[cols] if set(cols).issubset(filtered.columns) else pd.DataFrame(columns=cols)
    incidents = [
        {
            "case_id": r.get("case_id"),
            "first_name": r.get("first_name"),
            "last_name": r.get("last_name"),
            "missing_city": r.get("missing_city"),
            "missing_state": r.get("missing_state"),
            "missing_date": r.get("missing_date"),
            "last_seen_location": r.get("last_seen_location"),
        }
        for _, r in display.head(8).iterrows()
    ]

    # Check assets
    video_available = os.path.exists(VIDEO_PATH)
    model_path = os.path.join(os.path.dirname(__file__), "model", "yolov8n.pt")
    model_present = os.path.exists(model_path)

    return render_template_string(
        CCTV_HTML.replace("{{ navbar|safe }}", get_navbar_html()),
        states=states,
        cities=cities,
        state=state,
        city=city,
        incidents=incidents,
        video_available=video_available,
        video_path=VIDEO_PATH,
        model_present=str(model_present),
        model_path=model_path,
    )


@app.route("/video/result")
def serve_demo_video():
    if not os.path.exists(VIDEO_PATH):
        return ("Video not found", 404)
    return send_file(VIDEO_PATH, mimetype="video/mp4")


# ---------------- REGISTRATION PAGE ----------------

REGISTER_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Register - Tiny Traces</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { padding: 20px; }
      .register-container { max-width: 600px; margin: 0 auto; }
      .card { margin-bottom: 16px; }
    </style>
  </head>
  <body>
    <div class="container">
      {{ navbar|safe }}
      
      <div class="register-container">
        <div class="card">
          <div class="card-body">
            <h2 class="card-title mb-4">Register for Tiny Traces</h2>
            <p class="text-muted mb-4">Get your child safety device and monitoring dashboard. Complete the form below to purchase your Tiny Traces device.</p>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                  </div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            <form method="POST" action="{{ url_for('register') }}">
              <div class="row mb-3">
                <div class="col-md-6">
                  <label for="name" class="form-label">Parent/Guardian Name *</label>
                  <input type="text" class="form-control" id="name" name="name" required>
                </div>
                <div class="col-md-6">
                  <label for="email" class="form-label">Email Address *</label>
                  <input type="email" class="form-control" id="email" name="email" required>
                </div>
              </div>
              
              <div class="row mb-3">
                <div class="col-md-6">
                  <label for="phone" class="form-label">Phone Number *</label>
                  <input type="tel" class="form-control" id="phone" name="phone" required>
                </div>
                <div class="col-md-6">
                  <label for="password" class="form-label">Password *</label>
                  <input type="password" class="form-control" id="password" name="password" required>
                </div>
              </div>
              
              <div class="row mb-3">
                <div class="col-md-6">
                  <label for="child_name" class="form-label">Child's Name *</label>
                  <input type="text" class="form-control" id="child_name" name="child_name" required>
                </div>
                <div class="col-md-6">
                  <label for="child_age" class="form-label">Child's Age *</label>
                  <input type="number" class="form-control" id="child_age" name="child_age" min="1" max="18" required>
                </div>
              </div>
              
              <div class="card mb-3 border-success">
                <div class="card-header bg-success text-white">
                  <h6 class="mb-0">🎉 Super Affordable Device Package - Only ₹500!</h6>
                </div>
                <div class="card-body">
                  <div class="alert alert-success">
                    <strong>Limited Time Offer!</strong> Get your child's safety device at an unbeatable price.
                  </div>
                  <ul class="list-unstyled mb-0">
                    <li>✅ Tiny Traces BLE Device</li>
                    <li>✅ Real-time location monitoring</li>
                    <li>✅ Parent dashboard access</li>
                    <li>✅ SMS alerts</li>
                    <li>✅ 1-year warranty</li>
                    <li>✅ Free shipping across India</li>
                    <li>✅ 30-day money-back guarantee</li>
                  </ul>
                  <div class="mt-3">
                    <span class="text-decoration-line-through text-muted me-2">₹1,999</span>
                    <span class="fs-4 text-success fw-bold">₹500</span>
                    <span class="badge bg-danger ms-2">75% OFF</span>
                  </div>
                </div>
              </div>
              
              <div class="mb-3">
                <div class="form-check">
                  <input class="form-check-input" type="checkbox" id="terms" required>
                  <label class="form-check-label" for="terms">
                    I agree to the <a href="#" data-bs-toggle="modal" data-bs-target="#termsModal">Terms of Service</a> and <a href="#" data-bs-toggle="modal" data-bs-target="#privacyModal">Privacy Policy</a>
                  </label>
                </div>
              </div>
              
              <div class="d-grid">
                <button type="submit" class="btn btn-primary btn-lg">Register & Purchase Device</button>
              </div>
              
              <div class="text-center mt-3">
                <p class="text-muted">Already have an account? <a href="{{ url_for('login') }}">Login here</a></p>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Terms Modal -->
    <div class="modal fade" id="termsModal" tabindex="-1">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Terms of Service</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <h6>1. Device Usage</h6>
            <p>The Tiny Traces device is designed for child safety monitoring. Users are responsible for proper device maintenance and battery replacement.</p>
            
            <h6>2. Data Privacy</h6>
            <p>We collect and store location data solely for the purpose of child safety monitoring. Data is encrypted and stored securely.</p>
            
            <h6>3. Service Availability</h6>
            <p>While we strive for 99.9% uptime, service interruptions may occur. We are not liable for any consequences of service unavailability.</p>
            
            <h6>4. Warranty</h6>
            <p>Devices come with a 1-year manufacturer warranty covering defects in materials and workmanship.</p>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Privacy Modal -->
    <div class="modal fade" id="privacyModal" tabindex="-1">
      <div class="modal-dialog modal-lg">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Privacy Policy</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <h6>Data Collection</h6>
            <p>We collect location data, device status, and alert information to provide our monitoring service.</p>
            
            <h6>Data Usage</h6>
            <p>Your data is used exclusively for providing the Tiny Traces service and will not be sold to third parties.</p>
            
            <h6>Data Security</h6>
            <p>All data is encrypted in transit and at rest using industry-standard encryption methods.</p>
            
            <h6>Data Retention</h6>
            <p>Location data is retained for 30 days unless an incident requires longer retention for investigation purposes.</p>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
          </div>
        </div>
      </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        phone = request.form.get("phone")
        child_name = request.form.get("child_name")
        child_age = request.form.get("child_age")
        
        if not all([name, email, password, phone, child_name, child_age]):
            flash("All fields are required", "error")
            return render_template_string(REGISTER_HTML.replace("{{ navbar|safe }}", get_navbar_html()))
        
        success, message = register_user(email, password, name, phone, child_name, child_age)
        
        if success:
            flash(f"Registration successful! Your device ID is {message.split('Device ID: ')[1] if 'Device ID:' in message else 'TT0001'}. Please login to access your dashboard.", "success")
            return redirect(url_for("login"))
        else:
            flash(message, "error")
    
    return render_template_string(REGISTER_HTML.replace("{{ navbar|safe }}", get_navbar_html()))


# ---------------- LOGIN PAGE ----------------

LOGIN_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Login - Tiny Traces</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { padding: 20px; }
      .login-container { max-width: 400px; margin: 0 auto; }
      .card { margin-bottom: 16px; }
    </style>
  </head>
  <body>
    <div class="container">
      {{ navbar|safe }}
      
      <div class="login-container">
        <div class="card">
          <div class="card-body">
            <h2 class="card-title mb-4 text-center">Login to Tiny Traces</h2>
            <p class="text-muted mb-4 text-center">Access your child's safety monitoring dashboard</p>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                  </div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            <form method="POST" action="{{ url_for('login') }}">
              <div class="mb-3">
                <label for="email" class="form-label">Email Address</label>
                <input type="email" class="form-control" id="email" name="email" required>
              </div>
              
              <div class="mb-3">
                <label for="password" class="form-label">Password</label>
                <input type="password" class="form-control" id="password" name="password" required>
              </div>
              
              <div class="mb-3 form-check">
                <input type="checkbox" class="form-check-input" id="remember">
                <label class="form-check-label" for="remember">
                  Remember me
                </label>
              </div>
              
              <div class="d-grid">
                <button type="submit" class="btn btn-primary btn-lg">Login</button>
              </div>
              
              <div class="text-center mt-3">
                <p class="text-muted">Don't have an account? <a href="{{ url_for('register') }}">Register here</a></p>
              </div>
            </form>
          </div>
        </div>
        
        <div class="card">
          <div class="card-body">
            <h6 class="card-title">Demo Account</h6>
            <p class="card-text small text-muted">
              For demonstration purposes, you can use:<br>
              <strong>Email:</strong> demo@tinytraces.com<br>
              <strong>Password:</strong> demo123
            </p>
            <button class="btn btn-outline-secondary btn-sm" onclick="fillDemo()">Fill Demo Credentials</button>
          </div>
        </div>
      </div>
    </div>
    
    <script>
      function fillDemo() {
        document.getElementById('email').value = 'demo@tinytraces.com';
        document.getElementById('password').value = 'demo123';
      }
    </script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        if not email or not password:
            flash("Email and password are required", "error")
            return render_template_string(LOGIN_HTML.replace("{{ navbar|safe }}", get_navbar_html()))
        
        # Check for demo account
        if email == "demo@tinytraces.com" and password == "demo123":
            session['user_email'] = email
            session['user_name'] = "Demo Parent"
            session['user_device_id'] = "TT0001"
            flash("Logged in successfully!", "success")
            return redirect(url_for("parent_dashboard"))
        
        success, user_data = authenticate_user(email, password)
        
        if success:
            session['user_email'] = email
            session['user_name'] = user_data['name']
            session['user_device_id'] = user_data['device_id']
            flash("Logged in successfully!", "success")
            return redirect(url_for("parent_dashboard"))
        else:
            flash("Invalid email or password", "error")
    
    return render_template_string(LOGIN_HTML.replace("{{ navbar|safe }}", get_navbar_html()))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out", "success")
    return redirect(url_for("login"))


# ---------------- PARENT DASHBOARD ----------------

PARENT_DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Parent Dashboard - Tiny Traces</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
      body { padding: 20px; }
      .card { margin-bottom: 16px; }
      .status-indicator { width: 12px; height: 12px; border-radius: 50%; display: inline-block; margin-right: 8px; }
      .status-safe { background-color: #28a745; }
      .status-warning { background-color: #ffc107; }
      .status-danger { background-color: #dc3545; }
      .status-unknown { background-color: #6c757d; }
    </style>
  </head>
  <body>
    <div class="container-fluid">
      {{ navbar|safe }}
      
      <div class="d-flex align-items-center mb-3">
        <h2 class="me-3 mb-0">Welcome, {{ session.user_name }}!</h2>
        <span class="badge text-bg-primary">{{ session.user_device_id }}</span>
      </div>

      <div id="rssi-banner" class="alert d-none" role="alert"></div>

      <div class="row">
        <div class="col-lg-4">
          <div class="card">
            <div class="card-body">
              <h6 class="card-title">Device Status</h6>
              <div class="mb-2">
                <span class="status-indicator" id="status-indicator"></span>
                <span id="device-status">Checking...</span>
              </div>
              <div class="small text-muted">
                <div>Device ID: <strong>{{ session.user_device_id }}</strong></div>
                <div>Last Update: <span id="last-update">--</span></div>
                <div>Signal Strength: <span id="signal-strength">--</span></div>
              </div>
            </div>
          </div>
          
          <div class="card">
            <div class="card-body">
              <h6 class="card-title">Quick Actions</h6>
              <div class="d-grid gap-2">
                <button class="btn btn-outline-primary btn-sm" onclick="testAlert()">Test Alert</button>
                <button class="btn btn-outline-secondary btn-sm" onclick="refreshStatus()">Refresh Status</button>
                <button class="btn btn-outline-info btn-sm" onclick="viewHistory()">View History</button>
              </div>
            </div>
          </div>
        </div>
        
        <div class="col-lg-8">
          <div class="card">
            <div class="card-body">
              <h6 class="card-title">Real-time Signal Strength</h6>
              <canvas id="signalChart" height="100"></canvas>
            </div>
          </div>
          
          <div class="card mt-3">
            <div class="card-body">
              <h6 class="card-title">Recent Alerts & Activity</h6>
              <div id="alerts-list">
                <div class="text-muted">No alerts yet. Device monitoring is active.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      
      <div class="row mt-3">
        <div class="col-lg-6">
          <div class="card">
            <div class="card-body">
              <h6 class="card-title">Device Information</h6>
              <div class="row">
                <div class="col-6">
                  <div class="small text-muted">Battery Level</div>
                  <div class="fw-bold" id="battery-level">--</div>
                </div>
                <div class="col-6">
                  <div class="small text-muted">Uptime</div>
                  <div class="fw-bold" id="uptime">--</div>
                </div>
              </div>
              <hr>
              <div class="small text-muted">
                <div>Model: Tiny Traces BLE v1.0</div>
                <div>Firmware: 1.2.3</div>
                <div>Range: Up to 100m</div>
              </div>
            </div>
          </div>
        </div>
        
        <div class="col-lg-6">
          <div class="card">
            <div class="card-body">
              <h6 class="card-title">Emergency Contacts</h6>
              <div class="mb-2">
                <div class="small text-muted">Primary Contact</div>
                <div class="fw-bold">{{ session.user_name }}</div>
              </div>
              <div class="mb-2">
                <div class="small text-muted">Phone</div>
                <div class="fw-bold" id="emergency-phone">--</div>
              </div>
              <button class="btn btn-outline-warning btn-sm" onclick="updateContacts()">Update Contacts</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <script>
      let signalChart;
      let signalData = [];
      let alertLog = [];

      // Initialize signal chart
      function initChart() {
        const ctx = document.getElementById('signalChart').getContext('2d');
        signalChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: [],
            datasets: [{
              label: 'RSSI (dBm)',
              data: [],
              borderColor: '#0d6efd',
              backgroundColor: 'rgba(13, 110, 253, 0.1)',
              tension: 0.4,
              fill: true
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              y: {
                beginAtZero: false,
                max: -30,
                min: -100
              }
            },
            plugins: {
              legend: {
                display: false
              }
            }
          }
        });
      }

      // Update device status
      function updateDeviceStatus() {
        fetch('/api/rssi')
          .then(response => response.json())
          .then(data => {
            const indicator = document.getElementById('status-indicator');
            const status = document.getElementById('device-status');
            const lastUpdate = document.getElementById('last-update');
            const signalStrength = document.getElementById('signal-strength');
            
            // Update status indicator
            indicator.className = 'status-indicator status-' + (data.status || 'unknown');
            
            // Update status text
            const statusText = {
              'safe': 'Device Connected - Safe Zone',
              'warning': 'Device Out of Range - Warning',
              'unknown': 'Device Status Unknown'
            };
            status.textContent = statusText[data.status] || 'Device Status Unknown';
            
            // Update signal info
            if (data.latest_rssi) {
              signalStrength.textContent = data.latest_rssi + ' dBm';
              
              // Add to chart
              const now = new Date().toLocaleTimeString();
              signalData.push({time: now, value: data.latest_rssi});
              if (signalData.length > 20) signalData.shift();
              
              signalChart.data.labels = signalData.map(d => d.time);
              signalChart.data.datasets[0].data = signalData.map(d => d.value);
              signalChart.update();
            }
            
            lastUpdate.textContent = data.last_update || 'Never';
            
            // Update banner
            const banner = document.getElementById('rssi-banner');
            if (data.status === 'warning') {
              banner.className = 'alert alert-warning';
              banner.innerHTML = `⚠️ Your child's device is out of range! Latest signal: ${data.latest_rssi} dBm`;
              banner.classList.remove('d-none');
            } else if (data.status === 'safe') {
              banner.className = 'alert alert-success';
              banner.innerHTML = `✅ Device connected. Signal strength: ${data.latest_rssi} dBm`;
              banner.classList.remove('d-none');
            } else {
              banner.classList.add('d-none');
            }
          })
          .catch(error => {
            console.error('Error fetching RSSI data:', error);
          });
      }

      // Test alert function
      function testAlert() {
        alertLog.unshift({
          time: new Date().toLocaleTimeString(),
          type: 'test',
          message: 'Test alert triggered by parent'
        });
        updateAlertsList();
        
        fetch('/api/alert', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({source: 'parent_dashboard', note: 'Test alert triggered'})
        });
      }

      // Refresh status
      function refreshStatus() {
        updateDeviceStatus();
      }

      // View history
      function viewHistory() {
        alert('History feature coming soon!');
      }

      // Update contacts
      function updateContacts() {
        alert('Contact update feature coming soon!');
      }

      // Update alerts list
      function updateAlertsList() {
        const container = document.getElementById('alerts-list');
        if (alertLog.length === 0) {
          container.innerHTML = '<div class="text-muted">No alerts yet. Device monitoring is active.</div>';
          return;
        }
        
        container.innerHTML = alertLog.slice(0, 5).map(alert => `
          <div class="d-flex justify-content-between align-items-center border-bottom py-2">
            <div>
              <div class="fw-semibold">${alert.type === 'test' ? 'Test Alert' : 'Device Alert'}</div>
              <div class="small text-muted">${alert.message}</div>
            </div>
            <div class="small text-muted">${alert.time}</div>
          </div>
        `).join('');
      }

      // Initialize dashboard
      document.addEventListener('DOMContentLoaded', function() {
        initChart();
        updateDeviceStatus();
        
        // Update every 3 seconds
        setInterval(updateDeviceStatus, 3000);
      });
    </script>
  </body>
</html>
"""


@app.route("/parent-dashboard")
@login_required
def parent_dashboard():
    return render_template_string(PARENT_DASHBOARD_HTML.replace("{{ navbar|safe }}", get_navbar_html()))


# ---------------- ADMIN LOGIN PAGE ----------------

ADMIN_LOGIN_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Admin Login - Tiny Traces</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      body { 
        padding: 20px; 
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        min-height: 100vh;
      }
      .admin-container { max-width: 450px; margin: 0 auto; }
      .card { margin-bottom: 16px; box-shadow: 0 8px 32px rgba(0,0,0,0.1); }
      .admin-header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
    </style>
  </head>
  <body>
    <div class="container">
      <div class="admin-container">
        <div class="text-center mb-4">
          <h1 class="text-white">🔐 Admin Portal</h1>
          <p class="text-white-50">Tiny Traces Management System</p>
        </div>
        
        <div class="card">
          <div class="card-header admin-header">
            <h4 class="mb-0 text-center">Administrator Login</h4>
          </div>
          <div class="card-body">
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ 'danger' if category == 'error' else 'success' }} alert-dismissible fade show">
                    {{ message }}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                  </div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            <form method="POST" action="{{ url_for('admin_login') }}">
              <div class="mb-3">
                <label for="email" class="form-label">Admin Email</label>
                <input type="email" class="form-control" id="email" name="email" required>
              </div>
              
              <div class="mb-3">
                <label for="password" class="form-label">Password</label>
                <input type="password" class="form-control" id="password" name="password" required>
              </div>
              
              <div class="d-grid">
                <button type="submit" class="btn btn-primary btn-lg">Login as Admin</button>
              </div>
            </form>
          </div>
        </div>
        
        <div class="card">
          <div class="card-body">
            <h6 class="card-title">Demo Admin Accounts</h6>
            <div class="row">
              <div class="col-md-4">
                <div class="border rounded p-2 mb-2">
                  <div class="small text-muted">Super Admin</div>
                  <div class="fw-bold">admin@tinytraces.com</div>
                  <div class="small text-muted">Password: admin123</div>
                </div>
              </div>
              <div class="col-md-4">
                <div class="border rounded p-2 mb-2">
                  <div class="small text-muted">Organizer</div>
                  <div class="fw-bold">organizer@tinytraces.com</div>
                  <div class="small text-muted">Password: org123</div>
                </div>
              </div>
              <div class="col-md-4">
                <div class="border rounded p-2 mb-2">
                  <div class="small text-muted">Support</div>
                  <div class="fw-bold">support@tinytraces.com</div>
                  <div class="small text-muted">Password: support123</div>
                </div>
              </div>
            </div>
            <div class="text-center mt-3">
              <button class="btn btn-outline-secondary btn-sm me-2" onclick="fillAdmin()">Fill Admin</button>
              <button class="btn btn-outline-secondary btn-sm me-2" onclick="fillOrganizer()">Fill Organizer</button>
              <button class="btn btn-outline-secondary btn-sm" onclick="fillSupport()">Fill Support</button>
            </div>
          </div>
        </div>
        
        <div class="text-center mt-3">
          <a href="/" class="text-white">← Back to Main Site</a>
        </div>
      </div>
    </div>
    
    <script>
      function fillAdmin() {
        document.getElementById('email').value = 'admin@tinytraces.com';
        document.getElementById('password').value = 'admin123';
      }
      function fillOrganizer() {
        document.getElementById('email').value = 'organizer@tinytraces.com';
        document.getElementById('password').value = 'org123';
      }
      function fillSupport() {
        document.getElementById('email').value = 'support@tinytraces.com';
        document.getElementById('password').value = 'support123';
      }
    </script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
  </body>
</html>
"""


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        if not email or not password:
            flash("Email and password are required", "error")
            return render_template_string(ADMIN_LOGIN_HTML)
        
        success, admin_data = authenticate_admin(email, password)
        
        if success:
            session['admin_email'] = email
            session['admin_name'] = admin_data['name']
            session['admin_role'] = admin_data['role']
            flash("Admin login successful!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid admin credentials", "error")
    
    return render_template_string(ADMIN_LOGIN_HTML)


@app.route("/admin-logout")
def admin_logout():
    session.pop('admin_email', None)
    session.pop('admin_name', None)
    session.pop('admin_role', None)
    flash("Admin logged out successfully", "success")
    return redirect(url_for("admin_login"))


# ---------------- ADMIN DASHBOARD ----------------

ADMIN_DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Admin Dashboard - Tiny Traces</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
      body { padding: 20px; background-color: #f8f9fa; }
      .card { margin-bottom: 16px; }
      .admin-header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
      .stat-card { text-align: center; padding: 20px; }
      .stat-number { font-size: 2rem; font-weight: bold; }
    </style>
  </head>
  <body>
    <div class="container-fluid">
      <div class="d-flex justify-content-between align-items-center mb-4">
        <div>
          <h2 class="mb-0">Admin Dashboard</h2>
          <p class="text-muted">Welcome back, {{ session.admin_name }} ({{ session.admin_role.title() }})</p>
        </div>
        <div>
          <a href="/" class="btn btn-outline-primary me-2">View Public Site</a>
          <a href="/admin-logout" class="btn btn-outline-danger">Logout</a>
        </div>
      </div>

      <!-- Statistics Cards -->
      <div class="row mb-4">
        <div class="col-lg-3 col-md-6">
          <div class="card stat-card bg-primary text-white">
            <div class="stat-number" id="total-users">--</div>
            <div>Total Registered Parents</div>
          </div>
        </div>
        <div class="col-lg-3 col-md-6">
          <div class="card stat-card bg-success text-white">
            <div class="stat-number" id="active-devices">--</div>
            <div>Active Devices</div>
          </div>
        </div>
        <div class="col-lg-3 col-md-6">
          <div class="card stat-card bg-warning text-white">
            <div class="stat-number" id="alerts-today">--</div>
            <div>Alerts Today</div>
          </div>
        </div>
        <div class="col-lg-3 col-md-6">
          <div class="card stat-card bg-info text-white">
            <div class="stat-number" id="revenue-today">₹--</div>
            <div>Revenue Today</div>
          </div>
        </div>
      </div>

      <div class="row">
        <div class="col-lg-8">
          <div class="card">
            <div class="card-header">
              <h5 class="mb-0">System Overview</h5>
            </div>
            <div class="card-body">
              <div class="row">
                <div class="col-md-6">
                  <h6>Device Status Distribution</h6>
                  <canvas id="deviceStatusChart" height="200"></canvas>
                </div>
                <div class="col-md-6">
                  <h6>Recent Registrations</h6>
                  <canvas id="registrationChart" height="200"></canvas>
                </div>
              </div>
            </div>
          </div>
          
          <div class="card mt-3">
            <div class="card-header">
              <h5 class="mb-0">Recent Activity</h5>
            </div>
            <div class="card-body">
              <div id="recent-activity">
                <div class="text-muted">Loading recent activity...</div>
              </div>
            </div>
          </div>
        </div>
        
        <div class="col-lg-4">
          <div class="card">
            <div class="card-header">
              <h5 class="mb-0">Quick Actions</h5>
            </div>
            <div class="card-body">
              <div class="d-grid gap-2">
                <button class="btn btn-primary" onclick="viewUsers()">View All Users</button>
                <button class="btn btn-success" onclick="viewDevices()">Manage Devices</button>
                <button class="btn btn-warning" onclick="viewAlerts()">View Alerts</button>
                <button class="btn btn-info" onclick="generateReport()">Generate Report</button>
                <button class="btn btn-secondary" onclick="systemSettings()">System Settings</button>
              </div>
            </div>
          </div>
          
          <div class="card mt-3">
            <div class="card-header">
              <h5 class="mb-0">System Health</h5>
            </div>
            <div class="card-body">
              <div class="mb-2">
                <div class="d-flex justify-content-between">
                  <span>BLE Monitoring</span>
                  <span class="badge bg-success" id="ble-status">Active</span>
                </div>
              </div>
              <div class="mb-2">
                <div class="d-flex justify-content-between">
                  <span>Database</span>
                  <span class="badge bg-success">Online</span>
                </div>
              </div>
              <div class="mb-2">
                <div class="d-flex justify-content-between">
                  <span>API Status</span>
                  <span class="badge bg-success">Healthy</span>
                </div>
              </div>
              <div class="mb-2">
                <div class="d-flex justify-content-between">
                  <span>Last Backup</span>
                  <span class="small text-muted">2 hours ago</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <script>
      // Initialize charts
      function initCharts() {
        // Device Status Chart
        const deviceCtx = document.getElementById('deviceStatusChart').getContext('2d');
        new Chart(deviceCtx, {
          type: 'doughnut',
          data: {
            labels: ['Safe', 'Warning', 'Offline'],
            datasets: [{
              data: [85, 10, 5],
              backgroundColor: ['#28a745', '#ffc107', '#dc3545']
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false
          }
        });

        // Registration Chart
        const regCtx = document.getElementById('registrationChart').getContext('2d');
        new Chart(regCtx, {
          type: 'line',
          data: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            datasets: [{
              label: 'New Registrations',
              data: [12, 19, 8, 15, 22, 18, 25],
              borderColor: '#007bff',
              tension: 0.4
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              y: { beginAtZero: true }
            }
          }
        });
      }

      // Update statistics
      function updateStats() {
        // Simulate API calls
        document.getElementById('total-users').textContent = '1,247';
        document.getElementById('active-devices').textContent = '1,156';
        document.getElementById('alerts-today').textContent = '23';
        document.getElementById('revenue-today').textContent = '₹12,350';
        
        // Update recent activity
        const activityHtml = `
          <div class="d-flex justify-content-between align-items-center border-bottom py-2">
            <div>
              <div class="fw-semibold">New Registration</div>
              <div class="small text-muted">Parent registered for device TT1247</div>
            </div>
            <div class="small text-muted">2 min ago</div>
          </div>
          <div class="d-flex justify-content-between align-items-center border-bottom py-2">
            <div>
              <div class="fw-semibold">Device Alert</div>
              <div class="small text-muted">Device TT0892 went out of range</div>
            </div>
            <div class="small text-muted">5 min ago</div>
          </div>
          <div class="d-flex justify-content-between align-items-center border-bottom py-2">
            <div>
              <div class="fw-semibold">Payment Received</div>
              <div class="small text-muted">₹500 from user@example.com</div>
            </div>
            <div class="small text-muted">12 min ago</div>
          </div>
        `;
        document.getElementById('recent-activity').innerHTML = activityHtml;
      }

      // Quick action functions
      function viewUsers() { alert('User management feature coming soon!'); }
      function viewDevices() { alert('Device management feature coming soon!'); }
      function viewAlerts() { alert('Alert management feature coming soon!'); }
      function generateReport() { alert('Report generation feature coming soon!'); }
      function systemSettings() { alert('System settings feature coming soon!'); }

      // Initialize dashboard
      document.addEventListener('DOMContentLoaded', function() {
        initCharts();
        updateStats();
      });
    </script>
  </body>
</html>
"""


@app.route("/admin-dashboard")
@admin_required
def admin_dashboard():
    return render_template_string(ADMIN_DASHBOARD_HTML)


if __name__ == "__main__":
    # Start BLE monitor in background if available
    start_ble_monitor_background()
    # Run in development mode
    app.run(host="0.0.0.0", port=5000, debug=True)


