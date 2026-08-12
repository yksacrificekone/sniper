"""
zadenxx — multi-platform username sniper core.
Platforms : discord (auto-claim + probe), roblox (auto-claim + probe),
            tiktok (probe + best-effort claim)
Every request rotates through the proxy pool.
Hits / successes are pushed to the buyer's Discord webhook.
"""
import json
import random
import threading
import time
import uuid
from datetime import datetime, timezone

import requests

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


def send_webhook(url, platform, target, task_id, event, detail=""):
    """Push an embed to the buyer's webhook (sent directly, not via proxy pool)."""
    if not url or not url.startswith("http"):
        return
    payload = {
        "username": "zadenxx Sniper",
        "embeds": [{
            "title": event,
            "color": 0x00FF9D if ("HIT" in event or "SUCCESS" in event) else 0x7C5CFF,
            "fields": [
                {"name": "Platform", "value": platform.upper(), "inline": True},
                {"name": "Target", "value": target, "inline": True},
                {"name": "Task", "value": task_id, "inline": True},
                {"name": "Detail", "value": detail or "-", "inline": False},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "zofildoterr · zadenxx"},
        }]
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except requests.RequestException:
        pass


# ================================================================ DISCORD

def _discord_claim(target, user_token, proxies, log):
    proxy = _proxy_dict(random.choice(proxies))
    log("proxy=" + proxy["http"].split("//")[1])
    headers = {
        "Authorization": user_token,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    try:
        r = requests.patch("https://discord.com/api/v9/users/@me",
                           json={"username": target},
                           headers=headers, proxies=proxy, timeout=15)
    except requests.RequestException as exc:
        log("[!] request failed: %s" % exc)
        return False
    if r.status_code == 200:
        log("[+] DISCORD: username claimed!")
        return True
    if r.status_code == 429:
        log("[!] DISCORD: rate limited (429)")
        return False
    if r.status_code == 400:
        try:
            errs = (r.json().get("errors", {}).get("username", {})
                     .get("_errors", [{}])[0].get("message", "not available"))
        except Exception:
            errs = "not available"
        log("[-] DISCORD: %s" % errs)
        return False
    log("[-] DISCORD: status %s" % r.status_code)
    return False


def _discord_probe(target, proxies, log):
    """Tokenless availability check via the register gate."""
    proxy = _proxy_dict(random.choice(proxies))
    fingerprint = ""
    try:
        r = requests.get("https://discord.com/api/v9/experiments",
                         headers={"User-Agent": USER_AGENT},
                         proxies=proxy, timeout=10)
        if r.status_code == 200:
            fingerprint = r.json().get("fingerprint") or ""
    except Exception:
        pass
    try:
        r = requests.post(
            "https://discord.com/api/v9/auth/register",
            json={"username": target, "consent": True, "fingerprint": fingerprint},
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
            proxies=proxy, timeout=10)
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
        log("[probe] %s looks AVAILABLE" % target)
        return True
    log("[probe] unknown response %s" % r.status_code)
    return None


# ================================================================ ROBLOX

def _roblox_csrf(cookie, proxies, log):
    proxy = _proxy_dict(random.choice(proxies))
    try:
        r = requests.get("https://auth.roblox.com/v2/username",
                         headers={"User-Agent": USER_AGENT,
                                  "Cookie": ".ROBLOSECURITY=" + cookie},
                         proxies=proxy, timeout=10)
        return r.headers.get("x-csrf-token")
    except requests.RequestException as exc:
        log("[!] roblox csrf failed: %s" % exc)
        return None


def _roblox_claim(target, cookie, proxies, log):
    if not cookie:
        return False
    csrf = _roblox_csrf(cookie, proxies, log)
    if not csrf:
        log("[!] ROBLOX: could not get CSRF token (bad cookie?)")
        return False
    proxy = _proxy_dict(random.choice(proxies))
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "X-CSRF-TOKEN": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.roblox.com",
        "Referer": "https://www.roblox.com/",
        "Cookie": ".ROBLOSECURITY=" + cookie,
    }
    try:
        r = requests.post("https://auth.roblox.com/v2/username",
                          json={"username": target},
                          headers=headers, proxies=proxy, timeout=15)
    except requests.RequestException as exc:
        log("[!] roblox request failed: %s" % exc)
        return False
    if r.status_code == 200:
        log("[+] ROBLOX: username claimed!")
        return True
    if r.status_code == 429:
        log("[!] ROBLOX: rate limited (429)")
        return False
    if r.status_code == 403:
        log("[!] ROBLOX: CSRF rejected")
        return False
    if r.status_code == 400:
        try:
            message = r.json()["errors"][0].get("message", "not available")
        except Exception:
            message = "not available"
        log("[-] ROBLOX: %s" % message)
        return False
    log("[-] ROBLOX: status %s" % r.status_code)
    return False


def _roblox_probe(target, proxies, log):
    """Tokenless availability check via the users API."""
    proxy = _proxy_dict(random.choice(proxies))
    try:
        r = requests.post("https://users.roblox.com/v1/usernames/users",
                          json={"usernames": [target], "excludeBannedUsers": True},
                          headers={"User-Agent": USER_AGENT},
                          proxies=proxy, timeout=10)
    except requests.RequestException as exc:
        log("[probe] error: %s" % exc)
        return None
    if r.status_code == 200:
        data = r.json().get("data") or []
        if data:
            log("[probe] %s is taken" % target)
            return False
        log("[probe] %s looks AVAILABLE" % target)
        return True
    log("[probe] roblox status %s" % r.status_code)
    return None


# ================================================================ TIKTOK

def _tiktok_claim(target, sessionid, proxies, log):
    """Best-effort claim. TikTok requires X-Bogus/msToken signatures for
    real claims — if this 403s, the hit is still valid and the buyer claims
    manually in the app."""
    if not sessionid:
        return False
    proxy = _proxy_dict(random.choice(proxies))
    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": "sessionid=" + sessionid,
        "Referer": "https://www.tiktok.com/",
    }
    try:
        r = requests.post("https://www.tiktok.com/api/setting/user/",
                          data={"unique_id": target, "user_language": "en"},
                          headers=headers, proxies=proxy, timeout=15)
    except requests.RequestException as exc:
        log("[!] tiktok request failed: %s" % exc)
        return False
    try:
        body = r.json()
        if body.get("status_code") == 0:
            log("[+] TIKTOK: username claimed!")
            return True
        log("[-] TIKTOK: %s" % json.dumps(body)[:200])
    except Exception:
        log("[-] TIKTOK: status %s" % r.status_code)
    return False


def _tiktok_probe(target, proxies, log):
    """Tokenless availability check: profile page 404 = username free."""
    proxy = _proxy_dict(random.choice(proxies))
    try:
        r = requests.get("https://www.tiktok.com/@%s" % target,
                         headers={"User-Agent": USER_AGENT,
                                  "Accept-Language": "en-US,en;q=0.9"},
                         proxies=proxy, timeout=12, allow_redirects=True)
    except requests.RequestException as exc:
        log("[probe] error: %s" % exc)
        return None
    if r.status_code == 404:
        log("[probe] %s looks AVAILABLE (profile gone)" % target)
        return True
    if r.status_code == 200:
        log("[probe] %s is taken" % target)
        return False
    log("[probe] tiktok status %s" % r.status_code)
    return None


# ================================================================ LOOP

PLATFORMS = {
    "discord": {"claim": _discord_claim, "probe": _discord_probe},
    "roblox":  {"claim": _roblox_claim,  "probe": _roblox_probe},
    "tiktok":  {"claim": _tiktok_claim,  "probe": _tiktok_probe},
}


def _run(task_id, platform, target, auth, webhook, attempts,
         delay_min, delay_max, proxies, log):
    entry = _REGISTRY[task_id]
    entry["running"] = True
    handlers = PLATFORMS[platform]

    log("platform: %s | target: %s" % (platform.upper(), target))
    log("attempts: %s | delay: %s-%ss | proxies: %s"
        % (attempts, delay_min, delay_max, len(proxies)))
    if webhook:
        log("webhook: %s" % webhook)
        send_webhook(webhook, platform, target, task_id, "SNIPER STARTED",
                     "monitoring %s"
                     % ("with token (auto-claim)" if auth else "probe mode (manual claim)"))
    if not auth:
        log("[!] no token/cookie - probe mode: hits are pushed to the webhook")
    if platform == "tiktok" and auth:
        log("[!] tiktok claim may need X-Bogus signature - if it fails, claim manually")

    for i in range(1, attempts + 1):
        with _REGISTRY_LOCK:
            if _REGISTRY[task_id]["stop"]:
                log("stopped by user")
                break
        log("--- attempt %s/%s" % (i, attempts))

        if auth:
            if handlers["claim"](target, auth, proxies, log):
                log("[+] TARGET CLAIMED")
                send_webhook(webhook, platform, target, task_id,
                             "SUCCESS - TARGET CLAIMED", "claimed via proxy pool")
                break
        else:
            hit = handlers["probe"](target, proxies, log)
            if hit is True:
                log("[+] HIT - username looks available")
                send_webhook(webhook, platform, target, task_id,
                             "HIT - username looks available",
                             "claim it manually right now")
                break
            if hit is None:
                time.sleep(random.uniform(delay_min, delay_max))
                continue

        time.sleep(random.uniform(delay_min, delay_max))
    else:
        log("attempts exhausted - target still unavailable")
        send_webhook(webhook, platform, target, task_id, "SNIPER FINISHED",
                     "attempts exhausted, no hit")

    entry["running"] = False


def start_snipe(platform, target, auth, webhook, attempts,
                delay_min, delay_max, proxies, log):
    task_id = uuid.uuid4().hex[:12]
    with _REGISTRY_LOCK:
        _REGISTRY[task_id] = {"running": False, "stop": False}
    threading.Thread(
        target=_run,
        args=(task_id, platform, target, auth, webhook, attempts,
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
