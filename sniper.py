"""
zofild-sniper — Discord username sniper core.
Rotates the proxy pool on every request.
Pushes HIT / SUCCESS notifications to a Discord webhook.
"""
import json
import random
import threading
import time
import uuid
from datetime import datetime, timezone

import requests

DISCORD_API = "https://discord.com/api/v9"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")

_REGISTRY = {}
_REGISTRY_LOCK = threading.Lock()


def load_proxies(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return [ln.strip() for ln in fh if ln.strip() and ":" in ln]
    except FileNotFoundError:
        return []


def _proxy_dict(proxy_str):
    return {"http": "http://" + proxy_str, "https": "http://" + proxy_str}


def send_webhook(url, target, task_id, event, detail=""):
    """Push an embed to the buyer's Discord webhook (sent directly, not via proxy pool)."""
    if not url or not url.startswith("http"):
        return
    payload = {
        "username": "Z0F1LD Sniper",
        "embeds": [{
            "title": event,
            "color": 0x2ECC71 if ("HIT" in event or "SUCCESS" in event) else 0x5865F2,
            "fields": [
                {"name": "Target", "value": target, "inline": True},
                {"name": "Task", "value": task_id, "inline": True},
                {"name": "Detail", "value": detail or "-", "inline": False},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "zofildoterr · Z0F1LD Sniper"},
        }]
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except requests.RequestException:
        pass


def _attempt(target, user_token, proxies, log):
    proxy = _proxy_dict(random.choice(proxies))
    log("proxy=" + proxy["http"].split("//")[1])
    headers = {
        "Authorization": user_token,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    try:
        r = requests.patch(
            DISCORD_API + "/users/@me",
            json={"username": target},
            headers=headers,
            proxies=proxy,
            timeout=15,
        )
    except requests.RequestException as exc:
        log("[!] request failed: %s" % exc)
        return False

    if r.status_code == 200:
        log("[+] SUCCESS: username claimed!")
        return True
    if r.status_code == 429:
        log("[!] rate limited (429) - backing off")
        return False
    if r.status_code == 400:
        try:
            errs = (r.json().get("errors", {})
                     .get("username", {})
                     .get("_errors", [{}])[0]
                     .get("message", "username not available"))
        except Exception:
            errs = "username not available"
        log("[-] %s" % errs)
        return False
    log("[-] unexpected status %s" % r.status_code)
    return False


def _probe_available(target, proxies, log):
    """Best-effort availability check WITHOUT a user token.

    Uses the register gate: if Discord answers with a username error the name is
    taken; if it answers with captcha/registration gates the name is likely free.
    Returns True (available), False (taken) or None (inconclusive).
    """
    proxy = _proxy_dict(random.choice(proxies))
    fingerprint = ""
    try:
        r = requests.get(DISCORD_API + "/experiments",
                         headers={"User-Agent": USER_AGENT},
                         proxies=proxy, timeout=10)
        if r.status_code == 200:
            fingerprint = r.json().get("fingerprint") or ""
    except Exception:
        pass

    try:
        r = requests.post(
            DISCORD_API + "/auth/register",
            json={"username": target, "consent": True, "fingerprint": fingerprint},
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            proxies=proxy, timeout=10,
        )
    except requests.RequestException as exc:
        log("[probe] error: %s" % exc)
        return None

    if r.status_code == 429:
        log("[probe] rate limited")
        return None

    try:
        body = r.json()
    except Exception:
        body = {}

    msg = json.dumps(body).lower()
    if "not available" in msg:
        log("[probe] %s is taken" % target)
        return False
    if body.get("captcha_required") or body.get("captcha_key") or r.status_code == 400:
        log("[probe] %s looks AVAILABLE (captcha/registration gate)" % target)
        return True
    log("[probe] unknown response %s: %s" % (r.status_code, msg[:120]))
    return None


def _run(task_id, target, user_token, webhook, attempts,
         delay_min, delay_max, proxies, log):
    entry = _REGISTRY[task_id]
    entry["running"] = True
    log("target: %s" % target)
    log("attempts: %s | delay: %s-%ss | proxies: %s"
        % (attempts, delay_min, delay_max, len(proxies)))
    if webhook:
        log("webhook: %s" % webhook)
        send_webhook(webhook, target, task_id, "SNIPER STARTED",
                     "monitoring %s"
                     % ("with token (auto-claim)" if user_token else "probe mode (manual claim)"))
    if not user_token:
        log("[!] no user token - probe mode: hits are pushed to the webhook, buyer claims manually")

    for i in range(1, attempts + 1):
        with _REGISTRY_LOCK:
            if _REGISTRY[task_id]["stop"]:
                log("stopped by user")
                break
        log("--- attempt %s/%s" % (i, attempts))

        if user_token:
            if _attempt(target, user_token, proxies, log):
                log("[+] TARGET CLAIMED")
                send_webhook(webhook, target, task_id, "SUCCESS - TARGET CLAIMED",
                             "claimed through the proxy pool")
                break
        else:
            hit = _probe_available(target, proxies, log)
            if hit is True:
                log("[+] HIT - username looks available")
                send_webhook(webhook, target, task_id,
                             "HIT - username looks available",
                             "no token on this task - claim it manually right now")
                break
            if hit is None:
                time.sleep(random.uniform(delay_min, delay_max))
                continue

        time.sleep(random.uniform(delay_min, delay_max))
    else:
        log("attempts exhausted - target still unavailable")
        send_webhook(webhook, target, task_id, "SNIPER FINISHED",
                     "attempts exhausted, no hit")

    entry["running"] = False


def start_snipe(target, user_token, webhook, attempts,
                delay_min, delay_max, proxies, log):
    task_id = uuid.uuid4().hex[:12]
    with _REGISTRY_LOCK:
        _REGISTRY[task_id] = {"running": False, "stop": False}
    threading.Thread(
        target=_run,
        args=(task_id, target, user_token, webhook, attempts,
              delay_min, delay_max, proxies, log),
        daemon=True,
    ).start()
    return task_id


def stop_snipe(task_id):
    with _REGISTRY_LOCK:
        if task_id in _REGISTRY:
            _REGISTRY[task_id]["stop"] = True


def is_running(task_id):
    entry = _REGISTRY.get(task_id)
    return bool(entry and entry["running"])
