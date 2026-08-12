"""
zofild-sniper — Discord username sniper core.
Routes every attempt through the rotating proxy pool.
"""
import random
import threading
import time
import uuid

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
            return [line.strip() for line in fh if line.strip() and ":" in line]
    except FileNotFoundError:
        return []


def _proxy_dict(proxy_str):
    return {"http": "http://" + proxy_str, "https": "http://" + proxy_str}


def _attempt(target, user_token, proxies, log):
    proxy = _proxy_dict(random.choice(proxies))
    log("proxy=" + proxy["http"].split("//")[1])

    if not user_token:
        # No token -> can only verify the proxy path, cannot claim.
        try:
            r = requests.get(
                DISCORD_API + "/users/@me",
                headers={"Authorization": "invalid", "User-Agent": USER_AGENT},
                proxies=proxy, timeout=15,
            )
            if r.status_code in (401, 403):
                log("[i] no user token -> monitoring only, cannot claim")
            else:
                log("[i] proxy responded with %s" % r.status_code)
        except requests.RequestException as exc:
            log("[!] proxy error: %s" % exc)
        return False

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


def _run(task_id, target, user_token, attempts, delay_min, delay_max, proxies, log):
    entry = _REGISTRY[task_id]
    entry["running"] = True
    log("target: %s" % target)
    log("attempts: %s | delay: %s-%ss | proxies: %s" % (attempts, delay_min, delay_max, len(proxies)))
    if not user_token:
        log("[!] no Discord user token provided - monitoring only, cannot claim")

    for i in range(1, attempts + 1):
        with _REGISTRY_LOCK:
            if _REGISTRY[task_id]["stop"]:
                log("stopped by user")
                break
        log("--- attempt %s/%s" % (i, attempts))
        if _attempt(target, user_token, proxies, log):
            log("[+] TARGET CLAIMED")
            break
        time.sleep(random.uniform(delay_min, delay_max))
    else:
        log("attempts exhausted - target still unavailable")

    entry["running"] = False


def start_snipe(target, user_token, attempts, delay_min, delay_max, proxies, log):
    task_id = uuid.uuid4().hex[:12]
    with _REGISTRY_LOCK:
        _REGISTRY[task_id] = {"running": False, "stop": False}
    threading.Thread(
        target=_run,
        args=(task_id, target, user_token, attempts, delay_min, delay_max, proxies, log),
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
