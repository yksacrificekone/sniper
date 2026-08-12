"""
zofild-sniper — Flask web panel.
All HTML + CSS is embedded here so the project runs from .py files only.
Owner key:  Z0F1LD0TERRRR11111  (unlimited, never expires)
"""
import hashlib
import json
import os
import random
import secrets
import string
from datetime import datetime, timedelta, timezone

from flask import (Flask, jsonify, redirect, render_template_string,
                   request, session, url_for)

from sniper import is_running, load_proxies, start_snipe

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
KEYS_PATH = os.path.join(BASE, "keys.json")
USERS_PATH = os.path.join(BASE, "users.json")

DEFAULT_CONFIG = {
    "secret_key": "",
    "owner": {
        "key": "Z0F1LD0TERRRR11111",
        "password": "zofildoterr",
        "display_name": "zofildoterr"
    },
    "discord_invite": "https://discord.gg/REPLACE_ME",
    "proxy_file": "proxies.txt",
    "counters": {"basic": 0, "premium": 0, "admin": 0},
    "tiers": {
        "basic": {
            "name": "Basic - $3",
            "prefix": "3DDDDLOOOOLLLARRRR",
            "password_length": 6,
            "duration_hours": 72,
            "slots": 1,
            "perks": [
                "6-character license code",
                "3 days of sniper access",
                "1 concurrent sniper slot",
                "Proxy rotation enabled"
            ]
        },
        "premium": {
            "name": "Premium - $5",
            "prefix": "PREMIUM5DOLLAAAA",
            "password_length": 8,
            "duration_hours": 168,
            "slots": 5,
            "perks": [
                "8-character license code",
                "7 days of sniper access",
                "5 concurrent sniper slots",
                "Priority sniping queue"
            ]
        },
        "admin": {
            "name": "Admin - $10",
            "prefix": "ADDDMIMNNACCESSSSSSS",
            "password_length": 12,
            "duration_hours": 720,
            "slots": 999,
            "perks": [
                "12-character license code",
                "30 days of sniper access",
                "Unlimited concurrent sniper slots",
                "All features unlocked"
            ]
        }
    },
    "sniper": {"max_attempts": 300, "delay_min": 1.0, "delay_max": 4.0}
}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


cfg = load_json(CONFIG_PATH, DEFAULT_CONFIG)
if not cfg.get("secret_key"):
    cfg["secret_key"] = secrets.token_hex(32)
    save_json(CONFIG_PATH, cfg)

keys = load_json(KEYS_PATH, {})     # token -> {token, code, tier, expires}
users = load_json(USERS_PATH, {})   # username -> {password, token}

app = Flask(__name__)
app.secret_key = cfg["secret_key"]

PROXIES = load_proxies(os.path.join(BASE, cfg.get("proxy_file", "proxies.txt")))
SNIPE_LOGS = {}  # task_id -> {"user": uid, "lines": [...]}


def now_utc():
    return datetime.now(timezone.utc)


def fmt(iso_str):
    try:
        return datetime.fromisoformat(iso_str).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso_str


def random_code(length):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.SystemRandom().choice(chars) for _ in range(length))


def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()


def current_user_id():
    if session.get("is_owner"):
        return "owner"
    if session.get("key_token"):
        return "key:" + session["key_token"]
    return "user:" + session.get("username", "guest")


def current_access():
    """Returns the access dict (tier/token/expires) or None."""
    if session.get("is_owner"):
        return {"tier": "admin", "token": cfg["owner"]["key"],
                "expires": None, "unlimited": True}
    token = session.get("key_token")
    if not token:
        uname = session.get("username")
        if uname in users and users[uname].get("token"):
            token = users[uname]["token"]
    if token and token in keys:
        return keys[token]
    return None


def is_expired(access):
    if access.get("unlimited"):
        return False
    try:
        return datetime.fromisoformat(access["expires"]) < now_utc()
    except Exception:
        return True


def active_snipe_count(uid):
    return sum(1 for tid in SNIPE_LOGS
               if SNIPE_LOGS[tid]["user"] == uid and is_running(tid))


# ---------------------------------------------------------------- pages

@app.route("/")
def index():
    return render_template_string(INDEX_HTML, css=CSS,
                                  error=request.args.get("error", ""))


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if username in users and users[username]["password"] == hash_pw(password):
        session.clear()
        session["username"] = username
        return redirect(url_for("panel"))
    return redirect(url_for("index", error="Invalid username or password."))


@app.route("/signup", methods=["POST"])
def signup():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if len(username) < 3 or len(password) < 4:
        return redirect(url_for("index", error="Username (3+) and password (4+) required."))
    if username in users:
        return redirect(url_for("index", error="Username already taken."))
    users[username] = {"password": hash_pw(password), "token": None}
    save_json(USERS_PATH, users)
    session.clear()
    session["username"] = username
    return redirect(url_for("panel"))


@app.route("/key-access", methods=["POST"])
def key_access():
    token = request.form.get("token", "").strip()
    code = request.form.get("code", "").strip()

    # Owner key -> unlimited owner panel
    if token == cfg["owner"]["key"]:
        if code == cfg["owner"]["password"]:
            session.clear()
            session["is_owner"] = True
            return redirect(url_for("owner"))
        return redirect(url_for("index", error="Wrong owner password."))

    if token not in keys:
        return redirect(url_for("index", error="Unknown token."))
    entry = keys[token]
    if entry["code"] != code:
        return redirect(url_for("index", error="Wrong code password for this token."))
    if datetime.fromisoformat(entry["expires"]) < now_utc():
        return redirect(url_for("index", error="This token has expired."))

    session["key_token"] = token
    uname = session.get("username")
    if uname in users:
        users[uname]["token"] = token
        save_json(USERS_PATH, users)
    return redirect(url_for("panel"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/panel")
def panel():
    access = current_access()
    view = None
    if access:
        tier = cfg["tiers"][access["tier"]]
        view = {
            "tier": access["tier"],
            "token": access["token"],
            "expired": is_expired(access),
            "expires_str": "UNLIMITED" if access.get("unlimited") else fmt(access["expires"]),
            "tier_name": tier["name"],
            "perks": tier["perks"],
        }
    return render_template_string(PANEL_HTML, css=CSS, cfg=cfg,
                                  username=session.get("username", "guest"),
                                  access=view)


@app.route("/owner")
def owner():
    if not session.get("is_owner"):
        return redirect(url_for("index", error="Owner access only."))
    keylist = []
    for token, k in keys.items():
        keylist.append({
            "token": token,
            "code": k["code"],
            "tier": k["tier"],
            "expires_str": fmt(k["expires"]),
            "expired": datetime.fromisoformat(k["expires"]) < now_utc(),
        })
    keylist.sort(key=lambda x: x["token"])
    return render_template_string(OWNER_HTML, css=CSS, cfg=cfg,
                                  counters=cfg["counters"], keys=keylist)


# ---------------------------------------------------------------- API

@app.route("/api/generate_key", methods=["POST"])
def api_generate_key():
    if not session.get("is_owner"):
        return jsonify(ok=False, error="Owner only."), 403
    tier = request.json.get("tier", "basic")
    if tier not in cfg["tiers"]:
        return jsonify(ok=False, error="Bad tier."), 400
    t = cfg["tiers"][tier]

    cfg["counters"][tier] += 1
    token = t["prefix"] + str(cfg["counters"][tier])
    code = random_code(t["password_length"])
    expires = (now_utc() + timedelta(hours=t["duration_hours"])).isoformat()
    keys[token] = {"token": token, "code": code, "tier": tier, "expires": expires}
    save_json(CONFIG_PATH, cfg)
    save_json(KEYS_PATH, keys)
    return jsonify(ok=True, token=token, code=code, expires_at=fmt(expires))


@app.route("/api/random_code", methods=["POST"])
def api_random_code():
    if not session.get("is_owner"):
        return jsonify(ok=False, error="Owner only."), 403
    length = int(request.json.get("length", 6))
    if length not in (6, 8, 12):
        return jsonify(ok=False, error="Length must be 6, 8 or 12."), 400
    return jsonify(ok=True, code=random_code(length))


@app.route("/api/set_counter", methods=["POST"])
def api_set_counter():
    if not session.get("is_owner"):
        return jsonify(ok=False, error="Owner only."), 403
    data = request.json or {}
    for tier in ("basic", "premium", "admin"):
        val = data.get(tier)
        if isinstance(val, int) and val >= 0:
            cfg["counters"][tier] = val
    save_json(CONFIG_PATH, cfg)
    return jsonify(ok=True)


@app.route("/api/update_settings", methods=["POST"])
def api_update_settings():
    if not session.get("is_owner"):
        return jsonify(ok=False, error="Owner only."), 403
    data = request.json or {}
    if data.get("discord_invite"):
        cfg["discord_invite"] = data["discord_invite"].strip()
    if data.get("display_name"):
        cfg["owner"]["display_name"] = data["display_name"].strip()
    if data.get("owner_key"):
        cfg["owner"]["key"] = data["owner_key"].strip()
    if data.get("owner_password"):
        cfg["owner"]["password"] = data["owner_password"].strip()
    save_json(CONFIG_PATH, cfg)
    return jsonify(ok=True)


@app.route("/api/start_snipe", methods=["POST"])
def api_start_snipe():
    access = current_access()
    if not access:
        return jsonify(ok=False, message="No active license. Use KEY ACCESS first."), 403
    if is_expired(access):
        return jsonify(ok=False, message="License expired."), 403

    uid = current_user_id()
    tier_cfg = cfg["tiers"][access["tier"]]
    if active_snipe_count(uid) >= tier_cfg["slots"]:
        return jsonify(ok=False,
                       message="Slot limit reached (%s concurrent)." % tier_cfg["slots"]), 400

    target = request.form.get("username", "").strip()
    user_token = request.form.get("token", "").strip()
    if not target:
        return jsonify(ok=False, message="Target username required."), 400
    if len(target) > 32:
        return jsonify(ok=False, message="Usernames are max 32 characters."), 400

    try:
        attempts = int(request.form.get("attempts", cfg["sniper"]["max_attempts"]))
    except ValueError:
        attempts = cfg["sniper"]["max_attempts"]
    try:
        delay_min = float(request.form.get("delay_min", cfg["sniper"]["delay_min"]))
        delay_max = float(request.form.get("delay_max", cfg["sniper"]["delay_max"]))
    except ValueError:
        delay_min, delay_max = cfg["sniper"]["delay_min"], cfg["sniper"]["delay_max"]
    delay_min = max(0.1, min(delay_min, delay_max))

    if not PROXIES:
        return jsonify(ok=False, message="No proxies loaded. Check proxies.txt."), 500

    task_id = start_snipe(target, user_token, attempts, delay_min, delay_max,
                          PROXIES, lambda line: SNIPE_LOGS[task_id]["lines"].append(line))
    SNIPE_LOGS[task_id] = {"user": uid, "lines": []}
    return jsonify(ok=True, task_id=task_id,
                   message="Sniper started on %s via proxy pool." % target)


@app.route("/api/sniper_log")
def api_sniper_log():
    task = request.args.get("task", "")
    if task not in SNIPE_LOGS:
        return jsonify(ok=False, lines=[])
    return jsonify(ok=True, running=is_running(task),
                   lines=SNIPE_LOGS[task]["lines"])


# ---------------------------------------------------------------- embedded assets

CSS = """
:root{--bg:#0b0e14;--card:#131722;--accent:#5865f2;--green:#2ecc71;--red:#e74c3c;--gold:#f1c40f}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:#e8eaf0;font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
.wrap{max-width:960px;margin:0 auto;padding:30px 16px}
h1{font-size:1.6rem;margin-bottom:4px}
.sub{color:#8b93a7;font-size:.9rem;margin-bottom:24px}
.card{background:var(--card);border:1px solid #232a3b;border-radius:12px;padding:24px;margin-bottom:20px}
.tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.tab{padding:10px 18px;background:var(--card);border:1px solid #232a3b;border-radius:8px;cursor:pointer;color:#8b93a7;font-weight:600}
.tab.active{color:#fff;border-color:var(--accent);background:#1b2133}
label{display:block;font-size:.85rem;color:#8b93a7;margin:12px 0 6px}
input,select,textarea{width:100%;padding:11px 12px;background:#0d1119;border:1px solid #2a3246;border-radius:8px;color:#fff;font-size:.95rem}
input:focus{outline:none;border-color:var(--accent)}
button{padding:11px 18px;border:none;border-radius:8px;background:var(--accent);color:#fff;font-weight:700;cursor:pointer;font-size:.9rem}
button:hover{filter:brightness(1.15)}
button.green{background:var(--green)}
button.red{background:var(--red)}
button.gold{background:var(--gold);color:#111}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th,td{padding:10px 8px;text-align:left;border-bottom:1px solid #232a3b}
th{color:#8b93a7;font-weight:600}
.badge{padding:3px 10px;border-radius:20px;font-size:.72rem;font-weight:700}
.badge.basic{background:#3b4252;color:#c9d1e0}
.badge.premium{background:#5c3a00;color:#ffd479}
.badge.admin{background:#7a1f1f;color:#ffb3b3}
.log{background:#0d1119;border:1px solid #232a3b;border-radius:8px;padding:12px;height:220px;overflow-y:auto;font-family:monospace;font-size:.8rem;white-space:pre-wrap}
.msg{color:var(--green);font-weight:600;margin-top:14px}
.err{color:var(--red);font-weight:600;margin-top:14px}
code{background:#0d1119;padding:2px 8px;border-radius:5px;font-size:.9rem;word-break:break-all}
a{color:#8ab4ff}
"""

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Z0F1LD | Login</title>
<style>{{ css }}</style>
</head>
<body>
<div class="wrap" style="max-width:460px">
  <h1>Z0F1LD <span style="color:#5865f2">SNIPER</span></h1>
  <p class="sub">Username sniper — owned by <b>zofildoterr</b></p>

  <div class="tabs">
    <div class="tab active" data-tab="login">LOGIN</div>
    <div class="tab" data-tab="signup">SIGNUP</div>
    <div class="tab" data-tab="key">KEY ACCESS</div>
  </div>

  {% if error %}<p class="err">{{ error }}</p>{% endif %}

  <div class="card tab-page" id="page-login">
    <form method="POST" action="/login">
      <label>Username</label>
      <input type="text" name="username" required autocomplete="username">
      <label>Password</label>
      <input type="password" name="password" required autocomplete="current-password">
      <div style="margin-top:18px"><button type="submit">LOGIN</button></div>
    </form>
  </div>

  <div class="card tab-page" id="page-signup" style="display:none">
    <form method="POST" action="/signup">
      <label>Username</label>
      <input type="text" name="username" required minlength="3">
      <label>Password</label>
      <input type="password" name="password" required minlength="4">
      <p class="sub" style="margin-top:10px">Accounts are for tracking your access.
         To get sniper time you still need a <b>token + code</b>.</p>
      <div style="margin-top:18px"><button type="submit">CREATE ACCOUNT</button></div>
    </form>
  </div>

  <div class="card tab-page" id="page-key" style="display:none">
    <form method="POST" action="/key-access">
      <label>License Token (letters + numbers)</label>
      <input type="text" name="token" required placeholder="3DDDDLOOOOLLLARRRR1">
      <label>Code Password (6/8/12 chars)</label>
      <input type="text" name="code" required>
      <p class="sub" style="margin-top:10px">Owner? Use <code>Z0F1LD0TERRRR11111</code> +
         your owner password.</p>
      <div style="margin-top:18px"><button type="submit" class="green">UNLOCK ACCESS</button></div>
    </form>
  </div>
</div>

<script>
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab-page').forEach(x => x.style.display = 'none');
    t.classList.add('active');
    document.getElementById('page-' + t.dataset.tab).style.display = 'block';
  });
});
</script>
</body>
</html>
"""

PANEL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sniper Panel — {{ username }}</title>
<style>{{ css }}</style>
</head>
<body>
<div class="wrap">
  <div class="row" style="justify-content:space-between">
    <div>
      <h1>SNIPER PANEL</h1>
      <p class="sub">Logged in as <b>{{ username }}</b> · owned by <b>zofildoterr</b></p>
    </div>
    <div class="row">
      <a href="{{ cfg['discord_invite'] }}" target="_blank"><button class="gold">DISCORD</button></a>
      <a href="/logout"><button class="red">LOGOUT</button></a>
    </div>
  </div>

  {% if access %}
  <div class="card">
    <div class="row" style="justify-content:space-between">
      <div>
        <span class="badge {{ access.tier }}">{{ access.tier_name }}</span>
        <span style="margin-left:8px">Token: <code>{{ access.token }}</code></span>
      </div>
      <b style="color:{{ 'var(--red)' if access.expired else 'var(--green)' }}">
        {{ 'EXPIRED' if access.expired else 'Expires: ' + access.expires_str }}
      </b>
    </div>
    <ul style="margin:14px 0 0 18px;color:#8b93a7;font-size:.9rem">
      {% for p in access.perks %}<li style="margin:3px 0">{{ p }}</li>{% endfor %}
    </ul>
  </div>

  {% if not access.expired %}
  <div class="card">
    <h3 style="margin-bottom:6px">SNIPE A USERNAME</h3>
    <p class="sub">Watch a username and claim it the instant it frees up. Traffic is routed
       through the rotating proxy pool.</p>
    <form id="snipeForm">
      <label>Target Username</label>
      <input type="text" name="username" required placeholder="rare_name">
      <label>Discord User Token (optional — speeds up claim)</label>
      <input type="password" name="token" placeholder="••••••••••••••••">
      <div class="row" style="margin-top:12px">
        <div style="flex:1;min-width:140px">
          <label>Min delay (s)</label>
          <input type="number" step="0.1" name="delay_min" value="{{ cfg['sniper']['delay_min'] }}">
        </div>
        <div style="flex:1;min-width:140px">
          <label>Max delay (s)</label>
          <input type="number" step="0.1" name="delay_max" value="{{ cfg['sniper']['delay_max'] }}">
        </div>
        <div style="flex:1;min-width:140px">
          <label>Max attempts</label>
          <input type="number" name="attempts" value="{{ cfg['sniper']['max_attempts'] }}">
        </div>
      </div>
      <div style="margin-top:16px"><button type="submit" class="green">START SNIPER</button></div>
    </form>
    <p class="msg" id="snipeMsg" style="display:none"></p>
  </div>

  <div class="card">
    <h3 style="margin-bottom:6px">LIVE LOG</h3>
    <div class="log" id="log">Waiting for a snipe task…</div>
  </div>
  {% endif %}

  {% else %}
  <div class="card">
    <p class="err">You have no active access. Buy a token + code from the owner, then
       <a href="/logout">log out</a> and use the <b>KEY ACCESS</b> tab.</p>
  </div>
  {% endif %}
</div>

{% if access and not access.expired %}
<script>
let activeTask = null;

document.getElementById('snipeForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const res = await fetch('/api/start_snipe', {method:'POST', body: new URLSearchParams(fd)});
  const data = await res.json();
  const msg = document.getElementById('snipeMsg');
  msg.style.display = 'block';
  msg.className = data.ok ? 'msg' : 'err';
  msg.textContent = data.message;
  if (data.ok) {
    activeTask = data.task_id;
    document.getElementById('log').textContent = 'Task started…';
    pollLog();
  }
});

async function pollLog() {
  if (!activeTask) return;
  try {
    const res = await fetch('/api/sniper_log?task=' + encodeURIComponent(activeTask));
    const data = await res.json();
    if (data.lines && data.lines.length) {
      document.getElementById('log').textContent = data.lines.join('\\n');
      document.getElementById('log').scrollTop = document.getElementById('log').scrollHeight;
    }
  } catch (e) {}
  setTimeout(pollLog, 1500);
}
</script>
{% endif %}
</body>
</html>
"""

OWNER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Owner Panel — {{ cfg.owner.display_name }}</title>
<style>{{ css }}</style>
</head>
<body>
<div class="wrap" style="max-width:1100px">
  <div class="row" style="justify-content:space-between">
    <div>
      <h1>OWNER PANEL <span style="color:#f1c40f">★</span></h1>
      <p class="sub">Welcome, <b>{{ cfg.owner.display_name }}</b> — unlimited access, full control.</p>
    </div>
    <div class="row">
      <a href="{{ cfg['discord_invite'] }}" target="_blank"><button class="gold">DISCORD</button></a>
      <a href="/logout"><button class="red">LOGOUT</button></a>
    </div>
  </div>

  <div class="card">
    <h3>GENERATE LICENSE KEY</h3>
    <p class="sub">Each key = a letter+number token + a randomly generated code password
       (6 chars = $3, 8 chars = $5, 12 chars = $10). Access time is limited per tier.</p>
    <form id="genForm">
      <label>Tier</label>
      <select name="tier" id="tierSelect">
        <option value="basic">$3 — {{ cfg.tiers.basic.name }} (next: {{ cfg.tiers.basic.prefix }}{{ counters.basic + 1 }})</option>
        <option value="premium">$5 — {{ cfg.tiers.premium.name }} (next: {{ cfg.tiers.premium.prefix }}{{ counters.premium + 1 }})</option>
        <option value="admin">$10 — {{ cfg.tiers.admin.name }} (next: {{ cfg.tiers.admin.prefix }}{{ counters.admin + 1 }})</option>
      </select>
      <div style="margin-top:16px" class="row">
        <button type="submit" class="green">GENERATE +1</button>
        <button type="button" id="code6" class="gold">RANDOM 6-CHAR CODE</button>
        <button type="button" id="code8" class="gold">RANDOM 8-CHAR CODE</button>
        <button type="button" id="code12" class="gold">RANDOM 12-CHAR CODE</button>
      </div>
    </form>
    <p class="msg" id="genMsg" style="display:none"></p>
  </div>

  <div class="card">
    <h3>TOKEN COUNTERS</h3>
    <p class="sub">Change the next number for a tier. E.g. set $3 to 2 and the next key is
       <code>3DDDDLOOOOLLLARRRR2</code>. Owner key is unlimited and never expires.</p>
    <div class="row" style="align-items:flex-end">
      <div style="flex:1;min-width:150px">
        <label>$3 counter (basic)</label>
        <input type="number" id="c_basic" value="{{ counters.basic }}" min="0">
      </div>
      <div style="flex:1;min-width:150px">
        <label>$5 counter (premium)</label>
        <input type="number" id="c_premium" value="{{ counters.premium }}" min="0">
      </div>
      <div style="flex:1;min-width:150px">
        <label>$10 counter (admin)</label>
        <input type="number" id="c_admin" value="{{ counters.admin }}" min="0">
      </div>
      <button id="saveCounters" class="green">SAVE</button>
    </div>
    <p class="msg" id="counterMsg" style="display:none"></p>
  </div>

  <div class="card">
    <h3>SETTINGS</h3>
    <form id="settingsForm">
      <label>Discord Invite Link (shown to all buyers)</label>
      <input type="text" name="discord_invite" value="{{ cfg['discord_invite'] }}">
      <label>Owner Display Name (shown in header)</label>
      <input type="text" name="display_name" value="{{ cfg.owner.display_name }}">
      <label>Owner Key (unlimited access)</label>
      <input type="text" name="owner_key" value="{{ cfg.owner.key }}">
      <label>Owner Password</label>
      <input type="text" name="owner_password" value="{{ cfg.owner.password }}">
      <div style="margin-top:16px"><button type="submit" class="green">SAVE SETTINGS</button></div>
    </form>
    <p class="msg" id="settingsMsg" style="display:none"></p>
  </div>

  <div class="card">
    <h3>ISSUED KEYS ({{ keys|length }})</h3>
    <div style="overflow-x:auto">
    <table>
      <tr><th>Token</th><th>Code</th><th>Tier</th><th>Expires (UTC)</th><th>Status</th></tr>
      {% for k in keys|reverse %}
      <tr>
        <td><code>{{ k.token }}</code></td>
        <td><code>{{ k.code }}</code></td>
        <td><span class="badge {{ k.tier }}">{{ k.tier|upper }}</span></td>
        <td>{{ k.expires_str }}</td>
        <td style="color:{{ 'var(--red)' if k.expired else 'var(--green)' }}">{{ 'EXPIRED' if k.expired else 'ACTIVE' }}</td>
      </tr>
      {% endfor %}
    </table>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);

$('genForm').addEventListener('submit', async e => {
  e.preventDefault();
  const res = await fetch('/api/generate_key', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({tier: $('tierSelect').value})});
  const d = await res.json();
  const m = $('genMsg');
  m.style.display = 'block';
  m.className = d.ok ? 'msg' : 'err';
  m.textContent = d.ok ? 'KEY READY → Token: ' + d.token + '  |  Code: ' + d.code + '  |  Expires: ' + d.expires_at : d.error;
  if (d.ok) setTimeout(() => location.reload(), 2500);
});

[['code6',6],['code8',8],['code12',12]].forEach(pair => {
  $(pair[0]).addEventListener('click', async () => {
    const res = await fetch('/api/random_code', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({length: pair[1]})});
    const d = await res.json();
    const m = $('genMsg');
    m.style.display = 'block';
    m.className = d.ok ? 'msg' : 'err';
    m.textContent = d.ok ? 'Random ' + pair[1] + '-char code: ' + d.code +
      '  (password for the next ' + (pair[1] === 6 ? '$3' : pair[1] === 8 ? '$5' : '$10') + ' token)' : d.error;
  });
});

$('saveCounters').addEventListener('click', async () => {
  const res = await fetch('/api/set_counter', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      basic: parseInt($('c_basic').value) || 0,
      premium: parseInt($('c_premium').value) || 0,
      admin: parseInt($('c_admin').value) || 0
    })});
  const d = await res.json();
  const m = $('counterMsg');
  m.style.display = 'block';
  m.className = d.ok ? 'msg' : 'err';
  m.textContent = d.ok ? 'Counters updated.' : d.error;
  if (d.ok) setTimeout(() => location.reload(), 1500);
});

$('settingsForm').addEventListener('submit', async e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const res = await fetch('/api/update_settings', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(Object.fromEntries(fd))});
  const d = await res.json();
  const m = $('settingsMsg');
  m.style.display = 'block';
  m.className = d.ok ? 'msg' : 'err';
  m.textContent = d.ok ? 'Settings saved.' : d.error;
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print("=" * 50)
    print(" Z0F1LD SNIPER — owner: zofildoterr")
    print(" Owner key : %s" % cfg["owner"]["key"])
    print(" Panel     : http://127.0.0.1:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
